#!/usr/bin/env bash
# Construcción en Render: instala, prepara archivos estáticos, migra y carga la demo (solo la primera vez).
set -o errexit
pip install -r requirements.txt
python manage.py collectstatic --noinput
python manage.py migrate --noinput
python manage.py cargar_demo
