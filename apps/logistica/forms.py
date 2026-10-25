"""
Capa de FORMULARIOS (separación de capas: modelos · vistas · formularios).

Los ModelForm concentran las validaciones de entrada del negocio. Se usan en:
  · la API REST: los serializers delegan su validación en estos formularios (ValidarConFormulario);
  · el sitio de administración de Django (ModelAdmin.form).
Así una misma regla (p. ej. "la ventana horaria dura al menos 30 minutos") vive en un solo lugar.
"""
from datetime import time

from django import forms
from django.utils import timezone

from .models import PedidoDespacho, PuntoEntrega, Vehiculo

# Región Lambayeque (aprox.): se rechazan coordenadas fuera del área de operación
LAT_MIN, LAT_MAX = -7.30, -6.20
LNG_MIN, LNG_MAX = -80.30, -79.30
HORA_APERTURA, HORA_CIERRE = time(6, 0), time(22, 0)
DURACION_MINIMA_VENTANA = 30
PESO_MAXIMO_KG = 10000
CAPACIDAD_MAXIMA_POR_TIPO = {"MOTO": 150, "FURGONETA": 1500, "CAMION": 10000}


def dentro_del_area(lat, lng):
    return LAT_MIN <= lat <= LAT_MAX and LNG_MIN <= lng <= LNG_MAX


class PuntoEntregaForm(forms.ModelForm):
    class Meta:
        model = PuntoEntrega
        fields = ["cliente_nombre", "direccion", "referencia", "zona", "latitud", "longitud", "telefono", "email"]

    def clean_cliente_nombre(self):
        nombre = (self.cleaned_data.get("cliente_nombre") or "").strip()
        if len(nombre) < 3:
            raise forms.ValidationError("El nombre del cliente es muy corto.")
        return nombre

    def clean_direccion(self):
        direccion = (self.cleaned_data.get("direccion") or "").strip()
        if len(direccion) < 5:
            raise forms.ValidationError("Escribe la dirección completa.")
        return direccion

    def clean(self):
        datos = super().clean()
        lat, lng = datos.get("latitud"), datos.get("longitud")
        if lat is not None and lng is not None and not dentro_del_area(lat, lng):
            self.add_error("latitud", "La ubicación está fuera del área de operación (región Lambayeque).")
        return datos


class PedidoForm(forms.ModelForm):
    class Meta:
        model = PedidoDespacho
        fields = ["punto_entrega", "descripcion", "peso_kg", "bultos", "prioridad",
                  "ventana_inicio", "ventana_fin", "fecha_programada"]

    def clean_peso_kg(self):
        peso = self.cleaned_data.get("peso_kg")
        if peso is not None and peso <= 0:
            raise forms.ValidationError("El peso debe ser mayor a 0 kg.")
        if peso is not None and peso > PESO_MAXIMO_KG:
            raise forms.ValidationError("Ningún vehículo de la flota soporta más de 10 000 kg.")
        return peso

    def clean_bultos(self):
        bultos = self.cleaned_data.get("bultos")
        if bultos is not None and bultos < 1:
            raise forms.ValidationError("Debe haber al menos 1 bulto.")
        return bultos

    def clean_fecha_programada(self):
        fecha = self.cleaned_data.get("fecha_programada")
        if fecha and self.instance.pk is None and fecha < timezone.localdate():
            raise forms.ValidationError("No se puede programar un pedido en una fecha pasada.")
        return fecha

    def clean(self):
        datos = super().clean()
        if self.instance.pk and self.instance.estado not in (PedidoDespacho.Estado.PENDIENTE,
                                                             PedidoDespacho.Estado.REPROGRAMADO):
            raise forms.ValidationError("Solo se pueden editar pedidos pendientes.")
        ini, fin = datos.get("ventana_inicio"), datos.get("ventana_fin")
        if (ini is None) != (fin is None):
            self.add_error("ventana_fin", "Indica inicio y fin de la ventana, o ninguno.")
        elif ini and fin:
            if ini >= fin:
                self.add_error("ventana_fin", "El fin de la ventana debe ser posterior al inicio.")
            elif ini < HORA_APERTURA or fin > HORA_CIERRE:
                self.add_error("ventana_inicio", "La ventana debe estar entre las 06:00 y las 22:00.")
            elif (fin.hour * 60 + fin.minute) - (ini.hour * 60 + ini.minute) < DURACION_MINIMA_VENTANA:
                self.add_error("ventana_fin", "La ventana debe durar al menos 30 minutos.")
        return datos


class VehiculoForm(forms.ModelForm):
    class Meta:
        model = Vehiculo
        fields = ["placa", "tipo", "capacidad_kg", "capacidad_bultos", "conductor", "disponible"]

    def clean_placa(self):
        return (self.cleaned_data.get("placa") or "").upper().strip()

    def clean(self):
        datos = super().clean()
        tipo, capacidad = datos.get("tipo"), datos.get("capacidad_kg")
        limite = CAPACIDAD_MAXIMA_POR_TIPO.get(tipo)
        if limite and capacidad and capacidad > limite:
            self.add_error("capacidad_kg", f"Una {tipo.lower()} no puede cargar más de {limite} kg.")
        return datos
