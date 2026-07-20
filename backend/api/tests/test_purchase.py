"""
Purchase & Fulfillment Tests
============================
Idempotency, credit integrity, partial fulfillment, refunds,
manual product fulfillment, WhatsApp fulfillment, and order lifecycle.
"""
from decimal import Decimal
from unittest.mock import patch, MagicMock
from datetime import timedelta
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status

from api.models import (
    CustomUser, Provider, Category, Product, ProductVariant,
    Order, Credential, CreditTransaction, IdempotencyKey, QuarantinedCredential,
)
from api.services import (
    reserve_phase, fulfill_sync, compensate_order, check_idempotency,
    InsufficientCredits,
)
from api.utils import encrypt_password


class PurchaseTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.reseller = CustomUser.objects.create_user(
            username='reseller', email='r@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )

        self.reseller2 = CustomUser.objects.create_user(
            username='reseller2', email='r2@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('300.00'),
        )

        self.provider = Provider.objects.create(
            name='Mock Prov', slug='mock-prov', adapter_key='mock', is_active=True,
        )
        self.category = Category.objects.create(name='Test', slug='test')

        # API-driven product (mock adapter produces fake credentials)
        self.api_product = Product.objects.create(
            name='API Prod', category=self.category, provider=self.provider,
            is_active=True, is_manual=False,
        )
        self.api_variant = ProductVariant.objects.create(
            product=self.api_product, duration_months=1, external_pack_id=1,
            price_in_credits=Decimal('20.00'), is_active=True,
        )
        self.api_variant_lifetime = ProductVariant.objects.create(
            product=self.api_product, duration_months=None, external_pack_id=2,
            price_in_credits=Decimal('100.00'), is_active=True, is_lifetime=True,
        )

        # Manual product
        self.manual_product = Product.objects.create(
            name='Manual Prod', category=self.category, provider=self.provider,
            is_active=True, is_manual=True, credential_type='username_password',
        )
        self.manual_variant = ProductVariant.objects.create(
            product=self.manual_product, duration_months=1, external_pack_id=3,
            price_in_credits=Decimal('10.00'), is_active=True,
        )

    def _login(self):
        resp = self.client.post(reverse('auth-login'), {
            'username': 'reseller', 'password': 'pass123',
        })
        return resp.data

    def _auth_header(self):
        tokens = self._login()
        return {'HTTP_AUTHORIZATION': f'Bearer {tokens["access"]}'}

    def _api_headers(self, idempotency_key='test-key-1'):
        headers = self._auth_header()
        headers['HTTP_IDEMPOTENCY_KEY'] = idempotency_key
        return headers


# ── SEC-3.6: Idempotency Key Enforcement ──

class TestIdempotencyRequired(PurchaseTestBase):
    def test_purchase_without_idempotency_key_returns_400(self):
        headers = self._auth_header()
        resp = self.client.post(reverse('purchase'),
                                {'variant_id': self.api_variant.id, 'quantity': 1},
                                **headers)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Idempotency-Key', str(resp.data))


# ── SEC-3.7: Idempotency Replay ──

class TestIdempotencyReplay(PurchaseTestBase):
    @patch('api.services.get_adapter_for_provider')
    def test_duplicate_key_returns_409_with_original_order(self, mock_get_adapter):
        from api.providers.mock import MockProviderAdapter
        mock_adapter = MockProviderAdapter(provider=self.api_product.provider)
        mock_get_adapter.return_value = mock_adapter

        headers = self._api_headers('dup-key')
        data = {'variant_id': self.api_variant.id, 'quantity': 1}

        resp1 = self.client.post(reverse('purchase'), data, **headers)
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        resp2 = self.client.post(reverse('purchase'), data, **headers)
        self.assertEqual(resp2.status_code, status.HTTP_409_CONFLICT)
        self.assertIn('Original order returned', str(resp2.data))

    @patch('api.services.get_adapter_for_provider')
    def test_idempotency_scoped_per_user(self, mock_get_adapter):
        from api.providers.mock import MockProviderAdapter
        mock_adapter = MockProviderAdapter(provider=self.api_product.provider)
        mock_get_adapter.return_value = mock_adapter

        headers1 = self._api_headers('same-key')
        resp1 = self.client.post(reverse('purchase'),
                                 {'variant_id': self.api_variant.id, 'quantity': 1},
                                 **headers1)
        self.assertEqual(resp1.status_code, status.HTTP_201_CREATED)

        resp2 = self.client.post(reverse('auth-login'), {
            'username': 'reseller2', 'password': 'pass123',
        })
        headers2 = {'HTTP_AUTHORIZATION': f'Bearer {resp2.data["access"]}',
                    'HTTP_IDEMPOTENCY_KEY': 'same-key'}
        resp3 = self.client.post(reverse('purchase'),
                                 {'variant_id': self.api_variant.id, 'quantity': 1},
                                 **headers2)
        self.assertEqual(resp3.status_code, status.HTTP_201_CREATED)


# ── UX-3.1: Insufficient Credits ──

class TestInsufficientCredits(PurchaseTestBase):
    def test_insufficient_credits_returns_400(self):
        variant = ProductVariant.objects.create(
            product=self.api_product, duration_months=1, external_pack_id=99,
            price_in_credits=Decimal('999999.00'), is_active=True,
        )
        headers = self._api_headers('insufficient-test')
        resp = self.client.post(reverse('purchase'),
                                {'variant_id': variant.id, 'quantity': 1},
                                **headers)
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('Insufficient credits', str(resp.data))


# ── VULN-3.1 & 3.2: Credit Integrity ──

class TestCreditIntegrity(PurchaseTestBase):
    @patch('api.services.get_adapter_for_provider')
    def test_reserve_phase_deducts_credits_atomically(self, mock_get_adapter):
        from api.providers.mock import MockProviderAdapter
        mock_adapter = MockProviderAdapter(provider=self.api_product.provider)
        mock_get_adapter.return_value = mock_adapter

        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        headers = self._api_headers('atomic-test')
        resp = self.client.post(reverse('purchase'),
                                {'variant_id': self.api_variant.id, 'quantity': 2},
                                **headers)
        self.assertEqual(resp.status_code, status.HTTP_201_CREATED)

        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before - Decimal('40.00'))

        tx = CreditTransaction.objects.filter(reseller=self.reseller,
                                              actor=CreditTransaction.Actor.RESELLER).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.delta, Decimal('-40.00'))

    def test_negative_balance_prevented(self):
        low_credits_user = CustomUser.objects.create_user(
            username='low', email='low@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('5.00'),
        )
        resp = self.client.post(reverse('auth-login'),
                                {'username': 'low', 'password': 'pass123'})
        headers = {'HTTP_AUTHORIZATION': f'Bearer {resp.data["access"]}',
                   'HTTP_IDEMPOTENCY_KEY': 'low-bal-test'}
        resp2 = self.client.post(reverse('purchase'),
                                 {'variant_id': self.api_variant.id, 'quantity': 1},
                                 **headers)
        self.assertEqual(resp2.status_code, status.HTTP_400_BAD_REQUEST)


# ── VULN-3.6: Partial Fulfillment ──

class TestPartialFulfillment(PurchaseTestBase):
    @patch('api.providers.mock.MockProviderAdapter.create')
    def test_partial_fulfillment_refunds_unprocessed_items(self, mock_create):
        mock_create.side_effect = [
            {'external_id': 'cred-1', 'credentials': {'username': 'u1', 'secret_password': 'p1'},
             'expires_at': timezone.now() + timedelta(days=30), 'raw_response': {}},
            Exception('Provider error on item 2'),
        ]
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        order = reserve_phase(self.reseller, self.api_variant, 2, 'partial-test-key')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        self.assertIsNotNone(failure)
        order.refresh_from_db()
        self.assertEqual(order.quantity, 1)
        self.assertEqual(order.total_credits, Decimal('20.00'))
        reseller = CustomUser.objects.get(id=self.reseller.id)
        expected_refund = balance_before - Decimal('20.00')
        self.assertEqual(reseller.credit_balance, expected_refund)

    @patch('api.providers.mock.MockProviderAdapter.create')
    def test_partial_fulfillment_credits_correct_refund_amount(self, mock_create):
        mock_create.side_effect = [
            {'external_id': 'cred-1', 'credentials': {'username': 'u1', 'secret_password': 'p1'},
             'expires_at': timezone.now() + timedelta(days=30), 'raw_response': {}},
            Exception('Fail'),
            Exception('Fail'),
        ]
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        order = reserve_phase(self.reseller, self.api_variant, 3, 'partial-refund-math')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        order.refresh_from_db()
        self.assertEqual(order.quantity, 1)
        self.assertEqual(order.total_credits, Decimal('20.00'))
        reseller = CustomUser.objects.get(id=self.reseller.id)
        expected = balance_before - Decimal('20.00')
        self.assertEqual(reseller.credit_balance, expected)


# ── REL-1.3: Full Provider Failure → Refund + Quarantine ──

class TestFullProviderFailure(PurchaseTestBase):
    @patch('api.providers.mock.MockProviderAdapter.create')
    def test_full_failure_refunds_and_quarantines(self, mock_create):
        mock_create.side_effect = Exception('Provider completely down')
        order = reserve_phase(self.reseller, self.api_variant, 2, 'full-fail-key')
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 0)
        self.assertIsNotNone(failure)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FAILED)
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before + Decimal('40.00'))

    @patch('api.providers.mock.MockProviderAdapter.create')
    def test_full_failure_refunds_all_and_marks_failed(self, mock_create):
        mock_create.side_effect = Exception('Provider completely down')
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        order = reserve_phase(self.reseller, self.api_variant, 2, 'quarantine-test')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 0)
        self.assertIsNotNone(failure)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.FAILED)
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before)


# ── VULN-3.3: Refund Marks Credentials as Revoked ──

class TestRefundBehavior(PurchaseTestBase):
    def test_compensate_order_revokes_credentials(self):
        order = reserve_phase(self.reseller, self.api_variant, 1, 'comp-test-key')
        cred = Credential.objects.create(
            order=order, external_username='test-ext',
            streaming_username='test-stream',
            encrypted_password=encrypt_password('p'),
            dns_domain='d', m3u_url='',
            expires_at=timezone.now() + timedelta(days=30),
        )
        compensate_order(order, 'test failure')
        self.assertEqual(QuarantinedCredential.objects.count(), 1)
        self.assertFalse(Credential.objects.filter(id=cred.id).exists())

    def test_compensate_order_credits_restored(self):
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        order = reserve_phase(self.reseller, self.api_variant, 1, 'comp-test-key-2')
        compensate_order(order, 'test failure')
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before)

    def test_compensate_order_creates_credit_transaction(self):
        order = reserve_phase(self.reseller, self.api_variant, 1, 'comp-test-key-3')
        compensate_order(order, 'test failure')
        tx = CreditTransaction.objects.filter(
            reseller=self.reseller, reason__icontains='Refund'
        ).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.actor, CreditTransaction.Actor.SYSTEM)


# ── Manual Product Fulfillment ──

class TestManualProductFulfillment(PurchaseTestBase):
    def setUp(self):
        super().setUp()
        from dashboard.models import ManualProductCredential
        self.ManualCredential = ManualProductCredential

        self.manual_cred = self.ManualCredential.objects.create(
            product=self.manual_product,
            variant=self.manual_variant,
            credential_type='username_password',
            username='manual-user',
            password='manual-pass',
            status='available',
        )

    def test_manual_product_fulfillment_assigns_credential(self):
        order = reserve_phase(self.reseller, self.manual_variant, 1, 'manual-fulfill-key')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        self.assertIsNone(failure)
        order.refresh_from_db()
        self.assertEqual(order.status, Order.Status.COMPLETED)
        self.manual_cred.refresh_from_db()
        self.assertEqual(self.manual_cred.status, 'used')
        self.assertEqual(self.manual_cred.assigned_to, self.reseller)

    def test_manual_product_out_of_stock(self):
        order = reserve_phase(self.reseller, self.manual_variant, 2, 'manual-oos-key')
        credentials, failure = fulfill_sync(order)
        self.assertLess(len(credentials), 2)
        self.assertIsNotNone(failure)
        self.assertIn('out of stock', str(failure).lower() or 'no available credentials' in str(failure))

    def test_manual_product_single_code_fulfillment(self):
        from dashboard.models import ManualProductCredential
        code_cred = ManualProductCredential.objects.create(
            product=self.manual_product,
            variant=self.manual_variant,
            credential_type='single_code',
            code='ACTIVATE-CODE-123',
            status='available',
        )
        order = reserve_phase(self.reseller, self.manual_variant, 1, 'manual-code-key')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        self.assertIn('code', credentials[0].data)

    def test_manual_product_partial_fulfillment_refund(self):
        balance_before = CustomUser.objects.get(id=self.reseller.id).credit_balance
        order = reserve_phase(self.reseller, self.manual_variant, 3, 'manual-partial-key')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        order.refresh_from_db()
        self.assertEqual(order.quantity, 1)
        reseller = CustomUser.objects.get(id=self.reseller.id)
        self.assertEqual(reseller.credit_balance, balance_before - Decimal('10.00'))


# ── WhatsApp Fulfillment ──

class TestWhatsAppFulfillment(PurchaseTestBase):
    def setUp(self):
        super().setUp()
        self.whatsapp_provider = Provider.objects.create(
            name='WhatsApp', slug='whatsapp', adapter_key='whatsapp', is_active=True,
        )
        self.whatsapp_product = Product.objects.create(
            name='WhatsApp Order', category=self.category,
            provider=self.whatsapp_provider, is_active=True, is_manual=False,
        )
        self.whatsapp_variant = ProductVariant.objects.create(
            product=self.whatsapp_product, duration_months=1, external_pack_id=10,
            price_in_credits=Decimal('15.00'), is_active=True,
        )

    def test_whatsapp_fulfillment_no_admin_phone(self):
        order = reserve_phase(self.reseller, self.whatsapp_variant, 1, 'wa-no-admin')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 0)
        self.assertIsNotNone(failure)

    def test_whatsapp_fulfillment_success(self):
        admin = CustomUser.objects.create_user(
            username='wa-admin', email='wa@admin.com', password='admin123',
            role='ADMIN', whatsapp_phone='+1234567890',
        )

        order = reserve_phase(self.reseller, self.whatsapp_variant, 1, 'wa-success-key')
        credentials, failure = fulfill_sync(order)
        self.assertEqual(len(credentials), 1)
        self.assertIsNone(failure)
        self.assertTrue(credentials[0].data.get('whatsapp'))
        self.assertIn('wa.me', credentials[0].data.get('wa_link', ''))


# ── reserve_phase standalone unit tests ──

class TestReservePhase(PurchaseTestBase):
    def test_reserve_phase_creates_order(self):
        order = reserve_phase(self.reseller, self.api_variant, 1, 'unit-reserve-1')
        self.assertEqual(order.status, Order.Status.PENDING)
        self.assertEqual(order.quantity, 1)
        self.assertEqual(order.total_credits, Decimal('20.00'))
        self.assertEqual(order.product_name_at_purchase, 'API Prod - 1 Month')

    def test_reserve_phase_creates_credit_transaction(self):
        order = reserve_phase(self.reseller, self.api_variant, 2, 'unit-reserve-2')
        tx = CreditTransaction.objects.filter(reference_order=order).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.delta, Decimal('-40.00'))
        self.assertEqual(tx.actor, CreditTransaction.Actor.RESELLER)

    def test_reserve_phase_creates_idempotency_key(self):
        order = reserve_phase(self.reseller, self.api_variant, 1, 'unit-reserve-3')
        idem = IdempotencyKey.objects.filter(reseller=self.reseller,
                                             key='unit-reserve-3').first()
        self.assertIsNotNone(idem)
        self.assertEqual(idem.order, order)

    def test_reserve_phase_raises_on_insufficient_credits(self):
        poor_user = CustomUser.objects.create_user(
            username='poor', email='poor@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('5.00'),
        )
        with self.assertRaises(InsufficientCredits):
            reserve_phase(poor_user, self.api_variant, 1, 'unit-insufficient')

    def test_reserve_phase_preserves_balance_if_raises(self):
        poor_user = CustomUser.objects.create_user(
            username='poor2', email='poor2@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('5.00'),
        )
        with self.assertRaises(InsufficientCredits):
            reserve_phase(poor_user, self.api_variant, 1, 'unit-insufficient-2')
        poor_user.refresh_from_db()
        self.assertEqual(poor_user.credit_balance, Decimal('5.00'))


# ── check_idempotency unit tests ──

class TestCheckIdempotency(PurchaseTestBase):
    def test_check_idempotency_returns_none_for_new_key(self):
        result = check_idempotency(self.reseller, 'nonexistent-key')
        self.assertIsNone(result)

    def test_check_idempotency_returns_order_for_existing_key(self):
        order = reserve_phase(self.reseller, self.api_variant, 1, 'check-idem-test')
        result = check_idempotency(self.reseller, 'check-idem-test')
        self.assertEqual(result.uuid, order.uuid)

    def test_check_idempotency_scoped_per_user(self):
        reserve_phase(self.reseller, self.api_variant, 1, 'scoped-key')
        result = check_idempotency(self.reseller2, 'scoped-key')
        self.assertIsNone(result)
