#! /bin/bash
python manage.py collectstatic --noinput
python manage.py migrate
gunicorn STATZWeb.wsgi:application --bind 0.0.0.0:$PORT --workers 3