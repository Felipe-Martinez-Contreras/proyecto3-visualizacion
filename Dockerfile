# Imagen base común para los servicios Python (simulador y dashboard).
# Ambos servicios usan esta misma imagen y cambian solo el comando (ver
# docker-compose.yml), para mantenerlo simple.

FROM python:3.12-slim

WORKDIR /app

# Instalar dependencias primero para aprovechar la caché de capas.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del proyecto.
COPY . .

# Comando por defecto (el compose lo sobrescribe por servicio).
CMD ["python", "-m", "dashboard.app"]
