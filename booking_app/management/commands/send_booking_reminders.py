# In booking_app/management/commands/send_booking_reminders.py

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from booking_app.models import AutomationSettings, Booking
from booking_app.utils import send_system_notification

logger = logging.getLogger('booking_app')


class Command(BaseCommand):
    help = 'Checks for pending bookings that are older than the configured time and sends reminder emails.'

    def handle(self, *args, **options):
        try:
            settings = AutomationSettings.objects.first()
            if not settings or not settings.enable_pending_reminders or settings.reminder_days_pending <= 0:
                self.stdout.write(self.style.SUCCESS('Pending booking reminders are disabled. Exiting.'))
                return
        except AutomationSettings.DoesNotExist:
            self.stdout.write(self.style.WARNING('Automation settings not found. Exiting.'))
            return

        # Calculate the cutoff date. Any pending booking created on or before this date is overdue.
        cutoff_date = timezone.now() - timedelta(days=settings.reminder_days_pending)

        # Find all overdue bookings that are still in 'pending' status.
        overdue_bookings = Booking.objects.filter(
            status='pending',
            created_at__lte=cutoff_date
        )

        if not overdue_bookings.exists():
            self.stdout.write(self.style.SUCCESS('No overdue pending bookings found.'))
            return

        self.stdout.write(f'Found {overdue_bookings.count()} overdue pending bookings. Sending reminders...')

        sent_count = 0
        for booking in overdue_bookings:
            try:
                # Use your existing notification function with a new event trigger
                send_system_notification(
                    event_trigger='booking_pending_reminder',
                    context_data={"booking_instance":booking}
                )
                sent_count += 1
                logger.info(f"Sent pending reminder for Booking ID: {booking.pk}")
            except Exception as e:
                logger.error(f"Failed to send pending reminder for Booking ID: {booking.pk}. Error: {e}")

        self.stdout.write(self.style.SUCCESS(f'Successfully sent {sent_count} reminders.'))
