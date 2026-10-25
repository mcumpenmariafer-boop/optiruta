"""
Reportes y KPIs (GET /api/reportes/eficiencia/, /api/reportes/resumen/).

Indicadores calculados:
    % entrega           = entregados / asignados × 100
    km promedio/ruta    = Σ km / n_rutas
    pedidos/vehículo    = entregados / vehículos con ruta
    ahorro km           = Σ (km_manual − km_optimizado)
    ahorro %            = ahorro_km / Σ km_manual × 100
    CO2 evitado         = Σ litros_ahorrados × factor de emisión
"""
import csv
from datetime import date, timedelta

from django.core.cache import cache
from django.db.models import Count, F, Q, Sum
from django.http import HttpResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response

from apps.cuentas.permisos import EsSupervisorOAdmin
from apps.logistica.excepciones import ReglaNegocioError
from apps.logistica.models import IndicadorRuta, ParadaRuta, PedidoDespacho, Ruta, Vehiculo
from apps.optimizacion.metricas import porcentaje

CACHE_SEGUNDOS = 30


def _rango(request):
    fecha = request.query_params.get("fecha")
    desde = request.query_params.get("desde")
    hasta = request.query_params.get("hasta")
    try:
        if fecha:
            d = parse_date(fecha)
            if d is None:
                raise ValueError
            return d, d
        hoy = timezone.localdate()
        d1 = parse_date(desde) if desde else hoy - timedelta(days=6)
        d2 = parse_date(hasta) if hasta else hoy
        if d1 is None or d2 is None:
            raise ValueError
    except ValueError:
        raise ReglaNegocioError("Formato de fecha inválido; usa AAAA-MM-DD.", "fecha_invalida")
    if d1 > d2:
        raise ReglaNegocioError("La fecha 'desde' no puede ser posterior a 'hasta'.", "rango_invalido")
    if (d2 - d1).days > 366:
        raise ReglaNegocioError("El rango máximo es de un año.", "rango_invalido")
    return d1, d2


def _f(valor):
    return round(float(valor or 0), 2)


def calcular_eficiencia(desde: date, hasta: date, vehiculo_id=None):
    indicadores = IndicadorRuta.objects.filter(ruta__fecha__range=(desde, hasta))
    if vehiculo_id:
        indicadores = indicadores.filter(ruta__vehiculo_id=vehiculo_id)

    tot = indicadores.aggregate(
        rutas=Count("id"), asignados=Sum("pedidos_asignados"), entregados=Sum("pedidos_entregados"),
        fallidos=Sum("pedidos_fallidos"), reprogramados=Sum("pedidos_reprogramados"),
        km=Sum("km"), km_manual=Sum("km_sin_optimizar"), ahorro_km=Sum("ahorro_km"),
        soles=Sum("ahorro_soles"), co2=Sum("co2_evitado_kg"), minutos=Sum("tiempo_min"),
        vehiculos=Count("ruta__vehiculo", distinct=True),
    )
    rutas = tot["rutas"] or 0
    resumen = {
        "rutas_cerradas": rutas,
        "pedidos_asignados": tot["asignados"] or 0,
        "pedidos_entregados": tot["entregados"] or 0,
        "pedidos_fallidos": tot["fallidos"] or 0,
        "pedidos_reprogramados": tot["reprogramados"] or 0,
        "porcentaje_entrega": porcentaje(tot["entregados"] or 0, tot["asignados"] or 0),
        "km_recorridos": _f(tot["km"]),
        "km_sin_optimizar": _f(tot["km_manual"]),
        "ahorro_km": _f(tot["ahorro_km"]),
        "ahorro_pct": porcentaje(float(tot["ahorro_km"] or 0), float(tot["km_manual"] or 0)),
        "ahorro_soles": _f(tot["soles"]),
        "co2_evitado_kg": _f(tot["co2"]),
        "km_promedio_ruta": round(float(tot["km"] or 0) / rutas, 2) if rutas else 0,
        "tiempo_promedio_min": round((tot["minutos"] or 0) / rutas) if rutas else 0,
        "pedidos_por_vehiculo": round((tot["entregados"] or 0) / tot["vehiculos"], 1) if tot["vehiculos"] else 0,
    }

    por_vehiculo = []
    for fila in (indicadores.values("ruta__vehiculo__placa", "ruta__vehiculo__tipo",
                                    "ruta__vehiculo__conductor__usuario__first_name",
                                    "ruta__vehiculo__conductor__usuario__last_name")
                 .annotate(rutas=Count("id"), asignados=Sum("pedidos_asignados"),
                           entregados=Sum("pedidos_entregados"), km=Sum("km"),
                           ahorro_km=Sum("ahorro_km"), minutos=Sum("tiempo_min"))
                 .order_by("-entregados")):
        conductor = f'{fila["ruta__vehiculo__conductor__usuario__first_name"] or ""} ' \
                    f'{fila["ruta__vehiculo__conductor__usuario__last_name"] or ""}'.strip()
        por_vehiculo.append({
            "placa": fila["ruta__vehiculo__placa"],
            "tipo": fila["ruta__vehiculo__tipo"],
            "conductor": conductor or "-",
            "rutas": fila["rutas"],
            "asignados": fila["asignados"] or 0,
            "entregados": fila["entregados"] or 0,
            "porcentaje_entrega": porcentaje(fila["entregados"] or 0, fila["asignados"] or 0),
            "km": _f(fila["km"]),
            "ahorro_km": _f(fila["ahorro_km"]),
            "pedidos_por_hora": round((fila["entregados"] or 0) / (fila["minutos"] / 60), 2)
            if fila["minutos"] else 0,
        })

    por_dia = [
        {"fecha": f["ruta__fecha"], "entregados": f["entregados"] or 0, "asignados": f["asignados"] or 0,
         "km": _f(f["km"]), "km_sin_optimizar": _f(f["km_manual"]), "ahorro_km": _f(f["ahorro"])}
        for f in indicadores.values("ruta__fecha").annotate(
            entregados=Sum("pedidos_entregados"), asignados=Sum("pedidos_asignados"), km=Sum("km"),
            km_manual=Sum("km_sin_optimizar"), ahorro=Sum("ahorro_km"),
        ).order_by("ruta__fecha")
    ]

    paradas = ParadaRuta.objects.filter(ruta__fecha__range=(desde, hasta), ruta__estado="COMPLETADA")
    if vehiculo_id:
        paradas = paradas.filter(ruta__vehiculo_id=vehiculo_id)
    por_zona = [
        {"zona": z["pedido__punto_entrega__zona__nombre"], "color": z["pedido__punto_entrega__zona__color"],
         "total": z["total"], "entregados": z["entregados"],
         "porcentaje_entrega": porcentaje(z["entregados"], z["total"])}
        for z in paradas.values("pedido__punto_entrega__zona__nombre", "pedido__punto_entrega__zona__color")
        .annotate(total=Count("id"), entregados=Count("id", filter=Q(estado="ENTREGADO")))
        .order_by("-total")
    ]

    motivos_fallo = list(
        paradas.filter(estado="FALLIDO").exclude(observacion="")
        .values("observacion").annotate(total=Count("id")).order_by("-total")[:5]
    )

    return {
        "desde": desde, "hasta": hasta, "resumen": resumen, "por_vehiculo": por_vehiculo,
        "por_dia": por_dia, "por_zona": por_zona, "motivos_fallo": motivos_fallo,
    }


@extend_schema(responses=OpenApiTypes.OBJECT, parameters=[
    OpenApiParameter("fecha", OpenApiTypes.DATE), OpenApiParameter("desde", OpenApiTypes.DATE),
    OpenApiParameter("hasta", OpenApiTypes.DATE), OpenApiParameter("vehiculo", OpenApiTypes.INT),
    OpenApiParameter("formato", OpenApiTypes.STR, enum=["json", "csv", "pdf"])])
@api_view(["GET"])
@permission_classes([EsSupervisorOAdmin])
def eficiencia(request):
    """GET /api/reportes/eficiencia/?fecha=  (o ?desde=&hasta=&vehiculo=&formato=csv|pdf)"""
    desde, hasta = _rango(request)
    vehiculo = request.query_params.get("vehiculo") or None
    clave = f"eficiencia:{desde}:{hasta}:{vehiculo}"
    datos = cache.get(clave)
    if datos is None:
        datos = calcular_eficiencia(desde, hasta, vehiculo)
        cache.set(clave, datos, CACHE_SEGUNDOS)

    if request.query_params.get("formato") == "pdf":
        from .pdf import reporte_eficiencia
        nombre = None
        if vehiculo:
            v = Vehiculo.objects.filter(pk=vehiculo).first()
            nombre = v.placa if v else None
        respuesta = HttpResponse(reporte_eficiencia(datos, nombre), content_type="application/pdf")
        respuesta["Content-Disposition"] = f'attachment; filename="eficiencia_{desde}_{hasta}.pdf"'
        return respuesta
    if request.query_params.get("formato") == "csv":
        respuesta = HttpResponse(content_type="text/csv; charset=utf-8")
        respuesta["Content-Disposition"] = f'attachment; filename="eficiencia_{desde}_{hasta}.csv"'
        respuesta.write("﻿")  # BOM para que Excel lea las tildes
        escritor = csv.writer(respuesta, delimiter=";")
        escritor.writerow(["Placa", "Tipo", "Conductor", "Rutas", "Asignados", "Entregados", "% Entrega",
                           "Km", "Ahorro km", "Pedidos/hora"])
        for v in datos["por_vehiculo"]:
            escritor.writerow([v["placa"], v["tipo"], v["conductor"], v["rutas"], v["asignados"],
                               v["entregados"], v["porcentaje_entrega"], v["km"], v["ahorro_km"],
                               v["pedidos_por_hora"]])
        return respuesta
    return Response(datos)


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([EsSupervisorOAdmin])
def resumen(request):
    """GET /api/reportes/resumen/ — tarjetas del dashboard (hoy + mes)."""
    hoy = timezone.localdate()
    pedidos_hoy = PedidoDespacho.objects.filter(fecha_programada=hoy)
    por_estado = dict(pedidos_hoy.values_list("estado").annotate(n=Count("id")))
    rutas_hoy = Ruta.objects.filter(fecha=hoy).exclude(estado="CANCELADA")
    mes = IndicadorRuta.objects.filter(ruta__fecha__year=hoy.year, ruta__fecha__month=hoy.month).aggregate(
        ahorro_km=Sum("ahorro_km"), co2=Sum("co2_evitado_kg"), soles=Sum("ahorro_soles"),
        entregados=Sum("pedidos_entregados"), asignados=Sum("pedidos_asignados"),
    )
    paradas_hoy = ParadaRuta.objects.filter(ruta__fecha=hoy).exclude(ruta__estado="CANCELADA")
    entregados_hoy = paradas_hoy.filter(estado="ENTREGADO").count()
    cerradas_hoy = paradas_hoy.filter(estado__in=["ENTREGADO", "FALLIDO", "REPROGRAMADO"]).count()
    vehiculos = Vehiculo.objects.all()
    en_ruta = vehiculos.filter(rutas__estado="EN_CURSO").distinct().count()
    pendientes = PedidoDespacho.objects.filter(estado__in=["PENDIENTE", "REPROGRAMADO"],
                                               fecha_programada__lte=hoy)
    return Response({
        "fecha": hoy,
        "pedidos_hoy": pedidos_hoy.count(),
        "pedidos_por_estado": por_estado,
        "pendientes_sin_asignar": pendientes.count(),
        "urgentes_sin_asignar": pendientes.filter(prioridad="URGENTE").count(),
        "rutas_hoy": rutas_hoy.count(),
        "rutas_en_curso": rutas_hoy.filter(estado="EN_CURSO").count(),
        "rutas_completadas": rutas_hoy.filter(estado="COMPLETADA").count(),
        "entregas_hoy": entregados_hoy,
        "porcentaje_entrega_hoy": porcentaje(entregados_hoy, cerradas_hoy),
        "km_planificados_hoy": _f(rutas_hoy.aggregate(s=Sum("km_estimados"))["s"]),
        "km_ahorrados_hoy": _f(rutas_hoy.aggregate(s=Sum(F("km_sin_optimizar") - F("km_estimados")))["s"]),
        "vehiculos_total": vehiculos.count(),
        "vehiculos_disponibles": vehiculos.filter(disponible=True).exclude(
            rutas__estado__in=["PLANIFICADA", "EN_CURSO"]).count(),
        "vehiculos_en_ruta": en_ruta,
        "mes": {
            "ahorro_km": _f(mes["ahorro_km"]),
            "co2_evitado_kg": _f(mes["co2"]),
            "ahorro_soles": _f(mes["soles"]),
            "porcentaje_entrega": porcentaje(mes["entregados"] or 0, mes["asignados"] or 0),
            "hojas_papel_evitadas": (mes["asignados"] or 0) * 2,
        },
    })


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["POST"])
@permission_classes([EsSupervisorOAdmin])
def cierre_diario(request):
    """POST /api/reportes/cierre-diario/ — lanza ahora la tarea de Celery del cierre del día."""
    from django.conf import settings

    from apps.logistica.tasks import cierre_diario as tarea
    fecha = request.data.get("fecha") or timezone.localdate().isoformat()
    if parse_date(str(fecha)) is None:
        raise ReglaNegocioError("Formato de fecha inválido; usa AAAA-MM-DD.", "fecha_invalida")
    if settings.CELERY_TASK_ALWAYS_EAGER:
        return Response({"modo": "inmediato", "resultado": tarea.apply(args=[fecha]).get()})
    envio = tarea.delay(fecha)
    return Response({"modo": "segundo_plano", "tarea": envio.id,
                     "mensaje": "La tarea quedó en cola; el worker de Celery la ejecutará en segundos."},
                    status=status.HTTP_202_ACCEPTED)
