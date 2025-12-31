from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin)
from rest_framework_simplejwt.tokens import RefreshToken
import uuid
import re

from apps.pos_app.models import Store, Role


# ============================================
# USER MODELS
# ============================================

class UserManager(BaseUserManager):
    def _generate_username(self, name, email):
        """Generate a unique username"""
        base = re.sub(r'[^a-zA-Z0-9]', '', name.lower().replace(' ', '')) or email.split('@')[0].lower()
        username = base[:50]
        counter = 1
        while self.model.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username

    def create_user(self, name, email, password=None, store=None, role=None):
        if not email:
            raise TypeError('Users should have an email')
        if not name:
            raise TypeError('Users should have a name')

        username = self._generate_username(name, email)

        user = self.model(
            username=username,
            email=self.normalize_email(email),
            name=name,
            store=store,
            role=role
        )
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, name, email, password=None):
        if not password:
            raise TypeError('Password should not be none')

        user = self.create_user(name, email, password)
        user.is_superuser = True
        user.is_staff = True
        user.is_verified = True
        user.save(using=self._db)
        return user


AUTH_PROVIDERS = {
    'facebook': 'facebook',
    'google': 'google',
    'twitter': 'twitter',
    'email': 'email',
    'apple': 'apple'
}


class User(AbstractBaseUser, PermissionsMixin):
    """Extended User model with store and role"""
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    phone = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    # Store and Role relationships
    store = models.ForeignKey(
        Store,
        on_delete=models.CASCADE,
        related_name='users',
        help_text="Store the user belongs to",
        null=True
    )
    role = models.ForeignKey(
        Role,
        on_delete=models.PROTECT,
        related_name='users',
        help_text="User's role in the system",
        null=True
    )

    is_verified = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    auth_provider = models.CharField(
        max_length=255,
        blank=False,
        null=False,
        default=AUTH_PROVIDERS.get('email')
    )

    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['name']

    objects = UserManager()

    def __str__(self):
        return f"{self.email} - {self.store.name} ({self.role.name})"

    def tokens(self):
        refresh = RefreshToken.for_user(self)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token)
        }

    @property
    def is_owner(self):
        return self.role.name == 'owner'

    @property
    def is_salesperson(self):
        return self.role.name == 'salesperson'

    class Meta:
        ordering = ['-created_at']

