"""Datos de prueba compartidos (fixtures)."""
from datetime import time
from decimal import Decimal

import pytest
from django.utils import timezone
from rest_framework.test import APIClient

from apps.cuentas.models import Usuario
from apps.logistica.models import Conductor, PedidoDespacho, PuntoEntrega, Vehiculo, Zona

CLAVE = "ClaveSegura2026"


def _usuario(username, rol, **extra):
    return Usuario.objects.create_user(username, f"{username}@test.pe", CLAVE, rol=rol,
                                       first_name=username.title(), **extra)


@pytest.fixture
def admin(db):
    return _usuario("admin", Usuario.Rol.ADMIN)


@pytest.fixture
def supervisor(db):
    return _usuario("supervisor", Usuario.Rol.SUPERVISOR)


@pytest.fixture
def conductor_user(db):
    return _usuario("chofer", Usuario.Rol.CONDUCTOR)


@pytest.fixture
def otro_conductor_user(db):
    return _usuario("chofer2", Usuario.Rol.CONDUCTOR)


@pytest.fixture
def zona(db):
    return Zona.objects.create(codigo="Z01", nombre="Centro", color="#2F80ED", centro_lat=-6.7718, centro_lng=-79.8405)


@pytest.fixture
def zona_b(db):
    return Zona.objects.create(codigo="Z02", nombre="JLO", color="#9B51E0", centro_lat=-6.7555, centro_lng=-79.8460)


@pytest.fixture
def vehiculo(conductor_user):
    c = Conductor.objects.create(usuario=conductor_user, licencia="Q12345678", celular="987654321")
    return Vehiculo.objects.create(placa="ABC-123", tipo="FURGONETA", capacidad_kg=500, capacidad_bultos=30, conductor=c)


@pytest.fixture
def vehiculo_b(otro_conductor_user):
    c = Conductor.objects.create(usuario=otro_conductor_user, licencia="Q87654321", celular="912345678")
    return Vehiculo.objects.create(placa="XYZ-789", tipo="CAMION", capacidad_kg=2000, capacidad_bultos=100, conductor=c)


@pytest.fixture
def crear_pedido(zona):
    contador = {"n": 0}

    def _crear(peso=20, bultos=1, prioridad="NORMAL", lat=None, lng=None, ventana=None, zona_obj=None, fecha=None):
        contador["n"] += 1
        n = contador["n"]
        punto = PuntoEntrega.objects.create(
            cliente_nombre=f"Cliente {n}", direccion=f"Calle {n}", zona=zona_obj or zona,
            latitud=lat if lat is not None else -6.770 - n * 0.002,
            longitud=lng if lng is not None else -79.840 - (n % 3) * 0.003,
        )
        return PedidoDespacho.objects.create(
            punto_entrega=punto, peso_kg=Decimal(str(peso)), bultos=bultos, prioridad=prioridad,
            ventana_inicio=ventana[0] if ventana else None, ventana_fin=ventana[1] if ventana else None,
            fecha_programada=fecha or timezone.localdate(),
        )
    return _crear


@pytest.fixture
def pedidos(crear_pedido):
    return [crear_pedido(peso=30 + i * 5) for i in range(5)]


def cliente_de(usuario):
    c = APIClient()
    c.force_authenticate(usuario)
    return c


@pytest.fixture
def api_admin(admin):
    return cliente_de(admin)


@pytest.fixture
def api_sup(supervisor):
    return cliente_de(supervisor)


@pytest.fixture
def api_cond(conductor_user):
    return cliente_de(conductor_user)


@pytest.fixture
def api_otro_cond(otro_conductor_user):
    return cliente_de(otro_conductor_user)


@pytest.fixture
def ventana_manana():
    return (time(9, 0), time(11, 0))
