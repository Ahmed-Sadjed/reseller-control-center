"""
Dashboard API tests.

All tests use Django's test database and mock data only.
No real provider API calls are made — tests only cover:
  - Reseller management (CRUD, credits, toggle)
  - Manual product credential management
  - Analytics endpoints
  - Permission enforcement
"""
from decimal import Decimal
from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APIClient
from api.models import CustomUser, Product, ProductVariant, Order, CreditTransaction, Category, Provider
from dashboard.models import ManualProductCredential


class DashboardTestBase(TestCase):
    """Base class with shared fixtures — no real API provider calls."""

    def setUp(self):
        # Create admin user
        self.admin = CustomUser.objects.create_user(
            username='admin_test',
            email='admin@test.local',
            password='admin123',
            role='ADMIN',
        )
        self.admin.is_staff = True
        self.admin.save()

        # Create reseller user
        self.reseller = CustomUser.objects.create_user(
            username='reseller_test',
            email='reseller@test.local',
            password='reseller123',
            role='RESELLER',
            credit_balance=Decimal('500.00'),
        )

        # Create another reseller for list tests
        self.reseller2 = CustomUser.objects.create_user(
            username='reseller_two',
            email='reseller2@test.local',
            password='reseller123',
            role='RESELLER',
            credit_balance=Decimal('100.00'),
        )

        # Create category and provider (mock — no real API)
        self.category = Category.objects.create(
            name='Test Category',
            slug='test-category',
        )
        self.provider = Provider.objects.create(
            name='Mock Provider',
            slug='mock-provider',
            adapter_key='mock',
            is_active=True,
        )

        # Create a manual product
        self.manual_product = Product.objects.create(
            name='Gaming Credit 1K',
            category=self.category,
            provider=self.provider,
            is_active=True,
            is_manual=True,
            credential_type='username_password',
        )

        # Create a manual single-code product
        self.code_product = Product.objects.create(
            name='Gift Card $10',
            category=self.category,
            provider=self.provider,
            is_active=True,
            is_manual=True,
            credential_type='single_code',
        )

        # Create variants for manual products (needed for purchase flow)
        self.manual_variant = ProductVariant.objects.create(
            product=self.manual_product,
            duration_months=1,
            external_pack_id=9999,
            price_in_credits=Decimal('10.00'),
            is_active=True,
        )

        # Create a NON-manual (API-driven) product — we will NOT test purchases on this
        self.api_product = Product.objects.create(
            name='IPTV Subscription',
            category=self.category,
            provider=self.provider,
            is_active=True,
            is_manual=False,
        )

        # Create some credentials for the manual product
        self.cred1 = ManualProductCredential.objects.create(
            product=self.manual_product,
            credential_type='username_password',
            username='gamer123',
            password='pass123',
            status='available',
            created_by=self.admin,
        )
        self.cred2 = ManualProductCredential.objects.create(
            product=self.manual_product,
            credential_type='username_password',
            username='gamer456',
            password='pass456',
            status='used',
            assigned_to=self.reseller,
            created_by=self.admin,
        )
        self.code_cred = ManualProductCredential.objects.create(
            product=self.code_product,
            credential_type='single_code',
            code='GIFT-ABC-123-XYZ',
            status='available',
            created_by=self.admin,
        )

        # Create a completed order for analytics
        self.order = Order.objects.create(
            reseller=self.reseller,
            product=self.manual_product,
            variant=self.manual_variant,
            quantity=1,
            unit_price_at_purchase=Decimal('10.00'),
            product_name_at_purchase='Gaming Credit 1K - 1 Month',
            total_credits=Decimal('10.00'),
            status='COMPLETED',
            idempotency_key='test-key-1',
        )

        # Create credit transaction
        CreditTransaction.objects.create(
            reseller=self.reseller,
            delta=Decimal('500.00'),
            balance_after=Decimal('500.00'),
            actor='ADMIN',
            reason='Initial credits',
        )

        # API clients
        self.admin_client = APIClient()
        self.admin_client.force_authenticate(user=self.admin)

        self.reseller_client = APIClient()
        self.reseller_client.force_authenticate(user=self.reseller)

        self.anon_client = APIClient()


# ─────────────────────────────────────────────────
# Permission Tests
# ─────────────────────────────────────────────────

class PermissionTests(DashboardTestBase):
    """Verify ADMIN-only access. No API provider calls."""

    def test_reseller_cannot_access_dashboard_endpoints(self):
        """Resellers should get 403 on all dashboard endpoints."""
        endpoints = [
            '/api/dashboard/resellers/',
            '/api/dashboard/stats/',
            '/api/dashboard/top-resellers/',
            '/api/dashboard/manual-products/',
        ]
        for url in endpoints:
            resp = self.reseller_client.get(url)
            self.assertEqual(resp.status_code, 403, f"Reseller should be denied access to {url}")

    def test_anonymous_cannot_access_dashboard(self):
        """Unauthenticated requests should get 401."""
        resp = self.anon_client.get('/api/dashboard/resellers/')
        self.assertEqual(resp.status_code, 401)

    def test_admin_can_access_dashboard(self):
        """Admin should get 200 on dashboard endpoints."""
        resp = self.admin_client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────────────
# Reseller Management Tests
# ─────────────────────────────────────────────────

class ResellerManagementTests(DashboardTestBase):
    """Test reseller CRUD — no API provider calls."""

    def test_list_resellers(self):
        resp = self.admin_client.get('/api/dashboard/resellers/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        # Should be paginated
        self.assertIn('results', data)
        usernames = [r['username'] for r in data['results']]
        self.assertIn('reseller_test', usernames)
        self.assertIn('reseller_two', usernames)

    def test_list_resellers_search(self):
        resp = self.admin_client.get('/api/dashboard/resellers/?search=reseller_two')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(len(resp.data['results']), 1)
        self.assertEqual(resp.data['results'][0]['username'], 'reseller_two')

    def test_list_resellers_filter_active(self):
        resp = self.admin_client.get('/api/dashboard/resellers/?status=active')
        self.assertEqual(resp.status_code, 200)
        for r in resp.data['results']:
            self.assertTrue(r['is_active'])

    def test_create_reseller(self):
        resp = self.admin_client.post('/api/dashboard/resellers/', {
            'username': 'new_reseller',
            'password': 'newpass123',
            'password_confirm': 'newpass123',
            'initial_credits': '50.00',
        })
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['username'], 'new_reseller')
        self.assertEqual(Decimal(str(resp.data['credit_balance'])), Decimal('50.00'))

        # Verify user exists in DB
        user = CustomUser.objects.get(username='new_reseller')
        self.assertEqual(user.role, 'RESELLER')
        self.assertEqual(user.credit_balance, Decimal('50.00'))
        self.assertEqual(user.created_by, self.admin)

    def test_create_reseller_password_mismatch(self):
        resp = self.admin_client.post('/api/dashboard/resellers/', {
            'username': 'bad_user',
            'password': 'pass123',
            'password_confirm': 'different',
        })
        self.assertEqual(resp.status_code, 400)

    def test_create_reseller_duplicate_username(self):
        resp = self.admin_client.post('/api/dashboard/resellers/', {
            'username': 'reseller_test',  # already exists
            'password': 'pass123',
            'password_confirm': 'pass123',
        })
        self.assertEqual(resp.status_code, 400)

    def test_get_reseller_detail(self):
        resp = self.admin_client.get(f'/api/dashboard/resellers/{self.reseller.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.data['username'], 'reseller_test')
        self.assertIn('order_count', resp.data)
        self.assertIn('total_revenue', resp.data)

    def test_update_reseller_username(self):
        resp = self.admin_client.put(f'/api/dashboard/resellers/{self.reseller.id}/', {
            'username': 'reseller_renamed',
        })
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertEqual(self.reseller.username, 'reseller_renamed')

    def test_update_reseller_password(self):
        resp = self.admin_client.put(f'/api/dashboard/resellers/{self.reseller.id}/', {
            'password': 'newpassword123',
        })
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertTrue(self.reseller.check_password('newpassword123'))

    def test_toggle_reseller(self):
        self.assertTrue(self.reseller.is_active)
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/toggle/')
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertFalse(self.reseller.is_active)

        # Toggle back
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/toggle/')
        self.reseller.refresh_from_db()
        self.assertTrue(self.reseller.is_active)

    def test_soft_delete_reseller(self):
        resp = self.admin_client.delete(f'/api/dashboard/resellers/{self.reseller.id}/')
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertFalse(self.reseller.is_active)
        # User still exists in DB
        self.assertTrue(CustomUser.objects.filter(id=self.reseller.id).exists())


# ─────────────────────────────────────────────────
# Credit Management Tests
# ─────────────────────────────────────────────────

class CreditManagementTests(DashboardTestBase):
    """Test credit add/remove — no API provider calls."""

    def test_add_credits(self):
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/credits/', {
            'amount': '100.00',
            'reason': 'Test top-up',
        })
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertEqual(self.reseller.credit_balance, Decimal('600.00'))

    def test_deduct_credits(self):
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/credits/', {
            'amount': '-50.00',
            'reason': 'Test deduction',
        })
        self.assertEqual(resp.status_code, 200)
        self.reseller.refresh_from_db()
        self.assertEqual(self.reseller.credit_balance, Decimal('450.00'))

    def test_deduct_more_than_balance(self):
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/credits/', {
            'amount': '-999.00',
            'reason': 'Over-deduction',
        })
        self.assertEqual(resp.status_code, 400)
        self.reseller.refresh_from_db()
        self.assertEqual(self.reseller.credit_balance, Decimal('500.00'))  # unchanged

    def test_zero_amount_rejected(self):
        resp = self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/credits/', {
            'amount': '0',
            'reason': 'Zero',
        })
        self.assertEqual(resp.status_code, 400)

    def test_credit_transaction_created(self):
        initial_count = CreditTransaction.objects.filter(reseller=self.reseller).count()
        self.admin_client.post(f'/api/dashboard/resellers/{self.reseller.id}/credits/', {
            'amount': '25.00',
            'reason': 'Transaction test',
        })
        new_count = CreditTransaction.objects.filter(reseller=self.reseller).count()
        self.assertEqual(new_count, initial_count + 1)

    def test_list_transactions(self):
        resp = self.admin_client.get(f'/api/dashboard/resellers/{self.reseller.id}/transactions/')
        self.assertEqual(resp.status_code, 200)

    def test_list_orders(self):
        resp = self.admin_client.get(f'/api/dashboard/resellers/{self.reseller.id}/orders/')
        self.assertEqual(resp.status_code, 200)


# ─────────────────────────────────────────────────
# Manual Product & Credential Tests
# ─────────────────────────────────────────────────

class ManualProductTests(DashboardTestBase):
    """Test manual product credential management — no API provider calls."""

    def test_list_manual_products(self):
        resp = self.admin_client.get('/api/dashboard/manual-products/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        results = data.get('results', data)
        names = [p['name'] for p in results]
        self.assertIn('Gaming Credit 1K', names)
        self.assertIn('Gift Card $10', names)

    def test_manual_product_detail_with_credentials(self):
        resp = self.admin_client.get(f'/api/dashboard/manual-products/{self.manual_product.id}/')
        self.assertEqual(resp.status_code, 200)
        self.assertIn('product', resp.data)
        self.assertIn('stats', resp.data)
        self.assertEqual(resp.data['product']['name'], 'Gaming Credit 1K')
        self.assertEqual(resp.data['stats']['available'], 1)
        self.assertEqual(resp.data['stats']['used'], 1)

    def test_add_username_password_credential(self):
        resp = self.admin_client.post(
            f'/api/dashboard/manual-products/{self.manual_product.id}/credentials/',
            {
                'username': 'newgamer',
                'password': 'newpass',
                'notes': 'Test credential',
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['username'], 'newgamer')
        self.assertEqual(resp.data['status'], 'available')

    def test_add_single_code_credential(self):
        resp = self.admin_client.post(
            f'/api/dashboard/manual-products/{self.code_product.id}/credentials/',
            {
                'code': 'NEW-CODE-XYZ',
            },
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['code'], 'NEW-CODE-XYZ')

    def test_add_credential_missing_required_field(self):
        # Username/password product but no username provided
        resp = self.admin_client.post(
            f'/api/dashboard/manual-products/{self.manual_product.id}/credentials/',
            {
                'notes': 'Missing required fields',
            },
        )
        self.assertEqual(resp.status_code, 400)

    def test_bulk_add_credentials(self):
        resp = self.admin_client.post(
            f'/api/dashboard/manual-products/{self.manual_product.id}/credentials/bulk/',
            {
                'credentials': [
                    {'username': 'bulk1', 'password': 'bp1'},
                    {'username': 'bulk2', 'password': 'bp2'},
                    {'username': 'bulk3', 'password': 'bp3'},
                ],
            },
            format='json',
        )
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.data['count'], 3)

    def test_update_credential(self):
        resp = self.admin_client.put(
            f'/api/dashboard/credentials/{self.cred1.id}/',
            {'notes': 'Updated note'},
            format='json',
        )
        self.assertEqual(resp.status_code, 200)
        self.cred1.refresh_from_db()
        self.assertEqual(self.cred1.notes, 'Updated note')

    def test_delete_credential(self):
        resp = self.admin_client.delete(f'/api/dashboard/credentials/{self.cred1.id}/')
        self.assertEqual(resp.status_code, 204)
        self.assertFalse(ManualProductCredential.objects.filter(id=self.cred1.id).exists())

    def test_filter_credentials_by_status(self):
        resp = self.admin_client.get(
            f'/api/dashboard/manual-products/{self.manual_product.id}/?status=available'
        )
        self.assertEqual(resp.status_code, 200)
        for c in resp.data.get('results', []):
            self.assertEqual(c['status'], 'available')

    def test_non_manual_product_returns_404(self):
        resp = self.admin_client.get(f'/api/dashboard/manual-products/{self.api_product.id}/')
        self.assertEqual(resp.status_code, 404)


# ─────────────────────────────────────────────────
# Analytics Tests
# ─────────────────────────────────────────────────

class AnalyticsTests(DashboardTestBase):
    """Test analytics endpoints — no API provider calls."""

    def test_dashboard_stats(self):
        resp = self.admin_client.get('/api/dashboard/stats/')
        self.assertEqual(resp.status_code, 200)
        data = resp.data
        self.assertIn('total_resellers', data)
        self.assertIn('total_orders', data)
        self.assertIn('total_revenue', data)
        self.assertIn('available_credentials', data)
        self.assertEqual(data['total_resellers'], 2)  # reseller_test + reseller_two
        self.assertEqual(data['total_orders'], 1)

    def test_top_resellers(self):
        resp = self.admin_client.get('/api/dashboard/top-resellers/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_recent_activity(self):
        resp = self.admin_client.get('/api/dashboard/recent-activity/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_revenue_chart(self):
        resp = self.admin_client.get('/api/dashboard/revenue-chart/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)

    def test_provider_health(self):
        resp = self.admin_client.get('/api/dashboard/provider-health/')
        self.assertEqual(resp.status_code, 200)
        self.assertIsInstance(resp.data, list)
        if resp.data:
            self.assertIn('name', resp.data[0])
            self.assertIn('error_rate', resp.data[0])


# ─────────────────────────────────────────────────
# Manual Purchase Flow Tests (NO real API calls)
# ─────────────────────────────────────────────────

class ManualPurchaseFlowTests(DashboardTestBase):
    """
    Test the purchase flow for MANUAL products only.
    This does NOT test API-driven products — no real provider calls.
    """

    def test_manual_purchase_assigns_credential(self):
        """Buying a manual product should assign an available credential."""
        from api.services import reserve_phase, fulfill_sync

        # Pre-check: 1 available credential
        available_before = ManualProductCredential.objects.filter(
            product=self.manual_product, status='available',
        ).count()
        self.assertEqual(available_before, 1)

        # Reserve and fulfill
        order = reserve_phase(
            self.reseller, self.manual_variant, 1, 'manual-purchase-test-1',
        )
        credentials, failure = fulfill_sync(order)

        # Assertions
        self.assertIsNone(failure)
        self.assertEqual(len(credentials), 1)
        self.assertEqual(order.status, 'COMPLETED')

        # Credential should be marked as used
        self.cred1.refresh_from_db()
        self.assertEqual(self.cred1.status, 'used')
        self.assertEqual(self.cred1.assigned_to, self.reseller)

        # The Credential record should contain manual data
        cred = credentials[0]
        self.assertTrue(cred.data.get('manual'))
        self.assertEqual(cred.data.get('credential_type'), 'username_password')

    def test_manual_purchase_out_of_stock(self):
        """Buying a manual product with no available credentials fails gracefully."""
        from api.services import reserve_phase, fulfill_sync

        # Use up the only available credential
        self.cred1.status = 'used'
        self.cred1.save()

        order = reserve_phase(
            self.reseller, self.manual_variant, 1, 'manual-purchase-test-2',
        )
        credentials, failure = fulfill_sync(order)

        # Should fail with out of stock
        self.assertEqual(len(credentials), 0)
        self.assertIn('out of stock', failure)

        # Order should be refunded
        order.refresh_from_db()
        self.assertEqual(order.status, 'FAILED')

    def test_api_product_not_tested_for_real_purchase(self):
        """
        Explicit assertion that we do NOT test real API provider purchases.
        This test exists only to document the boundary.
        """
        self.assertFalse(
            self.api_product.is_manual,
            "API-driven products are not tested for purchase in dashboard tests.",
        )
