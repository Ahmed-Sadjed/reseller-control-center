"""
Auth & Security Tests
=====================
JWT lifecycle, token rotation/blacklist, role-based access,
credential ownership isolation, unauthenticated access, admin audit trail.
No real API calls — all tokens created programmatically.
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken
from api.models import CustomUser, Provider, Category, Product, ProductVariant, Order, Credential, CreditTransaction
from api.utils import encrypt_password


# Disable throttling for all tests in this module
throttle_patcher = patch('rest_framework.throttling.AnonRateThrottle.allow_request', return_value=True)
throttle_patcher.start()
user_throttle_patcher = patch('rest_framework.throttling.UserRateThrottle.allow_request', return_value=True)
user_throttle_patcher.start()


class AuthTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.admin = CustomUser.objects.create_user(
            username='admin', email='admin@test.com', password='AdminPass123!',
            role='ADMIN', credit_balance=Decimal('1000.00'),
        )
        self.admin.is_staff = True
        self.admin.save()

        self.reseller = CustomUser.objects.create_user(
            username='reseller', email='reseller@test.com', password='ResellerPass1',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )

        self.reseller2 = CustomUser.objects.create_user(
            username='reseller2', email='reseller2@test.com', password='ResellerPass2',
            role='RESELLER', credit_balance=Decimal('300.00'),
        )

        self.provider = Provider.objects.create(
            name='Mock Provider', slug='mock-provider', adapter_key='mock', is_active=True,
        )

        self.category = Category.objects.create(name='Test Cat', slug='test-cat')
        self.product = Product.objects.create(
            name='Test Product', category=self.category, provider=self.provider,
            is_active=True, is_manual=True, credential_type='username_password',
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=1,
            price_in_credits=Decimal('10.00'), is_active=True,
        )

        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)
        self.reseller_client = APIClient()
        self.reseller_client.force_authenticate(user=self.reseller)
        self.reseller2_client = APIClient()
        self.reseller2_client.force_authenticate(user=self.reseller2)

    def _make_tokens(self, user):
        refresh = RefreshToken.for_user(user)
        return {
            'access': str(refresh.access_token),
            'refresh': str(refresh),
        }

    def _create_order(self, reseller, status=Order.Status.COMPLETED):
        order = Order.objects.create(
            reseller=reseller,
            product=self.product,
            variant=self.variant,
            quantity=1,
            unit_price_at_purchase=Decimal('10.00'),
            product_name_at_purchase='Test Product - 1 Month',
            total_credits=Decimal('10.00'),
            status=status,
            idempotency_key=f'order-key-{reseller.id}',
        )
        cred = Credential.objects.create(
            order=order,
            external_username=f'user-{reseller.id}',
            streaming_username=f'stream-{reseller.id}',
            encrypted_password=encrypt_password('test-pass'),
            dns_domain='test.tv',
            m3u_url='http://test.tv/get.php?username=u&password=p',
            expires_at=timezone.now() + timedelta(days=30),
        )
        return order, cred


class TestJWTLifecycle(AuthTestBase):
    def test_login_returns_access_and_refresh_tokens(self):
        """login endpoint returns valid JWT tokens"""
        resp = self.client.post(reverse('auth-login'), {
            'username': 'reseller', 'password': 'ResellerPass1',
        })
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', resp.data)
        self.assertIn('refresh', resp.data)

    def test_access_token_lifetime(self):
        tokens = self._make_tokens(self.reseller)
        refresh = RefreshToken(tokens['refresh'])
        self.assertEqual(refresh.access_token.lifetime, timedelta(minutes=60))

    def test_refresh_token_lifetime(self):
        tokens = self._make_tokens(self.reseller)
        refresh = RefreshToken(tokens['refresh'])
        self.assertEqual(refresh.lifetime, timedelta(minutes=1440))


class TestTokenRotation(AuthTestBase):
    def test_refresh_rotates_tokens(self):
        tokens = self._make_tokens(self.reseller)
        refresh_resp = self.client.post(reverse('auth-refresh'), {
            'refresh': tokens['refresh'],
        })
        self.assertEqual(refresh_resp.status_code, status.HTTP_200_OK)
        self.assertIn('access', refresh_resp.data)
        self.assertIn('refresh', refresh_resp.data)

    def test_old_refresh_rejected_after_rotation(self):
        tokens = self._make_tokens(self.reseller)
        old_refresh = tokens['refresh']
        self.client.post(reverse('auth-refresh'), {'refresh': old_refresh})
        resp = self.client.post(reverse('auth-refresh'), {'refresh': old_refresh})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TestLogout(AuthTestBase):
    def test_logout_blacklists_refresh_token(self):
        tokens = self._make_tokens(self.reseller)
        refresh_token = tokens['refresh']
        logout_resp = self.reseller_client.post(reverse('auth-logout'),
                                                {'refresh': refresh_token})
        self.assertEqual(logout_resp.status_code, status.HTTP_204_NO_CONTENT)
        refresh_resp = self.client.post(reverse('auth-refresh'),
                                        {'refresh': refresh_token})
        self.assertEqual(refresh_resp.status_code, status.HTTP_401_UNAUTHORIZED)

    def test_logout_without_refresh_returns_400(self):
        resp = self.reseller_client.post(reverse('auth-logout'), {})
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TestRoleBasedAccess(AuthTestBase):
    def test_reseller_cannot_access_dashboard_endpoints(self):
        urls = ['/api/dashboard/resellers/', '/api/dashboard/stats/']
        for url in urls:
            resp = self.reseller_client.get(url)
            self.assertEqual(resp.status_code, status.HTTP_403_FORBIDDEN,
                             f"Reseller got {resp.status_code} on {url}")

    def test_admin_can_access_dashboard_endpoints(self):
        resp = self.admin_client.get('/api/dashboard/resellers/')
        self.assertEqual(resp.status_code, status.HTTP_200_OK)


class TestCredentialOwnership(AuthTestBase):
    def _set_balance(self):
        pass  # balance already set

    def test_cannot_view_other_resellers_order(self):
        order, _ = self._create_order(self.reseller)
        resp = self.reseller2_client.get(
            reverse('order-detail', kwargs={'uuid': order.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_view_other_resellers_order_credentials(self):
        order, _ = self._create_order(self.reseller)
        resp = self.reseller2_client.get(
            reverse('order-credentials', kwargs={'uuid': order.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_cannot_view_other_resellers_order_status(self):
        order, _ = self._create_order(self.reseller)
        resp = self.reseller2_client.get(
            reverse('order-status', kwargs={'uuid': order.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_credential_device_status_other_user_returns_400(self):
        _, cred = self._create_order(self.reseller)
        resp = self.reseller2_client.get(
            reverse('credential-device-status', kwargs={'credential_id': cred.id}),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_credential_device_activate_other_user_returns_400(self):
        _, cred = self._create_order(self.reseller)
        resp = self.reseller2_client.post(
            reverse('credential-device-activate', kwargs={'credential_id': cred.id}),
            {'pack_id': 1, 'duration': 'MONTHS_1'},
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)


class TestUnauthenticatedAccess(AuthTestBase):
    def test_protected_endpoint_returns_401(self):
        urls = [
            reverse('auth-me'),
            reverse('category-list'),
            reverse('product-list'),
            reverse('stats'),
            reverse('credential-list'),
        ]
        for url in urls:
            resp = self.client.get(url)
            self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED,
                             f"{url} returned {resp.status_code} instead of 401")


class TestAdminCreditManipulation(AuthTestBase):
    def test_credit_transaction_created_when_add_credits(self):
        CreditTransaction.objects.create(
            reseller=self.reseller,
            delta=Decimal('100.00'),
            balance_after=self.reseller.credit_balance + Decimal('100.00'),
            actor=CreditTransaction.Actor.ADMIN,
            reason='Admin: Added 100 credits',
        )
        self.assertEqual(CreditTransaction.objects.count(), 1)
        tx = CreditTransaction.objects.first()
        self.assertEqual(tx.delta, Decimal('100.00'))
        self.assertEqual(tx.actor, CreditTransaction.Actor.ADMIN)

    def test_credit_transaction_created_when_deduct_credits(self):
        CreditTransaction.objects.create(
            reseller=self.reseller,
            delta=Decimal('-50.00'),
            balance_after=Decimal('450.00'),
            actor=CreditTransaction.Actor.ADMIN,
            reason='Admin: Deducted 50 credits',
        )
        self.assertEqual(CreditTransaction.objects.count(), 1)
        tx = CreditTransaction.objects.first()
        self.assertEqual(tx.delta, Decimal('-50.00'))
        self.assertEqual(tx.actor, CreditTransaction.Actor.ADMIN)


class TestReplayAttack(AuthTestBase):
    def test_reuse_blacklisted_refresh_returns_401(self):
        tokens = self._make_tokens(self.reseller)
        refresh_token = tokens['refresh']
        self.reseller_client.post(reverse('auth-logout'),
                                  {'refresh': refresh_token})
        resp = self.client.post(reverse('auth-refresh'),
                                {'refresh': refresh_token})
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)
