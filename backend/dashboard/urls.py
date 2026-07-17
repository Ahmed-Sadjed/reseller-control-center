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

    # Analytics & Monitoring
    path('stats/', views.DashboardStatsView.as_view(), name='dashboard-stats'),
    path('top-resellers/', views.TopResellersView.as_view(), name='dashboard-top-resellers'),
    path('recent-activity/', views.RecentActivityView.as_view(), name='dashboard-recent-activity'),
    path('revenue-chart/', views.RevenueChartView.as_view(), name='dashboard-revenue-chart'),
    path('provider-health/', views.ProviderHealthView.as_view(), name='dashboard-provider-health'),
]
