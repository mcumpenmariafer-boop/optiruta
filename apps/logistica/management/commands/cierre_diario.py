"""python manage.py cierre_diario [--fecha AAAA-MM-DD] [--cola]  — ejecuta el cierre del día."""
from django.core.management.base import BaseCommand

from apps.logistica.tasks import cierre_diario


class Command(BaseCommand):
    help = "Reprograma los pedidos no entregados y envía el resumen del día con el PDF"

    def add_arguments(self, parser):
        parser.add_argument("--fecha", help="Día a cerrar (por defecto, hoy)")
        parser.add_argument("--cola", action="store_true", help="Enviar a la cola de Celery en vez de ejecutar aquí")

    def handle(self, *args, **opts):
        if opts["cola"]:
            envio = cierre_diario.delay(opts["fecha"])
            self.stdout.write(self.style.SUCCESS(f"Tarea encolada: {envio.id}"))
            return
        resultado = cierre_diario(opts["fecha"])
        self.stdout.write(self.style.SUCCESS(f"Cierre listo: {resultado}"))
