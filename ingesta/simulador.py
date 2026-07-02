"""Simulador de tráfico (TomTom/HERE simulada) y clasificación de congestión.

No hay una API de tráfico real disponible, así que la ingesta genera datos
simulados por zona (Centro, Norte, Sur): número de ``vehiculos`` y
``velocidad_promedio``, más ``timestamp`` y ``zona``, con las mismas columnas que
la tabla ``Trafico`` de ``db/schema.sql`` (sin ``id``, que es autoincremental).

La variación es **aleatoria pero controlada**: ruido acotado (±% configurable)
sobre valores base realistas por zona. El generador de aleatoriedad y el
``timestamp`` son **inyectables**, para que los tests sean deterministas y no
dependan de la hora real ni del estado global de ``random``.

El **estado de congestión** (bajo/medio/alto) NO se almacena en la BD: es un
valor DERIVADO. ``clasificar_congestion`` es una función pura sobre
``vehiculos``/``velocidad_promedio``. Se ubica aquí (y no en un módulo aparte)
para mantener junta toda la lógica de dominio del tráfico; si el dashboard llega
a necesitarla, extraerla es trivial (flexible sin abstraer de más).
"""

from __future__ import annotations

import random
from datetime import datetime

import pandas as pd

# Zonas del sistema (orden estable).
ZONAS = ["Centro", "Norte", "Sur"]

# Columnas destino (orden exacto del esquema `Trafico`, sin el `id` autoincremental).
COLUMNAS_TRAFICO = ["timestamp", "zona", "vehiculos", "velocidad_promedio"]

# Perfil base realista por zona: (vehiculos_base, velocidad_base_kmh).
# El Centro está más congestionado (más vehículos, menor velocidad) que la
# periferia; el Sur es el más fluido. Sobre estos valores se aplica el ruido.
PERFILES_ZONA = {
    "Centro": {"vehiculos": 250, "velocidad": 25.0},
    "Norte": {"vehiculos": 150, "velocidad": 40.0},
    "Sur": {"vehiculos": 100, "velocidad": 50.0},
}

# Amplitud del ruido: ±25% sobre el valor base (variación realista sin saltos absurdos).
RUIDO = 0.25

# --- Umbrales de congestión (derivada) -------------------------------------
# Congestión = más vehículos y/o menor velocidad. Umbrales documentados y
# fáciles de ajustar. Se combinan velocidad (indicador clásico de flujo) y
# volumen de vehículos (demanda/saturación).
UMBRAL_VEL_ALTO = 20.0   # km/h: por debajo, tráfico casi detenido → alto.
UMBRAL_VEL_BAJO = 40.0   # km/h: a partir de aquí, flujo libre.
UMBRAL_VEH_ALTO = 300    # vehículos: por encima, saturación → alto.
UMBRAL_VEH_BAJO = 150    # vehículos: hasta aquí, poca demanda.


def clasificar_congestion(vehiculos: int, velocidad_promedio: float) -> str:
    """Clasifica el estado de congestión en ``"bajo"``, ``"medio"`` o ``"alto"``.

    Lógica (más vehículos y/o menor velocidad ⇒ mayor congestión):

    - ``alto``: velocidad por debajo de ``UMBRAL_VEL_ALTO`` **o** vehículos por
      encima de ``UMBRAL_VEH_ALTO`` (basta con una condición crítica).
    - ``bajo``: flujo libre y poca demanda, es decir velocidad ``>=``
      ``UMBRAL_VEL_BAJO`` **y** vehículos ``<=`` ``UMBRAL_VEH_BAJO``.
    - ``medio``: cualquier caso intermedio.
    """
    if velocidad_promedio < UMBRAL_VEL_ALTO or vehiculos > UMBRAL_VEH_ALTO:
        return "alto"
    if velocidad_promedio >= UMBRAL_VEL_BAJO and vehiculos <= UMBRAL_VEH_BAJO:
        return "bajo"
    return "medio"


def generar_trafico_zona(
    zona: str,
    *,
    timestamp: str | None = None,
    rng: random.Random | None = None,
) -> dict:
    """Genera una lectura de tráfico simulada para una ``zona``.

    Aplica ruido acotado (``±RUIDO``) sobre el perfil base de la zona. El
    generador ``rng`` y el ``timestamp`` son inyectables para tests deterministas;
    por defecto usan aleatoriedad y hora actuales.

    Devuelve un ``dict`` con las claves de ``COLUMNAS_TRAFICO``.
    """
    if zona not in PERFILES_ZONA:
        raise ValueError(f"Zona desconocida: {zona!r}. Válidas: {ZONAS}")

    rng = rng if rng is not None else random.Random()
    timestamp = timestamp if timestamp is not None else datetime.now().isoformat()

    base = PERFILES_ZONA[zona]
    # Un factor de ruido independiente por variable (dentro de [1-RUIDO, 1+RUIDO]).
    vehiculos = round(base["vehiculos"] * rng.uniform(1 - RUIDO, 1 + RUIDO))
    velocidad = round(base["velocidad"] * rng.uniform(1 - RUIDO, 1 + RUIDO), 1)

    return {
        "timestamp": timestamp,
        "zona": zona,
        "vehiculos": int(vehiculos),
        "velocidad_promedio": float(velocidad),
    }


def generar_trafico(
    zonas: list[str] | None = None,
    *,
    timestamp: str | None = None,
    semilla: int | None = None,
    rng: random.Random | None = None,
) -> pd.DataFrame:
    """Genera lecturas de tráfico simuladas para varias zonas en un DataFrame.

    Por defecto genera para las tres zonas (``ZONAS``). Se devuelve un
    ``pandas.DataFrame`` (mismo criterio que ``ingesta/transformacion.py``): así
    la salida ya viene lista para transformar/persistir y encaja con el resto de
    la ingesta.

    Reproducibilidad: se puede pasar ``rng`` (un ``random.Random``) o ``semilla``
    (entero) para obtener resultados deterministas. Si se pasan ambos, manda
    ``rng``. El ``timestamp`` (compartido por todas las filas de la tanda) también
    es inyectable.
    """
    zonas = zonas if zonas is not None else ZONAS
    if rng is None:
        rng = random.Random(semilla)
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    filas = [
        generar_trafico_zona(zona, timestamp=timestamp, rng=rng) for zona in zonas
    ]
    df = pd.DataFrame(filas, columns=COLUMNAS_TRAFICO)
    return _tipar_trafico(df)


def _tipar_trafico(df: pd.DataFrame) -> pd.DataFrame:
    """Fuerza tipos coherentes con el esquema `Trafico`."""
    df = df.copy()
    df["timestamp"] = df["timestamp"].astype("string")
    df["zona"] = df["zona"].astype("string")
    df["vehiculos"] = pd.to_numeric(df["vehiculos"]).astype("int64")
    df["velocidad_promedio"] = pd.to_numeric(df["velocidad_promedio"]).astype("float64")
    return df
