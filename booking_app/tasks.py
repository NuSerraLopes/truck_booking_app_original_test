from celery import shared_task
from django.core.mail import mail_admins
from django.utils.timezone import now
from datetime import timedelta
from booking_app.utils import send_system_notification, sanitize_context
import logging

logger = logging.getLogger("booking_app")

@shared_task
def send_system_notification_task(event_trigger, context_data=None, test_email_recipient=None):
    """
    Background task to send ANY system notification asynchronously.
    """

    try:
        safe_context = sanitize_context(context_data)
        send_system_notification(
            event_trigger=event_trigger,
            context_data=safe_context,
            test_email_recipient=test_email_recipient
        )
        logger.info(f"Notification '{event_trigger}' sent successfully via Celery")
    except Exception as e:
        logger.error(f"Failed to send system notification '{event_trigger}': {e}", exc_info=True)


@shared_task
def send_daily_error_report():
    """Collect errors from log file and send them to admins once per day."""
    log_file = "debug.log"  # same file as your FileHandler
    errors = []

    try:
        yesterday = now() - timedelta(days=1)
        with open(log_file, "r") as f:
            for line in f:
                if "ERROR" in line:
                    errors.append(line.strip())

        if errors:
            body = "\n".join(errors[-100:])  # limit to last 100 errors
            mail_admins(
                subject="Daily Error Report",
                message=body
            )
            logger.info("Daily error report sent to admins")
        else:
            logger.info("No errors found for daily report")

    except Exception as e:
        logger.error(f"Failed to generate daily error report: {e}", exc_info=True)
