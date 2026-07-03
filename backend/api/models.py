import uuid
from decimal import Decimal
from django.db import models
from django.contrib.auth.models import AbstractUser
from django.utils import timezone
from datetime import timedelta


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


class Product(models.Model):
    class Category(models.TextChoices):
        IPTV = 'IPTV', 'IPTV'
        GAMING = 'GAMING', 'Gaming'
        STREAMING = 'STREAMING', 'Streaming'

    class Duration(models.IntegerChoices):
        ONE_MONTH = 1, '1 Month'
        THREE_MONTHS = 3, '3 Months'
        SIX_MONTHS = 6, '6 Months'
        TWELVE_MONTHS = 12, '12 Months'

    name = models.CharField(max_length=100)
    category = models.CharField(max_length=50, choices=Category.choices, default=Category.IPTV)
    description = models.TextField(blank=True)
    external_pack_id = models.IntegerField(null=True, blank=True)
    duration_months = models.IntegerField(choices=Duration.choices, null=True, blank=True)
    price_in_credits = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['is_active']),
            models.Index(fields=['category']),
        ]

    def __str__(self):
        return self.name


class ProductVariant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='variants')
    duration_months = models.IntegerField(choices=Product.Duration.choices)
    external_pack_id = models.IntegerField()
    price_in_credits = models.DecimalField(max_digits=10, decimal_places=2)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ['product', 'duration_months']

    def __str__(self):
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
    expires_at = models.DateTimeField()
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
