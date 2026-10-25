"""Autenticación de WebSockets con el mismo token JWT de la API (?token=...)."""
from urllib.parse import parse_qs

from channels.db import database_sync_to_async
from channels.middleware import BaseMiddleware
from django.contrib.auth.models import AnonymousUser
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken


@database_sync_to_async
def usuario_desde_token(token):
    from apps.cuentas.models import Usuario
    try:
        datos = AccessToken(token)
        return Usuario.objects.get(pk=datos["user_id"], is_active=True)
    except (TokenError, KeyError, Usuario.DoesNotExist):
        return AnonymousUser()


class JWTAuthMiddleware(BaseMiddleware):
    async def __call__(self, scope, receive, send):
        token = parse_qs(scope.get("query_string", b"").decode()).get("token", [None])[0]
        scope["user"] = await usuario_desde_token(token) if token else AnonymousUser()
        return await super().__call__(scope, receive, send)
