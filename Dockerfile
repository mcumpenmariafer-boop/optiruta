# Imagen de OptiRuta (Tema 2.4: Dockerizando una aplicación Django)
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN chmod +x docker/entrypoint.sh build.sh

EXPOSE 8000
ENTRYPOINT ["docker/entrypoint.sh"]
# Daphne: servidor ASGI que atiende HTTP y WebSockets
CMD ["daphne", "-b", "0.0.0.0", "-p", "8000", "config.asgi:application"]
