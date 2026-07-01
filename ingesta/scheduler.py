"""Motor de ingesta: un "tick" del ciclo de datos y su scheduler periódico.

Este módulo es la capa de ORQUESTACIÓN que cierra el ciclo de datos: junta las
piezas ya construidas (simulador de tráfico, calidad del aire, clima) y persiste
sus salidas en la BD compartida (SQLite) a través de ``datos/repositorio.py``.

Dos niveles, a propósito separados:

- ``ejecutar_tick(timestamp=None)``: UNA iteración del ciclo (pura orquestación,
  testeable). Genera tráfico simulado, consulta aire por zona y clima global, y
  lo inserta en la BD. Todas las filas de una misma iteración comparten el mismo
  ``timestamp`` (coherencia temporal). El ``timestamp`` es inyectable para que los
  tests no dependan de la hora real.

- ``iniciar()`` / ``main()``: el runtime. Programa ``ejecutar_tick`` para que se
  ejecute cada ``INTERVALO_SIMULACION`` segundos con APScheduler. Es el punto de
  entrada del servicio ``simulador`` en docker-compose. NO se ejecuta en tests.

Manejo mínimo de errores: cada fuente se ejecuta en su propio bloque
``try/except``; si una falla (p.ej. red), se registra por stdout y el tick sigue
con las demás. Nunca se cae el ciclo entero por una sola fuente.
"""

from __future__ import annotations

import os
from datetime import datetime

from dotenv import load_dotenv

from datos import repositorio
from ingesta import aire, apis, simulador, transformacion

# Carga `.env` si existe (no pisa variables ya definidas en el entorno).
load_dotenv()

# Intervalo (segundos) entre ticks del scheduler. Reutiliza la variable ya prevista
# en `.env.example` (INTERVALO_SIMULACION); por defecto 10 s.
INTERVALO_SIMULACION = int(os.environ.get("INTERVALO_SIMULACION", "10"))

# Coordenadas GLOBALES de la ciudad para el clima (Open-Meteo se consulta con una
# sola coordenada porque el clima no se desagrega por zona).
CLIMA_LATITUD = float(os.environ.get("CLIMA_LATITUD", "-33.45"))
CLIMA_LONGITUD = float(os.environ.get("CLIMA_LONGITUD", "-70.66"))


def ejecutar_tick(timestamp: str | None = None) -> dict[str, int]:
    """Ejecuta UNA iteración del ciclo de ingesta y devuelve un resumen.

    Orden: tráfico simulado → calidad del aire (por zona) → clima global. Todas
    las filas comparten el mismo ``timestamp`` (por defecto ``datetime.now()``),
    inyectable para tests deterministas.

    Cada fuente va en su propio ``try/except``: si una falla, se registra por
    stdout y el tick continúa con las demás (nunca se cae entero).

    Devuelve un ``dict`` con el número de filas insertadas por tabla::

        {"trafico": 3, "aire": 3, "clima": 1}
    """
    if timestamp is None:
        timestamp = datetime.now().isoformat()

    resumen = {"trafico": 0, "aire": 0, "clima": 0}

    # --- Tráfico simulado (no usa red) ---------------------------------------
    try:
        df_trafico = simulador.generar_trafico(timestamp=timestamp)
        resumen["trafico"] = repositorio.insertar_trafico(df_trafico)
    except Exception as error:  # noqa: BLE001 - manejo mínimo: registrar y seguir.
        print(f"[scheduler] Fallo generando/insertando tráfico ({error!r}).")

    # --- Calidad del aire por zona (usa red, con fallback interno) -----------
    # Cada zona por separado: si una falla, las demás igual se insertan.
    for zona in simulador.ZONAS:
        try:
            df_aire = aire.obtener_calidad_aire_zona(zona)
            # Unificamos el timestamp con el del tick para que toda la iteración
            # comparta instante (coherencia temporal en el dashboard).
            df_aire["timestamp"] = timestamp
            resumen["aire"] += repositorio.insertar_calidad_aire(df_aire)
        except Exception as error:  # noqa: BLE001
            print(f"[scheduler] Fallo con calidad del aire de '{zona}' ({error!r}).")

    # --- Clima global (usa red) ----------------------------------------------
    try:
        cruda = apis.obtener_clima(CLIMA_LATITUD, CLIMA_LONGITUD)
        df_clima = transformacion.normalizar_clima(cruda)
        # El clima no trae `timestamp` propio coherente con el tick; lo unificamos
        # con el de la iteración para que todo el ciclo comparta instante.
        df_clima["timestamp"] = timestamp
        resumen["clima"] = repositorio.insertar_clima(df_clima)
    except Exception as error:  # noqa: BLE001
        print(f"[scheduler] Fallo obteniendo/insertando clima ({error!r}).")

    print(
        f"[scheduler] Tick {timestamp}: "
        f"trafico={resumen['trafico']}, aire={resumen['aire']}, clima={resumen['clima']}."
    )
    return resumen


def iniciar(intervalo_segundos: int = INTERVALO_SIMULACION) -> None:
    """Programa ``ejecutar_tick`` cada ``intervalo_segundos`` y bloquea el proceso.

    Usa un ``BlockingScheduler`` de APScheduler: el proceso queda vivo ejecutando
    el tick periódicamente. Es el bucle de runtime; NO se ejecuta en tests.
    """
    # Import local: APScheduler solo hace falta en el runtime, no al importar el
    # módulo para testear `ejecutar_tick`.
    from apscheduler.schedulers.blocking import BlockingScheduler

    scheduler = BlockingScheduler()
    scheduler.add_job(
        ejecutar_tick,
        trigger="interval",
        seconds=intervalo_segundos,
        # Ejecuta un primer tick de inmediato en vez de esperar el primer intervalo.
        next_run_time=datetime.now(),
        # Si un tick se atrasa, agrupa las ejecuciones pendientes en una sola.
        coalesce=True,
        max_instances=1,
    )
    print(
        f"[scheduler] Iniciando ingesta cada {intervalo_segundos} s. Ctrl-C para salir."
    )
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        print("[scheduler] Detenido.")


def main() -> None:
    """Punto de entrada del servicio de ingesta (docker-compose: `simulador`)."""
    iniciar()


if __name__ == "__main__":
    main()
