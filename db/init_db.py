"""Crea (o recrea) el archivo SQLite `db/monitoreo.sqlite` aplicando `db/schema.sql`.

Uso:
    python db/init_db.py

Es idempotente: el esquema usa `CREATE TABLE IF NOT EXISTS`, por lo que ejecutarlo
sobre una BD existente no borra datos ni falla. El archivo resultante se versiona en
git para que todo el equipo comparta la misma base (decisión del equipo).
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

# Rutas relativas a este archivo, para que funcione sin importar el cwd.
DB_DIR = Path(__file__).resolve().parent
SCHEMA_PATH = DB_DIR / "schema.sql"
DB_PATH = DB_DIR / "monitoreo.sqlite"


def init_db(db_path: Path = DB_PATH, schema_path: Path = SCHEMA_PATH) -> None:
    """Aplica el esquema SQL sobre `db_path`, creando el archivo si no existe."""
    schema_sql = schema_path.read_text(encoding="utf-8")
    with sqlite3.connect(db_path) as conn:
        conn.executescript(schema_sql)
    print(f"Base de datos lista en: {db_path}")


if __name__ == "__main__":
    init_db()
