#!/bin/bash

echo "Starting deployment..."

# 1. Activate maintenance mode
touch /var/www/booking_app/maintenance.flag
echo "Maintenance mode ON"

# 2. Stop the Django application server
sudo systemctl stop gunicorn
echo "Gunicorn server stopped."

# 3. Pull latest code, update environment, and run Django commands
# (Activate virtual environment if not already active in the script's context)
source /var/www/booking_app/.venv/bin/activate
git pull origin master
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
echo "Code updated and Django commands executed."

# 4. Restart the Django application server
sudo systemctl start gunicorn
echo "Gunicorn server started."

# 5. Deactivate maintenance mode
rm /var/www/booking_app/maintenance.flag
echo "Maintenance mode OFF. Deployment complete."