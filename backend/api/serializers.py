from decimal import Decimal
from rest_framework import serializers
from .models import CustomUser, Category, Product, ProductVariant, Order, Credential, CreditTransaction
from .utils import decrypt_password


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(write_only=True)


class UserProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomUser
        fields = ['id', 'username', 'email', 'role', 'credit_balance']


class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'image', 'is_active',
                  'sort_order', 'product_count']

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class ProductVariantSerializer(serializers.ModelSerializer):
    display_name = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'duration_months', 'display_name', 'external_pack_id',
                   'price_in_credits', 'is_active']

    def get_display_name(self, obj):
        return obj.get_duration_months_display()


class ProductSerializer(serializers.ModelSerializer):
    variants = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    thumbnail_url = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'name', 'category', 'category_name', 'category_slug',
                  'provider', 'provider_name', 'description', 'image',
                  'thumbnail_url', 'is_active', 'variants', 'created_at']

    def get_variants(self, obj):
        active = getattr(obj, 'active_variants', None)
        if active is not None:
            return ProductVariantSerializer(active, many=True).data
        return ProductVariantSerializer(obj.variants.filter(is_active=True), many=True).data

    def get_thumbnail_url(self, obj):
        try:
            return obj.thumbnail.url if obj.image else None
        except Exception:
            return None


class PurchaseSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=50)

    def validate_variant_id(self, value):
        try:
            variant = ProductVariant.objects.select_related('product').get(
                id=value, is_active=True, product__is_active=True
            )
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError("Variant not found or inactive.")
        return variant


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
    username = serializers.CharField(source='streaming_username')
    password = serializers.SerializerMethodField()
    provider_adapter_key = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ['id', 'username', 'password', 'dns_domain', 'm3u_url',
                  'expires_at', 'provider_adapter_key']

    def get_password(self, obj):
        return decrypt_password(obj.encrypted_password)

    def get_provider_adapter_key(self, obj):
        if obj.order.product and obj.order.product.provider:
            return obj.order.product.provider.adapter_key
        return None


class DeviceActivateSerializer(serializers.Serializer):
    pack_id = serializers.IntegerField()
    duration = serializers.ChoiceField(choices=[
        'MONTHS_1', 'MONTHS_3', 'MONTHS_6',
        'MONTHS_12', 'YEAR_1', 'FOREVER',
    ])
    extend = serializers.BooleanField(default=False)


class PlaylistEntrySerializer(serializers.Serializer):
    url = serializers.URLField()
    name = serializers.CharField(max_length=100, required=False, default='Playlist')


class AddPlaylistsSerializer(serializers.Serializer):
    playlists = serializers.ListField(
        child=PlaylistEntrySerializer(),
        min_length=1,
        max_length=5,
    )


class OrderStatusSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    status = serializers.CharField()
    failure_reason = serializers.CharField(allow_null=True)
