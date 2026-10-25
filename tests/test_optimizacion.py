"""Pruebas unitarias del motor de optimización (sin base de datos)."""
import random
from datetime import time

import pytest

from apps.optimizacion import asignacion, metricas, motor
from apps.optimizacion.geo import distancia_vial, haversine, longitud_polilinea, matriz_distancias

DEP = (-6.778810, -79.868766)


def cfg(**kw):
    return motor.Configuracion(deposito=DEP, **kw)


# ---------------------------------------------------------------- Geo
def test_haversine_chiclayo_lambayeque():
    # Plaza de Armas de Chiclayo -> Plaza de Lambayeque: ~11.6 km en línea recta
    d = haversine(-6.7714, -79.8409, -6.7011, -79.9061)
    assert 10.5 < d < 12.5


def test_haversine_mismo_punto_es_cero():
    assert haversine(*DEP, *DEP) == 0


def test_distancia_vial_aplica_factor():
    recta = haversine(-6.77, -79.84, -6.78, -79.86)
    assert distancia_vial(-6.77, -79.84, -6.78, -79.86, factor=1.3) == pytest.approx(recta * 1.3)


def test_matriz_simetrica_y_diagonal_cero():
    pts = [DEP, (-6.77, -79.84), (-6.75, -79.85)]
    m = matriz_distancias(pts)
    assert all(m[i][i] == 0 for i in range(3))
    assert m[0][1] == m[1][0] and m[1][2] == m[2][1]


def test_longitud_polilinea():
    assert longitud_polilinea([DEP, DEP]) == 0
    assert longitud_polilinea([(-6.77, -79.84), (-6.78, -79.84)]) == pytest.approx(1.11, rel=0.02)


# ---------------------------------------------------------------- Secuenciación
def _paradas(n, semilla=1):
    rnd = random.Random(semilla)
    return [motor.Parada(i, DEP[0] + rnd.uniform(-0.03, 0.03), DEP[1] + rnd.uniform(-0.03, 0.03), codigo=f"P{i}")
            for i in range(1, n + 1)]


def test_ruta_vacia():
    resultado, it = motor.optimizar_secuencia([], cfg())
    assert resultado.km_total == 0 and resultado.secuencia == [] and it == 0


def test_visita_todas_las_paradas_una_vez():
    ps = _paradas(12)
    r, _ = motor.optimizar_secuencia(ps, cfg())
    assert sorted(r.ids) == sorted(p.id for p in ps)


@pytest.mark.parametrize("semilla", [1, 2, 3, 4, 5])
def test_optimizada_no_es_peor_que_orden_de_llegada(semilla):
    ps = _paradas(10, semilla)
    comp = motor.comparar(ps, cfg())
    assert comp["optima"].km_total <= comp["base"].km_total + 1e-6
    assert comp["ahorro_km"] >= 0


def test_dos_opt_elimina_cruces():
    # cuadrado recorrido en "X" (con cruce): el óptimo es el perímetro
    a = motor.Parada(1, DEP[0] + 0.01, DEP[1] + 0.01)
    b = motor.Parada(2, DEP[0] - 0.01, DEP[1] - 0.01)
    c = motor.Parada(3, DEP[0] + 0.01, DEP[1] - 0.01)
    d = motor.Parada(4, DEP[0] - 0.01, DEP[1] + 0.01)
    cruzada = motor.evaluar([a, b, c, d], cfg())
    optima, _ = motor.optimizar_secuencia([a, b, c, d], cfg())
    assert optima.km_total < cruzada.km_total


def test_urgentes_van_primero_rn3():
    ps = _paradas(8)
    ps[5].prioridad = "URGENTE"
    ps[7].prioridad = "URGENTE"
    r, _ = motor.optimizar_secuencia(ps, cfg())
    assert {r.ids[0], r.ids[1]} == {ps[5].id, ps[7].id}


def test_respeta_ventanas_horarias_rn5():
    ps = _paradas(6)
    # una parada cercana que solo recibe por la tarde no debe ir primero
    ps[0].lat, ps[0].lng = DEP[0] + 0.001, DEP[1] + 0.001
    ps[0].ventana_inicio, ps[0].ventana_fin = 14 * 60, 16 * 60
    ps[1].ventana_inicio, ps[1].ventana_fin = 8 * 60, 9 * 60
    r, _ = motor.optimizar_secuencia(ps, cfg())
    assert r.ventanas_incumplidas == 0
    assert r.ids[-1] == ps[0].id
    programada = next(p for p in r.secuencia if p.parada.id == ps[0].id)
    assert programada.inicio >= 14 * 60


def test_detecta_ventana_imposible():
    p = motor.Parada(1, DEP[0] + 0.05, DEP[1] + 0.05, ventana_inicio=6 * 60, ventana_fin=8 * 60 + 1)
    r = motor.evaluar([p], cfg())
    assert r.ventanas_incumplidas == 1 and r.tardanza_total > 0


def test_espera_si_llega_antes_de_la_ventana():
    p = motor.Parada(1, DEP[0] + 0.001, DEP[1], ventana_inicio=10 * 60, ventana_fin=12 * 60)
    r = motor.evaluar([p], cfg())
    assert r.espera_total > 100 and r.secuencia[0].inicio == 600


def test_conversion_horas():
    assert motor.a_minutos(time(9, 30)) == 570
    assert motor.a_minutos("08:15") == 495
    assert motor.a_minutos(None) is None
    assert motor.a_minutos(60) == 60
    assert motor.a_hora(570) == time(9, 30)


def test_tiempo_incluye_regreso_al_deposito():
    p = motor.Parada(1, DEP[0] + 0.02, DEP[1])
    ida = motor.evaluar([p], cfg(regresar_al_deposito=False))
    vuelta = motor.evaluar([p], cfg())
    assert vuelta.km_total == pytest.approx(ida.km_total * 2, rel=0.01)


# ---------------------------------------------------------------- Asignación FFD
def test_ffd_respeta_capacidad_rn2():
    items = [asignacion.ItemPedido(i, peso, 1) for i, peso in enumerate([400, 300, 250, 200, 100, 50], 1)]
    conts = [asignacion.Contenedor(1, 500, 10), asignacion.Contenedor(2, 600, 10)]
    llenos, sobrantes = asignacion.asignar_ffd(items, conts)
    for c in llenos:
        assert c.carga_kg <= c.capacidad_kg
    asignados = sum(len(c.pedidos) for c in llenos)
    assert asignados + len(sobrantes) == len(items)


def test_ffd_respeta_bultos():
    items = [asignacion.ItemPedido(i, 1, 6) for i in range(1, 4)]
    llenos, sobrantes = asignacion.asignar_ffd(items, [asignacion.Contenedor(1, 1000, 10)])
    assert llenos[0].carga_bultos <= 10 and len(sobrantes) == 2


def test_ffd_prioriza_urgentes_cuando_no_cabe_todo():
    items = [asignacion.ItemPedido(1, 80, 1, prioridad="NORMAL"),
             asignacion.ItemPedido(2, 80, 1, prioridad="URGENTE")]
    llenos, sobrantes = asignacion.asignar_ffd(items, [asignacion.Contenedor(1, 100, 10)])
    assert llenos[0].pedidos == [2] and sobrantes[0].id == 1


def test_ffd_agrupa_por_zona():
    items = [asignacion.ItemPedido(1, 50, 1, zona_id=1), asignacion.ItemPedido(2, 40, 1, zona_id=2),
             asignacion.ItemPedido(3, 30, 1, zona_id=1)]
    conts = [asignacion.Contenedor(1, 200, 10), asignacion.Contenedor(2, 100, 10)]
    llenos, _ = asignacion.asignar_ffd(items, conts)
    mayor = next(c for c in llenos if c.id == 1)
    assert {1, 3} <= set(mayor.pedidos)
    assert mayor.uso_kg_pct > 0


def test_validar_capacidad():
    items = [asignacion.ItemPedido(1, 60, 2), asignacion.ItemPedido(2, 50, 1)]
    assert asignacion.validar_capacidad(items, 120, 5) == (True, 110, 3)
    assert asignacion.validar_capacidad(items, 100, 5)[0] is False


# ---------------------------------------------------------------- Métricas
def test_metricas_combustible_y_co2():
    assert metricas.combustible_litros(100, "FURGONETA") == pytest.approx(10)
    assert metricas.co2_kg(100, "CAMION") == pytest.approx(18 * 2.68)
    assert metricas.costo_combustible(10, "MOTO", 5) == pytest.approx(1.5)
    assert metricas.porcentaje(1, 4) == 25.0 and metricas.porcentaje(1, 0) == 0.0
    imp = metricas.impacto(20, 15, "FURGONETA", 4.3)
    assert imp["ahorro_km"] == 5 and imp["ahorro_litros"] == 0.5 and imp["co2_evitado_kg"] == pytest.approx(1.16, abs=0.01)
    assert metricas.impacto(10, 12, "MOTO")["ahorro_km"] == 0


def test_urgente_con_ventana_de_tarde_no_retrasa_a_los_demas():
    # Un urgente que solo recibe a las 14:00 no debe obligar a esperar: se atienden
    # primero los demás y nadie llega tarde (RN3 + RN5 a la vez).
    ps = _paradas(6, semilla=7)
    ps[0].prioridad = "URGENTE"
    ps[0].ventana_inicio, ps[0].ventana_fin = 14 * 60, 16 * 60
    for p in ps[1:3]:
        p.ventana_inicio, p.ventana_fin = 9 * 60, 11 * 60
    r, _ = motor.optimizar_secuencia(ps, cfg())
    assert r.ventanas_incumplidas == 0
    assert r.ids[-1] == ps[0].id
    assert r.prioridad_violada == 0


def test_urgente_disponible_no_se_posterga():
    ps = _paradas(5, semilla=3)
    ps[4].prioridad = "URGENTE"
    r = motor.evaluar(ps, cfg())          # orden manual: el urgente queda al final
    assert r.prioridad_violada == 4
    optima, _ = motor.optimizar_secuencia(ps, cfg())
    assert optima.prioridad_violada == 0 and optima.ids[0] == ps[4].id
