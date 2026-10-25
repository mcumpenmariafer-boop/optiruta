from django.contrib import admin

from .forms import PedidoForm, PuntoEntregaForm, VehiculoForm

from .models import (Conductor, EventoRuta, IntentoBloqueado, IndicadorRuta, ParadaRuta, PedidoDespacho,
                     PosicionVehiculo, PuntoEntrega, Ruta, Vehiculo, Zona)


@admin.register(Zona)
class ZonaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "nombre", "color")


@admin.register(Conductor)
class ConductorAdmin(admin.ModelAdmin):
    list_display = ("usuario", "licencia", "celular", "activo")
    list_filter = ("activo",)


@admin.register(Vehiculo)
class VehiculoAdmin(admin.ModelAdmin):
    form = VehiculoForm
    list_display = ("placa", "tipo", "capacidad_kg", "capacidad_bultos", "conductor", "disponible")
    list_filter = ("tipo", "disponible")
    search_fields = ("placa",)


@admin.register(PuntoEntrega)
class PuntoEntregaAdmin(admin.ModelAdmin):
    form = PuntoEntregaForm
    list_display = ("cliente_nombre", "direccion", "zona")
    list_filter = ("zona",)
    search_fields = ("cliente_nombre", "direccion")


@admin.register(PedidoDespacho)
class PedidoAdmin(admin.ModelAdmin):
    form = PedidoForm
    list_display = ("codigo", "punto_entrega", "peso_kg", "bultos", "prioridad", "fecha_programada", "estado")
    list_filter = ("estado", "prioridad", "fecha_programada")
    search_fields = ("codigo",)
    list_select_related = ("punto_entrega",)


class ParadaInline(admin.TabularInline):
    model = ParadaRuta
    extra = 0
    readonly_fields = ("pedido", "orden", "hora_estimada", "hora_real", "estado", "observacion")


@admin.register(Ruta)
class RutaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "vehiculo", "fecha", "estado", "km_estimados", "km_sin_optimizar")
    list_filter = ("estado", "fecha")
    inlines = [ParadaInline]
    list_select_related = ("vehiculo",)


admin.site.register(IndicadorRuta)
admin.site.register(PosicionVehiculo)
admin.site.register(EventoRuta)


@admin.register(IntentoBloqueado)
class IntentoBloqueadoAdmin(admin.ModelAdmin):
    list_display = ("registrado", "regla", "codigo", "usuario", "endpoint")
    list_filter = ("regla",)
