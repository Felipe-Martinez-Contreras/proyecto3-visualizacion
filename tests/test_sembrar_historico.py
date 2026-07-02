"""Tests del script de siembra de históricos (`db/sembrar_historico.py`).

Aislamiento: cada test corre contra una BD SQLite temporal (fixture `bd_temporal`,
mismo patrón que `tests/test_repositorio.py`) con `DB_PATH` apuntando a `tmp_path`.
Nunca se toca `db/monitoreo.sqlite` y no hay red: todo es sintético y determinista
(semilla fija + `ahora` inyectado).
"""

from datetime import datetime

import pandas as pd
import pytest

from datos import repositorio
from db.init_db import init_db, SCHEMA_PATH
from db.sembrar_historico import sembrar
from ingesta.simulador import ZONAS


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """Crea una BD temporal aislada y apunta `DB_PATH` a ella durante el test."""
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db(db_path=db_path, schema_path=SCHEMA_PATH)
    return db_path


# `ahora` fijo para tests deterministas (mediodía: cubre 10:00–12:00 con 2 h).
AHORA = datetime(2026, 7, 1, 12, 0, 0)


def _sembrar_chico(**kwargs):
    """Siembra estándar de los tests: 2 h, tick cada 10 min, semilla fija."""
    params = dict(horas=2, paso_minutos=10, semilla=42, ahora=AHORA)
    params.update(kwargs)
    return sembrar(**params)


# --- Conteos y resumen -------------------------------------------------------

def test_conteos_por_tabla(bd_temporal):
    resumen = _sembrar_chico()
    # 2 h / 10 min = 12 pasos → 13 ticks (ambos extremos incluidos).
    ticks = 13
    assert resumen["trafico"] == ticks * len(ZONAS)
    assert resumen["aire"] == ticks * len(ZONAS)
    assert resumen["clima"] == ticks

    assert len(repositorio.consultar_trafico()) == ticks * len(ZONAS)
    assert len(repositorio.consultar_calidad_aire()) == ticks * len(ZONAS)
    assert len(repositorio.consultar_clima()) == ticks

    # El rango del resumen coincide con lo sembrado.
    assert resumen["desde"] == "2026-07-01T10:00:00"
    assert resumen["hasta"] == "2026-07-01T12:00:00"


def test_timestamps_compartidos_entre_tablas(bd_temporal):
    _sembrar_chico()
    ts_trafico = set(repositorio.consultar_trafico()["timestamp"])
    ts_aire = set(repositorio.consultar_calidad_aire()["timestamp"])
    ts_clima = set(repositorio.consultar_clima()["timestamp"])
    # Cada tick comparte EL MISMO timestamp en las 3 tablas (cruces del dashboard).
    assert ts_trafico == ts_aire == ts_clima
    assert len(ts_clima) == 13

    # En cada tick hay una fila de tráfico por zona.
    trafico = repositorio.consultar_trafico()
    for _, grupo in trafico.groupby("timestamp"):
        assert set(grupo["zona"]) == set(ZONAS)


# --- Plausibilidad de los valores -------------------------------------------

def test_rangos_de_valores_plausibles(bd_temporal):
    # Día completo para recorrer toda la curva de clima y tráfico.
    sembrar(horas=24, paso_minutos=30, semilla=42, ahora=AHORA)

    trafico = repositorio.consultar_trafico()
    assert (trafico["vehiculos"] > 0).all()
    assert (trafico["velocidad_promedio"] > 0).all()

    aire = repositorio.consultar_calidad_aire()
    assert (aire["pm25"] > 0).all()
    assert (aire["no2"] > 0).all()
    assert (aire["o3"] >= 0).all()

    clima = repositorio.consultar_clima()
    # Invierno santiaguino: entre -2 y 20 °C.
    assert clima["temperatura"].between(-2, 20).all()
    assert clima["humedad"].between(20, 100).all()
    assert (clima["viento"] >= 0).all()


def test_hora_punta_supera_al_valle(bd_temporal):
    sembrar(horas=24, paso_minutos=15, semilla=42, ahora=AHORA)
    trafico = repositorio.consultar_trafico()
    horas = pd.to_datetime(trafico["timestamp"]).dt.hour

    punta = trafico[horas.isin([7, 8, 9, 18, 19, 20])]
    valle = trafico[horas.isin([0, 1, 2, 3, 4, 5, 6])]
    assert not punta.empty and not valle.empty
    # Punta: más vehículos y menos velocidad que el valle nocturno.
    assert punta["vehiculos"].mean() > valle["vehiculos"].mean()
    assert punta["velocidad_promedio"].mean() < valle["velocidad_promedio"].mean()


def test_correlacion_pm25_vehiculos(bd_temporal):
    sembrar(horas=24, paso_minutos=15, semilla=42, ahora=AHORA)
    trafico = repositorio.consultar_trafico()
    aire = repositorio.consultar_calidad_aire()

    cruce = trafico.merge(aire, on=["timestamp", "zona"])
    assert len(cruce) == len(trafico)
    # Correlación positiva visible en el scatter PM2.5 vs vehículos.
    assert cruce["vehiculos"].corr(cruce["pm25"]) > 0


# --- Opción --limpiar ---------------------------------------------------------

def test_sin_limpiar_siembra_encima(bd_temporal):
    r1 = _sembrar_chico()
    _sembrar_chico()
    assert len(repositorio.consultar_trafico()) == 2 * r1["trafico"]
    assert len(repositorio.consultar_clima()) == 2 * r1["clima"]


def test_limpiar_borra_lo_previo(bd_temporal):
    _sembrar_chico()
    r2 = _sembrar_chico(limpiar=True)
    assert len(repositorio.consultar_trafico()) == r2["trafico"]
    assert len(repositorio.consultar_calidad_aire()) == r2["aire"]
    assert len(repositorio.consultar_clima()) == r2["clima"]
