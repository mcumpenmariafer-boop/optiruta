"""
Punto de entrada ASGI: atiende HTTP (Django) y WebSockets (Django Channels).

    /ws/mapa/?token=<JWT>   eventos en vivo del mapa del día (solo supervisor y administrador)
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django_asgi_app = get_asgi_application()

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402

from apps.logistica.routing import websocket_urlpatterns  # noqa: E402
from apps.logistica.ws_auth import JWTAuthMiddleware  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(JWTAuthMiddleware(URLRouter(websocket_urlpatterns))),
})
