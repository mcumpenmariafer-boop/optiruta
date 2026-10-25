"""
Asignación de pedidos a vehículos — Bin Packing bidimensional (peso y bultos).

MODELO
    Vehículos v ∈ V con capacidades Ck_v (kg) y Cb_v (bultos).
    Pedidos p ∈ P con peso w_p y bultos b_p.
    x_pv = 1 si el pedido p va en el vehículo v.

    Restricciones (regla de negocio "la suma de pesos no supera la capacidad"):
        Σ_p w_p · x_pv ≤ Ck_v      ∀ v
        Σ_p b_p · x_pv ≤ Cb_v      ∀ v
        Σ_v x_pv ≤ 1               ∀ p  (un pedido en a lo más un vehículo)
        Σ_p x_pv ≤ N_max           ∀ v  (límite de paradas por jornada)

    Objetivo: atender la mayor cantidad de pedidos priorizando los URGENTES y
    agrupando por zona (menos km porque los puntos de una zona están cerca).

ALGORITMO: First Fit Decreasing (FFD) con afinidad de zona
    1. Ordenar pedidos: URGENTE primero, luego ALTA, NORMAL; dentro de cada nivel,
       por peso descendente (los grandes son los difíciles de acomodar).
    2. Para cada pedido, probar primero los vehículos que ya llevan su zona
       (afinidad) y luego el resto, en orden de capacidad descendente.
    3. Se coloca en el PRIMER vehículo donde quepa (first fit).
    FFD garantiza usar como máximo 11/9·OPT + 6/9 vehículos (Dósa, 2007).
"""
from dataclasses import dataclass, field

ORDEN_PRIORIDAD = {"URGENTE": 0, "ALTA": 1, "NORMAL": 2}


@dataclass
class ItemPedido:
    id: int
    peso_kg: float
    bultos: int
    zona_id: int | None = None
    prioridad: str = "NORMAL"


@dataclass
class Contenedor:
    id: int
    capacidad_kg: float
    capacidad_bultos: int
    max_paradas: int = 999
    carga_kg: float = 0.0
    carga_bultos: int = 0
    pedidos: list = field(default_factory=list)
    zonas: set = field(default_factory=set)

    def cabe(self, item: ItemPedido):
        return (self.carga_kg + item.peso_kg <= self.capacidad_kg + 1e-9
                and self.carga_bultos + item.bultos <= self.capacidad_bultos
                and len(self.pedidos) < self.max_paradas)

    def agregar(self, item: ItemPedido):
        self.carga_kg += item.peso_kg
        self.carga_bultos += item.bultos
        self.pedidos.append(item.id)
        if item.zona_id is not None:
            self.zonas.add(item.zona_id)

    @property
    def uso_kg_pct(self):
        return round(100 * self.carga_kg / self.capacidad_kg, 1) if self.capacidad_kg else 0


def validar_capacidad(items, capacidad_kg, capacidad_bultos):
    """Devuelve (ok, peso_total, bultos_total)."""
    peso = sum(i.peso_kg for i in items)
    bultos = sum(i.bultos for i in items)
    return peso <= capacidad_kg + 1e-9 and bultos <= capacidad_bultos, round(peso, 2), bultos


def asignar_ffd(items, contenedores):
    """Devuelve (contenedores con pedidos, lista de items sin asignar)."""
    ordenados = sorted(items, key=lambda i: (ORDEN_PRIORIDAD.get(i.prioridad, 2), -i.peso_kg))
    contenedores = sorted(contenedores, key=lambda c: -c.capacidad_kg)
    sin_asignar = []
    for item in ordenados:
        afines = [c for c in contenedores if item.zona_id in c.zonas]
        resto = [c for c in contenedores if c not in afines]
        destino = next((c for c in afines + resto if c.cabe(item)), None)
        if destino:
            destino.agregar(item)
        else:
            sin_asignar.append(item)
    return contenedores, sin_asignar
