from django.contrib import admin
from .models import ManualProductCredential


@admin.register(ManualProductCredential)
class ManualProductCredentialAdmin(admin.ModelAdmin):
    list_display = ('product', 'variant_display', 'credential_type', 'username', 'code_preview', 'status', 'assigned_to', 'created_at')
    list_filter = ('status', 'credential_type', 'product', 'variant')
    search_fields = ('username', 'code', 'assigned_to__username')
    readonly_fields = ('uuid', 'created_at', 'updated_at')
    list_select_related = ('variant',)

    def variant_display(self, obj):
        if obj.variant:
            return str(obj.variant)
        return '—'
    variant_display.short_description = 'Duration'

    def code_preview(self, obj):
        if obj.code:
            return f"{obj.code[:15]}..." if len(obj.code) > 15 else obj.code
        return '-'
    code_preview.short_description = 'Code'
