from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from .views import (
    CategoryViewSet,
    ProductViewSet,
    TransactionViewSet,
    ProductUpdateLogViewSet,
    SyncLogViewSet,
    UserDeviceViewSet
)

# Create router and register viewsets
router = DefaultRouter()
router.register(r'categories', CategoryViewSet, basename='category')
router.register(r'products', ProductViewSet, basename='product')
router.register(r'transactions', TransactionViewSet, basename='transaction')
router.register(r'product-updates', ProductUpdateLogViewSet, basename='product-update')
router.register(r'sync-logs', SyncLogViewSet, basename='sync-log')
router.register(r'devices', UserDeviceViewSet, basename='device')

# Define URL patterns
urlpatterns = [
    # Router URLs (includes all viewset endpoints)
    path('', include(router.urls)),
]