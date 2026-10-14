FROM pypy:3.10-slim

ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencias de sistema necesarias para Pillow y numpy
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libjpeg-dev \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias con pip de PyPy
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar código de la aplicación
COPY . .

# Iniciar servidor
CMD ["pypy3", "server.py"]
