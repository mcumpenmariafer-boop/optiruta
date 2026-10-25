from django.urls import path

from . import views as v

urlpatterns = [
    path("", v.Inicio.as_view(), name="inicio"),
    path("login/", v.Login.as_view(), name="login"),
    path("seguimiento/", v.Seguimiento.as_view(), name="seguimiento"),
    path("app/dashboard/", v.Dashboard.as_view(), name="dashboard"),
    path("app/planificar/", v.Planificar.as_view(), name="planificar"),
    path("app/pedidos/", v.Pedidos.as_view(), name="pedidos"),
    path("app/historial/", v.Historial.as_view(), name="historial"),
    path("app/rutas/<int:pk>/", v.DetalleRuta.as_view(), name="ruta-detalle"),
    path("app/reportes/", v.Reportes.as_view(), name="reportes"),
    path("app/flota/", v.Flota.as_view(), name="flota"),
    path("app/conductor/", v.Conductor.as_view(), name="conductor"),
]
