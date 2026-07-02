"""Tests del motor de ingesta (`ingesta/scheduler.py`).

Se prueba SOLO el "tick" (una iteración), nunca el bucle real de APScheduler.

Aislamiento (patrón del Hito 3): BD SQLite temporal en `tmp_path` con `DB_PATH`
apuntando a ella y el esquema aplicado con `db.init_db.init_db`. Nunca se toca
`db/monitoreo.sqlite`.

Sin red: el simulador de tráfico corre REAL (no usa red), mientras que las fuentes
de red (`ingesta.aire.obtener_calidad_aire_zona` y `ingesta.apis.obtener_clima`)
se mockean. El `timestamp` se inyecta para no depender de la hora real.
"""

import pandas as pd
import pytest

from datos import repositorio
from db.init_db import init_db, SCHEMA_PATH
from ingesta import scheduler, simulador

TIMESTAMP = "2026-07-01T12:00:00"


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """BD temporal aislada; `DB_PATH` apunta a ella durante el test."""
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db(db_path=db_path, schema_path=SCHEMA_PATH)
    return db_path


def _aire_falso(zona, fuente=None):
    """Sustituto sin red de `obtener_calidad_aire_zona` (esquema común)."""
    return pd.DataFrame(
        [{"timestamp": "IGNORADO", "zona": zona, "pm25": 10.0, "no2": 20.0, "o3": 30.0}]
    )


def _clima_falso(latitud, longitud, **kwargs):
    """Sustituto sin red de `apis.obtener_clima` (formato Open-Meteo `current`)."""
    return {
        "current": {
            "time": "2026-07-01T00:00",
            "temperature_2m": 15.3,
            "relative_humidity_2m": 60,
            "wind_speed_10m": 12.4,
        }
    }


def test_tick_completo_inserta_en_las_tres_tablas(bd_temporal, monkeypatch):
    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falso)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_falso)

    resumen = scheduler.ejecutar_tick(timestamp=TIMESTAMP)

    # Resumen: 3 zonas de tráfico, 3 de aire, 1 fila de clima global.
    assert resumen == {"trafico": 3, "aire": 3, "clima": 1}

    trafico = repositorio.consultar_trafico()
    aire_df = repositorio.consultar_calidad_aire()
    clima = repositorio.consultar_clima()

    assert len(trafico) == 3
    assert set(trafico["zona"]) == set(simulador.ZONAS)
    assert len(aire_df) == 3
    assert set(aire_df["zona"]) == set(simulador.ZONAS)
    assert len(clima) == 1
    assert clima.iloc[0]["temperatura"] == 15.3


def test_tick_usa_timestamp_compartido(bd_temporal, monkeypatch):
    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falso)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_falso)

    scheduler.ejecutar_tick(timestamp=TIMESTAMP)

    # Todas las filas de la iteración comparten el timestamp inyectado.
    assert set(repositorio.consultar_trafico()["timestamp"]) == {TIMESTAMP}
    assert set(repositorio.consultar_calidad_aire()["timestamp"]) == {TIMESTAMP}
    assert set(repositorio.consultar_clima()["timestamp"]) == {TIMESTAMP}


def test_tick_sin_timestamp_usa_hora_actual(bd_temporal, monkeypatch):
    """Sin `timestamp` explícito no falla y usa la hora actual (una sola tanda)."""
    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falso)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_falso)

    resumen = scheduler.ejecutar_tick()

    assert resumen["trafico"] == 3
    # Un único timestamp compartido por toda la iteración.
    assert repositorio.consultar_trafico()["timestamp"].nunique() == 1


def test_tick_sigue_si_falla_el_clima(bd_temporal, monkeypatch):
    """Si el clima lanza excepción, tráfico y aire igual se insertan."""
    def _clima_roto(*args, **kwargs):
        raise RuntimeError("sin red")

    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falso)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_roto)

    resumen = scheduler.ejecutar_tick(timestamp=TIMESTAMP)

    assert resumen["trafico"] == 3
    assert resumen["aire"] == 3
    assert resumen["clima"] == 0
    assert len(repositorio.consultar_trafico()) == 3
    assert len(repositorio.consultar_calidad_aire()) == 3
    assert repositorio.consultar_clima().empty


def test_tick_sigue_si_falla_una_zona_de_aire(bd_temporal, monkeypatch):
    """Si una zona de aire falla, las otras zonas y el resto igual se insertan."""
    def _aire_falla_centro(zona, fuente=None):
        if zona == "Centro":
            raise RuntimeError("sin red")
        return _aire_falso(zona)

    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falla_centro)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_falso)

    resumen = scheduler.ejecutar_tick(timestamp=TIMESTAMP)

    # Solo 2 de 3 zonas de aire entran; tráfico y clima intactos.
    assert resumen["aire"] == 2
    assert resumen["trafico"] == 3
    assert resumen["clima"] == 1
    zonas_aire = set(repositorio.consultar_calidad_aire()["zona"])
    assert zonas_aire == {"Norte", "Sur"}


def test_tick_sigue_si_falla_el_trafico(bd_temporal, monkeypatch):
    """Si el simulador de tráfico falla, aire y clima igual se insertan."""
    def _trafico_roto(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(scheduler.simulador, "generar_trafico", _trafico_roto)
    monkeypatch.setattr(scheduler.aire, "obtener_calidad_aire_zona", _aire_falso)
    monkeypatch.setattr(scheduler.apis, "obtener_clima", _clima_falso)

    resumen = scheduler.ejecutar_tick(timestamp=TIMESTAMP)

    assert resumen["trafico"] == 0
    assert resumen["aire"] == 3
    assert resumen["clima"] == 1
    assert repositorio.consultar_trafico().empty
