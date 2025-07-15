from django.core.management.base import BaseCommand
from datetime import date, timedelta
from booking_app.models import Booking, AutomationSettings
from booking_app.utils import send_booking_notification
from django.utils import timezone
from django.utils.translation import gettext as _


class Command(BaseCommand):
    help = 'Checks for pending bookings to send reminders or cancel them.'

    def handle(self, *args, **options):
        settings = AutomationSettings.load()
        if not settings.pending_booking_automation_active:
            self.stdout.write('Pending booking automation is disabled. Exiting.')
            return

        self.stdout.write('Checking pending bookings...')
        today = date.today()

        # --- Handle 7-Day Reminders ---
        reminder_date = today + timedelta(days=7)
        bookings_to_remind = Booking.objects.filter(status='pending', start_date=reminder_date)

        for booking in bookings_to_remind:
            send_booking_notification('booking_reminder_7_days', booking_instance=booking)
            self.stdout.write(self.style.SUCCESS(f'Sent 7-day reminder for Booking ID: {booking.pk}'))

        # --- Handle Cancellations for Tomorrow's Bookings ---
        cancellation_date = today + timedelta(days=1)
        bookings_to_cancel = Booking.objects.filter(status='pending', start_date=cancellation_date)

        for booking in bookings_to_cancel:
            send_booking_notification('booking_auto_cancelled', booking_instance=booking)
            booking.status = 'cancelled'
            booking.cancellation_time = timezone.now()
            booking.cancellation_reason = _(
                "Automatically cancelled due to non-approval before start date.")  # Set a reason
            booking.save()
            self.stdout.write(self.style.WARNING(f'Auto-cancelled Booking ID: {booking.pk}'))

        self.stdout.write(self.style.SUCCESS('Pending booking check complete.'))