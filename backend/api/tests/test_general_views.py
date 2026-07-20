"""
General API View Tests
======================
Category listing, product listing with search/filter, pagination,
order CRUD, credential listing, health check, stats.
No real API calls — all data is test-local.
"""
from decimal import Decimal
from datetime import timedelta
from unittest.mock import patch

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient
from rest_framework import status


# Disable throttling for all tests in this module
patch('rest_framework.throttling.AnonRateThrottle.allow_request', return_value=True).start()
patch('rest_framework.throttling.UserRateThrottle.allow_request', return_value=True).start()

from api.models import (
    CustomUser, Provider, Category, Product, ProductVariant,
    Order, Credential,
)
from api.utils import encrypt_password


class ViewsTestBase(TestCase):
    def setUp(self):
        self.client = APIClient()

        self.reseller = CustomUser.objects.create_user(
            username='reseller', email='r@test.com', password='pass123',
            role='RESELLER', credit_balance=Decimal('500.00'),
        )
        self.auth_client = APIClient()
        self.auth_client.force_authenticate(user=self.reseller)

        self.provider = Provider.objects.create(
            name='Mock Provider', slug='mock-prov', adapter_key='mock', is_active=True,
        )
        self.provider2 = Provider.objects.create(
            name='HotPlayer', slug='hotplayer', adapter_key='hotplayer', is_active=True,
        )


class TestCategoryList(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat1 = Category.objects.create(
            name='CatIPTV', slug='cat-iptv', is_active=True, sort_order=1,
        )
        self.cat2 = Category.objects.create(
            name='CatGaming', slug='cat-gaming', is_active=True, sort_order=2,
        )
        self.cat_inactive = Category.objects.create(
            name='CatHidden', slug='cat-hidden', is_active=False, sort_order=99,
        )

    def test_list_active_categories(self):
        resp = self.auth_client.get(reverse('category-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        slugs = [c['slug'] for c in resp.data]
        self.assertIn('cat-iptv', slugs)
        self.assertIn('cat-gaming', slugs)
        self.assertNotIn('cat-hidden', slugs)

    def test_categories_sorted_by_sort_order(self):
        resp = self.auth_client.get(reverse('category-list'))
        slugs = [c['slug'] for c in resp.data]
        cat_iptv_idx = slugs.index('cat-iptv')
        cat_gaming_idx = slugs.index('cat-gaming')
        self.assertLess(cat_iptv_idx, cat_gaming_idx,
                        'cat-iptv (sort_order=1) should appear before cat-gaming (sort_order=2)')


class TestProductList(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='ProdCat', slug='prod-cat', is_active=True)
        self.cat2 = Category.objects.create(name='GameCat', slug='game-cat', is_active=True)
        self.product = Product.objects.create(
            name='IPTV Premium', category=self.cat, provider=self.provider,
            description='Best IPTV', is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=1,
            price_in_credits=Decimal('20.00'), is_active=True,
        )
        self.variant2 = ProductVariant.objects.create(
            product=self.product, duration_months=12, external_pack_id=2,
            price_in_credits=Decimal('120.00'), is_active=True,
        )
        self.product2 = Product.objects.create(
            name='Gaming Pack', category=self.cat2, provider=self.provider2,
            description='Gaming sub', is_active=True,
        )
        self.variant3 = ProductVariant.objects.create(
            product=self.product2, duration_months=1, external_pack_id=3,
            price_in_credits=Decimal('15.00'), is_active=True,
        )
        self.inactive_prod = Product.objects.create(
            name='Old Product', category=self.cat, provider=self.provider,
            is_active=False,
        )

    def test_list_active_products(self):
        resp = self.auth_client.get(reverse('product-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('IPTV Premium', names)
        self.assertIn('Gaming Pack', names)
        self.assertNotIn('Old Product', names)

    def test_product_has_variants(self):
        resp = self.auth_client.get(reverse('product-list'))
        for p in resp.data['results']:
            if p['name'] == 'IPTV Premium':
                self.assertEqual(len(p['variants']), 2)

    def test_product_returns_metadata(self):
        resp = self.auth_client.get(reverse('product-list'))
        for p in resp.data['results']:
            self.assertIn('category_name', p)
            self.assertIn('category_slug', p)
            self.assertIn('provider_name', p)
            self.assertIn('provider_key', p)

    def test_filter_by_category(self):
        resp = self.auth_client.get(reverse('product-list'),
                                    {'category': 'game-cat'})
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Gaming Pack', names)
        self.assertNotIn('IPTV Premium', names)

    def test_filter_by_provider(self):
        resp = self.auth_client.get(reverse('product-list'),
                                    {'provider': self.provider2.id})
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Gaming Pack', names)
        self.assertNotIn('IPTV Premium', names)

    def test_pagination_default_page_size(self):
        for i in range(25):
            Product.objects.create(
                name=f'Bulk Product {i}', category=self.cat,
                provider=self.provider, is_active=True,
            )
        resp = self.auth_client.get(reverse('product-list'))
        self.assertEqual(len(resp.data['results']), 20)
        self.assertIsNotNone(resp.data['next'])

    def test_inactive_category_products_visibility(self):
        """
        NOTE: ProductListView does NOT filter by category__is_active.
        Products in inactive categories still appear if the product
        itself is active. This may be intentional or a gap.
        """
        inactive_cat = Category.objects.create(
            name='HiddenCat', slug='hidden-cat', is_active=False,
        )
        Product.objects.create(
            name='Hidden Product', category=inactive_cat,
            provider=self.provider, is_active=True,
        )
        resp = self.auth_client.get(reverse('product-list'))
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Hidden Product', names,
                      'Known: ProductListView does not filter by category__is_active')


class TestProductSearch(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='SearchCat', slug='search-cat', is_active=True)
        Product.objects.create(
            name='Searchable Premium', category=self.cat, provider=self.provider,
            is_active=True,
        )

    def test_search_by_name(self):
        resp = self.auth_client.get(reverse('product-list'),
                                    {'search': 'Premium'})
        names = [p['name'] for p in resp.data['results']]
        self.assertIn('Searchable Premium', names)

    def test_search_no_results(self):
        resp = self.auth_client.get(reverse('product-list'),
                                    {'search': 'NonexistentProductXYZ'})
        self.assertEqual(len(resp.data['results']), 0)


class TestOrderViews(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='OrderCat', slug='order-cat', is_active=True)
        self.product = Product.objects.create(
            name='Order Product', category=self.cat, provider=self.provider,
            is_active=True,
        )
        self.variant = ProductVariant.objects.create(
            product=self.product, duration_months=1, external_pack_id=10,
            price_in_credits=Decimal('20.00'), is_active=True,
        )
        self.product2 = Product.objects.create(
            name='Order Product2', category=self.cat, provider=self.provider,
            is_active=True,
        )
        self.variant3 = ProductVariant.objects.create(
            product=self.product2, duration_months=1, external_pack_id=11,
            price_in_credits=Decimal('15.00'), is_active=True,
        )
        self.order1 = Order.objects.create(
            reseller=self.reseller, product=self.product, variant=self.variant,
            quantity=2, unit_price_at_purchase=Decimal('20.00'),
            product_name_at_purchase='Order Product - 1 Month',
            total_credits=Decimal('40.00'), status=Order.Status.COMPLETED,
            idempotency_key='ov-order-1',
        )
        self.order2 = Order.objects.create(
            reseller=self.reseller, product=self.product2, variant=self.variant3,
            quantity=1, unit_price_at_purchase=Decimal('15.00'),
            product_name_at_purchase='Order Product2 - 1 Month',
            total_credits=Decimal('15.00'), status=Order.Status.PENDING,
            idempotency_key='ov-order-2',
        )
        self.cred = Credential.objects.create(
            order=self.order1,
            external_username='ext-1',
            streaming_username='stream-1',
            encrypted_password=encrypt_password('secret-pass'),
            dns_domain='test.tv', m3u_url='',
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_order_list_returns_user_orders(self):
        resp = self.auth_client.get(reverse('order-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data['results']), 2)

    def test_order_detail_by_uuid(self):
        resp = self.auth_client.get(
            reverse('order-detail', kwargs={'uuid': self.order1.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['status'], Order.Status.COMPLETED)

    def test_order_detail_not_found_for_wrong_user(self):
        other_user = CustomUser.objects.create_user(
            username='other', email='o@test.com', password='pass123',
            role='RESELLER',
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(
            reverse('order-detail', kwargs={'uuid': self.order1.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_404_NOT_FOUND)

    def test_order_credentials(self):
        resp = self.auth_client.get(
            reverse('order-credentials', kwargs={'uuid': self.order1.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(len(resp.data), 1)

    def test_order_credentials_fails_for_pending_order(self):
        resp = self.auth_client.get(
            reverse('order-credentials', kwargs={'uuid': self.order2.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_400_BAD_REQUEST)

    def test_order_status(self):
        resp = self.auth_client.get(
            reverse('order-status', kwargs={'uuid': self.order1.uuid}),
        )
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('status', resp.data)
        self.assertIn('order_id', resp.data)

    def test_order_list_excludes_other_resellers(self):
        other_user = CustomUser.objects.create_user(
            username='other2', email='o2@test.com', password='pass123',
            role='RESELLER',
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(reverse('order-list'))
        self.assertEqual(len(resp.data['results']), 0)


class TestCredentialListView(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='CredCat', slug='cred-cat', is_active=True)
        prod = Product.objects.create(
            name='Cred Product', category=self.cat, provider=self.provider,
            is_active=True,
        )
        variant = ProductVariant.objects.create(
            product=prod, duration_months=1, external_pack_id=20,
            price_in_credits=Decimal('20.00'), is_active=True,
        )
        completed_order = Order.objects.create(
            reseller=self.reseller, product=prod, variant=variant,
            quantity=1, unit_price_at_purchase=Decimal('20.00'),
            product_name_at_purchase='Cred Product - 1 Month',
            total_credits=Decimal('20.00'), status=Order.Status.COMPLETED,
            idempotency_key='cred-list-key',
        )
        self.cred = Credential.objects.create(
            order=completed_order,
            external_username='cred-ext',
            streaming_username='cred-stream',
            encrypted_password=encrypt_password('secret-1'),
            dns_domain='test.tv', m3u_url='',
            expires_at=timezone.now() + timedelta(days=30),
        )

    def test_credential_list_returns_user_credentials(self):
        resp = self.auth_client.get(reverse('credential-list'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertGreater(len(resp.data['results']), 0)

    def test_credential_list_excludes_other_users(self):
        other_user = CustomUser.objects.create_user(
            username='other3', email='o3@test.com', password='pass123',
            role='RESELLER',
        )
        other_client = APIClient()
        other_client.force_authenticate(user=other_user)
        resp = other_client.get(reverse('credential-list'))
        self.assertEqual(len(resp.data['results']), 0)

    def test_credential_list_filter_by_provider(self):
        resp = self.auth_client.get(reverse('credential-list'),
                                    {'provider': 'mock'})
        self.assertEqual(resp.status_code, status.HTTP_200_OK)

    def test_credential_list_does_not_expose_password(self):
        resp = self.auth_client.get(reverse('credential-list'))
        for cred in resp.data['results']:
            self.assertNotIn('password', cred)


class TestStatsView(ViewsTestBase):
    def setUp(self):
        super().setUp()
        self.cat = Category.objects.create(name='StatsCat', slug='stats-cat', is_active=True)
        prod = Product.objects.create(
            name='Stats Product', category=self.cat, provider=self.provider,
            is_active=True,
        )

    def test_stats_returns_counts_and_balance(self):
        resp = self.auth_client.get(reverse('stats'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('total_products', resp.data)
        self.assertIn('total_categories', resp.data)
        self.assertIn('credit_balance', resp.data)

    def test_stats_returns_live_credit_balance(self):
        resp = self.auth_client.get(reverse('stats'))
        self.assertEqual(resp.data['credit_balance'], Decimal('500.00'))

    def test_stats_only_counts_active(self):
        Category.objects.create(name='StatsInactive', slug='stats-inactive', is_active=False)
        resp = self.auth_client.get(reverse('stats'))
        active_count = Category.objects.filter(is_active=True).count()
        self.assertEqual(resp.data['total_categories'], active_count)


class TestMeView(ViewsTestBase):
    def test_me_returns_user_profile(self):
        resp = self.auth_client.get(reverse('auth-me'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertEqual(resp.data['username'], 'reseller')
        self.assertEqual(resp.data['role'], 'RESELLER')

    def test_me_without_auth_returns_401(self):
        resp = self.client.get(reverse('auth-me'))
        self.assertEqual(resp.status_code, status.HTTP_401_UNAUTHORIZED)


class TestHealthCheck(ViewsTestBase):
    def test_health_check_allow_any(self):
        resp = self.client.get(reverse('health'))
        self.assertEqual(resp.status_code, status.HTTP_200_OK)
        self.assertIn('status', resp.data)
        self.assertIn('database', resp.data)
        self.assertIn('cache', resp.data)
        self.assertIn('rq_redis', resp.data)
