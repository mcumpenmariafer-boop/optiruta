"""Pruebas del tiempo real (WebSockets con Django Channels)."""
import pytest
from asgiref.sync import async_to_sync, sync_to_async
from channels.testing import WebsocketCommunicator
from django.utils import timezone
from rest_framework_simplejwt.tokens import AccessToken

from apps.logistica import servicios
from config.asgi import application


def conectar(usuario=None):
    url = "/ws/mapa/"
    if usuario is not None:
        url += f"?token={AccessToken.for_user(usuario)}"
    return WebsocketCommunicator(application, url, headers=[(b"origin", b"http://localhost")])


@pytest.mark.django_db(transaction=True)
def test_supervisor_recibe_posicion_y_cambios_al_instante(supervisor, conductor_user, vehiculo, pedidos):
    async def escenario():
        ws = conectar(supervisor)
        conectado, _ = await ws.connect()
        assert conectado
        assert (await ws.receive_json_from())["tipo"] == "conectado"

        ruta = await sync_to_async(servicios.planificar_ruta)(vehiculo, [p.id for p in pedidos],
                                                              timezone.localdate(), supervisor)
        evento = await ws.receive_json_from(timeout=3)
        assert evento == {"tipo": "ruta", "datos": {"ruta": ruta.id, "estado": "PLANIFICADA", "vehiculo": vehiculo.id}}

        await sync_to_async(servicios.iniciar_ruta)(ruta, conductor_user)
        assert (await ws.receive_json_from(timeout=3))["datos"]["estado"] == "EN_CURSO"

        await sync_to_async(servicios.registrar_posicion)(vehiculo, -6.775, -79.85, conductor_user)
        evento = await ws.receive_json_from(timeout=3)
        assert evento["tipo"] == "posicion" and evento["datos"]["lat"] == -6.775

        parada = await sync_to_async(lambda: ruta.paradas.get(orden=1))()
        await sync_to_async(servicios.cambiar_estado_parada)(parada, "ENTREGADO", conductor_user)
        evento = await ws.receive_json_from(timeout=3)
        assert evento["tipo"] == "parada" and evento["datos"]["estado"] == "ENTREGADO"

        await ws.send_json_to({"tipo": "ping"})
        assert (await ws.receive_json_from())["tipo"] == "pong"
        await ws.disconnect()
    async_to_sync(escenario)()


@pytest.mark.django_db(transaction=True)
@pytest.mark.parametrize("quien", ["anonimo", "conductor", "token_falso"])
def test_websocket_rechaza_sin_permiso(conductor_user, quien):
    async def escenario():
        if quien == "anonimo":
            ws = conectar()
        elif quien == "conductor":
            ws = conectar(conductor_user)
        else:
            ws = WebsocketCommunicator(application, "/ws/mapa/?token=abc", headers=[(b"origin", b"http://localhost")])
        conectado, _ = await ws.connect()
        assert not conectado
    async_to_sync(escenario)()
