"""
Input Validation & Encryption Tests
=====================================
MAC address validation, quantity bounds, HotPlayer-specific
validation, variant tampering, Fernet encrypt/decrypt,
provider token encryption, and utility functions.
"""
from decimal import Decimal
from unittest.mock import patch
from cryptography.fernet import InvalidToken
from django.test import TestCase, override_settings
from django.urls import reverse
from django.core.exceptions import ImproperlyConfigured
from rest_framework.test import APIClient
from rest_framework import status

from api.utils import encrypt_password, decrypt_password, get_fernet, extract_base_url, build_m3u_url
from api.models import CustomUser, Provider, Category, Product, ProductVariant
from api.serializers import PurchaseSerializer


class ValidationTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.reseller = CustomUser.objects.create_user(
            username='reseller', email='r@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )
        self.auth_client = APIClient()
        self.auth_client.force_authenticate(user=self.reseller)

        self.provider = Provider.objects.create(
            name='Mock Prov', slug='mock-prov', adapter_key='mock', is_active=True,
        )
        self.category = Category.objects.create(name='ValCat', slug='val-cat')
        self.product = Product.objects.create(
            name='Test Product', category=self.category, provider=self.provider,
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=1,
            price_in_credits=Decimal('10.00'), is_active=True,
        )


class TestMACValidation(ValidationTestBase):
    VALID_MACS = ['AA:BB:CC:DD:EE:FF', 'aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55']
    INVALID_MACS = ['not-a-mac', 'AA-BB-CC-DD-EE-FF', 'AA:BB:CC:DD:EE:FF:GG', '', 'ABC']

    def test_valid_mac_accepted_by_serializer(self):
        for mac in self.VALID_MACS:
            data = {'variant_id': self.variant.id, 'quantity': 1, 'mac': mac}
            serializer = PurchaseSerializer(data=data,
                                            context={'request': None})
            is_valid = serializer.is_valid()
            self.assertTrue(is_valid, f"MAC '{mac}' should be valid, errors: {serializer.errors}")

    def test_invalid_mac_rejected_by_serializer(self):
        for mac in self.INVALID_MACS:
            data = {'variant_id': self.variant.id, 'quantity': 1, 'mac': mac}
            serializer = PurchaseSerializer(data=data,
                                            context={'request': None})
            is_valid = serializer.is_valid()
            if mac == '':
                self.assertTrue(is_valid, "Empty MAC should be allowed for non-HotPlayer")
            else:
                self.assertFalse(is_valid, f"MAC '{mac}' should be invalid")

    @patch('api.providers.mock.MockProviderAdapter.create')
    def test_check_device_endpoint_valid_mac(self, mock_create):
        mock_create.return_value = {'found': True}
        resp = self.auth_client.post(reverse('check-device'),
                                     {'mac': 'AA:BB:CC:DD:EE:FF'})
        self.assertNotEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_check_device_endpoint_invalid_mac(self):
        resp = self.auth_client.post(reverse('check-device'),
                                     {'mac': 'invalid-mac'})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_check_device_endpoint_missing_mac(self):
        resp = self.auth_client.post(reverse('check-device'), {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TestQuantityBounds(ValidationTestBase):
    def test_quantity_0_rejected(self):
        data = {'variant_id': self.variant.id, 'quantity': 0}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_quantity_negative_rejected(self):
        data = {'variant_id': self.variant.id, 'quantity': -1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_quantity_51_rejected(self):
        data = {'variant_id': self.variant.id, 'quantity': 51}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_quantity_1_accepted(self):
        data = {'variant_id': self.variant.id, 'quantity': 1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertTrue(s.is_valid())

    def test_quantity_50_accepted(self):
        data = {'variant_id': self.variant.id, 'quantity': 50}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertTrue(s.is_valid())


class TestHotPlayerValidation(ValidationTestBase):
    def setUp(self):
        super().setUp()
        self.hp_provider = Provider.objects.create(
            name='HP', slug='hp', adapter_key='hotplayer', is_active=True,
        )
        self.hp_product = Product.objects.create(
            name='HP Sub', category=self.category,
            provider=self.hp_provider, is_active=True,
        )
        self.hp_variant = ProductVariant.objects.create(
            product=self.hp_product, duration_months=1, external_pack_id=10,
            price_in_credits=Decimal('25.00'), is_active=True,
        )

    def test_hotplayer_quantity_1_with_mac_valid(self):
        data = {'variant_id': self.hp_variant.id, 'quantity': 1,
                'mac': 'AA:BB:CC:DD:EE:FF'}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertTrue(s.is_valid(), f"Errors: {s.errors}")

    def test_hotplayer_quantity_gt_1_rejected(self):
        data = {'variant_id': self.hp_variant.id, 'quantity': 2,
                'mac': 'AA:BB:CC:DD:EE:FF'}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_hotplayer_missing_mac_rejected(self):
        data = {'variant_id': self.hp_variant.id, 'quantity': 1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_hotplayer_empty_mac_rejected(self):
        data = {'variant_id': self.hp_variant.id, 'quantity': 1, 'mac': ''}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())


class TestVariantValidation(ValidationTestBase):
    def test_inactive_variant_rejected(self):
        inactive_variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=999,
            price_in_credits=Decimal('10.00'), is_active=False,
        )
        data = {'variant_id': inactive_variant.id, 'quantity': 1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_nonexistent_variant_rejected(self):
        data = {'variant_id': 99999, 'quantity': 1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())

    def test_variant_of_inactive_product_rejected(self):
        inactive_product = Product.objects.create(
            name='Inactive', category=self.category, provider=self.provider,
            is_active=False,
        )
        orphan_variant = ProductVariant.objects.create(
            product=inactive_product, duration_months=1, external_pack_id=888,
            price_in_credits=Decimal('10.00'), is_active=True,
        )
        data = {'variant_id': orphan_variant.id, 'quantity': 1}
        s = PurchaseSerializer(data=data, context={'request': None})
        self.assertFalse(s.is_valid())


class TestFernetEncryption(TestCase):
    def test_encrypt_decrypt_round_trip(self):
        password = 'my-secret-password-123!@#'
        encrypted = encrypt_password(password)
        decrypted = decrypt_password(encrypted)
        self.assertEqual(decrypted, password)

    def test_encrypt_produces_bytes(self):
        encrypted = encrypt_password('test-pass')
        self.assertIsInstance(encrypted, bytes)

    def test_decrypt_empty_bytes_raises_invalid_token(self):
        with self.assertRaises(InvalidToken):
            decrypt_password(b'')

    def test_decrypt_none_returns_empty(self):
        self.assertEqual(decrypt_password(None), '')

    def test_encrypted_values_differ(self):
        p1 = encrypt_password('same-pass')
        p2 = encrypt_password('same-pass')
        self.assertNotEqual(p1, p2)

    def test_decrypt_memoryview(self):
        encrypted = encrypt_password('memory-view-test')
        mv = memoryview(encrypted)
        self.assertEqual(decrypt_password(mv), 'memory-view-test')

    @override_settings(FERNET_KEY='')
    def test_get_fernet_raises_with_empty_key(self):
        with self.assertRaises(ImproperlyConfigured):
            get_fernet()


class TestProviderTokenEncryption(TestCase):
    def test_set_and_get_token_round_trip(self):
        provider = Provider.objects.create(
            name='Token Test', slug='token-test', adapter_key='mock', is_active=True,
        )
        provider.set_token('my-api-token-12345')
        provider.save()
        provider.refresh_from_db()
        retrieved = provider.get_token()
        self.assertEqual(retrieved, 'my-api-token-12345')
        self.assertIsNotNone(provider.api_token)

    def test_set_token_stores_as_bytes(self):
        provider = Provider.objects.create(
            name='Token Bytes', slug='token-bytes', adapter_key='mock', is_active=True,
        )
        provider.set_token('raw-token')
        self.assertIsInstance(provider.api_token, bytes)

    def test_get_token_empty_returns_empty_string(self):
        provider = Provider.objects.create(
            name='Empty Token', slug='empty-token', adapter_key='mock', is_active=True,
        )
        result = provider.get_token()
        self.assertEqual(result, '')

    def test_get_token_none_returns_empty_string(self):
        provider = Provider(
            name='None Token', slug='none-token', adapter_key='mock',
            api_token=None, is_active=True,
        )
        result = provider.get_token()
        self.assertEqual(result, '')


class TestUtils(TestCase):
    def test_extract_base_url_full_url(self):
        url = 'http://example.com:8080/get.php?username=test&password=pass'
        self.assertEqual(extract_base_url(url), 'http://example.com:8080')

    def test_extract_base_url_https(self):
        url = 'https://secure.example.com/get.php'
        self.assertEqual(extract_base_url(url), 'https://secure.example.com')

    def test_extract_base_url_empty(self):
        self.assertEqual(extract_base_url(''), '')

    # extract_base_url('not-a-url') returns '://' because urlparse
    # has empty scheme/netloc but format produces '://'
    def test_extract_base_url_invalid_returns_scheme_separator(self):
        self.assertEqual(extract_base_url('not-a-url'), '://')

    def test_extract_base_url_none(self):
        self.assertEqual(extract_base_url(None), '')

    @override_settings(IPTV_DNS='test.tv', IPTV_PORT=8080)
    def test_build_m3u_url(self):
        url = build_m3u_url('myuser', 'mypass')
        self.assertIn('myuser', url)
        self.assertIn('mypass', url)

    @override_settings(IPTV_DNS='default.tv', IPTV_PORT=80)
    def test_build_m3u_url_custom_dns(self):
        url = build_m3u_url('u', 'p', dns='custom.tv', port=9090)
        self.assertIn('custom.tv', url)
        self.assertIn('9090', url)

    def test_decrypt_invalid_bytes_raises_error(self):
        with self.assertRaises(InvalidToken):
            decrypt_password(b'invalid-fernet-data')


class TestCreditTransactionAudit(ValidationTestBase):
    def test_purchase_creates_reseller_credit_transaction(self):
        from api.models import CreditTransaction
        from api.services import reserve_phase
        order = reserve_phase(self.reseller, self.variant, 2, 'tx-audit-test-1')
        tx = CreditTransaction.objects.filter(reference_order=order).first()
        self.assertIsNotNone(tx)
        self.assertEqual(tx.actor, CreditTransaction.Actor.RESELLER)
        self.assertEqual(tx.delta, Decimal('-20.00'))
        self.assertIsNotNone(tx.balance_after)
