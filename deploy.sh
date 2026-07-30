#!/bin/bash
set -e

echo "=== Updating apt packages ==="
apt-get update
apt-get install -y python3-pip python3-venv nginx certbot python3-certbot-nginx

echo "=== Extracting project files ==="
mkdir -p /var/www/easypharma
tar -xzf /tmp/project.tar.gz -C /var/www/easypharma

echo "=== Creating default .env ==="
if [ ! -f /var/www/easypharma/.env ]; then
cat <<EOT > /var/www/easypharma/.env
DJANGO_SECRET_KEY=django-insecure-vps-production-key
DJANGO_DEBUG=False
DATABASE_URL=paste_your_neon_database_url_here
EOT
fi

echo "=== Creating virtual environment ==="
python3 -m venv /var/www/easypharma/venv
/var/www/easypharma/venv/bin/pip install --upgrade pip
/var/www/easypharma/venv/bin/pip install -r /var/www/easypharma/requirements.txt

echo "=== Collecting static files ==="
/var/www/easypharma/venv/bin/python /var/www/easypharma/manage.py collectstatic --noinput

echo "=== Configuring Gunicorn socket ==="
cat <<EOT > /etc/systemd/system/gunicorn.socket
[Unit]
Description=gunicorn socket

[Socket]
ListenStream=/run/gunicorn.sock

[Install]
WantedBy=sockets.target
EOT

echo "=== Configuring Gunicorn service ==="
cat <<EOT > /etc/systemd/system/gunicorn.service
[Unit]
Description=gunicorn daemon
Requires=gunicorn.socket
After=network.target

[Service]
User=root
Group=www-data
WorkingDirectory=/var/www/easypharma
ExecStart=/var/www/easypharma/venv/bin/gunicorn \
          --access-logfile - \
          --workers 3 \
          --bind unix:/run/gunicorn.sock \
          pharmaProject.wsgi:application

[Install]
WantedBy=multi-user.target
EOT

echo "=== Configuring Nginx ==="
cat <<EOT > /etc/nginx/sites-available/easypharma
server {
    listen 80;
    server_name 200.141.7.142;

    location = /favicon.ico { access_log off; log_not_found off; }
    
    location /static/ {
        alias /var/www/easypharma/staticfiles/;
    }

    location / {
        include proxy_params;
        proxy_pass http://unix:/run/gunicorn.sock;
    }
}
EOT

echo "=== Enabling Nginx configuration ==="
ln -sf /etc/nginx/sites-available/easypharma /etc/nginx/sites-enabled/
rm -f /etc/nginx/sites-enabled/default

echo "=== Starting and Enabling Services ==="
systemctl daemon-reload
systemctl start gunicorn.socket
systemctl enable gunicorn.socket
systemctl restart gunicorn
systemctl restart nginx

echo "=== Gunicorn Status ==="
systemctl status gunicorn.socket --no-pager
systemctl status gunicorn --no-pager

echo "=== Nginx Status ==="
systemctl status nginx --no-pager

echo "=== Deployment script finished successfully! ==="
