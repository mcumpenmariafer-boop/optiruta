"""
Indicadores de eficiencia y sostenibilidad.

    Combustible (L)   = km · r_v / 100           r_v = rendimiento del vehículo (L/100 km)
    Costo (S/)        = combustible · precio_litro
    CO2 (kg)          = combustible · FE          FE = factor de emisión del combustible
                                                  (gasolina 2.31 kg/L, diésel 2.68 kg/L; IPCC 2006)
    % entrega         = entregados / asignados · 100
    Productividad     = entregados / horas de ruta
"""

RENDIMIENTO_L_100KM = {"MOTO": 3.0, "FURGONETA": 10.0, "CAMION": 18.0}
COMBUSTIBLE = {"MOTO": "GASOLINA", "FURGONETA": "GASOLINA", "CAMION": "DIESEL"}
FACTOR_EMISION = {"GASOLINA": 2.31, "DIESEL": 2.68}


def combustible_litros(km, tipo_vehiculo):
    return km * RENDIMIENTO_L_100KM.get(tipo_vehiculo, 10.0) / 100


def co2_kg(km, tipo_vehiculo):
    litros = combustible_litros(km, tipo_vehiculo)
    return litros * FACTOR_EMISION[COMBUSTIBLE.get(tipo_vehiculo, "GASOLINA")]


def costo_combustible(km, tipo_vehiculo, precio_litro=4.30):
    return combustible_litros(km, tipo_vehiculo) * precio_litro


def porcentaje(parte, total):
    return round(100 * parte / total, 1) if total else 0.0


def impacto(km_base, km_optimo, tipo_vehiculo, precio_litro=4.30):
    """Resumen del ahorro de una ruta optimizada frente a la manual."""
    ahorro_km = max(0.0, km_base - km_optimo)
    return {
        "ahorro_km": round(ahorro_km, 2),
        "ahorro_litros": round(combustible_litros(ahorro_km, tipo_vehiculo), 2),
        "ahorro_soles": round(costo_combustible(ahorro_km, tipo_vehiculo, precio_litro), 2),
        "co2_evitado_kg": round(co2_kg(ahorro_km, tipo_vehiculo), 2),
    }
