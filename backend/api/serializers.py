from decimal import Decimal
from rest_framework import serializers
from .models import CustomUser, Product, Order, Credential
from .utils import decrypt_password


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'role', 'credit_balance']


class ProductSerializer(serializers.ModelSerializer):
    class Meta:
        model = Product
        fields = ['id', 'name', 'category', 'description', 'duration_months',
                   'price_in_credits', 'created_at']


class PurchaseSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=50)

    def validate_product_id(self, value):
        try:
            product = Product.objects.get(id=value, is_active=True)
        except Product.DoesNotExist:
            raise serializers.ValidationError("Product not found or inactive.")
        return value


class OrderListSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'uuid', 'product_name_at_purchase', 'quantity',
                   'total_credits', 'status', 'created_at']


class OrderDetailSerializer(serializers.ModelSerializer):
    class Meta:
        model = Order
        fields = ['id', 'uuid', 'product_name_at_purchase', 'unit_price_at_purchase',
                   'quantity', 'total_credits', 'status', 'failure_reason', 'created_at']


class CredentialSerializer(serializers.ModelSerializer):
    password = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ['id', 'external_username', 'password', 'dns_domain', 'expires_at']

    def get_password(self, obj):
        return decrypt_password(obj.encrypted_password)


class OrderStatusSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    status = serializers.CharField()
    failure_reason = serializers.CharField(allow_null=True)
