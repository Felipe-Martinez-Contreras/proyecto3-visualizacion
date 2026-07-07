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
MENSAJE_SIN_DATOS_AIRE = (
    "Sin datos combinados de tráfico y calidad del aire en la ventana mostrada."
)
MENSAJE_SIN_DATOS_CLIMA = "Sin datos combinados de tráfico y clima en la ventana mostrada."


def _anotar_sin_datos(fig: go.Figure, mensaje: str) -> None:
    """Anotación centrada para figuras sin filas — la app nunca se rompe."""
    fig.add_annotation(
        text=mensaje,
        showarrow=False,
        font={"size": 16, "color": "#6c757d"},
    )


def figura_trafico(df: pd.DataFrame) -> go.Figure:
    """Línea temporal de tráfico: vehículos vs tiempo, una serie por zona.

    Espera un DataFrame con columnas ``timestamp``, ``zona`` y ``vehiculos``
    (como devuelve ``datos.repositorio.consultar_trafico``). Si viene vacío
    (BD sin datos o filtros sin coincidencias), devuelve una figura sin trazas
    con una anotación explicativa.
    """
    fig = go.Figure()

    if df.empty:
        _anotar_sin_datos(fig, MENSAJE_SIN_DATOS)
    else:
        for zona in ZONAS:
            df_zona = df[df["zona"] == zona].sort_values("timestamp")
            if df_zona.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=pd.to_datetime(df_zona["timestamp"], format="ISO8601"),
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


def _scatter_por_zona(
    df: pd.DataFrame,
    *,
    col_x: str,
    col_y: str,
    mensaje_sin_datos: str,
) -> go.Figure:
    """Scatter ``col_x`` vs ``col_y`` con una traza de puntos por zona.

    Base común de las visualizaciones de cruce (aire vs tráfico y clima vs
    tráfico): mismas zonas, mismos colores fijos y misma anotación cuando el
    cruce no produce filas.
    """
    fig = go.Figure()

    if df.empty:
        _anotar_sin_datos(fig, mensaje_sin_datos)
    else:
        for zona in ZONAS:
            df_zona = df[df["zona"] == zona]
            if df_zona.empty:
                continue
            fig.add_trace(
                go.Scatter(
                    x=df_zona[col_x],
                    y=df_zona[col_y],
                    mode="markers",
                    name=zona,
                    marker={"color": COLORES_ZONA.get(zona), "size": 9},
                )
            )
    return fig


def figura_aire_trafico(df: pd.DataFrame) -> go.Figure:
    """Scatter contaminación vs tráfico: PM2.5 vs vehículos, color por zona.

    Espera el cruce de ``Trafico`` y ``Calidad_Aire_Hist`` por ``timestamp`` +
    ``zona`` (``dashboard.consultas.cruzar_trafico_aire``), con columnas
    ``vehiculos``, ``pm25`` y ``zona``.
    """
    fig = _scatter_por_zona(
        df,
        col_x="vehiculos",
        col_y="pm25",
        mensaje_sin_datos=MENSAJE_SIN_DATOS_AIRE,
    )
    fig.update_layout(
        title="Contaminación vs tráfico — PM2.5 vs vehículos",
        xaxis_title="Vehículos",
        yaxis_title="PM2.5 (µg/m³)",
        legend_title="Zona",
        template="plotly_white",
        margin={"l": 60, "r": 30, "t": 60, "b": 50},
    )
    return fig


def figura_clima_trafico(df: pd.DataFrame) -> go.Figure:
    """Scatter clima vs congestión: temperatura vs tráfico, color por zona.

    Espera el cruce de ``Trafico`` y ``Condiciones_Clima`` por ``timestamp``
    (``dashboard.consultas.cruzar_trafico_clima``; el clima es global), con
    columnas ``temperatura``, ``vehiculos`` y ``zona``.
    """
    fig = _scatter_por_zona(
        df,
        col_x="temperatura",
        col_y="vehiculos",
        mensaje_sin_datos=MENSAJE_SIN_DATOS_CLIMA,
    )
    fig.update_layout(
        title="Clima vs congestión — temperatura vs tráfico",
        xaxis_title="Temperatura (°C)",
        yaxis_title="Vehículos",
        legend_title="Zona",
        template="plotly_white",
        margin={"l": 60, "r": 30, "t": 60, "b": 50},
    )
    return fig
