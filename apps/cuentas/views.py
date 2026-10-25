from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle
from rest_framework_simplejwt.views import TokenObtainPairView

from .models import Usuario
from .permisos import EsAdmin
from .serializers import LoginSerializer, UsuarioSerializer


class LoginThrottle(AnonRateThrottle):
    scope = "login"


class LoginView(TokenObtainPairView):
    """POST /api/auth/login/ — devuelve access, refresh y datos del usuario."""

    serializer_class = LoginSerializer
    throttle_classes = [LoginThrottle]


@extend_schema(responses=UsuarioSerializer)
@api_view(["GET"])
@permission_classes([IsAuthenticated])
def yo(request):
    """GET /api/auth/yo/ — datos del usuario autenticado."""
    datos = UsuarioSerializer(request.user).data
    if request.user.es_admin:
        datos["rol"] = "ADMIN"
    return Response(datos)


class UsuarioViewSet(viewsets.ModelViewSet):
    """CRUD de usuarios (solo administrador)."""

    queryset = Usuario.objects.all().order_by("username")
    serializer_class = UsuarioSerializer
    permission_classes = [EsAdmin]
    filterset_fields = ["rol", "is_active"]
    search_fields = ["username", "first_name", "last_name", "email"]
