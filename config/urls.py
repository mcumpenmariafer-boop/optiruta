from django.contrib import admin
from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularRedocView, SpectacularSwaggerView
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView

from apps.cuentas.views import LoginView, UsuarioViewSet, yo
from apps.logistica import views as log
from apps.reportes import views as rep

router = DefaultRouter()
router.register("usuarios", UsuarioViewSet, basename="usuario")
router.register("zonas", log.ZonaViewSet, basename="zona")
router.register("conductores", log.ConductorViewSet, basename="conductor")
router.register("vehiculos", log.VehiculoViewSet, basename="vehiculo")
router.register("puntos-entrega", log.PuntoEntregaViewSet, basename="punto")
router.register("pedidos", log.PedidoViewSet, basename="pedido")
router.register("rutas", log.RutaViewSet, basename="ruta")
router.register("paradas", log.ParadaViewSet, basename="parada")

admin.site.site_header = "OptiRuta · Administración"
admin.site.site_title = "OptiRuta"

urlpatterns = [
    path("admin/", admin.site.urls),
    # Autenticación JWT
    path("api/auth/login/", LoginView.as_view(), name="login-api"),
    path("api/auth/refresh/", TokenRefreshView.as_view(), name="refresh"),
    path("api/auth/yo/", yo, name="yo"),
    # Reportes
    path("api/reportes/eficiencia/", rep.eficiencia, name="reporte-eficiencia"),
    path("api/reportes/resumen/", rep.resumen, name="reporte-resumen"),
    path("api/reportes/cierre-diario/", rep.cierre_diario, name="reporte-cierre-diario"),
    # Seguimiento público
    path("api/seguimiento/<str:codigo>/", log.seguimiento_publico, name="seguimiento-api"),
    path("api/", include(router.urls)),
    # Documentación (Swagger / ReDoc)
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="swagger"),
    path("api/redoc/", SpectacularRedocView.as_view(url_name="schema"), name="redoc"),
    # Frontend
    path("", include("apps.web.urls")),
]
