"""Tests de la capa de acceso a datos (`datos/conexion.py` y `datos/repositorio.py`).

Aislamiento: cada test corre contra una BD SQLite temporal (fixture `bd_temporal`)
creada en `tmp_path` aplicando `db/schema.sql`, con `DB_PATH` apuntando a ese
archivo. Nunca se toca `db/monitoreo.sqlite`.
"""

import importlib

import pandas as pd
import pytest

from datos import repositorio
from datos.conexion import get_db_path
from db.init_db import init_db, SCHEMA_PATH


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """Crea una BD temporal aislada y apunta `DB_PATH` a ella durante el test."""
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db(db_path=db_path, schema_path=SCHEMA_PATH)
    # `get_db_path()` lee `DB_PATH` en cada llamada, así que basta con el env.
    assert get_db_path() == db_path
    return db_path


# --- DataFrames de ejemplo (mismas columnas que los productores de la ingesta) ---

def _df_trafico():
    return pd.DataFrame(
        [
            {"timestamp": "2026-07-01T10:00:00", "zona": "Centro", "vehiculos": 250, "velocidad_promedio": 25.0},
            {"timestamp": "2026-07-01T11:00:00", "zona": "Norte", "vehiculos": 150, "velocidad_promedio": 40.0},
            {"timestamp": "2026-07-01T12:00:00", "zona": "Centro", "vehiculos": 300, "velocidad_promedio": 18.0},
        ]
    )


def _df_aire():
    return pd.DataFrame(
        [
            {"timestamp": "2026-07-01T10:00:00", "zona": "Centro", "pm25": 12.5, "no2": 20.0, "o3": 30.0},
            {"timestamp": "2026-07-01T11:00:00", "zona": "Sur", "pm25": 8.0, "no2": 15.0, "o3": 25.0},
        ]
    )


def _df_clima():
    return pd.DataFrame(
        [
            {"timestamp": "2026-07-01T10:00:00", "temperatura": 15.3, "humedad": 60.0, "viento": 12.4},
            {"timestamp": "2026-07-01T12:00:00", "temperatura": 18.1, "humedad": 55.0, "viento": 9.0},
        ]
    )


# --- Round-trip: insertar y leer de vuelta ---------------------------------

def test_roundtrip_trafico(bd_temporal):
    n = repositorio.insertar_trafico(_df_trafico())
    assert n == 3

    df = repositorio.consultar_trafico()
    assert len(df) == 3
    # Las columnas del esquema aparecen (más `id` autoincremental de SELECT *).
    assert set(repositorio.COLUMNAS_TRAFICO).issubset(df.columns)
    assert "id" in df.columns  # id lo pone la BD, no lo insertamos nosotros.
    assert set(df["zona"]) == {"Centro", "Norte"}


def test_roundtrip_calidad_aire(bd_temporal):
    n = repositorio.insertar_calidad_aire(_df_aire())
    assert n == 2

    df = repositorio.consultar_calidad_aire()
    assert len(df) == 2
    assert set(repositorio.COLUMNAS_AIRE).issubset(df.columns)
    assert df.iloc[0]["pm25"] == 12.5


def test_roundtrip_clima_sin_zona(bd_temporal):
    n = repositorio.insertar_clima(_df_clima())
    assert n == 2

    df = repositorio.consultar_clima()
    assert len(df) == 2
    assert set(repositorio.COLUMNAS_CLIMA).issubset(df.columns)
    # El clima es global: no debe existir columna `zona`.
    assert "zona" not in df.columns


# --- Filtro por zona --------------------------------------------------------

def test_filtro_por_zona_trafico(bd_temporal):
    repositorio.insertar_trafico(_df_trafico())

    centro = repositorio.consultar_trafico(zona="Centro")
    assert len(centro) == 2
    assert set(centro["zona"]) == {"Centro"}

    norte = repositorio.consultar_trafico(zona="Norte")
    assert len(norte) == 1


def test_filtro_por_zona_aire(bd_temporal):
    repositorio.insertar_calidad_aire(_df_aire())
    sur = repositorio.consultar_calidad_aire(zona="Sur")
    assert len(sur) == 1
    assert sur.iloc[0]["zona"] == "Sur"


# --- Filtro por rango de timestamp -----------------------------------------

def test_filtro_por_rango_timestamp(bd_temporal):
    repositorio.insertar_trafico(_df_trafico())

    # desde/hasta inclusivos: incluye 11:00 y 12:00, excluye 10:00.
    df = repositorio.consultar_trafico(desde="2026-07-01T11:00:00", hasta="2026-07-01T12:00:00")
    assert list(df["timestamp"]) == ["2026-07-01T11:00:00", "2026-07-01T12:00:00"]

    # Solo cota inferior.
    df2 = repositorio.consultar_trafico(desde="2026-07-01T11:30:00")
    assert list(df2["timestamp"]) == ["2026-07-01T12:00:00"]


def test_filtro_zona_y_rango_combinados(bd_temporal):
    repositorio.insertar_trafico(_df_trafico())
    df = repositorio.consultar_trafico(zona="Centro", desde="2026-07-01T11:00:00")
    # Solo la fila Centro de las 12:00 (la de las 10:00 queda fuera del rango).
    assert len(df) == 1
    assert df.iloc[0]["timestamp"] == "2026-07-01T12:00:00"


def test_filtro_rango_clima(bd_temporal):
    repositorio.insertar_clima(_df_clima())
    df = repositorio.consultar_clima(desde="2026-07-01T11:00:00")
    assert len(df) == 1
    assert df.iloc[0]["timestamp"] == "2026-07-01T12:00:00"


# --- Defensa: columnas faltantes -------------------------------------------

def test_insertar_falla_si_faltan_columnas(bd_temporal):
    df_malo = pd.DataFrame([{"timestamp": "2026-07-01T10:00:00", "zona": "Centro"}])
    with pytest.raises(ValueError):
        repositorio.insertar_trafico(df_malo)


# --- Aislamiento: la BD por defecto no se toca -----------------------------

def test_consulta_vacia_en_bd_recien_creada(bd_temporal):
    assert repositorio.consultar_trafico().empty
    assert repositorio.consultar_calidad_aire().empty
    assert repositorio.consultar_clima().empty
