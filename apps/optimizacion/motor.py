"""
Motor de secuenciación de paradas (problema del viajero con prioridades y ventanas horarias).

MODELO MATEMÁTICO
-----------------
Sea 0 el almacén y P = {1..n} las paradas. Buscamos una permutación π de P que minimice

    Z(π) = Σ d(π_k, π_k+1) + α · Σ espera_k + β · Σ tardanza_k + Π · V_prioridad(π)

donde:
    d(i, j)       distancia vial entre i y j (Haversine × factor de circuito)
    llegada_k     = salida_(k-1) + d(π_(k-1), π_k) / v · 60            (minutos)
    inicio_k      = max(llegada_k, ventana_inicio_k)                    (si llega antes, espera)
    espera_k      = inicio_k − llegada_k
    tardanza_k    = max(0, llegada_k − ventana_fin_k)                   (violación de ventana)
    salida_k      = inicio_k + s                                         (s = minutos de servicio)

    V_prioridad   = número de pares (i, j) con i antes que j, i NO urgente, j URGENTE y
                    j ya disponible cuando se atendió i (su ventana abre a más tardar
                    E_max minutos después de inicio_i). Un urgente cuya ventana aún no abre
                    NO obliga a esperar: mientras tanto se atienden otros pedidos.

Reglas de negocio que modela:
    RN3. Los URGENTES se atienden primero siempre que ya se puedan atender (Π muy grande).
    RN5. Las ventanas horarias se respetan: β es muy grande, así que solo se acepta llegar
         tarde cuando la ventana es imposible de cumplir.

ALGORITMO (heurística en dos fases)
    Fase 1 — Construcción: Vecino Más Cercano con costo compuesto. En cada paso, si hay
        urgentes disponibles se elige entre ellos; si no, entre todos:
        c(i, j) = d(i, j) · f_p(j) + α · espera_j + β · tardanza_j
        con f_p = 0.85 para prioridad ALTA (se "acerca" virtualmente) y 1.0 en otro caso.
    Fase 2 — Mejora local 2-opt: invierte el subtramo [i..k] mientras Z disminuya.
"""
from dataclasses import dataclass, field
from datetime import time

from .geo import distancia_vial

ALFA_ESPERA = 0.25        # km equivalentes por minuto de espera (esperar 4 min "cuesta" como 1 km)
BETA_TARDANZA = 50.0      # km equivalentes por minuto de tardanza (penalización fuerte)
PI_PRIORIDAD = 1000.0     # km equivalentes por cada urgente postergado sin motivo
ESPERA_MAX_URGENTE = 15   # minutos: si la ventana del urgente abre en ≤ 15 min, se le espera
FACTOR_PRIORIDAD = {"URGENTE": 1.0, "ALTA": 0.85, "NORMAL": 1.0}


@dataclass
class Parada:
    id: int
    lat: float
    lng: float
    prioridad: str = "NORMAL"
    ventana_inicio: int | None = None   # minutos desde las 00:00
    ventana_fin: int | None = None
    codigo: str = ""

    @property
    def urgente(self):
        return self.prioridad == "URGENTE"


@dataclass
class Configuracion:
    deposito: tuple = (-6.778810, -79.868766)
    velocidad_kmh: float = 25.0
    factor_circuito: float = 1.3
    minutos_servicio: int = 8
    hora_inicio: int = 8 * 60
    regresar_al_deposito: bool = True


@dataclass
class ParadaProgramada:
    parada: Parada
    orden: int
    distancia_km: float
    llegada: int
    inicio: int
    espera: int
    tardanza: int


@dataclass
class ResultadoRuta:
    secuencia: list = field(default_factory=list)  # list[ParadaProgramada]
    km_total: float = 0.0
    minutos_total: int = 0
    espera_total: int = 0
    tardanza_total: int = 0
    ventanas_incumplidas: int = 0
    prioridad_violada: int = 0
    costo: float = 0.0

    @property
    def ids(self):
        return [p.parada.id for p in self.secuencia]


def a_minutos(valor):
    """time(9, 30) -> 570. Acepta None."""
    if valor is None:
        return None
    if isinstance(valor, time):
        return valor.hour * 60 + valor.minute
    if isinstance(valor, str):
        h, m = valor.split(":")[:2]
        return int(h) * 60 + int(m)
    return int(valor)


def a_hora(minutos):
    minutos = int(round(minutos))
    return time((minutos // 60) % 24, minutos % 60)


def disponible(parada, momento):
    """¿Se puede atender la parada en `momento` (o esperando como máximo E_max minutos)?"""
    return parada.ventana_inicio is None or parada.ventana_inicio <= momento + ESPERA_MAX_URGENTE


def violaciones_prioridad(programadas):
    """Cuenta urgentes postergados detrás de un no urgente cuando ya estaban disponibles."""
    total = 0
    for i, a in enumerate(programadas):
        if a.parada.urgente:
            continue
        for b in programadas[i + 1:]:
            if b.parada.urgente and disponible(b.parada, a.inicio):
                total += 1
    return total


# ----------------------------------------------------------------------------
# Evaluación de una secuencia (simulación del recorrido en el tiempo)
# ----------------------------------------------------------------------------
def evaluar(secuencia, config: Configuracion) -> ResultadoRuta:
    resultado = ResultadoRuta()
    lat, lng = config.deposito
    reloj = config.hora_inicio
    km = espera_total = tardanza_total = 0.0
    for orden, p in enumerate(secuencia, start=1):
        d = distancia_vial(lat, lng, p.lat, p.lng, config.factor_circuito)
        llegada = reloj + d / config.velocidad_kmh * 60
        inicio = max(llegada, p.ventana_inicio) if p.ventana_inicio is not None else llegada
        espera = inicio - llegada
        tardanza = max(0, llegada - p.ventana_fin) if p.ventana_fin is not None else 0
        resultado.secuencia.append(
            ParadaProgramada(p, orden, round(d, 3), round(llegada), round(inicio), round(espera), round(tardanza))
        )
        km += d
        espera_total += espera
        tardanza_total += tardanza
        if tardanza > 0:
            resultado.ventanas_incumplidas += 1
        reloj = inicio + config.minutos_servicio
        lat, lng = p.lat, p.lng
    if config.regresar_al_deposito and secuencia:
        d = distancia_vial(lat, lng, *config.deposito, config.factor_circuito)
        km += d
        reloj += d / config.velocidad_kmh * 60
    resultado.prioridad_violada = violaciones_prioridad(resultado.secuencia)
    resultado.minutos_total = round(reloj - config.hora_inicio)
    resultado.costo = (km + ALFA_ESPERA * espera_total + BETA_TARDANZA * tardanza_total
                       + PI_PRIORIDAD * resultado.prioridad_violada)
    resultado.km_total = round(km, 2)
    resultado.espera_total = round(espera_total)
    resultado.tardanza_total = round(tardanza_total)
    return resultado


# ----------------------------------------------------------------------------
# Fase 1: construcción por vecino más cercano con costo compuesto
# ----------------------------------------------------------------------------
def _construir(paradas, config):
    pendientes = list(paradas)
    ruta = []
    lat, lng = config.deposito
    reloj = config.hora_inicio
    while pendientes:
        # Si hay urgentes que ya se pueden atender, se elige entre ellos (RN3)
        urgentes = []
        for p in pendientes:
            if p.urgente:
                llegada = reloj + distancia_vial(lat, lng, p.lat, p.lng, config.factor_circuito) / config.velocidad_kmh * 60
                if disponible(p, llegada):
                    urgentes.append(p)
        candidatos = urgentes or pendientes
        mejor, mejor_costo, mejor_inicio = None, float("inf"), reloj
        for p in candidatos:
            d = distancia_vial(lat, lng, p.lat, p.lng, config.factor_circuito)
            llegada = reloj + d / config.velocidad_kmh * 60
            inicio = max(llegada, p.ventana_inicio) if p.ventana_inicio is not None else llegada
            espera = inicio - llegada
            tardanza = max(0, llegada - p.ventana_fin) if p.ventana_fin is not None else 0
            costo = d * FACTOR_PRIORIDAD.get(p.prioridad, 1.0) + ALFA_ESPERA * espera + BETA_TARDANZA * tardanza
            # desempate: la ventana que cierra antes va primero
            if costo < mejor_costo - 1e-9 or (
                abs(costo - mejor_costo) < 1e-9 and mejor is not None
                and (p.ventana_fin or 9999) < (mejor.ventana_fin or 9999)
            ):
                mejor, mejor_costo, mejor_inicio = p, costo, inicio
        ruta.append(mejor)
        pendientes.remove(mejor)
        reloj = mejor_inicio + config.minutos_servicio
        lat, lng = mejor.lat, mejor.lng
    return ruta


# ----------------------------------------------------------------------------
# Fase 2: mejora local 2-opt
# ----------------------------------------------------------------------------
def _dos_opt(secuencia, config, max_iter=200):
    mejor = list(secuencia)
    mejor_costo = evaluar(mejor, config).costo
    n = len(mejor)
    mejoro, iteraciones = True, 0
    while mejoro and iteraciones < max_iter:
        mejoro = False
        iteraciones += 1
        for i in range(n - 1):
            for k in range(i + 1, n):
                candidata = mejor[:i] + mejor[i:k + 1][::-1] + mejor[k + 1:]
                costo = evaluar(candidata, config).costo
                if costo < mejor_costo - 1e-6:
                    mejor, mejor_costo, mejoro = candidata, costo, True
    return mejor, iteraciones


def optimizar_secuencia(paradas, config: Configuracion | None = None):
    """Devuelve (ResultadoRuta optimizado, iteraciones 2-opt)."""
    config = config or Configuracion()
    if not paradas:
        return evaluar([], config), 0
    mejorada, iteraciones = _dos_opt(_construir(paradas, config), config)
    return evaluar(mejorada, config), iteraciones


def secuencia_sin_optimizar(paradas, config: Configuracion | None = None):
    """Línea base: el orden en que llegaron los pedidos (como se hacía manualmente)."""
    return evaluar(list(paradas), config or Configuracion())


def comparar(paradas, config: Configuracion | None = None):
    """Compara la ruta manual contra la optimizada (base del cuadro antes/después)."""
    config = config or Configuracion()
    base = secuencia_sin_optimizar(paradas, config)
    optima, iteraciones = optimizar_secuencia(paradas, config)
    ahorro_km = base.km_total - optima.km_total
    return {
        "base": base,
        "optima": optima,
        "iteraciones_2opt": iteraciones,
        "ahorro_km": round(ahorro_km, 2),
        "ahorro_pct": round(100 * ahorro_km / base.km_total, 1) if base.km_total else 0.0,
        "ahorro_min": base.minutos_total - optima.minutos_total,
    }
