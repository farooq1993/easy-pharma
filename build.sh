#!/bin/bash

echo "Building the project..."
python3.12 -m pip install -r requirements.txt

echo "Running Migrations..."
python3.12 manage.py makemigrations --noinput
python3.12 manage.py migrate --noinput

echo "Collecting Static Files..."
python3.12 manage.py collectstatic --noinput --clear

echo "Creating Superuser..."
python3.12 manage.py shell <<EOF
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
    print('ADMIN_USERNAME or ADMIN_PASSWORD not set. Skipping superuser creation.')
EOF
