from django.db import models

# Create your models here.
from django.db import models
from django.utils import timezone
from django.core.validators import MinValueValidator
from decimal import Decimal
import uuid
from dateutil import parser
from django.conf import settings


class Category(models.Model):
    """Product categories for better organization"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Categories"
        ordering = ['name']

    def __str__(self):
        return self.name


class Product(models.Model):
    """Main product model with retail and wholesale pricing"""
    name = models.CharField(max_length=255, db_index=True)
    barcode = models.CharField(max_length=100, unique=True, db_index=True)
    sku = models.CharField(max_length=100, unique=True, db_index=True)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, related_name='products')
    description = models.TextField(blank=True)

    # Pricing
    retail_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)])
    cost_price = models.DecimalField(max_digits=10, decimal_places=2, validators=[MinValueValidator(0)], default=0)

    # Stock management
    quantity_in_stock = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    reorder_level = models.IntegerField(default=10)

    # Status
    is_active = models.BooleanField(default=True, db_index=True)

    # Tracking
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='products_created')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='products_updated')

    # Version tracking for sync
    version = models.IntegerField(default=1)

    class Meta:
        ordering = ['name']
        indexes = [
            models.Index(fields=['updated_at', 'is_active']),
            models.Index(fields=['barcode', 'is_active']),
        ]

    def __str__(self):
        return f"{self.name} ({self.sku})"

    def save(self, *args, **kwargs):
        if self.pk:
            self.version += 1
        super().save(*args, **kwargs)


class ProductUpdateLog(models.Model):
    """Tracks all changes to products for sync notifications"""
    ACTION_CHOICES = [
        ('CREATE', 'Created'),
        ('UPDATE', 'Updated'),
        ('DELETE', 'Deleted'),
        ('STOCK_CHANGE', 'Stock Changed'),
        ('PRICE_CHANGE', 'Price Changed'),
    ]

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name='update_logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    changed_fields = models.JSONField(default=dict)  # Stores what changed
    old_values = models.JSONField(default=dict)
    new_values = models.JSONField(default=dict)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['timestamp', 'action']),
        ]

    def __str__(self):
        return f"{self.product.name} - {self.action} at {self.timestamp}"


class Transaction(models.Model):
    """Main transaction/sale record"""
    TRANSACTION_TYPE_CHOICES = [
        ('RETAIL', 'Retail'),
        ('WHOLESALE', 'Wholesale'),
    ]

    PAYMENT_STATUS_CHOICES = [
        ('PAID', 'Paid'),
        ('UNPAID', 'Unpaid'),
        ('PARTIAL', 'Partially Paid'),
    ]

    # Unique identifier for offline sync
    transaction_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False, db_index=True)

    # Transaction details
    transaction_type = models.CharField(max_length=10, choices=TRANSACTION_TYPE_CHOICES, default='RETAIL')
    payment_status = models.CharField(max_length=10, choices=PAYMENT_STATUS_CHOICES, default='UNPAID')

    # Amounts
    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    amount_paid = models.DecimalField(max_digits=10, decimal_places=2, default=0)

    # Customer info (optional)
    customer_name = models.CharField(max_length=255, blank=True)
    customer_phone = models.CharField(max_length=20, blank=True)

    # User and timestamps
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='transactions')
    created_at = models.DateTimeField(default=timezone.now, db_index=True)

    # Sync tracking
    is_synced = models.BooleanField(default=False, db_index=True)
    synced_at = models.DateTimeField(null=True, blank=True)
    created_offline = models.BooleanField(default=False)

    # Notes
    notes = models.TextField(blank=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at', 'is_synced']),
            models.Index(fields=['transaction_type', 'created_at']),
        ]

    def __str__(self):
        return f"Transaction {self.transaction_id} - {self.total_amount}"


class TransactionItem(models.Model):
    """Individual items in a transaction"""
    transaction = models.ForeignKey(Transaction, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name='transaction_items')

    # Item details at time of sale
    product_name = models.CharField(max_length=255)  # Snapshot
    product_sku = models.CharField(max_length=100)  # Snapshot

    quantity = models.IntegerField(validators=[MinValueValidator(1)])
    unit_price = models.DecimalField(max_digits=10, decimal_places=2)
    line_total = models.DecimalField(max_digits=10, decimal_places=2)

    # Track which price was used
    price_type = models.CharField(max_length=10, choices=[('RETAIL', 'Retail'), ('WHOLESALE', 'Wholesale')])

    class Meta:
        ordering = ['id']

    def __str__(self):
        return f"{self.product_name} x {self.quantity}"

    def save(self, *args, **kwargs):
        self.line_total = self.quantity * self.unit_price
        super().save(*args, **kwargs)


class SyncLog(models.Model):
    """Tracks sync operations for debugging and monitoring"""
    SYNC_TYPE_CHOICES = [
        ('PRODUCTS_PULL', 'Products Pull'),
        ('TRANSACTIONS_PUSH', 'Transactions Push'),
        ('FULL_SYNC', 'Full Sync'),
    ]

    STATUS_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED', 'Failed'),
        ('PARTIAL', 'Partial'),
    ]

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    sync_type = models.CharField(max_length=20, choices=SYNC_TYPE_CHOICES)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES)

    items_synced = models.IntegerField(default=0)
    errors = models.JSONField(default=list)

    started_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-started_at']

    def __str__(self):
        return f"{self.sync_type} - {self.status} at {self.started_at}"


class UserDevice(models.Model):
    """Track devices for better offline sync management"""
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='devices')
    device_id = models.CharField(max_length=255, unique=True)
    device_name = models.CharField(max_length=255)

    last_sync_at = models.DateTimeField(null=True, blank=True)
    last_product_version_synced = models.IntegerField(default=0)

    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-last_sync_at']

    def __str__(self):
        return f"{self.user.username} - {self.device_name}"