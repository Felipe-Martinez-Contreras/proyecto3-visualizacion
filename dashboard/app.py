"""Punto de entrada del dashboard Dash (servicio `dashboard` en docker-compose).

Estructura en dos niveles, igual que la ingesta:

- Lógica testeable: ``consultar_trafico_reciente`` (ventana de tiempo sobre la
  capa ``datos/``) y las figuras en ``dashboard/figuras.py``. Nada de esto
  necesita levantar un servidor.

- Runtime: ``crear_app()`` arma la app Dash (layout + callbacks) y ``main()``
  la sirve en ``DASHBOARD_HOST:DASHBOARD_PORT``. El refresco en vivo lo hace un
  ``dcc.Interval`` que dispara el callback cada ``DASHBOARD_INTERVALO_REFRESCO``
  segundos, re-consultando la BD compartida (que el simulador alimenta cada ~10 s).

La ventana de tiempo mostrada es fija por ahora (últimos ``DASHBOARD_VENTANA_MINUTOS``
minutos); los filtros de zona/rango/métrica/congestión llegan en el próximo hito.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta

import pandas as pd
from dash import Dash, Input, Output, dcc, html
from dotenv import load_dotenv

from dashboard.figuras import figura_trafico
from datos import repositorio

# Carga `.env` si existe (no pisa variables ya definidas en el entorno).
load_dotenv()

DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8050"))

# Segundos entre refrescos del dashboard (dcc.Interval). El simulador inserta
# cada ~10 s, así que 5 s da una vista fluida sin recargar la BD.
DASHBOARD_INTERVALO_REFRESCO = int(os.environ.get("DASHBOARD_INTERVALO_REFRESCO", "5"))

# Ventana de tiempo mostrada: últimos N minutos. Fija por ahora (los filtros de
# rango son del próximo hito).
DASHBOARD_VENTANA_MINUTOS = int(os.environ.get("DASHBOARD_VENTANA_MINUTOS", "30"))


def consultar_trafico_reciente(ahora: datetime | None = None) -> pd.DataFrame:
    """Consulta el tráfico de los últimos ``DASHBOARD_VENTANA_MINUTOS`` minutos.

    ``ahora`` es inyectable para que los tests no dependan de la hora real.
    """
    if ahora is None:
        ahora = datetime.now()
    desde = (ahora - timedelta(minutes=DASHBOARD_VENTANA_MINUTOS)).isoformat()
    return repositorio.consultar_trafico(desde=desde)


def crear_app() -> Dash:
    """Crea la app Dash con su layout y callbacks (no levanta el servidor)."""
    app = Dash(__name__, title="Monitoreo Urbano")

    app.layout = html.Div(
        style={
            "fontFamily": "system-ui, -apple-system, 'Segoe UI', sans-serif",
            "maxWidth": "1100px",
            "margin": "0 auto",
            "padding": "1.5rem",
            "color": "#212529",
        },
        children=[
            html.Header(
                children=[
                    html.H1(
                        "Monitoreo de Movilidad Urbana y Calidad del Aire",
                        style={"marginBottom": "0.25rem", "fontSize": "1.6rem"},
                    ),
                    html.P(
                        "Ministerio de Transporte y Medio Ambiente · Santiago — "
                        f"datos en vivo de los últimos {DASHBOARD_VENTANA_MINUTOS} minutos, "
                        f"actualizados cada {DASHBOARD_INTERVALO_REFRESCO} segundos.",
                        style={"color": "#6c757d", "marginTop": 0},
                    ),
                ],
                style={"borderBottom": "1px solid #dee2e6", "marginBottom": "1rem"},
            ),
            html.Main(
                children=[
                    dcc.Graph(id="grafico-trafico"),
                    # Motor del refresco en vivo: cada tick dispara el callback,
                    # que re-consulta la BD y redibuja la figura.
                    dcc.Interval(
                        id="intervalo-refresco",
                        interval=DASHBOARD_INTERVALO_REFRESCO * 1000,  # milisegundos
                        n_intervals=0,
                    ),
                ]
            ),
        ],
    )

    @app.callback(
        Output("grafico-trafico", "figure"),
        Input("intervalo-refresco", "n_intervals"),
    )
    def actualizar_grafico_trafico(_n_intervals: int):
        """Re-consulta la BD y reconstruye la línea temporal de tráfico."""
        return figura_trafico(consultar_trafico_reciente())

    return app


def main() -> None:
    """Levanta el servidor del dashboard (docker-compose: `dashboard`)."""
    app = crear_app()
    print(f"[dashboard] Sirviendo en http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT)


if __name__ == "__main__":
    main()
