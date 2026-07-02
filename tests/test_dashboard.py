"""Tests del dashboard (`dashboard/figuras.py` y `dashboard/app.py`).

Se testea la lógica que importa — la ventana de consulta y la construcción de la
figura a partir de datos — sin levantar el servidor Dash ni tocar internals de Dash.

Aislamiento: igual que en `test_repositorio.py`, cada test corre contra una BD
SQLite temporal (fixture `bd_temporal`) con `DB_PATH` apuntando a ella. Nunca se
toca `db/monitoreo.sqlite`.
"""

from datetime import datetime

import pandas as pd
import pytest

from dashboard import figuras
from dashboard.app import consultar_trafico_reciente
from datos import repositorio
from datos.conexion import get_db_path
from db.init_db import init_db, SCHEMA_PATH


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """Crea una BD temporal aislada y apunta `DB_PATH` a ella durante el test."""
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db(db_path=db_path, schema_path=SCHEMA_PATH)
    assert get_db_path() == db_path
    return db_path


# "Ahora" fijo para los tests: la ventana del dashboard se calcula hacia atrás
# desde este instante (últimos 30 min por defecto).
AHORA = datetime(2026, 7, 1, 12, 0, 0)


def _sembrar_trafico():
    """Inserta tráfico de las 3 zonas dentro de la ventana, desordenado a propósito,
    más una fila antigua (2 horas atrás) que debe quedar FUERA de la ventana."""
    repositorio.insertar_trafico(
        pd.DataFrame(
            [
                # Centro: dos puntos en orden invertido (para probar el orden temporal).
                {"timestamp": "2026-07-01T11:55:00", "zona": "Centro", "vehiculos": 300, "velocidad_promedio": 18.0},
                {"timestamp": "2026-07-01T11:45:00", "zona": "Centro", "vehiculos": 250, "velocidad_promedio": 25.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Norte", "vehiculos": 150, "velocidad_promedio": 40.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "vehiculos": 90, "velocidad_promedio": 50.0},
                # Fuera de la ventana de 30 min (2 horas antes de AHORA).
                {"timestamp": "2026-07-01T10:00:00", "zona": "Centro", "vehiculos": 999, "velocidad_promedio": 10.0},
            ]
        )
    )


# --- Ventana de consulta -----------------------------------------------------

def test_consulta_reciente_respeta_la_ventana(bd_temporal):
    _sembrar_trafico()
    df = consultar_trafico_reciente(ahora=AHORA)
    # Entran las 4 filas recientes; la de las 10:00 queda fuera.
    assert len(df) == 4
    assert 999 not in set(df["vehiculos"])


def test_consulta_reciente_con_bd_vacia(bd_temporal):
    assert consultar_trafico_reciente(ahora=AHORA).empty


# --- Figura de tráfico: una serie por zona, en orden temporal ----------------

def test_figura_trafico_una_serie_por_zona(bd_temporal):
    _sembrar_trafico()
    fig = figuras.figura_trafico(consultar_trafico_reciente(ahora=AHORA))

    # Una traza por zona, con las zonas como nombre de serie.
    assert [traza.name for traza in fig.data] == ["Centro", "Norte", "Sur"]

    # Los valores de cada zona son los sembrados (Centro ordenado temporalmente).
    centro = fig.data[0]
    assert list(centro.y) == [250, 300]
    assert list(centro.x) == sorted(centro.x)  # orden temporal ascendente
    assert list(fig.data[1].y) == [150]
    assert list(fig.data[2].y) == [90]


def test_figura_trafico_omite_zonas_sin_datos():
    # Solo hay datos de Norte: la figura no debe inventar series vacías.
    df = pd.DataFrame(
        [{"timestamp": "2026-07-01T11:50:00", "zona": "Norte", "vehiculos": 150, "velocidad_promedio": 40.0}]
    )
    fig = figuras.figura_trafico(df)
    assert [traza.name for traza in fig.data] == ["Norte"]


def test_figura_trafico_sin_datos_no_rompe():
    fig = figuras.figura_trafico(pd.DataFrame())
    # Figura válida sin trazas y con la anotación explicativa.
    assert len(fig.data) == 0
    anotaciones = [a.text for a in fig.layout.annotations]
    assert figuras.MENSAJE_SIN_DATOS in anotaciones
