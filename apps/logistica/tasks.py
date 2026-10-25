"""
Tareas de Celery (Tema 8.4).

    cierre_diario           Programada todos los días a las 22:00 (ver CELERY_BEAT_SCHEDULE):
                            1. Reprograma para mañana los pedidos que no se entregaron hoy
                               (pendientes sin ruta y entregas fallidas).
                            2. Envía a supervisión el resumen del día con el reporte PDF adjunto.
    enviar_correo_cierre    Envía en segundo plano el correo de cierre de una ruta.
"""
import logging
from datetime import timedelta

from celery import shared_task
from django.core.mail import EmailMultiAlternatives
from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date

log = logging.getLogger("optiruta")


def en_segundo_plano(tarea, *args):
    """Encola la tarea; si la cola no está disponible, la ejecuta en el momento (nunca se pierde)."""
    try:
        return tarea.delay(*args)
    except Exception:
        log.warning("Cola de Celery no disponible; %s se ejecuta en línea", tarea.name)
        return tarea(*args)


@shared_task(name="apps.logistica.tasks.enviar_correo_cierre")
def enviar_correo_cierre(ruta_id):
    from .servicios import notificar_cierre
    notificar_cierre(ruta_id)
    return {"ruta": ruta_id}


@shared_task(name="apps.logistica.tasks.cierre_diario")
def cierre_diario(fecha=None):
    from apps.cuentas.models import Usuario
    from apps.reportes.pdf import reporte_eficiencia
    from apps.reportes.views import calcular_eficiencia

    from .models import ParadaRuta, PedidoDespacho

    dia = parse_date(fecha) if isinstance(fecha, str) else (fecha or timezone.localdate())
    manana = dia + timedelta(days=1)
    P = PedidoDespacho.Estado
    with transaction.atomic():
        # 1a. Pendientes del día (o atrasados) que nunca salieron a ruta
        sin_ruta = PedidoDespacho.objects.filter(estado__in=[P.PENDIENTE, P.REPROGRAMADO], fecha_programada__lte=dia)
        reprog_sin_ruta = sin_ruta.update(estado=P.REPROGRAMADO, fecha_programada=manana)
        # 1b. Entregas fallidas del día: vuelven a la bolsa para mañana
        fallidos = PedidoDespacho.objects.filter(
            estado=P.FALLIDO, paradas__ruta__fecha=dia, paradas__estado=ParadaRuta.Estado.FALLIDO).distinct()
        reprog_fallidos = PedidoDespacho.objects.filter(pk__in=list(fallidos.values_list("pk", flat=True))).update(
            estado=P.REPROGRAMADO, fecha_programada=manana)

    datos = calcular_eficiencia(dia, dia)
    r = datos["resumen"]
    resultado = {
        "fecha": dia.isoformat(),
        "reprogramados_sin_ruta": reprog_sin_ruta,
        "reprogramados_fallidos": reprog_fallidos,
        "rutas_cerradas": r["rutas_cerradas"],
        "entregados": r["pedidos_entregados"],
        "porcentaje_entrega": r["porcentaje_entrega"],
        "ahorro_km": r["ahorro_km"],
        "correo_enviado_a": [],
    }

    destinatarios = list(Usuario.objects.filter(rol__in=[Usuario.Rol.SUPERVISOR, Usuario.Rol.ADMIN], is_active=True)
                         .exclude(email="").values_list("email", flat=True))
    if destinatarios:
        texto = (
            f"Cierre automático del {dia:%d/%m/%Y}\n\n"
            f"Rutas cerradas: {r['rutas_cerradas']}\n"
            f"Entregas: {r['pedidos_entregados']} de {r['pedidos_asignados']} ({r['porcentaje_entrega']} %)\n"
            f"Km recorridos: {r['km_recorridos']} · ahorro por optimización: {r['ahorro_km']} km ({r['ahorro_pct']} %)\n"
            f"CO2 evitado: {r['co2_evitado_kg']} kg · combustible ahorrado: S/ {r['ahorro_soles']}\n\n"
            f"Reprogramados para mañana: {reprog_sin_ruta} sin ruta y {reprog_fallidos} con entrega fallida.\n"
            "Se adjunta el reporte de eficiencia en PDF."
        )
        correo = EmailMultiAlternatives(
            subject=f"[OptiRuta] Cierre del día {dia:%d/%m/%Y} — {r['porcentaje_entrega']} % entregado",
            body=texto, to=destinatarios)
        correo.attach(f"eficiencia_{dia.isoformat()}.pdf", reporte_eficiencia(datos), "application/pdf")
        correo.send(fail_silently=True)
        resultado["correo_enviado_a"] = destinatarios
    log.info("Cierre diario %s: %s", dia, resultado)
    return resultado
