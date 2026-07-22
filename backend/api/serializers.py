from decimal import Decimal
from rest_framework import serializers
from .models import CustomUser, Category, Product, ProductVariant, Order, Credential, CreditTransaction
from dashboard.models import ManualProductCredential
from .utils import decrypt_password, extract_base_url


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
    stock_count = serializers.SerializerMethodField()

    class Meta:
        model = ProductVariant
        fields = ['id', 'duration_months', 'display_name', 'external_pack_id',
                   'price_in_credits', 'is_active', 'stock_count']

    def get_display_name(self, obj):
        if obj.is_lifetime:
            return 'Lifetime'
        return obj.get_duration_months_display()

    def get_stock_count(self, obj):
        if not obj.product.is_manual:
            return None
        return ManualProductCredential.objects.filter(
            product=obj.product, variant=obj, status='available'
        ).count()


class ProductSerializer(serializers.ModelSerializer):
    variants = serializers.SerializerMethodField()
    category_name = serializers.CharField(source='category.name', read_only=True)
    category_slug = serializers.CharField(source='category.slug', read_only=True)
    provider_name = serializers.CharField(source='provider.name', read_only=True)
    provider_key = serializers.CharField(source='provider.adapter_key', read_only=True)
    thumbnail_url = serializers.SerializerMethodField()
    available_credentials = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = ['id', 'name', 'category', 'category_name', 'category_slug',
                  'provider', 'provider_name', 'provider_key', 'description', 'image',
                  'thumbnail_url', 'is_active', 'is_manual', 'available_credentials',
                  'variants', 'created_at']

    def get_variants(self, obj):
        active = getattr(obj, 'active_variants', None)
        if active is not None:
            return ProductVariantSerializer(active, many=True).data
        return ProductVariantSerializer(obj.variants.filter(is_active=True), many=True).data

    def get_thumbnail_url(self, obj):
        try:
            return obj.image.url if obj.image else None
        except Exception:
            return None

    def get_available_credentials(self, obj):
        if not obj.is_manual:
            return None
        return ManualProductCredential.objects.filter(
            product=obj, status=ManualProductCredential.Status.AVAILABLE
        ).count()


class PurchaseSerializer(serializers.Serializer):
    variant_id = serializers.IntegerField()
    quantity = serializers.IntegerField(min_value=1, max_value=50)
    mac = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    note = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    username = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    password = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    template_id = serializers.IntegerField(required=False, allow_null=True)
    dns_domain_id = serializers.IntegerField(required=False, allow_null=True)

    def validate_variant_id(self, value):
        try:
            variant = ProductVariant.objects.select_related('product').get(
                id=value, is_active=True, product__is_active=True
            )
        except ProductVariant.DoesNotExist:
            raise serializers.ValidationError("Variant not found or inactive.")
        return variant

    def validate_mac(self, value):
        if not value:
            return value
        import re
        if not re.match(r'^([0-9A-Za-z]{2}:){5}[0-9A-Za-z]{2}$', value):
            raise serializers.ValidationError(
                "Invalid MAC address. Use format XX:XX:XX:XX:XX:XX"
            )
        return value.upper()

    def validate(self, data):
        variant = data.get('variant_id')
        if variant and variant.product.provider.adapter_key == 'hotplayer':
            if data.get('quantity', 1) != 1:
                raise serializers.ValidationError(
                    {"quantity": "HotPlayer products support only quantity 1 per purchase."}
                )
            if not data.get('mac'):
                raise serializers.ValidationError(
                    {"mac": "MAC address is required for HotPlayer products."}
                )
        return data


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
    url = serializers.SerializerMethodField()
    provider_adapter_key = serializers.SerializerMethodField()
    credential_data = serializers.SerializerMethodField()
    provider_config = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ['id', 'username', 'password', 'url', 'dns_domain', 'm3u_url',
                  'expires_at', 'provider_adapter_key', 'credential_data',
                  'provider_config', 'product_id']

    def get_product_id(self, obj):
        return obj.order.product_id

    product_id = serializers.SerializerMethodField()

    def get_password(self, obj):
        return decrypt_password(obj.encrypted_password)

    def get_url(self, obj):
        return extract_base_url(obj.m3u_url)

    def get_provider_adapter_key(self, obj):
        if obj.order.product and obj.order.product.provider:
            return obj.order.product.provider.adapter_key
        return None

    def get_credential_data(self, obj):
        data = dict(obj.data) if obj.data else {}
        decrypted = decrypt_password(obj.encrypted_password)
        if decrypted:
            data['secret_password'] = decrypted
        data['url'] = extract_base_url(obj.m3u_url)
        return data

    def get_provider_config(self, obj):
        # Manual product: return a display schema based on credential type
        data = dict(obj.data) if obj.data else {}
        if data.get('manual'):
            cred_type = data.get('credential_type', '')
            if cred_type == 'username_password':
                return {
                    'fields': [
                        {'key': 'username', 'label': 'USERNAME'},
                        {'key': 'secret_password', 'label': 'PASSWORD', 'type': 'secret'},
                    ]
                }
            elif cred_type == 'single_code':
                return {
                    'fields': [
                        {'key': 'code', 'label': 'ACTIVATION CODE'},
                    ]
                }
        if data.get('whatsapp'):
            return {
                'fields': [
                    {'key': 'wa_link', 'label': 'OPEN WHATSAPP', 'type': 'url'},
                    {'key': 'message', 'label': 'MESSAGE'},
                ]
            }
        try:
            provider = obj.order.product.provider
            if provider and provider.extra_config:
                return provider.extra_config.get('display', {})
        except Exception:
            pass
        return {}


class DeviceActivateSerializer(serializers.Serializer):
    pack_id = serializers.IntegerField()
    duration = serializers.ChoiceField(choices=[
        'MONTHS_1', 'MONTHS_3', 'MONTHS_6',
        'MONTHS_12', 'YEAR_1', 'FOREVER',
    ])
    extend = serializers.BooleanField(default=False)


class CredentialListSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source='streaming_username')
    url = serializers.SerializerMethodField()
    provider_adapter_key = serializers.SerializerMethodField()
    product_name = serializers.CharField(source='order.product_name_at_purchase')
    order_uuid = serializers.UUIDField(source='order.uuid')
    order_created = serializers.DateTimeField(source='order.created_at')
    credential_data = serializers.SerializerMethodField()
    provider_config = serializers.SerializerMethodField()

    class Meta:
        model = Credential
        fields = ['id', 'username', 'url', 'expires_at', 'is_revoked',
                  'provider_adapter_key', 'product_name', 'order_uuid', 'order_created',
                  'credential_data', 'provider_config', 'created_at', 'product_id']

    def get_product_id(self, obj):
        return obj.order.product_id

    product_id = serializers.SerializerMethodField()

    def get_provider_adapter_key(self, obj):
        if obj.order.product and obj.order.product.provider:
            return obj.order.product.provider.adapter_key
        return None

    def get_credential_data(self, obj):
        data = dict(obj.data) if obj.data else {}
        data['url'] = extract_base_url(obj.m3u_url)
        return data

    def get_url(self, obj):
        return extract_base_url(obj.m3u_url)

    def get_provider_config(self, obj):
        data = dict(obj.data) if obj.data else {}
        if data.get('whatsapp'):
            return {
                'fields': [
                    {'key': 'wa_link', 'label': 'OPEN WHATSAPP', 'type': 'url'},
                    {'key': 'message', 'label': 'MESSAGE'},
                ]
            }
        try:
            provider = obj.order.product.provider
            if provider and provider.extra_config:
                return provider.extra_config.get('display', {})
        except Exception:
            pass
        return {}


class OrderStatusSerializer(serializers.Serializer):
    order_id = serializers.UUIDField()
    status = serializers.CharField()
    failure_reason = serializers.CharField(allow_null=True)
