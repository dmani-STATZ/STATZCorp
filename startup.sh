#! /bin/bash
# Activate the virtual environment
# source venv/bin/activate

# Run Django startup commands
echo "Running Collectstatic..."
python manage.py collectstatic --noinput || true

echo "Running Migrations..."
python manage.py migrate || true

echo "Setting Build Info..."
python manage.py set_build_info --auto || true

echo "Running Gunicorn..."
gunicorn STATZWeb.wsgi:application --bind 0.0.0.0:$PORT --workers 3
