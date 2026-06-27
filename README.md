# Monitor Urbano - Proyecto Unidad 3

## Setup
1. Crear entorno virtual: `python -m venv venv`
2. Activar entorno e instalar: `pip install -r requirements.txt`
3. Configurar `.env` con credenciales de PostgreSQL
4. Crear la base de datos: `monitoreo_urbano`
5. Iniciar ingesta: `python data/ingesta.py`
6. Iniciar dashboard: `python app/dashboard.py`