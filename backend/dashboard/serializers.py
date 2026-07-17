from decimal import Decimal
from rest_framework import serializers
from api.models import CustomUser, Product, Order, CreditTransaction
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
    assigned_credentials = serializers.IntegerField(read_only=True)
    category_name = serializers.CharField(source='category.name', read_only=True, default=None)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'category', 'category_name', 'credential_type',
            'is_active', 'image', 'created_at',
            'total_credentials', 'available_credentials',
            'used_credentials', 'assigned_credentials',
        ]


class CredentialSerializer(serializers.ModelSerializer):
    assigned_to_username = serializers.CharField(
        source='assigned_to.username', read_only=True, default=None,
    )
    product_name = serializers.CharField(source='product.name', read_only=True)

    class Meta:
        model = ManualProductCredential
        fields = [
            'id', 'uuid', 'product', 'product_name', 'credential_type',
            'username', 'password', 'code', 'notes',
            'status', 'assigned_to', 'assigned_to_username',
            'assigned_at', 'used_at', 'expires_at',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'uuid', 'created_at', 'updated_at']


class CredentialCreateSerializer(serializers.Serializer):
    username = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    password = serializers.CharField(max_length=255, required=False, allow_blank=True, default='')
    code = serializers.CharField(max_length=500, required=False, allow_blank=True, default='')
    notes = serializers.CharField(required=False, allow_blank=True, default='')
    expires_at = serializers.DateTimeField(required=False, allow_null=True, default=None)

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


class RevenueChartSerializer(serializers.Serializer):
    month = serializers.CharField()
    revenue = serializers.DecimalField(max_digits=12, decimal_places=2)
    orders = serializers.IntegerField()
