import django_filters

from .models import PedidoDespacho, Ruta


class PedidoFiltro(django_filters.FilterSet):
    zona = django_filters.NumberFilter(field_name="punto_entrega__zona_id")
    fecha = django_filters.DateFilter(field_name="fecha_programada")
    fecha_desde = django_filters.DateFilter(field_name="fecha_programada", lookup_expr="gte")
    fecha_hasta = django_filters.DateFilter(field_name="fecha_programada", lookup_expr="lte")

    class Meta:
        model = PedidoDespacho
        fields = ["estado", "prioridad", "zona", "fecha"]


class RutaFiltro(django_filters.FilterSet):
    desde = django_filters.DateFilter(field_name="fecha", lookup_expr="gte")
    hasta = django_filters.DateFilter(field_name="fecha", lookup_expr="lte")

    class Meta:
        model = Ruta
        fields = ["estado", "vehiculo", "fecha"]
