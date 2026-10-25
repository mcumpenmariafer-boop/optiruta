"""
python manage.py cargar_demo [--reset]

Crea usuarios, zonas de Chiclayo, flota, puntos de entrega, pedidos de hoy y 14 días de
historial (rutas cerradas con KPIs) para que los reportes tengan datos desde el primer día.
"""
import random
from datetime import datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction
from django.test import override_settings
from django.utils import timezone

from apps.cuentas.models import Usuario
from types import SimpleNamespace

from apps.logistica import servicios
from apps.logistica.excepciones import ReglaNegocioError, registrar_intento
from apps.logistica.models import (Conductor, EventoRuta, IndicadorRuta, ParadaRuta, PedidoDespacho,
                                   PosicionVehiculo, PuntoEntrega, Ruta, Vehiculo, Zona)

CLAVE_DEMO = "Optiruta2026"

ZONAS = [
    ("Z01", "Chiclayo Centro", "#2F80ED", -6.7718, -79.8405, 0.007,
     ["Av. José Balta", "Calle Elías Aguirre", "Av. Luis Gonzales", "Calle San José", "Calle 7 de Enero"]),
    ("Z02", "José Leonardo Ortiz", "#9B51E0", -6.7555, -79.8460, 0.008,
     ["Av. Sáenz Peña", "Av. Chiclayo", "Calle Los Incas", "Av. Mesones Muro", "Calle Kennedy"]),
    ("Z03", "La Victoria", "#27AE60", -6.7915, -79.8375, 0.008,
     ["Av. Haya de la Torre", "Calle Los Lirios", "Av. Chinchaysuyo", "Av. Grau", "Calle Las Dalias"]),
    ("Z04", "Chiclayo Oeste", "#F2994A", -6.7800, -79.8600, 0.006,
     ["Av. Pedro Ruiz", "Av. Bolognesi", "Calle Las Palmeras", "Av. Francisco Cabrera", "Calle Huáscar"]),
    ("Z05", "Pimentel", "#EB5757", -6.8360, -79.9320, 0.006,
     ["Malecón Seoane", "Calle Quiñones", "Av. Chiclayo (Pimentel)", "Calle Leguía", "Calle Bolívar"]),
    ("Z06", "Lambayeque", "#D4A017", -6.7020, -79.9060, 0.007,
     ["Av. Ramón Castilla", "Calle 2 de Mayo", "Calle Atahualpa", "Av. Huamachuco", "Calle Bolívar"]),
]

NEGOCIOS = ["Bodega", "Minimarket", "Farmacia", "Ferretería", "Panadería", "Librería", "Botica",
            "Market", "Distribuidora", "Restaurante", "Juguería", "Comercial"]
NOMBRES = ["Don Lucho", "Santa Rosa", "El Sol", "La Esperanza", "Mi Perú", "San Martín", "El Chalán",
           "Los Andes", "Rosita", "El Norteño", "Señor de Sipán", "La Muña", "Chiclayito", "Virgen del Carmen",
           "El Progreso", "Mochica", "Sabor Norteño", "La Económica", "Nueva Era", "El Algarrobo"]
REFERENCIAS = ["Frente al parque", "Al costado de la iglesia", "Esquina con semáforo", "Portón verde",
               "Cerca al mercado", "Altura del colegio", "Fachada amarilla", "Junto a la comisaría", ""]
VENTANAS = [(time(8, 30), time(10, 30)), (time(9, 0), time(11, 0)), (time(10, 0), time(12, 0)),
            (time(11, 0), time(13, 0)), (time(14, 0), time(16, 0)), (time(15, 0), time(17, 30))]
MOTIVOS_FALLO = ["Cliente ausente", "Dirección incorrecta", "Local cerrado", "Cliente rechazó el pedido"]


class Command(BaseCommand):
    help = "Carga datos de demostración de OptiRuta"

    def add_arguments(self, parser):
        parser.add_argument("--reset", action="store_true", help="Borra los datos existentes antes de cargar")
        parser.add_argument("--dias", type=int, default=14, help="Días de historial (default 14)")

    def handle(self, *args, **opts):
        self.rnd = random.Random(2026)
        with override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend"):
            with transaction.atomic():
                if opts["reset"]:
                    self._borrar()
                if Zona.objects.exists():
                    self.stdout.write(self.style.WARNING("Ya hay datos. Usa --reset para recargar."))
                    return
                self._usuarios()
                self._zonas_y_puntos()
                self._flota()
                self._historial(opts["dias"])
                self._hoy()
                self._intentos_bloqueados()
        self.stdout.write(self.style.SUCCESS(
            f"Datos cargados. Usuarios: admin, supervisor, conductor1..4 — clave: {CLAVE_DEMO}"
        ))

    # ------------------------------------------------------------------
    def _borrar(self):
        for modelo in (EventoRuta, PosicionVehiculo, IndicadorRuta, ParadaRuta, Ruta, PedidoDespacho,
                       PuntoEntrega, Vehiculo, Conductor, Zona):
            modelo.objects.all().delete()
        Usuario.objects.filter(is_superuser=False).delete()
        Usuario.objects.filter(username="admin").delete()

    def _usuarios(self):
        self.admin = Usuario.objects.create_superuser(
            "admin", "admin@optiruta.pe", CLAVE_DEMO, first_name="Administrador", last_name="General",
            rol=Usuario.Rol.ADMIN)
        self.supervisor = Usuario.objects.create_user(
            "supervisor", "supervisor@optiruta.pe", CLAVE_DEMO, first_name="Lucía", last_name="Ramos Vílchez",
            rol=Usuario.Rol.SUPERVISOR, telefono="987654321")
        self.conductores = []
        datos = [("Juan", "Pérez Saavedra", "Q45128763"), ("Carlos", "Díaz Chumán", "Q41873925"),
                 ("Rosa", "Quispe Llontop", "Q47265183"), ("Miguel", "Sánchez Ñiquen", "Q43918276")]
        for i, (nom, ape, lic) in enumerate(datos, start=1):
            u = Usuario.objects.create_user(f"conductor{i}", f"conductor{i}@optiruta.pe", CLAVE_DEMO,
                                            first_name=nom, last_name=ape, rol=Usuario.Rol.CONDUCTOR)
            self.conductores.append(Conductor.objects.create(usuario=u, licencia=lic, celular=f"9{self.rnd.randint(10000000, 99999999)}"))

    def _zonas_y_puntos(self):
        self.puntos = []
        for codigo, nombre, color, lat, lng, radio, calles in ZONAS:
            zona = Zona.objects.create(codigo=codigo, nombre=nombre, color=color, centro_lat=lat, centro_lng=lng)
            cantidad = 8 if codigo in ("Z05", "Z06") else 14
            for _ in range(cantidad):
                self.puntos.append(PuntoEntrega.objects.create(
                    cliente_nombre=f"{self.rnd.choice(NEGOCIOS)} {self.rnd.choice(NOMBRES)}",
                    direccion=f"{self.rnd.choice(calles)} {self.rnd.randint(1, 18) * 50 + self.rnd.randint(0, 49)}",
                    referencia=self.rnd.choice(REFERENCIAS),
                    zona=zona,
                    latitud=round(lat + self.rnd.uniform(-radio, radio), 6),
                    longitud=round(lng + self.rnd.uniform(-radio, radio), 6),
                    telefono=f"9{self.rnd.randint(10000000, 99999999)}",
                ))

    def _flota(self):
        specs = [("CNX-101", "FURGONETA", 1200, 60), ("B7W-882", "FURGONETA", 1000, 50),
                 ("T3K-450", "CAMION", 3500, 150), ("M1A-123", "MOTO", 120, 8)]
        self.vehiculos = []
        for (placa, tipo, kg, bultos), conductor in zip(specs, self.conductores):
            self.vehiculos.append(Vehiculo.objects.create(
                placa=placa, tipo=tipo, capacidad_kg=kg, capacidad_bultos=bultos, conductor=conductor,
                ultima_lat=settings.OPTIRUTA["DEPOSITO_LAT"], ultima_lng=settings.OPTIRUTA["DEPOSITO_LNG"],
            ))

    def _crear_pedido(self, fecha, zonas=None, moto=False):
        candidatos = [p for p in self.puntos if not zonas or p.zona.codigo in zonas]
        r = self.rnd.random()
        prioridad = "URGENTE" if r < 0.15 else "ALTA" if r < 0.40 else "NORMAL"
        ventana = self.rnd.choice(VENTANAS) if self.rnd.random() < 0.35 else (None, None)
        return PedidoDespacho.objects.create(
            punto_entrega=self.rnd.choice(candidatos),
            descripcion=self.rnd.choice(["Abarrotes", "Bebidas", "Productos de limpieza", "Medicamentos",
                                         "Útiles", "Lácteos", "Snacks"]),
            peso_kg=Decimal(str(round(self.rnd.uniform(2, 12) if moto else self.rnd.uniform(8, 110), 1))),
            bultos=1 if moto else self.rnd.randint(1, 6),
            prioridad=prioridad, ventana_inicio=ventana[0], ventana_fin=ventana[1], fecha_programada=fecha,
        )

    def _historial(self, dias):
        hoy = timezone.localdate()
        zonas_por_vehiculo = [["Z01", "Z04"], ["Z02", "Z06"], ["Z03", "Z05"], ["Z01", "Z03"]]
        for d in range(dias, 0, -1):
            fecha = hoy - timedelta(days=d)
            if fecha.weekday() == 6:  # domingo no se reparte
                continue
            for vehiculo, zonas in zip(self.vehiculos, zonas_por_vehiculo):
                es_moto = vehiculo.tipo == "MOTO"
                n = self.rnd.randint(4, 6) if es_moto else self.rnd.randint(8, 13)
                pedidos = [self._crear_pedido(fecha, zonas, es_moto) for _ in range(n)]
                while (sum(p.peso_kg for p in pedidos) > vehiculo.capacidad_kg
                       or sum(p.bultos for p in pedidos) > vehiculo.capacidad_bultos):
                    pedidos.pop().delete()
                ruta = servicios.planificar_ruta(vehiculo, [p.id for p in pedidos], fecha, self.supervisor)
                servicios.iniciar_ruta(ruta, vehiculo.conductor.usuario)
                for parada in ruta.paradas.order_by("orden"):
                    parada.refresh_from_db()
                    if parada.estado == "PENDIENTE":
                        servicios.cambiar_estado_parada(parada, "EN_CAMINO", vehiculo.conductor.usuario)
                    r = self.rnd.random()
                    estado, obs = ("ENTREGADO", "") if r < 0.88 else \
                        ("FALLIDO", self.rnd.choice(MOTIVOS_FALLO)) if r < 0.96 else \
                        ("REPROGRAMADO", "Cliente pidió otro día")
                    servicios.cambiar_estado_parada(parada, estado, vehiculo.conductor.usuario, obs)
                servicios.cerrar_ruta(ruta, vehiculo.conductor.usuario)
                # Ajustar horas y km reales para que el historial sea realista
                inicio = timezone.make_aware(datetime.combine(fecha, time(8, self.rnd.randint(0, 20))))
                ruta.hora_inicio = inicio
                ruta.hora_fin = inicio + timedelta(minutes=int(ruta.minutos_estimados * self.rnd.uniform(1.0, 1.25)))
                ruta.km_reales = (ruta.km_estimados * Decimal(str(round(self.rnd.uniform(1.02, 1.12), 2)))).quantize(Decimal("0.01"))
                ruta.save(update_fields=["hora_inicio", "hora_fin", "km_reales"])
                servicios.calcular_indicadores(ruta)
                for parada in ruta.paradas.all():
                    if parada.hora_estimada:
                        parada.hora_real = timezone.make_aware(datetime.combine(fecha, parada.hora_estimada)) \
                            + timedelta(minutes=self.rnd.randint(-5, 20))
                        parada.save(update_fields=["hora_real"])
        # los reprogramados del historial pasan a hoy
        PedidoDespacho.objects.filter(estado="REPROGRAMADO").update(fecha_programada=hoy)

    def _hoy(self):
        hoy = timezone.localdate()
        # Una ruta en curso para ver el seguimiento en vivo en el mapa
        vehiculo = self.vehiculos[0]
        pedidos = [self._crear_pedido(hoy, ["Z01", "Z04"]) for _ in range(9)]
        ruta = servicios.planificar_ruta(vehiculo, [p.id for p in pedidos], hoy, self.supervisor)
        servicios.iniciar_ruta(ruta, vehiculo.conductor.usuario)
        usuario = vehiculo.conductor.usuario
        for parada in list(ruta.paradas.order_by("orden"))[:3]:
            parada.refresh_from_db()
            servicios.cambiar_estado_parada(parada, "ENTREGADO", usuario)
        actual = ruta.paradas.filter(estado="EN_CAMINO").select_related("pedido__punto_entrega").first()
        anterior = ruta.paradas.get(orden=3).pedido.punto_entrega
        if actual:
            destino = actual.pedido.punto_entrega
            for t in (0.0, 0.35, 0.6):
                servicios.registrar_posicion(
                    vehiculo, anterior.latitud + (destino.latitud - anterior.latitud) * t,
                    anterior.longitud + (destino.longitud - anterior.longitud) * t, usuario, 24.0)
        # Pedidos pendientes para planificar en la demo
        for _ in range(32):
            self._crear_pedido(hoy)
        for _ in range(4):
            self._crear_pedido(hoy + timedelta(days=1))

    def _intentos_bloqueados(self):
        """Simula operaciones indebidas para que el registro de intentos bloqueados tenga ejemplos."""
        hoy = timezone.localdate()
        ruta = Ruta.objects.get(estado="EN_CURSO")
        chofer = ruta.vehiculo.conductor.usuario
        otro = self.vehiculos[1].conductor.usuario
        pendiente = ruta.paradas.filter(estado="PENDIENTE").order_by("-orden").first()
        libres = list(PedidoDespacho.objects.filter(estado="PENDIENTE", fecha_programada=hoy)[:12])
        intentos = [
            (self.supervisor, "POST /api/rutas/planificar/",
             lambda: servicios.planificar_ruta(ruta.vehiculo, [libres[0].id], hoy, self.supervisor)),
            (self.supervisor, "POST /api/rutas/planificar/",
             lambda: servicios.planificar_ruta(self.vehiculos[3], [p.id for p in libres[:8]], hoy, self.supervisor)),
            (chofer, f"POST /api/rutas/{ruta.id}/cerrar/", lambda: servicios.cerrar_ruta(ruta, chofer)),
            (chofer, f"PATCH /api/paradas/{pendiente.id}/estado/",
             lambda: servicios.cambiar_estado_parada(pendiente, "EN_CAMINO", chofer)),
            (chofer, f"PATCH /api/paradas/{pendiente.id}/estado/",
             lambda: servicios.cambiar_estado_parada(ruta.paradas.get(estado="EN_CAMINO"), "FALLIDO", chofer, "")),
            (otro, f"POST /api/rutas/{ruta.id}/iniciar/", lambda: servicios.iniciar_ruta(ruta, otro)),
            (chofer, f"PATCH /api/paradas/{ruta.paradas.get(orden=1).id}/estado/",
             lambda: servicios.cambiar_estado_parada(ruta.paradas.get(orden=1), "FALLIDO", chofer, "Ya estaba entregado")),
        ]
        for usuario, endpoint, accion in intentos:
            metodo, ruta_url = endpoint.split(" ", 1)
            try:
                accion()
            except ReglaNegocioError as e:
                registrar_intento(e, SimpleNamespace(method=metodo, path=ruta_url, user=usuario))
