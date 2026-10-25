"""
Geometría sobre la superficie terrestre.

Fórmula de Haversine: distancia del círculo máximo entre dos puntos (φ1, λ1) y (φ2, λ2)

    a = sin²(Δφ/2) + cos φ1 · cos φ2 · sin²(Δλ/2)
    c = 2 · atan2(√a, √(1−a))
    d = R · c            con R = 6371 km (radio medio de la Tierra)

Como los vehículos circulan por calles y no en línea recta, la distancia vial se
estima multiplicando por un factor de circuito k (≈1.3 en ciudades peruanas):

    d_vial = k · d_haversine
"""
from math import asin, cos, radians, sin, sqrt

RADIO_TIERRA_KM = 6371.0


def haversine(lat1, lng1, lat2, lng2):
    """Distancia en línea recta (km) entre dos coordenadas."""
    phi1, phi2 = radians(lat1), radians(lat2)
    dphi = radians(lat2 - lat1)
    dlmb = radians(lng2 - lng1)
    a = sin(dphi / 2) ** 2 + cos(phi1) * cos(phi2) * sin(dlmb / 2) ** 2
    return 2 * RADIO_TIERRA_KM * asin(sqrt(a))


def distancia_vial(lat1, lng1, lat2, lng2, factor=1.3):
    """Distancia estimada por calles (km)."""
    return haversine(lat1, lng1, lat2, lng2) * factor


def matriz_distancias(coordenadas, factor=1.3):
    """
    Matriz D de n×n con D[i][j] = distancia vial entre i y j.
    Es simétrica (D[i][j] = D[j][i]) y su diagonal es 0.
    """
    n = len(coordenadas)
    matriz = [[0.0] * n for _ in range(n)]
    for i in range(n):
        for j in range(i + 1, n):
            d = distancia_vial(*coordenadas[i], *coordenadas[j], factor=factor)
            matriz[i][j] = matriz[j][i] = d
    return matriz


def longitud_polilinea(coordenadas, factor=1.0):
    """Suma de tramos consecutivos (usado para km reales a partir del GPS)."""
    total = 0.0
    for (a, b), (c, d) in zip(coordenadas, coordenadas[1:]):
        total += haversine(a, b, c, d)
    return total * factor
