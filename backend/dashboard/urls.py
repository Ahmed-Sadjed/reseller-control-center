from django.urls import path
from . import views

urlpatterns = [
    # Reseller Management
    path('resellers/', views.ResellerListCreateView.as_view(), name='dashboard-reseller-list'),
    path('resellers/<int:pk>/', views.ResellerDetailView.as_view(), name='dashboard-reseller-detail'),
    path('resellers/<int:pk>/credits/', views.ResellerCreditView.as_view(), name='dashboard-reseller-credits'),
    path('resellers/<int:pk>/transactions/', views.ResellerTransactionsView.as_view(), name='dashboard-reseller-transactions'),
    path('resellers/<int:pk>/orders/', views.ResellerOrdersView.as_view(), name='dashboard-reseller-orders'),
    path('resellers/<int:pk>/toggle/', views.ResellerToggleView.as_view(), name='dashboard-reseller-toggle'),

    # Manual Products & Credentials
    path('manual-products/', views.ManualProductListView.as_view(), name='dashboard-manual-products'),
    path('manual-products/<int:pk>/', views.ManualProductDetailView.as_view(), name='dashboard-manual-product-detail'),
    path('manual-products/<int:pk>/credentials/', views.CredentialCreateView.as_view(), name='dashboard-credential-create'),
    path('manual-products/<int:pk>/credentials/bulk/', views.CredentialBulkCreateView.as_view(), name='dashboard-credential-bulk'),
    path('credentials/<int:pk>/', views.CredentialDetailView.as_view(), name='dashboard-credential-detail'),

    # WhatsApp Orders
    path('whatsapp-orders/', views.WhatsAppOrdersView.as_view(), name='dashboard-whatsapp-orders'),
    path('whatsapp-orders/<uuid:uuid>/complete/', views.CompleteWhatsAppOrderView.as_view(), name='dashboard-whatsapp-order-complete'),

    # Admin Settings
    path('settings/', views.AdminSettingsView.as_view(), name='dashboard-settings'),

    # Product Management
    path('products/', views.AdminProductListView.as_view(), name='dashboard-product-list'),
    path('products/create/', views.AdminProductCreateView.as_view(), name='dashboard-product-create'),
    path('products/<int:pk>/', views.AdminProductDetailView.as_view(), name='dashboard-product-detail'),
    path('products/<int:pk>/image/', views.AdminProductImageUploadView.as_view(), name='dashboard-product-image'),

    # Variant Management
    path('products/<int:product_pk>/variants/', views.ProductVariantListView.as_view(), name='dashboard-variant-list'),
    path('products/<int:product_pk>/variants/create/', views.ProductVariantCreateView.as_view(), name='dashboard-variant-create'),
    path('products/<int:product_pk>/variants/<int:variant_pk>/', views.ProductVariantDetailView.as_view(), name='dashboard-variant-detail'),

    # Category Management
    path('categories/', views.CategoryListView.as_view(), name='dashboard-category-list'),
    path('categories/create/', views.CategoryCreateView.as_view(), name='dashboard-category-create'),
    path('categories/<int:pk>/', views.CategoryDetailView.as_view(), name='dashboard-category-detail'),

    # Provider List
    path('providers/', views.AdminProviderListView.as_view(), name='dashboard-provider-list'),

    # Analytics & Monitoring
    path('stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('top-resellers/', views.TopResellersView.as_view(), name='dashboard-top-resellers'),
    path('recent-activity/', views.RecentActivityView.as_view(), name='dashboard-recent-activity'),
    path('provider-health/', views.ProviderHealthView.as_view(), name='dashboard-provider-health'),
]
