"""
Vistas de la API REST (capa de presentación de datos).

Endpoints mínimos de la guía:
    POST  /api/rutas/planificar/              Crear ruta asignando pedidos a vehículo por zona y capacidad
    GET   /api/rutas/{id}/paradas/            Secuencia de paradas con horas estimadas
    PATCH /api/paradas/{id}/estado/           Actualizar estado (ENTREGADO, FALLIDO, REPROGRAMADO)
    GET   /api/rutas/en-curso/                Rutas activas con posición actual
    POST  /api/vehiculos/{id}/posicion/       Actualizar posición GPS
    GET   /api/reportes/eficiencia/?fecha=    KPIs (app reportes)
    GET   /api/pedidos/sin-asignar/           Pedidos pendientes
    GET   /api/zonas/{id}/pedidos-hoy/        Pedidos del día por zona
Endpoints adicionales: previsualizar, planificar-automatico, iniciar, cerrar, cancelar,
mi-ruta, eventos, hoja-ruta (PDF) y seguimiento público.
"""
from django.db.models import Case, Count, IntegerField, Prefetch, Q, Value, When
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action, api_view, permission_classes, throttle_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle

from apps.cuentas.permisos import EsSupervisorOAdmin, LecturaTodosEscrituraGestion

from . import servicios
from .excepciones import ReglaNegocioError
from .filtros import PedidoFiltro, RutaFiltro
from .models import Conductor, ParadaRuta, PedidoDespacho, PuntoEntrega, Ruta, Vehiculo, Zona
from .pdf import hoja_de_ruta
from .serializers import (CancelarSerializer, ConductorSerializer, EstadoParadaSerializer,
                          EventoSerializer, ParadaSerializer, PedidoSerializer,
                          PlanificarAutoSerializer, PlanificarSerializer, PosicionSerializer,
                          PuntoEntregaSerializer, RutaDetalleSerializer, RutaSerializer,
                          VehiculoSerializer, ZonaSerializer)

PEDIDO_QS = PedidoDespacho.objects.select_related("punto_entrega__zona")


class ZonaViewSet(viewsets.ModelViewSet):
    queryset = Zona.objects.all()
    serializer_class = ZonaSerializer
    permission_classes = [LecturaTodosEscrituraGestion]
    pagination_class = None

    @action(detail=True, methods=["get"], url_path="pedidos-hoy", permission_classes=[EsSupervisorOAdmin])
    def pedidos_hoy(self, request, pk=None):
        zona = self.get_object()
        pedidos = PEDIDO_QS.filter(punto_entrega__zona=zona, fecha_programada=timezone.localdate())
        datos = PedidoSerializer(pedidos, many=True).data
        return Response({
            "zona": ZonaSerializer(zona).data,
            "total": len(datos),
            "peso_total_kg": round(sum(float(p["peso_kg"]) for p in datos), 2),
            "pedidos": datos,
        })


class ConductorViewSet(viewsets.ModelViewSet):
    queryset = Conductor.objects.select_related("usuario", "vehiculo")
    serializer_class = ConductorSerializer
    permission_classes = [EsSupervisorOAdmin]
    filterset_fields = ["activo"]
    search_fields = ["usuario__first_name", "usuario__last_name", "licencia"]


class VehiculoViewSet(viewsets.ModelViewSet):
    serializer_class = VehiculoSerializer
    permission_classes = [LecturaTodosEscrituraGestion]
    filterset_fields = ["tipo", "disponible"]
    search_fields = ["placa"]

    def get_queryset(self):
        qs = Vehiculo.objects.select_related("conductor__usuario").prefetch_related(
            Prefetch("rutas", queryset=Ruta.objects.filter(estado__in=Ruta.ESTADOS_ACTIVOS),
                     to_attr="rutas_activas")
        )
        if getattr(self, "swagger_fake_view", False):
            return qs.none()
        if self.request.user.es_conductor:
            qs = qs.filter(conductor__usuario=self.request.user)
        return qs

    def destroy(self, request, *args, **kwargs):
        vehiculo = self.get_object()
        if vehiculo.rutas.exists():
            raise ReglaNegocioError("No se puede eliminar un vehículo con historial de rutas; "
                                    "márcalo como no disponible.", "vehiculo_con_historial", http=409)
        return super().destroy(request, *args, **kwargs)

    @extend_schema(request=PosicionSerializer, responses=PosicionSerializer)
    @action(detail=True, methods=["post", "get"], permission_classes=[IsAuthenticated])
    def posicion(self, request, pk=None):
        vehiculo = self.get_object()
        if request.method == "GET":
            ultimas = vehiculo.posiciones.all()[:50]
            return Response(PosicionSerializer(ultimas, many=True).data)
        entrada = PosicionSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        pos = servicios.registrar_posicion(
            vehiculo, entrada.validated_data["latitud"], entrada.validated_data["longitud"],
            request.user, entrada.validated_data.get("velocidad_kmh"),
        )
        return Response(PosicionSerializer(pos).data, status=status.HTTP_201_CREATED)


class PuntoEntregaViewSet(viewsets.ModelViewSet):
    queryset = PuntoEntrega.objects.select_related("zona")
    serializer_class = PuntoEntregaSerializer
    permission_classes = [EsSupervisorOAdmin]
    filterset_fields = ["zona"]
    search_fields = ["cliente_nombre", "direccion"]


class PedidoViewSet(viewsets.ModelViewSet):
    queryset = PEDIDO_QS.all()
    serializer_class = PedidoSerializer
    permission_classes = [EsSupervisorOAdmin]
    filterset_class = PedidoFiltro
    search_fields = ["codigo", "punto_entrega__cliente_nombre", "punto_entrega__direccion"]
    ordering_fields = ["fecha_programada", "peso_kg", "prioridad", "creado"]

    def destroy(self, request, *args, **kwargs):
        pedido = self.get_object()
        if pedido.estado != PedidoDespacho.Estado.PENDIENTE:
            raise ReglaNegocioError("Solo se pueden eliminar pedidos PENDIENTES.", "pedido_no_eliminable",
                                    http=409)
        return super().destroy(request, *args, **kwargs)

    @action(detail=False, methods=["get"], url_path="sin-asignar")
    def sin_asignar(self, request):
        qs = self.filter_queryset(
            self.get_queryset().filter(estado__in=servicios.ESTADOS_PLANIFICABLES)
        ).annotate(rango=Case(
            When(prioridad="URGENTE", then=Value(0)), When(prioridad="ALTA", then=Value(1)),
            default=Value(2), output_field=IntegerField(),
        )).order_by("fecha_programada", "rango", "-peso_kg")
        pagina = self.paginate_queryset(qs)
        if pagina is not None:
            return self.get_paginated_response(self.get_serializer(pagina, many=True).data)
        return Response(self.get_serializer(qs, many=True).data)


class RutaViewSet(viewsets.ReadOnlyModelViewSet):
    permission_classes = [IsAuthenticated]
    filterset_class = RutaFiltro
    search_fields = ["codigo", "vehiculo__placa"]
    ordering_fields = ["fecha", "km_estimados", "creada"]

    def get_queryset(self):
        qs = (
            Ruta.objects.select_related("vehiculo__conductor__usuario", "indicador")
            .annotate(
                total_paradas=Count("paradas", distinct=True),
                paradas_cerradas=Count(
                    "paradas",
                    filter=Q(paradas__estado__in=["ENTREGADO", "FALLIDO", "REPROGRAMADO"]),
                    distinct=True,
                ),
            )
            .order_by("-fecha", "-creada")
        )
        if self.action in ("retrieve", "en_curso", "mi_ruta"):
            qs = qs.prefetch_related(
                Prefetch("paradas", queryset=ParadaRuta.objects.select_related(
                    "pedido__punto_entrega__zona").order_by("orden"))
            )
        if getattr(self, "swagger_fake_view", False):
            return qs.none()
        if self.request.user.es_conductor:
            qs = qs.filter(vehiculo__conductor__usuario=self.request.user)
        return qs

    def get_serializer_class(self):
        if self.action in ("retrieve", "en_curso", "mi_ruta"):
            return RutaDetalleSerializer
        return RutaSerializer

    def _detalle(self, ruta, http=status.HTTP_200_OK):
        ruta = self.get_queryset().get(pk=ruta.pk) if self.action != "retrieve" else ruta
        return Response(RutaDetalleSerializer(ruta).data, status=http)

    # ---------------- Planificación ----------------
    @extend_schema(request=PlanificarSerializer, responses=RutaDetalleSerializer)
    @action(detail=False, methods=["post"], permission_classes=[EsSupervisorOAdmin])
    def planificar(self, request):
        entrada = PlanificarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        ruta = servicios.planificar_ruta(
            d["vehiculo"], d["pedidos"], d.get("fecha") or timezone.localdate(), request.user,
            d.get("hora_inicio"),
        )
        return self._detalle(ruta, http=status.HTTP_201_CREATED)

    @extend_schema(request=PlanificarSerializer)
    @action(detail=False, methods=["post"], permission_classes=[EsSupervisorOAdmin])
    def previsualizar(self, request):
        entrada = PlanificarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        pedidos = PEDIDO_QS.filter(id__in=d["pedidos"])
        return Response(servicios.previsualizar(d["vehiculo"], pedidos, d.get("hora_inicio")))

    @extend_schema(request=PlanificarAutoSerializer)
    @action(detail=False, methods=["post"], url_path="planificar-automatico",
            permission_classes=[EsSupervisorOAdmin])
    def planificar_automatico(self, request):
        entrada = PlanificarAutoSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        d = entrada.validated_data
        zona = d.get("zona")
        rutas, sin_asignar = servicios.planificar_automatico(
            d.get("fecha") or timezone.localdate(), request.user, zona.id if zona else None
        )
        qs = self.get_queryset().filter(pk__in=[r.pk for r in rutas])
        return Response(
            {"rutas": RutaSerializer(qs, many=True).data, "pedidos_sin_asignar": sin_asignar},
            status=status.HTTP_201_CREATED,
        )

    # ---------------- Consulta ----------------
    @action(detail=True, methods=["get"])
    def paradas(self, request, pk=None):
        ruta = self.get_object()
        paradas = ruta.paradas.select_related("pedido__punto_entrega__zona").order_by("orden")
        return Response({
            "ruta": ruta.codigo,
            "estado": ruta.estado,
            "secuencia": ruta.secuencia,
            "paradas": ParadaSerializer(paradas, many=True).data,
        })

    @action(detail=False, methods=["get"], url_path="en-curso")
    def en_curso(self, request):
        """Rutas activas con posición actual. Con ?incluir=completadas suma las cerradas hoy (mapa del día)."""
        filtro = Q(estado__in=Ruta.ESTADOS_ACTIVOS, fecha__lte=timezone.localdate())
        if request.query_params.get("incluir") == "completadas":
            filtro |= Q(estado=Ruta.Estado.COMPLETADA, fecha=timezone.localdate())
        qs = self.get_queryset().filter(filtro)
        return Response(RutaDetalleSerializer(qs, many=True).data)

    @action(detail=False, methods=["get"], url_path="mi-ruta")
    def mi_ruta(self, request):
        ruta = (self.get_queryset().filter(estado=Ruta.Estado.EN_CURSO).first()
                or self.get_queryset().filter(estado=Ruta.Estado.PLANIFICADA).order_by("fecha").first())
        if not ruta:
            return Response({"ruta": None, "mensaje": "No tienes rutas asignadas por ahora."})
        return Response({"ruta": RutaDetalleSerializer(ruta).data})

    @action(detail=True, methods=["get"])
    def eventos(self, request, pk=None):
        ruta = self.get_object()
        return Response(EventoSerializer(ruta.eventos.select_related("usuario"), many=True).data)

    @action(detail=True, methods=["get"], url_path="hoja-ruta")
    def hoja_ruta(self, request, pk=None):
        ruta = self.get_object()
        respuesta = HttpResponse(hoja_de_ruta(ruta), content_type="application/pdf")
        respuesta["Content-Disposition"] = f'inline; filename="hoja-{ruta.codigo}.pdf"'
        return respuesta

    # ---------------- Ejecución ----------------
    @action(detail=True, methods=["post"])
    def iniciar(self, request, pk=None):
        return self._detalle(servicios.iniciar_ruta(self.get_object(), request.user))

    @action(detail=True, methods=["post"])
    def cerrar(self, request, pk=None):
        return self._detalle(servicios.cerrar_ruta(self.get_object(), request.user))

    @extend_schema(request=CancelarSerializer)
    @action(detail=True, methods=["post"], permission_classes=[EsSupervisorOAdmin])
    def cancelar(self, request, pk=None):
        entrada = CancelarSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        servicios.cancelar_ruta(self.get_object(), request.user, entrada.validated_data["motivo"])
        return Response({"mensaje": "Ruta cancelada y pedidos liberados."})


class ParadaViewSet(mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    serializer_class = ParadaSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = ParadaRuta.objects.select_related("ruta__vehiculo__conductor", "pedido__punto_entrega__zona")
        if getattr(self, "swagger_fake_view", False):
            return qs.none()
        if self.request.user.es_conductor:
            qs = qs.filter(ruta__vehiculo__conductor__usuario=self.request.user)
        return qs

    @extend_schema(request=EstadoParadaSerializer, responses=ParadaSerializer)
    @action(detail=True, methods=["patch"])
    def estado(self, request, pk=None):
        entrada = EstadoParadaSerializer(data=request.data)
        entrada.is_valid(raise_exception=True)
        parada = servicios.cambiar_estado_parada(
            self.get_object(), entrada.validated_data["estado"], request.user,
            entrada.validated_data.get("observacion", ""),
        )
        return Response(ParadaSerializer(self.get_queryset().get(pk=parada.pk)).data)


class SeguimientoThrottle(AnonRateThrottle):
    rate = "30/min"


@extend_schema(responses=OpenApiTypes.OBJECT)
@api_view(["GET"])
@permission_classes([AllowAny])
@throttle_classes([SeguimientoThrottle])
def seguimiento_publico(request, codigo):
    """GET /api/seguimiento/{codigo}/ — el cliente final consulta su pedido sin iniciar sesión."""
    pedido = get_object_or_404(PedidoDespacho.objects.select_related("punto_entrega__zona"),
                               codigo=codigo.upper())
    parada = (pedido.paradas.select_related("ruta__vehiculo").exclude(ruta__estado="CANCELADA")
              .order_by("-ruta__creada").first())
    datos = {
        "codigo": pedido.codigo,
        "estado": pedido.estado,
        "estado_display": pedido.get_estado_display(),
        "fecha_programada": pedido.fecha_programada,
        "zona": pedido.punto_entrega.zona.nombre,
        "ventana_horaria": pedido.ventana_horaria,
        "destino": {"lat": pedido.punto_entrega.latitud, "lng": pedido.punto_entrega.longitud},
        "ruta": None,
    }
    if parada:
        ruta = parada.ruta
        delante = ruta.paradas.filter(orden__lt=parada.orden,
                                      estado__in=ParadaRuta.ESTADOS_ABIERTOS).count()
        datos["ruta"] = {
            "codigo": ruta.codigo,
            "estado": ruta.estado,
            "orden": parada.orden,
            "paradas_antes": delante,
            "hora_estimada": parada.hora_estimada,
            "hora_entrega": parada.hora_real,
            "vehiculo": ({"lat": ruta.vehiculo.ultima_lat, "lng": ruta.vehiculo.ultima_lng}
                         if ruta.estado == "EN_CURSO" and ruta.vehiculo.ultima_lat else None),
        }
    return Response(datos)
