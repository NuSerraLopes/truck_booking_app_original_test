from django.core.management.base import BaseCommand
from django.utils.timezone import now, timedelta
from booking_app.models import Transport
from booking_app.utils import send_system_notification

class Command(BaseCommand):
    help = "Send a weekly digest email with all required transports."

    def handle(self, *args, **kwargs):
        today = now().date()
        end_of_week = today + timedelta(days=7)

        transports = Transport.objects.filter(
            booking__start_date__range=(today, end_of_week),
            booking__status="confirmed"
        ).select_related("booking", "origin_location", "destination_location", "booking__vehicle")

        if not transports.exists():
            self.stdout.write(self.style.WARNING("No transports this week."))
            return

        context = {
            "transports": transports,
            "week_start": today,
            "week_end": end_of_week,
        }

        send_system_notification(
            event_trigger="weekly_transport_digest",
            context_data=context,
        )

        self.stdout.write(self.style.SUCCESS(f"Weekly transport digest sent with {transports.count()} entries."))