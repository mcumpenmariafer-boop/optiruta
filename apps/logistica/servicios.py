"""
Capa de lógica de negocio (servicios).

Aquí viven TODAS las reglas críticas; las vistas de la API solo validan formato y delegan.

Reglas de negocio de la guía:
    RN1. Un vehículo no puede tener dos rutas activas al mismo tiempo.
    RN2. La suma de pesos (y bultos) de una ruta no puede superar la capacidad del vehículo.
    RN3. Los pedidos URGENTES tienen prioridad en el ordenamiento de paradas.
    RN4. La ruta no puede cerrarse si tiene paradas pendientes.
    RN5. Las ventanas horarias deben respetarse en el orden de paradas.
Reglas adicionales:
    RN6. Las paradas se atienden en el orden optimizado (solo la siguiente puede pasar a EN_CAMINO).
    RN7. Una parada FALLIDA o REPROGRAMADA exige observación.
    RN8. El conductor solo opera su propia ruta y su propio vehículo.
"""
import logging
from datetime import datetime, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from apps.cuentas.models import Usuario
from apps.optimizacion import asignacion, metricas, motor
from apps.optimizacion.geo import longitud_polilinea

from .excepciones import ReglaNegocioError
from .tiempo_real import publicar
from .models import (EventoRuta, IndicadorRuta, ParadaRuta, PedidoDespacho, PosicionVehiculo,
                     Ruta, Vehiculo)

log = logging.getLogger("optiruta")
P = PedidoDespacho.Estado
E = ParadaRuta.Estado

ESTADOS_PLANIFICABLES = (P.PENDIENTE, P.REPROGRAMADO)

TRANSICIONES_PARADA = {
    E.PENDIENTE: {E.EN_CAMINO, E.REPROGRAMADO},
    E.EN_CAMINO: {E.ENTREGADO, E.FALLIDO, E.REPROGRAMADO},
    E.ENTREGADO: set(),
    E.FALLIDO: set(),
    E.REPROGRAMADO: set(),
}


# ----------------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------------
def configuracion(hora_inicio=None):
    cfg = settings.OPTIRUTA
    return motor.Configuracion(
        deposito=(cfg["DEPOSITO_LAT"], cfg["DEPOSITO_LNG"]),
        velocidad_kmh=cfg["VELOCIDAD_KMH"],
        factor_circuito=cfg["FACTOR_CIRCUITO"],
        minutos_servicio=cfg["MINUTOS_SERVICIO"],
        hora_inicio=motor.a_minutos(hora_inicio or cfg["HORA_INICIO"]),
    )


def a_paradas(pedidos):
    return [
        motor.Parada(
            id=p.id, lat=p.punto_entrega.latitud, lng=p.punto_entrega.longitud,
            prioridad=p.prioridad, ventana_inicio=motor.a_minutos(p.ventana_inicio),
            ventana_fin=motor.a_minutos(p.ventana_fin), codigo=p.codigo,
        )
        for p in pedidos
    ]


def registrar_evento(ruta, tipo, descripcion, usuario=None, parada=None):
    EventoRuta.objects.create(ruta=ruta, tipo=tipo, descripcion=descripcion,
                              usuario=usuario, parada=parada)


def _es_gestion(usuario):
    return usuario.es_admin or usuario.es_supervisor


def _validar_capacidad(vehiculo, pedidos):
    maximo = settings.OPTIRUTA["MAX_PARADAS_RUTA"]
    if len(pedidos) > maximo:
        raise ReglaNegocioError(
            f"Una ruta admite como máximo {maximo} paradas por jornada ({len(pedidos)} seleccionadas).",
            codigo="demasiadas_paradas", detalle={"maximo": maximo, "seleccionadas": len(pedidos)},
        )
    items = [asignacion.ItemPedido(p.id, float(p.peso_kg), p.bultos) for p in pedidos]
    ok, peso, bultos = asignacion.validar_capacidad(
        items, float(vehiculo.capacidad_kg), vehiculo.capacidad_bultos
    )
    if not ok:
        raise ReglaNegocioError(
            f"La carga ({peso} kg, {bultos} bultos) supera la capacidad del vehículo "
            f"{vehiculo.placa} ({vehiculo.capacidad_kg} kg, {vehiculo.capacidad_bultos} bultos).",
            codigo="capacidad_excedida",
            detalle={"peso_kg": peso, "bultos": bultos,
                     "capacidad_kg": float(vehiculo.capacidad_kg),
                     "capacidad_bultos": vehiculo.capacidad_bultos},
        )
    return peso, bultos


def _validar_vehiculo(vehiculo):
    if not vehiculo.disponible:
        raise ReglaNegocioError(f"El vehículo {vehiculo.placa} no está disponible.", "vehiculo_no_disponible")
    if not vehiculo.conductor or not vehiculo.conductor.activo:
        raise ReglaNegocioError(f"El vehículo {vehiculo.placa} no tiene un conductor activo asignado.",
                                "sin_conductor")
    if Ruta.objects.filter(vehiculo=vehiculo, estado__in=Ruta.ESTADOS_ACTIVOS).exists():
        raise ReglaNegocioError(
            f"El vehículo {vehiculo.placa} ya tiene una ruta activa (RN1).",
            "vehiculo_con_ruta_activa", http=409,
        )


def _serializar_resultado(resultado, pedidos_por_id):
    return [
        {
            "pedido_id": pp.parada.id,
            "codigo": pp.parada.codigo,
            "orden": pp.orden,
            "lat": pp.parada.lat,
            "lng": pp.parada.lng,
            "prioridad": pp.parada.prioridad,
            "cliente": pedidos_por_id[pp.parada.id].punto_entrega.cliente_nombre,
            "distancia_km": pp.distancia_km,
            "hora_estimada": motor.a_hora(pp.inicio).strftime("%H:%M"),
            "espera_min": pp.espera,
            "tardanza_min": pp.tardanza,
        }
        for pp in resultado.secuencia
    ]


# ----------------------------------------------------------------------------
# Optimización y planificación
# ----------------------------------------------------------------------------
def previsualizar(vehiculo, pedidos, hora_inicio=None):
    """Calcula la ruta óptima SIN guardar nada (para la vista de planificación)."""
    pedidos = list(pedidos)
    if not pedidos:
        raise ReglaNegocioError("Selecciona al menos un pedido.", "sin_pedidos")
    peso, bultos = _validar_capacidad(vehiculo, pedidos)
    cfg = configuracion(hora_inicio)
    comp = motor.comparar(a_paradas(pedidos), cfg)
    por_id = {p.id: p for p in pedidos}
    precio = settings.OPTIRUTA["PRECIO_COMBUSTIBLE_LITRO"]
    return {
        "vehiculo": vehiculo.placa,
        "peso_kg": peso,
        "bultos": bultos,
        "uso_capacidad_pct": round(100 * peso / float(vehiculo.capacidad_kg), 1),
        "deposito": {"lat": cfg.deposito[0], "lng": cfg.deposito[1],
                     "nombre": settings.OPTIRUTA["DEPOSITO_NOMBRE"]},
        "optimizada": {
            "paradas": _serializar_resultado(comp["optima"], por_id),
            "km": comp["optima"].km_total,
            "minutos": comp["optima"].minutos_total,
            "ventanas_incumplidas": comp["optima"].ventanas_incumplidas,
        },
        "sin_optimizar": {
            "paradas": _serializar_resultado(comp["base"], por_id),
            "km": comp["base"].km_total,
            "minutos": comp["base"].minutos_total,
            "ventanas_incumplidas": comp["base"].ventanas_incumplidas,
        },
        "ahorro": {
            "km": comp["ahorro_km"], "pct": comp["ahorro_pct"], "minutos": comp["ahorro_min"],
            **metricas.impacto(comp["base"].km_total, comp["optima"].km_total, vehiculo.tipo, precio),
        },
        "iteraciones_2opt": comp["iteraciones_2opt"],
        "excede_jornada": comp["optima"].minutos_total > settings.OPTIRUTA["JORNADA_MAX_MIN"],
        "jornada_max_min": settings.OPTIRUTA["JORNADA_MAX_MIN"],
        "algoritmo": "Vecino más cercano con prioridad y ventanas + mejora 2-opt",
    }


@transaction.atomic
def planificar_ruta(vehiculo, pedido_ids, fecha, usuario, hora_inicio=None):
    """Crea una ruta optimizada (POST /api/rutas/planificar/)."""
    vehiculo = Vehiculo.objects.select_for_update(of=("self",)).select_related("conductor").get(pk=vehiculo.pk)
    _validar_vehiculo(vehiculo)

    pedidos = list(
        PedidoDespacho.objects.select_for_update()
        .select_related("punto_entrega")
        .filter(id__in=pedido_ids)
    )
    if len(pedidos) != len(set(pedido_ids)):
        raise ReglaNegocioError("Uno o más pedidos no existen.", "pedido_inexistente", http=404)
    no_libres = [p.codigo for p in pedidos if p.estado not in ESTADOS_PLANIFICABLES]
    if no_libres:
        raise ReglaNegocioError(
            f"Estos pedidos ya están asignados o cerrados: {', '.join(no_libres)}.",
            "pedido_no_disponible", http=409, detalle={"pedidos": no_libres},
        )
    if not pedidos:
        raise ReglaNegocioError("Selecciona al menos un pedido.", "sin_pedidos")

    peso, bultos = _validar_capacidad(vehiculo, pedidos)
    cfg = configuracion(hora_inicio)
    comp = motor.comparar(a_paradas(pedidos), cfg)
    optima = comp["optima"]

    ruta = Ruta.objects.create(
        vehiculo=vehiculo, fecha=fecha, creada_por=usuario,
        km_estimados=Decimal(str(optima.km_total)),
        km_sin_optimizar=Decimal(str(comp["base"].km_total)),
        minutos_estimados=optima.minutos_total,
        peso_total_kg=Decimal(str(peso)), bultos_total=bultos,
        capacidad_kg=vehiculo.capacidad_kg, capacidad_bultos=vehiculo.capacidad_bultos,
        secuencia=optima.ids,
    )
    ParadaRuta.objects.bulk_create([
        ParadaRuta(
            ruta=ruta, pedido_id=pp.parada.id, orden=pp.orden,
            distancia_km=Decimal(str(pp.distancia_km)),
            hora_estimada=motor.a_hora(pp.inicio),
        )
        for pp in optima.secuencia
    ])
    PedidoDespacho.objects.filter(id__in=optima.ids).update(estado=P.ASIGNADO, fecha_programada=fecha)
    registrar_evento(
        ruta, "PLANIFICADA",
        f"Ruta optimizada: {optima.km_total} km (manual: {comp['base'].km_total} km, "
        f"ahorro {comp['ahorro_pct']}%).", usuario,
    )
    log.info("Ruta %s planificada por %s", ruta.codigo, usuario)
    publicar("ruta", ruta=ruta.id, estado=ruta.estado, vehiculo=vehiculo.id)
    return ruta


@transaction.atomic
def planificar_automatico(fecha, usuario, zona_id=None):
    """
    Planificación de toda la flota: FFD reparte los pedidos pendientes del día entre los
    vehículos libres y luego cada ruta se secuencia con VMC + 2-opt.
    """
    pedidos = PedidoDespacho.objects.select_related("punto_entrega").filter(
        estado__in=ESTADOS_PLANIFICABLES, fecha_programada__lte=fecha
    )
    if zona_id:
        pedidos = pedidos.filter(punto_entrega__zona_id=zona_id)
    pedidos = list(pedidos)
    vehiculos = list(
        Vehiculo.objects.select_related("conductor").filter(
            disponible=True, conductor__isnull=False, conductor__activo=True
        ).exclude(rutas__estado__in=Ruta.ESTADOS_ACTIVOS)
    )
    if not pedidos:
        raise ReglaNegocioError("No hay pedidos pendientes para planificar.", "sin_pedidos")
    if not vehiculos:
        raise ReglaNegocioError("No hay vehículos libres con conductor.", "sin_vehiculos", http=409)

    items = [asignacion.ItemPedido(p.id, float(p.peso_kg), p.bultos, p.punto_entrega.zona_id, p.prioridad)
             for p in pedidos]
    maximo = settings.OPTIRUTA["MAX_PARADAS_RUTA"]
    contenedores = [asignacion.Contenedor(v.id, float(v.capacidad_kg), v.capacidad_bultos, maximo)
                    for v in vehiculos]
    llenos, sin_asignar = asignacion.asignar_ffd(items, contenedores)

    rutas = []
    por_id = {v.id: v for v in vehiculos}
    for c in llenos:
        if c.pedidos:
            rutas.append(planificar_ruta(por_id[c.id], c.pedidos, fecha, usuario))
    return rutas, [i.id for i in sin_asignar]


# ----------------------------------------------------------------------------
# Ejecución de la ruta
# ----------------------------------------------------------------------------
def _validar_dueno(ruta, usuario):
    if _es_gestion(usuario):
        return
    conductor = getattr(ruta.vehiculo, "conductor", None)
    if not conductor or conductor.usuario_id != usuario.id:
        raise ReglaNegocioError("Esta ruta no está asignada a ti (RN8).", "no_es_tu_ruta", http=403)


@transaction.atomic
def iniciar_ruta(ruta, usuario):
    ruta = Ruta.objects.select_for_update(of=("self",)).select_related("vehiculo__conductor").get(pk=ruta.pk)
    _validar_dueno(ruta, usuario)
    if ruta.estado != Ruta.Estado.PLANIFICADA:
        raise ReglaNegocioError(f"Solo se puede iniciar una ruta PLANIFICADA (está {ruta.estado}).",
                                "transicion_invalida", http=409)
    ruta.estado = Ruta.Estado.EN_CURSO
    ruta.hora_inicio = timezone.now()
    ruta.save(update_fields=["estado", "hora_inicio"])
    PedidoDespacho.objects.filter(paradas__ruta=ruta).update(estado=P.EN_RUTA)
    primera = ruta.paradas.order_by("orden").first()
    if primera:
        primera.estado = E.EN_CAMINO
        primera.save(update_fields=["estado"])
    registrar_evento(ruta, "INICIADA", "El conductor salió del almacén.", usuario)
    publicar("ruta", ruta=ruta.id, estado=ruta.estado, vehiculo=ruta.vehiculo_id)
    return ruta


@transaction.atomic
def cambiar_estado_parada(parada, nuevo_estado, usuario, observacion=""):
    """PATCH /api/paradas/{id}/estado/ con validación de transición."""
    parada = ParadaRuta.objects.select_for_update(of=("self",)).select_related(
        "ruta__vehiculo__conductor", "pedido").get(pk=parada.pk)
    ruta = parada.ruta
    _validar_dueno(ruta, usuario)
    observacion = (observacion or "").strip()

    if nuevo_estado not in E.values:
        raise ReglaNegocioError(f"Estado '{nuevo_estado}' no existe.", "estado_invalido")
    if ruta.estado != Ruta.Estado.EN_CURSO and not (
        nuevo_estado == E.REPROGRAMADO and ruta.estado == Ruta.Estado.PLANIFICADA and _es_gestion(usuario)
    ):
        raise ReglaNegocioError("La ruta debe estar EN CURSO para actualizar paradas.", "ruta_no_en_curso",
                                http=409)
    if nuevo_estado not in TRANSICIONES_PARADA[parada.estado]:
        permitidos = ", ".join(sorted(TRANSICIONES_PARADA[parada.estado])) or "ninguno (estado final)"
        raise ReglaNegocioError(
            f"Transición no permitida: {parada.estado} → {nuevo_estado}. Permitidos: {permitidos}.",
            "transicion_invalida", http=409,
        )
    if nuevo_estado in (E.FALLIDO, E.REPROGRAMADO) and len(observacion) < 5:
        raise ReglaNegocioError("Debes escribir una observación (mínimo 5 caracteres) (RN7).",
                                "observacion_requerida")
    if nuevo_estado == E.EN_CAMINO:
        if ruta.paradas.filter(estado=E.EN_CAMINO).exists():
            raise ReglaNegocioError("Ya hay una parada EN CAMINO; termínala primero.", "otra_en_camino", http=409)
        siguiente = ruta.paradas.filter(estado=E.PENDIENTE).order_by("orden").first()
        if siguiente and siguiente.pk != parada.pk:
            raise ReglaNegocioError(
                f"Respeta el orden optimizado: la siguiente parada es la #{siguiente.orden} (RN6).",
                "orden_no_respetado", http=409,
            )

    anterior = parada.estado
    parada.estado = nuevo_estado
    parada.observacion = observacion or parada.observacion
    if nuevo_estado in (E.ENTREGADO, E.FALLIDO, E.REPROGRAMADO):
        parada.hora_real = timezone.now()
    parada.save()  # la señal post_save sincroniza el estado del pedido
    registrar_evento(ruta, f"PARADA_{nuevo_estado}",
                     f"Parada #{parada.orden} ({parada.pedido.codigo}): {anterior} → {nuevo_estado}. "
                     f"{observacion}".strip(), usuario, parada)

    # Avance automático: al cerrar una parada, la siguiente pasa a EN_CAMINO
    if nuevo_estado in (E.ENTREGADO, E.FALLIDO, E.REPROGRAMADO) and ruta.estado == Ruta.Estado.EN_CURSO:
        siguiente = ruta.paradas.filter(estado=E.PENDIENTE).order_by("orden").first()
        if siguiente and not ruta.paradas.filter(estado=E.EN_CAMINO).exists():
            siguiente.estado = E.EN_CAMINO
            siguiente.save(update_fields=["estado"])
    publicar("parada", ruta=ruta.id, parada=parada.id, orden=parada.orden, estado=nuevo_estado)
    return parada


def calcular_indicadores(ruta):
    """Calcula y guarda los KPIs de la ruta (se ejecuta al cerrar)."""
    paradas = list(ruta.paradas.all())
    asignados = len(paradas)
    entregados = sum(1 for p in paradas if p.estado == E.ENTREGADO)
    fallidos = sum(1 for p in paradas if p.estado == E.FALLIDO)
    reprog = sum(1 for p in paradas if p.estado == E.REPROGRAMADO)
    km = float(ruta.km_reales if ruta.km_reales is not None else ruta.km_estimados)
    tiempo = 0
    if ruta.hora_inicio and ruta.hora_fin:
        tiempo = int((ruta.hora_fin - ruta.hora_inicio).total_seconds() // 60)
    base = float(ruta.km_sin_optimizar)
    imp = metricas.impacto(base, float(ruta.km_estimados), ruta.vehiculo.tipo,
                           settings.OPTIRUTA["PRECIO_COMBUSTIBLE_LITRO"])
    indicador, _ = IndicadorRuta.objects.update_or_create(
        ruta=ruta,
        defaults=dict(
            pedidos_asignados=asignados, pedidos_entregados=entregados,
            pedidos_fallidos=fallidos, pedidos_reprogramados=reprog,
            km=Decimal(str(round(km, 2))), tiempo_min=tiempo,
            porcentaje_entrega=Decimal(str(metricas.porcentaje(entregados, asignados))),
            km_sin_optimizar=Decimal(str(round(base, 2))),
            ahorro_km=Decimal(str(imp["ahorro_km"])),
            ahorro_pct=Decimal(str(metricas.porcentaje(imp["ahorro_km"], base))),
            ahorro_soles=Decimal(str(imp["ahorro_soles"])),
            co2_evitado_kg=Decimal(str(imp["co2_evitado_kg"])),
        ),
    )
    return indicador


@transaction.atomic
def cerrar_ruta(ruta, usuario):
    ruta = Ruta.objects.select_for_update(of=("self",)).select_related("vehiculo__conductor").get(pk=ruta.pk)
    _validar_dueno(ruta, usuario)
    if ruta.estado != Ruta.Estado.EN_CURSO:
        raise ReglaNegocioError("Solo se puede cerrar una ruta EN CURSO.", "transicion_invalida", http=409)
    abiertas = list(ruta.paradas.filter(estado__in=ParadaRuta.ESTADOS_ABIERTOS).values_list("orden", flat=True))
    if abiertas:
        raise ReglaNegocioError(
            f"No se puede cerrar: hay {len(abiertas)} parada(s) pendiente(s) (RN4).",
            "paradas_pendientes", http=409, detalle={"paradas": abiertas},
        )
    ruta.estado = Ruta.Estado.COMPLETADA
    ruta.hora_fin = timezone.now()
    puntos = list(ruta.posiciones.order_by("registrado").values_list("latitud", "longitud"))
    if len(puntos) >= 2:
        ruta.km_reales = Decimal(str(round(longitud_polilinea(puntos), 2)))
    ruta.save(update_fields=["estado", "hora_fin", "km_reales"])
    indicador = calcular_indicadores(ruta)
    registrar_evento(ruta, "CERRADA",
                     f"Ruta cerrada: {indicador.pedidos_entregados}/{indicador.pedidos_asignados} entregados.",
                     usuario)
    from .tasks import en_segundo_plano, enviar_correo_cierre
    transaction.on_commit(lambda: en_segundo_plano(enviar_correo_cierre, ruta.pk))   # Celery
    publicar("ruta", ruta=ruta.id, estado=ruta.estado, vehiculo=ruta.vehiculo_id)
    return ruta


@transaction.atomic
def cancelar_ruta(ruta, usuario, motivo=""):
    ruta = Ruta.objects.select_for_update().get(pk=ruta.pk)
    if not _es_gestion(usuario):
        raise ReglaNegocioError("Solo supervisión puede cancelar rutas.", "sin_permiso", http=403)
    if ruta.estado != Ruta.Estado.PLANIFICADA:
        raise ReglaNegocioError("Solo se pueden cancelar rutas PLANIFICADAS.", "transicion_invalida", http=409)
    if len(motivo.strip()) < 5:
        raise ReglaNegocioError("Indica el motivo de la cancelación.", "observacion_requerida")
    ruta.estado = Ruta.Estado.CANCELADA
    ruta.save(update_fields=["estado"])
    PedidoDespacho.objects.filter(paradas__ruta=ruta).update(estado=P.PENDIENTE)
    registrar_evento(ruta, "CANCELADA", motivo.strip(), usuario)
    publicar("ruta", ruta=ruta.id, estado=ruta.estado, vehiculo=ruta.vehiculo_id)
    return ruta


def registrar_posicion(vehiculo, latitud, longitud, usuario, velocidad=None):
    """POST /api/vehiculos/{id}/posicion/"""
    if usuario.es_conductor:
        conductor = getattr(vehiculo, "conductor", None)
        if not conductor or conductor.usuario_id != usuario.id:
            raise ReglaNegocioError("Solo puedes reportar la posición de tu vehículo (RN8).",
                                    "no_es_tu_vehiculo", http=403)
    ruta = vehiculo.rutas.filter(estado=Ruta.Estado.EN_CURSO).first()
    posicion = PosicionVehiculo.objects.create(
        vehiculo=vehiculo, ruta=ruta, latitud=latitud, longitud=longitud, velocidad_kmh=velocidad
    )
    vehiculo.ultima_lat, vehiculo.ultima_lng = latitud, longitud
    vehiculo.ultima_actualizacion = posicion.registrado
    vehiculo.save(update_fields=["ultima_lat", "ultima_lng", "ultima_actualizacion"])
    publicar("posicion", vehiculo=vehiculo.id, ruta=ruta.id if ruta else None,
             lat=latitud, lng=longitud, registrado=posicion.registrado.isoformat())
    return posicion


def reprogramar_pedido(pedido):
    """El pedido vuelve a la bolsa de pendientes para el día siguiente."""
    pedido.estado = P.REPROGRAMADO
    pedido.fecha_programada = pedido.fecha_programada + timedelta(days=1)
    pedido.save(update_fields=["estado", "fecha_programada"])


# ----------------------------------------------------------------------------
# Notificaciones por correo (Tema 5.2 / 5.3)
# ----------------------------------------------------------------------------
def notificar_cierre(ruta_id):
    try:
        ruta = Ruta.objects.select_related("vehiculo__conductor__usuario", "indicador").get(pk=ruta_id)
        destinatarios = list(
            Usuario.objects.filter(rol__in=[Usuario.Rol.SUPERVISOR, Usuario.Rol.ADMIN], is_active=True)
            .exclude(email="").values_list("email", flat=True)
        )
        if not destinatarios:
            return
        contexto = {"ruta": ruta, "kpi": ruta.indicador, "fecha": datetime.now()}
        send_mail(
            subject=f"[OptiRuta] Ruta {ruta.codigo} cerrada — {ruta.indicador.porcentaje_entrega}% entregado",
            message=render_to_string("correos/cierre_ruta.txt", contexto),
            html_message=render_to_string("correos/cierre_ruta.html", contexto),
            from_email=None, recipient_list=destinatarios, fail_silently=True,
        )
    except Exception:  # el correo nunca debe romper la operación
        log.exception("No se pudo enviar el correo de cierre de la ruta %s", ruta_id)
