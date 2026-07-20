import logging
from decimal import Decimal
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from api.models import CustomUser, Product, ProductVariant, Category, Provider, Order, CreditTransaction
from .models import ManualProductCredential
from .permissions import IsSuperAdmin
from .serializers import (
    ResellerListSerializer, ResellerDetailSerializer,
    ResellerCreateSerializer, ResellerUpdateSerializer,
    CreditAdjustSerializer, CreditTransactionSerializer,
    OrderListAdminSerializer,
    ManualProductListSerializer, CredentialSerializer,
    CredentialCreateSerializer, CredentialBulkCreateSerializer,
    DashboardStatsSerializer, TopResellerSerializer,
    RecentActivitySerializer,
    WhatsAppOrderSerializer,
    CategorySerializer, ProviderSerializer,
    ProductListSerializer, ProductCreateSerializer,
    ProductUpdateSerializer, ProductVariantSerializer,
)
from .services import (
    get_dashboard_stats, get_top_resellers, get_recent_activity,
    get_provider_health, adjust_credits,
)

logger = logging.getLogger(__name__)


class DashboardPaginationMixin:
    """Reusable pagination for dashboard views."""

    @property
    def paginator(self):
        if not hasattr(self, '_paginator'):
            from rest_framework.pagination import PageNumberPagination
            self._paginator = PageNumberPagination()
            self._paginator.page_size = 20
            self._paginator.page_size_query_param = 'page_size'
        return self._paginator

    def paginate_queryset(self, queryset, request):
        return self.paginator.paginate_queryset(queryset, request)

    def get_paginated_response(self, data):
        return self.paginator.get_paginated_response(data)


# ──────────────────────────────────────────────
# Reseller Management Views
# ──────────────────────────────────────────────

class ResellerListCreateView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        resellers = (
            CustomUser.objects.filter(role='RESELLER')
            .annotate(
                order_count=Count('orders', filter=Q(orders__status='COMPLETED')),
                total_revenue=Sum('orders__total_credits', filter=Q(orders__status='COMPLETED')),
            )
            .order_by('-date_joined')
        )

        search = request.query_params.get('search', '').strip()
        if search:
            resellers = resellers.filter(username__icontains=search)

        status_filter = request.query_params.get('status', '').strip()
        if status_filter == 'active':
            resellers = resellers.filter(is_active=True)
        elif status_filter == 'inactive':
            resellers = resellers.filter(is_active=False)

        page = self.paginate_queryset(resellers, request)
        if page is not None:
            serializer = ResellerListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ResellerListSerializer(resellers, many=True)
        return Response(serializer.data)

    def post(self, request):
        serializer = ResellerCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        username = data['username']

        # Auto-generate placeholder email since the field is required+unique
        email = f"{username}@reseller.local"
        counter = 1
        while CustomUser.objects.filter(email=email).exists():
            email = f"{username}{counter}@reseller.local"
            counter += 1

        user = CustomUser.objects.create_user(
            username=username,
            email=email,
            password=data['password'],
            role=CustomUser.Role.RESELLER,
            created_by=request.user,
        )

        initial_credits = data.get('initial_credits', Decimal('0.00'))
        if initial_credits and initial_credits > 0:
            user.credit_balance = initial_credits
            user.save()
            CreditTransaction.objects.create(
                reseller=user,
                delta=initial_credits,
                balance_after=initial_credits,
                actor=CreditTransaction.Actor.ADMIN,
                reason='Initial credits on account creation',
            )

        detail_serializer = ResellerDetailSerializer(user)
        return Response(detail_serializer.data, status=status.HTTP_201_CREATED)


class ResellerDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        serializer = ResellerDetailSerializer(reseller)
        return Response(serializer.data)

    def put(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        serializer = ResellerUpdateSerializer(
            data=request.data, context={'reseller': reseller},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        if 'username' in data:
            reseller.username = data['username']
        if 'password' in data:
            reseller.set_password(data['password'])
        if 'is_active' in data:
            reseller.is_active = data['is_active']
        reseller.save()

        return Response(ResellerDetailSerializer(reseller).data)

    def delete(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        reseller.is_active = False
        reseller.save()
        return Response({'detail': 'Reseller deactivated.'}, status=status.HTTP_200_OK)


class ResellerCreditView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        serializer = CreditAdjustSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        try:
            updated_reseller = adjust_credits(
                reseller=reseller,
                amount=serializer.validated_data['amount'],
                reason=serializer.validated_data['reason'],
                admin_user=request.user,
            )
        except ValueError as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'credit_balance': updated_reseller.credit_balance,
            'detail': 'Credits updated successfully.',
        })


class ResellerTransactionsView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        transactions = CreditTransaction.objects.filter(
            reseller=reseller,
        ).order_by('-created_at')

        page = self.paginate_queryset(transactions, request)
        if page is not None:
            serializer = CreditTransactionSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CreditTransactionSerializer(transactions, many=True)
        return Response(serializer.data)


class ResellerOrdersView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        orders = Order.objects.filter(reseller=reseller).order_by('-created_at')

        page = self.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderListAdminSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = OrderListAdminSerializer(orders, many=True)
        return Response(serializer.data)


class ResellerToggleView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        reseller = get_object_or_404(CustomUser, pk=pk, role='RESELLER')
        reseller.is_active = not reseller.is_active
        reseller.save()
        return Response({
            'is_active': reseller.is_active,
            'detail': f"Reseller {'activated' if reseller.is_active else 'deactivated'}.",
        })


# ──────────────────────────────────────────────
# Manual Product & Credential Views
# ──────────────────────────────────────────────

class ManualProductListView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        products = (
            Product.objects.filter(is_manual=True)
            .select_related('category')
            .annotate(
                total_credentials=Count('manual_credentials'),
                available_credentials=Count(
                    'manual_credentials',
                    filter=Q(manual_credentials__status='available'),
                ),
                used_credentials=Count(
                    'manual_credentials',
                    filter=Q(manual_credentials__status='used'),
                ),
            )
            .order_by('name')
        )

        search = request.query_params.get('search', '').strip()
        if search:
            products = products.filter(name__icontains=search)

        page = self.paginate_queryset(products, request)
        if page is not None:
            serializer = ManualProductListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ManualProductListSerializer(products, many=True)
        return Response(serializer.data)


class ManualProductDetailView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, pk):
        product = get_object_or_404(Product, pk=pk, is_manual=True)

        credentials = ManualProductCredential.objects.filter(
            product=product,
        ).select_related('assigned_to').order_by('-created_at')

        status_filter = request.query_params.get('status', '').strip()
        if status_filter:
            credentials = credentials.filter(status=status_filter)

        search = request.query_params.get('search', '').strip()
        if search:
            credentials = credentials.filter(
                Q(username__icontains=search) |
                Q(code__icontains=search) |
                Q(assigned_to__username__icontains=search)
            )

        stats = {
            'total': credentials.count(),
            'available': ManualProductCredential.objects.filter(product=product, status='available').count(),
            'used': ManualProductCredential.objects.filter(product=product, status='used').count(),
        }

        variants = ProductVariant.objects.filter(product=product).values(
            'id', 'duration_months', 'is_lifetime', 'price_in_credits',
        )

        page = self.paginate_queryset(credentials, request)
        if page is not None:
            serializer = CredentialSerializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            response.data['product'] = {
                'id': product.id,
                'name': product.name,
                'credential_type': product.credential_type,
                'is_active': product.is_active,
                'variants': list(variants),
            }
            response.data['stats'] = stats
            return response

        serializer = CredentialSerializer(credentials, many=True)
        return Response({
            'product': {
                'id': product.id,
                'name': product.name,
                'credential_type': product.credential_type,
                'is_active': product.is_active,
                'variants': list(variants),
            },
            'stats': stats,
            'results': serializer.data,
        })


class CredentialCreateView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk, is_manual=True)
        serializer = CredentialCreateSerializer(
            data=request.data, context={'product': product},
        )
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        data = serializer.validated_data
        variant_id = data.get('variant_id')
        variant = ProductVariant.objects.get(id=variant_id) if variant_id else None

        credential = ManualProductCredential.objects.create(
            product=product,
            variant=variant,
            credential_type=product.credential_type,
            username=data.get('username', ''),
            password=data.get('password', ''),
            code=data.get('code', ''),
            notes=data.get('notes', ''),
            expires_at=data.get('expires_at'),
            created_by=request.user,
        )
        return Response(
            CredentialSerializer(credential).data,
            status=status.HTTP_201_CREATED,
        )


class CredentialBulkCreateView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk, is_manual=True)
        serializer = CredentialBulkCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        credentials_data = serializer.validated_data['credentials']
        created = []
        for item_data in credentials_data:
            # Validate each item against the product context
            item_serializer = CredentialCreateSerializer(
                data=item_data, context={'product': product},
            )
            if not item_serializer.is_valid():
                return Response(
                    {'error': f'Invalid credential data: {item_serializer.errors}'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            variant_id = item_data.get('variant_id')
            variant = ProductVariant.objects.get(id=variant_id) if variant_id else None

            credential = ManualProductCredential.objects.create(
                product=product,
                variant=variant,
                credential_type=product.credential_type,
                username=item_data.get('username', ''),
                password=item_data.get('password', ''),
                code=item_data.get('code', ''),
                notes=item_data.get('notes', ''),
                expires_at=item_data.get('expires_at'),
                created_by=request.user,
            )
            created.append(credential)

        return Response({
            'count': len(created),
            'credentials': CredentialSerializer(created, many=True).data,
        }, status=status.HTTP_201_CREATED)


class CredentialDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def put(self, request, pk):
        credential = get_object_or_404(ManualProductCredential, pk=pk)
        data = request.data

        if 'username' in data:
            credential.username = data['username']
        if 'password' in data:
            credential.password = data['password']
        if 'code' in data:
            credential.code = data['code']
        if 'notes' in data:
            credential.notes = data['notes']
        if 'status' in data:
            credential.status = data['status']
        if 'expires_at' in data:
            credential.expires_at = data['expires_at']
        if 'variant_id' in data:
            if data['variant_id'] is not None:
                variant = get_object_or_404(ProductVariant, id=data['variant_id'], product=credential.product)
                credential.variant = variant
            else:
                credential.variant = None

        credential.save()
        return Response(CredentialSerializer(credential).data)

    def delete(self, request, pk):
        credential = get_object_or_404(ManualProductCredential, pk=pk)
        credential.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────
# WhatsApp Order Views
# ──────────────────────────────────────────────

class WhatsAppOrdersView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        orders = (
            Order.objects.filter(
                product__provider__adapter_key='whatsapp',
                status='PENDING',
            )
            .select_related('reseller', 'product', 'variant')
            .prefetch_related('credentials')
            .order_by('-created_at')
        )
        page = self.paginate_queryset(orders, request)
        if page is not None:
            serializer = WhatsAppOrderSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = WhatsAppOrderSerializer(orders, many=True)
        return Response(serializer.data)


class CompleteWhatsAppOrderView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, uuid):
        order = get_object_or_404(
            Order,
            uuid=uuid,
            product__provider__adapter_key='whatsapp',
            status='PENDING',
        )
        order.status = Order.Status.COMPLETED
        order.save()
        return Response({'detail': 'Order marked as completed.'})


# ──────────────────────────────────────────────
# Admin Settings Views
# ──────────────────────────────────────────────

class AdminSettingsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        return Response({
            'whatsapp_phone': request.user.whatsapp_phone or '',
        })

    def put(self, request):
        phone = request.data.get('whatsapp_phone', '').strip()
        request.user.whatsapp_phone = phone
        request.user.save(update_fields=['whatsapp_phone'])
        return Response({
            'whatsapp_phone': phone,
            'detail': 'WhatsApp phone updated.',
        })


# ──────────────────────────────────────────────
# Analytics & Monitoring Views
# ──────────────────────────────────────────────

class DashboardStatsView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        stats = get_dashboard_stats()
        serializer = DashboardStatsSerializer(stats)
        return Response(serializer.data)


class TopResellersView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        limit = int(request.query_params.get('limit', 10))
        resellers = get_top_resellers(limit=limit)
        data = [
            {
                'id': r.id,
                'username': r.username,
                'credit_balance': r.credit_balance,
                'is_active': r.is_active,
                'order_count': r.order_count or 0,
                'total_revenue': r.total_revenue or Decimal('0.00'),
            }
            for r in resellers
        ]
        serializer = TopResellerSerializer(data, many=True)
        return Response(serializer.data)


class RecentActivityView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        limit = int(request.query_params.get('limit', 20))
        activities = get_recent_activity(limit=limit)
        serializer = RecentActivitySerializer(activities, many=True)
        return Response(serializer.data)


class ProviderHealthView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        data = get_provider_health()
        return Response(data)


# ──────────────────────────────────────────────
# Product Management Views
# ──────────────────────────────────────────────

class AdminProductListView(DashboardPaginationMixin, APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        products = Product.objects.select_related('category', 'provider')

        search = request.query_params.get('search', '').strip()
        if search:
            products = products.filter(name__icontains=search)

        category = request.query_params.get('category', '').strip()
        if category:
            products = products.filter(category_id=category)

        product_type = request.query_params.get('type', '').strip()
        if product_type == 'manual':
            products = products.filter(is_manual=True)
        elif product_type == 'api':
            products = products.filter(is_manual=False).exclude(provider__adapter_key='whatsapp')
        elif product_type == 'whatsapp':
            products = products.filter(provider__adapter_key='whatsapp')

        status = request.query_params.get('status', '').strip()
        if status == 'active':
            products = products.filter(is_active=True)
        elif status == 'inactive':
            products = products.filter(is_active=False)

        products = products.annotate(
            variant_count=Count('variants', distinct=True),
            total_credentials=Count('manual_credentials', distinct=True),
            available_credentials=Count(
                'manual_credentials',
                filter=Q(manual_credentials__status='available'),
                distinct=True,
            ),
        )

        products = products.order_by('-created_at')

        page = self.paginate_queryset(products, request)
        if page is not None:
            serializer = ProductListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)


class AdminProductCreateView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        serializer = ProductCreateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        product = serializer.save()
        return Response(
            ProductListSerializer(product).data,
            status=status.HTTP_201_CREATED,
        )


class AdminProductDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def get_object(self, pk):
        return get_object_or_404(
            Product.objects.select_related('category', 'provider'),
            pk=pk,
        )

    def get(self, request, pk):
        product = self.get_object(pk)
        serializer = ProductListSerializer(product)
        return Response(serializer.data)

    def put(self, request, pk):
        product = self.get_object(pk)
        serializer = ProductUpdateSerializer(product, data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        product = serializer.save()
        return Response(ProductListSerializer(product).data)

    def delete(self, request, pk):
        product = self.get_object(pk)
        has_orders = Order.objects.filter(product=product).exists()
        if has_orders:
            product.is_active = False
            product.save()
            return Response(
                {'detail': 'Product has existing orders. It has been deactivated instead of deleted.'},
                status=status.HTTP_200_OK,
            )
        product.delete()
        return Response(
            {'detail': 'Product deleted successfully.'},
            status=status.HTTP_204_NO_CONTENT,
        )


class AdminProductImageUploadView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, pk):
        product = get_object_or_404(Product, pk=pk)
        if 'image' not in request.FILES:
            return Response({'error': 'No image file provided.'}, status=status.HTTP_400_BAD_REQUEST)
        product.image = request.FILES['image']
        product.save()
        return Response({
            'detail': 'Image uploaded successfully.',
            'image_url': product.thumbnail.url if product.thumbnail else product.image.url,
        })


# ──────────────────────────────────────────────
# Category Management Views
# ──────────────────────────────────────────────

class CategoryListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        categories = Category.objects.all().order_by('sort_order', 'name')
        serializer = CategorySerializer(categories, many=True)
        return Response(serializer.data)


class CategoryCreateView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request):
        serializer = CategorySerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        category = serializer.save()
        return Response(CategorySerializer(category).data, status=status.HTTP_201_CREATED)


class CategoryDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def get_object(self, pk):
        return get_object_or_404(Category, pk=pk)

    def get(self, request, pk):
        category = self.get_object(pk)
        serializer = CategorySerializer(category)
        return Response(serializer.data)

    def put(self, request, pk):
        category = self.get_object(pk)
        serializer = CategorySerializer(category, data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        category = serializer.save()
        return Response(CategorySerializer(category).data)

    def delete(self, request, pk):
        category = self.get_object(pk)
        product_count = category.products.count()
        if product_count > 0:
            return Response(
                {'error': f'Cannot delete category. It has {product_count} product(s) assigned.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        category.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────
# Variant Management Views
# ──────────────────────────────────────────────

class ProductVariantListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request, product_pk):
        product = get_object_or_404(Product, pk=product_pk)
        variants = ProductVariant.objects.filter(product=product).order_by('duration_months')
        serializer = ProductVariantSerializer(variants, many=True)
        return Response(serializer.data)


class ProductVariantCreateView(APIView):
    permission_classes = [IsSuperAdmin]

    def post(self, request, product_pk):
        product = get_object_or_404(Product, pk=product_pk)
        serializer = ProductVariantSerializer(data=request.data, context={'product': product, 'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        variant = serializer.save(product=product)
        return Response(
            ProductVariantSerializer(variant).data,
            status=status.HTTP_201_CREATED,
        )


class ProductVariantDetailView(APIView):
    permission_classes = [IsSuperAdmin]

    def get_object(self, product_pk, variant_pk):
        return get_object_or_404(ProductVariant, pk=variant_pk, product_id=product_pk)

    def put(self, request, product_pk, variant_pk):
        variant = self.get_object(product_pk, variant_pk)
        serializer = ProductVariantSerializer(variant, data=request.data, context={'product': variant.product, 'request': request})
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        variant = serializer.save()
        return Response(ProductVariantSerializer(variant).data)

    def delete(self, request, product_pk, variant_pk):
        variant = self.get_object(product_pk, variant_pk)
        variant.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


# ──────────────────────────────────────────────
# Provider List View
# ──────────────────────────────────────────────

class AdminProviderListView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        providers = Provider.objects.filter(is_active=True)
        serializer = ProviderSerializer(providers, many=True)
        return Response(serializer.data)
