from django.urls import path
from . import views

urlpatterns = [
    path('auth/login/', views.LoginView.as_view(), name='auth-login'),
    path('auth/refresh/', views.RefreshView.as_view(), name='auth-refresh'),
    path('auth/logout/', views.LogoutView.as_view(), name='auth-logout'),
    path('auth/me/', views.MeView.as_view(), name='auth-me'),
    path('categories/', views.CategoryListView.as_view(), name='category-list'),
    path('products/', views.ProductListView.as_view(), name='product-list'),
    path('purchase/', views.PurchaseView.as_view(), name='purchase'),
    path('orders/', views.OrderListView.as_view(), name='order-list'),
    path('orders/<uuid:uuid>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('orders/<uuid:uuid>/credentials/', views.OrderCredentialsView.as_view(), name='order-credentials'),
    path('orders/<uuid:uuid>/status/', views.OrderStatusView.as_view(), name='order-status'),
    path('stats/', views.StatsView.as_view(), name='stats'),
    path('health/', views.HealthCheckView.as_view(), name='health'),
    path('rq/', views.RQStatsView.as_view(), name='rq-stats'),
]
