from django.conf.urls.static import static
from django.contrib import admin
from django.urls import path, include
from rest_framework import permissions
from drf_yasg.views import get_schema_view
from drf_yasg import openapi
from django.http import JsonResponse
from django.db import connection

from kikuboposmachine import settings

schema_view = get_schema_view(
    openapi.Info(
        title="KIKUBO POS MACHINE",
        default_version='v1',
        description="Test description",
        terms_of_service="https://kikubo.mwonya.com/terms/",
        contact=openapi.Contact(email="contact@mwonya.com"),
        license=openapi.License(name="Test License"),
    ),
    public=True,
    permission_classes=[permissions.AllowAny, ],
    authentication_classes=[]
)


def health_check(request):
    try:
        # Check database connection
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return JsonResponse({"status": "healthy"}, status=200)
    except Exception as e:
        return JsonResponse({"status": "unhealthy", "error": str(e)}, status=500)


urlpatterns = [
    path('admin/', admin.site.urls),
    # local apps
    path('auth/', include('apps.authentication.urls')),
    path('social_auth/', include(('apps.social_auth.urls', 'social_auth'), namespace="social_auth")),


    path('pos/', include('apps.pos_app.urls')),

    # Swagger endpoints
    path('', schema_view.with_ui('swagger', cache_timeout=0), name='schema-swagger-ui'),
    path('api/api.json/', schema_view.without_ui(cache_timeout=0), name='schema-json'),
    path('redoc/', schema_view.with_ui('redoc', cache_timeout=0), name='schema-redoc'),

]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
