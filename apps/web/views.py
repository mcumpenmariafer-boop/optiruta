"""
Vistas web (capa de presentación). Cada página es una plantilla Django + Bootstrap que
consume la API REST con el token JWT guardado en el navegador (static/js/api.js).
La protección por rol se aplica en el navegador (redirección) y, sobre todo, en la API.
"""
from django.conf import settings
from django.views.generic import TemplateView


class Pagina(TemplateView):
    roles = ("ADMIN", "SUPERVISOR", "CONDUCTOR")
    titulo = ""
    seccion = ""

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx.update(
            titulo=self.titulo, seccion=self.seccion, roles_permitidos=",".join(self.roles),
            deposito={"lat": settings.OPTIRUTA["DEPOSITO_LAT"], "lng": settings.OPTIRUTA["DEPOSITO_LNG"],
                      "nombre": settings.OPTIRUTA["DEPOSITO_NOMBRE"]},
        )
        return ctx


GESTION = ("ADMIN", "SUPERVISOR")


class Login(TemplateView):
    template_name = "web/login.html"


class Inicio(Pagina):
    template_name = "web/inicio.html"


class Dashboard(Pagina):
    template_name = "web/dashboard.html"
    roles, titulo, seccion = GESTION, "Mapa del día", "dashboard"


class Planificar(Pagina):
    template_name = "web/planificar.html"
    roles, titulo, seccion = GESTION, "Planificación de rutas", "planificar"


class Pedidos(Pagina):
    template_name = "web/pedidos.html"
    roles, titulo, seccion = GESTION, "Pedidos sin asignar", "pedidos"


class DetalleRuta(Pagina):
    template_name = "web/ruta_detalle.html"
    titulo, seccion = "Detalle de ruta", "historial"


class Historial(Pagina):
    template_name = "web/historial.html"
    roles, titulo, seccion = GESTION, "Historial de rutas", "historial"


class Reportes(Pagina):
    template_name = "web/reportes.html"
    roles, titulo, seccion = GESTION, "Reportes de eficiencia", "reportes"


class Flota(Pagina):
    template_name = "web/flota.html"
    roles, titulo, seccion = GESTION, "Flota y conductores", "flota"


class Conductor(Pagina):
    template_name = "web/conductor.html"
    roles, titulo, seccion = ("CONDUCTOR",), "Mi ruta", "conductor"


class Seguimiento(TemplateView):
    template_name = "web/seguimiento.html"
