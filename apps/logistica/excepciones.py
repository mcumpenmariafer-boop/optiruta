"""Errores de negocio con mensaje descriptivo y código HTTP adecuado."""
from django.db import IntegrityError
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler


class ReglaNegocioError(Exception):
    """Se lanza cuando una operación viola una regla de negocio crítica."""

    def __init__(self, mensaje, codigo="regla_negocio", http=status.HTTP_400_BAD_REQUEST, detalle=None):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.codigo = codigo
        self.http = http
        self.detalle = detalle or {}


# Qué regla de negocio protege cada código de error
REGLA_POR_CODIGO = {
    "vehiculo_con_ruta_activa": "RN1",
    "capacidad_excedida": "RN2",
    "paradas_pendientes": "RN4",
    "orden_no_respetado": "RN6", "otra_en_camino": "RN6",
    "observacion_requerida": "RN7",
    "no_es_tu_ruta": "RN8", "no_es_tu_vehiculo": "RN8",
    "demasiadas_paradas": "RN9",
    "transicion_invalida": "RN10", "ruta_no_en_curso": "RN10", "estado_invalido": "RN10",
}


def registrar_intento(exc, request):
    """Guarda el intento rechazado (se consulta en Administración → Intentos bloqueados)."""
    regla = REGLA_POR_CODIGO.get(exc.codigo)
    if not regla:
        return
    try:
        from .models import IntentoBloqueado
        usuario = getattr(request, "user", None)
        IntentoBloqueado.objects.create(
            regla=regla, codigo=exc.codigo, mensaje=exc.mensaje[:300],
            usuario=usuario if usuario and usuario.is_authenticated else None,
            endpoint=f"{request.method} {request.path}"[:200] if request else "",
        )
    except Exception:  # la auditoría nunca debe romper la respuesta
        pass


def manejador_errores(exc, context):
    """Formato uniforme de errores: {"error": "...", "codigo": "...", "detalle": {...}}."""
    if isinstance(exc, ReglaNegocioError):
        registrar_intento(exc, context.get("request"))
        return Response(
            {"error": exc.mensaje, "codigo": exc.codigo, "detalle": exc.detalle}, status=exc.http
        )
    if isinstance(exc, IntegrityError):
        return Response(
            {"error": "La operación viola una restricción de la base de datos.", "codigo": "integridad"},
            status=status.HTTP_409_CONFLICT,
        )
    respuesta = exception_handler(exc, context)
    if respuesta is not None and isinstance(respuesta.data, dict) and "error" not in respuesta.data:
        detalle = respuesta.data
        mensaje = detalle.get("detail") if isinstance(detalle.get("detail"), str) else "Datos inválidos."
        respuesta.data = {"error": str(mensaje), "codigo": "validacion", "detalle": detalle}
    return respuesta
