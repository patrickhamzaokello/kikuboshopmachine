# admin.py - Django Admin Configuration
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from .models import (
    Store, Role, Category, Product,
    Invoice, InvoiceItem, SyncLog, DailySales
)


@admin.register(Store)
class StoreAdmin(admin.ModelAdmin):
    list_display = ['name', 'code', 'tax_rate', 'currency', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'code', 'email']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ['name', 'display_name', 'created_at']
    search_fields = ['name', 'display_name']
    readonly_fields = ['id', 'created_at', 'updated_at']




@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'store', 'parent', 'is_active', 'created_at']
    list_filter = ['store', 'is_active', 'created_at']
    search_fields = ['name', 'description']
    readonly_fields = ['id', 'created_at', 'updated_at']


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ['code', 'name', 'store', 'category', 'price', 'stock', 'is_low_stock_badge', 'is_active',
                    'created_at']
    list_filter = ['store', 'category', 'is_active', 'created_at']
    search_fields = ['name', 'code', 'barcode']
    readonly_fields = ['id', 'is_low_stock', 'created_at', 'updated_at']

    def is_low_stock_badge(self, obj):
        if obj.is_low_stock:
            return format_html('<span style="color: red;">⚠️ Low Stock</span>')
        return format_html('<span style="color: green;">✓ OK</span>')

    is_low_stock_badge.short_description = 'Stock Status'


class InvoiceItemInline(admin.TabularInline):
    model = InvoiceItem
    extra = 0
    readonly_fields = ['total']


@admin.register(Invoice)
class InvoiceAdmin(admin.ModelAdmin):
    list_display = ['invoice_number', 'store', 'salesperson', 'total', 'sync_status_badge', 'created_at']
    list_filter = ['store', 'sync_status', 'created_at']
    search_fields = ['invoice_number', 'customer_name', 'customer_phone']
    readonly_fields = ['id', 'subtotal', 'tax', 'total', 'synced_at', 'created_at', 'updated_at']
    inlines = [InvoiceItemInline]

    def sync_status_badge(self, obj):
        colors = {
            'PENDING': 'orange',
            'SYNCED': 'green',
            'FAILED': 'red'
        }
        return format_html(
            '<span style="color: {};">●</span> {}',
            colors.get(obj.sync_status, 'gray'),
            obj.get_sync_status_display()
        )

    sync_status_badge.short_description = 'Sync Status'


@admin.register(InvoiceItem)
class InvoiceItemAdmin(admin.ModelAdmin):
    list_display = ['invoice', 'product_code', 'product_name', 'quantity', 'price', 'total', 'created_at']
    list_filter = ['created_at']
    search_fields = ['product_name', 'product_code', 'invoice__invoice_number']
    readonly_fields = ['id', 'total', 'created_at']


@admin.register(SyncLog)
class SyncLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'store', 'sync_type', 'status', 'items_synced', 'items_failed', 'started_at',
                    'completed_at']
    list_filter = ['sync_type', 'status', 'started_at']
    search_fields = ['user__name', 'user__email']
    readonly_fields = ['id', 'started_at', 'completed_at']


@admin.register(DailySales)
class DailySalesAdmin(admin.ModelAdmin):
    list_display = ['store', 'date', 'total_sales', 'invoice_count', 'items_sold']
    list_filter = ['store', 'date']
    search_fields = ['store__name']
    readonly_fields = ['id', 'created_at', 'updated_at']
    date_hierarchy = 'date'