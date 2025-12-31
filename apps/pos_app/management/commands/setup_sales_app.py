# management/commands/setup_sales_app.py
from django.core.management.base import BaseCommand
from django.db import transaction

from apps.pos_app.models import Role, Store


class Command(BaseCommand):
    help = 'Initialize stores and roles for sales app'

    def handle(self, *args, **options):
        with transaction.atomic():
            self.stdout.write('Setting up sales app...')

            # Create default roles
            roles_data = [
                {
                    'name': 'salesperson',
                    'display_name': 'Salesperson',
                    'description': 'Creates and manages sales invoices',
                    'permissions': {
                        'can_create_invoice': True,
                        'can_view_own_sales': True,
                        'can_view_products': True,
                    }
                },
                {
                    'name': 'owner',
                    'display_name': 'Store Owner',
                    'description': 'Full access to store management and analytics',
                    'permissions': {
                        'can_create_invoice': True,
                        'can_view_all_sales': True,
                        'can_view_products': True,
                        'can_manage_products': True,
                        'can_manage_users': True,
                        'can_view_analytics': True,
                    }
                },
                {
                    'name': 'manager',
                    'display_name': 'Store Manager',
                    'description': 'Manages products and views analytics',
                    'permissions': {
                        'can_create_invoice': True,
                        'can_view_all_sales': True,
                        'can_view_products': True,
                        'can_manage_products': True,
                        'can_view_analytics': True,
                    }
                }
            ]

            for role_data in roles_data:
                role, created = Role.objects.get_or_create(
                    name=role_data['name'],
                    defaults={
                        'display_name': role_data['display_name'],
                        'description': role_data['description'],
                        'permissions': role_data['permissions']
                    }
                )
                if created:
                    self.stdout.write(self.style.SUCCESS(f'✓ Created role: {role.display_name}'))
                else:
                    self.stdout.write(f'  Role already exists: {role.display_name}')

            # Create a default demo store
            demo_store, created = Store.objects.get_or_create(
                code='DEMO001',
                defaults={
                    'name': 'Demo Store',
                    'address': '123 Main Street, City, Country',
                    'phone': '+1234567890',
                    'email': 'demo@store.com',
                    'tax_rate': 0.1000,
                    'currency': 'USD',
                    'is_active': True
                }
            )

            if created:
                self.stdout.write(self.style.SUCCESS(f'✓ Created demo store: {demo_store.name}'))
                self.stdout.write(f'  Store ID: {demo_store.id}')
                self.stdout.write(f'  Store Code: {demo_store.code}')
            else:
                self.stdout.write(f'  Demo store already exists')

            self.stdout.write(self.style.SUCCESS('\n✅ Sales app setup complete!'))
            self.stdout.write('\nNext steps:')
            self.stdout.write('1. Users can register using the store_id and role_id')
            self.stdout.write('2. Create additional stores via admin or API')
            self.stdout.write('3. Start using the sales app!\n')