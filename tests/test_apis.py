"""Tests de los clientes de API (Open-Meteo, OpenAQ).

NO hay llamadas reales a la red: se mockea `requests.get`. Aquí solo se comprueba
el comportamiento del cliente (URL, params, header de API key); la normalización se
prueba en `test_transformacion.py`.
"""

from unittest.mock import MagicMock, patch

from ingesta import apis


def _respuesta_falsa(payload):
    """Crea un objeto tipo `requests.Response` mockeado con `.json()` y raise_for_status."""
    resp = MagicMock()
    resp.json.return_value = payload
    resp.raise_for_status.return_value = None
    return resp


def test_obtener_clima_consulta_forecast_y_devuelve_json():
    payload = {"current": {"time": "2026-07-01T12:00"}}
    with patch("ingesta.apis.requests.get", return_value=_respuesta_falsa(payload)) as get:
        resultado = apis.obtener_clima(-33.45, -70.66, base_url="http://fake/v1")

    assert resultado == payload
    url, kwargs = get.call_args.args[0], get.call_args.kwargs
    assert url == "http://fake/v1/forecast"
    assert kwargs["params"]["latitude"] == -33.45
    assert kwargs["params"]["longitude"] == -70.66
    assert "current" in kwargs["params"]


def test_obtener_calidad_aire_envia_header_api_key_desde_entorno(monkeypatch):
    monkeypatch.setenv("OPENAQ_API_KEY", "clave-secreta-123")
    payload = {"results": []}
    with patch("ingesta.apis.requests.get", return_value=_respuesta_falsa(payload)) as get:
        apis.obtener_calidad_aire(42, base_url="http://fake/v3")

    kwargs = get.call_args.kwargs
    assert kwargs["headers"] == {"X-API-Key": "clave-secreta-123"}
    assert get.call_args.args[0] == "http://fake/v3/locations/42/latest"


def test_obtener_calidad_aire_sin_clave_no_envia_header(monkeypatch):
    monkeypatch.delenv("OPENAQ_API_KEY", raising=False)
    payload = {"results": []}
    with patch("ingesta.apis.requests.get", return_value=_respuesta_falsa(payload)) as get:
        apis.obtener_calidad_aire(7, base_url="http://fake/v3")

    assert get.call_args.kwargs["headers"] == {}
