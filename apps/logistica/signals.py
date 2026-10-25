"""Señales de Django (Tema 8.3): mantienen sincronizado el pedido con su parada."""
from django.db.models.signals import post_save
from django.dispatch import receiver

from .models import ParadaRuta, PedidoDespacho


@receiver(post_save, sender=ParadaRuta)
def sincronizar_pedido(sender, instance, created, **kwargs):
    if created:
        return
    E, P = ParadaRuta.Estado, PedidoDespacho.Estado
    pedido = instance.pedido
    if instance.estado == E.ENTREGADO and pedido.estado != P.ENTREGADO:
        pedido.estado = P.ENTREGADO
        pedido.save(update_fields=["estado"])
    elif instance.estado == E.FALLIDO and pedido.estado != P.FALLIDO:
        pedido.estado = P.FALLIDO
        pedido.save(update_fields=["estado"])
    elif instance.estado == E.REPROGRAMADO and pedido.estado != P.REPROGRAMADO:
        from .servicios import reprogramar_pedido
        reprogramar_pedido(pedido)
