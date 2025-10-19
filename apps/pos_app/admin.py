from django.contrib import admin
from django.utils.html import format_html
from django.db.models import Sum, Count
from django.urls import reverse
from django.utils.safestring import mark_safe
from django.http import HttpResponse
import csv
from .models import (
    Category, Product, ProductUpdateLog, Transaction,
    TransactionItem, SyncLog, UserDevice
)


# ==========================================
# Category Admin
# ==========================================

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'product_count', 'active_products', 'total_stock_value', 'created_at', 'updated_at']
    search_fields = ['name', 'description']
    list_filter = ['created_at', 'updated_at']
    ordering = ['name']

    readonly_fields = ['created_at', 'updated_at', 'category_stats']

    fieldsets = (
        ('Category Information', {
            'fields': ('name', 'description')
        }),
        ('Statistics', {
            'fields': ('category_stats',),
            'classes': ('collapse',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )

    def product_count(self, obj):
        """Total products in category"""
        count = obj.products.count()
        url = reverse('admin:pos_product_changelist') + f'?category__id__exact={obj.id}'
        return format_html('<a href="{}">{} products</a>', url, count)

    product_count.short_description = 'Total Products'

    def active_products(self, obj):
        """Active products count"""
        count = obj.products.filter(is_active=True).count()
        return format_html('<span style="color: green; font-weight: bold;">{}</span>', count)

    active_products.short_description = 'Active'

    def total_stock_value(self, obj):
        """Total stock value at retail price"""
        from django.db.models import F
        total = obj.products.filter(is_active=True).aggregate(
            value=Sum(F('quantity_in_stock') * F('retail_price'))
        )['value'] or 0
        return format_html('<span style="color: #2563eb;">UGX {:,.0f}</span>', total)

    total_stock_value.short_description = 'Stock Value'

    def category_stats(self, obj):
        """Display detailed category statistics"""
        if not obj.pk:
            return "Save category to view statistics"

        from django.db.models import F, Avg

        stats = obj.products.filter(is_active=True).aggregate(
            total_products=Count('id'),
            total_stock=Sum('quantity_in_stock'),
            avg_retail=Avg('retail_price'),
            retail_value=Sum(F('quantity_in_stock') * F('retail_price')),
            cost_value=Sum(F('quantity_in_stock') * F('cost_price'))
        )

        low_stock = obj.products.filter(
            is_active=True,
            quantity_in_stock__lte=F('reorder_level')
        ).count()

        html = f"""
        <div style="background: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin-top: 0; color: #1f2937;">Category Overview</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Total Products:</td>
                    <td style="padding: 8px;">{stats['total_products'] or 0}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Total Stock Units:</td>
                    <td style="padding: 8px;">{stats['total_stock'] or 0:,}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Average Retail Price:</td>
                    <td style="padding: 8px;">UGX {stats['avg_retail'] or 0:,.0f}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Stock Value (Retail):</td>
                    <td style="padding: 8px; color: #16a34a; font-weight: 600;">UGX {stats['retail_value'] or 0:,.0f}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Stock Value (Cost):</td>
                    <td style="padding: 8px;">UGX {stats['cost_value'] or 0:,.0f}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: 600;">Low Stock Items:</td>
                    <td style="padding: 8px; color: {'#dc2626' if low_stock > 0 else '#16a34a'}; font-weight: 600;">{low_stock}</td>
                </tr>
            </table>
        </div>
        """
        return mark_safe(html)

    category_stats.short_description = 'Category Statistics'


# ==========================================
# Product Admin
# ==========================================

@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = [
        'name', 'sku', 'barcode', 'category',
        'retail_price_display', 'wholesale_price_display',
        'stock_badge', 'profit_margin', 'is_active_badge', 'updated_at'
    ]
    list_filter = [
        'is_active', 'category', 'created_at', 'updated_at'
    ]
    search_fields = ['name', 'sku', 'barcode', 'description']
    readonly_fields = [
        'created_at', 'updated_at', 'version',
        'created_by', 'updated_by', 'product_analytics'
    ]
    list_per_page = 50
    date_hierarchy = 'created_at'

    actions = [
        'activate_products',
        'deactivate_products',
        'export_to_csv',
        'mark_for_reorder'
    ]

    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'barcode', 'sku', 'category', 'description', 'is_active')
        }),
        ('Pricing', {
            'fields': ('retail_price', 'wholesale_price', 'cost_price'),
            'description': 'Set retail, wholesale, and cost prices'
        }),
        ('Stock Management', {
            'fields': ('quantity_in_stock', 'reorder_level'),
            'description': 'Manage inventory levels'
        }),
        ('Analytics', {
            'fields': ('product_analytics',),
            'classes': ('collapse',)
        }),
        ('Tracking Information', {
            'fields': ('version', 'created_at', 'updated_at', 'created_by', 'updated_by'),
            'classes': ('collapse',)
        }),
    )

    def retail_price_display(self, obj):
        """Format retail price"""
        return format_html('<span style="color: #16a34a; font-weight: 600;">UGX {:,.0f}</span>', obj.retail_price)

    retail_price_display.short_description = 'Retail Price'
    retail_price_display.admin_order_field = 'retail_price'

    def wholesale_price_display(self, obj):
        """Format wholesale price"""
        return format_html('<span style="color: #2563eb; font-weight: 600;">UGX {:,.0f}</span>', obj.wholesale_price)

    wholesale_price_display.short_description = 'Wholesale Price'
    wholesale_price_display.admin_order_field = 'wholesale_price'

    def stock_badge(self, obj):
        """Display stock status with color coding"""
        if obj.quantity_in_stock <= 0:
            color = '#dc2626'  # red
            bg_color = '#fee2e2'
            text = 'OUT OF STOCK'
        elif obj.quantity_in_stock <= obj.reorder_level:
            color = '#d97706'  # orange
            bg_color = '#fed7aa'
            text = f'LOW ({obj.quantity_in_stock})'
        else:
            color = '#16a34a'  # green
            bg_color = '#dcfce7'
            text = str(obj.quantity_in_stock)

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 12px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px; display: inline-block;">{}</span>',
            bg_color, color, text
        )

    stock_badge.short_description = 'Stock'
    stock_badge.admin_order_field = 'quantity_in_stock'

    def profit_margin(self, obj):
        """Calculate and display profit margin"""
        if obj.cost_price > 0:
            margin = ((obj.retail_price - obj.cost_price) / obj.cost_price) * 100
            color = '#16a34a' if margin > 30 else '#d97706' if margin > 15 else '#dc2626'
            return format_html(
                '<span style="color: {}; font-weight: 600;">{:.1f}%</span>',
                color, margin
            )
        return format_html('<span style="color: #6b7280;">N/A</span>')

    profit_margin.short_description = 'Margin'

    def is_active_badge(self, obj):
        """Display active status badge"""
        if obj.is_active:
            return format_html(
                '<span style="color: #16a34a; font-weight: 600;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: #dc2626; font-weight: 600;">✗ Inactive</span>'
        )

    is_active_badge.short_description = 'Status'
    is_active_badge.admin_order_field = 'is_active'

    def product_analytics(self, obj):
        """Display detailed product analytics"""
        if not obj.pk:
            return "Save product to view analytics"

        # Get sales data
        sales_data = obj.transaction_items.aggregate(
            total_sold=Sum('quantity'),
            total_revenue=Sum('line_total'),
            transaction_count=Count('transaction', distinct=True)
        )

        total_sold = sales_data['total_sold'] or 0
        total_revenue = sales_data['total_revenue'] or 0
        transaction_count = sales_data['transaction_count'] or 0

        # Calculate values
        stock_value_retail = obj.quantity_in_stock * obj.retail_price
        stock_value_cost = obj.quantity_in_stock * obj.cost_price
        potential_profit = stock_value_retail - stock_value_cost

        if obj.cost_price > 0:
            retail_margin = ((obj.retail_price - obj.cost_price) / obj.cost_price) * 100
            wholesale_margin = ((obj.wholesale_price - obj.cost_price) / obj.cost_price) * 100
        else:
            retail_margin = 0
            wholesale_margin = 0

        html = f"""
        <div style="background: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin-top: 0; color: #1f2937;">Product Analytics</h3>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px;">
                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">Sales Performance</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Units Sold:</td>
                            <td style="padding: 6px;">{total_sold:,}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Total Revenue:</td>
                            <td style="padding: 6px; color: #16a34a; font-weight: 600;">UGX {total_revenue:,.0f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Transactions:</td>
                            <td style="padding: 6px;">{transaction_count}</td>
                        </tr>
                    </table>
                </div>

                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">Inventory Value</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Current Stock:</td>
                            <td style="padding: 6px;">{obj.quantity_in_stock:,} units</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Value (Retail):</td>
                            <td style="padding: 6px; color: #16a34a;">UGX {stock_value_retail:,.0f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Value (Cost):</td>
                            <td style="padding: 6px;">UGX {stock_value_cost:,.0f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Potential Profit:</td>
                            <td style="padding: 6px; color: #2563eb; font-weight: 600;">UGX {potential_profit:,.0f}</td>
                        </tr>
                    </table>
                </div>

                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">Profit Margins</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Retail Margin:</td>
                            <td style="padding: 6px; color: {'#16a34a' if retail_margin > 30 else '#d97706'}; font-weight: 600;">{retail_margin:.1f}%</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Wholesale Margin:</td>
                            <td style="padding: 6px; color: {'#16a34a' if wholesale_margin > 20 else '#d97706'}; font-weight: 600;">{wholesale_margin:.1f}%</td>
                        </tr>
                    </table>
                </div>

                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">Status</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Reorder Level:</td>
                            <td style="padding: 6px;">{obj.reorder_level}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Needs Reorder:</td>
                            <td style="padding: 6px; color: {'#dc2626' if obj.quantity_in_stock <= obj.reorder_level else '#16a34a'}; font-weight: 600;">
                                {'YES' if obj.quantity_in_stock <= obj.reorder_level else 'NO'}
                            </td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Version:</td>
                            <td style="padding: 6px;">{obj.version}</td>
                        </tr>
                    </table>
                </div>
            </div>
        </div>
        """
        return mark_safe(html)

    product_analytics.short_description = 'Product Analytics'

    # Actions
    def activate_products(self, request, queryset):
        """Activate selected products"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} product(s) activated successfully.')

    activate_products.short_description = 'Activate selected products'

    def deactivate_products(self, request, queryset):
        """Deactivate selected products"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} product(s) deactivated successfully.')

    deactivate_products.short_description = 'Deactivate selected products'

    def export_to_csv(self, request, queryset):
        """Export selected products to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="products_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'ID', 'Name', 'SKU', 'Barcode', 'Category',
            'Retail Price', 'Wholesale Price', 'Cost Price',
            'Stock', 'Reorder Level', 'Active', 'Last Updated'
        ])

        for product in queryset:
            writer.writerow([
                product.id,
                product.name,
                product.sku,
                product.barcode,
                product.category.name if product.category else '',
                product.retail_price,
                product.wholesale_price,
                product.cost_price,
                product.quantity_in_stock,
                product.reorder_level,
                'Yes' if product.is_active else 'No',
                product.updated_at.strftime('%Y-%m-%d %H:%M:%S')
            ])

        return response

    export_to_csv.short_description = 'Export to CSV'

    def mark_for_reorder(self, request, queryset):
        """Show products that need reordering"""
        from django.db.models import F
        low_stock = queryset.filter(quantity_in_stock__lte=F('reorder_level'))
        count = low_stock.count()
        if count > 0:
            self.message_user(request, f'{count} product(s) need reordering.', level='warning')
        else:
            self.message_user(request, 'No products need reordering.')

    mark_for_reorder.short_description = 'Check reorder status'

    def save_model(self, request, obj, form, change):
        """Auto-set user fields"""
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


# ==========================================
# Product Update Log Admin
# ==========================================

@admin.register(ProductUpdateLog)
class ProductUpdateLogAdmin(admin.ModelAdmin):
    list_display = [
        'product_link', 'action_badge', 'change_summary_display',
        'changed_by', 'timestamp'
    ]
    list_filter = ['action', 'timestamp', 'changed_by']
    search_fields = ['product__name', 'product__sku', 'product__barcode']
    readonly_fields = [
        'product', 'action', 'changed_fields', 'old_values',
        'new_values', 'changed_by', 'timestamp', 'detailed_changes'
    ]
    date_hierarchy = 'timestamp'
    list_per_page = 100

    fieldsets = (
        ('Update Information', {
            'fields': ('product', 'action', 'changed_by', 'timestamp')
        }),
        ('Changes', {
            'fields': ('detailed_changes',)
        }),
        ('Raw Data', {
            'fields': ('changed_fields', 'old_values', 'new_values'),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def product_link(self, obj):
        """Link to product"""
        url = reverse('admin:pos_product_change', args=[obj.product.id])
        return format_html('<a href="{}">{}</a>', url, obj.product.name)

    product_link.short_description = 'Product'

    def action_badge(self, obj):
        """Display action with badge"""
        colors = {
            'CREATE': ('#16a34a', '#dcfce7'),
            'UPDATE': ('#2563eb', '#dbeafe'),
            'DELETE': ('#dc2626', '#fee2e2'),
            'STOCK_CHANGE': ('#d97706', '#fed7aa'),
            'PRICE_CHANGE': ('#7c3aed', '#ede9fe'),
        }
        color, bg = colors.get(obj.action, ('#6b7280', '#f3f4f6'))

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 10px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, color, obj.get_action_display()
        )

    action_badge.short_description = 'Action'
    action_badge.admin_order_field = 'action'

    def change_summary_display(self, obj):
        """Display readable change summary"""
        summaries = []

        for field in obj.changed_fields.keys():
            if field in obj.old_values and field in obj.new_values:
                old = obj.old_values[field]
                new = obj.new_values[field]

                if field == 'quantity_in_stock':
                    diff = new - old
                    if diff > 0:
                        summaries.append(f'Stock +{diff}')
                    else:
                        summaries.append(f'Stock {diff}')
                elif 'price' in field:
                    summaries.append(f'{field.replace("_", " ").title()}: {old}→{new}')
                elif field == 'is_active':
                    status = "activated" if new else "deactivated"
                    summaries.append(status.title())

        return ', '.join(summaries) if summaries else 'Created'

    change_summary_display.short_description = 'Summary'

    def detailed_changes(self, obj):
        """Display detailed change information"""
        if obj.action == 'CREATE':
            return mark_safe('<p style="color: #16a34a; font-weight: 600;">Product was created</p>')

        html = '<div style="background: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb;">'
        html += '<h3 style="margin-top: 0; color: #1f2937;">Change Details</h3>'
        html += '<table style="width: 100%; border-collapse: collapse;">'
        html += '<tr style="background: #e5e7eb; font-weight: 600;"><td style="padding: 8px;">Field</td><td style="padding: 8px;">Old Value</td><td style="padding: 8px;">New Value</td></tr>'

        for field in obj.changed_fields.keys():
            if field in obj.old_values and field in obj.new_values:
                field_name = field.replace('_', ' ').title()
                old_val = obj.old_values[field]
                new_val = obj.new_values[field]

                html += f'''
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">{field_name}</td>
                    <td style="padding: 8px; color: #dc2626;">{old_val}</td>
                    <td style="padding: 8px; color: #16a34a;">{new_val}</td>
                </tr>
                '''

        html += '</table></div>'
        return mark_safe(html)

    detailed_changes.short_description = 'Detailed Changes'


# ==========================================
# Transaction Item Inline
# ==========================================

class TransactionItemInline(admin.TabularInline):
    model = TransactionItem
    extra = 0
    readonly_fields = [
        'product', 'product_name', 'product_sku',
        'quantity', 'unit_price', 'line_total', 'price_type'
    ]
    can_delete = False
    fields = [
        'product_name', 'product_sku', 'quantity',
        'unit_price', 'price_type', 'line_total'
    ]

    def has_add_permission(self, request, obj=None):
        return False


# ==========================================
# Transaction Admin
# ==========================================

@admin.register(Transaction)
class TransactionAdmin(admin.ModelAdmin):
    list_display = [
        'transaction_id_short', 'transaction_type_badge', 'total_amount_display',
        'payment_status_badge', 'customer_name', 'created_by',
        'created_at', 'sync_badge'
    ]
    list_filter = [
        'transaction_type', 'payment_status', 'is_synced',
        'created_offline', 'created_at'
    ]
    search_fields = [
        'transaction_id', 'customer_name', 'customer_phone',
        'created_by__username'
    ]
    readonly_fields = [
        'transaction_id', 'created_at', 'created_by', 'subtotal',
        'total_amount', 'is_synced', 'synced_at', 'transaction_details'
    ]
    inlines = [TransactionItemInline]
    date_hierarchy = 'created_at'
    list_per_page = 50

    actions = ['export_transactions']

    fieldsets = (
        ('Transaction Information', {
            'fields': ('transaction_id', 'transaction_type', 'payment_status', 'created_offline')
        }),
        ('Customer Details', {
            'fields': ('customer_name', 'customer_phone')
        }),
        ('Amounts', {
            'fields': ('subtotal', 'discount', 'total_amount', 'amount_paid')
        }),
        ('Details', {
            'fields': ('transaction_details',),
            'classes': ('collapse',)
        }),
        ('Additional Information', {
            'fields': ('notes', 'created_by', 'created_at', 'is_synced', 'synced_at'),
            'classes': ('collapse',)
        }),
    )

    def transaction_id_short(self, obj):
        """Display shortened transaction ID"""
        short_id = str(obj.transaction_id)[:8]
        return format_html(
            '<code style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{}</code>',
            short_id
        )

    transaction_id_short.short_description = 'ID'
    transaction_id_short.admin_order_field = 'transaction_id'

    def transaction_type_badge(self, obj):
        """Display transaction type badge"""
        colors = {
            'RETAIL': ('#2563eb', '#dbeafe'),
            'WHOLESALE': ('#7c3aed', '#ede9fe'),
        }
        color, bg = colors.get(obj.transaction_type, ('#6b7280', '#f3f4f6'))

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 10px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, color, obj.get_transaction_type_display()
        )

    transaction_type_badge.short_description = 'Type'
    transaction_type_badge.admin_order_field = 'transaction_type'

    def total_amount_display(self, obj):
        """Format total amount"""
        return format_html(
            '<span style="color: #16a34a; font-weight: 700; font-size: 14px;">UGX {:,.0f}</span>',
            obj.total_amount
        )

    total_amount_display.short_description = 'Total'
    total_amount_display.admin_order_field = 'total_amount'

    def payment_status_badge(self, obj):
        """Display payment status badge"""
        colors = {
            'PAID': ('#16a34a', '#dcfce7'),
            'UNPAID': ('#dc2626', '#fee2e2'),
            'PARTIAL': ('#d97706', '#fed7aa')
        }
        color, bg = colors.get(obj.payment_status, ('#6b7280', '#f3f4f6'))

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 10px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, color, obj.get_payment_status_display()
        )

    payment_status_badge.short_description = 'Payment'
    payment_status_badge.admin_order_field = 'payment_status'

    def sync_badge(self, obj):
        """Display sync status"""
        if obj.is_synced:
            return format_html(
                '<span style="color: #16a34a; font-weight: 600;">✓ Synced</span>'
            )
        return format_html(
            '<span style="color: #d97706; font-weight: 600;">⏳ Pending</span>'
        )

    sync_badge.short_description = 'Sync Status'
    sync_badge.admin_order_field = 'is_synced'

    def transaction_details(self, obj):
        """Display detailed transaction information"""
        if not obj.pk:
            return "Save transaction to view details"

        items = obj.items.all()
        items_count = items.count()
        balance = obj.total_amount - obj.amount_paid

        html = f"""
        <div style="background: #f9fafb; padding: 20px; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin-top: 0; color: #1f2937;">Transaction Summary</h3>

            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 20px; margin-bottom: 20px;">
                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">General Info</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Transaction ID:</td>
                            <td style="padding: 6px;"><code>{obj.transaction_id}</code></td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Items Count:</td>
                            <td style="padding: 6px;">{items_count}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Created:</td>
                            <td style="padding: 6px;">{obj.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Created Offline:</td>
                            <td style="padding: 6px;">{'Yes' if obj.created_offline else 'No'}</td>
                        </tr>
                    </table>
                </div>

                <div>
                    <h4 style="color: #4b5563; margin-bottom: 10px;">Financial Summary</h4>
                    <table style="width: 100%; border-collapse: collapse;">
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Subtotal:</td>
                            <td style="padding: 6px;">UGX {obj.subtotal:,.0f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Discount:</td>
                            <td style="padding: 6px; color: #dc2626;">- UGX {obj.discount:,.0f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Total:</td>
                            <td style="padding: 6px; color: #16a34a; font-weight: 700;">UGX {obj.total_amount:,.0f}</td>
                        </tr>
                        <tr style="border-bottom: 1px solid #e5e7eb;">
                            <td style="padding: 6px; font-weight: 600;">Amount Paid:</td>
                            <td style="padding: 6px;">UGX {obj.amount_paid:,.0f}</td>
                        </tr>
                        <tr>
                            <td style="padding: 6px; font-weight: 600;">Balance:</td>
                            <td style="padding: 6px; color: {'#dc2626' if balance > 0 else '#16a34a'}; font-weight: 600;">
                                UGX {balance:,.0f}
                            </td>
                        </tr>
                    </table>
                </div>
            </div>

            <h4 style="color: #4b5563; margin-bottom: 10px;">Items</h4>
            <table style="width: 100%; border-collapse: collapse; border: 1px solid #e5e7eb;">
                <thead>
                    <tr style="background: #e5e7eb;">
                        <th style="padding: 8px; text-align: left;">Product</th>
                        <th style="padding: 8px; text-align: left;">SKU</th>
                        <th style="padding: 8px; text-align: right;">Qty</th>
                        <th style="padding: 8px; text-align: right;">Unit Price</th>
                        <th style="padding: 8px; text-align: right;">Total</th>
                    </tr>
                </thead>
                <tbody>
        """

        for item in items:
            html += f"""
                    <tr style="border-bottom: 1px solid #e5e7eb;">
                        <td style="padding: 8px;">{item.product_name}</td>
                        <td style="padding: 8px;"><code>{item.product_sku}</code></td>
                        <td style="padding: 8px; text-align: right;">{item.quantity}</td>
                        <td style="padding: 8px; text-align: right;">UGX {item.unit_price:,.0f}</td>
                        <td style="padding: 8px; text-align: right; font-weight: 600;">UGX {item.line_total:,.0f}</td>
                    </tr>
            """

        html += """
                </tbody>
            </table>
        </div>
        """

        return mark_safe(html)

    transaction_details.short_description = 'Transaction Details'

    def export_transactions(self, request, queryset):
        """Export transactions to CSV"""
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="transactions_export.csv"'

        writer = csv.writer(response)
        writer.writerow([
            'Transaction ID', 'Date', 'Type', 'Payment Status',
            'Customer Name', 'Customer Phone', 'Subtotal', 'Discount',
            'Total', 'Amount Paid', 'Balance', 'Cashier', 'Synced'
        ])

        for transaction in queryset:
            balance = transaction.total_amount - transaction.amount_paid
            writer.writerow([
                str(transaction.transaction_id),
                transaction.created_at.strftime('%Y-%m-%d %H:%M:%S'),
                transaction.get_transaction_type_display(),
                transaction.get_payment_status_display(),
                transaction.customer_name,
                transaction.customer_phone,
                transaction.subtotal,
                transaction.discount,
                transaction.total_amount,
                transaction.amount_paid,
                balance,
                transaction.created_by.username if transaction.created_by else 'N/A',
                'Yes' if transaction.is_synced else 'No'
            ])

        return response

    export_transactions.short_description = 'Export to CSV'

    def has_add_permission(self, request):
        """Transactions should be created via API"""
        return False

    def has_change_permission(self, request, obj=None):
        """Transactions should not be modified"""
        return False

    def has_delete_permission(self, request, obj=None):
        """Only superusers can delete transactions"""
        return request.user.is_superuser


# ==========================================
# Sync Log Admin
# ==========================================

@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = [
        'sync_type_badge', 'status_badge', 'user',
        'items_synced', 'started_at', 'duration_display'
    ]
    list_filter = ['sync_type', 'status', 'started_at']
    search_fields = ['user__username']
    readonly_fields = [
        'user', 'sync_type', 'status', 'items_synced',
        'errors', 'started_at', 'completed_at', 'sync_details'
    ]
    date_hierarchy = 'started_at'
    list_per_page = 100

    fieldsets = (
        ('Sync Information', {
            'fields': ('user', 'sync_type', 'status', 'started_at', 'completed_at')
        }),
        ('Results', {
            'fields': ('items_synced', 'sync_details')
        }),
        ('Errors', {
            'fields': ('errors',),
            'classes': ('collapse',)
        }),
    )

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def sync_type_badge(self, obj):
        """Display sync type with badge"""
        colors = {
            'PRODUCTS_PULL': ('#2563eb', '#dbeafe'),
            'TRANSACTIONS_PUSH': ('#16a34a', '#dcfce7'),
            'FULL_SYNC': ('#7c3aed', '#ede9fe'),
        }
        color, bg = colors.get(obj.sync_type, ('#6b7280', '#f3f4f6'))

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 10px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, color, obj.get_sync_type_display()
        )

    sync_type_badge.short_description = 'Sync Type'
    sync_type_badge.admin_order_field = 'sync_type'

    def status_badge(self, obj):
        """Display status with color coding"""
        colors = {
            'SUCCESS': ('#16a34a', '#dcfce7'),
            'FAILED': ('#dc2626', '#fee2e2'),
            'PARTIAL': ('#d97706', '#fed7aa')
        }
        color, bg = colors.get(obj.status, ('#6b7280', '#f3f4f6'))

        return format_html(
            '<span style="background-color: {}; color: {}; padding: 4px 10px; '
            'border-radius: 12px; font-weight: 600; font-size: 11px;">{}</span>',
            bg, color, obj.status
        )

    status_badge.short_description = 'Status'
    status_badge.admin_order_field = 'status'

    def duration_display(self, obj):
        """Display sync duration"""
        if obj.completed_at:
            delta = obj.completed_at - obj.started_at
            duration = delta.total_seconds()

            if duration < 1:
                return format_html('<span style="color: #16a34a;">{:.2f}s</span>', duration)
            elif duration < 10:
                return format_html('<span style="color: #2563eb;">{:.2f}s</span>', duration)
            else:
                return format_html('<span style="color: #d97706;">{:.2f}s</span>', duration)
        return format_html('<span style="color: #6b7280;">In Progress</span>')

    duration_display.short_description = 'Duration'

    def sync_details(self, obj):
        """Display detailed sync information"""
        if not obj.pk:
            return "Sync log not yet saved"

        failed_count = len(obj.errors) if obj.errors else 0
        total = obj.items_synced + failed_count
        success_rate = (obj.items_synced / total * 100) if total > 0 else 0

        duration = "In Progress"
        if obj.completed_at:
            delta = obj.completed_at - obj.started_at
            duration = f"{delta.total_seconds():.2f} seconds"

        html = f"""
        <div style="background: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin-top: 0; color: #1f2937;">Sync Performance</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Started At:</td>
                    <td style="padding: 8px;">{obj.started_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Completed At:</td>
                    <td style="padding: 8px;">{obj.completed_at.strftime('%Y-%m-%d %H:%M:%S') if obj.completed_at else 'In Progress'}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Duration:</td>
                    <td style="padding: 8px; font-weight: 600;">{duration}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Items Synced:</td>
                    <td style="padding: 8px; color: #16a34a; font-weight: 600;">{obj.items_synced}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Failed:</td>
                    <td style="padding: 8px; color: #dc2626; font-weight: 600;">{failed_count}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: 600;">Success Rate:</td>
                    <td style="padding: 8px; color: {'#16a34a' if success_rate > 90 else '#d97706'}; font-weight: 600;">
                        {success_rate:.1f}%
                    </td>
                </tr>
            </table>
        </div>
        """

        if obj.errors and len(obj.errors) > 0:
            html += """
            <div style="background: #fee2e2; padding: 15px; border-radius: 8px; border: 1px solid #fca5a5; margin-top: 15px;">
                <h4 style="color: #dc2626; margin-top: 0;">Errors</h4>
                <ul style="margin: 0; padding-left: 20px;">
            """
            for error in obj.errors[:10]:  # Show first 10 errors
                html += f"<li style='color: #991b1b; margin-bottom: 5px;'>{error}</li>"

            if len(obj.errors) > 10:
                html += f"<li style='color: #991b1b; font-style: italic;'>...and {len(obj.errors) - 10} more errors</li>"

            html += "</ul></div>"

        return mark_safe(html)

    sync_details.short_description = 'Sync Details'


# ==========================================
# User Device Admin
# ==========================================

@admin.register(UserDevice)
class UserDeviceAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'device_name', 'device_id_short',
        'last_sync_display', 'is_active_badge', 'created_at'
    ]
    list_filter = ['is_active', 'last_sync_at', 'created_at']
    search_fields = ['user__username', 'device_name', 'device_id']
    readonly_fields = [
        'user', 'device_id', 'created_at', 'last_sync_at',
        'last_product_version_synced', 'device_info'
    ]

    actions = ['activate_devices', 'deactivate_devices']

    fieldsets = (
        ('Device Information', {
            'fields': ('user', 'device_id', 'device_name', 'is_active')
        }),
        ('Sync Information', {
            'fields': ('last_sync_at', 'last_product_version_synced', 'device_info')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )

    def device_id_short(self, obj):
        """Display shortened device ID"""
        short_id = obj.device_id[:12] + '...' if len(obj.device_id) > 12 else obj.device_id
        return format_html(
            '<code style="background: #f3f4f6; padding: 2px 6px; border-radius: 4px; font-size: 11px;">{}</code>',
            short_id
        )

    device_id_short.short_description = 'Device ID'

    def last_sync_display(self, obj):
        """Display time since last sync"""
        if not obj.last_sync_at:
            return format_html('<span style="color: #dc2626;">Never synced</span>')

        from django.utils import timezone
        delta = timezone.now() - obj.last_sync_at

        if delta.days > 0:
            time_str = f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
            color = '#dc2626' if delta.days > 7 else '#d97706'
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            time_str = f"{hours} hour{'s' if hours > 1 else ''} ago"
            color = '#2563eb'
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            time_str = f"{minutes} minute{'s' if minutes > 1 else ''} ago"
            color = '#16a34a'
        else:
            time_str = "Just now"
            color = '#16a34a'

        return format_html('<span style="color: {}; font-weight: 600;">{}</span>', color, time_str)

    last_sync_display.short_description = 'Last Sync'
    last_sync_display.admin_order_field = 'last_sync_at'

    def is_active_badge(self, obj):
        """Display active status"""
        if obj.is_active:
            return format_html(
                '<span style="color: #16a34a; font-weight: 600;">✓ Active</span>'
            )
        return format_html(
            '<span style="color: #dc2626; font-weight: 600;">✗ Inactive</span>'
        )

    is_active_badge.short_description = 'Status'
    is_active_badge.admin_order_field = 'is_active'

    def device_info(self, obj):
        """Display detailed device information"""
        if not obj.pk:
            return "Save device to view information"

        from django.utils import timezone

        sync_status = "Never synced"
        sync_color = "#dc2626"

        if obj.last_sync_at:
            delta = timezone.now() - obj.last_sync_at
            if delta.days > 7:
                sync_status = "Outdated (>7 days)"
                sync_color = "#dc2626"
            elif delta.days > 1:
                sync_status = "This week"
                sync_color = "#d97706"
            elif delta.seconds >= 3600:
                sync_status = "Today"
                sync_color = "#2563eb"
            else:
                sync_status = "Recent"
                sync_color = "#16a34a"

        html = f"""
        <div style="background: #f9fafb; padding: 15px; border-radius: 8px; border: 1px solid #e5e7eb;">
            <h3 style="margin-top: 0; color: #1f2937;">Device Information</h3>
            <table style="width: 100%; border-collapse: collapse;">
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Device ID:</td>
                    <td style="padding: 8px;"><code>{obj.device_id}</code></td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Device Name:</td>
                    <td style="padding: 8px;">{obj.device_name}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">User:</td>
                    <td style="padding: 8px;">{obj.user.username}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Registered:</td>
                    <td style="padding: 8px;">{obj.created_at.strftime('%Y-%m-%d %H:%M:%S')}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Last Sync:</td>
                    <td style="padding: 8px;">{obj.last_sync_at.strftime('%Y-%m-%d %H:%M:%S') if obj.last_sync_at else 'Never'}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Sync Status:</td>
                    <td style="padding: 8px; color: {sync_color}; font-weight: 600;">{sync_status}</td>
                </tr>
                <tr style="border-bottom: 1px solid #e5e7eb;">
                    <td style="padding: 8px; font-weight: 600;">Product Version:</td>
                    <td style="padding: 8px;">{obj.last_product_version_synced}</td>
                </tr>
                <tr>
                    <td style="padding: 8px; font-weight: 600;">Active:</td>
                    <td style="padding: 8px; color: {'#16a34a' if obj.is_active else '#dc2626'}; font-weight: 600;">
                        {'Yes' if obj.is_active else 'No'}
                    </td>
                </tr>
            </table>
        </div>
        """

        return mark_safe(html)

    device_info.short_description = 'Device Information'

    def activate_devices(self, request, queryset):
        """Activate selected devices"""
        updated = queryset.update(is_active=True)
        self.message_user(request, f'{updated} device(s) activated successfully.')

    activate_devices.short_description = 'Activate selected devices'

    def deactivate_devices(self, request, queryset):
        """Deactivate selected devices"""
        updated = queryset.update(is_active=False)
        self.message_user(request, f'{updated} device(s) deactivated successfully.')

    deactivate_devices.short_description = 'Deactivate selected devices'


# ==========================================
# Customize Admin Site
# ==========================================

admin.site.site_header = "SureLaces POS Administration"
admin.site.site_title = "SureLaces POS Admin"
admin.site.index_title = "Welcome to SureLaces POS Management"