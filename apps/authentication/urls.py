# urls.py - Complete URL Configuration
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from .views import (
    # Auth views (use your existing ones)
    RegisterView, LoginAPIView, LogoutAPIView,
    RequestPasswordResetEmail, VerifyResetCodeAPIView, SetNewPasswordAPIView,
    VerifyEmailAPIView, ResendVerificationCodeAPIView,

)

app_name = 'sales'

urlpatterns = [
    # ============================================
    # AUTHENTICATION ENDPOINTS
    # ============================================
    path('auth/register/', RegisterView.as_view(), name='register'),
    path('auth/login/', LoginAPIView.as_view(), name='login'),
    path('auth/logout/', LogoutAPIView.as_view(), name='logout'),
    path('auth/token/refresh/', TokenRefreshView.as_view(), name='token_refresh'),

    # Email verification
    path('auth/verify-email/', VerifyEmailAPIView.as_view(), name='verify-email'),
    path('auth/resend-verification-code/', ResendVerificationCodeAPIView.as_view(), name='resend-verification-code'),

    # Password reset
    path('auth/request-reset-email/', RequestPasswordResetEmail.as_view(), name='request-reset-email'),
    path('auth/verify-reset-code/', VerifyResetCodeAPIView.as_view(), name='verify-reset-code'),
    path('auth/password-reset-complete/', SetNewPasswordAPIView.as_view(), name='password-reset-complete'),

]