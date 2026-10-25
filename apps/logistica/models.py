"""
Modelo de datos de OptiRuta.

Entidades de la guía: Vehiculo, Conductor, PuntoEntrega, PedidoDespacho, Ruta, ParadaRuta,
IndicadorRuta. Entidades adicionales: Zona, PosicionVehiculo (rastreo GPS) y EventoRuta
(bitácora para trazabilidad).
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q

validar_placa = RegexValidator(
    r"^[A-Z0-9]{3}-[0-9]{3}$", "La placa debe tener el formato ABC-123 (mayúsculas)."
)
validar_licencia = RegexValidator(
    r"^[A-Z][0-9]{8}$", "La licencia debe ser una letra seguida de 8 dígitos (ej. Q12345678)."
)
validar_celular = RegexValidator(
    r"^9[0-9]{8}$", "El celular peruano (+51) debe tener 9 dígitos y empezar con 9 (ej. 987654321)."
)
validar_color = RegexValidator(r"^#[0-9A-Fa-f]{6}$", "Color hexadecimal, ej. #2F80ED.")
LATITUD = [MinValueValidator(-90), MaxValueValidator(90)]
LONGITUD = [MinValueValidator(-180), MaxValueValidator(180)]


class Prioridad(models.TextChoices):
    URGENTE = "URGENTE", "Urgente"
    ALTA = "ALTA", "Alta"
    NORMAL = "NORMAL", "Normal"


class Zona(models.Model):
    codigo = models.CharField(max_length=10, unique=True)
    nombre = models.CharField(max_length=80)
    color = models.CharField(max_length=7, default="#2F80ED", validators=[validar_color])
    centro_lat = models.FloatField(validators=LATITUD)
    centro_lng = models.FloatField(validators=LONGITUD)

    class Meta:
        ordering = ["nombre"]

    def __str__(self):
        return self.nombre


class Conductor(models.Model):
    usuario = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="conductor"
    )
    licencia = models.CharField(max_length=9, unique=True, validators=[validar_licencia])
    celular = models.CharField(max_length=9, validators=[validar_celular])
    activo = models.BooleanField(default=True)

    class Meta:
        verbose_name_plural = "conductores"

    def __str__(self):
        return str(self.usuario)


class Vehiculo(models.Model):
    class Tipo(models.TextChoices):
        MOTO = "MOTO", "Motocicleta"
        FURGONETA = "FURGONETA", "Furgoneta"
        CAMION = "CAMION", "Camión"

    placa = models.CharField(max_length=7, unique=True, validators=[validar_placa])
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    capacidad_kg = models.DecimalField(max_digits=8, decimal_places=2)
    capacidad_bultos = models.PositiveIntegerField()
    conductor = models.OneToOneField(
        Conductor, on_delete=models.SET_NULL, null=True, blank=True, related_name="vehiculo"
    )
    disponible = models.BooleanField(default=True)
    # Última posición conocida (cache para el mapa; el historial está en PosicionVehiculo)
    ultima_lat = models.FloatField(null=True, blank=True, validators=LATITUD)
    ultima_lng = models.FloatField(null=True, blank=True, validators=LONGITUD)
    ultima_actualizacion = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["placa"]
        constraints = [
            models.CheckConstraint(condition=Q(capacidad_kg__gt=0), name="vehiculo_capacidad_kg_positiva"),
            models.CheckConstraint(condition=Q(capacidad_bultos__gt=0), name="vehiculo_capacidad_bultos_positiva"),
        ]

    def __str__(self):
        return f"{self.placa} ({self.get_tipo_display()})"


class PuntoEntrega(models.Model):
    cliente_nombre = models.CharField(max_length=120)
    direccion = models.CharField(max_length=200)
    referencia = models.CharField(max_length=200, blank=True)
    zona = models.ForeignKey(Zona, on_delete=models.PROTECT, related_name="puntos")
    latitud = models.FloatField(validators=LATITUD)
    longitud = models.FloatField(validators=LONGITUD)
    telefono = models.CharField(max_length=9, blank=True, validators=[validar_celular])
    email = models.EmailField(blank=True)

    class Meta:
        verbose_name = "punto de entrega"
        verbose_name_plural = "puntos de entrega"
        indexes = [models.Index(fields=["zona"])]

    def __str__(self):
        return f"{self.cliente_nombre} - {self.direccion}"


class PedidoDespacho(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente (sin asignar)"
        ASIGNADO = "ASIGNADO", "Asignado a ruta"
        EN_RUTA = "EN_RUTA", "En ruta"
        ENTREGADO = "ENTREGADO", "Entregado"
        FALLIDO = "FALLIDO", "Fallido"
        REPROGRAMADO = "REPROGRAMADO", "Reprogramado"

    codigo = models.CharField(max_length=12, unique=True, editable=False)
    punto_entrega = models.ForeignKey(PuntoEntrega, on_delete=models.PROTECT, related_name="pedidos")
    descripcion = models.CharField(max_length=200, blank=True)
    peso_kg = models.DecimalField(max_digits=8, decimal_places=2)
    bultos = models.PositiveIntegerField(default=1)
    prioridad = models.CharField(max_length=8, choices=Prioridad.choices, default=Prioridad.NORMAL)
    ventana_inicio = models.TimeField(null=True, blank=True)
    ventana_fin = models.TimeField(null=True, blank=True)
    fecha_programada = models.DateField()
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    creado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "pedido de despacho"
        verbose_name_plural = "pedidos de despacho"
        ordering = ["fecha_programada", "creado"]
        indexes = [
            models.Index(fields=["estado", "fecha_programada"]),
            models.Index(fields=["prioridad"]),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(peso_kg__gt=0), name="pedido_peso_positivo"),
            models.CheckConstraint(condition=Q(bultos__gte=1), name="pedido_bultos_minimo"),
            models.CheckConstraint(
                condition=Q(ventana_inicio__isnull=True) | Q(ventana_fin__isnull=True)
                | Q(ventana_inicio__lt=models.F("ventana_fin")),
                name="pedido_ventana_valida",
            ),
        ]

    @property
    def ventana_horaria(self) -> str:
        if self.ventana_inicio and self.ventana_fin:
            return f"{self.ventana_inicio:%H:%M}-{self.ventana_fin:%H:%M}"
        return "Todo el día"

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.codigo:
            self.codigo = f"PD-{self.pk:06d}"
            super().save(update_fields=["codigo"])

    def __str__(self):
        return self.codigo


class Ruta(models.Model):
    class Estado(models.TextChoices):
        PLANIFICADA = "PLANIFICADA", "Planificada"
        EN_CURSO = "EN_CURSO", "En curso"
        COMPLETADA = "COMPLETADA", "Completada"
        CANCELADA = "CANCELADA", "Cancelada"

    ESTADOS_ACTIVOS = (Estado.PLANIFICADA, Estado.EN_CURSO)

    codigo = models.CharField(max_length=14, unique=True, editable=False)
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.PROTECT, related_name="rutas")
    fecha = models.DateField()
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PLANIFICADA)
    hora_inicio = models.DateTimeField(null=True, blank=True)
    hora_fin = models.DateTimeField(null=True, blank=True)
    km_estimados = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    km_reales = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    km_sin_optimizar = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    minutos_estimados = models.PositiveIntegerField(default=0)
    peso_total_kg = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    bultos_total = models.PositiveIntegerField(default=0)
    # Capacidad del vehículo al momento de planificar (permite el CHECK de capacidad en la BD)
    capacidad_kg = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    capacidad_bultos = models.PositiveIntegerField(default=0)
    secuencia = models.JSONField(default=list, help_text="IDs de pedidos en el orden optimizado")
    algoritmo = models.CharField(max_length=60, default="VMC + 2-opt con ventanas horarias")
    creada_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="rutas_creadas"
    )
    creada = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-fecha", "-creada"]
        indexes = [models.Index(fields=["fecha", "estado"])]
        constraints = [
            # Regla de negocio: un vehículo no puede tener dos rutas activas al mismo tiempo
            models.UniqueConstraint(
                fields=["vehiculo"],
                condition=Q(estado__in=["PLANIFICADA", "EN_CURSO"]),
                name="una_ruta_activa_por_vehiculo",
            ),
            # Regla de negocio: la carga de la ruta no supera la capacidad del vehículo
            models.CheckConstraint(
                condition=Q(peso_total_kg__lte=F("capacidad_kg")),
                name="ruta_peso_dentro_de_capacidad",
                violation_error_message="La carga de la ruta supera la capacidad del vehículo.",
            ),
            models.CheckConstraint(
                condition=Q(bultos_total__lte=F("capacidad_bultos")),
                name="ruta_bultos_dentro_de_capacidad",
                violation_error_message="Los bultos de la ruta superan la capacidad del vehículo.",
            ),
        ]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.codigo:
            self.codigo = f"RT-{self.fecha:%y%m%d}-{self.pk:03d}"
            super().save(update_fields=["codigo"])

    def __str__(self):
        return self.codigo


class ParadaRuta(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_CAMINO = "EN_CAMINO", "En camino"
        ENTREGADO = "ENTREGADO", "Entregado"
        FALLIDO = "FALLIDO", "Fallido"
        REPROGRAMADO = "REPROGRAMADO", "Reprogramado"

    ESTADOS_ABIERTOS = (Estado.PENDIENTE, Estado.EN_CAMINO)

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="paradas")
    pedido = models.ForeignKey(PedidoDespacho, on_delete=models.PROTECT, related_name="paradas")
    orden = models.PositiveIntegerField()
    distancia_km = models.DecimalField(max_digits=7, decimal_places=3, default=0)
    hora_estimada = models.TimeField(null=True, blank=True)
    hora_real = models.DateTimeField(null=True, blank=True)
    estado = models.CharField(max_length=12, choices=Estado.choices, default=Estado.PENDIENTE)
    observacion = models.CharField(max_length=250, blank=True)

    class Meta:
        verbose_name = "parada de ruta"
        verbose_name_plural = "paradas de ruta"
        ordering = ["ruta", "orden"]
        constraints = [
            models.UniqueConstraint(fields=["ruta", "orden"], name="orden_unico_por_ruta"),
            models.UniqueConstraint(fields=["ruta", "pedido"], name="pedido_unico_por_ruta"),
        ]

    def __str__(self):
        return f"{self.ruta.codigo} #{self.orden}"


class IndicadorRuta(models.Model):
    ruta = models.OneToOneField(Ruta, on_delete=models.CASCADE, related_name="indicador")
    pedidos_asignados = models.PositiveIntegerField(default=0)
    pedidos_entregados = models.PositiveIntegerField(default=0)
    pedidos_fallidos = models.PositiveIntegerField(default=0)
    pedidos_reprogramados = models.PositiveIntegerField(default=0)
    km = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    tiempo_min = models.PositiveIntegerField(default=0)
    porcentaje_entrega = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    # Indicadores de optimización y sostenibilidad (valor agregado)
    km_sin_optimizar = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ahorro_km = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    ahorro_pct = models.DecimalField(max_digits=5, decimal_places=1, default=0)
    ahorro_soles = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    co2_evitado_kg = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    calculado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "indicador de ruta"
        verbose_name_plural = "indicadores de ruta"

    def __str__(self):
        return f"KPI {self.ruta.codigo}"


class PosicionVehiculo(models.Model):
    vehiculo = models.ForeignKey(Vehiculo, on_delete=models.CASCADE, related_name="posiciones")
    ruta = models.ForeignKey(Ruta, on_delete=models.SET_NULL, null=True, blank=True, related_name="posiciones")
    latitud = models.FloatField(validators=LATITUD)
    longitud = models.FloatField(validators=LONGITUD)
    velocidad_kmh = models.FloatField(null=True, blank=True, validators=[MinValueValidator(0)])
    registrado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "posiciones de vehículo"
        ordering = ["-registrado"]
        indexes = [models.Index(fields=["vehiculo", "-registrado"])]


class EventoRuta(models.Model):
    """Bitácora: quién hizo qué y cuándo (trazabilidad para auditoría)."""

    ruta = models.ForeignKey(Ruta, on_delete=models.CASCADE, related_name="eventos")
    parada = models.ForeignKey(ParadaRuta, on_delete=models.SET_NULL, null=True, blank=True)
    tipo = models.CharField(max_length=30)
    descripcion = models.CharField(max_length=250)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    registrado = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["registrado"]


class IntentoBloqueado(models.Model):
    """Registro de cada operación rechazada por una regla de negocio (visible en el admin de Django)."""

    regla = models.CharField(max_length=10, db_index=True)
    codigo = models.CharField(max_length=40)
    mensaje = models.CharField(max_length=300)
    usuario = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    endpoint = models.CharField(max_length=200, blank=True)
    registrado = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "intento bloqueado"
        verbose_name_plural = "intentos bloqueados"
        ordering = ["-registrado"]
