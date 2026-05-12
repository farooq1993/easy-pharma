#!/bin/bash

# Exit on error
set -e

echo "--- STARTING VERCEL BUILD ---"

# Install dependencies
echo "Installing requirements..."
pip install -r requirements.txt

# Run migrations
echo "Running database migrations..."
python manage.py migrate --noinput

# Collect static files
echo "Collecting static files..."
python manage.py collectstatic --noinput --clear

# Create superuser if env vars exist
echo "Checking for superuser creation..."
python manage.py shell <<EOF
from easypharma.models import User
import os
username = os.environ.get('ADMIN_USERNAME')
password = os.environ.get('ADMIN_PASSWORD')
if username and password:
    if not User.objects.filter(username=username).exists():
        User.objects.create_superuser(username=username, password=password, user_type='admin')
        print(f'Superuser "{username}" created successfully.')
    else:
        print(f'Superuser "{username}" already exists.')
else:
    print('ADMIN_USERNAME or ADMIN_PASSWORD not set. Skipping.')
EOF

echo "--- VERCEL BUILD COMPLETE ---"
