"""Operaciones de lectura/escritura sobre las 3 tablas del modelo.

Tablas y columnas (según `db/schema.sql`, sin el `id` autoincremental):

- `Trafico`            → timestamp, zona, vehiculos, velocidad_promedio
- `Calidad_Aire_Hist`  → timestamp, zona, pm25, no2, o3
- `Condiciones_Clima`  → timestamp, temperatura, humedad, viento  (sin `zona`)

Diseño:

- **Inserción**: se usa `DataFrame.to_sql(..., if_exists="append", index=False)`.
  Los productores de la ingesta (`ingesta/simulador.py`, `ingesta/transformacion.py`)
  ya entregan DataFrames con exactamente estas columnas, así que `to_sql` mapea por
  nombre sin boilerplate. Antes de insertar se seleccionan solo las columnas del
  esquema (defensa simple: nunca intentamos escribir `id` ni columnas de más).

- **Consulta**: funciones parametrizadas por `zona` y/o rango de tiempo
  (`desde`/`hasta` sobre `timestamp`). Se construyen con placeholders `?` y
  `pandas.read_sql_query(..., params=...)`; NUNCA se interpolan valores con
  f-strings (evita inyección SQL). Devuelven `pandas.DataFrame`.
"""

from __future__ import annotations

import pandas as pd

from datos.conexion import conectar, get_connection

# Columnas de cada tabla (orden del esquema, sin el `id` autoincremental).
COLUMNAS_TRAFICO = ["timestamp", "zona", "vehiculos", "velocidad_promedio"]
COLUMNAS_AIRE = ["timestamp", "zona", "pm25", "no2", "o3"]
COLUMNAS_CLIMA = ["timestamp", "temperatura", "humedad", "viento"]


# --- Inserción --------------------------------------------------------------

def insertar_trafico(df: pd.DataFrame) -> int:
    """Inserta filas de tráfico. Devuelve el número de filas insertadas."""
    return _insertar(df, tabla="Trafico", columnas=COLUMNAS_TRAFICO)


def insertar_calidad_aire(df: pd.DataFrame) -> int:
    """Inserta filas de calidad del aire. Devuelve el número de filas insertadas."""
    return _insertar(df, tabla="Calidad_Aire_Hist", columnas=COLUMNAS_AIRE)


def insertar_clima(df: pd.DataFrame) -> int:
    """Inserta filas de clima (sin `zona`). Devuelve el número de filas insertadas."""
    return _insertar(df, tabla="Condiciones_Clima", columnas=COLUMNAS_CLIMA)


def _insertar(df: pd.DataFrame, *, tabla: str, columnas: list[str]) -> int:
    """Append de `df[columnas]` a `tabla` vía `to_sql`. Devuelve nº de filas.

    Se seleccionan explícitamente las columnas del esquema para no arrastrar
    columnas derivadas (p.ej. un estado de congestión) ni un índice.
    """
    faltan = [col for col in columnas if col not in df.columns]
    if faltan:
        raise ValueError(f"Al DataFrame para {tabla} le faltan columnas: {faltan}")

    subset = df[columnas]
    with conectar() as conn:
        subset.to_sql(tabla, conn, if_exists="append", index=False)
    return len(subset)


# --- Consulta ---------------------------------------------------------------

def consultar_trafico(
    zona: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> pd.DataFrame:
    """Consulta `Trafico`, filtrable por `zona` y rango de `timestamp`."""
    return _consultar("Trafico", zona=zona, desde=desde, hasta=hasta)


def consultar_calidad_aire(
    zona: str | None = None,
    desde: str | None = None,
    hasta: str | None = None,
) -> pd.DataFrame:
    """Consulta `Calidad_Aire_Hist`, filtrable por `zona` y rango de `timestamp`."""
    return _consultar("Calidad_Aire_Hist", zona=zona, desde=desde, hasta=hasta)


def consultar_clima(
    desde: str | None = None,
    hasta: str | None = None,
) -> pd.DataFrame:
    """Consulta `Condiciones_Clima`, filtrable por rango de `timestamp`.

    El clima es GLOBAL para la ciudad: no tiene `zona`, por eso este método no
    acepta ese filtro.
    """
    return _consultar("Condiciones_Clima", zona=None, desde=desde, hasta=hasta)


def _consultar(
    tabla: str,
    *,
    zona: str | None,
    desde: str | None,
    hasta: str | None,
) -> pd.DataFrame:
    """SELECT parametrizado sobre `tabla` con filtros opcionales.

    Construye la cláusula WHERE con placeholders `?` y pasa los valores como
    `params`, de modo que SQLite los trate como datos (no como SQL). Ordena por
    `timestamp` para una lectura estable en el dashboard.
    """
    clausulas: list[str] = []
    params: list[str] = []

    if zona is not None:
        clausulas.append("zona = ?")
        params.append(zona)
    if desde is not None:
        clausulas.append("timestamp >= ?")
        params.append(desde)
    if hasta is not None:
        clausulas.append("timestamp <= ?")
        params.append(hasta)

    sql = f"SELECT * FROM {tabla}"  # `tabla` es un literal interno, nunca input del usuario.
    if clausulas:
        sql += " WHERE " + " AND ".join(clausulas)
    sql += " ORDER BY timestamp"

    conn = get_connection()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()
