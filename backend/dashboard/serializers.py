from decimal import Decimal
from rest_framework import serializers
from api.models import CustomUser, Product, ProductVariant, Category, Provider, Order, CreditTransaction
from .models import ManualProductCredential


# ──────────────────────────────────────────────
# Reseller Serializers
# ──────────────────────────────────────────────

class ResellerListSerializer(serializers.ModelSerializer):
    order_count = serializers.IntegerField(read_only=True)
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'role', 'credit_balance',
            'is_active', 'uuid', 'date_joined', 'last_login',
            'order_count', 'total_revenue',
        ]


class ResellerDetailSerializer(serializers.ModelSerializer):
    order_count = serializers.SerializerMethodField()
    total_revenue = serializers.SerializerMethodField()
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, default=None)

    class Meta:
        model = CustomUser
        fields = [
            'id', 'username', 'email', 'role', 'credit_balance',
            'is_active', 'uuid', 'date_joined', 'last_login',
            'created_by', 'created_by_username',
            'order_count', 'total_revenue',
        ]

    def get_order_count(self, obj):
        return obj.orders.count()

    def get_total_revenue(self, obj):
        from django.db.models import Sum
        total = obj.orders.filter(status='COMPLETED').aggregate(
            total=Sum('total_credits')
        )['total']
        return total or Decimal('0.00')


class ResellerCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150)
    password = serializers.CharField(min_length=6, write_only=True)
    password_confirm = serializers.CharField(min_length=6, write_only=True)
    initial_credits = serializers.DecimalField(
        max_digits=12, decimal_places=2, default=Decimal('0.00'), required=False,
    )

    def validate_username(self, value):
        if CustomUser.objects.filter(username=value).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value

    def validate(self, data):
        if data['password'] != data['password_confirm']:
            raise serializers.ValidationError({"password_confirm": "Passwords do not match."})
        return data


class ResellerUpdateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=150, required=False)
    password = serializers.CharField(min_length=6, write_only=True, required=False)
    is_active = serializers.BooleanField(required=False)

    def validate_username(self, value):
        reseller = self.context.get('reseller')
        if reseller and CustomUser.objects.filter(username=value).exclude(id=reseller.id).exists():
            raise serializers.ValidationError("A user with this username already exists.")
        return value


class CreditAdjustSerializer(serializers.Serializer):
    amount = serializers.DecimalField(max_digits=12, decimal_places=2)
    reason = serializers.CharField(max_length=255, default='Admin adjustment')

    def validate_amount(self, value):
        if value == 0:
            raise serializers.ValidationError("Amount cannot be zero.")
        return value


class CreditTransactionSerializer(serializers.ModelSerializer):
    class Meta:
        model = CreditTransaction
        fields = [
            'id', 'delta', 'balance_after', 'actor', 'reason',
            'reference_order', 'created_at',
        ]


class OrderListAdminSerializer(serializers.ModelSerializer):
    reseller_username = serializers.CharField(source='reseller.username', read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'reseller', 'reseller_username',
            'product_name_at_purchase', 'quantity', 'total_credits',
            'status', 'failure_reason', 'created_at',
        ]


# ──────────────────────────────────────────────
# Manual Product / Credential Serializers
# ──────────────────────────────────────────────

class ManualProductListSerializer(serializers.ModelSerializer):
    total_credentials = serializers.IntegerField(read_only=True)
    available_credentials = serializers.IntegerField(read_only=True)
    used_credentials = serializers.IntegerField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'category', 'category_name', 'credential_type',
            'is_active', 'image', 'created_at',
            'total_credentials', 'available_credentials',
            'used_credentials',
        ]


class CredentialSerializer(serializers.ModelSerializer):
    assigned_to_username = serializers.CharField(
        source='assigned_to.username', read_only=True, default=None,
    )
    product_name = serializers.CharField(source='product.name', read_only=True)
    variant = serializers.IntegerField(source='variant_id', read_only=True)
    variant_display = serializers.SerializerMethodField()

    class Meta:
        model = ManualProductCredential
        fields = [
            'id', 'uuid', 'product', 'product_name', 'credential_type',
            'variant', 'variant_display',
            'username', 'password', 'code', 'notes',
            'status', 'assigned_to', 'assigned_to_username',
            'assigned_at', 'used_at', 'expires_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'uuid', 'created_at', 'updated_at']

    def get_variant_display(self, obj):
        if not obj.variant:
            return None
        return str(obj.variant)


class CredentialCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    password = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    code = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    variant_id = serializers.IntegerField(required=False, allow_null=True, default=None)

    def validate(self, data):
        product = self.context.get('product')
        if not product:
            raise serializers.ValidationError("Product context is required.")

        if product.credential_type == 'username_password':
            if not data.get('username') or not data.get('password'):
                raise serializers.ValidationError(
                    "Username and password are required for this product."
                )
        elif product.credential_type == 'single_code':
            if not data.get('code'):
                raise serializers.ValidationError(
                    "Activation code is required for this product."
                )

        variant_id = data.get('variant_id')
        if variant_id is not None:
            from api.models import ProductVariant
            if not ProductVariant.objects.filter(id=variant_id, product=product).exists():
                raise serializers.ValidationError(
                    {"variant_id": "Variant does not belong to this product."}
                )
        return data


class CredentialBulkCreateSerializer(serializers.Serializer):
    credentials = CredentialCreateSerializer(many=True)

    def validate_credentials(self, value):
        if not value:
            raise serializers.ValidationError("At least one credential is required.")
        if len(value) > 100:
            raise serializers.ValidationError("Maximum 100 credentials per bulk operation.")
        return value


# ──────────────────────────────────────────────
# Analytics Serializers
# ──────────────────────────────────────────────

class DashboardStatsSerializer(serializers.Serializer):
    total_resellers = serializers.IntegerField()
    active_resellers = serializers.IntegerField()
    total_orders = serializers.IntegerField()
    completed_orders = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    total_credentials = serializers.IntegerField()
    available_credentials = serializers.IntegerField()


class TopResellerSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    credit_balance = serializers.DecimalField(max_digits=12, decimal_places=2)
    is_active = serializers.BooleanField()
    order_count = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class RecentActivitySerializer(serializers.Serializer):
    type = serializers.CharField()
    description = serializers.CharField()
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, allow_null=True)
    user = serializers.CharField()
    status = serializers.CharField(allow_null=True)
    created_at = serializers.DateTimeField()


# ──────────────────────────────────────────────
# WhatsApp Order Serializers
# ──────────────────────────────────────────────

class WhatsAppOrderSerializer(serializers.ModelSerializer):
    reseller_username = serializers.CharField(source='reseller.username', read_only=True)
    product_name = serializers.CharField(source='product.name', read_only=True)
    duration_display = serializers.SerializerMethodField()
    wa_link = serializers.SerializerMethodField()
    message_text = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'uuid', 'reseller', 'reseller_username',
            'product', 'product_name', 'duration_display',
            'quantity', 'total_credits', 'status', 'created_at',
            'wa_link', 'message_text',
        ]

    def get_duration_display(self, obj):
        v = obj.variant
        if not v:
            return '—'
        if v.is_lifetime:
            return 'Lifetime'
        return v.get_duration_months_display()

    def get_wa_link(self, obj):
        cred = obj.credentials.first()
        if cred and cred.data:
            return cred.data.get('wa_link')
        return None

    def get_message_text(self, obj):
        cred = obj.credentials.first()
        if cred and cred.data:
            return cred.data.get('message')
        return None


# ──────────────────────────────────────────────
# Product Management Serializers
# ──────────────────────────────────────────────

class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'slug', 'description', 'image', 'is_active', 'sort_order', 'product_count']
        read_only_fields = ['slug']

    def get_product_count(self, obj):
        return obj.products.count()

    def create(self, validated_data):
        from django.utils.text import slugify
        if 'slug' not in validated_data or not validated_data.get('slug'):
            validated_data['slug'] = slugify(validated_data['name'])
        return super().create(validated_data)


class ProviderSerializer(serializers.ModelSerializer):
    class Meta:
        model = Provider
        fields = ['id', 'name', 'slug', 'adapter_key', 'is_active']


class ProductVariantSerializer(serializers.ModelSerializer):
    duration_display = serializers.SerializerMethodField()
    external_pack_id = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = ProductVariant
        fields = [
            'id', 'product', 'duration_months', 'is_lifetime',
            'external_pack_id', 'price_in_credits', 'is_active',
            'duration_display', 'created_at',
        ]
        read_only_fields = ['id', 'product', 'created_at']

    def get_duration_display(self, obj):
        if obj.is_lifetime:
            return 'Lifetime'
        if obj.duration_months is not None:
            labels = dict(Product.Duration.choices)
            return labels.get(obj.duration_months, f'{obj.duration_months} Months')
        return '—'

    def validate_external_pack_id(self, value):
        product = self.context.get('product')
        if product is not None and not product.is_manual and product.provider and product.provider.adapter_key != 'whatsapp':
            if value is None:
                raise serializers.ValidationError("External Pack ID is required for API products.")
        return value


class ProductListSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)
    provider_name = serializers.CharField(source='provider.name', read_only=True, default=None)
    provider_key = serializers.CharField(source='provider.adapter_key', read_only=True, default=None)
    variant_count = serializers.SerializerMethodField()
    total_credentials = serializers.SerializerMethodField()
    available_credentials = serializers.SerializerMethodField()
    product_type = serializers.SerializerMethodField()
    image_url = serializers.SerializerMethodField()
    variants = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'category', 'category_name', 'provider', 'provider_name',
            'provider_key', 'description', 'is_active', 'is_manual', 'credential_type',
            'price_in_credits', 'duration_months', 'external_pack_id',
            'image_url', 'product_type', 'variant_count', 'total_credentials',
            'available_credentials', 'variants', 'created_at', 'updated_at',
        ]

    def get_variant_count(self, obj):
        return getattr(obj, 'variant_count', obj.variants.count())

    def get_total_credentials(self, obj):
        if obj.is_manual:
            return getattr(obj, 'total_credentials', obj.manual_credentials.count())
        return None

    def get_available_credentials(self, obj):
        if obj.is_manual:
            return getattr(obj, 'available_credentials', obj.manual_credentials.filter(status='available').count())
        return None

    def get_product_type(self, obj):
        if obj.is_manual:
            return 'manual'
        if obj.provider and obj.provider.adapter_key == 'whatsapp':
            return 'whatsapp'
        return 'api'

    def get_image_url(self, obj):
        if obj.image:
            try:
                return obj.image.url
            except Exception:
                return None
        return None

    def get_variants(self, obj):
        variants = obj.variants.all()
        return ProductVariantSerializer(variants, many=True).data


class ProductCreateSerializer(serializers.ModelSerializer):
    duration_months = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Product
        fields = [
            'name', 'category', 'provider', 'description', 'image',
            'is_manual', 'credential_type', 'price_in_credits',
            'duration_months', 'external_pack_id', 'is_active',
        ]

    def validate_duration_months(self, value):
        if value == '' or value is None:
            return None
        return value

    def validate(self, data):
        if data.get('is_manual'):
            if not data.get('credential_type'):
                raise serializers.ValidationError(
                    {'credential_type': 'Manual products require a credential type.'}
                )
        else:
            if not data.get('provider'):
                raise serializers.ValidationError(
                    {'provider': 'API/WhatsApp products require a provider.'}
                )
        return data


class ProductUpdateSerializer(serializers.ModelSerializer):
    duration_months = serializers.IntegerField(required=False, allow_null=True)

    class Meta:
        model = Product
        fields = [
            'name', 'category', 'provider', 'description', 'image',
            'is_manual', 'credential_type', 'price_in_credits',
            'duration_months', 'external_pack_id', 'is_active',
        ]
        extra_kwargs = {field: {'required': False} for field in fields}

    def validate_duration_months(self, value):
        if value == '' or value is None:
            return None
        return value
