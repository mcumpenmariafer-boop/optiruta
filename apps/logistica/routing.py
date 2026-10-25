from django.urls import path

from .consumers import MapaConsumer

websocket_urlpatterns = [
    path("ws/mapa/", MapaConsumer.as_asgi()),
]
