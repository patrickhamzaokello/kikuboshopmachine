from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework.authtoken.views import obtain_auth_token
from .views import (
    CategoryViewSet,
    ProductViewSet,
    TransactionViewSet,
    ProductUpdateLogViewSet,
    SyncLogViewSet,
    UserDeviceViewSet,
    download_product_template,
    upload_products_bulk,
    export_products_excel
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

    # Bulk upload URLs
    path('products/download-template/', download_product_template, name='download_product_template'),
    path('products/bulk-upload/', upload_products_bulk, name='upload_products_bulk'),
    path('products/export-excel/', export_products_excel, name='export_products_excel'),
]