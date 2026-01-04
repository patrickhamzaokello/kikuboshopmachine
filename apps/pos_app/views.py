# pos_app/views.py

from rest_framework import generics, status, views, permissions, filters
from rest_framework.response import Response
from rest_framework.decorators import api_view, permission_classes
from rest_framework.exceptions import ValidationError
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Sum, Count, Q, F, Avg
from django.db import transaction
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
import logging

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
from .permissions import (
    IsOwner, IsOwnerOrReadOnly, IsSameStore,
    IsSalespersonOrOwner, CanCreateInvoice, CanViewReports
)

# Set up logging
logger = logging.getLogger(__name__)


# ============================================
# STORE & ROLE VIEWS
# ============================================

class StoreListView(generics.ListAPIView):
    """
    Public endpoint to list all active stores.
    Used during registration to select a store.
    """
    queryset = Store.objects.filter(is_active=True)
    serializer_class = StoreListSerializer
    permission_classes = []  # Public endpoint
    pagination_class = None  # No pagination for store list


class StoreDetailView(generics.RetrieveAPIView):
    """
    Get authenticated user's store details.
    """
    serializer_class = StoreSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return the store of the authenticated user"""
        return self.request.user.store


class RoleListView(generics.ListAPIView):
    """
    Public endpoint to list all available roles.
    Used during registration to select a role.
    """
    queryset = Role.objects.all().order_by('name')
    serializer_class = RoleSerializer
    permission_classes = []  # Public endpoint
    pagination_class = None  # No pagination for role list


# ============================================
# CATEGORY VIEWS
# ============================================

class CategoryListCreateView(generics.ListCreateAPIView):
    """
    List and create product categories.
    Users can only see and create categories for their store.
    """
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        """Return only active categories from user's store"""
        return Category.objects.filter(
            store=self.request.user.store,
            is_active=True
        ).select_related('parent', 'store')

    def perform_create(self, serializer):
        """Set store automatically from authenticated user"""
        try:
            serializer.save(store=self.request.user.store)
            logger.info(
                f"Category '{serializer.instance.name}' created by user {self.request.user.email}"
            )
        except Exception as e:
            logger.error(f"Error creating category: {str(e)}")
            raise


class CategoryDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Get, update, or soft-delete a category.
    """
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated, IsSameStore]

    def get_queryset(self):
        """Return categories from user's store"""
        return Category.objects.filter(
            store=self.request.user.store
        ).select_related('parent', 'store')

    def perform_destroy(self, instance):
        """Soft delete - mark as inactive instead of deleting"""
        instance.is_active = False
        instance.save()
        logger.info(
            f"Category '{instance.name}' deactivated by user {self.request.user.email}"
        )


# ============================================
# PRODUCT VIEWS
# ============================================

class ProductListCreateView(generics.ListCreateAPIView):
    """
    List and create products.
    Users can only see and create products for their store.
    """
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active']
    search_fields = ['name', 'code', 'barcode', 'description']
    ordering_fields = ['name', 'price', 'stock', 'created_at']
    ordering = ['name']

    def get_queryset(self):
        """Return products from user's store with optimized queries"""
        queryset = Product.objects.filter(
            store=self.request.user.store
        ).select_related('category', 'store', 'created_by')

        # Add filter for low stock if requested
        if self.request.query_params.get('low_stock') == 'true':
            queryset = queryset.filter(stock__lte=F('low_stock_threshold'))

        return queryset

    def get_serializer_class(self):
        """Use list serializer for GET, full serializer for POST"""
        if self.request.method == 'GET':
            return ProductListSerializer
        return ProductSerializer

    def perform_create(self, serializer):
        """Set store and created_by automatically"""
        try:
            serializer.save(
                store=self.request.user.store,
                created_by=self.request.user
            )
            logger.info(
                f"Product '{serializer.instance.name}' created by user {self.request.user.email}"
            )
        except Exception as e:
            logger.error(f"Error creating product: {str(e)}")
            raise


class ProductDetailView(generics.RetrieveUpdateDestroyAPIView):
    """
    Get, update, or soft-delete a product.
    """
    serializer_class = ProductSerializer
    permission_classes = [permissions.IsAuthenticated, IsSameStore]

    def get_queryset(self):
        """Return products from user's store"""
        return Product.objects.filter(
            store=self.request.user.store
        ).select_related('category', 'store', 'created_by')

    def perform_destroy(self, instance):
        """Soft delete - mark as inactive instead of deleting"""
        instance.is_active = False
        instance.save()
        logger.info(
            f"Product '{instance.name}' deactivated by user {self.request.user.email}"
        )


class LowStockProductsView(generics.ListAPIView):
    """
    Get products with stock below or equal to their low stock threshold.
    """
    serializer_class = ProductListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Return all low stock items

    def get_queryset(self):
        """Return low stock products from user's store"""
        return Product.objects.filter(
            store=self.request.user.store,
            is_active=True
        ).filter(
            stock__lte=F('low_stock_threshold')
        ).select_related('category', 'store').order_by('stock')


# ============================================
# INVOICE VIEWS
# ============================================

class InvoiceListCreateView(generics.ListCreateAPIView):
    """
    List and create invoices.
    Salespeople see only their invoices, owners/managers see all.
    """
    permission_classes = [permissions.IsAuthenticated, CanCreateInvoice]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['sync_status']
    ordering_fields = ['created_at', 'total']
    ordering = ['-created_at']

    def get_serializer_class(self):
        """Use list serializer for GET, full serializer for POST"""
        if self.request.method == 'GET':
            return InvoiceListSerializer
        return InvoiceSerializer

    def get_queryset(self):
        """Return invoices based on user role"""
        user = self.request.user
        queryset = Invoice.objects.filter(store=user.store)

        # Salespeople only see their own invoices
        if user.role.name == 'salesperson':
            queryset = queryset.filter(salesperson=user)

        # Filter by date range if provided
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')

        if start_date:
            try:
                start = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                queryset = queryset.filter(created_at__gte=start)
            except ValueError:
                pass  # Ignore invalid date format

        if end_date:
            try:
                end = datetime.fromisoformat(end_date.replace('Z', '+00:00'))
                queryset = queryset.filter(created_at__lte=end)
            except ValueError:
                pass  # Ignore invalid date format

        # Optimize queries
        queryset = queryset.select_related(
            'store', 'salesperson', 'salesperson__role'
        ).prefetch_related('items__product')

        return queryset

    @transaction.atomic
    def perform_create(self, serializer):
        """
        Create invoice with transaction to ensure data consistency.
        """
        try:
            invoice = serializer.save(
                store=self.request.user.store,
                salesperson=self.request.user
            )
            logger.info(
                f"Invoice {invoice.invoice_number} created by user {self.request.user.email}"
            )
        except Exception as e:
            logger.error(f"Error creating invoice: {str(e)}")
            raise ValidationError({"error": "Failed to create invoice. Please try again."})


class InvoiceDetailView(generics.RetrieveAPIView):
    """
    Get invoice details with all items.
    Salespeople can only view their own invoices.
    """
    serializer_class = InvoiceSerializer
    permission_classes = [permissions.IsAuthenticated, IsSalespersonOrOwner]

    def get_queryset(self):
        """Return invoices based on user role"""
        user = self.request.user
        queryset = Invoice.objects.filter(store=user.store)

        # Salespeople only see their own invoices
        if user.role.name == 'salesperson':
            queryset = queryset.filter(salesperson=user)

        # Optimize queries
        queryset = queryset.select_related(
            'store', 'salesperson', 'salesperson__role'
        ).prefetch_related('items__product')

        return queryset


class BulkInvoiceSyncView(generics.CreateAPIView):
    """
    Sync multiple invoices from offline mode.
    Uses transactions to ensure all-or-nothing processing per invoice.
    """
    serializer_class = BulkInvoiceSyncSerializer
    permission_classes = [permissions.IsAuthenticated, CanCreateInvoice]

    def create(self, request, *args, **kwargs):
        """Process bulk invoice sync"""
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            # Process sync
            result = serializer.save()

            # Log sync operation
            log_status = 'completed' if result['failed'] == 0 else 'failed'
            sync_log = SyncLog.objects.create(
                user=request.user,
                store=request.user.store,
                sync_type='invoice',
                status=log_status,
                items_synced=result['synced'],
                items_failed=result['failed'],
                details=result,
                completed_at=timezone.now()
            )

            logger.info(
                f"Bulk sync completed: {result['synced']} synced, "
                f"{result['failed']} failed by user {request.user.email}"
            )

            return Response(result, status=status.HTTP_200_OK)

        except Exception as e:
            logger.error(f"Bulk sync error: {str(e)}")

            # Log failed sync
            SyncLog.objects.create(
                user=request.user,
                store=request.user.store,
                sync_type='invoice',
                status='failed',
                items_synced=0,
                items_failed=0,
                error_message=str(e),
                completed_at=timezone.now()
            )

            return Response(
                {"error": "Sync failed. Please try again."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# DASHBOARD & ANALYTICS VIEWS
# ============================================

class DashboardStatsView(views.APIView):
    """
    Get dashboard statistics for store owners and managers.
    """
    permission_classes = [permissions.IsAuthenticated, CanViewReports]

    def get(self, request):
        """Calculate and return dashboard statistics"""
        try:
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
            today_sales = today_invoices.aggregate(
                total=Sum('total')
            )['total'] or Decimal('0.00')
            invoice_count = today_invoices.count()

            # Active salespeople today
            active_salespeople = today_invoices.values(
                'salesperson'
            ).distinct().count()

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

            # Low stock products count
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

        except Exception as e:
            logger.error(f"Dashboard stats error: {str(e)}")
            return Response(
                {"error": "Failed to fetch dashboard statistics"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SalesReportView(views.APIView):
    """
    Get sales report by salesperson.
    Only accessible to owners and managers.
    """
    permission_classes = [permissions.IsAuthenticated, CanViewReports]

    def get(self, request):
        """Generate sales report by salesperson"""
        try:
            store = request.user.store

            # Get date range from query params
            start_date = request.query_params.get(
                'start_date',
                (timezone.now().date() - timedelta(days=30)).isoformat()
            )
            end_date = request.query_params.get(
                'end_date',
                timezone.now().date().isoformat()
            )

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

        except Exception as e:
            logger.error(f"Sales report error: {str(e)}")
            return Response(
                {"error": "Failed to generate sales report"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class ProductReportView(views.APIView):
    """
    Get product sales report.
    Only accessible to owners and managers.
    """
    permission_classes = [permissions.IsAuthenticated, CanViewReports]

    def get(self, request):
        """Generate product sales report"""
        try:
            store = request.user.store

            # Get date range and limit from query params
            start_date = request.query_params.get(
                'start_date',
                (timezone.now().date() - timedelta(days=30)).isoformat()
            )
            end_date = request.query_params.get(
                'end_date',
                timezone.now().date().isoformat()
            )
            limit = int(request.query_params.get('limit', 20))

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
            ).order_by('-quantity_sold')[:limit]

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

        except Exception as e:
            logger.error(f"Product report error: {str(e)}")
            return Response(
                {"error": "Failed to generate product report"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


# ============================================
# SYNC VIEWS
# ============================================

class SyncStatusView(views.APIView):
    """
    Get sync status for authenticated user.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        """Return current sync status"""
        try:
            user = request.user

            # Count pending invoices
            pending_invoices = Invoice.objects.filter(
                salesperson=user,
                sync_status='PENDING'
            ).count()

            # Get last successful sync
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

        except Exception as e:
            logger.error(f"Sync status error: {str(e)}")
            return Response(
                {"error": "Failed to fetch sync status"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )


class SyncHistoryView(generics.ListAPIView):
    """
    Get sync history for authenticated user.
    """
    serializer_class = SyncLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None  # Return all recent logs

    def get_queryset(self):
        """Return last 20 sync logs for user"""
        return SyncLog.objects.filter(
            user=self.request.user
        ).select_related('store').order_by('-started_at')[:20]


# ============================================
# PROFILE VIEWS
# ============================================

class UserProfileView(generics.RetrieveUpdateAPIView):
    """
    Get and update user profile.
    Users can only update certain fields.
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_object(self):
        """Return authenticated user"""
        return self.request.user


# ============================================
# UTILITY VIEWS
# ============================================

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def health_check(request):
    """
    Health check endpoint to verify API and user authentication.
    """
    return Response({
        'status': 'healthy',
        'timestamp': timezone.now().isoformat(),
        'user': {
            'email': request.user.email,
            'name': request.user.name,
            'store': request.user.store.name if request.user.store else None,
            'role': request.user.role.name if request.user.role else None
        }
    })