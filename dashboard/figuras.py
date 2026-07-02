"""Construcción de figuras Plotly para el dashboard.

Separado de `dashboard/app.py` para que la lógica de graficado sea testeable sin
levantar la app Dash: cada función recibe un DataFrame (ya consultado por la capa
`datos/`) y devuelve una `plotly.graph_objects.Figure`.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

# Única fuente de verdad de las zonas (las mismas que genera el simulador).
from ingesta.simulador import ZONAS

# Colores fijos por zona para que cada serie mantenga su color entre refrescos.
COLORES_ZONA = {"Centro": "#1f77b4", "Norte": "#ff7f0e", "Sur": "#2ca02c"}

MENSAJE_SIN_DATOS = "Sin datos de tráfico en la ventana de tiempo mostrada."


def figura_trafico(df: pd.DataFrame) -> go.Figure:
    """Línea temporal de tráfico: vehículos vs tiempo, una serie por zona.

    Espera un DataFrame con columnas ``timestamp``, ``zona`` y ``vehiculos``
    (como devuelve ``datos.repositorio.consultar_trafico``). Si viene vacío
    (BD sin datos o ventana sin filas), devuelve una figura sin trazas con una
    anotación explicativa — la app nunca se rompe.
    """
    fig = go.Figure()

    if df.empty:
        fig.add_annotation(
            text=MENSAJE_SIN_DATOS,
            showarrow=False,
            font={"size": 16, "color": "#6c757d"},
        )
    else:
        for zona in ZONAS:
            df_zona = df[df["zona"] == zona].sort_values("timestamp")
            if df_zona.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=pd.to_datetime(df_zona["timestamp"]),
                    y=df_zona["vehiculos"],
                    mode="lines+markers",
                    name=zona,
                    line={"color": COLORES_ZONA.get(zona)},
                )
            )

    fig.update_layout(
        title="Tráfico por zona — vehículos vs tiempo",
        xaxis_title="Tiempo",
        yaxis_title="Vehículos",
        legend_title="Zona",
        template="plotly_white",
        margin={"l": 60, "r": 30, "t": 60, "b": 50},
    )
    return fig
