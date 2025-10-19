from django.db.migrations import serializer
from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Sum
from django.utils import timezone
from django_filters.rest_framework import DjangoFilterBackend

from . import models
from .models import (
    Category, Product, ProductUpdateLog, Transaction,
    TransactionItem, SyncLog, UserDevice
)
from .serializers import (
    CategorySerializer, ProductListSerializer, ProductDetailSerializer,
    ProductUpdateLogSerializer, TransactionSerializer, TransactionListSerializer,
    SyncLogSerializer, UserDeviceSerializer, ProductSyncSerializer,
    ProductBulkSearchSerializer
)


class CategoryViewSet(viewsets.ModelViewSet):
    """ViewSet for managing product categories"""
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'description']
    ordering_fields = ['name', 'created_at']


class ProductViewSet(viewsets.ModelViewSet):
    """ViewSet for managing products with sync capabilities"""
    queryset = Product.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_fields = ['category', 'is_active']
    search_fields = ['name', 'barcode', 'sku', 'description']
    ordering_fields = ['name', 'updated_at', 'quantity_in_stock', 'retail_price']

    def get_serializer_class(self):
        if self.action == 'list':
            return ProductListSerializer
        return ProductDetailSerializer

    def get_queryset(self):
        queryset = Product.objects.select_related('category')

        # Filter by stock level
        low_stock = self.request.query_params.get('low_stock', None)
        if low_stock:
            queryset = queryset.filter(quantity_in_stock__lte=models.F('reorder_level'))

        return queryset

    @action(detail=False, methods=['post'])
    def quick_search(self, request):
        """
        Optimized search endpoint for POS scanning/searching
        Searches by name, barcode, or SKU simultaneously
        """
        serializer = ProductBulkSearchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        query = serializer.validated_data['query']
        search_fields = serializer.validated_data['search_fields']
        is_active_only = serializer.validated_data['is_active_only']

        # Build dynamic query
        q_objects = Q()
        if 'name' in search_fields:
            q_objects |= Q(name__icontains=query)
        if 'barcode' in search_fields:
            q_objects |= Q(barcode__iexact=query)
        if 'sku' in search_fields:
            q_objects |= Q(sku__iexact=query)

        queryset = Product.objects.filter(q_objects)

        if is_active_only:
            queryset = queryset.filter(is_active=True)

        # Prioritize exact matches
        exact_matches = queryset.filter(
            Q(barcode__iexact=query) | Q(sku__iexact=query)
        )

        if exact_matches.exists():
            results = exact_matches[:5]
        else:
            results = queryset[:10]

        serializer = ProductListSerializer(results, many=True)
        return Response(serializer.data)

    @action(detail=False, methods=['post'])
    def sync(self, request):
        """
        Sync endpoint for offline clients
        Returns products updated since last sync
        """
        serializer = ProductSyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        device_id = serializer.validated_data['device_id']
        last_version = serializer.validated_data.get('last_version_synced', 0)

        # Get or create device
        device, created = UserDevice.objects.get_or_create(
            user=request.user,
            device_id=device_id,
            defaults={'device_name': request.META.get('HTTP_USER_AGENT', 'Unknown')}
        )

        # Get updated products
        updated_products = Product.objects.filter(
            version__gt=last_version,
            is_active=True
        ).select_related('category')

        # Get deleted/deactivated products
        deactivated_products = Product.objects.filter(
            version__gt=last_version,
            is_active=False
        ).values('id', 'barcode', 'sku')

        # Update device sync info
        device.last_sync_at = timezone.now()
        if updated_products.exists():
            device.last_product_version_synced = updated_products.order_by('-version').first().version
        device.save()

        # Get recent updates for notification
        recent_updates = ProductUpdateLog.objects.filter(
            timestamp__gt=device.last_sync_at - timezone.timedelta(hours=24)
        ).select_related('product')[:50]

        response_data = {
            'updated_products': ProductListSerializer(updated_products, many=True).data,
            'deactivated_products': list(deactivated_products),
            'recent_updates': ProductUpdateLogSerializer(recent_updates, many=True).data,
            'last_version': device.last_product_version_synced,
            'sync_timestamp': timezone.now(),
            'total_active_products': Product.objects.filter(is_active=True).count()
        }

        return Response(response_data)

    @action(detail=False, methods=['get'])
    def updates_summary(self, request):
        """Get summary of recent product updates"""
        hours = int(request.query_params.get('hours', 24))
        since = timezone.now() - timezone.timedelta(hours=hours)

        updates = ProductUpdateLog.objects.filter(timestamp__gte=since)

        summary = {
            'total_updates': updates.count(),
            'by_action': dict(updates.values('action').annotate(count=Count('action')).values_list('action', 'count')),
            'recent_updates': ProductUpdateLogSerializer(updates[:20], many=True).data
        }

        return Response(summary)

    @action(detail=True, methods=['post'])
    def adjust_stock(self, request, pk=None):
        """Manually adjust stock levels"""
        product = self.get_object()
        adjustment = request.data.get('adjustment', 0)
        reason = request.data.get('reason', 'Manual adjustment')

        try:
            adjustment = int(adjustment)
        except ValueError:
            return Response(
                {'error': 'Invalid adjustment value'},
                status=status.HTTP_400_BAD_REQUEST
            )

        old_stock = product.quantity_in_stock
        product.quantity_in_stock += adjustment

        if product.quantity_in_stock < 0:
            return Response(
                {'error': 'Stock cannot be negative'},
                status=status.HTTP_400_BAD_REQUEST
            )

        product.save()

        # Log the change
        ProductUpdateLog.objects.create(
            product=product,
            action='STOCK_CHANGE',
            changed_fields={'quantity_in_stock': True},
            old_values={'quantity_in_stock': old_stock, 'reason': reason},
            new_values={'quantity_in_stock': product.quantity_in_stock},
            changed_by=request.user
        )

        return Response({
            'message': 'Stock adjusted successfully',
            'old_stock': old_stock,
            'new_stock': product.quantity_in_stock,
            'adjustment': adjustment
        })

    @action(detail=False, methods=['get'])
    def low_stock(self, request):
        """Get products with low stock"""
        products = Product.objects.filter(
            quantity_in_stock__lte=models.F('reorder_level'),
            is_active=True
        ).order_by('quantity_in_stock')

        serializer = ProductListSerializer(products, many=True)
        return Response(serializer.data)


class TransactionViewSet(viewsets.ModelViewSet):
    """ViewSet for managing transactions/sales"""
    queryset = Transaction.objects.all()
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['transaction_type', 'payment_status', 'is_synced', 'created_by']
    ordering_fields = ['created_at', 'total_amount']

    def get_serializer_class(self):
        if self.action == 'list':
            return TransactionListSerializer
        return TransactionSerializer

    def get_queryset(self):
        queryset = Transaction.objects.select_related('created_by').prefetch_related('items')

        # Filter by date range
        start_date = self.request.query_params.get('start_date', None)
        end_date = self.request.query_params.get('end_date', None)

        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        # Filter unsynced transactions for offline sync
        unsynced = self.request.query_params.get('unsynced', None)
        if unsynced:
            queryset = queryset.filter(is_synced=False)

        return queryset

    @action(detail=False, methods=['post'])
    def bulk_sync(self, request):
        """
        Sync multiple transactions from offline device
        Handles conflicts and validates data
        """
        transactions_data = request.data.get('transactions', [])

        if not transactions_data:
            return Response(
                {'error': 'No transactions provided'},
                status=status.HTTP_400_BAD_REQUEST
            )

        synced = []
        failed = []

        for trans_data in transactions_data:
            try:
                # Check if transaction already exists
                transaction_id = trans_data.get('transaction_id')
                if Transaction.objects.filter(transaction_id=transaction_id).exists():
                    failed.append({
                        'transaction_id': transaction_id,
                        'error': serializer.errors
                    })
            except Exception as e:
                failed.append({
                    'transaction_id': trans_data.get('transaction_id', 'unknown'),
                    'error': str(e)
                })

        # Log sync operation
        SyncLog.objects.create(
            user=request.user,
            sync_type='TRANSACTIONS_PUSH',
            status='SUCCESS' if not failed else 'PARTIAL' if synced else 'FAILED',
            items_synced=len(synced),
            errors=failed,
            completed_at=timezone.now()
        )

        return Response({
            'synced': synced,
            'failed': failed,
            'total_synced': len(synced),
            'total_failed': len(failed)
        })

    @action(detail=False, methods=['get'])
    def sales_summary(self, request):
        """Get sales summary and statistics"""
        # Date range
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')

        queryset = Transaction.objects.all()

        if start_date:
            queryset = queryset.filter(created_at__gte=start_date)
        if end_date:
            queryset = queryset.filter(created_at__lte=end_date)

        # Calculate statistics
        stats = queryset.aggregate(
            total_transactions=Count('id'),
            total_revenue=Sum('total_amount'),
            total_paid=Sum('amount_paid'),
            retail_count=Count('id', filter=Q(transaction_type='RETAIL')),
            wholesale_count=Count('id', filter=Q(transaction_type='WHOLESALE')),
            paid_count=Count('id', filter=Q(payment_status='PAID')),
            unpaid_count=Count('id', filter=Q(payment_status='UNPAID'))
        )

        # Top selling products
        top_products = TransactionItem.objects.filter(
            transaction__in=queryset
        ).values(
            'product__name', 'product__sku'
        ).annotate(
            total_quantity=Sum('quantity'),
            total_revenue=Sum('line_total')
        ).order_by('-total_quantity')[:10]

        return Response({
            'statistics': stats,
            'top_products': list(top_products),
            'date_range': {
                'start': start_date,
                'end': end_date
            }
        })

    @action(detail=True, methods=['get'])
    def receipt(self, request, pk=None):
        """Get formatted receipt data"""
        transaction = self.get_object()

        receipt_data = {
            'transaction_id': str(transaction.transaction_id),
            'transaction_type': transaction.get_transaction_type_display(),
            'date': transaction.created_at,
            'cashier': transaction.created_by.username if transaction.created_by else 'N/A',
            'customer_name': transaction.customer_name,
            'customer_phone': transaction.customer_phone,
            'items': [
                {
                    'name': item.product_name,
                    'sku': item.product_sku,
                    'quantity': item.quantity,
                    'unit_price': float(item.unit_price),
                    'line_total': float(item.line_total)
                }
                for item in transaction.items.all()
            ],
            'subtotal': float(transaction.subtotal),
            'discount': float(transaction.discount),
            'total': float(transaction.total_amount),
            'amount_paid': float(transaction.amount_paid),
            'balance': float(transaction.total_amount - transaction.amount_paid),
            'payment_status': transaction.get_payment_status_display(),
            'notes': transaction.notes
        }

        return Response(receipt_data)


class ProductUpdateLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing product update logs"""
    queryset = ProductUpdateLog.objects.all()
    serializer_class = ProductUpdateLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['product', 'action', 'changed_by']
    ordering_fields = ['timestamp']

    @action(detail=False, methods=['get'])
    def recent(self, request):
        """Get recent updates with pagination"""
        hours = int(request.query_params.get('hours', 24))
        since = timezone.now() - timezone.timedelta(hours=hours)

        updates = self.queryset.filter(timestamp__gte=since)

        page = self.paginate_queryset(updates)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)

        serializer = self.get_serializer(updates, many=True)
        return Response(serializer.data)


class SyncLogViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing sync logs"""
    queryset = SyncLog.objects.all()
    serializer_class = SyncLogSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_fields = ['user', 'sync_type', 'status']
    ordering_fields = ['started_at']

    def get_queryset(self):
        # Users can only see their own sync logs
        return self.queryset.filter(user=self.request.user)


class UserDeviceViewSet(viewsets.ModelViewSet):
    """ViewSet for managing user devices"""
    queryset = UserDevice.objects.all()
    serializer_class = UserDeviceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        # Users can only see their own devices
        return self.queryset.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a device"""
        device = self.get_object()
        device.is_active = False
        device.save()

        return Response({'message': 'Device deactivated successfully'})

    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a device"""
        device = self.get_object()
        device.is_active = True
        device.save()

        return Response({'message': 'Device activated successfully'})
