-- Esquema de la base de datos del proyecto (SQLite).
-- Modelo de datos: 3 tablas relacionadas por `timestamp` (y `zona` cuando aplica).
-- El clima es GLOBAL para la ciudad, por eso NO tiene columna `zona`.
--
-- Este archivo es la única fuente de verdad del esquema. Para (re)crear la BD:
--     python db/init_db.py

-- Movilidad urbana: conteo de vehículos y velocidad promedio por zona.
CREATE TABLE IF NOT EXISTS Trafico (
    id                  INTEGER PRIMARY KEY,
    timestamp           TEXT,
    zona                TEXT,
    vehiculos           INTEGER,
    velocidad_promedio  REAL
);

-- Histórico de calidad del aire por zona.
-- pm25 = material particulado fino · no2 = dióxido de nitrógeno · o3 = ozono.
CREATE TABLE IF NOT EXISTS Calidad_Aire_Hist (
    id          INTEGER PRIMARY KEY,
    timestamp   TEXT,
    zona        TEXT,
    pm25        REAL,
    no2         REAL,
    o3          REAL
);

-- Condiciones de clima. Global para la ciudad: sin columna `zona`.
CREATE TABLE IF NOT EXISTS Condiciones_Clima (
    id           INTEGER PRIMARY KEY,
    timestamp    TEXT,
    temperatura  REAL,
    humedad      REAL,
    viento       REAL
);
