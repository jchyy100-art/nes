FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias limpias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Iniciar servidor FastAPI con Uvicorn en el puerto dinámico $PORT
CMD ["sh", "-c", "uvicorn server:app --host 0.0.0.0 --port ${PORT:-8000}"]
