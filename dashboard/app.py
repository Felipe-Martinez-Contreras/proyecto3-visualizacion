"""Punto de entrada del dashboard Dash (servicio `dashboard` en docker-compose).

Estructura en dos niveles, igual que la ingesta:

- Lógica testeable: las consultas por rango, la congestión derivada y los cruces
  viven en ``dashboard/consultas.py``; las figuras en ``dashboard/figuras.py``;
  y ``construir_figuras`` (aquí) arma las 3 visualizaciones a partir de los
  filtros. Nada de esto necesita levantar un servidor.

- Runtime: ``crear_app()`` arma la app Dash (layout + callbacks) y ``main()``
  la sirve en ``DASHBOARD_HOST:DASHBOARD_PORT``. El refresco en vivo lo hace un
  ``dcc.Interval`` que dispara el callback cada ``DASHBOARD_INTERVALO_REFRESCO``
  segundos, re-consultando la BD compartida (que el simulador alimenta cada ~10 s).

Filtros del enunciado (todos conectados al mismo callback que el refresco):

- **Zona** (Centro/Norte/Sur, o todas) → se aplica en la consulta de tráfico y aire.
- **Rango de tiempo** (últimos 5 min / 1 hora / día) → ventana hacia atrás desde ahora.
- **Métrica** (tráfico/aire/clima) → muestra u oculta cada panel de visualización.
- **Congestión** (bajo/medio/alto) → derivada con ``clasificar_congestion`` (no
  está en la BD); filtra las filas de tráfico que alimentan las 3 figuras.
"""

from __future__ import annotations

import os
from datetime import datetime

from dash import Dash, Input, Output, dcc, html
from dotenv import load_dotenv
import plotly.graph_objects as go

from dashboard import consultas
from dashboard.figuras import figura_aire_trafico, figura_clima_trafico, figura_trafico
from ingesta.simulador import ZONAS

# Carga `.env` si existe (no pisa variables ya definidas en el entorno).
load_dotenv()

DASHBOARD_HOST = os.environ.get("DASHBOARD_HOST", "0.0.0.0")
DASHBOARD_PORT = int(os.environ.get("DASHBOARD_PORT", "8050"))

# Segundos entre refrescos del dashboard (dcc.Interval). El simulador inserta
# cada ~10 s, así que 5 s da una vista fluida sin recargar la BD.
DASHBOARD_INTERVALO_REFRESCO = int(os.environ.get("DASHBOARD_INTERVALO_REFRESCO", "5"))

# Valores "sin filtro" de los dropdowns (la BD no conoce estos comodines).
ZONA_TODAS = "todas"
CONGESTION_TODOS = "todos"

# Métricas del enunciado: cada una controla la visibilidad de un panel.
METRICAS = ["trafico", "aire", "clima"]


def construir_figuras(
    zona: str | None = None,
    rango: str = consultas.RANGO_DEFAULT,
    congestion: str | None = None,
    ahora: datetime | None = None,
) -> tuple[go.Figure, go.Figure, go.Figure]:
    """Construye las 3 visualizaciones aplicando los filtros de datos.

    Devuelve ``(trafico, aire_vs_trafico, clima_vs_trafico)``. ``zona`` y
    ``congestion`` en ``None`` no filtran; ``ahora`` es inyectable para tests.
    El filtro de congestión (derivada) se aplica sobre el tráfico ANTES de los
    cruces, de modo que las 3 figuras muestren el mismo subconjunto de tráfico.
    """
    df_trafico = consultas.consultar_trafico_rango(rango, zona=zona, ahora=ahora)
    df_trafico = consultas.filtrar_congestion(
        consultas.agregar_congestion(df_trafico), congestion
    )

    df_aire = consultas.consultar_aire_rango(rango, zona=zona, ahora=ahora)
    df_clima = consultas.consultar_clima_rango(rango, ahora=ahora)

    return (
        figura_trafico(df_trafico),
        figura_aire_trafico(consultas.cruzar_trafico_aire(df_trafico, df_aire)),
        figura_clima_trafico(consultas.cruzar_trafico_clima(df_trafico, df_clima)),
    )


def _campo_filtro(etiqueta: str, control) -> html.Div:
    """Envuelve un control con su etiqueta (celda de la barra de filtros)."""
    return html.Div(
        children=[
            html.Label(
                etiqueta,
                style={
                    "display": "block",
                    "fontSize": "0.85rem",
                    "fontWeight": "600",
                    "marginBottom": "0.25rem",
                    "color": "#495057",
                },
            ),
            control,
        ],
        style={"minWidth": "180px", "flex": "1"},
    )


def _barra_filtros() -> html.Div:
    """Barra con los 4 filtros del enunciado, sobre los gráficos."""
    return html.Div(
        children=[
            _campo_filtro(
                "Zona",
                dcc.Dropdown(
                    id="filtro-zona",
                    options=[{"label": "Todas", "value": ZONA_TODAS}]
                    + [{"label": zona, "value": zona} for zona in ZONAS],
                    value=ZONA_TODAS,
                    clearable=False,
                ),
            ),
            _campo_filtro(
                "Rango de tiempo",
                dcc.Dropdown(
                    id="filtro-rango",
                    options=[
                        {"label": datos["etiqueta"], "value": clave}
                        for clave, datos in consultas.RANGOS.items()
                    ],
                    value=consultas.RANGO_DEFAULT,
                    clearable=False,
                ),
            ),
            _campo_filtro(
                "Métrica",
                dcc.Checklist(
                    id="filtro-metrica",
                    options=[
                        {"label": "Tráfico", "value": "trafico"},
                        {"label": "Aire", "value": "aire"},
                        {"label": "Clima", "value": "clima"},
                    ],
                    value=list(METRICAS),
                    inline=True,
                    inputStyle={"marginRight": "0.3rem"},
                    labelStyle={"marginRight": "0.9rem"},
                    style={"paddingTop": "0.4rem"},
                ),
            ),
            _campo_filtro(
                "Congestión",
                dcc.Dropdown(
                    id="filtro-congestion",
                    options=[{"label": "Todos", "value": CONGESTION_TODOS}]
                    + [
                        {"label": estado.capitalize(), "value": estado}
                        for estado in consultas.ESTADOS_CONGESTION
                    ],
                    value=CONGESTION_TODOS,
                    clearable=False,
                ),
            ),
        ],
        style={
            "display": "flex",
            "gap": "1rem",
            "flexWrap": "wrap",
            "padding": "0.75rem 1rem",
            "border": "1px solid #dee2e6",
            "borderRadius": "6px",
            "backgroundColor": "#f8f9fa",
            "marginBottom": "1rem",
        },
    )


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
                        f"datos en vivo, actualizados cada {DASHBOARD_INTERVALO_REFRESCO} "
                        "segundos.",
                        style={"color": "#6c757d", "marginTop": 0},
                    ),
                ],
                style={"borderBottom": "1px solid #dee2e6", "marginBottom": "1rem"},
            ),
            html.Main(
                children=[
                    _barra_filtros(),
                    html.Div(id="panel-trafico", children=[dcc.Graph(id="grafico-trafico")]),
                    html.Div(id="panel-aire", children=[dcc.Graph(id="grafico-aire-trafico")]),
                    html.Div(id="panel-clima", children=[dcc.Graph(id="grafico-clima-trafico")]),
                    # Motor del refresco en vivo: cada tick dispara el callback,
                    # que re-consulta la BD y redibuja las figuras con los
                    # filtros vigentes.
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
        Output("grafico-aire-trafico", "figure"),
        Output("grafico-clima-trafico", "figure"),
        Output("panel-trafico", "style"),
        Output("panel-aire", "style"),
        Output("panel-clima", "style"),
        Input("intervalo-refresco", "n_intervals"),
        Input("filtro-zona", "value"),
        Input("filtro-rango", "value"),
        Input("filtro-metrica", "value"),
        Input("filtro-congestion", "value"),
    )
    def actualizar_visualizaciones(_n_intervals, zona, rango, metricas, congestion):
        """Re-consulta la BD con los filtros vigentes y redibuja las 3 vistas.

        Se dispara tanto por el `dcc.Interval` (refresco en vivo) como por
        cualquier cambio en los filtros. El filtro de métrica no toca los datos:
        muestra u oculta el panel de cada visualización.
        """
        fig_trafico, fig_aire, fig_clima = construir_figuras(
            zona=None if zona == ZONA_TODAS else zona,
            rango=rango,
            congestion=None if congestion == CONGESTION_TODOS else congestion,
        )
        metricas = metricas or []
        visibilidad = [
            {"display": "block"} if metrica in metricas else {"display": "none"}
            for metrica in METRICAS
        ]
        return fig_trafico, fig_aire, fig_clima, *visibilidad

    return app


def main() -> None:
    """Levanta el servidor del dashboard (docker-compose: `dashboard`)."""
    app = crear_app()
    print(f"[dashboard] Sirviendo en http://{DASHBOARD_HOST}:{DASHBOARD_PORT}")
    app.run(host=DASHBOARD_HOST, port=DASHBOARD_PORT)


if __name__ == "__main__":
    main()
