from django.db.migrations import serializer
from django.shortcuts import render

# Create your views here.
from rest_framework import viewsets, status, filters
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Count, Sum
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

from django.shortcuts import render, redirect
from django.contrib.admin.views.decorators import staff_member_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter
import openpyxl
from decimal import Decimal, InvalidOperation
from django.db import transaction


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


@staff_member_required
def download_product_template(request):
    """
    Download Excel template for bulk product upload
    """
    # Create workbook
    wb = Workbook()

    # Instructions Sheet
    ws_instructions = wb.active
    ws_instructions.title = "Instructions"

    # Header styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=12)

    # Instructions content
    instructions = [
        ["KIKUBO POS - BULK PRODUCT UPLOAD TEMPLATE"],
        [""],
        ["INSTRUCTIONS:"],
        ["1. Fill in the 'Products' sheet with your product data"],
        ["2. Do not modify column headers"],
        ["3. All fields marked with * are REQUIRED"],
        ["4. Barcode and SKU must be unique"],
        ["5. Prices must be positive numbers"],
        ["6. Category must match existing category names (see Categories sheet)"],
        ["7. Set 'is_active' to TRUE or FALSE"],
        ["8. Save the file and upload it through the admin panel"],
        [""],
        ["FIELD DESCRIPTIONS:"],
        [""],
        ["Field", "Required", "Description", "Example"],
        ["name", "YES", "Product name", "Coca Cola 500ml"],
        ["barcode", "YES", "Unique barcode number", "5449000000996"],
        ["sku", "YES", "Unique SKU code", "COKE-500"],
        ["category", "NO", "Category name (must exist)", "Beverages"],
        ["description", "NO", "Product description", "Refreshing cola drink"],
        ["retail_price", "YES", "Selling price to customers", "2500"],
        ["wholesale_price", "YES", "Bulk/wholesale price", "2000"],
        ["cost_price", "YES", "Your cost/purchase price", "1500"],
        ["quantity_in_stock", "YES", "Initial stock quantity", "100"],
        ["reorder_level", "NO", "Low stock alert level (default: 10)", "20"],
        ["is_active", "NO", "Product active status (default: TRUE)", "TRUE"],
    ]

    # Write instructions
    for row_idx, row_data in enumerate(instructions, 1):
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_instructions.cell(row=row_idx, column=col_idx, value=value)

            if row_idx == 1:  # Title
                cell.font = Font(bold=True, size=14, color="4472C4")
            elif row_idx == 3 or row_idx == 10:  # Section headers
                cell.font = Font(bold=True, size=12)
            elif row_idx == 15:  # Table header
                cell.fill = header_fill
                cell.font = header_font
                cell.alignment = Alignment(horizontal="center", vertical="center")

    # Adjust column widths
    ws_instructions.column_dimensions['A'].width = 20
    ws_instructions.column_dimensions['B'].width = 15
    ws_instructions.column_dimensions['C'].width = 50
    ws_instructions.column_dimensions['D'].width = 25

    # Products Sheet
    ws_products = wb.create_sheet("Products")

    # Headers
    headers = [
        "name*", "barcode*", "sku*", "category", "description",
        "retail_price*", "wholesale_price*", "cost_price*",
        "quantity_in_stock*", "reorder_level", "is_active"
    ]

    # Write headers with styling
    for col_idx, header in enumerate(headers, 1):
        cell = ws_products.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Add sample data
    sample_data = [
        [
            "Sample Product 1",
            "1234567890123",
            "SAMPLE-001",
            "Electronics",
            "This is a sample product description",
            "15000",
            "12000",
            "8000",
            "50",
            "10",
            "TRUE"
        ],
        [
            "Sample Product 2",
            "9876543210987",
            "SAMPLE-002",
            "Beverages",
            "Another sample product",
            "3500",
            "3000",
            "2000",
            "100",
            "20",
            "TRUE"
        ]
    ]

    for row_idx, row_data in enumerate(sample_data, 2):
        for col_idx, value in enumerate(row_data, 1):
            cell = ws_products.cell(row=row_idx, column=col_idx, value=value)
            cell.alignment = Alignment(horizontal="left", vertical="center")

    # Adjust column widths
    column_widths = [25, 18, 15, 15, 40, 15, 15, 15, 18, 15, 12]
    for idx, width in enumerate(column_widths, 1):
        ws_products.column_dimensions[get_column_letter(idx)].width = width

    # Add note about sample data
    note_row = len(sample_data) + 3
    ws_products.cell(row=note_row, column=1,
                     value="NOTE: Delete sample data before uploading. Add your products starting from row 2.")
    ws_products.cell(row=note_row, column=1).font = Font(italic=True, color="FF0000")

    # Categories Sheet (Reference)
    ws_categories = wb.create_sheet("Categories")
    ws_categories.cell(row=1, column=1, value="Available Categories")
    ws_categories.cell(row=1, column=1).fill = header_fill
    ws_categories.cell(row=1, column=1).font = header_font

    categories = Category.objects.all().order_by('name')
    for idx, category in enumerate(categories, 2):
        ws_categories.cell(row=idx, column=1, value=category.name)

    ws_categories.column_dimensions['A'].width = 30

    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="product_upload_template_{timezone.now().strftime("%Y%m%d")}.xlsx"'

    wb.save(response)
    return response


@staff_member_required
def upload_products_bulk(request):
    """
    Handle bulk product upload from Excel file
    """
    if request.method == 'POST':
        excel_file = request.FILES.get('excel_file')

        if not excel_file:
            messages.error(request, 'Please select an Excel file to upload.')
            return render(request, 'admin/pos_app/product/upload_bulk.html')

        if not excel_file.name.endswith(('.xlsx', '.xls')):
            messages.error(request, 'Please upload a valid Excel file (.xlsx or .xls)')
            return render(request, 'admin/pos_app/product/upload_bulk.html')

        try:
            # Load workbook
            wb = openpyxl.load_workbook(excel_file)

            # Check if Products sheet exists
            if 'Products' not in wb.sheetnames:
                messages.error(request, 'Excel file must contain a "Products" sheet. Please use the provided template.')
                return render(request, 'admin/pos_app/product/upload_bulk.html')

            ws = wb['Products']

            # Validate headers
            expected_headers = [
                'name*', 'barcode*', 'sku*', 'category', 'description',
                'retail_price*', 'wholesale_price*', 'cost_price*',
                'quantity_in_stock*', 'reorder_level', 'is_active'
            ]

            actual_headers = [cell.value for cell in ws[1]]

            if actual_headers[:11] != expected_headers:
                messages.error(request, 'Excel file headers do not match template. Please download a fresh template.')
                return render(request, 'admin/pos_app/product/upload_bulk.html')

            # Process products
            success_count = 0
            error_count = 0
            errors = []

            with transaction.atomic():
                for row_idx, row in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
                    # Skip empty rows
                    if not any(row):
                        continue

                    try:
                        # Extract data
                        name = str(row[0]).strip() if row[0] else None
                        barcode = str(row[1]).strip() if row[1] else None
                        sku = str(row[2]).strip() if row[2] else None
                        category_name = str(row[3]).strip() if row[3] else None
                        description = str(row[4]).strip() if row[4] else ""
                        retail_price = row[5]
                        wholesale_price = row[6]
                        cost_price = row[7]
                        quantity_in_stock = row[8]
                        reorder_level = row[9] if row[9] else 10
                        is_active_str = str(row[10]).strip().upper() if row[10] else "TRUE"

                        # Validate required fields
                        if not all([name, barcode, sku]):
                            errors.append(f"Row {row_idx}: Missing required fields (name, barcode, or sku)")
                            error_count += 1
                            continue

                        # Check for duplicate barcode
                        if Product.objects.filter(barcode=barcode).exists():
                            errors.append(f"Row {row_idx}: Barcode '{barcode}' already exists")
                            error_count += 1
                            continue

                        # Check for duplicate SKU
                        if Product.objects.filter(sku=sku).exists():
                            errors.append(f"Row {row_idx}: SKU '{sku}' already exists")
                            error_count += 1
                            continue

                        # Get or create category
                        category = None
                        if category_name:
                            category, _ = Category.objects.get_or_create(name=category_name)

                        # Validate and convert prices
                        try:
                            retail_price = Decimal(str(retail_price))
                            wholesale_price = Decimal(str(wholesale_price))
                            cost_price = Decimal(str(cost_price))

                            if retail_price <= 0 or wholesale_price <= 0 or cost_price <= 0:
                                raise ValueError("Prices must be positive")
                        except (ValueError, InvalidOperation, TypeError):
                            errors.append(f"Row {row_idx}: Invalid price values")
                            error_count += 1
                            continue

                        # Validate quantity
                        try:
                            quantity_in_stock = int(quantity_in_stock)
                            reorder_level = int(reorder_level)

                            if quantity_in_stock < 0 or reorder_level < 0:
                                raise ValueError("Quantities must be non-negative")
                        except (ValueError, TypeError):
                            errors.append(f"Row {row_idx}: Invalid quantity values")
                            error_count += 1
                            continue

                        # Parse is_active
                        is_active = is_active_str in ['TRUE', 'YES', '1', 'Y']

                        # Create product
                        product = Product.objects.create(
                            name=name,
                            barcode=barcode,
                            sku=sku,
                            category=category,
                            description=description,
                            retail_price=retail_price,
                            wholesale_price=wholesale_price,
                            cost_price=cost_price,
                            quantity_in_stock=quantity_in_stock,
                            reorder_level=reorder_level,
                            is_active=is_active,
                            created_by=request.user,
                            updated_by=request.user
                        )

                        success_count += 1

                    except Exception as e:
                        errors.append(f"Row {row_idx}: {str(e)}")
                        error_count += 1

            # Show results
            if success_count > 0:
                messages.success(request, f'Successfully imported {success_count} product(s)!')

            if error_count > 0:
                error_message = f'Failed to import {error_count} product(s). Errors:\n'
                error_message += '\n'.join(errors[:20])  # Show first 20 errors
                if len(errors) > 20:
                    error_message += f'\n... and {len(errors) - 20} more errors'
                messages.error(request, error_message)

            if success_count > 0 and error_count == 0:
                return redirect('admin:pos_app_product_changelist')

        except Exception as e:
            messages.error(request, f'Error processing file: {str(e)}')

    return render(request, 'admin/pos_app/product/upload_bulk.html')


@staff_member_required
def export_products_excel(request):
    """
    Export all products to Excel
    """
    # Create workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Products"

    # Styling
    header_fill = PatternFill(start_color="4472C4", end_color="4472C4", fill_type="solid")
    header_font = Font(bold=True, color="FFFFFF", size=11)

    # Headers
    headers = [
        "ID", "Name", "Barcode", "SKU", "Category",
        "Description", "Retail Price", "Wholesale Price", "Cost Price",
        "Quantity in Stock", "Reorder Level", "Active", "Created At", "Updated At"
    ]

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.fill = header_fill
        cell.font = header_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    # Fetch products
    products = Product.objects.select_related('category').all().order_by('name')

    # Write data
    for row_idx, product in enumerate(products, 2):
        ws.cell(row=row_idx, column=1, value=product.id)
        ws.cell(row=row_idx, column=2, value=product.name)
        ws.cell(row=row_idx, column=3, value=product.barcode)
        ws.cell(row=row_idx, column=4, value=product.sku)
        ws.cell(row=row_idx, column=5, value=product.category.name if product.category else "")
        ws.cell(row=row_idx, column=6, value=product.description)
        ws.cell(row=row_idx, column=7, value=float(product.retail_price))
        ws.cell(row=row_idx, column=8, value=float(product.wholesale_price))
        ws.cell(row=row_idx, column=9, value=float(product.cost_price))
        ws.cell(row=row_idx, column=10, value=product.quantity_in_stock)
        ws.cell(row=row_idx, column=11, value=product.reorder_level)
        ws.cell(row=row_idx, column=12, value="Yes" if product.is_active else "No")
        ws.cell(row=row_idx, column=13, value=product.created_at.strftime('%Y-%m-%d %H:%M:%S'))
        ws.cell(row=row_idx, column=14, value=product.updated_at.strftime('%Y-%m-%d %H:%M:%S'))

    # Adjust column widths
    column_widths = [8, 30, 18, 15, 20, 40, 15, 15, 15, 18, 15, 10, 20, 20]
    for idx, width in enumerate(column_widths, 1):
        ws.column_dimensions[get_column_letter(idx)].width = width

    # Prepare response
    response = HttpResponse(
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response[
        'Content-Disposition'] = f'attachment; filename="products_export_{timezone.now().strftime("%Y%m%d_%H%M%S")}.xlsx"'

    wb.save(response)
    return response