"""Pruebas de la capa de formularios (forms.py) y de la restricción de capacidad en la base de datos."""
from datetime import timedelta
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.logistica.forms import PedidoForm, PuntoEntregaForm, VehiculoForm
from apps.logistica.models import Ruta

HOY = timezone.localdate


@pytest.mark.django_db
class TestFormularios:
    def test_punto_entrega_valido_y_normalizado(self, zona):
        f = PuntoEntregaForm(data={"cliente_nombre": "  Bodega Rosita ", "direccion": "Av. Balta 120", "zona": zona.id,
                                   "latitud": -6.77, "longitud": -79.84, "telefono": "943275324",
                                   "email": "rosita@gmail.com"})
        assert f.is_valid(), f.errors
        assert f.cleaned_data["cliente_nombre"] == "Bodega Rosita"

    @pytest.mark.parametrize("cambio,campo", [
        ({"cliente_nombre": "A"}, "cliente_nombre"),
        ({"direccion": "Av"}, "direccion"),
        ({"latitud": -12.04, "longitud": -77.03}, "latitud"),
        ({"telefono": "845959555"}, "telefono"),
        ({"email": "sinarroba.com"}, "email"),
    ])
    def test_punto_entrega_invalido(self, zona, cambio, campo):
        datos = {"cliente_nombre": "Bodega", "direccion": "Av. Balta 120", "zona": zona.id,
                 "latitud": -6.77, "longitud": -79.84, **cambio}
        f = PuntoEntregaForm(data=datos)
        assert not f.is_valid() and campo in f.errors

    def test_pedido_ventanas_y_fechas(self, crear_pedido):
        punto = crear_pedido().punto_entrega.id
        base = {"punto_entrega": punto, "peso_kg": "10", "bultos": 1, "prioridad": "NORMAL",
                "fecha_programada": HOY()}
        assert PedidoForm(data={**base, "ventana_inicio": "09:00", "ventana_fin": "11:00"}).is_valid()
        assert "ventana_fin" in PedidoForm(data={**base, "ventana_inicio": "11:00", "ventana_fin": "09:00"}).errors
        assert "ventana_fin" in PedidoForm(data={**base, "ventana_inicio": "09:00", "ventana_fin": "09:20"}).errors
        assert "ventana_inicio" in PedidoForm(data={**base, "ventana_inicio": "05:00", "ventana_fin": "07:00"}).errors
        assert "fecha_programada" in PedidoForm(data={**base, "fecha_programada": HOY() - timedelta(days=1)}).errors
        assert "peso_kg" in PedidoForm(data={**base, "peso_kg": "0"}).errors

    def test_pedido_asignado_no_se_edita(self, crear_pedido):
        pedido = crear_pedido()
        pedido.estado = "ASIGNADO"
        pedido.save()
        f = PedidoForm(data={"punto_entrega": pedido.punto_entrega_id, "peso_kg": "5", "bultos": 1,
                             "prioridad": "NORMAL", "fecha_programada": HOY()}, instance=pedido)
        assert not f.is_valid() and "__all__" in f.errors

    def test_vehiculo_placa_y_capacidad_por_tipo(self):
        f = VehiculoForm(data={"placa": "abc-321", "tipo": "FURGONETA", "capacidad_kg": "800", "capacidad_bultos": 40,
                               "disponible": True})
        assert f.is_valid(), f.errors
        assert f.cleaned_data["placa"] == "ABC-321"
        f = VehiculoForm(data={"placa": "MOT-321", "tipo": "MOTO", "capacidad_kg": "500", "capacidad_bultos": 5})
        assert "capacidad_kg" in f.errors


@pytest.mark.django_db
def test_bd_rechaza_ruta_con_exceso_de_carga(vehiculo, pedidos, supervisor):
    from apps.logistica import servicios
    ruta = servicios.planificar_ruta(vehiculo, [p.id for p in pedidos], HOY(), supervisor)
    assert ruta.capacidad_kg == vehiculo.capacidad_kg
    with pytest.raises(IntegrityError), transaction.atomic():
        Ruta.objects.filter(pk=ruta.pk).update(peso_total_kg=Decimal("999999"))
    with pytest.raises(IntegrityError), transaction.atomic():
        Ruta.objects.filter(pk=ruta.pk).update(bultos_total=ruta.capacidad_bultos + 1)
