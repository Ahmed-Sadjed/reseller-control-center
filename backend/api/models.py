import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta
from django.contrib.postgres.search import SearchVectorField
from django.contrib.postgres.indexes import GinIndex
from imagekit.models import ImageSpecField
from imagekit.processors import ResizeToFill


class CustomUser(AbstractUser):
    class Role(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        RESELLER = 'RESELLER', 'Reseller'

    role = models.CharField(max_length=10, choices=Role.choices, default=Role.RESELLER)
    credit_balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    created_by = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True)
    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    last_login_ip = models.GenericIPAddressField(null=True, blank=True)
    email = models.EmailField(unique=True)

    class Meta:
        indexes = [
            models.Index(fields=['role']),
        ]

    def __str__(self):
        return f"{self.username} ({self.get_role_display()})"


class Provider(models.Model):
    class AdapterKey(models.TextChoices):
        NEO4K = 'neo4k', 'NEO 4K'
        GOLD_PANEL = 'goldpanel', 'Gold Panel'
        HOTPLAYER = 'hotplayer', 'HotPlayer'
        GOLDEN_API = 'golden_api', 'Golden API'
        MOCK = 'mock', 'Mock'

    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    adapter_key = models.CharField(
        max_length=20,
        choices=AdapterKey.choices,
        default=AdapterKey.MOCK,
        help_text='Determines which adapter class handles API calls for this provider.',
    )
    api_endpoint = models.URLField(max_length=500, blank=True)
    api_token = models.BinaryField(editable=False, null=True, blank=True)
    extra_config = models.JSONField(
        default=dict,
        blank=True,
        help_text='Provider-specific config (e.g. {"dns_domain": "kmapp.xyz", "port": 8080}).',
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def set_token(self, raw_token: str):
        from .utils import encrypt_password
        self.api_token = encrypt_password(raw_token)

    def get_token(self) -> str:
        from .utils import decrypt_password
        return decrypt_password(self.api_token)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name = 'Provider'
        verbose_name_plural = 'Providers'


class Category(models.Model):
    name = models.CharField(max_length=100, unique=True)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='categories/', blank=True, null=True)
    is_active = models.BooleanField(default=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['sort_order', 'name']
        verbose_name_plural = 'Categories'

    def __str__(self):
        return self.name


class Product(models.Model):
    class Duration(models.IntegerChoices):
        TRIAL_6H = 100, '6 Hours'
        TRIAL_12H = 101, '12 Hours'
        TRIAL_24H = 102, '24 Hours'
        TRIAL_72H = 103, '72 Hours'
        ONE_MONTH = 1, '1 Month'
        THREE_MONTHS = 3, '3 Months'
        SIX_MONTHS = 6, '6 Months'
        TWELVE_MONTHS = 12, '12 Months'
        TWENTY_FOUR_MONTHS = 24, '2 Years'
        THIRTY_SIX_MONTHS = 36, '3 Years'

    name = models.CharField(max_length=100)
    category_old = models.CharField(
        max_length=50,
        choices=[('IPTV', 'IPTV'), ('GAMING', 'Gaming'), ('STREAMING', 'Streaming')],
        default='IPTV',
        null=True,
        blank=True,
    )
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name='products', null=True, blank=True)
    provider = models.ForeignKey(Provider, on_delete=models.PROTECT, related_name='products', null=True, blank=True)
    description = models.TextField(blank=True)
    external_pack_id = models.IntegerField(null=True, blank=True)
    duration_months = models.IntegerField(choices=Duration.choices, null=True, blank=True)
    price_in_credits = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    image = models.ImageField(upload_to='products/originals/', blank=True, null=True)
    thumbnail = ImageSpecField(
        source='image',
        processors=[ResizeToFill(300, 300)],
        format='WEBP',
        options={'quality': 80}
    )
    product_image = ImageSpecField(
        source='image',
        processors=[ResizeToFill(800, 800)],
        format='WEBP',
        options={'quality': 85}
    )
    is_active = models.BooleanField(default=True)
    search_vector = SearchVectorField(null=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['is_active', 'category']),
            GinIndex(fields=['search_vector']),
        ]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    duration_months = models.IntegerField(
        choices=Product.Duration.choices,
        null=True,
        blank=True,
        help_text='Leave blank for Lifetime variants.',
    )
    is_lifetime = models.BooleanField(
        default=False,
        help_text='Check for subscriptions that never expire (e.g. HotPlayer FOREVER).',
    )
    external_pack_id = models.IntegerField()
    price_in_credits = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['product', 'external_pack_id', 'duration_months']

    def __str__(self):
        if self.is_lifetime:
            return f"{self.product.name} - Lifetime"
        return f"{self.product.name} - {self.get_duration_months_display()}"


class Order(models.Model):
    class Status(models.TextChoices):
        PENDING = 'PENDING', 'Pending'
        COMPLETED = 'COMPLETED', 'Completed'
        FAILED = 'FAILED', 'Failed'
        REFUNDED = 'REFUNDED', 'Refunded'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    reseller = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='orders')
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    variant = models.ForeignKey(ProductVariant, on_delete=models.PROTECT, null=True, blank=True)
    quantity = models.PositiveIntegerField()
    unit_price_at_purchase = models.DecimalField(max_digits=10, decimal_places=2)
    product_name_at_purchase = models.CharField(max_length=100)
    total_credits = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING)
    failure_reason = models.TextField(blank=True, null=True)
    idempotency_key = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        indexes = [
            models.Index(fields=['reseller', '-created_at']),
        ]
        unique_together = ['reseller', 'idempotency_key']

    def __str__(self):
        return f"Order {self.uuid} - {self.reseller.username}"


class Credential(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='credentials')
    external_username = models.CharField(max_length=100)
    streaming_username = models.CharField(max_length=100, blank=True, null=True)
    encrypted_password = models.BinaryField()
    dns_domain = models.CharField(max_length=255)
    m3u_url = models.CharField(
        max_length=500,
        blank=True,
        default='',
        help_text='Full M3U playlist URL (separate from base DNS domain).',
    )
    data = models.JSONField(
        default=dict,
        blank=True,
        help_text='Flexible JSONB store for non-secret credential data (MAC, M3U URL, license key, etc.).',
    )
    expires_at = models.DateTimeField(
        null=True,
        blank=True,
        help_text='Null for Lifetime subscriptions.',
    )
    is_revoked = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['order']),
        ]

    def __str__(self):
        return f"{self.streaming_username or self.external_username} (Order {self.order_id})"


class CreditTransaction(models.Model):
    class Actor(models.TextChoices):
        ADMIN = 'ADMIN', 'Admin'
        RESELLER = 'RESELLER', 'Reseller'
        SYSTEM = 'SYSTEM', 'System'

    reseller = models.ForeignKey(CustomUser, on_delete=models.PROTECT, related_name='credit_transactions')
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    actor = models.CharField(max_length=20, choices=Actor.choices)
    reason = models.CharField(max_length=255)
    reference_order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['reseller', '-created_at']),
        ]

    def __str__(self):
        return f"{self.actor}: {self.delta} credits - {self.reason}"


class IdempotencyKey(models.Model):
    reseller = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    key = models.CharField(max_length=255)
    order = models.ForeignKey(Order, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ['reseller', 'key']

    def __str__(self):
        return f"Idempotency {self.key} - Order {self.order_id}"


class QuarantinedCredential(models.Model):
    order = models.ForeignKey(Order, on_delete=models.SET_NULL, null=True, blank=True)
    username = models.CharField(max_length=100)
    encrypted_password = models.BinaryField()
    provider_response = models.JSONField(default=dict)
    reason = models.TextField()
    resolved = models.BooleanField(default=False)
    resolved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        indexes = [
            models.Index(fields=['resolved']),
        ]

    def __str__(self):
        return f"Quarantined {self.username} ({'Resolved' if self.resolved else 'Unresolved'})"
