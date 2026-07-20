import uuid
from django.db import models
from django.conf import settings


class ManualProductCredential(models.Model):
    """
    Stores manually-entered credentials for products that don't support
    automatic API-based credential generation.

    Each credential is either a username/password pair or a single activation code,
    determined by `credential_type`.
    """

    class CredentialType(models.TextChoices):
        USERNAME_PASSWORD = 'username_password', 'Username + Password'
        SINGLE_CODE = 'single_code', 'Single Code'

    class Status(models.TextChoices):
        AVAILABLE = 'available', 'Available'
        USED = 'used', 'Used'
        EXPIRED = 'expired', 'Expired'

    uuid = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    product = models.ForeignKey(
        'api.Product',
        on_delete=models.CASCADE,
        related_name='manual_credentials',
    )
    variant = models.ForeignKey(
        'api.ProductVariant',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='manual_credentials',
        help_text='The duration variant this credential is tied to. Null for legacy/universal credentials.',
    )
    credential_type = models.CharField(
        max_length=20,
        choices=CredentialType.choices,
    )

    # Username + Password fields
    username = models.CharField(max_length=255, blank=True, default='')
    password = models.CharField(max_length=255, blank=True, default='')

    # Single Code field
    code = models.CharField(max_length=500, blank=True, default='')

    notes = models.TextField(blank=True, default='')
    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.AVAILABLE,
    )
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='assigned_credentials',
    )
    assigned_at = models.DateTimeField(null=True, blank=True)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_credentials',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=['product', 'status']),
            models.Index(fields=['product', 'variant', 'status']),
            models.Index(fields=['assigned_to', 'status']),
            models.Index(fields=['status']),
        ]
        ordering = ['-created_at']

    def __str__(self):
        if self.credential_type == self.CredentialType.USERNAME_PASSWORD:
            return f"{self.username} ({self.get_status_display()})"
        return f"{self.code[:20]}... ({self.get_status_display()})"
