# Create this file: apps/authentication/management/commands/fix_user_data.py
#
# Directory structure:
# apps/authentication/management/commands/fix_user_data.py
# apps/authentication/management/__init__.py (empty file)
# apps/authentication/management/commands/__init__.py (empty file)

from django.core.management.base import BaseCommand
from django.db import transaction
from apps.authentication.models import User
from apps.pos_app.models import Role, Store
from decimal import Decimal


class Command(BaseCommand):
    help = 'Fix users with missing store or role assignments'

    def add_arguments(self, parser):
        parser.add_argument(
            '--assign',
            action='store_true',
            help='Automatically assign default store/role to users',
        )
        parser.add_argument(
            '--delete',
            action='store_true',
            help='Delete users without store/role (DANGEROUS!)',
        )

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('\n=== User Data Integrity Check ===\n'))

        # Find problematic users
        users_without_role = User.objects.filter(
            role__isnull=True,
            is_superuser=False,
            is_staff=False
        )

        users_without_store = User.objects.filter(
            store__isnull=True,
            is_superuser=False,
            is_staff=False
        )

        # Report issues
        self.stdout.write(f'\nFound {users_without_role.count()} users without role:')
        for user in users_without_role:
            self.stdout.write(f'  - {user.email} (ID: {user.id})')

        self.stdout.write(f'\nFound {users_without_store.count()} users without store:')
        for user in users_without_store:
            self.stdout.write(f'  - {user.email} (ID: {user.id})')

        # Check for users with inactive stores
        users_with_inactive_store = User.objects.filter(
            store__is_active=False
        ).exclude(is_superuser=True).exclude(is_staff=True)

        if users_with_inactive_store.exists():
            self.stdout.write(
                self.style.WARNING(
                    f'\nFound {users_with_inactive_store.count()} users with inactive stores:'
                )
            )
            for user in users_with_inactive_store:
                self.stdout.write(f'  - {user.email} @ {user.store.name}')

        # Take action based on options
        if options['delete']:
            self.delete_problematic_users(users_without_role, users_without_store)
        elif options['assign']:
            self.assign_defaults(users_without_role, users_without_store)
        else:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  No action taken. Use --assign or --delete flag to fix issues.'
                )
            )
            self.stdout.write('\nOptions:')
            self.stdout.write('  --assign : Assign default store/role to users')
            self.stdout.write('  --delete : Delete users without store/role (CAREFUL!)')

    @transaction.atomic
    def assign_defaults(self, users_without_role, users_without_store):
        """Assign default store and role to users."""
        self.stdout.write(self.style.WARNING('\n=== Assigning Defaults ===\n'))

        # Get or create default role (salesperson)
        default_role, created = Role.objects.get_or_create(
            name='salesperson',
            defaults={
                'display_name': 'Salesperson',
                'description': 'Default salesperson role',
                'permissions': {'can_create_invoice': True}
            }
        )

        if created:
            self.stdout.write(
                self.style.SUCCESS(f'✓ Created default role: {default_role.display_name}')
            )

        # Get or create default store
        default_store = Store.objects.filter(is_active=True).first()

        if not default_store:
            default_store = Store.objects.create(
                name='Default Store',
                code='DEFAULT001',
                address='Default Address',
                tax_rate=Decimal('0.18'),
                currency='UGX',
                is_active=True
            )
            self.stdout.write(
                self.style.SUCCESS(f'✓ Created default store: {default_store.name}')
            )

        # Update users without role
        role_count = 0
        for user in users_without_role:
            user.role = default_role
            user.save(skip_validation=True)
            role_count += 1
            self.stdout.write(f'  ✓ Assigned role to {user.email}')

        # Update users without store
        store_count = 0
        for user in users_without_store:
            user.store = default_store
            user.save(skip_validation=True)
            store_count += 1
            self.stdout.write(f'  ✓ Assigned store to {user.email}')

        self.stdout.write(
            self.style.SUCCESS(
                f'\n✓ Fixed {role_count} users without role and {store_count} users without store'
            )
        )

    @transaction.atomic
    def delete_problematic_users(self, users_without_role, users_without_store):
        """Delete users without store/role."""
        self.stdout.write(
            self.style.ERROR('\n⚠️  WARNING: This will DELETE users! ⚠️\n')
        )

        # Combine querysets
        users_to_delete = (users_without_role | users_without_store).distinct()

        count = users_to_delete.count()

        if count == 0:
            self.stdout.write(self.style.SUCCESS('No users to delete.'))
            return

        # Confirm deletion
        self.stdout.write(f'\nAbout to delete {count} user(s):')
        for user in users_to_delete:
            self.stdout.write(f'  - {user.email}')

        confirm = input('\nType "DELETE" to confirm: ')

        if confirm == 'DELETE':
            deleted_count, _ = users_to_delete.delete()
            self.stdout.write(
                self.style.SUCCESS(f'\n✓ Deleted {deleted_count} user(s)')
            )
        else:
            self.stdout.write(self.style.WARNING('Deletion cancelled.'))