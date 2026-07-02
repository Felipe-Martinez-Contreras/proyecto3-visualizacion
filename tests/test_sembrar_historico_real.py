"""Tests de la fuente ``real`` del script de siembra (Open-Meteo mockeado).

SIN red: se mockea ``requests.get`` del módulo `db/sembrar_historico.py` con
respuestas ``hourly`` como las de Open-Meteo (incluyendo horas futuras en null,
tal como hace la API). BD temporal aislada, mismo patrón que
`tests/test_sembrar_historico.py` — nunca se toca `db/monitoreo.sqlite`.
"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
import requests

from datos import repositorio
from db import sembrar_historico as sh
from db.init_db import SCHEMA_PATH, init_db
from ingesta.aire import _coords_zona
from ingesta.simulador import ZONAS


@pytest.fixture
def bd_temporal(tmp_path, monkeypatch):
    """Crea una BD temporal aislada y apunta `DB_PATH` a ella durante el test."""
    db_path = tmp_path / "test.sqlite"
    monkeypatch.setenv("DB_PATH", str(db_path))
    init_db(db_path=db_path, schema_path=SCHEMA_PATH)
    return db_path


# `ahora` fijo para tests deterministas.
AHORA = datetime(2026, 7, 1, 12, 0, 0)

# Bases por zona para que los valores del mock sean reconocibles en los asserts.
# Valor insertado esperado: base + hora del timestamp.
PM25_BASE = {"Centro": 100.0, "Norte": 50.0, "Sur": 20.0}
NO2_BASE = {"Centro": 60.0, "Norte": 40.0, "Sur": 30.0}
O3_BASE = {"Centro": 5.0, "Norte": 15.0, "Sur": 25.0}


def _zona_por_latitud(lat: float) -> str:
    """Zona cuya coordenada de `_coords_zona` coincide con la latitud pedida."""
    for zona in ZONAS:
        if _coords_zona(zona)[0] == lat:
            return zona
    raise AssertionError(f"Latitud desconocida en el mock: {lat}")


def _respuesta(payload):
    """Objeto tipo `requests.Response` mockeado (mismo patrón que test_apis.py)."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def _mock_get(ahora: datetime = AHORA, horas_datos: int = 6, horas_futuras: int = 2,
              clima_null: set | frozenset = frozenset()):
    """``side_effect`` para ``requests.get`` que imita las series hourly de Open-Meteo.

    La serie va de ``ahora - horas_datos`` a ``ahora + horas_futuras`` (paso 1 h);
    las horas posteriores a ``ahora`` vienen con null (como la API con horas que
    aún no ocurren). ``clima_null``: timestamps que vienen null SOLO en el clima.
    """
    tiempos = [
        ahora - timedelta(hours=horas_datos) + timedelta(hours=i)
        for i in range(horas_datos + horas_futuras + 1)
    ]

    def side_effect(url, params=None, timeout=None, **kwargs):
        textos = [t.strftime("%Y-%m-%dT%H:%M") for t in tiempos]

        def serie(valor_de, nulos=frozenset()):
            return [None if (t > ahora or t in nulos) else valor_de(t) for t in tiempos]

        if "air-quality" in url:
            zona = _zona_por_latitud(params["latitude"])
            hourly = {
                "time": textos,
                "pm2_5": serie(lambda t: PM25_BASE[zona] + t.hour),
                "nitrogen_dioxide": serie(lambda t: NO2_BASE[zona] + t.hour),
                "ozone": serie(lambda t: O3_BASE[zona] + t.hour),
            }
        else:
            hourly = {
                "time": textos,
                "temperature_2m": serie(lambda t: float(t.hour), clima_null),
                "relative_humidity_2m": serie(lambda t: 80.0, clima_null),
                "wind_speed_10m": serie(lambda t: 5.0, clima_null),
            }
        return _respuesta({"hourly": hourly})

    return side_effect


# --- Ventana, nulls y timestamps compartidos ---------------------------------

def test_ventana_nulls_y_timestamps_compartidos(bd_temporal):
    # Serie 06:00–14:00; 13:00/14:00 futuras (null) y 09:00 null solo en clima.
    mock = _mock_get(clima_null={datetime(2026, 7, 1, 9)})
    with patch("db.sembrar_historico.requests.get", side_effect=mock):
        resumen = sh.sembrar_real(horas=4, semilla=42, ahora=AHORA)

    # Ventana 08:00–12:00, menos el 09:00 (null en clima) → 4 ticks horarios.
    esperados = {f"2026-07-01T{h:02d}:00:00" for h in (8, 10, 11, 12)}
    ts_trafico = set(repositorio.consultar_trafico()["timestamp"])
    ts_aire = set(repositorio.consultar_calidad_aire()["timestamp"])
    ts_clima = set(repositorio.consultar_clima()["timestamp"])
    # Ni horas previas a la ventana (06/07), ni futuras null (13/14), ni el null.
    assert ts_trafico == ts_aire == ts_clima == esperados

    assert resumen == {
        "trafico": 4 * len(ZONAS),
        "aire": 4 * len(ZONAS),
        "clima": 4,
        "desde": "2026-07-01T08:00:00",
        "hasta": "2026-07-01T12:00:00",
    }


def test_trafico_simulado_presente_en_cada_tick(bd_temporal):
    with patch("db.sembrar_historico.requests.get", side_effect=_mock_get()):
        sh.sembrar_real(horas=4, semilla=42, ahora=AHORA)

    trafico = repositorio.consultar_trafico()
    # En cada tick horario hay UNA fila de tráfico por zona, con valores plausibles.
    for _, grupo in trafico.groupby("timestamp"):
        assert set(grupo["zona"]) == set(ZONAS)
    assert (trafico["vehiculos"] > 0).all()
    assert (trafico["velocidad_promedio"] > 0).all()


# --- Valores del mock insertados correctamente --------------------------------

def test_valores_reales_insertados_por_zona(bd_temporal):
    with patch("db.sembrar_historico.requests.get", side_effect=_mock_get()):
        sh.sembrar_real(horas=4, semilla=42, ahora=AHORA)

    aire = repositorio.consultar_calidad_aire()
    ts = "2026-07-01T10:00:00"  # valor esperado = base de la zona + 10.
    centro = aire[(aire["zona"] == "Centro") & (aire["timestamp"] == ts)].iloc[0]
    assert (centro["pm25"], centro["no2"], centro["o3"]) == (110.0, 70.0, 15.0)
    sur = aire[(aire["zona"] == "Sur") & (aire["timestamp"] == ts)].iloc[0]
    assert (sur["pm25"], sur["no2"], sur["o3"]) == (30.0, 40.0, 35.0)

    clima = repositorio.consultar_clima()
    fila = clima[clima["timestamp"] == "2026-07-01T11:00:00"].iloc[0]
    assert (fila["temperatura"], fila["humedad"], fila["viento"]) == (11.0, 80.0, 5.0)


# --- Parámetros de las llamadas a Open-Meteo ----------------------------------

def test_llamadas_a_openmeteo_con_params_correctos(bd_temporal):
    with patch("db.sembrar_historico.requests.get", side_effect=_mock_get()) as get:
        sh.sembrar_real(horas=30, semilla=1, ahora=AHORA)

    # 1 llamada de clima + 1 de aire por zona.
    assert get.call_count == 1 + len(ZONAS)
    urls = [llamada.args[0] for llamada in get.call_args_list]
    assert sum("air-quality" in url for url in urls) == len(ZONAS)
    for llamada in get.call_args_list:
        params = llamada.kwargs["params"]
        assert params["timezone"] == "America/Santiago"
        assert params["past_days"] == 2  # ceil(30/24)
        assert "hourly" in params


def test_past_days_cubre_horas_y_respeta_limites_de_la_api():
    assert sh._past_days(1) == 1
    assert sh._past_days(24) == 1
    assert sh._past_days(25) == 2
    assert sh._past_days(24 * 200) == 92  # tope de la API


# --- Manejo de errores ---------------------------------------------------------

def test_error_de_red_lanza_excepcion(bd_temporal):
    with patch(
        "db.sembrar_historico.requests.get",
        side_effect=requests.ConnectionError("sin red"),
    ):
        with pytest.raises(requests.RequestException):
            sh.sembrar_real(horas=4, ahora=AHORA)


def test_sin_horas_utiles_lanza_valueerror(bd_temporal):
    # `ahora` 5 días después de los datos del mock: nada cae en la ventana.
    with patch("db.sembrar_historico.requests.get", side_effect=_mock_get()):
        with pytest.raises(ValueError):
            sh.sembrar_real(horas=2, ahora=AHORA + timedelta(days=5))


def test_main_con_api_caida_sale_con_error_y_sugiere_fallback(bd_temporal, capsys):
    # Datos previos: --limpiar NO debe borrarlos si la descarga falla antes.
    sh.sembrar(horas=1, paso_minutos=30, semilla=1, ahora=AHORA)
    previo = len(repositorio.consultar_trafico())

    with patch(
        "db.sembrar_historico.requests.get",
        side_effect=requests.ConnectionError("sin red"),
    ):
        with pytest.raises(SystemExit) as excinfo:
            sh.main(["--limpiar"])  # fuente default: real.

    assert excinfo.value.code == 1
    assert "sintetico" in capsys.readouterr().err
    assert len(repositorio.consultar_trafico()) == previo


# --- CLI: default real y fuente sintética intacta ------------------------------

def test_main_usa_fuente_real_por_defecto(bd_temporal):
    # `main` usa datetime.now(): el mock genera la serie alrededor de la hora actual.
    ahora = datetime.now().replace(minute=0, second=0, microsecond=0)
    with patch(
        "db.sembrar_historico.requests.get", side_effect=_mock_get(ahora=ahora)
    ) as get:
        sh.main(["--horas", "4"])

    assert get.called  # sin --fuente, consulta Open-Meteo (default: real).
    clima = repositorio.consultar_clima()
    # Ventana de 4 h con resolución horaria: 4 o 5 ticks según el minuto actual.
    assert 4 <= len(clima) <= 5
    assert len(repositorio.consultar_trafico()) == len(clima) * len(ZONAS)


def test_main_fuente_sintetico_sigue_igual_y_no_llama_apis(bd_temporal):
    with patch("db.sembrar_historico.requests.get") as get:
        sh.main([
            "--fuente", "sintetico",
            "--horas", "1", "--paso-minutos", "10", "--semilla", "7",
        ])

    get.assert_not_called()
    # 1 h / 10 min = 6 pasos → 7 ticks (ambos extremos), como siempre.
    assert len(repositorio.consultar_clima()) == 7
    assert len(repositorio.consultar_trafico()) == 7 * len(ZONAS)
    assert len(repositorio.consultar_calidad_aire()) == 7 * len(ZONAS)
