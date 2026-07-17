from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django.utils.html import format_html
from django import forms
from django.shortcuts import redirect
from django.urls import path
from django.contrib import messages
from django.template.response import TemplateResponse
from .models import CustomUser, Provider, Category, Product, ProductVariant, Order, Credential, CreditTransaction, IdempotencyKey, QuarantinedCredential
from .device_services import check_device, get_credential_for_user
from .providers import get_adapter_for_provider, ADAPTER_REGISTRY


class AddCreditsForm(forms.Form):
    delta = forms.DecimalField(label='Credit Amount', max_digits=12, decimal_places=2, min_value=0.01)
    reason = forms.CharField(max_length=255, required=False, initial='Admin top-up')


@admin.action(description='Add credits to selected resellers')
def add_credits(modeladmin, request, queryset):
    if 'apply' in request.POST:
        form = AddCreditsForm(request.POST)
        if form.is_valid():
            delta = form.cleaned_data['delta']
            reason = form.cleaned_data['reason'] or 'Admin top-up'
            for user in queryset:
                user.credit_balance += delta
                user.save()
                CreditTransaction.objects.create(
                    reseller=user,
                    delta=delta,
                    balance_after=user.credit_balance,
                    actor=CreditTransaction.Actor.ADMIN,
                    reason=reason,
                )
            modeladmin.message_user(request, f'Added {delta} credits to {queryset.count()} reseller(s).', messages.SUCCESS)
            return redirect(request.get_full_path())
    form = AddCreditsForm(initial={'_selected_action': queryset.values_list('pk', flat=True)})
    return TemplateResponse(request, 'admin/add_credits.html', {
        'form': form,
        'users': queryset,
        'title': 'Add Credits',
    })


@admin.register(CustomUser)
class CustomUserAdmin(BaseUserAdmin):
    list_display = ('username', 'email', 'role', 'credit_balance', 'is_active', 'uuid')
    list_filter = ('role', 'is_active')
    search_fields = ('username', 'email')
    ordering = ('-date_joined',)
    readonly_fields = ('credit_balance', 'uuid', 'last_login_ip')
    actions = [add_credits]

    fieldsets = (
        (None, {'fields': ('username', 'password')}),
        ('Personal info', {'fields': ('email',)}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Reseller Info', {'fields': ('role', 'credit_balance', 'created_by', 'uuid', 'last_login_ip')}),
        ('Important dates', {'fields': ('last_login', 'date_joined')}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'role'),
        }),
    )


class ProviderAdminForm(forms.ModelForm):
    raw_token = forms.CharField(
        required=False,
        widget=forms.PasswordInput(render_value=True),
        label='API Token',
        help_text='Enter a new token to update. Leave blank to keep existing.',
    )

    class Meta:
        model = Provider
        fields = '__all__'


@admin.register(Provider)
class ProviderAdmin(admin.ModelAdmin):
    form = ProviderAdminForm
    list_display = ('name', 'slug', 'adapter_key', 'capabilities_display', 'api_endpoint', 'is_active', 'created_at')
    list_filter = ('is_active', 'adapter_key')
    search_fields = ('name', 'slug')
    readonly_fields = ('api_token',)
    prepopulated_fields = {'slug': ('name',)}

    def capabilities_display(self, obj):
        """
        CRITICAL: Bypass USE_MOCK_PROVIDER — look up the adapter class directly
        from ADAPTER_REGISTRY so we show the real capabilities per provider,
        not MockProviderAdapter's capabilities for all of them.
        """
        adapter_class = ADAPTER_REGISTRY.get(obj.adapter_key)
        if adapter_class:
            try:
                # Instantiate with the provider to read capabilities
                adapter = adapter_class(provider=obj)
                caps = sorted(adapter.capabilities)
                return ', '.join(caps)
            except Exception:
                return '—'
        return '—'
    capabilities_display.short_description = 'Capabilities'

    def save_model(self, request, obj, form, change):
        raw_token = form.cleaned_data.get('raw_token')
        if raw_token:
            obj.set_token(raw_token)
        super().save_model(request, obj, form, change)


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'slug', 'sort_order', 'product_count', 'is_active', 'image_tag')
    prepopulated_fields = {'slug': ('name',)}
    search_fields = ('name',)
    list_editable = ('sort_order', 'is_active')
    fields = ('name', 'slug', 'description', 'image', 'image_tag', 'is_active', 'sort_order')
    readonly_fields = ('image_tag',)

    def product_count(self, obj):
        return obj.products.filter(is_active=True).count()
    product_count.short_description = 'Active Products'

    def image_tag(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:100px;border-radius:4px;" />', obj.image.url)
        return '-'
    image_tag.short_description = 'Preview'


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    min_num = 1
    ordering = ['duration_months']
    fields = ['is_lifetime', 'duration_months', 'external_pack_id', 'price_in_credits', 'is_active']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductVariantInline]
    list_display = ('name', 'category', 'provider', 'is_active', 'image_tag', 'created_at')
    list_filter = ('category', 'provider', 'is_active')
    search_fields = ('name',)
    autocomplete_fields = ('category', 'provider')
    readonly_fields = ('image_tag',)
    fieldsets = (
        (None, {'fields': ('name', 'category', 'provider', 'description')}),
        ('Media', {'fields': ('image', 'image_tag')}),
        ('Manual Credentials', {'fields': ('is_manual', 'credential_type'), 'classes': ('collapse',)}),
        ('Status', {'fields': ('is_active',)}),
    )
    actions = ['archive_products']

    def image_tag(self, obj):
        if obj.image:
            return format_html('<img src="{}" style="max-height:100px;border-radius:4px;" />', obj.image.url)
        return '-'
    image_tag.short_description = 'Preview'

    @admin.action(description='Archive selected products')
    def archive_products(self, request, queryset):
        queryset.update(is_active=False)


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    list_display = ('uuid', 'reseller', 'product_name_at_purchase', 'quantity', 'total_credits', 'status', 'created_at')
    list_filter = ('status', 'created_at')
    search_fields = ('uuid', 'reseller__username')
    readonly_fields = ('uuid', 'reseller', 'product', 'quantity', 'unit_price_at_purchase',
                       'product_name_at_purchase', 'total_credits', 'idempotency_key', 'created_at')
    actions = ['refund_order']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Refund selected orders')
    def refund_order(self, request, queryset):
        for order in queryset:
            if order.status in ('COMPLETED', 'FAILED'):
                reseller = order.reseller
                reseller.credit_balance += order.total_credits
                reseller.save()
                CreditTransaction.objects.create(
                    reseller=reseller,
                    delta=order.total_credits,
                    balance_after=reseller.credit_balance,
                    actor=CreditTransaction.Actor.ADMIN,
                    reason=f"Manual refund for Order #{order.uuid}",
                    reference_order=order,
                )
                order.status = Order.Status.REFUNDED
                order.save()
        self.message_user(request, f'Refunded {queryset.count()} order(s).', messages.SUCCESS)


@admin.register(Credential)
class CredentialAdmin(admin.ModelAdmin):
    list_display = ('streaming_username', 'order', 'expires_at', 'is_revoked', 'created_at')
    list_filter = ('is_revoked', 'expires_at')
    search_fields = ('streaming_username', 'external_username')
    readonly_fields = ('order', 'streaming_username', 'encrypted_password', 'dns_domain', 'm3u_url', 'data', 'expires_at', 'created_at')
    exclude = ('external_username',)
    actions = ['toggle_revoke', 'check_device']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Toggle revoke status')
    def toggle_revoke(self, request, queryset):
        for cred in queryset:
            cred.is_revoked = not cred.is_revoked
            cred.save()
        self.message_user(request, f'Toggled revoke for {queryset.count()} credential(s).', messages.SUCCESS)

    @admin.action(description='Check device status')
    def check_device(self, request, queryset):
        results = []
        for cred in queryset:
            mac = cred.streaming_username or cred.external_username
            try:
                adapter = get_adapter_for_provider(cred.order.product.provider)
                data = adapter.check_device(mac)
                results.append(f"{mac}: OK - {data.get('status', 'unknown')}")
            except NotImplementedError:
                results.append(f"{mac}: Device check not supported")
            except Exception as e:
                results.append(f"{mac}: Error - {e}")
        self.message_user(request, '\n'.join(results), messages.SUCCESS)

@admin.register(CreditTransaction)
class CreditTransactionAdmin(admin.ModelAdmin):
    list_display = ('reseller', 'delta', 'balance_after', 'actor', 'reason', 'created_at')
    list_filter = ('actor', 'created_at')
    search_fields = ('reseller__username', 'reason')
    readonly_fields = ('reseller', 'delta', 'balance_after', 'actor', 'reason', 'reference_order', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(IdempotencyKey)
class IdempotencyKeyAdmin(admin.ModelAdmin):
    list_display = ('key', 'reseller', 'order', 'created_at')
    readonly_fields = ('reseller', 'key', 'order', 'created_at')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False


@admin.register(QuarantinedCredential)
class QuarantinedCredentialAdmin(admin.ModelAdmin):
    list_display = ('username', 'order', 'resolved', 'created_at')
    list_filter = ('resolved',)
    search_fields = ('username', 'reason')
    readonly_fields = ('order', 'username', 'encrypted_password', 'provider_response', 'reason', 'created_at')
    actions = ['mark_resolved']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Mark selected as resolved')
    def mark_resolved(self, request, queryset):
        now = timezone.now()
        queryset.update(resolved=True, resolved_at=now)
        self.message_user(request, f'Marked {queryset.count()} quarantine(s) as resolved.', messages.SUCCESS)
