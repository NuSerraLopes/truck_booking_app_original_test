# In booking_app/management/commands/update_ended_bookings.py

import logging
from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from booking_app.models import Booking
from booking_app.utils import send_system_notification

logger = logging.getLogger('booking_app')


class Command(BaseCommand):
    help = 'Checks for confirmed bookings that ended yesterday and moves them to "Pending Final KM".'

    def handle(self, *args, **options):
        yesterday = timezone.now().date() - timedelta(days=1)

        # Find all bookings that were 'confirmed' and ended yesterday.
        ended_bookings = Booking.objects.filter(
            status='confirmed',
            end_date=yesterday
        )

        if not ended_bookings.exists():
            self.stdout.write(self.style.SUCCESS('No bookings ended yesterday. Exiting.'))
            return

        self.stdout.write(
            f'Found {ended_bookings.count()} bookings that ended yesterday. Updating status and sending notifications...')

        updated_count = 0
        for booking in ended_bookings:
            try:
                booking.status = 'pending_final_km'
                booking.save(update_fields=['status'])

                # Send a notification to prompt for final KM entry
                send_system_notification(
                    event_trigger='booking_ended_pending_km',
                    context_data={"booking_instance":booking}
                )
                updated_count += 1
                logger.info(f"Moved Booking ID {booking.pk} to 'Pending Final KM'.")
            except Exception as e:
                logger.error(f"Failed to update Booking ID {booking.pk}. Error: {e}")

        self.stdout.write(self.style.SUCCESS(f'Successfully updated {updated_count} bookings.'))