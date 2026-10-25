import copy

from django.db import models
from django.forms.models import model_to_dict
from django.utils import timezone
from rest_framework import serializers

from .forms import PedidoForm, PuntoEntregaForm, VehiculoForm, dentro_del_area
from .models import (Conductor, EventoRuta, IndicadorRuta, ParadaRuta, PedidoDespacho,
                     PosicionVehiculo, PuntoEntrega, Ruta, Vehiculo, Zona)


def validar_area(lat, lng):
    if not dentro_del_area(lat, lng):
        raise serializers.ValidationError(
            "La ubicación está fuera del área de operación (región Lambayeque)."
        )


class ValidarConFormulario:
    """
    Delega la validación de negocio en el ModelForm de la capa de formularios (forms.py).
    El serializer se encarga del formato JSON; el formulario, de las reglas.
    """

    formulario = None

    def validate(self, attrs):
        attrs = super().validate(attrs)
        datos = model_to_dict(self.instance) if self.instance else {}
        for campo, valor in attrs.items():
            datos[campo] = valor.pk if isinstance(valor, models.Model) else valor
        modelo = self.formulario._meta.model
        for campo in self.formulario._meta.fields:   # valores por defecto del modelo (p. ej. prioridad NORMAL)
            definicion = modelo._meta.get_field(campo)
            if campo not in datos and definicion.has_default():
                datos[campo] = definicion.get_default()
        instancia = copy.copy(self.instance) if self.instance else None
        form = self.formulario(data=datos, instance=instancia)
        if not form.is_valid():
            errores = {}
            for campo, mensajes in form.errors.items():
                errores["non_field_errors" if campo == "__all__" else campo] = [str(m) for m in mensajes]
            raise serializers.ValidationError(errores)
        for campo in attrs:
            if campo in form.cleaned_data:
                attrs[campo] = form.cleaned_data[campo]
        return attrs


class ZonaSerializer(serializers.ModelSerializer):
    class Meta:
        model = Zona
        fields = ["id", "codigo", "nombre", "color", "centro_lat", "centro_lng"]


class ConductorSerializer(serializers.ModelSerializer):
    nombre = serializers.CharField(source="usuario.get_full_name", read_only=True)
    username = serializers.CharField(source="usuario.username", read_only=True)
    vehiculo_placa = serializers.CharField(source="vehiculo.placa", read_only=True, default=None)

    class Meta:
        model = Conductor
        fields = ["id", "usuario", "username", "nombre", "licencia", "celular", "activo", "vehiculo_placa"]

    def validate_usuario(self, usuario):
        if not usuario.es_conductor:
            raise serializers.ValidationError("El usuario debe tener rol CONDUCTOR.")
        return usuario


class VehiculoSerializer(ValidarConFormulario, serializers.ModelSerializer):
    formulario = VehiculoForm

    tipo_display = serializers.CharField(source="get_tipo_display", read_only=True)
    conductor_nombre = serializers.CharField(source="conductor.usuario.get_full_name", read_only=True,
                                             default=None)
    ruta_activa = serializers.SerializerMethodField()

    class Meta:
        model = Vehiculo
        fields = [
            "id", "placa", "tipo", "tipo_display", "capacidad_kg", "capacidad_bultos",
            "conductor", "conductor_nombre", "disponible", "ultima_lat", "ultima_lng",
            "ultima_actualizacion", "ruta_activa",
        ]
        read_only_fields = ["ultima_lat", "ultima_lng", "ultima_actualizacion"]

    def get_ruta_activa(self, obj) -> dict | None:
        # Usa el prefetch "rutas_activas" para evitar N+1
        rutas = getattr(obj, "rutas_activas", None)
        if rutas is None:
            rutas = list(obj.rutas.filter(estado__in=Ruta.ESTADOS_ACTIVOS))
        if not rutas:
            return None
        r = rutas[0]
        return {"id": r.id, "codigo": r.codigo, "estado": r.estado}

    def to_internal_value(self, data):
        # la placa se normaliza a mayúsculas antes de validar el formato ABC-123
        if hasattr(data, "get") and data.get("placa"):
            data = data.copy() if hasattr(data, "copy") else dict(data)
            data["placa"] = str(data["placa"]).upper().strip()
        return super().to_internal_value(data)


class PuntoEntregaSerializer(ValidarConFormulario, serializers.ModelSerializer):
    formulario = PuntoEntregaForm

    zona_nombre = serializers.CharField(source="zona.nombre", read_only=True)
    zona_color = serializers.CharField(source="zona.color", read_only=True)

    class Meta:
        model = PuntoEntrega
        fields = ["id", "cliente_nombre", "direccion", "referencia", "zona", "zona_nombre", "zona_color",
                  "latitud", "longitud", "telefono", "email"]


class PedidoSerializer(ValidarConFormulario, serializers.ModelSerializer):
    formulario = PedidoForm

    punto = PuntoEntregaSerializer(source="punto_entrega", read_only=True)
    punto_entrega = serializers.PrimaryKeyRelatedField(queryset=PuntoEntrega.objects.all(), write_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    ventana_horaria = serializers.CharField(read_only=True)

    class Meta:
        model = PedidoDespacho
        fields = [
            "id", "codigo", "punto", "punto_entrega", "descripcion", "peso_kg", "bultos", "prioridad",
            "ventana_inicio", "ventana_fin", "ventana_horaria", "fecha_programada", "estado",
            "estado_display", "creado",
        ]
        read_only_fields = ["codigo", "estado", "creado"]


class PedidoEnParadaSerializer(serializers.ModelSerializer):
    cliente = serializers.CharField(source="punto_entrega.cliente_nombre")
    direccion = serializers.CharField(source="punto_entrega.direccion")
    referencia = serializers.CharField(source="punto_entrega.referencia")
    telefono = serializers.CharField(source="punto_entrega.telefono")
    lat = serializers.FloatField(source="punto_entrega.latitud")
    lng = serializers.FloatField(source="punto_entrega.longitud")
    zona = serializers.CharField(source="punto_entrega.zona.nombre")

    class Meta:
        model = PedidoDespacho
        fields = ["id", "codigo", "cliente", "direccion", "referencia", "telefono", "lat", "lng", "zona",
                  "peso_kg", "bultos", "prioridad", "ventana_horaria", "descripcion"]


class ParadaSerializer(serializers.ModelSerializer):
    pedido = PedidoEnParadaSerializer(read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)

    class Meta:
        model = ParadaRuta
        fields = ["id", "orden", "pedido", "distancia_km", "hora_estimada", "hora_real", "estado",
                  "estado_display", "observacion"]


class IndicadorSerializer(serializers.ModelSerializer):
    class Meta:
        model = IndicadorRuta
        exclude = ["id", "ruta"]


class EventoSerializer(serializers.ModelSerializer):
    usuario = serializers.CharField(source="usuario.get_full_name", default=None)

    class Meta:
        model = EventoRuta
        fields = ["id", "tipo", "descripcion", "usuario", "registrado"]


class RutaSerializer(serializers.ModelSerializer):
    vehiculo_placa = serializers.CharField(source="vehiculo.placa", read_only=True)
    vehiculo_tipo = serializers.CharField(source="vehiculo.tipo", read_only=True)
    conductor = serializers.CharField(source="vehiculo.conductor.usuario.get_full_name", default=None,
                                      read_only=True)
    estado_display = serializers.CharField(source="get_estado_display", read_only=True)
    total_paradas = serializers.IntegerField(read_only=True)
    paradas_cerradas = serializers.IntegerField(read_only=True)
    avance_pct = serializers.SerializerMethodField()
    ahorro_pct = serializers.SerializerMethodField()

    class Meta:
        model = Ruta
        fields = [
            "id", "codigo", "vehiculo", "vehiculo_placa", "vehiculo_tipo", "conductor", "fecha", "estado",
            "estado_display", "hora_inicio", "hora_fin", "km_estimados", "km_reales", "km_sin_optimizar",
            "minutos_estimados", "peso_total_kg", "bultos_total", "total_paradas", "paradas_cerradas",
            "avance_pct", "ahorro_pct", "algoritmo", "creada",
        ]

    def get_avance_pct(self, obj) -> float:
        total = getattr(obj, "total_paradas", 0) or 0
        return round(100 * (getattr(obj, "paradas_cerradas", 0) or 0) / total, 1) if total else 0

    def get_ahorro_pct(self, obj) -> float:
        base = float(obj.km_sin_optimizar or 0)
        return round(100 * (base - float(obj.km_estimados)) / base, 1) if base else 0


class RutaDetalleSerializer(RutaSerializer):
    paradas = ParadaSerializer(many=True, read_only=True)
    indicador = IndicadorSerializer(read_only=True)
    posicion_actual = serializers.SerializerMethodField()
    secuencia = serializers.JSONField(read_only=True)

    class Meta(RutaSerializer.Meta):
        fields = RutaSerializer.Meta.fields + ["secuencia", "paradas", "indicador", "posicion_actual"]

    def get_posicion_actual(self, obj) -> dict | None:
        v = obj.vehiculo
        if v.ultima_lat is None:
            return None
        return {"lat": v.ultima_lat, "lng": v.ultima_lng, "actualizado": v.ultima_actualizacion}


# ---------------------------------------------------------------------------
# Serializadores de entrada para acciones
# ---------------------------------------------------------------------------
class PlanificarSerializer(serializers.Serializer):
    vehiculo = serializers.PrimaryKeyRelatedField(queryset=Vehiculo.objects.all())
    pedidos = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=False,
                                    max_length=40)
    fecha = serializers.DateField(required=False)
    hora_inicio = serializers.TimeField(required=False)

    def validate_pedidos(self, value):
        if len(value) != len(set(value)):
            raise serializers.ValidationError("Hay pedidos repetidos en la lista.")
        return value

    def validate_fecha(self, value):
        if value < timezone.localdate():
            raise serializers.ValidationError("No se pueden planificar rutas en fechas pasadas.")
        return value


class PlanificarAutoSerializer(serializers.Serializer):
    fecha = serializers.DateField(required=False)
    zona = serializers.PrimaryKeyRelatedField(queryset=Zona.objects.all(), required=False)


class EstadoParadaSerializer(serializers.Serializer):
    estado = serializers.ChoiceField(choices=ParadaRuta.Estado.choices)
    observacion = serializers.CharField(required=False, allow_blank=True, max_length=250)


class CancelarSerializer(serializers.Serializer):
    motivo = serializers.CharField(min_length=5, max_length=250)


class PosicionSerializer(serializers.ModelSerializer):
    class Meta:
        model = PosicionVehiculo
        fields = ["id", "latitud", "longitud", "velocidad_kmh", "registrado", "ruta"]
        read_only_fields = ["registrado", "ruta"]

    def validate(self, attrs):
        try:
            validar_area(attrs["latitud"], attrs["longitud"])
        except serializers.ValidationError as e:
            raise serializers.ValidationError({"latitud": e.detail})
        return attrs
