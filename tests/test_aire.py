"""Tests de selección de fuente de calidad del aire y fallback.

Sin red: se mockean los clientes de `ingesta.apis`. Se comprueba que por defecto se
usa Open-Meteo AQ y que, si la fuente primaria falla, se cae al fallback OpenAQ (y
viceversa), devolviendo siempre el esquema común `timestamp, zona, pm25, no2, o3`.
"""

import requests
from unittest.mock import patch

from ingesta import aire
from ingesta.transformacion import COLUMNAS_AIRE

# Respuestas crudas mínimas por fuente (formato conocido de cada API).
CRUDA_OPENMETEO = {
    "current": {
        "time": "2026-07-01T12:00",
        "pm2_5": 12.5,
        "nitrogen_dioxide": 30.1,
        "ozone": 45.0,
    }
}
CRUDA_OPENAQ = {
    "results": [
        {
            "parameter": {"name": "pm25"},
            "value": 9.0,
            "datetime": {"utc": "2026-07-01T12:00:00Z"},
        }
    ]
}


def test_por_defecto_usa_open_meteo(monkeypatch):
    monkeypatch.setattr(aire, "FUENTE_AIRE", "open-meteo")
    with patch(
        "ingesta.apis.obtener_calidad_aire_openmeteo", return_value=CRUDA_OPENMETEO
    ) as om, patch("ingesta.apis.obtener_calidad_aire") as oaq:
        df = aire.obtener_calidad_aire_zona("Centro")

    om.assert_called_once()          # se usó Open-Meteo
    oaq.assert_not_called()          # NO se tocó OpenAQ
    assert list(df.columns) == COLUMNAS_AIRE
    assert df.iloc[0]["zona"] == "Centro"
    assert df.iloc[0]["pm25"] == 12.5


def test_fuente_explicita_openaq(monkeypatch):
    monkeypatch.setenv("OPENAQ_LOC_NORTE", "42")
    with patch(
        "ingesta.apis.obtener_calidad_aire", return_value=CRUDA_OPENAQ
    ) as oaq, patch("ingesta.apis.obtener_calidad_aire_openmeteo") as om:
        df = aire.obtener_calidad_aire_zona("Norte", fuente="openaq")

    oaq.assert_called_once()
    om.assert_not_called()
    assert list(df.columns) == COLUMNAS_AIRE
    assert df.iloc[0]["zona"] == "Norte"


def test_fallback_si_primaria_falla(monkeypatch):
    # Primaria (Open-Meteo) lanza excepción de red → debe usarse OpenAQ.
    monkeypatch.setattr(aire, "FUENTE_AIRE", "open-meteo")
    monkeypatch.setenv("OPENAQ_LOC_CENTRO", "77")

    def _falla(*args, **kwargs):
        raise requests.RequestException("sin red")

    with patch(
        "ingesta.apis.obtener_calidad_aire_openmeteo", side_effect=_falla
    ) as om, patch(
        "ingesta.apis.obtener_calidad_aire", return_value=CRUDA_OPENAQ
    ) as oaq:
        df = aire.obtener_calidad_aire_zona("Centro")

    om.assert_called_once()          # se intentó la primaria
    oaq.assert_called_once()         # y se cayó al fallback
    assert list(df.columns) == COLUMNAS_AIRE
    assert df.iloc[0]["zona"] == "Centro"
    assert df.iloc[0]["pm25"] == 9.0


def test_fallback_inverso_openaq_a_openmeteo(monkeypatch):
    # Primaria (OpenAQ) falla → fallback a Open-Meteo AQ.
    def _falla(*args, **kwargs):
        raise requests.RequestException("sin red")

    with patch(
        "ingesta.apis.obtener_calidad_aire", side_effect=_falla
    ) as oaq, patch(
        "ingesta.apis.obtener_calidad_aire_openmeteo", return_value=CRUDA_OPENMETEO
    ) as om:
        df = aire.obtener_calidad_aire_zona("Sur", fuente="openaq")

    om.assert_called_once()          # fallback usado
    assert list(df.columns) == COLUMNAS_AIRE
    assert df.iloc[0]["zona"] == "Sur"
    assert df.iloc[0]["pm25"] == 12.5
