"""Verifica que la BD SQLite exista y tenga las 3 tablas del modelo de datos."""

import sqlite3

from datos.conexion import get_db_path

TABLAS_ESPERADAS = {"Trafico", "Calidad_Aire_Hist", "Condiciones_Clima"}


def test_bd_existe():
    assert get_db_path().exists(), (
        "No existe la BD. Créala con: python db/init_db.py"
    )


def test_bd_tiene_las_tres_tablas():
    conn = sqlite3.connect(get_db_path())
    try:
        filas = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        conn.close()
    tablas = {fila[0] for fila in filas}
    assert TABLAS_ESPERADAS.issubset(tablas), (
        f"Faltan tablas. Esperadas: {TABLAS_ESPERADAS}, encontradas: {tablas}"
    )
