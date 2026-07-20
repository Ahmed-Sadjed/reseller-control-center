"""
Device Management Tests
=======================
Device activation, status check, refund flow, MAC-based device
check, and credit refund on provider failure during activation.
No real API calls — all provider adapters are mocked.
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock, PropertyMock
from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from api.models import (
    CustomUser, Provider, Category, Product, ProductVariant,
    Order, Credential, CreditTransaction,
)
from api.utils import encrypt_password
from api.device_services import (
    activate_device, check_device, check_device_by_mac, refund_device,
    InsufficientCredits, NoMatchingVariant, get_credential_for_user,
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


class TestDeviceActivation(DeviceTestBase):
    @patch('api.providers.hotplayer.HotPlayerAdapter.activate_device')
    def test_activate_device_deducts_credits(self, mock_activate):
        mock_activate.return_value = {'status': 'success'}
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        activate_device(self.credential.id, self.reseller,
                        pack_id=200, duration='MONTHS_1')
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before - Decimal('50.00'))
        tx = CreditTransaction.objects.filter(
            reseller=reseller, reason__icontains='Device activation'
        ).first()
        self.assertIsNotNone(tx)

    @patch('api.providers.hotplayer.HotPlayerAdapter.activate_device')
    def test_activate_device_success(self, mock_activate):
        mock_activate.return_value = {'status': 'success', 'line': 'test-line'}
        result = activate_device(self.credential.id, self.reseller,
                                 pack_id=200, duration='MONTHS_1')
        self.assertIn('result', result)
        self.assertIn('credential', result)
        self.assertIn('variant', result)
        self.assertEqual(result['variant'].id, self.activate_variant.id)

    def test_activate_device_no_matching_variant(self):
        with self.assertRaises(NoMatchingVariant):
            activate_device(self.credential.id, self.reseller,
                            pack_id=99999, duration='MONTHS_1')

    def test_activate_device_insufficient_credits(self):
        poor_user = CustomUser.objects.create_user(
            username='poor', email='poor@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('1.00'),
        )
        poor_order = Order.objects.create(
            reseller=poor_user, product=self.product, variant=self.variant,
            quantity=1, unit_price_at_purchase=Decimal('30.00'),
            product_name_at_purchase='IPTV Sub - 1 Month',
            total_credits=Decimal('30.00'), status=Order.Status.COMPLETED,
            idempotency_key='poor-dev-order-key',
        )
        poor_cred = Credential.objects.create(
            order=poor_order,
            external_username='11:22:33:44:55:66',
            streaming_username='11:22:33:44:55:66',
            encrypted_password=encrypt_password('test-pass'),
            dns_domain='hp.test.tv',
            m3u_url='http://hp.test.tv/get.php?username=test&password=pass',
            expires_at=timezone.now() + timedelta(days=30),
        )
        with self.assertRaises(InsufficientCredits):
            activate_device(poor_cred.id, poor_user,
                            pack_id=200, duration='MONTHS_1')


class TestDeviceActivationRefund(DeviceTestBase):
    @patch('api.providers.hotplayer.HotPlayerAdapter.activate_device')
    def test_provider_failure_refunds_credits(self, mock_activate):
        mock_activate.side_effect = Exception('Provider activation failed')
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        with self.assertRaises(Exception):
            activate_device(self.credential.id, self.reseller,
                            pack_id=200, duration='MONTHS_1')
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before)

    @patch('api.providers.hotplayer.HotPlayerAdapter.activate_device')
    def test_provider_failure_creates_refund_transaction(self, mock_activate):
        mock_activate.side_effect = Exception('Provider activation failed')
        with self.assertRaises(Exception):
            activate_device(self.credential.id, self.reseller,
                            pack_id=200, duration='MONTHS_1')
        tx = CreditTransaction.objects.filter(
            reseller=self.reseller, reason__icontains='Refund'
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.actor, CreditTransaction.Actor.SYSTEM)
        self.assertEqual(tx.delta, Decimal('50.00'))


class TestDeviceStatus(DeviceTestBase):
    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_check_device_returns_data(self, mock_check):
        mock_check.return_value = {
            'status': 'active', 'expiration': 1767225600000,
            'plan': 'MONTHS_1', 'mac': 'AA:BB:CC:DD:EE:FF',
        }
        result = check_device(self.credential.id, self.reseller)
        self.assertIsNotNone(result)

    @patch('api.providers.hotplayer.HotPlayerAdapter.check_device')
    def test_check_device_raises_for_other_user(self, mock_check):
        other_user = CustomUser.objects.create_user(
            username='other', email='other@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )
        from django.http import Http404
        with self.assertRaises(Http404):
            check_device(self.credential.id, other_user)

    def test_check_device_via_api_returns_400_for_other_user(self):
        other_user = CustomUser.objects.create_user(
            username='other2', email='other2@test.com', password='pass123',
            role='RESELLER',
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(
            reverse('credential-device-status',
                    kwargs={'credential_id': self.credential.id}),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


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


class TestDeviceRefund(DeviceTestBase):
    @patch('api.providers.hotplayer.HotPlayerAdapter.refund', create=True)
    @patch('api.providers.hotplayer.HotPlayerAdapter.capabilities',
           new_callable=PropertyMock, return_value={'create', 'refund'})
    def test_refund_restores_credits(self, mock_caps, mock_refund):
        mock_refund.return_value = {'status': 'refunded'}
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        result = refund_device(self.credential.id, self.reseller)
        self.assertEqual(result['refunded_credits'], Decimal('30.00'))
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before + Decimal('30.00'))

    @patch('api.providers.hotplayer.HotPlayerAdapter.refund', create=True)
    @patch('api.providers.hotplayer.HotPlayerAdapter.capabilities',
           new_callable=PropertyMock, return_value={'create', 'refund'})
    def test_refund_marks_credential_revoked(self, mock_caps, mock_refund):
        mock_refund.return_value = {'status': 'refunded'}
        refund_device(self.credential.id, self.reseller)
        self.credential.refresh_from_db()
        self.assertTrue(self.credential.is_revoked)

    @patch('api.providers.hotplayer.HotPlayerAdapter.refund', create=True)
    @patch('api.providers.hotplayer.HotPlayerAdapter.capabilities',
           new_callable=PropertyMock, return_value={'create', 'refund'})
    def test_refund_creates_credit_transaction(self, mock_caps, mock_refund):
        mock_refund.return_value = {'status': 'refunded'}
        refund_device(self.credential.id, self.reseller)
        tx = CreditTransaction.objects.filter(
            reseller=self.reseller, reason__icontains='Refund'
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.actor, CreditTransaction.Actor.SYSTEM)

    @patch('api.providers.hotplayer.HotPlayerAdapter.refund', create=True)
    @patch('api.providers.hotplayer.HotPlayerAdapter.capabilities',
           new_callable=PropertyMock, return_value={'create', 'refund'})
    def test_refund_marks_order_refunded(self, mock_caps, mock_refund):
        mock_refund.return_value = {'status': 'refunded'}
        refund_device(self.credential.id, self.reseller)
        self.order.refresh_from_db()
        self.assertEqual(self.order.status, 'REFUNDED')

    def test_refund_not_implemented(self):
        with self.assertRaises(NotImplementedError):
            refund_device(self.credential.id, self.reseller)


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
