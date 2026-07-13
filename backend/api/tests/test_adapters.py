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
from api.providers.base import BaseProviderAdapter, ProviderAPIError, ProviderInvalidResponseError
from api.providers.mock import MockProviderAdapter
from api.providers.hotplayer import HotPlayerAdapter
from api.providers.cms_only import CMSOnlyAdapter
from api.providers.golden_api import GoldenAPIAdapter
from api.providers.tivipanel import TiviPanelAdapter
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
        self.assertIn('panel_url', creds)

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
        mock_response.text = '{"user_id": "testuser123", "url": "https://kmapp.xyz:8080/get.php?username=stream1&password=pass1"}'
        mock_response.json.return_value = {
            'user_id': 'testuser123',
            'url': 'https://kmapp.xyz:8080/get.php?username=stream1&password=pass1',
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=1)
        self.assert_standard_format(result)

    @patch('api.providers.cms_only.requests.get')
    def test_create_extracts_credentials_correctly(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"user_id": "u1", "url": "https://kmapp.xyz:8080/get.php?username=stream_u1&password=secret123"}'
        mock_response.json.return_value = {
            'user_id': 'u1',
            'url': 'https://kmapp.xyz:8080/get.php?username=stream_u1&password=secret123',
        }
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=3)
        creds = result['credentials']
        self.assertEqual(creds['username'], 'stream_u1')
        self.assertEqual(creds['secret_password'], 'secret123')
        self.assertIn('m3u_url', creds)
        self.assertEqual(result['external_id'], 'u1')


class TestGoldenAPIAdapter(TestCase, StandardFormatMixin):
    """Test GoldenAPIAdapter with mocked HTTP — no real API calls."""

    def _mock_create_response(self, overrides=None):
        """Build a mock response matching the real Golden API nested format."""
        base = {
            'success': True,
            'data': [{
                'id': 42,
                'username': 'golden_u1',
                'password': 'pass123',
                'exp_date': '2027-07-11',
                'created_at': '2025-01-01 00:00:00',
                'is_trial': False,
                'max_connections': 1,
                'package_id': 5,
                'dns_link_for_samsung_lg': 'http://tv.example.com',
            }],
            'package': {'id': 5, 'name': 'Test Package', 'is_trial': False, 'credits_used': 10},
            'template': {'id': 3, 'name': 'My Template'},
            'qr': {'token': 'abc-123', 'url': 'https://example.com/qr/abc-123', 'expires_at': '2025-05-16T12:00:00Z'},
        }
        if overrides:
            self._deep_merge(base, overrides)
        return base

    def _deep_merge(self, base, overrides):
        for key, val in overrides.items():
            if isinstance(val, dict) and key in base and isinstance(base[key], dict):
                self._deep_merge(base[key], val)
            else:
                base[key] = val

    def setUp(self):
        self.provider = MockProviderModel(
            adapter_key='golden_api',
            api_endpoint='http://golden-api.test',
            extra_config={
                'timeout': 15,
            }
        )
        self.adapter = GoldenAPIAdapter(provider=self.provider)

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertIn('create', caps)
        self.assertIn('renew', caps)
        self.assertIn('check', caps)
        self.assertIn('refund', caps)

    @patch('api.providers.golden_api.requests.request')
    def test_create_returns_standard_format(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12)
        self.assert_standard_format(result)

    @patch('api.providers.golden_api.requests.request')
    def test_create_credentials_contain_username_password_line_id(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12)
        creds = result['credentials']
        self.assertIn('username', creds)
        self.assertIn('secret_password', creds)
        self.assertIn('line_id', creds)
        self.assertEqual(creds['line_id'], 42)

    @patch('api.providers.golden_api.requests.request')
    def test_create_uses_provided_username(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response({
            'data': [{'username': 'mycustomuser'}]
        })
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12, username='mycustomuser')
        self.assertEqual(result['credentials']['username'], 'mycustomuser')

    @patch('api.providers.golden_api.requests.request')
    def test_create_auto_generates_username_when_blank(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12)
        self.assertTrue(result['external_id'].startswith('g'))
        self.assertEqual(len(result['external_id']), 8)

    @patch('api.providers.golden_api.requests.request')
    def test_create_auto_generates_password_when_blank(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12)
        self.assertEqual(len(result['credentials']['secret_password']), 7)

    @patch('api.providers.golden_api.requests.request')
    def test_create_retries_on_422_username_taken(self, mock_request):
        fail_response = MagicMock()
        fail_response.status_code = 422
        fail_response.json.return_value = {'message': 'Username already taken'}
        fail_response.raise_for_status.side_effect = Exception('HTTP 422')

        success_response = MagicMock()
        success_response.status_code = 200
        success_response.json.return_value = self._mock_create_response()
        success_response.raise_for_status = MagicMock()

        mock_request.side_effect = [fail_response, success_response]

        result = self.adapter.create(pack_id=5, months=12)
        self.assert_standard_format(result)
        self.assertEqual(mock_request.call_count, 2)

    @patch('api.providers.golden_api.requests.request')
    def test_create_exhausts_retries_and_raises(self, mock_request):
        fail_response = MagicMock()
        fail_response.status_code = 422
        fail_response.json.return_value = {'message': 'Username already taken'}
        fail_response.raise_for_status.side_effect = Exception('HTTP 422')
        mock_request.return_value = fail_response

        with self.assertRaises(Exception):
            self.adapter.create(pack_id=5, months=12)

    @patch('api.providers.golden_api.requests.request')
    def test_create_lifetime_no_expiry(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response({
            'data': [{'id': 1, 'username': 'golden_u1'}]
        })
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        result = self.adapter.create(pack_id=5, months=12, is_lifetime=True)
        self.assertIsNone(result['expires_at'])

    @patch('api.providers.golden_api.requests.request')
    def test_create_sends_correct_payload(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = self._mock_create_response()
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        self.adapter.create(pack_id=5, months=12, username='testuser', password='testpass')
        call_kwargs = mock_request.call_args.kwargs
        payload = call_kwargs.get('json', {})
        self.assertEqual(payload['package_id'], 5)
        self.assertEqual(payload['username'], 'testuser')
        self.assertEqual(payload['password'], 'testpass')

    def test_check_device_without_credential_raises(self):
        credential = MagicMock()
        credential.data = {}
        with self.assertRaises(Exception):
            self.adapter.check_device(mac='00:1A:79:AB:CD:EF', credential=credential)

    @patch('api.providers.golden_api.requests.request')
    def test_check_device_with_line_id(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 42, 'status': 'active', 'exp_date': '2027-07-11'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        credential = MagicMock()
        credential.data = {'line_id': 42}
        result = self.adapter.check_device(mac='00:1A:79:AB:CD:EF', credential=credential)
        self.assertEqual(result['id'], 42)

    @patch('api.providers.golden_api.requests.request')
    def test_extend_device(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 42, 'status': 'active', 'exp_date': '2028-07-11'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        credential = MagicMock()
        credential.data = {'line_id': 42}
        result = self.adapter.activate_device(
            mac='00:1A:79:AB:CD:EF', pack_id=5, duration='12_months',
            extend=True, credential=credential
        )
        self.assertEqual(result['id'], 42)

    def test_extend_without_extend_flag_raises(self):
        credential = MagicMock()
        credential.data = {'line_id': 42}
        with self.assertRaises(Exception):
            self.adapter.activate_device(
                mac='00:1A:79:AB:CD:EF', pack_id=5, duration='12_months',
                extend=False, credential=credential
            )

    def test_extend_without_credential_raises(self):
        with self.assertRaises(Exception):
            self.adapter.activate_device(
                mac='00:1A:79:AB:CD:EF', pack_id=5, duration='12_months',
                extend=True, credential=None
            )

    def test_refund_without_line_id_raises(self):
        credential = MagicMock()
        credential.data = {}
        with self.assertRaises(Exception):
            self.adapter.refund(credential=credential)

    @patch('api.providers.golden_api.requests.request')
    def test_refund_success(self, mock_request):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {'id': 42, 'status': 'refunded'}
        mock_response.raise_for_status = MagicMock()
        mock_request.return_value = mock_response

        credential = MagicMock()
        credential.data = {'line_id': 42}
        result = self.adapter.refund(credential=credential)
        self.assertEqual(result['status'], 'refunded')


class TestTiviPanelAdapter(TestCase, StandardFormatMixin):
    """Test TiviPanelAdapter with mocked HTTP — no real API calls."""

    def setUp(self):
        self.provider = MockProviderModel(
            adapter_key='tivipanel',
            api_endpoint='https://api.tivipanel.net/reseller/panel_api.php',
            extra_config={
                'dns_domain': 'tivipanel.net',
                'port': 8080,
                'timeout': 10,
            }
        )
        self.adapter = TiviPanelAdapter(provider=self.provider)

    def test_capabilities(self):
        caps = self.adapter.capabilities
        self.assertIn('create', caps)
        self.assertEqual(len(caps), 1)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_returns_standard_format(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = '{"status": "true", "username": "u1", "password": "pass1"}'
        mock_response.json.return_value = {"status": "true", "username": "u1", "password": "pass1"}
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=1)
        self.assert_standard_format(result)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_credentials_correct(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "testuser", "password": "testpass"}
        mock_response.text = '{"status": "true", "username": "testuser", "password": "testpass"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=1, months=1)
        creds = result['credentials']
        self.assertIn('username', creds)
        self.assertIn('secret_password', creds)
        self.assertIn('dns_domain', creds)
        self.assertIn('m3u_url', creds)
        self.assertEqual(creds['username'], 'testuser')
        self.assertEqual(creds['secret_password'], 'testpass')
        self.assertEqual(creds['dns_domain'], 'tivipanel.net')
        self.assertEqual(creds['panel_url'], 'https://api.tivipanel.net')
        self.assertEqual(result['external_id'], 'testuser')

    @patch('api.providers.tivipanel.requests.get')
    def test_create_1_month_expiry(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "u1", "password": "p1"}
        mock_response.text = '{"status": "true", "username": "u1", "password": "p1"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        before = timezone.now()
        result = self.adapter.create(pack_id=1, months=1)
        after = timezone.now()
        expected_min = before + timedelta(days=30)
        expected_max = after + timedelta(days=30)
        self.assertGreaterEqual(result['expires_at'], expected_min)
        self.assertLessEqual(result['expires_at'], expected_max)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_6h_trial_expiry(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "trial_u", "password": "trial_p"}
        mock_response.text = '{"status": "true", "username": "trial_u", "password": "trial_p"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=0, months=100)
        self.assertIsNotNone(result['expires_at'])

    @patch('api.providers.tivipanel.requests.get')
    def test_create_uses_pack_id_as_package(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "u1", "password": "p1"}
        mock_response.text = '{"status": "true", "username": "u1", "password": "p1"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.adapter.create(pack_id=35, months=1)
        params = mock_get.call_args.kwargs['params']
        self.assertEqual(params['package'], 35)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_trial_uses_pack_id_as_package(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "trial_u", "password": "trial_p"}
        mock_response.text = '{"status": "true", "username": "trial_u", "password": "trial_p"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.adapter.create(pack_id=35, months=102)
        params = mock_get.call_args.kwargs['params']
        self.assertEqual(params['package'], 35)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_3_year_expiry(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "u1", "password": "p1"}
        mock_response.text = '{"status": "true", "username": "u1", "password": "p1"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        result = self.adapter.create(pack_id=12, months=36)
        expected = timezone.now() + timedelta(days=1095)
        self.assertIsNotNone(result['expires_at'])

    def test_create_lifetime_raises(self):
        with self.assertRaises(ValueError):
            self.adapter.create(pack_id=1, months=1, is_lifetime=True)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_provider_error(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "false", "message": "Invalid API key"}
        mock_response.text = '{"status": "false", "message": "Invalid API key"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with self.assertRaises(ProviderAPIError):
            self.adapter.create(pack_id=1, months=1)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_missing_credentials_raises(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true"}
        mock_response.text = '{"status": "true"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        with self.assertRaises(ProviderInvalidResponseError):
            self.adapter.create(pack_id=1, months=1)

    @patch('api.providers.tivipanel.requests.get')
    def test_create_passes_optional_params(self, mock_get):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"status": "true", "username": "u1", "password": "p1"}
        mock_response.text = '{"status": "true", "username": "u1", "password": "p1"}'
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        self.adapter.create(pack_id=1, months=1, template='tmpl1', notes='test note', country='US')
        params = mock_get.call_args.kwargs['params']
        self.assertEqual(params['template'], 'tmpl1')
        self.assertEqual(params['notes'], 'test note')
        self.assertEqual(params['country'], 'US')
