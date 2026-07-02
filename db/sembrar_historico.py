"""Siembra de datos históricos para la demo del dashboard.

Puebla las últimas N horas (default 24) en las 3 tablas (`Trafico`,
`Calidad_Aire_Hist`, `Condiciones_Clima`), con dos fuentes seleccionables:

- ``--fuente real`` (default): clima y calidad del aire HISTÓRICOS REALES desde
  Open-Meteo (gratis, sin API key) con resolución horaria; el tráfico sigue
  SIMULADO (no existe fuente pública y el enunciado lo exige simulado), generado
  para los mismos timestamps horarios que devuelve la API.
- ``--fuente sintetico``: todo sintético con ticks cada ``--paso-minutos``
  (comportamiento original del script).

Así los rangos "última hora" y "último día" del dashboard tienen contenido
interesante sin esperar a que el scheduler acumule datos en vivo.

Realismo del sintético (invierno en Santiago de Chile):

- **Tráfico**: baselines por zona de `ingesta/simulador.py` (Centro más cargado,
  Sur más fluido), modulados por hora del día — horas punta 7–9 y 18–20 (más
  vehículos, menos velocidad) y valle nocturno 0–6 — más ruido.
- **Clima**: curva día/noche suave (mínimo ~3 °C a las 6 am, máximo ~14 °C a las
  ~14:30) con ruido leve; humedad inversa a la temperatura (~90 % de madrugada,
  ~50 % a mediodía); viento suave con algo de ruido.
- **Aire**: baselines por zona coherentes con lo observado en vivo, pero
  **correlacionados con el tráfico del tick**: más vehículos ⇒ más pm2.5 y no2;
  el o3 al revés (sube con menos tráfico y más sol). Así el scatter
  PM2.5 vs vehículos del dashboard muestra una correlación visible.

Cada tick comparte EL MISMO ``timestamp`` en las 3 tablas, para que los cruces
por `timestamp` del dashboard funcionen.

Uso::

    uv run python -m db.sembrar_historico                    # 24 h reales (horario)
    uv run python -m db.sembrar_historico --limpiar --horas 48
    uv run python -m db.sembrar_historico --fuente sintetico --horas 6 --paso-minutos 2
    uv run python -m db.sembrar_historico --fuente sintetico --limpiar --semilla 42

Sin ``--limpiar`` siembra ENCIMA de lo existente; con ``--limpiar`` borra antes
las filas de las 3 tablas. Inserta vía `datos/repositorio.py` (mismo camino que
la ingesta en vivo). Si Open-Meteo no responde, usar ``--fuente sintetico``.
"""

from __future__ import annotations

import argparse
import math
import random
import sys
from datetime import datetime, timedelta

import pandas as pd
import requests

from datos.conexion import conectar
from datos.repositorio import (
    insertar_calidad_aire,
    insertar_clima,
    insertar_trafico,
)
from ingesta.aire import _coords_zona
from ingesta.apis import OPENMETEO_AIRE_BASE_URL, OPENMETEO_BASE_URL, TIMEOUT_S
from ingesta.scheduler import CLIMA_LATITUD, CLIMA_LONGITUD
from ingesta.simulador import PERFILES_ZONA, ZONAS

# --- Perfil de aire por zona (coherente con lo observado en vivo) -----------
# Valores promedio aproximados: pm2.5 y no2 altos en el Centro (más tráfico,
# invierno santiaguino), o3 mayor en la periferia (menos NO que lo consuma).
PERFILES_AIRE = {
    "Centro": {"pm25": 150.0, "no2": 99.0, "o3": 0.0},
    "Norte": {"pm25": 55.0, "no2": 56.0, "o3": 15.0},
    "Sur": {"pm25": 22.0, "no2": 42.0, "o3": 50.0},
}

# --- Clima de invierno santiaguino -------------------------------------------
TEMP_MIN = 3.0    # °C, madrugada (~6 am).
TEMP_MAX = 14.0   # °C, primera hora de la tarde (~14:30).
HORA_TEMP_MIN = 6.0
HORA_TEMP_MAX = 14.5
HUMEDAD_MAX = 90.0  # % a la temperatura mínima.
HUMEDAD_MIN = 50.0  # % a la temperatura máxima.
VIENTO_BASE = 7.0   # km/h, brisa suave.

# --- Modulación horaria del tráfico ------------------------------------------
# Factores multiplicativos sobre los baselines por zona del simulador.
FACTOR_VEH_PUNTA = 1.6   # horas punta 7–9 y 18–20: más vehículos...
FACTOR_VEL_PUNTA = 0.6   # ...y menos velocidad.
FACTOR_VEH_VALLE = 0.35  # valle nocturno 0–6: pocas salidas...
FACTOR_VEL_VALLE = 1.25  # ...y vías despejadas.


def _es_punta(hora: int) -> bool:
    """True en horas punta (7–9 mañana, 18–20 tarde)."""
    return 7 <= hora <= 9 or 18 <= hora <= 20


def _es_valle(hora: int) -> bool:
    """True en el valle nocturno (0–6)."""
    return hora <= 6


def _factores_trafico(hora: int) -> tuple[float, float]:
    """Devuelve ``(factor_vehiculos, factor_velocidad)`` según la hora del día."""
    if _es_punta(hora):
        return FACTOR_VEH_PUNTA, FACTOR_VEL_PUNTA
    if _es_valle(hora):
        return FACTOR_VEH_VALLE, FACTOR_VEL_VALLE
    return 1.0, 1.0


def _temperatura_base(hora_frac: float) -> float:
    """Temperatura sin ruido para una hora del día (fraccionaria, 0–24).

    Curva suave por tramos de coseno: sube de ``TEMP_MIN`` (6 am) a ``TEMP_MAX``
    (~14:30) y baja de vuelta durante la tarde/noche. Se usan dos medios cosenos
    (subida corta, bajada larga) en vez de una sinusoide simple, porque el máximo
    real no está 12 h después del mínimo.
    """
    amplitud = TEMP_MAX - TEMP_MIN
    if HORA_TEMP_MIN <= hora_frac <= HORA_TEMP_MAX:
        # Subida (mañana): de mínimo a máximo.
        avance = (hora_frac - HORA_TEMP_MIN) / (HORA_TEMP_MAX - HORA_TEMP_MIN)
        return TEMP_MIN + amplitud * (1 - math.cos(math.pi * avance)) / 2
    # Bajada (tarde/noche/madrugada): de máximo a mínimo, envolviendo medianoche.
    horas_desde_max = (hora_frac - HORA_TEMP_MAX) % 24
    duracion_bajada = 24 - (HORA_TEMP_MAX - HORA_TEMP_MIN)
    avance = horas_desde_max / duracion_bajada
    return TEMP_MAX - amplitud * (1 - math.cos(math.pi * avance)) / 2


def _factor_sol(hora_frac: float) -> float:
    """Radiación solar relativa (0 de noche, 1 a mediodía solar ~13 h, invierno)."""
    # Día corto de invierno: sol aproximado entre las 8 y las 18 h.
    if not 8.0 <= hora_frac <= 18.0:
        return 0.0
    return math.sin(math.pi * (hora_frac - 8.0) / 10.0)


def _fila_trafico(zona: str, ts: datetime, rng: random.Random) -> dict:
    """Lectura de tráfico para una zona, modulada por hora del día + ruido."""
    base = PERFILES_ZONA[zona]
    f_veh, f_vel = _factores_trafico(ts.hour)
    vehiculos = max(1, round(base["vehiculos"] * f_veh * rng.uniform(0.85, 1.15)))
    velocidad = max(5.0, round(base["velocidad"] * f_vel * rng.uniform(0.9, 1.1), 1))
    return {
        "timestamp": ts.isoformat(timespec="seconds"),
        "zona": zona,
        "vehiculos": int(vehiculos),
        "velocidad_promedio": float(velocidad),
    }


def _fila_aire(zona: str, ts: datetime, vehiculos: int, rng: random.Random) -> dict:
    """Lectura de aire para una zona, correlacionada con el tráfico del tick.

    ``ratio`` compara los vehículos del tick con el baseline de la zona: con
    tráfico alto sube pm2.5/no2 y baja o3 (que además crece con el sol).
    """
    base = PERFILES_AIRE[zona]
    ratio = vehiculos / PERFILES_ZONA[zona]["vehiculos"]
    hora_frac = ts.hour + ts.minute / 60
    pm25 = max(1.0, base["pm25"] * (0.45 + 0.55 * ratio) * rng.uniform(0.9, 1.1))
    no2 = max(0.5, base["no2"] * (0.45 + 0.55 * ratio) * rng.uniform(0.9, 1.1))
    o3 = max(
        0.0,
        base["o3"] * (1.5 - 0.5 * ratio) * (0.7 + 0.6 * _factor_sol(hora_frac))
        + rng.gauss(0, 1.5),
    )
    return {
        "timestamp": ts.isoformat(timespec="seconds"),
        "zona": zona,
        "pm25": round(pm25, 1),
        "no2": round(no2, 1),
        "o3": round(o3, 1),
    }


def _fila_clima(ts: datetime, rng: random.Random) -> dict:
    """Lectura de clima global del tick: curva día/noche + ruido leve."""
    hora_frac = ts.hour + ts.minute / 60
    temperatura = _temperatura_base(hora_frac) + rng.gauss(0, 0.6)
    # Humedad inversamente proporcional a la temperatura (lineal entre extremos).
    proporcion = (temperatura - TEMP_MIN) / (TEMP_MAX - TEMP_MIN)
    humedad = HUMEDAD_MAX - (HUMEDAD_MAX - HUMEDAD_MIN) * proporcion + rng.gauss(0, 3)
    viento = max(0.0, VIENTO_BASE + rng.gauss(0, 2.5))
    return {
        "timestamp": ts.isoformat(timespec="seconds"),
        "temperatura": round(temperatura, 1),
        "humedad": round(min(100.0, max(20.0, humedad)), 1),
        "viento": round(viento, 1),
    }


# --- Fuente "real": históricos horarios de Open-Meteo ------------------------
# Timezone pedida a la API: CRÍTICO para que los timestamps vengan en hora local
# chilena, consistentes con el resto del sistema (scheduler, dashboard).
ZONA_HORARIA = "America/Santiago"

# Variables horarias pedidas a cada API (mapean a nuestras tablas).
CLIMA_VARS_HORARIAS = ("temperature_2m", "relative_humidity_2m", "wind_speed_10m")
AIRE_VARS_HORARIAS = ("pm2_5", "nitrogen_dioxide", "ozone")


def _past_days(horas: float) -> int:
    """Días de historia a pedir a Open-Meteo para cubrir ``horas`` (API acepta 1–92)."""
    return min(92, max(1, math.ceil(horas / 24)))


def _serie_horaria(url: str, params: dict, campos: tuple[str, ...]) -> dict[datetime, dict]:
    """Descarga una serie ``hourly`` de Open-Meteo y la indexa por timestamp.

    Devuelve ``{datetime: {campo: valor}}`` descartando las horas donde algún
    campo viene ``None`` (la API incluye las horas del día que aún no ocurren,
    con valor null). Lanza ``requests.RequestException`` si la red/HTTP falla.
    """
    respuesta = requests.get(url, params=params, timeout=TIMEOUT_S)
    respuesta.raise_for_status()
    hourly = respuesta.json().get("hourly", {})
    tiempos = hourly.get("time", [])
    vacia = [None] * len(tiempos)

    serie: dict[datetime, dict] = {}
    for i, texto in enumerate(tiempos):
        valores = {campo: hourly.get(campo, vacia)[i] for campo in campos}
        if any(v is None for v in valores.values()):
            continue  # hora futura o hueco de la API: se descarta.
        serie[datetime.fromisoformat(texto)] = valores
    return serie


def _clima_horario_real(horas: float) -> dict[datetime, dict]:
    """Clima horario real (Open-Meteo) en la coordenada global de la ciudad."""
    return _serie_horaria(
        f"{OPENMETEO_BASE_URL}/forecast",
        {
            "latitude": CLIMA_LATITUD,
            "longitude": CLIMA_LONGITUD,
            "hourly": ",".join(CLIMA_VARS_HORARIAS),
            "past_days": _past_days(horas),
            "timezone": ZONA_HORARIA,
        },
        CLIMA_VARS_HORARIAS,
    )


def _aire_horario_real(zona: str, horas: float) -> dict[datetime, dict]:
    """Calidad del aire horaria real (Open-Meteo AQ) en la coordenada de la zona."""
    lat, lon = _coords_zona(zona)
    return _serie_horaria(
        f"{OPENMETEO_AIRE_BASE_URL}/air-quality",
        {
            "latitude": lat,
            "longitude": lon,
            "hourly": ",".join(AIRE_VARS_HORARIAS),
            "past_days": _past_days(horas),
            "timezone": ZONA_HORARIA,
        },
        AIRE_VARS_HORARIAS,
    )


def sembrar_real(
    horas: float = 24,
    *,
    semilla: int | None = None,
    ahora: datetime | None = None,
    limpiar: bool = False,
) -> dict:
    """Siembra clima y aire REALES (Open-Meteo, horario) + tráfico simulado.

    Descarga las series horarias de clima (global) y aire (una por zona), se
    queda con los timestamps comunes dentro de la ventana ``[ahora - horas,
    ahora]`` (sin horas futuras ni valores null) y por cada uno inserta 1 fila
    de clima, 3 de aire y 3 de tráfico simulado con el MISMO ``timestamp``,
    para que los cruces del dashboard funcionen. Resolución: horaria.

    Lanza ``requests.RequestException`` si Open-Meteo falla y ``ValueError`` si
    no quedan horas útiles. Con ``limpiar`` borra las tablas SOLO después de
    descargar con éxito. Devuelve el mismo resumen que :func:`sembrar`.
    """
    rng = random.Random(semilla)
    ahora = ahora if ahora is not None else datetime.now()
    desde = ahora - timedelta(hours=horas)

    clima = _clima_horario_real(horas)
    aire_por_zona = {zona: _aire_horario_real(zona, horas) for zona in ZONAS}

    # Timestamps presentes en TODAS las series (clima + aire de las 3 zonas),
    # recortados a la ventana pedida.
    comunes = set(clima)
    for serie in aire_por_zona.values():
        comunes &= set(serie)
    timestamps = sorted(ts for ts in comunes if desde <= ts <= ahora)
    if not timestamps:
        raise ValueError(
            "Open-Meteo no devolvió horas con datos dentro de la ventana pedida."
        )

    if limpiar:
        limpiar_tablas()

    filas_trafico: list[dict] = []
    filas_aire: list[dict] = []
    filas_clima: list[dict] = []

    for ts in timestamps:
        iso = ts.isoformat(timespec="seconds")
        c = clima[ts]
        filas_clima.append(
            {
                "timestamp": iso,
                "temperatura": float(c["temperature_2m"]),
                "humedad": float(c["relative_humidity_2m"]),
                "viento": float(c["wind_speed_10m"]),
            }
        )
        for zona in ZONAS:
            a = aire_por_zona[zona][ts]
            filas_aire.append(
                {
                    "timestamp": iso,
                    "zona": zona,
                    "pm25": float(a["pm2_5"]),
                    "no2": float(a["nitrogen_dioxide"]),
                    "o3": float(a["ozone"]),
                }
            )
            # Tráfico SIMULADO para el mismo timestamp exacto (no hay fuente real).
            filas_trafico.append(_fila_trafico(zona, ts, rng))

    n_trafico = insertar_trafico(pd.DataFrame(filas_trafico))
    n_aire = insertar_calidad_aire(pd.DataFrame(filas_aire))
    n_clima = insertar_clima(pd.DataFrame(filas_clima))

    return {
        "trafico": n_trafico,
        "aire": n_aire,
        "clima": n_clima,
        "desde": filas_clima[0]["timestamp"],
        "hasta": filas_clima[-1]["timestamp"],
    }


def limpiar_tablas() -> None:
    """Borra TODAS las filas de las 3 tablas (los `CREATE TABLE` no se tocan)."""
    with conectar() as conn:
        for tabla in ("Trafico", "Calidad_Aire_Hist", "Condiciones_Clima"):
            conn.execute(f"DELETE FROM {tabla}")  # noqa: S608 — tabla es literal interno.


def sembrar(
    horas: float = 24,
    paso_minutos: float = 1,
    *,
    semilla: int | None = None,
    ahora: datetime | None = None,
    limpiar: bool = False,
) -> dict:
    """Siembra el historial sintético y devuelve un resumen.

    Genera ticks cada ``paso_minutos`` hacia atrás desde ``ahora`` (inyectable
    para tests; default hora actual), cubriendo las últimas ``horas`` — ambos
    extremos incluidos, o sea ``horas*60/paso + 1`` ticks. En cada tick las 3
    tablas comparten el mismo ``timestamp``.

    Devuelve ``{"trafico": n, "aire": n, "clima": n, "desde": str, "hasta": str}``.
    """
    rng = random.Random(semilla)
    ahora = ahora if ahora is not None else datetime.now()
    n_pasos = int(horas * 60 // paso_minutos)

    if limpiar:
        limpiar_tablas()

    filas_trafico: list[dict] = []
    filas_aire: list[dict] = []
    filas_clima: list[dict] = []

    # Del tick más antiguo al más reciente (ambos incluidos).
    for i in range(n_pasos, -1, -1):
        ts = ahora - timedelta(minutes=i * paso_minutos)
        for zona in ZONAS:
            fila_t = _fila_trafico(zona, ts, rng)
            filas_trafico.append(fila_t)
            filas_aire.append(_fila_aire(zona, ts, fila_t["vehiculos"], rng))
        filas_clima.append(_fila_clima(ts, rng))

    n_trafico = insertar_trafico(pd.DataFrame(filas_trafico))
    n_aire = insertar_calidad_aire(pd.DataFrame(filas_aire))
    n_clima = insertar_clima(pd.DataFrame(filas_clima))

    return {
        "trafico": n_trafico,
        "aire": n_aire,
        "clima": n_clima,
        "desde": filas_clima[0]["timestamp"],
        "hasta": filas_clima[-1]["timestamp"],
    }


def main(argv: list[str] | None = None) -> None:
    """Punto de entrada CLI: parsea argumentos, siembra e imprime el resumen."""
    parser = argparse.ArgumentParser(
        description="Siembra datos históricos en la BD del proyecto.",
    )
    parser.add_argument(
        "--fuente",
        choices=("real", "sintetico"),
        default="real",
        help=(
            "'real': clima y aire históricos de Open-Meteo (resolución horaria) "
            "+ tráfico simulado; 'sintetico': todo simulado (default: real)"
        ),
    )
    parser.add_argument("--horas", type=float, default=24, help="horas hacia atrás (default: 24)")
    parser.add_argument(
        "--paso-minutos",
        type=float,
        default=1,
        help="minutos entre ticks, SOLO con --fuente sintetico; la fuente real es horaria (default: 1)",
    )
    parser.add_argument("--semilla", type=int, default=None, help="semilla para reproducibilidad")
    parser.add_argument("--limpiar", action="store_true", help="borra los datos existentes antes de sembrar")
    args = parser.parse_args(argv)

    if args.fuente == "real":
        try:
            resumen = sembrar_real(
                horas=args.horas,
                semilla=args.semilla,
                limpiar=args.limpiar,
            )
        except (requests.RequestException, ValueError) as error:
            print(f"ERROR: no se pudo obtener el histórico real de Open-Meteo: {error}", file=sys.stderr)
            print("Sugerencia: reintentar, o usar `--fuente sintetico` como fallback.", file=sys.stderr)
            sys.exit(1)
    else:
        resumen = sembrar(
            horas=args.horas,
            paso_minutos=args.paso_minutos,
            semilla=args.semilla,
            limpiar=args.limpiar,
        )
    print(f"Siembra completada (fuente: {args.fuente}):")
    print(f"  Trafico:           {resumen['trafico']} filas")
    print(f"  Calidad_Aire_Hist: {resumen['aire']} filas")
    print(f"  Condiciones_Clima: {resumen['clima']} filas")
    print(f"  Rango temporal:    {resumen['desde']} → {resumen['hasta']}")


if __name__ == "__main__":
    main()
