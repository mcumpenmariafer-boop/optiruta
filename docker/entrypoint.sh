#!/bin/sh
set -e
echo "Esperando a PostgreSQL en $DB_HOST:$DB_PORT..."
until python -c "import psycopg,os; psycopg.connect(host=os.environ['DB_HOST'], port=os.environ.get('DB_PORT','5432'), user=os.environ['DB_USER'], password=os.environ['DB_PASSWORD'], dbname=os.environ['DB_NAME']).close()" 2>/dev/null; do
  sleep 1
done
# Solo el servicio web prepara la base y los estáticos (worker y beat solo esperan)
if [ "$1" = "daphne" ]; then
  python manage.py migrate --noinput
  python manage.py collectstatic --noinput
  if [ "$CARGAR_DEMO" = "1" ]; then
    python manage.py cargar_demo || true
  fi
fi
exec "$@"
