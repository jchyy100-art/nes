FROM python:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Instalar dependencias limpias de Python sin paquetes GUI
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el código de la aplicación
COPY . .

# Iniciar servidor (lee automáticamente la variable $PORT que inyecta Railway o Render)
CMD ["python", "server.py"]
