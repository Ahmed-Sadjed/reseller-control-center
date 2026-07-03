from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils import timezone
from django import forms
from django.shortcuts import redirect
from django.urls import path
from django.contrib import messages
from django.template.response import TemplateResponse
from .models import CustomUser, Product, ProductVariant, Order, Credential, CreditTransaction, IdempotencyKey, QuarantinedCredential


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


class ProductVariantInline(admin.TabularInline):
    model = ProductVariant
    extra = 1
    min_num = 1
    ordering = ['duration_months']
    fields = ['duration_months', 'external_pack_id', 'price_in_credits', 'is_active']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    inlines = [ProductVariantInline]
    list_display = ('name', 'category', 'is_active', 'created_at')
    list_filter = ('category', 'is_active')
    search_fields = ('name',)
    actions = ['archive_products']

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
    readonly_fields = ('order', 'streaming_username', 'encrypted_password', 'dns_domain', 'expires_at', 'created_at')
    exclude = ('external_username',)
    actions = ['toggle_revoke']

    def has_add_permission(self, request):
        return False

    @admin.action(description='Toggle revoke status')
    def toggle_revoke(self, request, queryset):
        for cred in queryset:
            cred.is_revoked = not cred.is_revoked
            cred.save()
        self.message_user(request, f'Toggled revoke for {queryset.count()} credential(s).', messages.SUCCESS)


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
