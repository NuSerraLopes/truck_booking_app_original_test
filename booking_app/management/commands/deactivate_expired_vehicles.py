from django.core.management.base import BaseCommand
from booking_app.models import Vehicle
from booking_app.utils import send_system_notification
from datetime import date

class Command(BaseCommand):
    help = "Deactivate vehicles whose end_date has passed and notify stakeholders"

    def handle(self, *args, **kwargs):
        today = date.today()
        expired_qs = Vehicle.objects.filter(end_date__lt=today, active_status=True)

        # Capture list before update
        expired_vehicles = list(expired_qs)

        count = expired_qs.update(active_status=False, is_available=False)
        self.stdout.write(self.style.SUCCESS(f"{count} vehicles deactivated"))

        if count > 0:
            # Prepare context for email templates
            context_data = {
                "date": today,
                "vehicles": expired_vehicles,  # pass queryset list for looping in template
            }

            send_system_notification(
                event_trigger="vehicles_deactivated_auto",
                context_data=context_data
            )
