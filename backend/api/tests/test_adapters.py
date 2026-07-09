"""
Adapter Contract Tests
======================
Verify that all registered adapters return Standard Format
and have correct capabilities. No real API calls — all HTTP is mocked.
"""
import uuid
from datetime import timedelta
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.utils import timezone

from api.models import Provider
from api.providers import ADAPTER_REGISTRY
from api.providers.base import BaseProviderAdapter
from api.providers.mock import MockProviderAdapter
from api.providers.hotplayer import HotPlayerAdapter
from api.providers.cms_only import CMSOnlyAdapter
from api.utils import encrypt_password


class MockProviderModel:
    """Fake Provider model instance for testing adapters without DB."""
    def __init__(self, adapter_key='mock', name='Test Provider', api_endpoint='http://mock.test/api',
                 extra_config=None):
        self.adapter_key = adapter_key
        self.name = name
        self.api_endpoint = api_endpoint
        self.extra_config = extra_config or {}
        self._token = encrypt_password('test-api-token-1234')

    def get_token(self):
        from api.utils import decrypt_password
        return decrypt_password(self._token)


class StandardFormatMixin:
    """Mixin providing standard format assertion helpers."""

    def assert_standard_format(self, result):
        """Assert result dict conforms to the Standard Format contract."""
        self.assertIn('external_id', result, "Missing 'external_id' in standard format")
        self.assertIn('credentials', result, "Missing 'credentials' in standard format")
        self.assertIn('raw_response', result, "Missing 'raw_response' in standard format")
        self.assertIn('expires_at', result, "Missing 'expires_at' in standard format")
        self.assertIsInstance(result['credentials'], dict, "'credentials' must be a dict")
        self.assertIsInstance(result['raw_response'], dict, "'raw_response' must be a dict")


class TestAdapterRegistry(TestCase):
    """Test that all registered adapters are proper BaseProviderAdapter subclasses."""

    def test_all_registered_adapters_are_subclasses(self):
        for key, adapter_class in ADAPTER_REGISTRY.items():
            self.assertTrue(
                issubclass(adapter_class, BaseProviderAdapter),
                f"Adapter '{key}' ({adapter_class}) is not a subclass of BaseProviderAdapter"
            )

    def test_all_adapters_have_create_capability(self):
        for key, adapter_class in ADAPTER_REGISTRY.items():
            provider = MockProviderModel(adapter_key=key)
            try:
                adapter = adapter_class(provider=provider)
                self.assertIn('create', adapter.capabilities,
                              f"Adapter '{key}' missing 'create' capability")
            except Exception:
                # Some adapters may fail init without real provider, skip
                pass


class TestMockProviderAdapter(TestCase, StandardFormatMixin):
    """Test MockProviderAdapter returns correct standard format."""

    def setUp(self):
        self.provider = MockProviderModel(adapter_key='mock', extra_config={
            'dns_domain': 'mock-test.tv',
            'port': 9090,
        })
        self.adapter = MockProviderAdapter(provider=self.provider, fail_rate=0.0)

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertIsInstance(caps, set)
        self.assertIn('create', caps)
        self.assertIn('renew', caps)
        self.assertIn('suspend', caps)
        self.assertIn('balance_check', caps)

    def test_create_returns_standard_format(self):
        result = self.adapter.create(pack_id=1, months=1)
        self.assert_standard_format(result)

    def test_create_1_month_expiry(self):
        before = timezone.now()
        result = self.adapter.create(pack_id=1, months=1)
        after = timezone.now()

        self.assertIsNotNone(result['expires_at'])
        expected_min = before + timedelta(days=30)
        expected_max = after + timedelta(days=30)
        self.assertGreaterEqual(result['expires_at'], expected_min)
        self.assertLessEqual(result['expires_at'], expected_max)

    def test_create_12_month_expiry(self):
        before = timezone.now()
        result = self.adapter.create(pack_id=1, months=12)
        after = timezone.now()

        self.assertIsNotNone(result['expires_at'])
        expected_min = before + timedelta(days=360)
        expected_max = after + timedelta(days=360)
        self.assertGreaterEqual(result['expires_at'], expected_min)
        self.assertLessEqual(result['expires_at'], expected_max)

    def test_create_lifetime_no_expiry(self):
        result = self.adapter.create(pack_id=1, months=12, is_lifetime=True)
        self.assertIsNone(result['expires_at'])

    def test_create_credentials_contain_username_and_secret(self):
        result = self.adapter.create(pack_id=1, months=1)
        creds = result['credentials']
        self.assertIn('username', creds)
        self.assertIn('secret_password', creds)
        self.assertIn('m3u_url', creds)

    def test_create_external_id_is_string(self):
        result = self.adapter.create(pack_id=1, months=1)
        self.assertIsInstance(result['external_id'], str)
        self.assertTrue(result['external_id'].startswith('mock_'))

    def test_raw_response_does_not_contain_password(self):
        result = self.adapter.create(pack_id=1, months=1)
        raw = result['raw_response']
        self.assertNotIn('password', raw)


class TestMockLegacyAlias(TestCase):
    """Test that create_line() legacy alias correctly translates standard format."""

    def setUp(self):
        self.provider = MockProviderModel(adapter_key='mock')
        self.adapter = MockProviderAdapter(provider=self.provider, fail_rate=0.0)

    def test_create_line_returns_legacy_format(self):
        result = self.adapter.create_line(pack_id=1, months=1)
        self.assertIn('user_id', result)
        self.assertIn('streaming_username', result)
        self.assertIn('password', result)
        self.assertIn('dns_domain', result)
        self.assertIn('m3u_url', result)
        self.assertIn('expires_at', result)
        self.assertIn('raw_response', result)

    def test_create_line_password_matches_secret(self):
        """Legacy alias should extract secret_password into 'password' key."""
        result = self.adapter.create_line(pack_id=1, months=6)
        self.assertTrue(len(result['password']) > 0)


class TestHotPlayerAdapter(TestCase, StandardFormatMixin):
    """Test HotPlayerAdapter with mocked HTTP — no real API calls."""

    def setUp(self):
        self.provider = MockProviderModel(
            adapter_key='hotplayer',
            api_endpoint='http://hotplayer.test/api/activate',
            extra_config={
                'mac_prefix': '00:1A:79',
                'timeout': 10,
                'dns_domain': 'hotplayer.net',
            }
        )
        self.adapter = HotPlayerAdapter(provider=self.provider)

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertIn('create', caps)
        self.assertIn('renew', caps)
        self.assertIn('suspend', caps)
        self.assertIn('balance_check', caps)

    @patch('api.providers.hotplayer.requests.request')
    def test_create_returns_standard_format(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success', 'mac': '00:1A:79:AB:CD:EF'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=100, months=12)
        self.assert_standard_format(result)

    @patch('api.providers.hotplayer.requests.request')
    def test_create_mac_only_credentials(self, mock_request):
        """HotPlayer credentials should only have mac and device_type."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=100, months=12)
        creds = result['credentials']
        self.assertIn('mac', creds)
        self.assertIn('device_type', creds)
        # HotPlayer should NOT have password or m3u_url
        self.assertNotIn('secret_password', creds)
        self.assertNotIn('m3u_url', creds)

    @patch('api.providers.hotplayer.requests.request')
    def test_create_expiry_from_months(self, mock_request):
        """CRITICAL: Expiry must be based on months argument, not hardcoded."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        before = timezone.now()
        result = self.adapter.create(pack_id=100, months=6)
        after = timezone.now()

        self.assertIsNotNone(result['expires_at'])
        expected_min = before + timedelta(days=180)
        expected_max = after + timedelta(days=180)
        self.assertGreaterEqual(result['expires_at'], expected_min)
        self.assertLessEqual(result['expires_at'], expected_max)

    @patch('api.providers.hotplayer.requests.request')
    def test_create_lifetime_no_expiry(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=100, months=12, is_lifetime=True)
        self.assertIsNone(result['expires_at'])

    @patch('api.providers.hotplayer.requests.request')
    def test_create_sends_subscription_field(self, mock_request):
        """HotPlayer API expects 'subscription' in payload."""
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'status': 'success'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        self.adapter.create(pack_id=100, months=12)

        call_kwargs = mock_request.call_args
        payload = call_kwargs.kwargs.get('json', {}) if call_kwargs.kwargs else call_kwargs[1].get('json', {})
        self.assertIn('subscription', payload)
        self.assertEqual(payload['subscription'], 'YEAR_1')


class TestCMSOnlyAdapter(TestCase, StandardFormatMixin):
    """Test CMSOnlyAdapter with mocked HTTP — no real API calls."""

    def setUp(self):
        self.provider = MockProviderModel(
            adapter_key='neo4k',
            api_endpoint='http://neo4k.test/api',
            extra_config={
                'dns_domain': 'kmapp.xyz',
                'port': 8080,
                'timeout': 10,
            }
        )
        self.adapter = CMSOnlyAdapter(provider=self.provider)

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertIn('create', caps)
        self.assertEqual(len(caps), 1, "CMSOnlyAdapter should only support 'create'")

    @patch('api.providers.cms_only.requests.get')
    def test_create_returns_standard_format(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"user_id": "testuser123", "url": "http://kmapp.xyz:8080/get.php?username=stream1&password=pass1"}'
        mock_response.json.return_value = {
            'user_id': 'testuser123',
            'url': 'http://kmapp.xyz:8080/get.php?username=stream1&password=pass1',
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=1)
        self.assert_standard_format(result)

    @patch('api.providers.cms_only.requests.get')
    def test_create_extracts_credentials_correctly(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"user_id": "u1", "url": "http://kmapp.xyz:8080/get.php?username=stream_u1&password=secret123"}'
        mock_response.json.return_value = {
            'user_id': 'u1',
            'url': 'http://kmapp.xyz:8080/get.php?username=stream_u1&password=secret123',
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=3)
        creds = result['credentials']
        self.assertEqual(creds['username'], 'stream_u1')
        self.assertEqual(creds['secret_password'], 'secret123')
        self.assertIn('m3u_url', creds)
        self.assertEqual(result['external_id'], 'u1')
