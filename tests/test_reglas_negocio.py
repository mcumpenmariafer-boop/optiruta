"""Pruebas de integración de las reglas de negocio (capa de servicios + base de datos)."""
from datetime import timedelta

import pytest
from django.core import mail
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.logistica import servicios
from apps.logistica.excepciones import ReglaNegocioError
from apps.logistica.models import IndicadorRuta, ParadaRuta, PedidoDespacho, Ruta

HOY = timezone.localdate


def planificar(vehiculo, pedidos, usuario):
    return servicios.planificar_ruta(vehiculo, [p.id for p in pedidos], HOY(), usuario)


def ejecutar_todo(ruta, usuario, estados=None):
    servicios.iniciar_ruta(ruta, usuario)
    for i, parada in enumerate(ruta.paradas.order_by("orden")):
        parada.refresh_from_db()
        estado = (estados or {}).get(i, "ENTREGADO")
        servicios.cambiar_estado_parada(parada, estado, usuario, "Cliente ausente" if estado != "ENTREGADO" else "")


@pytest.mark.django_db
class TestPlanificacion:
    def test_crea_ruta_con_paradas_ordenadas(self, vehiculo, pedidos, supervisor):
        ruta = planificar(vehiculo, pedidos, supervisor)
        assert ruta.codigo.startswith("RT-")
        assert ruta.paradas.count() == 5
        assert list(ruta.paradas.values_list("orden", flat=True)) == [1, 2, 3, 4, 5]
        assert ruta.km_estimados <= ruta.km_sin_optimizar
        assert len(ruta.secuencia) == 5
        assert all(p.estado == "ASIGNADO" for p in PedidoDespacho.objects.all())
        assert ruta.eventos.filter(tipo="PLANIFICADA").exists()

    def test_rn1_vehiculo_no_puede_tener_dos_rutas_activas(self, vehiculo, crear_pedido, supervisor):
        planificar(vehiculo, [crear_pedido()], supervisor)
        with pytest.raises(ReglaNegocioError) as e:
            planificar(vehiculo, [crear_pedido()], supervisor)
        assert e.value.codigo == "vehiculo_con_ruta_activa"

    def test_rn1_restriccion_en_base_de_datos(self, vehiculo):
        Ruta.objects.create(vehiculo=vehiculo, fecha=HOY())
        with pytest.raises(IntegrityError), transaction.atomic():
            Ruta.objects.create(vehiculo=vehiculo, fecha=HOY())

    def test_rn2_capacidad_en_kg(self, vehiculo, crear_pedido, supervisor):
        ps = [crear_pedido(peso=300), crear_pedido(peso=250)]
        with pytest.raises(ReglaNegocioError) as e:
            planificar(vehiculo, ps, supervisor)
        assert e.value.codigo == "capacidad_excedida"
        assert not Ruta.objects.exists()

    def test_rn2_capacidad_en_bultos(self, vehiculo, crear_pedido, supervisor):
        with pytest.raises(ReglaNegocioError):
            planificar(vehiculo, [crear_pedido(peso=1, bultos=31)], supervisor)

    def test_rn3_urgente_primero(self, vehiculo, crear_pedido, supervisor):
        ps = [crear_pedido() for _ in range(4)]
        lejano = crear_pedido(prioridad="URGENTE", lat=-6.80, lng=-79.82)
        ruta = planificar(vehiculo, ps + [lejano], supervisor)
        assert ruta.paradas.get(orden=1).pedido == lejano

    def test_pedido_ya_asignado_no_se_replanifica(self, vehiculo, vehiculo_b, pedidos, supervisor):
        planificar(vehiculo, pedidos[:2], supervisor)
        with pytest.raises(ReglaNegocioError) as e:
            planificar(vehiculo_b, pedidos[:3], supervisor)
        assert e.value.codigo == "pedido_no_disponible"

    def test_vehiculo_sin_conductor_o_no_disponible(self, vehiculo, pedidos, supervisor):
        vehiculo.disponible = False
        vehiculo.save()
        with pytest.raises(ReglaNegocioError, match="no está disponible"):
            planificar(vehiculo, pedidos, supervisor)
        vehiculo.disponible, vehiculo.conductor = True, None
        vehiculo.save()
        with pytest.raises(ReglaNegocioError, match="conductor"):
            planificar(vehiculo, pedidos, supervisor)

    def test_pedido_inexistente(self, vehiculo, supervisor):
        with pytest.raises(ReglaNegocioError) as e:
            servicios.planificar_ruta(vehiculo, [9999], HOY(), supervisor)
        assert e.value.http == 404

    def test_previsualizar_no_guarda(self, vehiculo, pedidos):
        datos = servicios.previsualizar(vehiculo, PedidoDespacho.objects.all())
        assert datos["optimizada"]["km"] <= datos["sin_optimizar"]["km"]
        assert len(datos["optimizada"]["paradas"]) == 5
        assert not Ruta.objects.exists()
        with pytest.raises(ReglaNegocioError):
            servicios.previsualizar(vehiculo, [])

    def test_planificacion_automatica_reparte_flota(self, vehiculo, vehiculo_b, crear_pedido, zona_b, supervisor):
        for _ in range(4):
            crear_pedido(peso=100)
            crear_pedido(peso=150, zona_obj=zona_b)
        rutas, sobrantes = servicios.planificar_automatico(HOY(), supervisor)
        assert len(rutas) >= 1 and sobrantes == []
        for r in rutas:
            assert r.peso_total_kg <= r.vehiculo.capacidad_kg
        assert not PedidoDespacho.objects.filter(estado="PENDIENTE").exists()

    def test_planificacion_automatica_sin_pedidos_o_vehiculos(self, vehiculo, supervisor, crear_pedido):
        with pytest.raises(ReglaNegocioError, match="pedidos"):
            servicios.planificar_automatico(HOY(), supervisor)
        crear_pedido()
        vehiculo.disponible = False
        vehiculo.save()
        with pytest.raises(ReglaNegocioError, match="vehículos"):
            servicios.planificar_automatico(HOY(), supervisor)


@pytest.mark.django_db
class TestEjecucion:
    def test_iniciar_pone_primera_parada_en_camino(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        ruta.refresh_from_db()
        assert ruta.estado == "EN_CURSO" and ruta.hora_inicio
        assert ruta.paradas.get(orden=1).estado == "EN_CAMINO"
        assert PedidoDespacho.objects.filter(estado="EN_RUTA").count() == 5
        with pytest.raises(ReglaNegocioError):
            servicios.iniciar_ruta(ruta, conductor_user)

    def test_transicion_invalida(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        p1 = ruta.paradas.get(orden=1)
        servicios.cambiar_estado_parada(p1, "ENTREGADO", conductor_user)
        with pytest.raises(ReglaNegocioError) as e:
            servicios.cambiar_estado_parada(p1, "FALLIDO", conductor_user, "Ya entregado")
        assert e.value.codigo == "transicion_invalida"
        with pytest.raises(ReglaNegocioError):
            servicios.cambiar_estado_parada(p1, "VOLANDO", conductor_user)

    def test_avance_automatico_a_la_siguiente_parada(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        servicios.cambiar_estado_parada(ruta.paradas.get(orden=1), "ENTREGADO", conductor_user)
        assert ruta.paradas.get(orden=2).estado == "EN_CAMINO"
        assert ruta.paradas.get(orden=1).pedido.estado == "ENTREGADO"  # señal sincronizó el pedido

    def test_rn6_orden_optimizado(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        servicios.cambiar_estado_parada(ruta.paradas.get(orden=1), "REPROGRAMADO", conductor_user, "Cliente pidió otro día")
        ruta.paradas.filter(orden=2).update(estado="PENDIENTE")
        with pytest.raises(ReglaNegocioError) as e:
            servicios.cambiar_estado_parada(ruta.paradas.get(orden=4), "EN_CAMINO", conductor_user)
        assert e.value.codigo == "orden_no_respetado"
        servicios.cambiar_estado_parada(ruta.paradas.get(orden=2), "EN_CAMINO", conductor_user)
        with pytest.raises(ReglaNegocioError) as e:
            servicios.cambiar_estado_parada(ruta.paradas.get(orden=3), "EN_CAMINO", conductor_user)
        assert e.value.codigo == "otra_en_camino"

    def test_rn7_fallido_exige_observacion(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        with pytest.raises(ReglaNegocioError) as e:
            servicios.cambiar_estado_parada(ruta.paradas.get(orden=1), "FALLIDO", conductor_user, "")
        assert e.value.codigo == "observacion_requerida"
        servicios.cambiar_estado_parada(ruta.paradas.get(orden=1), "FALLIDO", conductor_user, "Local cerrado")
        assert ruta.paradas.get(orden=1).pedido.estado == "FALLIDO"

    def test_reprogramado_vuelve_a_pendientes_del_dia_siguiente(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        parada = ruta.paradas.get(orden=1)
        servicios.cambiar_estado_parada(parada, "REPROGRAMADO", conductor_user, "Cliente pidió otro día")
        pedido = PedidoDespacho.objects.get(pk=parada.pedido_id)
        assert pedido.estado == "REPROGRAMADO"
        assert pedido.fecha_programada == HOY() + timedelta(days=1)

    def test_rn8_conductor_ajeno_no_opera(self, vehiculo, pedidos, supervisor, otro_conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        with pytest.raises(ReglaNegocioError) as e:
            servicios.iniciar_ruta(ruta, otro_conductor_user)
        assert e.value.http == 403

    def test_ruta_no_iniciada_no_acepta_entregas(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        with pytest.raises(ReglaNegocioError, match="EN CURSO"):
            servicios.cambiar_estado_parada(ruta.paradas.first(), "EN_CAMINO", conductor_user)
        # supervisión sí puede reprogramar antes de salir
        servicios.cambiar_estado_parada(ruta.paradas.first(), "REPROGRAMADO", supervisor, "Cliente cerró hoy")

    def test_rn4_no_se_cierra_con_paradas_pendientes(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        with pytest.raises(ReglaNegocioError) as e:
            servicios.cerrar_ruta(ruta, conductor_user)
        assert e.value.codigo == "paradas_pendientes"
        assert e.value.detalle["paradas"] == [1, 2, 3, 4, 5]

    def test_cierre_calcula_kpis_y_notifica(self, vehiculo, pedidos, supervisor, conductor_user, django_capture_on_commit_callbacks):
        ruta = planificar(vehiculo, pedidos, supervisor)
        ejecutar_todo(ruta, conductor_user, {1: "FALLIDO"})
        servicios.registrar_posicion(vehiculo, -6.77, -79.84, conductor_user)
        servicios.registrar_posicion(vehiculo, -6.78, -79.85, conductor_user)
        with django_capture_on_commit_callbacks(execute=True):
            servicios.cerrar_ruta(ruta, conductor_user)
        ruta.refresh_from_db()
        k = IndicadorRuta.objects.get(ruta=ruta)
        assert ruta.estado == "COMPLETADA" and ruta.km_reales > 0
        assert (k.pedidos_asignados, k.pedidos_entregados, k.pedidos_fallidos) == (5, 4, 1)
        assert float(k.porcentaje_entrega) == 80.0
        assert k.ahorro_km >= 0
        assert len(mail.outbox) == 1 and ruta.codigo in mail.outbox[0].subject
        with pytest.raises(ReglaNegocioError):
            servicios.cerrar_ruta(ruta, conductor_user)

    def test_cancelar_libera_pedidos(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        with pytest.raises(ReglaNegocioError):
            servicios.cancelar_ruta(ruta, conductor_user, "No quiero")
        with pytest.raises(ReglaNegocioError):
            servicios.cancelar_ruta(ruta, supervisor, "")
        servicios.cancelar_ruta(ruta, supervisor, "Vehículo averiado")
        assert not PedidoDespacho.objects.exclude(estado="PENDIENTE").exists()
        planificar(vehiculo, pedidos, supervisor)  # el vehículo vuelve a quedar libre

    def test_registrar_posicion(self, vehiculo, pedidos, supervisor, conductor_user, otro_conductor_user):
        ruta = planificar(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        pos = servicios.registrar_posicion(vehiculo, -6.775, -79.85, conductor_user, 20)
        vehiculo.refresh_from_db()
        assert pos.ruta == ruta and vehiculo.ultima_lat == -6.775
        with pytest.raises(ReglaNegocioError):
            servicios.registrar_posicion(vehiculo, -6.77, -79.85, otro_conductor_user)

    def test_restricciones_de_modelo(self, vehiculo, crear_pedido):
        from datetime import time
        p = crear_pedido()
        p.ventana_inicio, p.ventana_fin = time(12), time(10)
        with pytest.raises(IntegrityError), transaction.atomic():
            p.save()
        assert str(p).startswith("PD-") and str(vehiculo).startswith("ABC-123")
        assert ParadaRuta._meta.constraints


@pytest.mark.django_db
def test_limite_de_paradas_por_ruta(vehiculo_b, crear_pedido, supervisor, settings):
    settings.OPTIRUTA = {**settings.OPTIRUTA, "MAX_PARADAS_RUTA": 3}
    ps = [crear_pedido(peso=5) for _ in range(4)]
    with pytest.raises(ReglaNegocioError) as e:
        planificar(vehiculo_b, ps, supervisor)
    assert e.value.codigo == "demasiadas_paradas"
    rutas, sobrantes = servicios.planificar_automatico(HOY(), supervisor)
    assert rutas[0].paradas.count() == 3 and len(sobrantes) == 1
