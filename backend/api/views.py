from django.conf import settings
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.throttling import UserRateThrottle
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView

from .models import Product, ProductVariant, Order, Credential
from .serializers import (
    UserProfileSerializer, ProductSerializer,
    PurchaseSerializer, OrderListSerializer, OrderDetailSerializer,
    CredentialSerializer, OrderStatusSerializer,
)
from .services import reserve_phase, fulfill_sync, check_idempotency, InsufficientCredits
from .tasks import fulfill_order_async


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


class ProductListView(APIView):
    def get(self, request):
        products = Product.objects.filter(is_active=True)
        page = self.paginate_queryset(products, request)
        if page is not None:
            serializer = ProductSerializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        serializer = ProductSerializer(products, many=True)
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
        credentials = Credential.objects.filter(order=order)
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
