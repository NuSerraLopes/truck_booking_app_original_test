from django.core.management.base import BaseCommand
from booking_app.models import Booking
from booking_app.utils import _recompute_single_transport

class Command(BaseCommand):
    help = "Recompute transports for all confirmed bookings"

    def handle(self, *args, **kwargs):
        qs = Booking.objects.filter(status__in=["confirmed", "pending_final_km"]).select_related("vehicle")
        count = 0
        for b in qs.order_by("vehicle_id", "start_date"):
            _recompute_single_transport(b)
            count += 1
        self.stdout.write(self.style.SUCCESS(f"Recomputed {count} transports"))