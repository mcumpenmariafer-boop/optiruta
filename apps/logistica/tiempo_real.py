"""Publica eventos de la operación hacia los navegadores conectados por WebSocket."""
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.db import transaction

from .consumers import GRUPO_MAPA

log = logging.getLogger("optiruta")


def _enviar(tipo, datos):
    capa = get_channel_layer()
    if capa is None:
        return
    try:
        async_to_sync(capa.group_send)(GRUPO_MAPA, {"type": "evento", "tipo": tipo, "datos": datos})
    except Exception:  # el tiempo real nunca debe romper la operación
        log.exception("No se pudo publicar el evento %s", tipo)


def publicar(tipo, **datos):
    """Se envía solo cuando la transacción se confirma (nunca se anuncia algo que no se guardó)."""
    transaction.on_commit(lambda: _enviar(tipo, datos))
