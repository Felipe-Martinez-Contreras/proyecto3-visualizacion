"""Tests del simulador de tráfico y de la clasificación de congestión.

Sin red ni BD: el simulador recibe una semilla/RNG y un timestamp inyectables,
así que los resultados son deterministas y verificables.
"""

import random

from ingesta.simulador import (
    COLUMNAS_TRAFICO,
    PERFILES_ZONA,
    RUIDO,
    UMBRAL_VEH_ALTO,
    UMBRAL_VEH_BAJO,
    UMBRAL_VEL_ALTO,
    UMBRAL_VEL_BAJO,
    ZONAS,
    clasificar_congestion,
    generar_trafico,
    generar_trafico_zona,
)

TS = "2026-07-01T12:00:00"

# --- Simulador: columnas y zonas -------------------------------------------


def test_genera_las_tres_zonas_con_columnas_del_esquema():
    df = generar_trafico(timestamp=TS, semilla=42)

    assert list(df.columns) == COLUMNAS_TRAFICO
    assert list(df["zona"]) == ZONAS  # Centro, Norte, Sur (orden estable)
    assert len(df) == 3
    assert (df["timestamp"] == TS).all()


def test_genera_una_sola_zona():
    df = generar_trafico(["Norte"], timestamp=TS, semilla=1)
    assert len(df) == 1
    assert df.iloc[0]["zona"] == "Norte"


def test_zona_desconocida_lanza_error():
    import pytest

    with pytest.raises(ValueError):
        generar_trafico_zona("Oeste", timestamp=TS, rng=random.Random(0))


# --- Simulador: rangos válidos ---------------------------------------------


def test_valores_en_rangos_esperables_por_zona():
    df = generar_trafico(timestamp=TS, semilla=123)

    for _, fila in df.iterrows():
        base = PERFILES_ZONA[fila["zona"]]
        veh_min = base["vehiculos"] * (1 - RUIDO)
        veh_max = base["vehiculos"] * (1 + RUIDO)
        vel_min = base["velocidad"] * (1 - RUIDO)
        vel_max = base["velocidad"] * (1 + RUIDO)

        # Se redondea, por eso se deja 1 unidad de holgura en los enteros.
        assert veh_min - 1 <= fila["vehiculos"] <= veh_max + 1
        assert vel_min - 0.1 <= fila["velocidad_promedio"] <= vel_max + 0.1
        assert fila["vehiculos"] > 0
        assert fila["velocidad_promedio"] > 0


def test_tipos_coherentes_con_el_esquema():
    df = generar_trafico(timestamp=TS, semilla=7)
    assert df["vehiculos"].dtype == "int64"
    assert df["velocidad_promedio"].dtype == "float64"


# --- Simulador: reproducibilidad -------------------------------------------


def test_misma_semilla_produce_resultado_identico():
    df1 = generar_trafico(timestamp=TS, semilla=99)
    df2 = generar_trafico(timestamp=TS, semilla=99)
    assert df1.equals(df2)


def test_semillas_distintas_producen_resultados_distintos():
    df1 = generar_trafico(timestamp=TS, semilla=1)
    df2 = generar_trafico(timestamp=TS, semilla=2)
    assert not df1.equals(df2)


def test_rng_inyectado_es_deterministic():
    df1 = generar_trafico(timestamp=TS, rng=random.Random(555))
    df2 = generar_trafico(timestamp=TS, rng=random.Random(555))
    assert df1.equals(df2)


# --- Clasificación de congestión: casos y bordes ---------------------------


def test_congestion_bajo():
    # Flujo libre y poca demanda.
    assert clasificar_congestion(vehiculos=80, velocidad_promedio=55.0) == "bajo"


def test_congestion_medio():
    # Intermedio: ni saturado ni completamente libre.
    assert clasificar_congestion(vehiculos=200, velocidad_promedio=30.0) == "medio"


def test_congestion_alto_por_velocidad():
    assert clasificar_congestion(vehiculos=100, velocidad_promedio=10.0) == "alto"


def test_congestion_alto_por_vehiculos():
    assert clasificar_congestion(vehiculos=400, velocidad_promedio=45.0) == "alto"


def test_borde_bajo_exacto():
    # velocidad == UMBRAL_VEL_BAJO y vehiculos == UMBRAL_VEH_BAJO ⇒ bajo.
    assert (
        clasificar_congestion(UMBRAL_VEH_BAJO, UMBRAL_VEL_BAJO) == "bajo"
    )


def test_borde_bajo_justo_por_debajo_de_velocidad_es_medio():
    # Un pelo por debajo del umbral de flujo libre ya no es "bajo".
    assert clasificar_congestion(UMBRAL_VEH_BAJO, UMBRAL_VEL_BAJO - 0.1) == "medio"


def test_borde_alto_por_velocidad_exacto_no_es_alto():
    # velocidad == UMBRAL_VEL_ALTO NO es alto (la condición es estrictamente <).
    assert clasificar_congestion(200, UMBRAL_VEL_ALTO) == "medio"


def test_borde_alto_por_velocidad_justo_por_debajo():
    assert clasificar_congestion(200, UMBRAL_VEL_ALTO - 0.1) == "alto"


def test_borde_alto_por_vehiculos_exacto_no_es_alto():
    # vehiculos == UMBRAL_VEH_ALTO NO es alto (la condición es estrictamente >).
    assert clasificar_congestion(UMBRAL_VEH_ALTO, 30.0) == "medio"


def test_borde_alto_por_vehiculos_justo_por_encima():
    assert clasificar_congestion(UMBRAL_VEH_ALTO + 1, 30.0) == "alto"
