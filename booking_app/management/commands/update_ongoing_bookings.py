# In booking_app/management/commands/update_ended_bookings.py

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from booking_app.models import Booking
from booking_app.tasks import send_system_notification_task

logger = logging.getLogger('booking_app')


class Command(BaseCommand):
    help = 'Checks for confirmed bookings that started yesterday and moves them to "Ongoing".'

    def handle(self, *args, **options):
        yesterday = timezone.now().date() - timedelta(days=1)

        # Find all bookings that were 'confirmed' and started yesterday.
        ongoing_bookings = Booking.objects.filter(
            status='confirmed',
            start_date=yesterday
        )

        if not ongoing_bookings.exists():
            self.stdout.write(self.style.SUCCESS('No bookings started yesterday. Exiting.'))
            return

        self.stdout.write(
            f'Found {ongoing_bookings.count()} bookings that started yesterday. Updating status and sending notifications...')

        updated_count = 0
        for booking in ongoing_bookings:
            try:
                booking.status = 'ongoing'
                booking.save(update_fields=['status'])

                send_system_notification_task.delay(booking.pk)
                updated_count += 1
                logger.info(f"Moved Booking ID {booking.pk} to 'Ongoing'.")
            except Exception as e:
                logger.error(f"Failed to update Booking ID {booking.pk}", exc_info=True)

        self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} bookings.'))