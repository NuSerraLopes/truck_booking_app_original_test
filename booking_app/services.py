# services.py
import os

import requests
from .models import Booking

WEBHOOK_URL = os.environ.get('WEBHOOK_URL')

def send_booking_to_webservice(booking: Booking):
    vehicle = booking.vehicle
    client = booking.client

    data = {
        "client": {
            "name": client.name if client else None,
            "address": client.address if client else None,
            "tax_number": client.tax_number if client else None,
        },
        "vehicle": {
            "model": vehicle.model,
            "type": vehicle.vehicle_type,
            "chassis": vehicle.chassis,
            "viaverde_id": vehicle.viaverde_id,
            "is_electric": vehicle.is_electric,
            "vehicle_km": vehicle.vehicle_km,
        },
        "booking": {
            "start_date": booking.start_date.isoformat() if booking.start_date else None,
            "end_date": booking.end_date.isoformat() if booking.end_date else None,
        },
    }

    try:
        response = requests.post(WEBHOOK_URL, json=data, timeout=10)
        response.raise_for_status()
        return True, response.json() if response.content else {}
    except requests.RequestException as e:
        return False, str(e)
