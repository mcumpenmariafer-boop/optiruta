"""
Consumer de WebSocket del mapa del día.

El servidor envía un mensaje cada vez que ocurre algo en la operación:
    {"tipo": "posicion", "datos": {"vehiculo": 3, "ruta": 12, "lat": -6.77, "lng": -79.84}}
    {"tipo": "parada",   "datos": {"ruta": 12, "parada": 85, "estado": "ENTREGADO"}}
    {"tipo": "ruta",     "datos": {"ruta": 12, "estado": "COMPLETADA"}}
"""
from channels.generic.websocket import AsyncJsonWebsocketConsumer

GRUPO_MAPA = "mapa"


class MapaConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        usuario = self.scope.get("user")
        if not usuario or not usuario.is_authenticated or not (usuario.es_admin or usuario.es_supervisor):
            await self.close(code=4403)  # sin permiso
            return
        await self.channel_layer.group_add(GRUPO_MAPA, self.channel_name)
        await self.accept()
        await self.send_json({"tipo": "conectado", "datos": {"usuario": usuario.username}})

    async def disconnect(self, code):
        await self.channel_layer.group_discard(GRUPO_MAPA, self.channel_name)

    async def receive_json(self, contenido, **kwargs):
        if contenido.get("tipo") == "ping":           # mantiene viva la conexión
            await self.send_json({"tipo": "pong"})

    async def evento(self, mensaje):
        """Reenvía al navegador los eventos publicados por apps.logistica.tiempo_real."""
        await self.send_json({"tipo": mensaje["tipo"], "datos": mensaje["datos"]})
