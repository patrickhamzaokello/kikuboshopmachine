# permissions.py - Custom Permissions
from rest_framework import permissions


class IsOwner(permissions.BasePermission):
    """
    Permission to check if user is store owner
    """

    def has_permission(self, request, view):
        return request.user.is_authenticated and request.user.role.name == 'owner'


class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Owners can do anything, others can only read
    """

    def has_permission(self, request, view):
        if request.method in permissions.SAFE_METHODS:
            return request.user.is_authenticated
        return request.user.is_authenticated and request.user.role.name == 'owner'


class IsSameStore(permissions.BasePermission):
    """
    Check if the object belongs to user's store
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Check if object has store attribute
        if hasattr(obj, 'store'):
            return obj.store == request.user.store

        return False


class IsOwnInvoice(permissions.BasePermission):
    """
    Salespeople can only access their own invoices
    Owners can access all invoices in their store
    """

    def has_object_permission(self, request, view, obj):
        if not request.user.is_authenticated:
            return False

        # Owners can access all store invoices
        if request.user.role.name == 'owner':
            return obj.store == request.user.store

        # Salespeople can only access their own
        return obj.salesperson == request.user