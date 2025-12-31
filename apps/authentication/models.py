from django.db import models
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin)
from rest_framework_simplejwt.tokens import RefreshToken
import uuid
import re


class UserManager(BaseUserManager):

    def _generate_username(self, name, email):
        """
        Generate a unique username based on the user's name or email.
        """
        # Clean the name to remove special characters and spaces
        base = re.sub(r'[^a-zA-Z0-9]', '', name.lower().replace(' ', '')) or email.split('@')[0].lower()
        username = base[:50]  # Limit length
        # Ensure uniqueness by appending a number if necessary
        counter = 1
        while self.model.objects.filter(username=username).exists():
            username = f"{base}{counter}"
            counter += 1
        return username

    def create_user(self, name, email, password=None, role='salesperson', store_name=None):
        if not email:
            raise TypeError('Users should have an email')
        if not name:
            raise TypeError('Users should have a name')

        # Generate a unique username
        username = self._generate_username(name, email)

        user = self.model(
            username=username,
            email=self.normalize_email(email),
            name=name,
            role=role,
            store_name=store_name or 'Default Store'
        )
        if password:
            user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, name, email, password=None):
        if not password:
            raise TypeError('Password should not be none')

        user = self.create_user(name, email, password, role='owner')
        user.is_superuser = True
        user.is_staff = True
        user.save(using=self._db)
        return user


AUTH_PROVIDERS = {
    'facebook': 'facebook',
    'google': 'google',
    'twitter': 'twitter',
    'email': 'email',
    'apple': 'apple'
}

USER_ROLES = (
    ('salesperson', 'Salesperson'),
    ('owner', 'Store Owner'),
)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    username = models.CharField(max_length=255, unique=True, db_index=True)
    name = models.CharField(max_length=255)
    email = models.EmailField(max_length=255, unique=True, db_index=True)
    phone = models.CharField(max_length=255, blank=True, null=True)
    bio = models.TextField(blank=True, null=True)

    # New fields for sales app
    role = models.CharField(
        max_length=20,
        choices=USER_ROLES,
        default='salesperson',
        help_text='User role in the sales system'
    )
    store_name = models.CharField(
        max_length=255,
        default='Default Store',
        help_text='Name of the store the user belongs to'
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
        return f"{self.email} ({self.role})"

    def tokens(self):
        refresh = RefreshToken.for_user(self)
        return {
            'refresh': str(refresh),
            'access': str(refresh.access_token)
        }

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'User'
        verbose_name_plural = 'Users'