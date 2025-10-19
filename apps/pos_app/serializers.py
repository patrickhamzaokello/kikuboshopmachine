from rest_framework import serializers
from django.contrib.auth.models import User
from decimal import Decimal
from .models import (
    Category, Product, ProductUpdateLog, Transaction,
    TransactionItem, SyncLog, UserDevice
)


# ==========================================
# Category Serializer
# ==========================================

class CategorySerializer(serializers.ModelSerializer):
    """
    Serializer for product categories
    Includes product count for better UI display
    """
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = ['id', 'name', 'description', 'product_count', 'created_at', 'updated_at']
        read_only_fields = ['created_at', 'updated_at']

    def get_product_count(self, obj):
        """Get count of active products in this category"""
        return obj.products.filter(is_active=True).count()

    def validate_name(self, value):
        """Ensure category name is unique (case-insensitive)"""
        if self.instance:
            # Exclude current instance when updating
            if Category.objects.exclude(pk=self.instance.pk).filter(name__iexact=value).exists():
                raise serializers.ValidationError("A category with this name already exists.")
        else:
            if Category.objects.filter(name__iexact=value).exists():
                raise serializers.ValidationError("A category with this name already exists.")
        return value.strip()


# ==========================================
# Product Serializers
# ==========================================

class ProductListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for product lists
    Optimized for mobile app display and offline sync
    """
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    stock_status = serializers.SerializerMethodField()
    price_difference = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'barcode', 'sku',
            'category', 'category_name',
            'retail_price', 'wholesale_price',
            'quantity_in_stock', 'stock_status',
            'price_difference', 'is_active',
            'updated_at', 'version'
        ]

    def get_stock_status(self, obj):
        """Return stock status: out_of_stock, low, available"""
        if obj.quantity_in_stock <= 0:
            return 'out_of_stock'
        elif obj.quantity_in_stock <= obj.reorder_level:
            return 'low'
        return 'available'

    def get_price_difference(self, obj):
        """Calculate price difference between retail and wholesale"""
        return float(obj.retail_price - obj.wholesale_price)


class ProductDetailSerializer(serializers.ModelSerializer):
    """
    Detailed serializer for product CRUD operations
    Includes all fields and relationships
    """
    category_name = serializers.CharField(source='category.name', read_only=True, allow_null=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    updated_by_username = serializers.CharField(source='updated_by.username', read_only=True, allow_null=True)

    # Computed fields
    stock_status = serializers.SerializerMethodField()
    needs_reorder = serializers.SerializerMethodField()
    profit_margin_retail = serializers.SerializerMethodField()
    profit_margin_wholesale = serializers.SerializerMethodField()
    stock_value_retail = serializers.SerializerMethodField()
    stock_value_cost = serializers.SerializerMethodField()

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'barcode', 'sku',
            'category', 'category_name', 'description',
            'retail_price', 'wholesale_price', 'cost_price',
            'profit_margin_retail', 'profit_margin_wholesale',
            'quantity_in_stock', 'stock_status', 'needs_reorder',
            'reorder_level', 'stock_value_retail', 'stock_value_cost',
            'is_active', 'created_at', 'updated_at',
            'created_by', 'created_by_username',
            'updated_by', 'updated_by_username', 'version'
        ]
        read_only_fields = [
            'created_at', 'updated_at', 'version',
            'created_by', 'updated_by'
        ]

    def get_stock_status(self, obj):
        """Return detailed stock status"""
        if obj.quantity_in_stock <= 0:
            return 'out_of_stock'
        elif obj.quantity_in_stock <= obj.reorder_level:
            return 'low'
        return 'available'

    def get_needs_reorder(self, obj):
        """Check if product needs reordering"""
        return obj.quantity_in_stock <= obj.reorder_level

    def get_profit_margin_retail(self, obj):
        """Calculate profit margin for retail price"""
        if obj.cost_price > 0:
            margin = ((obj.retail_price - obj.cost_price) / obj.cost_price) * 100
            return round(float(margin), 2)
        return 0.0

    def get_profit_margin_wholesale(self, obj):
        """Calculate profit margin for wholesale price"""
        if obj.cost_price > 0:
            margin = ((obj.wholesale_price - obj.cost_price) / obj.cost_price) * 100
            return round(float(margin), 2)
        return 0.0

    def get_stock_value_retail(self, obj):
        """Calculate total stock value at retail price"""
        return float(obj.quantity_in_stock * obj.retail_price)

    def get_stock_value_cost(self, obj):
        """Calculate total stock value at cost price"""
        return float(obj.quantity_in_stock * obj.cost_price)

    def validate_barcode(self, value):
        """Ensure barcode is unique"""
        value = value.strip()
        if self.instance:
            if Product.objects.exclude(pk=self.instance.pk).filter(barcode=value).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        else:
            if Product.objects.filter(barcode=value).exists():
                raise serializers.ValidationError("A product with this barcode already exists.")
        return value

    def validate_sku(self, value):
        """Ensure SKU is unique"""
        value = value.strip()
        if self.instance:
            if Product.objects.exclude(pk=self.instance.pk).filter(sku=value).exists():
                raise serializers.ValidationError("A product with this SKU already exists.")
        else:
            if Product.objects.filter(sku=value).exists():
                raise serializers.ValidationError("A product with this SKU already exists.")
        return value

    def validate(self, data):
        """Validate pricing relationships"""
        retail_price = data.get('retail_price', getattr(self.instance, 'retail_price', None))
        wholesale_price = data.get('wholesale_price', getattr(self.instance, 'wholesale_price', None))
        cost_price = data.get('cost_price', getattr(self.instance, 'cost_price', None))

        if retail_price and wholesale_price:
            if retail_price < wholesale_price:
                raise serializers.ValidationError({
                    'retail_price': 'Retail price must be greater than or equal to wholesale price.'
                })

        if cost_price and wholesale_price:
            if wholesale_price < cost_price:
                raise serializers.ValidationError({
                    'wholesale_price': 'Wholesale price should not be less than cost price.'
                })

        quantity = data.get('quantity_in_stock', getattr(self.instance, 'quantity_in_stock', 0))
        if quantity < 0:
            raise serializers.ValidationError({
                'quantity_in_stock': 'Quantity cannot be negative.'
            })

        return data

    def create(self, validated_data):
        """Set created_by and updated_by on creation"""
        validated_data['created_by'] = self.context['request'].user
        validated_data['updated_by'] = self.context['request'].user
        return super().create(validated_data)

    def update(self, instance, validated_data):
        """Set updated_by on update"""
        validated_data['updated_by'] = self.context['request'].user
        return super().update(instance, validated_data)


# ==========================================
# Product Update Log Serializer
# ==========================================

class ProductUpdateLogSerializer(serializers.ModelSerializer):
    """
    Serializer for product update tracking
    Shows what changed and when
    """
    product_name = serializers.CharField(source='product.name', read_only=True)
    product_sku = serializers.CharField(source='product.sku', read_only=True)
    changed_by_username = serializers.CharField(source='changed_by.username', read_only=True, allow_null=True)
    action_display = serializers.CharField(source='get_action_display', read_only=True)

    # Human-readable change summary
    change_summary = serializers.SerializerMethodField()

    class Meta:
        model = ProductUpdateLog
        fields = [
            'id', 'product', 'product_name', 'product_sku',
            'action', 'action_display', 'change_summary',
            'changed_fields', 'old_values', 'new_values',
            'changed_by', 'changed_by_username', 'timestamp'
        ]

    def get_change_summary(self, obj):
        """Generate human-readable summary of changes"""
        if obj.action == 'CREATE':
            return f"Product '{obj.product.name}' was created"

        if not obj.changed_fields:
            return "No changes"

        summaries = []

        for field in obj.changed_fields.keys():
            if field in obj.old_values and field in obj.new_values:
                old = obj.old_values[field]
                new = obj.new_values[field]

                # Format field name nicely
                field_display = field.replace('_', ' ').title()

                if field == 'quantity_in_stock':
                    diff = new - old
                    if diff > 0:
                        summaries.append(f"Stock increased by {diff} (from {old} to {new})")
                    else:
                        summaries.append(f"Stock decreased by {abs(diff)} (from {old} to {new})")
                elif 'price' in field:
                    summaries.append(f"{field_display} changed from ${old} to ${new}")
                elif field == 'is_active':
                    status = "activated" if new else "deactivated"
                    summaries.append(f"Product {status}")
                else:
                    summaries.append(f"{field_display} changed from '{old}' to '{new}'")

        return '; '.join(summaries) if summaries else "Multiple fields updated"


# ==========================================
# Transaction Item Serializer
# ==========================================

class TransactionItemSerializer(serializers.ModelSerializer):
    """
    Serializer for individual transaction items
    """
    product_detail = serializers.SerializerMethodField()

    class Meta:
        model = TransactionItem
        fields = [
            'id', 'product', 'product_name', 'product_sku',
            'quantity', 'unit_price', 'line_total',
            'price_type', 'product_detail'
        ]
        read_only_fields = ['line_total', 'product_name', 'product_sku']

    def get_product_detail(self, obj):
        """Get minimal product details for display"""
        return {
            'id': obj.product.id,
            'name': obj.product.name,
            'current_stock': obj.product.quantity_in_stock
        }

    def validate(self, data):
        """Validate transaction item"""
        product = data.get('product')
        quantity = data.get('quantity', 0)

        if not product:
            raise serializers.ValidationError("Product is required")

        if quantity <= 0:
            raise serializers.ValidationError("Quantity must be greater than zero")

        # Check stock availability
        if product.quantity_in_stock < quantity:
            raise serializers.ValidationError(
                f"Insufficient stock for {product.name}. "
                f"Available: {product.quantity_in_stock}, Requested: {quantity}"
            )

        # Auto-set product details
        data['product_name'] = product.name
        data['product_sku'] = product.sku

        # Set price based on price_type
        price_type = data.get('price_type', 'RETAIL')
        if price_type == 'WHOLESALE':
            data['unit_price'] = product.wholesale_price
        else:
            data['unit_price'] = product.retail_price

        return data


# ==========================================
# Transaction Serializers
# ==========================================

class TransactionListSerializer(serializers.ModelSerializer):
    """
    Lightweight serializer for transaction lists
    Optimized for listing many transactions
    """
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    items_count = serializers.SerializerMethodField()
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'transaction_type', 'transaction_type_display',
            'payment_status', 'payment_status_display', 'total_amount', 'balance',
            'customer_name', 'customer_phone', 'created_by_username',
            'created_at', 'is_synced', 'items_count', 'created_offline'
        ]

    def get_items_count(self, obj):
        """Get count of items in transaction"""
        return obj.items.count()

    def get_balance(self, obj):
        """Calculate outstanding balance"""
        return float(obj.total_amount - obj.amount_paid)


class TransactionSerializer(serializers.ModelSerializer):
    """
    Full transaction serializer with nested items
    Used for creating and viewing transaction details
    """
    items = TransactionItemSerializer(many=True)
    created_by_username = serializers.CharField(source='created_by.username', read_only=True, allow_null=True)
    transaction_type_display = serializers.CharField(source='get_transaction_type_display', read_only=True)
    payment_status_display = serializers.CharField(source='get_payment_status_display', read_only=True)
    balance = serializers.SerializerMethodField()

    class Meta:
        model = Transaction
        fields = [
            'id', 'transaction_id', 'transaction_type', 'transaction_type_display',
            'payment_status', 'payment_status_display',
            'subtotal', 'discount', 'total_amount', 'amount_paid', 'balance',
            'customer_name', 'customer_phone', 'notes',
            'created_by', 'created_by_username', 'created_at',
            'is_synced', 'synced_at', 'created_offline', 'items'
        ]
        read_only_fields = [
            'transaction_id', 'created_by', 'created_at',
            'is_synced', 'synced_at', 'subtotal', 'total_amount'
        ]

    def get_balance(self, obj):
        """Calculate outstanding balance"""
        return float(obj.total_amount - obj.amount_paid)

    def validate(self, data):
        """Validate transaction data"""
        items = data.get('items', [])

        if not items:
            raise serializers.ValidationError({
                'items': "Transaction must have at least one item"
            })

        # Validate discount
        discount = data.get('discount', Decimal('0.00'))
        if discount < 0:
            raise serializers.ValidationError({
                'discount': "Discount cannot be negative"
            })

        # Calculate expected subtotal
        expected_subtotal = sum(
            item_data['quantity'] * item_data.get('unit_price', Decimal('0.00'))
            for item_data in items
        )

        if discount > expected_subtotal:
            raise serializers.ValidationError({
                'discount': "Discount cannot exceed subtotal"
            })

        # Validate amount paid
        amount_paid = data.get('amount_paid', Decimal('0.00'))
        if amount_paid < 0:
            raise serializers.ValidationError({
                'amount_paid': "Amount paid cannot be negative"
            })

        return data

    def create(self, validated_data):
        """Create transaction with items"""
        items_data = validated_data.pop('items')
        validated_data['created_by'] = self.context['request'].user

        # Calculate totals
        subtotal = Decimal('0.00')
        for item_data in items_data:
            subtotal += item_data['quantity'] * item_data.get('unit_price', Decimal('0.00'))

        validated_data['subtotal'] = subtotal
        validated_data['total_amount'] = subtotal - validated_data.get('discount', Decimal('0.00'))

        # Create transaction
        transaction = Transaction.objects.create(**validated_data)

        # Create transaction items and update stock
        for item_data in items_data:
            product = item_data['product']
            quantity = item_data['quantity']

            # Create transaction item
            TransactionItem.objects.create(transaction=transaction, **item_data)

            # Update product stock
            product.quantity_in_stock -= quantity
            product.updated_by = self.context['request'].user
            product.save()

        return transaction

    def update(self, instance, validated_data):
        """
        Transactions should not be updated after creation
        This is for data integrity
        """
        raise serializers.ValidationError("Transactions cannot be modified after creation")


# ==========================================
# Sync Log Serializer
# ==========================================

class SyncLogSerializer(serializers.ModelSerializer):
    """
    Serializer for sync operation logs
    """
    user_username = serializers.CharField(source='user.username', read_only=True, allow_null=True)
    sync_type_display = serializers.CharField(source='get_sync_type_display', read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    duration = serializers.SerializerMethodField()
    success_rate = serializers.SerializerMethodField()

    class Meta:
        model = SyncLog
        fields = [
            'id', 'user', 'user_username', 'sync_type', 'sync_type_display',
            'status', 'status_display', 'items_synced', 'errors',
            'started_at', 'completed_at', 'duration', 'success_rate'
        ]

    def get_duration(self, obj):
        """Calculate sync duration in seconds"""
        if obj.completed_at:
            delta = obj.completed_at - obj.started_at
            return round(delta.total_seconds(), 2)
        return None

    def get_success_rate(self, obj):
        """Calculate success rate percentage"""
        if obj.items_synced > 0:
            failed_count = len(obj.errors) if obj.errors else 0
            total = obj.items_synced + failed_count
            if total > 0:
                return round((obj.items_synced / total) * 100, 2)
        return 0.0


# ==========================================
# User Device Serializer
# ==========================================

class UserDeviceSerializer(serializers.ModelSerializer):
    """
    Serializer for user devices (for offline sync tracking)
    """
    user_username = serializers.CharField(source='user.username', read_only=True)
    time_since_last_sync = serializers.SerializerMethodField()
    sync_status = serializers.SerializerMethodField()

    class Meta:
        model = UserDevice
        fields = [
            'id', 'user', 'user_username', 'device_id', 'device_name',
            'last_sync_at', 'time_since_last_sync', 'sync_status',
            'last_product_version_synced', 'is_active', 'created_at'
        ]
        read_only_fields = ['user', 'last_sync_at', 'last_product_version_synced', 'created_at']

    def get_time_since_last_sync(self, obj):
        """Get human-readable time since last sync"""
        if not obj.last_sync_at:
            return "Never synced"

        from django.utils import timezone
        delta = timezone.now() - obj.last_sync_at

        if delta.days > 0:
            return f"{delta.days} day{'s' if delta.days > 1 else ''} ago"
        elif delta.seconds >= 3600:
            hours = delta.seconds // 3600
            return f"{hours} hour{'s' if hours > 1 else ''} ago"
        elif delta.seconds >= 60:
            minutes = delta.seconds // 60
            return f"{minutes} minute{'s' if minutes > 1 else ''} ago"
        else:
            return "Just now"

    def get_sync_status(self, obj):
        """Determine sync status based on last sync time"""
        if not obj.last_sync_at:
            return 'never_synced'

        from django.utils import timezone
        import datetime

        delta = timezone.now() - obj.last_sync_at

        if delta < datetime.timedelta(hours=1):
            return 'recent'
        elif delta < datetime.timedelta(days=1):
            return 'today'
        elif delta < datetime.timedelta(days=7):
            return 'this_week'
        else:
            return 'outdated'

    def validate_device_id(self, value):
        """Ensure device_id is unique per user"""
        user = self.context['request'].user
        value = value.strip()

        if self.instance:
            if UserDevice.objects.exclude(pk=self.instance.pk).filter(user=user, device_id=value).exists():
                raise serializers.ValidationError("This device is already registered for your account.")
        else:
            if UserDevice.objects.filter(user=user, device_id=value).exists():
                raise serializers.ValidationError("This device is already registered for your account.")

        return value


# ==========================================
# Product Sync Request Serializer
# ==========================================

class ProductSyncSerializer(serializers.Serializer):
    """
    Serializer for product sync requests from offline clients
    """
    device_id = serializers.CharField(required=True, max_length=255)
    last_sync_timestamp = serializers.DateTimeField(required=False, allow_null=True)
    last_version_synced = serializers.IntegerField(required=False, default=0, min_value=0)

    def validate_device_id(self, value):
        """Validate and clean device_id"""
        return value.strip()

    def validate_last_version_synced(self, value):
        """Ensure version number is valid"""
        if value < 0:
            raise serializers.ValidationError("Version number cannot be negative")
        return value


# ==========================================
# Product Bulk Search Serializer
# ==========================================

class ProductBulkSearchSerializer(serializers.Serializer):
    """
    Serializer for bulk product search (barcode scanning, quick search)
    """
    query = serializers.CharField(
        required=True,
        max_length=255,
        help_text="Search query (barcode, SKU, or product name)"
    )
    search_fields = serializers.ListField(
        child=serializers.ChoiceField(choices=['name', 'barcode', 'sku', 'description']),
        required=False,
        default=['name', 'barcode', 'sku'],
        help_text="Fields to search in"
    )
    is_active_only = serializers.BooleanField(
        default=True,
        help_text="Only return active products"
    )
    limit = serializers.IntegerField(
        required=False,
        default=10,
        min_value=1,
        max_value=50,
        help_text="Maximum number of results to return"
    )

    def validate_query(self, value):
        """Clean and validate search query"""
        value = value.strip()
        if len(value) < 1:
            raise serializers.ValidationError("Search query must be at least 1 character long")
        return value

    def validate_search_fields(self, value):
        """Ensure at least one search field is specified"""
        if not value:
            raise serializers.ValidationError("At least one search field must be specified")
        return value