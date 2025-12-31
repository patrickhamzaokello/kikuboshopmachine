from django.core.cache import cache
from rest_framework import serializers
from .models import User
from django.contrib import auth
from rest_framework.exceptions import AuthenticationFailed
from rest_framework_simplejwt.tokens import RefreshToken, TokenError
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_str
from django.utils.http import urlsafe_base64_decode

from ..pos_app.models import Store, Role


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



class EmailVerificationSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    class Meta:
        fields = ['email', 'code']

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Code must contain only digits")
        if len(value) != 6:
            raise serializers.ValidationError("Code must be exactly 6 digits")
        return value

    def validate_email(self, value):
        return value.lower()


class ResendVerificationCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()

    class Meta:
        fields = ['email']

    def validate_email(self, value):
        return value.lower()





class ResetPasswordEmailRequestSerializer(serializers.Serializer):
    email = serializers.EmailField(min_length=2)

    class Meta:
        fields = ['email']

    def validate_email(self, value):
        return value.lower()


class VerifyResetCodeSerializer(serializers.Serializer):
    email = serializers.EmailField()
    code = serializers.CharField(min_length=6, max_length=6)

    class Meta:
        fields = ['email', 'code']

    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Code must contain only digits")
        if len(value) != 6:
            raise serializers.ValidationError("Code must be exactly 6 digits")
        return value

    def validate_email(self, value):
        return value.lower()


class SetNewPasswordSerializer(serializers.Serializer):
    password = serializers.CharField(min_length=6, max_length=68, write_only=True)
    token = serializers.CharField(min_length=1, write_only=True)
    uidb64 = serializers.CharField(min_length=1, write_only=True)

    class Meta:
        fields = ['password', 'token', 'uidb64']

    def validate_password(self, value):
        if len(value) < 6:
            raise serializers.ValidationError("Password must be at least 6 characters long")
        return value

    def validate(self, attrs):
        try:
            password = attrs.get('password')
            token = attrs.get('token')
            uidb64 = attrs.get('uidb64')

            # Decode user ID
            id = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=id)

            # Verify token
            if not default_token_generator.check_token(user, token):
                raise AuthenticationFailed('The reset token is invalid or expired', 401)

            # Check reset session
            reset_session_key = f"reset_session_{user.pk}"
            session_data = cache.get(reset_session_key)

            if not session_data or not session_data.get('verified'):
                raise AuthenticationFailed('Reset session expired. Please verify your code again.', 401)

            # Set new password
            user.set_password(password)
            user.save()

            return attrs

        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise AuthenticationFailed('The reset link is invalid', 401)
        except Exception as e:
            raise AuthenticationFailed('Password reset failed', 401)


class LogoutSerializer(serializers.Serializer):
    refresh = serializers.CharField()

    def validate(self, value):
        try:
            token = RefreshToken(value)
            token.blacklist()
            return value
        except TokenError:
            raise serializers.ValidationError("Token is expired or invalid")

    def save(self, **kwargs):
        pass

