"""Scheduler de ingesta continua (APScheduler).

Ejecutará periódicamente (~cada 10 s) la obtención de clima/aire y la generación
de tráfico simulado, insertando los resultados en la BD.

TODO: configurar el scheduler y registrar los jobs. Por ahora es solo un stub.
Sirve como punto de entrada del servicio `simulador` en docker-compose.
"""


def main() -> None:
    """Punto de entrada del servicio de ingesta. TODO: implementar."""
    raise NotImplementedError("Scheduler de ingesta aún no implementado.")


if __name__ == "__main__":
    main()
