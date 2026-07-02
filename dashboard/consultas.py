"""Consultas y transformaciones puras que alimentan las vistas del dashboard.

Separado de `dashboard/app.py` (runtime Dash) para que toda la lógica de los
filtros sea testeable sin levantar el servidor:

- **Rango de tiempo**: los rangos del enunciado (últimos 5 min / 1 hora / día)
  viven en ``RANGOS``; las funciones ``consultar_*_rango`` calculan el ``desde``
  hacia atrás a partir de un ``ahora`` inyectable (tests deterministas) y
  delegan en ``datos/repositorio.py`` (sin duplicar SQL).

- **Zona**: se pasa directo al repositorio (``zona=None`` ⇒ todas). El clima es
  global (sin zona), así que su consulta solo filtra por tiempo.

- **Congestión (derivada)**: el estado bajo/medio/alto NO está en la BD; se
  deriva fila a fila con ``clasificar_congestion`` (``ingesta/simulador.py``,
  función pura) vía ``agregar_congestion`` y se filtra con ``filtrar_congestion``.

- **Cruces**: las visualizaciones 2 y 3 combinan tablas con ``pandas.merge`` —
  tráfico + aire por ``timestamp`` y ``zona`` (comparten el timestamp exacto de
  cada tick del scheduler), y tráfico + clima solo por ``timestamp`` (el clima
  es global).
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd

from datos import repositorio
from ingesta.simulador import clasificar_congestion

# --- Rangos de tiempo (filtro del enunciado: últimos 5 min / 1 hora / día) ---

RANGOS: dict[str, dict] = {
    "5min": {"etiqueta": "Últimos 5 minutos", "delta": timedelta(minutes=5)},
    "1h": {"etiqueta": "Última hora", "delta": timedelta(hours=1)},
    "dia": {"etiqueta": "Último día", "delta": timedelta(days=1)},
}

# Default razonable: la última hora (suficiente historia para ver tendencia,
# sin cargar el día completo en cada refresco).
RANGO_DEFAULT = "1h"

# Estados de congestión (derivados, mismo orden que devuelve `clasificar_congestion`).
ESTADOS_CONGESTION = ["bajo", "medio", "alto"]


def _desde(rango: str, ahora: datetime | None) -> str:
    """Timestamp ISO del inicio de la ventana: ``ahora - RANGOS[rango]``."""
    if rango not in RANGOS:
        raise ValueError(f"Rango desconocido: {rango!r}. Válidos: {list(RANGOS)}")
    if ahora is None:
        ahora = datetime.now()
    return (ahora - RANGOS[rango]["delta"]).isoformat()


# --- Consultas por rango (delegan en datos/repositorio.py) -------------------

def consultar_trafico_rango(
    rango: str = RANGO_DEFAULT,
    zona: str | None = None,
    ahora: datetime | None = None,
) -> pd.DataFrame:
    """Tráfico dentro del rango, opcionalmente filtrado por ``zona``."""
    return repositorio.consultar_trafico(zona=zona, desde=_desde(rango, ahora))


def consultar_aire_rango(
    rango: str = RANGO_DEFAULT,
    zona: str | None = None,
    ahora: datetime | None = None,
) -> pd.DataFrame:
    """Calidad del aire dentro del rango, opcionalmente filtrada por ``zona``."""
    return repositorio.consultar_calidad_aire(zona=zona, desde=_desde(rango, ahora))


def consultar_clima_rango(
    rango: str = RANGO_DEFAULT,
    ahora: datetime | None = None,
) -> pd.DataFrame:
    """Clima dentro del rango. Global (sin ``zona``, ver esquema)."""
    return repositorio.consultar_clima(desde=_desde(rango, ahora))


# --- Congestión derivada ------------------------------------------------------

def agregar_congestion(df_trafico: pd.DataFrame) -> pd.DataFrame:
    """Devuelve una copia con la columna derivada ``congestion`` (bajo/medio/alto).

    No modifica el DataFrame de entrada ni toca la BD: la congestión es siempre
    derivada, nunca almacenada. Con un DataFrame vacío devuelve otro vacío con
    la columna presente (para que los filtros aguas abajo no fallen).
    """
    df = df_trafico.copy()
    if df.empty:
        df["congestion"] = pd.Series(dtype="string")
        return df
    df["congestion"] = [
        clasificar_congestion(int(vehiculos), float(velocidad))
        for vehiculos, velocidad in zip(df["vehiculos"], df["velocidad_promedio"])
    ]
    return df


def filtrar_congestion(df_trafico: pd.DataFrame, estado: str | None) -> pd.DataFrame:
    """Filtra las filas cuyo estado derivado coincide con ``estado``.

    ``estado`` en ``None``/``"todos"`` no filtra. Si el DataFrame aún no trae la
    columna ``congestion``, se deriva aquí mismo. Puede devolver un DataFrame
    vacío (cero coincidencias): las figuras lo manejan con su anotación.
    """
    if estado is None or estado == "todos":
        return df_trafico
    if estado not in ESTADOS_CONGESTION:
        raise ValueError(
            f"Estado de congestión desconocido: {estado!r}. Válidos: {ESTADOS_CONGESTION}"
        )
    df = df_trafico if "congestion" in df_trafico.columns else agregar_congestion(df_trafico)
    return df[df["congestion"] == estado]


# --- Cruces para las visualizaciones 2 y 3 ------------------------------------

def cruzar_trafico_aire(df_trafico: pd.DataFrame, df_aire: pd.DataFrame) -> pd.DataFrame:
    """Cruza tráfico y calidad del aire por ``timestamp`` + ``zona`` (inner join).

    Cada tick del scheduler inserta tráfico y aire con el MISMO timestamp, así
    que el merge exacto empareja las lecturas del mismo instante y zona. Filas
    sin contraparte quedan fuera (no se inventan pares).
    """
    if df_trafico.empty or df_aire.empty:
        return pd.DataFrame(columns=["timestamp", "zona", "vehiculos", "pm25"])
    return pd.merge(df_trafico, df_aire, on=["timestamp", "zona"], how="inner")


def cruzar_trafico_clima(df_trafico: pd.DataFrame, df_clima: pd.DataFrame) -> pd.DataFrame:
    """Cruza tráfico y clima solo por ``timestamp`` (el clima es global, sin zona).

    La misma lectura de clima se asocia a las tres zonas de ese instante (inner
    join 1→N por timestamp).
    """
    if df_trafico.empty or df_clima.empty:
        return pd.DataFrame(columns=["timestamp", "zona", "vehiculos", "temperatura"])
    return pd.merge(df_trafico, df_clima, on="timestamp", how="inner")
