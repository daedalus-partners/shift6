#!/bin/bash
# Auto-deploy script for shift6
# Called by webhook on GitHub push

set -e

cd /var/www/shift6

echo "$(date): Starting deploy..."

# Pull latest code
git -c safe.directory=/var/www/shift6 pull origin master

# Rebuild and restart containers
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build

echo "$(date): Deploy complete!"
