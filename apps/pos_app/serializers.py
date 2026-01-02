# serializers.py - Complete Serializers
from django.utils import timezone
from rest_framework import serializers
from django.contrib import auth
from rest_framework.exceptions import AuthenticationFailed, ValidationError
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode
from django.core.cache import cache
from decimal import Decimal
from .models import (
    Store, Role, Category, Product,
    Invoice, InvoiceItem, SyncLog, DailySales
)
from ..authentication.models import User


# ============================================
# STORE SERIALIZERS
# ============================================

class StoreSerializer(serializers.ModelSerializer):
    user_count = serializers.SerializerMethodField()
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Store
        fields = [
            'id', 'name', 'code', 'address', 'phone', 'email',
            'tax_rate', 'currency', 'is_active',
            'user_count', 'product_count', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_user_count(self, obj):
        return obj.users.filter(is_active=True).count()

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()


class StoreListSerializer(serializers.ModelSerializer):
    """Minimal store info for listings"""

    class Meta:
        model = Store
        fields = ['id', 'name', 'code']


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = ['id', 'name', 'display_name', 'description', 'permissions']
        read_only_fields = ['id']


# ============================================
# USER/AUTH SERIALIZERS
# ============================================

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(max_length=68, min_length=6, write_only=True)
    user_id = serializers.UUIDField(source='id', read_only=True)
    username = serializers.CharField(read_only=True)
    store_id = serializers.UUIDField(write_only=True, required=True)
    role_id = serializers.UUIDField(write_only=True, required=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model = User
        fields = [
            'email', 'name', 'password', 'phone',
            'store_id', 'role_id', 'user_id', 'username',
            'store_name', 'role_name'
        ]
        read_only_fields = ['user_id', 'username', 'store_name', 'role_name']

    def validate(self, attrs):
        email = attrs.get('email', '').lower()
        name = attrs.get('name', '')
        store_id = attrs.get('store_id')
        role_id = attrs.get('role_id')

        if not name:
            raise serializers.ValidationError({'name': 'Name is required'})
        if not email:
            raise serializers.ValidationError({'email': 'Email is required'})

        # Validate store exists and is active
        try:
            store = Store.objects.get(id=store_id, is_active=True)
            attrs['store'] = store
        except Store.DoesNotExist:
            raise serializers.ValidationError({'store_id': 'Invalid or inactive store'})

        # Validate role exists
        try:
            role = Role.objects.get(id=role_id)
            attrs['role'] = role
        except Role.DoesNotExist:
            raise serializers.ValidationError({'role_id': 'Invalid role'})

        return attrs

    def create(self, validated_data):
        # Remove store_id and role_id from validated_data (already have store and role objects)
        validated_data.pop('store_id', None)
        validated_data.pop('role_id', None)

        return User.objects.create_user(
            name=validated_data['name'],
            email=validated_data['email'],
            password=validated_data['password'],
            store=validated_data['store'],
            role=validated_data['role']
        )


class LoginSerializer(serializers.ModelSerializer):
    email = serializers.EmailField(max_length=255, min_length=3)
    password = serializers.CharField(max_length=68, min_length=6, write_only=True)
    username = serializers.CharField(read_only=True)
    user_id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    store_id = serializers.UUIDField(read_only=True)
    store_name = serializers.CharField(read_only=True)
    role = serializers.CharField(read_only=True)
    tokens = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            'email', 'name', 'password', 'username', 'user_id',
            'store_id', 'store_name', 'role', 'tokens'
        ]
        read_only_fields = ['name', 'username', 'user_id', 'store_id', 'store_name', 'role', 'tokens']

    def get_tokens(self, obj):
        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError("User not found in context")
        return user.tokens()

    def validate(self, attrs):
        email = attrs.get('email', '').lower()
        password = attrs.get('password', '')

        # Check auth provider
        filtered_user_by_email = User.objects.filter(email=email)
        if filtered_user_by_email.exists() and filtered_user_by_email[0].auth_provider != 'email':
            raise AuthenticationFailed(
                f"Please continue your login using {filtered_user_by_email[0].auth_provider}"
            )

        # Authenticate
        user = auth.authenticate(email=email, password=password)
        if not user:
            raise AuthenticationFailed('Invalid credentials, try again')
        if not user.is_active:
            raise AuthenticationFailed('Account disabled, contact admin')
        if not user.is_verified:
            raise AuthenticationFailed('Email is not verified')
        if not user.store.is_active:
            raise AuthenticationFailed('Store is inactive, contact admin')

        # Store user in context
        self.context['user'] = user
        return attrs

    def to_representation(self, instance):
        user = self.context.get('user')
        if not user:
            raise serializers.ValidationError("User not found in context")

        return {
            'email': user.email,
            'name': user.name,
            'username': user.username,
            'user_id': str(user.id),
            'store_id': str(user.store.id),
            'store_name': user.store.name,
            'role': user.role.name,
            'tokens': self.get_tokens(user)
        }


class UserProfileSerializer(serializers.ModelSerializer):
    user_id = serializers.UUIDField(source='id', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)
    store_id = serializers.UUIDField(source='store.id', read_only=True)
    role_name = serializers.CharField(source='role.name', read_only=True)

    class Meta:
        model = User
        fields = [
            'user_id', 'username', 'name', 'email', 'phone', 'bio',
            'store_id', 'store_name', 'role_name',
            'is_verified', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'user_id', 'email', 'username', 'is_verified',
            'store_id', 'store_name', 'role_name',
            'created_at', 'updated_at'
        ]


# ============================================
# PRODUCT SERIALIZERS
# ============================================

class CategorySerializer(serializers.ModelSerializer):
    product_count = serializers.SerializerMethodField()

    class Meta:
        model = Category
        fields = [
            'id', 'name', 'description', 'parent',
            'product_count', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

    def get_product_count(self, obj):
        return obj.products.filter(is_active=True).count()

    def validate(self, attrs):
        # Automatically set store from request user
        request = self.context.get('request')
        if request and request.user:
            attrs['store'] = request.user.store
        return attrs


class ProductSerializer(serializers.ModelSerializer):
    category_name = serializers.CharField(source='category.name', read_only=True)
    is_low_stock = serializers.BooleanField(read_only=True)

    class Meta:
        model = Product
        fields = [
            'id', 'name', 'code', 'description', 'category', 'category_name',
            'price', 'cost', 'stock', 'low_stock_threshold', 'is_low_stock',
            'barcode', 'image_url', 'is_active',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'is_low_stock', 'created_at', 'updated_at']

    def validate(self, attrs):
        request = self.context.get('request')
        if request and request.user:
            attrs['store'] = request.user.store
            attrs['created_by'] = request.user

        # Validate category belongs to same store
        category = attrs.get('category')
        if category and category.store != attrs['store']:
            raise ValidationError({'category': 'Category must belong to your store'})

        return attrs

    def validate_price(self, value):
        if value <= 0:
            raise ValidationError("Price must be greater than 0")
        return value


class ProductListSerializer(serializers.ModelSerializer):
    """Minimal product info for listings"""

    class Meta:
        model = Product
        fields = ['id', 'name', 'code', 'price', 'stock', 'is_active']


# ============================================
# INVOICE SERIALIZERS
# ============================================
class InvoiceItemSerializer(serializers.ModelSerializer):
    """Full invoice item serializer with all fields"""
    class Meta:
        model = InvoiceItem
        fields = [
            'id', 'product', 'product_name', 'product_code',
            'quantity', 'price', 'total', 'created_at'
        ]
        read_only_fields = ['id', 'total', 'created_at']

    def validate(self, attrs):
        product = attrs.get('product')
        quantity = attrs.get('quantity')

        # Store product details at time of sale
        if product:
            attrs['product_name'] = product.name
            attrs['product_code'] = product.code
            attrs['price'] = attrs.get('price', product.price)

        # Validate stock
        if product and quantity:
            if product.stock < quantity:
                raise ValidationError({
                    'quantity': f'Insufficient stock. Available: {product.stock}'
                })

        return attrs


class InvoiceSerializer(serializers.ModelSerializer):
    """Full invoice serializer with nested items"""
    items = InvoiceItemSerializer(many=True, read_only=False)
    salesperson_name = serializers.CharField(source='salesperson.name', read_only=True)
    store_name = serializers.CharField(source='store.name', read_only=True)

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'salesperson', 'salesperson_name',
            'store_name', 'items', 'subtotal', 'tax', 'discount', 'total',
            'customer_name', 'customer_phone', 'customer_email', 'notes',
            'sync_status', 'synced_at', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'id', 'salesperson_name', 'store_name',
            'subtotal', 'tax', 'total', 'synced_at',
            'created_at', 'updated_at'
        ]

    def validate(self, attrs):
        request = self.context.get('request')
        if request and request.user:
            attrs['store'] = request.user.store
            attrs['salesperson'] = request.user

        # Generate invoice number if not provided
        if not attrs.get('invoice_number'):
            import time
            attrs['invoice_number'] = f"INV-{int(time.time())}"

        return attrs

    def create(self, validated_data):
        items_data = validated_data.pop('items')

        # Create invoice
        invoice = Invoice.objects.create(**validated_data)

        # Create items and update stock
        for item_data in items_data:
            product = item_data['product']
            quantity = item_data['quantity']

            # Create invoice item
            InvoiceItem.objects.create(invoice=invoice, **item_data)

            # Update product stock
            product.stock -= quantity
            product.save()

        # Calculate totals
        invoice.calculate_totals()
        invoice.save()

        return invoice


class InvoiceListSerializer(serializers.ModelSerializer):
    """Invoice list serializer - NOW WITH ITEMS!"""
    salesperson_name = serializers.CharField(source='salesperson.name', read_only=True)
    items = InvoiceItemSerializer(many=True, read_only=True)  # Add this!
    item_count = serializers.SerializerMethodField()

    class Meta:
        model = Invoice
        fields = [
            'id', 'invoice_number', 'salesperson', 'salesperson_name',
            'items',  # Add this!
            'subtotal', 'tax', 'discount', 'total',
            'item_count', 'sync_status', 'created_at'
        ]

    def get_item_count(self, obj):
        return obj.items.count()

class BulkInvoiceItemSerializer(serializers.Serializer):
    """Serializer for invoice items in bulk sync - accepts UUIDs"""
    product = serializers.UUIDField()
    product_name = serializers.CharField(max_length=255)
    product_code = serializers.CharField(max_length=100)
    quantity = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=10, decimal_places=2, min_value=0.01)
    total = serializers.DecimalField(max_digits=12, decimal_places=2, required=False)

    def validate_product(self, value):
        """Validate that product exists and belongs to user's store"""
        request = self.context.get('request')
        try:
            product = Product.objects.get(id=value, store=request.user.store, is_active=True)
            return product
        except Product.DoesNotExist:
            raise ValidationError(f'"{value}" is not a valid UUID.')

    def validate(self, attrs):
        # Calculate total if not provided
        if 'total' not in attrs or attrs['total'] is None:
            attrs['total'] = attrs['quantity'] * attrs['price']
        return attrs


class BulkInvoiceSerializer(serializers.Serializer):
    """Serializer for individual invoice in bulk sync - accepts UUIDs"""
    id = serializers.CharField(required=False)  # Local ID, optional
    createdAt = serializers.DateTimeField(required=False)
    invoice_number = serializers.CharField(max_length=100)
    salesperson = serializers.UUIDField()
    salespersonName = serializers.CharField(required=False)  # Optional, for display
    subtotal = serializers.DecimalField(max_digits=12, decimal_places=2)
    tax = serializers.DecimalField(max_digits=12, decimal_places=2)
    discount = serializers.DecimalField(max_digits=12, decimal_places=2, default=Decimal('0.00'))
    total = serializers.DecimalField(max_digits=12, decimal_places=2)
    customer_name = serializers.CharField(max_length=255, required=False, allow_blank=True)
    customer_phone = serializers.CharField(max_length=50, required=False, allow_blank=True)
    customer_email = serializers.EmailField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)
    syncStatus = serializers.CharField(required=False)  # Expected to be 'PENDING'
    items = BulkInvoiceItemSerializer(many=True)

    def validate_salesperson(self, value):
        """Validate that salesperson exists and belongs to same store"""
        request = self.context.get('request')
        try:
            user = User.objects.get(id=value, store=request.user.store, is_active=True)
            return user
        except User.DoesNotExist:
            raise ValidationError(f'"{value}" is not a valid UUID.')

    def validate_invoice_number(self, value):
        """Check if invoice number already exists"""
        request = self.context.get('request')
        if Invoice.objects.filter(invoice_number=value, store=request.user.store).exists():
            raise ValidationError(f'Invoice with number "{value}" already exists.')
        return value

    def validate(self, attrs):
        """Additional validation"""
        # Validate items
        if not attrs.get('items'):
            raise ValidationError({'items': 'At least one item is required.'})

        # Validate stock for all items
        for item_data in attrs['items']:
            product = item_data['product']
            quantity = item_data['quantity']

            if product.stock < quantity:
                raise ValidationError({
                    'items': f'Insufficient stock for {product.code}. Available: {product.stock}, Requested: {quantity}'
                })

        return attrs


class BulkInvoiceSyncSerializer(serializers.Serializer):
    """For syncing multiple invoices from offline mode"""
    invoices = BulkInvoiceSerializer(many=True)

    def create(self, validated_data):
        invoices_data = validated_data.get('invoices', [])
        synced_invoices = []
        failed_invoices = []

        request = self.context.get('request')
        store = request.user.store

        for invoice_data in invoices_data:
            try:
                # Extract items data
                items_data = invoice_data.pop('items')

                # Remove fields not in Invoice model
                invoice_data.pop('id', None)  # Remove local ID
                invoice_data.pop('createdAt', None)
                invoice_data.pop('salespersonName', None)
                invoice_data.pop('syncStatus', None)

                # Create invoice
                invoice = Invoice.objects.create(
                    store=store,
                    sync_status='SYNCED',
                    synced_at=timezone.now(),
                    **invoice_data
                )

                # Create invoice items and update stock
                for item_data in items_data:
                    product = item_data['product']
                    quantity = item_data['quantity']

                    # Create invoice item
                    InvoiceItem.objects.create(
                        invoice=invoice,
                        product=product,
                        product_name=item_data['product_name'],
                        product_code=item_data['product_code'],
                        quantity=quantity,
                        price=item_data['price'],
                        total=item_data['total']
                    )

                    # Update product stock
                    product.stock -= quantity
                    product.save()

                synced_invoices.append(invoice)

            except ValidationError as e:
                failed_invoices.append({
                    'invoice_number': invoice_data.get('invoice_number', 'Unknown'),
                    'errors': e.detail if hasattr(e, 'detail') else str(e)
                })
            except Exception as e:
                failed_invoices.append({
                    'invoice_number': invoice_data.get('invoice_number', 'Unknown'),
                    'errors': {'error': str(e)}
                })

        return {
            'synced': len(synced_invoices),
            'failed': len(failed_invoices),
            'failed_invoices': failed_invoices
        }

# ============================================
# ANALYTICS SERIALIZERS
# ============================================

class DashboardStatsSerializer(serializers.Serializer):
    today_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    invoice_count = serializers.IntegerField()
    top_product = serializers.CharField()
    active_salespeople = serializers.IntegerField()
    week_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    month_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    low_stock_products = serializers.IntegerField()


class SalesReportSerializer(serializers.Serializer):
    salesperson_id = serializers.UUIDField()
    salesperson_name = serializers.CharField()
    total_sales = serializers.DecimalField(max_digits=12, decimal_places=2)
    invoice_count = serializers.IntegerField()
    average_sale = serializers.DecimalField(max_digits=12, decimal_places=2)


class ProductReportSerializer(serializers.Serializer):
    product_id = serializers.UUIDField()
    product_name = serializers.CharField()
    product_code = serializers.CharField()
    quantity_sold = serializers.IntegerField()
    total_revenue = serializers.DecimalField(max_digits=12, decimal_places=2)


class SyncLogSerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(source='user.name', read_only=True)

    class Meta:
        model = SyncLog
        fields = [
            'id', 'user_name', 'sync_type', 'status',
            'items_synced', 'items_failed', 'error_message',
            'started_at', 'completed_at'
        ]
        read_only_fields = ['id', 'user_name', 'started_at', 'completed_at']