import re
from hashlib import md5
from django.conf import settings
from django.core.cache import cache
from django.db import connection
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404
from django.contrib.postgres.search import SearchQuery, SearchRank
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import Product, ProductVariant, Order, Credential, Category
from .serializers import (
    UserProfileSerializer, CategorySerializer, ProductSerializer,
    PurchaseSerializer, OrderListSerializer, OrderDetailSerializer,
    CredentialSerializer, CredentialListSerializer, OrderStatusSerializer,
    DeviceActivateSerializer, AddPlaylistsSerializer,
)
from .services import reserve_phase, fulfill_sync, check_idempotency, InsufficientCredits
from .tasks import fulfill_order_async
from .device_services import (
    activate_device as device_activate,
    check_device as device_check,
    add_playlists as device_add_playlists,
    delete_playlists as device_delete_playlists,
    InsufficientCredits as DeviceInsufficientCredits,
    NoMatchingVariant,
)


def _cache_key(prefix, request):
    params = sorted(request.query_params.items())
    return f'{prefix}:{md5(str(params).encode()).hexdigest()}'


class LoginView(TokenObtainPairView):
    permission_classes = [AllowAny]


class RefreshView(TokenRefreshView):
    permission_classes = [AllowAny]


class LogoutView(APIView):
    def post(self, request):
        try:
            refresh_token = request.data.get('refresh')
            if refresh_token:
                token = RefreshToken(refresh_token)
                token.blacklist()
            return Response(status=status.HTTP_204_NO_CONTENT)
        except Exception:
            return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    def get(self, request):
        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)


class CategoryListView(APIView):
    def get(self, request):
        cache_key = 'category_list'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)
        categories = Category.objects.filter(is_active=True)
        serializer = CategorySerializer(categories, many=True)
        cache.set(cache_key, serializer.data, 300)
        return Response(serializer.data)


class ProductListView(APIView):
    def get(self, request):
        cache_key = _cache_key('product_list', request)
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)

        products = Product.objects.filter(is_active=True).select_related('category', 'provider').prefetch_related(
            Prefetch('variants', queryset=ProductVariant.objects.filter(is_active=True), to_attr='active_variants')
        )

        search = request.query_params.get('search', '').strip()
        if search:
            query = SearchQuery(search, config='simple')
            products = (
                products.annotate(rank=SearchRank('search_vector', query))
                .filter(search_vector=query)
                .order_by('-rank')
            )

        category_slug = request.query_params.get('category', '').strip()
        if category_slug:
            products = products.filter(category__slug=category_slug)

        provider_id = request.query_params.get('provider', '').strip()
        if provider_id:
            products = products.filter(provider_id=provider_id)

        page = self.paginate_queryset(products, request)
        if page is not None:
            serializer = ProductSerializer(page, many=True)
            response = self.get_paginated_response(serializer.data)
            cache.set(cache_key, response.data, 300)
            return response
        serializer = ProductSerializer(products, many=True)
        cache.set(cache_key, serializer.data, 300)
        return Response(serializer.data)

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


class PurchaseThrottle(UserRateThrottle):
    scope = 'purchase'
    rate = f'{settings.RATE_LIMIT_PURCHASE}/min'


class PurchaseView(APIView):
    throttle_classes = [PurchaseThrottle]

    def post(self, request):
        idempotency_key = request.META.get('HTTP_IDEMPOTENCY_KEY') or request.headers.get('Idempotency-Key')
        if not idempotency_key:
            return Response({'error': 'Idempotency-Key header is required.'}, status=status.HTTP_400_BAD_REQUEST)

        existing_order = check_idempotency(request.user, idempotency_key)
        if existing_order:
            return Response({
                'order_id': existing_order.uuid,
                'status': existing_order.status,
                'message': 'Idempotent request. Original order returned.',
            }, status=status.HTTP_409_CONFLICT)

        serializer = PurchaseSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        variant = serializer.validated_data['variant_id']
        quantity = serializer.validated_data['quantity']

        try:
            order = reserve_phase(request.user, variant, quantity, idempotency_key)
        except InsufficientCredits as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if quantity <= settings.ASYNC_THRESHOLD:
            credentials, failure = fulfill_sync(order)
            if failure:
                return Response({'error': failure}, status=status.HTTP_400_BAD_REQUEST)
            cred_serializer = CredentialSerializer(credentials, many=True)
            return Response({
                'order_id': order.uuid,
                'status': order.status,
                'credentials': cred_serializer.data,
            }, status=status.HTTP_201_CREATED)
        else:
            fulfill_order_async.delay(order.id)
            return Response({
                'order_id': order.uuid,
                'status': 'PENDING',
            }, status=status.HTTP_202_ACCEPTED)


class OrderListView(APIView):
    def get(self, request):
        orders = Order.objects.filter(reseller=request.user).order_by('-created_at')
        page = self.paginate_queryset(orders, request)
        if page is not None:
            serializer = OrderListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = OrderListSerializer(orders, many=True)
        return Response(serializer.data)

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


class OrderDetailView(APIView):
    def get(self, request, uuid):
        order = get_object_or_404(Order, uuid=uuid, reseller=request.user)
        serializer = OrderDetailSerializer(order)
        return Response(serializer.data)


class OrderCredentialsView(APIView):
    def get(self, request, uuid):
        order = get_object_or_404(Order, uuid=uuid, reseller=request.user)
        if order.status != Order.Status.COMPLETED:
            return Response({'error': 'Order is not completed.'}, status=status.HTTP_400_BAD_REQUEST)
        credentials = Credential.objects.filter(order=order).select_related(
            'order__product__provider', 'order__variant'
        )
        serializer = CredentialSerializer(credentials, many=True)
        return Response(serializer.data)


class OrderStatusView(APIView):
    def get(self, request, uuid):
        order = get_object_or_404(Order, uuid=uuid, reseller=request.user)
        serializer = OrderStatusSerializer({
            'order_id': order.uuid,
            'status': order.status,
            'failure_reason': order.failure_reason,
        })
        return Response(serializer.data)


class StatsView(APIView):
    def get(self, request):
        cache_key = f'stats:{request.user.id}'
        cached = cache.get(cache_key)
        if cached:
            return Response(cached)
        data = {
            'total_products': Product.objects.filter(is_active=True).count(),
            'total_categories': Category.objects.filter(is_active=True).count(),
            'credit_balance': request.user.credit_balance,
        }
        cache.set(cache_key, data, 300)
        return Response(data)


class HealthCheckView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        try:
            connection.ensure_connection()
            db_ok = True
        except Exception:
            db_ok = False
        try:
            cache.set('health_check', 1, 5)
            cache_ok = cache.get('health_check') == 1
        except Exception:
            cache_ok = False
        try:
            from redis import Redis
            r = Redis(
                host=settings.REDIS_HOST,
                port=settings.REDIS_PORT,
                db=settings.REDIS_DB,
            )
            r.ping()
            rq_ok = True
        except Exception:
            rq_ok = False
        status_code = status.HTTP_200_OK if db_ok and cache_ok and rq_ok else status.HTTP_503_SERVICE_UNAVAILABLE
        return Response({
            'status': 'healthy' if status_code == 200 else 'unhealthy',
            'database': 'ok' if db_ok else 'error',
            'cache': 'ok' if cache_ok else 'error',
            'rq_redis': 'ok' if rq_ok else 'error',
        }, status=status_code)


class RQStatsView(APIView):
    def get(self, request):
        from django_rq import get_queue
        from redis import Redis
        r = Redis(
            host=settings.REDIS_HOST,
            port=settings.REDIS_PORT,
            db=settings.REDIS_DB,
        )
        queue = get_queue('default')
        return Response({
            'default_queue': {
                'count': queue.count,
                'failed_count': queue.failed_job_registry.count,
                'started_count': queue.started_job_registry.count,
                'deferred_count': queue.deferred_job_registry.count,
                'scheduled_count': queue.scheduled_job_registry.count,
            },
            'redis_info': {
                'used_memory': r.info().get('used_memory_human', 'N/A'),
                'connected_clients': r.info().get('connected_clients', 0),
            },
        })


class CredentialListView(APIView):
    def get(self, request):
        credentials = Credential.objects.filter(
            order__reseller=request.user,
            order__status=Order.Status.COMPLETED,
        ).select_related(
            'order__product__provider', 'order__variant'
        ).order_by('-created_at')

        provider = request.query_params.get('provider')
        if provider:
            credentials = credentials.filter(order__product__provider__adapter_key=provider)

        page = self.paginate_queryset(credentials, request)
        if page is not None:
            serializer = CredentialListSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = CredentialListSerializer(credentials, many=True)
        return Response(serializer.data)

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


MAC_REGEX = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')


class CredentialDeviceStatusView(APIView):
    def get(self, request, credential_id):
        try:
            data = device_check(credential_id, request.user)
            return Response(data)
        except NotImplementedError as e:
            return Response({'error': str(e)}, status=status.HTTP_501_NOT_IMPLEMENTED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CredentialDeviceActivateView(APIView):
    throttle_classes = [PurchaseThrottle]

    def post(self, request, credential_id):
        serializer = DeviceActivateSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

        mac = None
        try:
            credential = get_object_or_404(Credential, id=credential_id, order__reseller=request.user)
            mac = credential.streaming_username or credential.external_username
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

        if not mac or not MAC_REGEX.match(mac):
            return Response({'error': 'Invalid MAC address on credential.'}, status=status.HTTP_400_BAD_REQUEST)

        try:
            result = device_activate(
                credential_id, request.user,
                pack_id=serializer.validated_data['pack_id'],
                duration=serializer.validated_data['duration'],
                extend=serializer.validated_data.get('extend', False),
            )
            return Response(result, status=status.HTTP_200_OK)
        except DeviceInsufficientCredits as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except NoMatchingVariant as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        except NotImplementedError as e:
            return Response({'error': str(e)}, status=status.HTTP_501_NOT_IMPLEMENTED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)


class CredentialDevicePlaylistsView(APIView):
    def post(self, request, credential_id):
        serializer = AddPlaylistsSerializer(data=request.data)
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        try:
            data = device_add_playlists(credential_id, request.user, serializer.validated_data['playlists'])
            return Response(data)
        except NotImplementedError as e:
            return Response({'error': str(e)}, status=status.HTTP_501_NOT_IMPLEMENTED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, credential_id):
        try:
            data = device_delete_playlists(credential_id, request.user)
            return Response(data)
        except NotImplementedError as e:
            return Response({'error': str(e)}, status=status.HTTP_501_NOT_IMPLEMENTED)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
