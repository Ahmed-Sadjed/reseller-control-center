"""
Device Management Tests
=======================
Device activation, status check, refund flow, MAC-based device
check, and credit refund on provider failure during activation.
No real API calls — all provider adapters are mocked.
"""
from decimal import Decimal
from unittest.mock import patch
from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from api.models import (
    CustomUser, Provider, Category, Product, ProductVariant,
    Order, Credential,
)
from api.utils import encrypt_password
from api.device_services import (
    check_device_by_mac, get_credential_for_user,
)

patch('rest_framework.throttling.AnonRateThrottle.allow_request', return_value=True).start()
patch('rest_framework.throttling.UserRateThrottle.allow_request', return_value=True).start()


class DeviceTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.reseller = CustomUser.objects.create_user(
            username='reseller', email='r@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )
        self.auth_client = APIClient()
        self.auth_client.force_authenticate(user=self.reseller)

        self.provider = Provider.objects.create(
            name='HP Provider', slug='hp-provider', adapter_key='hotplayer',
            is_active=True, extra_config={'dns_domain': 'hp.test.tv', 'port': 8080},
        )
        self.golden_provider = Provider.objects.create(
            name='Golden API', slug='golden-api', adapter_key='golden_api',
            is_active=True,
        )

        self.category = Category.objects.create(name='DevCat', slug='dev-cat')
        self.product = Product.objects.create(
            name='IPTV Sub', category=self.category, provider=self.provider,
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=100,
            price_in_credits=Decimal('30.00'), is_active=True,
        )
        self.activate_variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=200,
            price_in_credits=Decimal('50.00'), is_active=True,
        )

        self.order = Order.objects.create(
            reseller=self.reseller, product=self.product, variant=self.variant,
            quantity=1, unit_price_at_purchase=Decimal('30.00'),
            product_name_at_purchase='IPTV Sub - 1 Month',
            total_credits=Decimal('30.00'), status=Order.Status.COMPLETED,
            idempotency_key='dev-order-key',
        )
        self.credential = Credential.objects.create(
            order=self.order,
            external_username='AA:BB:CC:DD:EE:FF',
            streaming_username='AA:BB:CC:DD:EE:FF',
            encrypted_password=encrypt_password('test-pass'),
            dns_domain='hp.test.tv',
            m3u_url='http://hp.test.tv/get.php?username=test&password=pass',
            expires_at=timezone.now() + timedelta(days=30),
        )


class TestCheckDeviceByMAC(DeviceTestBase):
    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_active_device(self, mock_check):
        future_ts = int((timezone.now() + timedelta(days=60)).timestamp() * 1000)
        mock_check.return_value = {
            'status': 'active', 'expiration': future_ts,
            'plan': 'MONTHS_1', 'mac': 'AA:BB:CC:DD:EE:FF',
        }
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertTrue(result['found'])
        self.assertEqual(result['status'], 'active')
        self.assertGreater(result['days_remaining'], 0)

    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_expiring_soon(self, mock_check):
        near_future_ts = int((timezone.now() + timedelta(days=3)).timestamp() * 1000)
        mock_check.return_value = {
            'status': 'active', 'expiration': near_future_ts,
            'plan': 'MONTHS_1', 'mac': 'AA:BB:CC:DD:EE:FF',
        }
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertEqual(result['status'], 'expiring_soon')

    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_expired(self, mock_check):
        past_ts = int((timezone.now() - timedelta(days=1)).timestamp() * 1000)
        mock_check.return_value = {
            'status': 'active', 'expiration': past_ts,
            'plan': 'MONTHS_1', 'mac': 'AA:BB:CC:DD:EE:FF',
        }
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertEqual(result['status'], 'expired')

    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_lifetime(self, mock_check):
        mock_check.return_value = {
            'status': 'active', 'expiration': None,
            'plan': 'FOREVER', 'mac': 'AA:BB:CC:DD:EE:FF',
        }
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertEqual(result['status'], 'lifetime')
        self.assertEqual(result['plan'], 'Lifetime')

    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_mac_not_found(self, mock_check):
        mock_check.side_effect = Exception('MAC not found')
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertFalse(result['found'])
        self.assertEqual(result['status'], 'error')

    def test_no_hotplayer_provider(self):
        Provider.objects.filter(adapter_key='hotplayer').update(is_active=False)
        result = check_device_by_mac('AA:BB:CC:DD:EE:FF', self.reseller)
        self.assertFalse(result['found'])
        self.assertIn('No active HotPlayer provider', result['message'])


class TestGetCredentialForUser(DeviceTestBase):
    def test_get_own_credential(self):
        cred = get_credential_for_user(self.credential.id, self.reseller)
        self.assertEqual(cred.id, self.credential.id)

    def test_get_other_users_credential_raises_404(self):
        other_user = CustomUser.objects.create_user(
            username='other4', email='other4@test.com', password='pass123',
            role='RESELLER',
        )
        from django.http import Http404
        with self.assertRaises(Http404):
            get_credential_for_user(self.credential.id, other_user)

    def test_get_nonexistent_credential_raises_404(self):
        from django.http import Http404
        with self.assertRaises(Http404):
            get_credential_for_user(99999, self.reseller)
