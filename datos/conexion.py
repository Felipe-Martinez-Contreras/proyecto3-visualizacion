"""Utilidades de conexión a la base de datos SQLite.

La ruta de la BD se toma de la variable de entorno `DB_PATH` (ver `.env.example`),
con `db/monitoreo.sqlite` como valor por defecto.

TODO: ampliar según necesidad (context managers, pragmas). Mínimo por ahora.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

# Raíz del repo (dos niveles arriba de este archivo: datos/ -> repo/).
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = REPO_ROOT / "db" / "monitoreo.sqlite"


def get_db_path() -> Path:
    """Devuelve la ruta de la BD (env `DB_PATH` o el valor por defecto del repo)."""
    return Path(os.environ.get("DB_PATH", DEFAULT_DB_PATH))


def get_connection() -> sqlite3.Connection:
    """Abre una conexión a la BD SQLite. El llamador es responsable de cerrarla."""
    return sqlite3.connect(get_db_path())
