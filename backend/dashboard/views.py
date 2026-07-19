import logging
from decimal import Decimal
from django.db.models import Count, Sum, Q
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from api.models import CustomUser, Product, ProductVariant, Order, CreditTransaction
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
    RecentActivitySerializer, RevenueChartSerializer,
)
from .services import (
    get_dashboard_stats, get_top_resellers, get_recent_activity,
    get_revenue_chart_data, get_provider_health, adjust_credits,
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
                assigned_credentials=Count(
                    'manual_credentials',
                    filter=Q(manual_credentials__status='assigned'),
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
            'assigned': ManualProductCredential.objects.filter(product=product, status='assigned').count(),
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


class RevenueChartView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        months = int(request.query_params.get('months', 12))
        data = get_revenue_chart_data(months=months)
        serializer = RevenueChartSerializer(data, many=True)
        return Response(serializer.data)


class ProviderHealthView(APIView):
    permission_classes = [IsSuperAdmin]

    def get(self, request):
        data = get_provider_health()
        return Response(data)
