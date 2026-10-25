"""Pruebas de la API REST: endpoints, códigos HTTP, validaciones y permisos por rol."""
from datetime import timedelta

import pytest
from django.core.management import call_command
from django.utils import timezone
from rest_framework.test import APIClient

from apps.logistica import servicios
from apps.logistica.models import PedidoDespacho, Ruta

from .conftest import CLAVE

HOY = timezone.localdate


def crear_ruta(vehiculo, pedidos, supervisor):
    return servicios.planificar_ruta(vehiculo, [p.id for p in pedidos], HOY(), supervisor)


@pytest.mark.django_db
class TestAutenticacion:
    def test_login_devuelve_jwt_y_rol(self, supervisor):
        r = APIClient().post("/api/auth/login/", {"username": "supervisor", "password": CLAVE}, format="json")
        assert r.status_code == 200
        assert {"access", "refresh", "usuario"} <= set(r.data)
        assert r.data["usuario"]["rol"] == "SUPERVISOR"
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {r.data['access']}")
        assert c.get("/api/auth/yo/").data["username"] == "supervisor"
        ref = APIClient().post("/api/auth/refresh/", {"refresh": r.data["refresh"]}, format="json")
        assert ref.status_code == 200 and "access" in ref.data

    def test_login_incorrecto(self, supervisor):
        r = APIClient().post("/api/auth/login/", {"username": "supervisor", "password": "mala"}, format="json")
        assert r.status_code == 401
        assert r.data["error"] == "Usuario o contraseña incorrectos."

    def test_sin_token_401(self, db):
        assert APIClient().get("/api/rutas/").status_code == 401

    def test_admin_es_admin_aunque_sea_superusuario(self, db):
        from apps.cuentas.models import Usuario
        Usuario.objects.create_superuser("root", "r@x.pe", CLAVE)
        r = APIClient().post("/api/auth/login/", {"username": "root", "password": CLAVE}, format="json")
        assert r.data["usuario"]["rol"] == "ADMIN"


@pytest.mark.django_db
class TestPermisosPorRol:
    def test_conductor_no_accede_a_pedidos_ni_reportes(self, api_cond):
        assert api_cond.get("/api/pedidos/").status_code == 403
        assert api_cond.get("/api/pedidos/sin-asignar/").status_code == 403
        assert api_cond.get("/api/reportes/eficiencia/").status_code == 403
        assert api_cond.post("/api/rutas/planificar/", {}, format="json").status_code == 403

    def test_conductor_solo_ve_sus_rutas(self, vehiculo, vehiculo_b, crear_pedido, supervisor, api_cond, api_otro_cond):
        r1 = crear_ruta(vehiculo, [crear_pedido()], supervisor)
        crear_ruta(vehiculo_b, [crear_pedido()], supervisor)
        datos = api_cond.get("/api/rutas/").data
        assert datos["count"] == 1 and datos["results"][0]["id"] == r1.id
        assert api_otro_cond.get(f"/api/rutas/{r1.id}/").status_code == 404
        assert api_cond.get("/api/vehiculos/").data["count"] == 1

    def test_solo_admin_gestiona_usuarios(self, api_sup, api_admin):
        assert api_sup.get("/api/usuarios/").status_code == 403
        r = api_admin.post("/api/usuarios/", {"username": "nuevo", "password": "OtraClave2026!", "rol": "CONDUCTOR",
                                              "telefono": "912345678"}, format="json")
        assert r.status_code == 201
        assert api_admin.post("/api/usuarios/", {"username": "x", "rol": "CONDUCTOR"}, format="json").status_code == 400
        assert api_admin.post("/api/usuarios/", {"username": "y", "password": "OtraClave2026!", "telefono": "123"},
                              format="json").status_code == 400
        assert api_admin.patch(f"/api/usuarios/{r.data['id']}/", {"password": "Nueva2026Clave"}, format="json").status_code == 200

    def test_zonas_lectura_para_todos(self, api_cond, zona, api_sup):
        assert api_cond.get("/api/zonas/").status_code == 200
        assert api_cond.post("/api/zonas/", {}, format="json").status_code == 403
        assert api_sup.get(f"/api/zonas/{zona.id}/pedidos-hoy/").status_code == 200


@pytest.mark.django_db
class TestEndpointsMinimos:
    def test_planificar_201(self, api_sup, vehiculo, pedidos):
        r = api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": [p.id for p in pedidos]}, format="json")
        assert r.status_code == 201
        assert len(r.data["paradas"]) == 5 and r.data["estado"] == "PLANIFICADA"

    def test_planificar_validaciones(self, api_sup, vehiculo, pedidos, crear_pedido):
        ids = [p.id for p in pedidos]
        assert api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": []}, format="json").status_code == 400
        assert api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": [ids[0], ids[0]]}, format="json").status_code == 400
        ayer = (HOY() - timedelta(days=1)).isoformat()
        assert api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": ids, "fecha": ayer}, format="json").status_code == 400
        pesado = crear_pedido(peso=900)
        r = api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": [pesado.id]}, format="json")
        assert r.status_code == 400 and r.data["codigo"] == "capacidad_excedida"
        api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": ids}, format="json")
        r = api_sup.post("/api/rutas/planificar/", {"vehiculo": vehiculo.id, "pedidos": [crear_pedido().id]}, format="json")
        assert r.status_code == 409

    def test_previsualizar(self, api_sup, vehiculo, pedidos):
        r = api_sup.post("/api/rutas/previsualizar/", {"vehiculo": vehiculo.id, "pedidos": [p.id for p in pedidos]}, format="json")
        assert r.status_code == 200 and r.data["ahorro"]["km"] >= 0
        assert not Ruta.objects.exists()

    def test_planificar_automatico(self, api_sup, vehiculo, pedidos, zona):
        r = api_sup.post("/api/rutas/planificar-automatico/", {"zona": zona.id}, format="json")
        assert r.status_code == 201 and len(r.data["rutas"]) == 1

    def test_paradas_y_detalle(self, api_sup, vehiculo, pedidos, supervisor):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        r = api_sup.get(f"/api/rutas/{ruta.id}/paradas/")
        assert r.status_code == 200 and [p["orden"] for p in r.data["paradas"]] == [1, 2, 3, 4, 5]
        assert all(p["hora_estimada"] for p in r.data["paradas"])
        d = api_sup.get(f"/api/rutas/{ruta.id}/")
        assert d.data["total_paradas"] == 5 and d.data["avance_pct"] == 0
        assert api_sup.get(f"/api/rutas/{ruta.id}/eventos/").status_code == 200
        lista = api_sup.get("/api/rutas/?estado=PLANIFICADA&ordering=-fecha")
        assert lista.data["count"] == 1

    def test_flujo_conductor_completo(self, api_cond, api_sup, vehiculo, pedidos, supervisor):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        assert api_cond.get("/api/rutas/mi-ruta/").data["ruta"]["id"] == ruta.id
        assert api_cond.post(f"/api/rutas/{ruta.id}/iniciar/").status_code == 200
        en_curso = api_sup.get("/api/rutas/en-curso/").data
        assert len(en_curso) == 1 and en_curso[0]["estado"] == "EN_CURSO"
        r = api_cond.post(f"/api/vehiculos/{vehiculo.id}/posicion/", {"latitud": -6.775, "longitud": -79.85}, format="json")
        assert r.status_code == 201
        assert api_cond.post(f"/api/vehiculos/{vehiculo.id}/posicion/", {"latitud": -12.0, "longitud": -77.0}, format="json").status_code == 400
        assert len(api_sup.get(f"/api/vehiculos/{vehiculo.id}/posicion/").data) == 1
        assert api_cond.post(f"/api/rutas/{ruta.id}/cerrar/").status_code == 409
        for parada in ruta.paradas.order_by("orden"):
            resp = api_cond.patch(f"/api/paradas/{parada.id}/estado/", {"estado": "ENTREGADO"}, format="json")
            assert resp.status_code == 200, resp.data
        r = api_cond.post(f"/api/rutas/{ruta.id}/cerrar/")
        assert r.status_code == 200 and r.data["estado"] == "COMPLETADA"
        assert r.data["indicador"]["porcentaje_entrega"] == "100.0"
        assert api_cond.get("/api/rutas/mi-ruta/").data["ruta"] is None

    def test_estado_parada_errores(self, api_cond, api_otro_cond, vehiculo, pedidos, supervisor):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        p1 = ruta.paradas.get(orden=1)
        assert api_cond.patch(f"/api/paradas/{p1.id}/estado/", {"estado": "ENTREGADO"}, format="json").status_code == 409
        assert api_cond.patch(f"/api/paradas/{p1.id}/estado/", {"estado": "NADA"}, format="json").status_code == 400
        assert api_otro_cond.patch(f"/api/paradas/{p1.id}/estado/", {"estado": "EN_CAMINO"}, format="json").status_code == 404

    def test_cancelar_ruta(self, api_sup, vehiculo, pedidos, supervisor):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        assert api_sup.post(f"/api/rutas/{ruta.id}/cancelar/", {"motivo": "x"}, format="json").status_code == 400
        assert api_sup.post(f"/api/rutas/{ruta.id}/cancelar/", {"motivo": "Avería del vehículo"}, format="json").status_code == 200

    def test_hoja_de_ruta_pdf(self, api_sup, vehiculo, pedidos, supervisor):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        r = api_sup.get(f"/api/rutas/{ruta.id}/hoja-ruta/")
        assert r.status_code == 200 and r["Content-Type"] == "application/pdf"
        assert r.content.startswith(b"%PDF")

    def test_pedidos_sin_asignar_y_filtros(self, api_sup, crear_pedido, zona, zona_b):
        crear_pedido(prioridad="URGENTE")
        crear_pedido(zona_obj=zona_b)
        r = api_sup.get("/api/pedidos/sin-asignar/")
        assert r.data["count"] == 2 and r.data["results"][0]["prioridad"] == "URGENTE"
        assert api_sup.get(f"/api/pedidos/sin-asignar/?zona={zona_b.id}").data["count"] == 1
        assert api_sup.get("/api/pedidos/sin-asignar/?prioridad=URGENTE").data["count"] == 1
        assert api_sup.get(f"/api/pedidos/?fecha={HOY()}&page_size=1").data["count"] == 2

    def test_pedidos_hoy_por_zona(self, api_sup, crear_pedido, zona):
        crear_pedido(peso=12.5)
        crear_pedido(fecha=HOY() + timedelta(days=1))
        r = api_sup.get(f"/api/zonas/{zona.id}/pedidos-hoy/")
        assert r.data["total"] == 1 and r.data["peso_total_kg"] == 12.5


@pytest.mark.django_db
class TestValidacionesCrud:
    def test_crear_pedido_valido(self, api_sup, crear_pedido):
        punto = crear_pedido().punto_entrega
        r = api_sup.post("/api/pedidos/", {"punto_entrega": punto.id, "peso_kg": "15.5", "bultos": 2,
                                           "fecha_programada": HOY().isoformat(), "ventana_inicio": "09:00",
                                           "ventana_fin": "11:00"}, format="json")
        assert r.status_code == 201 and r.data["codigo"].startswith("PD-")

    @pytest.mark.parametrize("cambios,campo", [
        ({"peso_kg": "0"}, "peso_kg"),
        ({"peso_kg": "20000"}, "peso_kg"),
        ({"bultos": 0}, "bultos"),
        ({"fecha_programada": "2020-01-01"}, "fecha_programada"),
        ({"ventana_inicio": "11:00", "ventana_fin": "09:00"}, "ventana_fin"),
        ({"ventana_inicio": "05:00", "ventana_fin": "07:00"}, "ventana_inicio"),
        ({"ventana_inicio": "09:00", "ventana_fin": "09:15"}, "ventana_fin"),
        ({"ventana_inicio": "09:00"}, "ventana_fin"),
    ])
    def test_crear_pedido_invalido(self, api_sup, crear_pedido, cambios, campo):
        punto = crear_pedido().punto_entrega
        datos = {"punto_entrega": punto.id, "peso_kg": "15", "bultos": 1, "fecha_programada": HOY().isoformat(), **cambios}
        r = api_sup.post("/api/pedidos/", datos, format="json")
        assert r.status_code == 400 and campo in r.data["detalle"], r.data

    def test_no_editar_ni_borrar_pedido_asignado(self, api_sup, vehiculo, pedidos, supervisor):
        crear_ruta(vehiculo, pedidos[:1], supervisor)
        assert api_sup.patch(f"/api/pedidos/{pedidos[0].id}/", {"bultos": 3}, format="json").status_code == 400
        assert api_sup.delete(f"/api/pedidos/{pedidos[0].id}/").status_code == 409
        assert api_sup.delete(f"/api/pedidos/{pedidos[1].id}/").status_code == 204

    def test_punto_fuera_del_area(self, api_sup, zona):
        base = {"cliente_nombre": "Tienda", "direccion": "Av. Lima 100", "zona": zona.id}
        assert api_sup.post("/api/puntos-entrega/", {**base, "latitud": -12.04, "longitud": -77.03}, format="json").status_code == 400
        assert api_sup.post("/api/puntos-entrega/", {**base, "cliente_nombre": "A", "latitud": -6.77, "longitud": -79.84}, format="json").status_code == 400
        assert api_sup.post("/api/puntos-entrega/", {**base, "latitud": -6.77, "longitud": -79.84}, format="json").status_code == 201

    def test_vehiculo_validaciones(self, api_sup, api_cond):
        ok = {"placa": "abc-999", "tipo": "FURGONETA", "capacidad_kg": "800", "capacidad_bultos": 40}
        r = api_sup.post("/api/vehiculos/", ok, format="json")
        assert r.status_code == 201 and r.data["placa"] == "ABC-999"
        assert api_sup.post("/api/vehiculos/", {**ok, "placa": "MAL"}, format="json").status_code == 400
        assert api_sup.post("/api/vehiculos/", {**ok, "placa": "MOT-111", "tipo": "MOTO", "capacidad_kg": "500"}, format="json").status_code == 400
        assert api_cond.post("/api/vehiculos/", ok, format="json").status_code == 403
        assert api_sup.patch(f"/api/vehiculos/{r.data['id']}/", {"disponible": False}, format="json").status_code == 200
        assert api_sup.delete(f"/api/vehiculos/{r.data['id']}/").status_code == 204

    def test_no_borrar_vehiculo_con_historial(self, api_sup, vehiculo, pedidos, supervisor):
        crear_ruta(vehiculo, pedidos, supervisor)
        assert api_sup.delete(f"/api/vehiculos/{vehiculo.id}/").status_code == 409

    def test_conductor_crud(self, api_admin, api_sup, admin):
        u = api_admin.post("/api/usuarios/", {"username": "pepe", "password": "Clave2026Segura", "rol": "CONDUCTOR"}, format="json").data
        r = api_sup.post("/api/conductores/", {"usuario": u["id"], "licencia": "Q11112222", "celular": "911111111"}, format="json")
        assert r.status_code == 201
        assert api_sup.post("/api/conductores/", {"usuario": admin.id, "licencia": "Q11113333", "celular": "911111111"}, format="json").status_code == 400


@pytest.mark.django_db
class TestReportesYSeguimiento:
    def _ruta_cerrada(self, vehiculo, pedidos, supervisor, conductor_user):
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        for p in ruta.paradas.order_by("orden"):
            p.refresh_from_db()
            servicios.cambiar_estado_parada(p, "ENTREGADO" if p.orden != 2 else "FALLIDO", conductor_user,
                                            "Local cerrado" if p.orden == 2 else "")
        return servicios.cerrar_ruta(ruta, conductor_user)

    def test_eficiencia(self, api_sup, vehiculo, pedidos, supervisor, conductor_user):
        self._ruta_cerrada(vehiculo, pedidos, supervisor, conductor_user)
        r = api_sup.get(f"/api/reportes/eficiencia/?fecha={HOY()}")
        assert r.status_code == 200
        res = r.data["resumen"]
        assert res["rutas_cerradas"] == 1 and res["pedidos_entregados"] == 4 and res["porcentaje_entrega"] == 80.0
        assert r.data["por_vehiculo"][0]["placa"] == "ABC-123"
        assert r.data["por_zona"][0]["total"] == 5
        assert r.data["motivos_fallo"][0]["observacion"] == "Local cerrado"
        assert api_sup.get(f"/api/reportes/eficiencia/?desde={HOY()}&hasta={HOY()}&vehiculo={vehiculo.id}").status_code == 200
        csv = api_sup.get(f"/api/reportes/eficiencia/?fecha={HOY()}&formato=csv")
        assert csv.status_code == 200 and b"ABC-123" in csv.content

    @pytest.mark.parametrize("q", ["fecha=hoy", "desde=2026-10-10&hasta=2026-10-01", "desde=2020-01-01&hasta=2026-01-01"])
    def test_eficiencia_fechas_invalidas(self, api_sup, q):
        assert api_sup.get(f"/api/reportes/eficiencia/?{q}").status_code == 400

    def test_resumen_dashboard(self, api_sup, vehiculo, pedidos, supervisor, conductor_user, crear_pedido):
        self._ruta_cerrada(vehiculo, pedidos, supervisor, conductor_user)
        crear_pedido(prioridad="URGENTE")
        r = api_sup.get("/api/reportes/resumen/")
        assert r.status_code == 200
        assert r.data["urgentes_sin_asignar"] == 1 and r.data["entregas_hoy"] == 4
        assert r.data["mes"]["ahorro_km"] >= 0

    def test_seguimiento_publico(self, vehiculo, pedidos, supervisor, conductor_user):
        cliente = APIClient()
        r = cliente.get(f"/api/seguimiento/{pedidos[0].codigo.lower()}/")
        assert r.status_code == 200 and r.data["estado"] == "PENDIENTE" and r.data["ruta"] is None
        ruta = crear_ruta(vehiculo, pedidos, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        servicios.registrar_posicion(vehiculo, -6.775, -79.85, conductor_user)
        r = cliente.get(f"/api/seguimiento/{pedidos[0].codigo}/")
        assert r.data["ruta"]["estado"] == "EN_CURSO" and r.data["ruta"]["vehiculo"]["lat"] == -6.775
        assert "telefono" not in str(r.data)  # no expone datos personales
        assert cliente.get("/api/seguimiento/PD-999999/").status_code == 404


@pytest.mark.django_db
def test_paginas_web_responden(client):
    for url in ["/", "/login/", "/seguimiento/", "/app/dashboard/", "/app/planificar/", "/app/pedidos/",
                "/app/historial/", "/app/rutas/1/", "/app/reportes/", "/app/flota/", "/app/conductor/", "/api/docs/"]:
        assert client.get(url).status_code == 200, url


@pytest.mark.django_db
def test_comando_cargar_demo():
    call_command("cargar_demo", "--reset", "--dias", "3")
    assert Ruta.objects.filter(estado="COMPLETADA").exists()
    assert Ruta.objects.filter(estado="EN_CURSO").count() == 1
    assert PedidoDespacho.objects.filter(estado="PENDIENTE").exists()
    call_command("cargar_demo")  # segunda vez no duplica


@pytest.mark.django_db
class TestValidacionContactoYAuditoria:
    @pytest.mark.parametrize("telefono", ["845959555", "98765432", "9876543210", "+51987654321", "abc"])
    def test_celular_peruano_invalido(self, api_sup, zona, telefono):
        r = api_sup.post("/api/puntos-entrega/", {"cliente_nombre": "Tienda", "direccion": "Av. Balta 100", "zona": zona.id,
                                                  "latitud": -6.77, "longitud": -79.84, "telefono": telefono}, format="json")
        assert r.status_code == 400 and "telefono" in r.data["detalle"]

    @pytest.mark.parametrize("email", ["sinarroba.com", "a@", "@gmail.com", "a b@x.pe"])
    def test_correo_invalido(self, api_sup, zona, email):
        r = api_sup.post("/api/puntos-entrega/", {"cliente_nombre": "Tienda", "direccion": "Av. Balta 100", "zona": zona.id,
                                                  "latitud": -6.77, "longitud": -79.84, "email": email}, format="json")
        assert r.status_code == 400 and "email" in r.data["detalle"]

    def test_contacto_valido(self, api_sup, zona):
        r = api_sup.post("/api/puntos-entrega/", {"cliente_nombre": "Tienda", "direccion": "Av. Balta 100", "zona": zona.id,
                                                  "latitud": -6.77, "longitud": -79.84, "telefono": "943275324",
                                                  "email": "tienda@gmail.com"}, format="json")
        assert r.status_code == 201


@pytest.mark.django_db
def test_mapa_del_dia_incluye_completadas_de_hoy(api_sup, vehiculo, pedidos, supervisor, conductor_user):
    ruta = crear_ruta(vehiculo, pedidos, supervisor)
    servicios.iniciar_ruta(ruta, conductor_user)
    for p in ruta.paradas.order_by("orden"):
        p.refresh_from_db()
        servicios.cambiar_estado_parada(p, "ENTREGADO", conductor_user)
    servicios.cerrar_ruta(ruta, conductor_user)
    assert api_sup.get("/api/rutas/en-curso/").data == []
    datos = api_sup.get("/api/rutas/en-curso/?incluir=completadas").data
    assert len(datos) == 1 and datos[0]["estado"] == "COMPLETADA"


@pytest.mark.django_db
class TestCeleryYPdf:
    def test_reporte_pdf(self, api_sup):
        r = api_sup.get(f"/api/reportes/eficiencia/?fecha={HOY()}&formato=pdf")
        assert r.status_code == 200 and r["Content-Type"] == "application/pdf" and r.content.startswith(b"%PDF")

    def test_cierre_diario_reprograma_y_envia_pdf(self, api_sup, api_cond, supervisor, conductor_user, vehiculo, crear_pedido):
        from django.core import mail
        supervisor.email = "lucia@optiruta.pe"
        supervisor.save()
        sin_ruta = crear_pedido()
        en_ruta = [crear_pedido(), crear_pedido()]
        ruta = crear_ruta(vehiculo, en_ruta, supervisor)
        servicios.iniciar_ruta(ruta, conductor_user)
        p1, p2 = list(ruta.paradas.order_by("orden"))
        servicios.cambiar_estado_parada(p1, "FALLIDO", conductor_user, "Cliente ausente")
        p2.refresh_from_db()
        servicios.cambiar_estado_parada(p2, "ENTREGADO", conductor_user)
        mail.outbox.clear()
        r = api_sup.post("/api/reportes/cierre-diario/", {}, format="json")
        assert r.status_code == 200 and r.data["modo"] == "inmediato"
        assert r.data["resultado"]["reprogramados_sin_ruta"] == 1 and r.data["resultado"]["reprogramados_fallidos"] == 1
        sin_ruta.refresh_from_db()
        assert sin_ruta.estado == "REPROGRAMADO" and sin_ruta.fecha_programada == HOY() + timedelta(days=1)
        correo = mail.outbox[-1]
        assert "Cierre del día" in correo.subject and correo.attachments[0][2] == "application/pdf"
        assert api_cond.post("/api/reportes/cierre-diario/", {}, format="json").status_code == 403
        assert api_sup.post("/api/reportes/cierre-diario/", {"fecha": "ayer"}, format="json").status_code == 400

    def test_tarea_en_cola_cuando_no_es_inmediata(self, api_sup, settings, monkeypatch):
        from apps.logistica import tasks
        settings.CELERY_TASK_ALWAYS_EAGER = False
        monkeypatch.setattr(tasks.cierre_diario, "delay", lambda *a: type("R", (), {"id": "abc-123"})())
        r = api_sup.post("/api/reportes/cierre-diario/", {}, format="json")
        assert r.status_code == 202 and r.data["tarea"] == "abc-123"

    def test_en_segundo_plano_ejecuta_si_la_cola_falla(self, monkeypatch):
        from apps.logistica import tasks
        llamado = {}
        monkeypatch.setattr(tasks.enviar_correo_cierre, "delay", lambda *a: (_ for _ in ()).throw(ConnectionError()))
        monkeypatch.setattr(tasks, "notificar_cierre", lambda rid: llamado.setdefault("ruta", rid), raising=False)
        resultado = tasks.en_segundo_plano(tasks.enviar_correo_cierre, 7)
        assert resultado == {"ruta": 7}

    def test_comando_cierre_diario(self, crear_pedido):
        from django.core.management import call_command
        crear_pedido()
        call_command("cierre_diario")
        assert not PedidoDespacho.objects.filter(estado="PENDIENTE").exists()
