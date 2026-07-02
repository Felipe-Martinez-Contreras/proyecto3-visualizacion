"""Tests del dashboard (`dashboard/consultas.py`, `dashboard/figuras.py`, `dashboard/app.py`).

Se testea la lógica que importa — rangos de tiempo, filtros (zona, congestión
derivada), cruces por timestamp/zona y la construcción de las 3 figuras — sin
levantar el servidor Dash ni tocar internals de Dash.

Aislamiento: igual que en `test_repositorio.py`, cada test corre contra una BD
SQLite temporal (fixture `bd_temporal`) con `DB_PATH` apuntando a ella. Nunca se
toca `db/monitoreo.sqlite`.
"""

from datetime import datetime

import pandas as pd
import pytest

from dashboard import consultas, figuras
from dashboard.app import construir_figuras
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


# "Ahora" fijo para los tests: los rangos del dashboard se calculan hacia atrás
# desde este instante.
AHORA = datetime(2026, 7, 1, 12, 0, 0)


def _sembrar_trafico():
    """Inserta tráfico de las 3 zonas dentro de la última hora, desordenado a
    propósito, más una fila antigua (2 horas atrás) que queda FUERA del rango
    "1h" pero DENTRO de "dia".

    Estados de congestión derivados (clasificar_congestion):
    Centro 11:55 (300 veh, 18 km/h) → alto · Centro 11:45 (250, 25) → medio ·
    Norte 11:50 (150, 40) → bajo · Sur 11:50 (90, 50) → bajo · la antigua → alto.
    """
    repositorio.insertar_trafico(
        pd.DataFrame(
            [
                # Centro: dos puntos en orden invertido (para probar el orden temporal).
                {"timestamp": "2026-07-01T11:55:00", "zona": "Centro", "vehiculos": 300, "velocidad_promedio": 18.0},
                {"timestamp": "2026-07-01T11:45:00", "zona": "Centro", "vehiculos": 250, "velocidad_promedio": 25.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Norte", "vehiculos": 150, "velocidad_promedio": 40.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "vehiculos": 90, "velocidad_promedio": 50.0},
                # Fuera del rango "1h" (2 horas antes de AHORA), dentro de "dia".
                {"timestamp": "2026-07-01T10:00:00", "zona": "Centro", "vehiculos": 999, "velocidad_promedio": 10.0},
            ]
        )
    )


def _sembrar_aire():
    """Aire con el MISMO timestamp+zona que 3 lecturas de tráfico (tick compartido
    del scheduler) y una lectura huérfana (11:57, sin tráfico) que ningún cruce
    debe emparejar."""
    repositorio.insertar_calidad_aire(
        pd.DataFrame(
            [
                {"timestamp": "2026-07-01T11:55:00", "zona": "Centro", "pm25": 42.0, "no2": 30.0, "o3": 20.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Norte", "pm25": 18.0, "no2": 15.0, "o3": 25.0},
                {"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "pm25": 12.0, "no2": 10.0, "o3": 30.0},
                # Sin tráfico en este instante: queda fuera del cruce.
                {"timestamp": "2026-07-01T11:57:00", "zona": "Centro", "pm25": 99.0, "no2": 50.0, "o3": 40.0},
            ]
        )
    )


def _sembrar_clima():
    """Clima global (sin zona): un timestamp compartido por Norte y Sur (11:50),
    otro solo de Centro (11:55) y uno huérfano (10:30, sin tráfico)."""
    repositorio.insertar_clima(
        pd.DataFrame(
            [
                {"timestamp": "2026-07-01T11:50:00", "temperatura": 15.0, "humedad": 60.0, "viento": 10.0},
                {"timestamp": "2026-07-01T11:55:00", "temperatura": 16.0, "humedad": 55.0, "viento": 12.0},
                {"timestamp": "2026-07-01T10:30:00", "temperatura": 8.0, "humedad": 80.0, "viento": 5.0},
            ]
        )
    )


# --- Rangos de tiempo (últimos 5 min / 1 hora / día) --------------------------

def test_rango_default_una_hora(bd_temporal):
    _sembrar_trafico()
    df = consultas.consultar_trafico_rango(ahora=AHORA)
    # Entran las 4 filas de la última hora; la de las 10:00 queda fuera.
    assert len(df) == 4
    assert 999 not in set(df["vehiculos"])


def test_rango_cinco_minutos(bd_temporal):
    _sembrar_trafico()
    df = consultas.consultar_trafico_rango("5min", ahora=AHORA)
    # Solo la lectura de las 11:55 cae en los últimos 5 minutos.
    assert list(df["vehiculos"]) == [300]


def test_rango_dia_incluye_todo(bd_temporal):
    _sembrar_trafico()
    df = consultas.consultar_trafico_rango("dia", ahora=AHORA)
    assert len(df) == 5
    assert 999 in set(df["vehiculos"])


def test_rango_desconocido_lanza_error(bd_temporal):
    with pytest.raises(ValueError):
        consultas.consultar_trafico_rango("2semanas", ahora=AHORA)


def test_consulta_con_bd_vacia(bd_temporal):
    assert consultas.consultar_trafico_rango(ahora=AHORA).empty


# --- Filtro de zona ------------------------------------------------------------

def test_filtro_zona_en_trafico(bd_temporal):
    _sembrar_trafico()
    df = consultas.consultar_trafico_rango(zona="Centro", ahora=AHORA)
    assert set(df["zona"]) == {"Centro"}
    assert len(df) == 2


def test_filtro_zona_sin_datos_devuelve_vacio(bd_temporal):
    _sembrar_trafico()
    # Zona válida del sistema pero sin filas en el rango de 5 minutos.
    df = consultas.consultar_trafico_rango("5min", zona="Sur", ahora=AHORA)
    assert df.empty


def test_filtro_zona_en_aire(bd_temporal):
    _sembrar_aire()
    df = consultas.consultar_aire_rango(zona="Norte", ahora=AHORA)
    assert list(df["pm25"]) == [18.0]


# --- Congestión derivada (no almacenada: clasificar_congestion) -----------------

def test_agregar_congestion_deriva_estados(bd_temporal):
    _sembrar_trafico()
    df = consultas.agregar_congestion(consultas.consultar_trafico_rango(ahora=AHORA))
    estados = dict(zip(zip(df["timestamp"], df["zona"]), df["congestion"]))
    assert estados[("2026-07-01T11:55:00", "Centro")] == "alto"   # 18 km/h < 20
    assert estados[("2026-07-01T11:45:00", "Centro")] == "medio"
    assert estados[("2026-07-01T11:50:00", "Norte")] == "bajo"
    assert estados[("2026-07-01T11:50:00", "Sur")] == "bajo"


def test_agregar_congestion_no_muta_la_entrada():
    df = pd.DataFrame(
        [{"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "vehiculos": 90, "velocidad_promedio": 50.0}]
    )
    consultas.agregar_congestion(df)
    assert "congestion" not in df.columns


def test_agregar_congestion_con_df_vacio():
    df = consultas.agregar_congestion(pd.DataFrame(columns=["timestamp", "zona", "vehiculos", "velocidad_promedio"]))
    assert df.empty
    assert "congestion" in df.columns


def test_filtrar_congestion_por_estado(bd_temporal):
    _sembrar_trafico()
    df = consultas.agregar_congestion(consultas.consultar_trafico_rango(ahora=AHORA))

    bajo = consultas.filtrar_congestion(df, "bajo")
    assert sorted(bajo["zona"]) == ["Norte", "Sur"]

    alto = consultas.filtrar_congestion(df, "alto")
    assert list(alto["vehiculos"]) == [300]


def test_filtrar_congestion_todos_no_filtra(bd_temporal):
    _sembrar_trafico()
    df = consultas.agregar_congestion(consultas.consultar_trafico_rango(ahora=AHORA))
    assert len(consultas.filtrar_congestion(df, "todos")) == 4
    assert len(consultas.filtrar_congestion(df, None)) == 4


def test_filtrar_congestion_sin_coincidencias_devuelve_vacio():
    # Solo hay flujo libre: pedir "alto" deja cero filas (y no explota).
    df = pd.DataFrame(
        [{"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "vehiculos": 90, "velocidad_promedio": 50.0}]
    )
    assert consultas.filtrar_congestion(df, "alto").empty


def test_filtrar_congestion_estado_desconocido_lanza_error():
    with pytest.raises(ValueError):
        consultas.filtrar_congestion(pd.DataFrame(), "extremo")


# --- Cruces por timestamp / zona ------------------------------------------------

def test_cruce_trafico_aire_por_timestamp_y_zona(bd_temporal):
    _sembrar_trafico()
    _sembrar_aire()
    df = consultas.cruzar_trafico_aire(
        consultas.consultar_trafico_rango(ahora=AHORA),
        consultas.consultar_aire_rango(ahora=AHORA),
    )
    # Solo los 3 pares con timestamp+zona exactos; ni el tráfico de las 11:45
    # (sin aire) ni el aire de las 11:57 (sin tráfico) entran al cruce.
    assert len(df) == 3
    pares = dict(zip(zip(df["timestamp"], df["zona"]), zip(df["vehiculos"], df["pm25"])))
    assert pares[("2026-07-01T11:55:00", "Centro")] == (300, 42.0)
    assert pares[("2026-07-01T11:50:00", "Norte")] == (150, 18.0)
    assert pares[("2026-07-01T11:50:00", "Sur")] == (90, 12.0)


def test_cruce_trafico_aire_con_entrada_vacia():
    df_trafico = pd.DataFrame(
        [{"timestamp": "2026-07-01T11:50:00", "zona": "Sur", "vehiculos": 90, "velocidad_promedio": 50.0}]
    )
    assert consultas.cruzar_trafico_aire(df_trafico, pd.DataFrame()).empty
    assert consultas.cruzar_trafico_aire(pd.DataFrame(), pd.DataFrame()).empty


def test_cruce_trafico_clima_solo_por_timestamp(bd_temporal):
    _sembrar_trafico()
    _sembrar_clima()
    df = consultas.cruzar_trafico_clima(
        consultas.consultar_trafico_rango(ahora=AHORA),
        consultas.consultar_clima_rango(ahora=AHORA),
    )
    # El clima es global: la lectura de las 11:50 se asocia a Norte Y Sur; la de
    # las 11:55 a Centro. El tráfico de las 11:45 (sin clima) queda fuera.
    assert len(df) == 3
    temperaturas = dict(zip(df["zona"], df["temperatura"]))
    assert temperaturas == {"Norte": 15.0, "Sur": 15.0, "Centro": 16.0}


def test_cruce_trafico_clima_con_entrada_vacia():
    assert consultas.cruzar_trafico_clima(pd.DataFrame(), pd.DataFrame()).empty


# --- Figura de tráfico: una serie por zona, en orden temporal --------------------

def test_figura_trafico_una_serie_por_zona(bd_temporal):
    _sembrar_trafico()
    fig = figuras.figura_trafico(consultas.consultar_trafico_rango(ahora=AHORA))

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


# --- Figura 2: contaminación vs tráfico (PM2.5 vs vehículos) ---------------------

def test_figura_aire_trafico_series_correctas(bd_temporal):
    _sembrar_trafico()
    _sembrar_aire()
    cruce = consultas.cruzar_trafico_aire(
        consultas.consultar_trafico_rango(ahora=AHORA),
        consultas.consultar_aire_rango(ahora=AHORA),
    )
    fig = figuras.figura_aire_trafico(cruce)

    assert [traza.name for traza in fig.data] == ["Centro", "Norte", "Sur"]
    # x = vehículos, y = PM2.5, según lo sembrado.
    centro = fig.data[0]
    assert (list(centro.x), list(centro.y)) == ([300], [42.0])
    assert (list(fig.data[1].x), list(fig.data[1].y)) == ([150], [18.0])
    assert (list(fig.data[2].x), list(fig.data[2].y)) == ([90], [12.0])


def test_figura_aire_trafico_sin_datos_no_rompe():
    fig = figuras.figura_aire_trafico(pd.DataFrame())
    assert len(fig.data) == 0
    anotaciones = [a.text for a in fig.layout.annotations]
    assert figuras.MENSAJE_SIN_DATOS_AIRE in anotaciones


# --- Figura 3: clima vs congestión (temperatura vs tráfico) ----------------------

def test_figura_clima_trafico_series_correctas(bd_temporal):
    _sembrar_trafico()
    _sembrar_clima()
    cruce = consultas.cruzar_trafico_clima(
        consultas.consultar_trafico_rango(ahora=AHORA),
        consultas.consultar_clima_rango(ahora=AHORA),
    )
    fig = figuras.figura_clima_trafico(cruce)

    assert [traza.name for traza in fig.data] == ["Centro", "Norte", "Sur"]
    # x = temperatura, y = vehículos, según lo sembrado.
    centro = fig.data[0]
    assert (list(centro.x), list(centro.y)) == ([16.0], [300])
    assert (list(fig.data[1].x), list(fig.data[1].y)) == ([15.0], [150])
    assert (list(fig.data[2].x), list(fig.data[2].y)) == ([15.0], [90])


def test_figura_clima_trafico_sin_datos_no_rompe():
    fig = figuras.figura_clima_trafico(pd.DataFrame())
    assert len(fig.data) == 0
    anotaciones = [a.text for a in fig.layout.annotations]
    assert figuras.MENSAJE_SIN_DATOS_CLIMA in anotaciones


# --- construir_figuras: los filtros aplicados a las 3 vistas a la vez ------------

def test_construir_figuras_sin_filtros(bd_temporal):
    _sembrar_trafico()
    _sembrar_aire()
    _sembrar_clima()
    fig_trafico, fig_aire, fig_clima = construir_figuras(ahora=AHORA)
    assert [t.name for t in fig_trafico.data] == ["Centro", "Norte", "Sur"]
    assert len(fig_aire.data) == 3
    assert len(fig_clima.data) == 3


def test_construir_figuras_filtro_congestion_propaga_a_los_cruces(bd_temporal):
    _sembrar_trafico()
    _sembrar_aire()
    _sembrar_clima()
    fig_trafico, fig_aire, fig_clima = construir_figuras(congestion="bajo", ahora=AHORA)
    # Solo Norte y Sur están en "bajo": las 3 vistas muestran ese subconjunto.
    assert [t.name for t in fig_trafico.data] == ["Norte", "Sur"]
    assert [t.name for t in fig_aire.data] == ["Norte", "Sur"]
    assert [t.name for t in fig_clima.data] == ["Norte", "Sur"]


def test_construir_figuras_filtro_zona(bd_temporal):
    _sembrar_trafico()
    _sembrar_aire()
    _sembrar_clima()
    fig_trafico, fig_aire, _ = construir_figuras(zona="Centro", ahora=AHORA)
    assert [t.name for t in fig_trafico.data] == ["Centro"]
    assert [t.name for t in fig_aire.data] == ["Centro"]


def test_construir_figuras_filtros_sin_coincidencias(bd_temporal):
    # Sur solo tiene congestión "bajo": pedir "alto" deja las 3 vistas sin datos,
    # con sus anotaciones y sin excepciones.
    _sembrar_trafico()
    _sembrar_aire()
    _sembrar_clima()
    fig_trafico, fig_aire, fig_clima = construir_figuras(
        zona="Sur", congestion="alto", ahora=AHORA
    )
    assert len(fig_trafico.data) == 0
    assert len(fig_aire.data) == 0
    assert len(fig_clima.data) == 0
    assert figuras.MENSAJE_SIN_DATOS in [a.text for a in fig_trafico.layout.annotations]


def test_construir_figuras_con_bd_vacia(bd_temporal):
    fig_trafico, fig_aire, fig_clima = construir_figuras(ahora=AHORA)
    assert len(fig_trafico.data) == 0
    assert len(fig_aire.data) == 0
    assert len(fig_clima.data) == 0
