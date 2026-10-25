"""Permisos por rol para la API (backend). El frontend aplica las mismas reglas."""
from rest_framework.permissions import SAFE_METHODS, BasePermission


class EsAdmin(BasePermission):
    message = "Solo el administrador puede realizar esta acción."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.es_admin)


class EsSupervisorOAdmin(BasePermission):
    message = "Solo supervisores o administradores pueden realizar esta acción."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and (u.es_admin or u.es_supervisor))


class EsConductor(BasePermission):
    message = "Solo los conductores pueden realizar esta acción."

    def has_permission(self, request, view):
        u = request.user
        return bool(u and u.is_authenticated and u.es_conductor)


class LecturaTodosEscrituraGestion(BasePermission):
    """Cualquier usuario autenticado lee; solo supervisor/admin escriben."""

    message = "No tienes permiso para modificar este recurso."

    def has_permission(self, request, view):
        u = request.user
        if not (u and u.is_authenticated):
            return False
        if request.method in SAFE_METHODS:
            return True
        return u.es_admin or u.es_supervisor
