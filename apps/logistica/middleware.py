"""Middleware personalizado (Tema 8.3): registra el tiempo de respuesta de la API."""
import logging
import time

log = logging.getLogger("optiruta")


class TiempoRespuestaMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        inicio = time.perf_counter()
        respuesta = self.get_response(request)
        ms = (time.perf_counter() - inicio) * 1000
        respuesta["X-Tiempo-Respuesta-ms"] = f"{ms:.1f}"
        if request.path.startswith("/api/") and ms > 500:
            log.warning("Petición lenta: %s %s (%.0f ms)", request.method, request.path, ms)
        return respuesta
