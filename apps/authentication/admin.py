from django.contrib import admin

# Register your models here.
from .models import User


from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = ['email', 'name', 'username', 'store', 'role', 'is_verified', 'is_active', 'created_at']
    list_filter = ['role', 'store', 'is_verified', 'is_active', 'created_at']
    search_fields = ['email', 'name', 'username']
    ordering = ['-created_at']

    fieldsets = (
        ('Authentication', {
            'fields': ('email', 'password')
        }),
        ('Personal Info', {
            'fields': ('name', 'username', 'phone', 'bio')
        }),
        ('Store & Role', {
            'fields': ('store', 'role'),
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'is_verified', 'groups', 'user_permissions'),
        }),
        ('Important Dates', {
            'fields': ('last_login', 'created_at', 'updated_at')
        }),
        ('Authentication Provider', {
            'fields': ('auth_provider',)
        }),
    )

    add_fieldsets = (
        ('Required Information', {
            'classes': ('wide',),
            'fields': ('email', 'name', 'password1', 'password2'),
        }),
        ('Store & Role', {
            'classes': ('wide',),
            'fields': ('store', 'role'),
        }),
        ('Permissions', {
            'classes': ('wide',),
            'fields': ('is_active', 'is_staff', 'is_superuser'),
        }),
    )

    readonly_fields = ['id', 'created_at', 'updated_at', 'last_login', 'username']


