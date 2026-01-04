# views.py - Complete API Views
from rest_framework import generics, status, views, permissions, filters
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count, Q, F, Avg
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from .models import (
    Store, Role, Category, Product,
    Invoice, InvoiceItem, SyncLog, DailySales
)
from .serializers import (
    StoreSerializer, StoreListSerializer, RoleSerializer,
    CategorySerializer, ProductSerializer, ProductListSerializer,
    InvoiceSerializer, InvoiceListSerializer, BulkInvoiceSyncSerializer,
    DashboardStatsSerializer, SalesReportSerializer, ProductReportSerializer,
    SyncLogSerializer, UserProfileSerializer
)
from .permissions import IsOwner, IsOwnerOrReadOnly, IsSameStore



class StoreListView(generics.ListAPIView):
    """List all active stores (for registration)"""
    queryset = Store.objects.filter(is_active=True)
    serializer_class = StoreListSerializer
    permission_classes = []  # Public endpoint for registration


class StoreDetailView(generics.RetrieveAPIView):
    """Get store details"""
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user.store


class RoleListView(generics.ListAPIView):
    """List all available roles (for registration)"""
    queryset = Role.objects.all()
    serializer_class = RoleSerializer
    permission_classes = []  # Public endpoint for registration


class ProductListCreateView(generics.ListCreateAPIView):
    """List and create products"""
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active']
    search_fields = ['name', 'code', 'barcode']
    ordering_fields = ['name', 'price', 'stock', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        # Users only see products from their store
        return Product.objects.filter(store=self.request.user.store)

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return ProductListSerializer
        return ProductSerializer


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a product"""
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsSameStore]

    def get_queryset(self):
        return Product.objects.filter(store=self.request.user.store)

    def perform_destroy(self, instance):
        # Soft delete
        instance.is_active = False
        instance.save()


class LowStockProductsView(generics.ListAPIView):
    """Get products with low stock"""
    serializer_class = ProductListSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Product.objects.filter(
            store=self.request.user.store,
            is_active=True
        ).filter(stock__lte=F('low_stock_threshold'))


class CategoryListCreateView(generics.ListCreateAPIView):
    """List and create categories"""
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return Category.objects.filter(
            store=self.request.user.store,
            is_active=True
        )


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Get, update, or delete a category"""
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsSameStore]

    def get_queryset(self):
        return Category.objects.filter(store=self.request.user.store)


class InvoiceListCreateView(generics.ListCreateAPIView):
    """List and create invoices"""
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['sync_status', 'salesperson']
    ordering_fields = ['created_at', 'total']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.request.method == 'GET':
            return InvoiceListSerializer
        return InvoiceSerializer

    def get_queryset(self):
        user = self.request.user
        queryset = Invoice.objects.filter(store=user.store)

        # Salespeople only see their own invoices
        if user.role.name == 'salesperson':
            queryset = queryset.filter(salesperson=user)

        # Filter by date range if provided
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        # IMPORTANT: Prefetch items for performance
        queryset = queryset.prefetch_related('items')

        return queryset


class InvoiceDetailView(generics.RetrieveAPIView):
    """Get invoice details"""
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        user = self.request.user
        queryset = Invoice.objects.filter(store=user.store)

        # Salespeople only see their own invoices
        if user.role.name == 'salesperson':
            queryset = queryset.filter(salesperson=user)

        # IMPORTANT: Prefetch items for performance
        queryset = queryset.prefetch_related('items')

        return queryset


class BulkInvoiceSyncView(generics.CreateAPIView):
    """Sync multiple invoices (for offline recovery)"""
    serializer_class = BulkInvoiceSyncSerializer
    permission_classes = [permissions.IsAuthenticated]

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = serializer.save()

        # Log sync operation
        SyncLog.objects.create(
            user=request.user,
            store=request.user.store,
            sync_type='invoice',
            status='completed' if result['failed'] == 0 else 'failed',
            items_synced=result['synced'],
            items_failed=result['failed'],
            details=result
        )

        return Response(result, status=status.HTTP_200_OK)


class DashboardStatsView(views.APIView):
    """Get dashboard statistics"""
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get(self, request):
        store = request.user.store
        today = timezone.now().date()
        week_ago = today - timedelta(days=7)
        month_ago = today - timedelta(days=30)

        # Today's sales
        today_invoices = Invoice.objects.filter(
            store=store,
            created_at__date=today,
            sync_status='SYNCED'
        )
        today_sales = today_invoices.aggregate(total=Sum('total'))['total'] or Decimal('0.00')
        invoice_count = today_invoices.count()

        # Active salespeople today
        active_salespeople = today_invoices.values('salesperson').distinct().count()

        # Week sales
        week_sales = Invoice.objects.filter(
            store=store,
            created_at__date__gte=week_ago,
            sync_status='SYNCED'
        ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')

        # Month sales
        month_sales = Invoice.objects.filter(
            store=store,
            created_at__date__gte=month_ago,
            sync_status='SYNCED'
        ).aggregate(total=Sum('total'))['total'] or Decimal('0.00')

        # Top product today
        top_product = InvoiceItem.objects.filter(
            invoice__store=store,
            invoice__created_at__date=today,
            invoice__sync_status='SYNCED'
        ).values('product_name').annotate(
            total_quantity=Sum('quantity')
        ).order_by('-total_quantity').first()

        # Low stock products
        low_stock_count = Product.objects.filter(
            store=store,
            is_active=True
        ).filter(stock__lte=F('low_stock_threshold')).count()

        data = {
            'today_sales': today_sales,
            'invoice_count': invoice_count,
            'top_product': top_product['product_name'] if top_product else 'N/A',
            'active_salespeople': active_salespeople,
            'week_sales': week_sales,
            'month_sales': month_sales,
            'low_stock_products': low_stock_count
        }

        serializer = DashboardStatsSerializer(data)
        return Response(serializer.data)


class SalesReportView(views.APIView):
    """Get sales report by salesperson"""
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get(self, request):
        store = request.user.store

        # Get date range from query params
        start_date = request.query_params.get('start_date', timezone.now().date() - timedelta(days=30))
        end_date = request.query_params.get('end_date', timezone.now().date())

        # Sales by salesperson
        sales_data = Invoice.objects.filter(
            store=store,
            created_at__date__gte=start_date,
            created_at__date__lte=end_date,
            sync_status='SYNCED'
        ).values(
            'salesperson__id',
            'salesperson__name'
        ).annotate(
            total_sales=Sum('total'),
            invoice_count=Count('id'),
            average_sale=Avg('total')
        ).order_by('-total_sales')

        # Format data
        report_data = [
            {
                'salesperson_id': item['salesperson__id'],
                'salesperson_name': item['salesperson__name'],
                'total_sales': item['total_sales'],
                'invoice_count': item['invoice_count'],
                'average_sale': item['average_sale']
            }
            for item in sales_data
        ]

        serializer = SalesReportSerializer(report_data, many=True)
        return Response(serializer.data)


class ProductReportView(views.APIView):
    """Get product sales report"""
    permission_classes = [permissions.IsAuthenticated, IsOwner]

    def get(self, request):
        store = request.user.store

        # Get date range from query params
        start_date = request.query_params.get('start_date', timezone.now().date() - timedelta(days=30))
        end_date = request.query_params.get('end_date', timezone.now().date())

        # Product sales data
        product_data = InvoiceItem.objects.filter(
            invoice__store=store,
            invoice__created_at__date__gte=start_date,
            invoice__created_at__date__lte=end_date,
            invoice__sync_status='SYNCED'
        ).values(
            'product__id',
            'product__name',
            'product__code'
        ).annotate(
            quantity_sold=Sum('quantity'),
            total_revenue=Sum('total')
        ).order_by('-quantity_sold')[:20]  # Top 20 products

        # Format data
        report_data = [
            {
                'product_id': item['product__id'],
                'product_name': item['product__name'],
                'product_code': item['product__code'],
                'quantity_sold': item['quantity_sold'],
                'total_revenue': item['total_revenue']
            }
            for item in product_data
        ]

        serializer = ProductReportSerializer(report_data, many=True)
        return Response(serializer.data)


class SyncStatusView(views.APIView):
    """Get sync status for user"""
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        user = request.user

        # Pending invoices
        pending_invoices = Invoice.objects.filter(
            salesperson=user,
            sync_status='PENDING'
        ).count()

        # Last sync
        last_sync = SyncLog.objects.filter(
            user=user,
            status='completed'
        ).order_by('-completed_at').first()

        data = {
            'pending_invoices': pending_invoices,
            'last_sync_time': last_sync.completed_at if last_sync else None,
            'sync_status': 'online' if pending_invoices == 0 else 'pending'
        }

        return Response(data)


class SyncHistoryView(generics.ListAPIView):
    """Get sync history"""
    serializer_class = SyncLogSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return SyncLog.objects.filter(
            user=self.request.user
        ).order_by('-started_at')[:20]

class UserProfileView(generics.RetrieveUpdateAPIView):
    """Get and update user profile"""
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        return self.request.user


# ============================================
# UTILITY VIEWS
# ============================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def health_check(request):
    """Health check endpoint"""
    return Response({
        'status': 'healthy',
        'user': request.user.email,
        'store': request.user.store.name,
        'role': request.user.role.name
    })