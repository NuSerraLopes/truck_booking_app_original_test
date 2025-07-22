# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\utils.py

from datetime import timedelta, date

from django.conf import settings
from django.core.mail import send_mail
from django.template import Template, Context
import logging

from .models import EmailTemplate, DistributionList, EmailLog

logger = logging.getLogger('booking_app')

def add_business_days(start_date, num_business_days):
    current_date = start_date
    days_added = 0
    while days_added < num_business_days:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:  # Check if it's a weekday (Monday-Friday)
            days_added += 1
    return current_date

def subtract_business_days(from_date, days):
    from datetime import timedelta
    current_date = from_date
    while days > 0:
        current_date -= timedelta(days=1)
        if current_date.weekday() < 5:
            days -= 1
    return current_date

def send_booking_notification(event_trigger, booking_instance=None, context_data=None, test_email_recipient=None):
    """
    Finds the active email template, builds the recipient list, sends the email,
    and logs the attempt to a file and the database.
    """
    try:
        template_obj = EmailTemplate.objects.get(event_trigger=event_trigger, is_active=True)
    except EmailTemplate.DoesNotExist:
        # Replace print() with logger.info()
        logger.info(f"No active email template found for event '{event_trigger}'. Skipping email.")
        return
    except EmailTemplate.MultipleObjectsReturned:
        # Replace print() with logger.error()
        logger.error(f"Multiple active templates found for event '{event_trigger}'. Please ensure only one is active.")
        return

    # --- Build the recipient list (your existing logic) ---
    recipient_list = set()
    if test_email_recipient:
        recipient_list.add(test_email_recipient)
    else:
        if template_obj.send_to_salesperson and booking_instance and booking_instance.user and booking_instance.user.email:
            recipient_list.add(booking_instance.user.email)
        # ... (rest of your recipient gathering logic) ...

    if not recipient_list:
        logger.info(f"No recipients found for event '{event_trigger}'. Skipping email.")
        return

    # --- Render the email content (your existing logic) ---
    context_dict = {'booking': booking_instance}
    if context_data:
        context_dict.update(context_data)
    context = Context(context_dict)
    subject_template = Template(template_obj.subject)
    body_template = Template(template_obj.body)
    rendered_subject = subject_template.render(context)
    rendered_body = body_template.render(context)
    final_recipient_list = list(recipient_list)

    # --- Send the email and log the result ---
    try:
        send_mail(
            subject=rendered_subject,
            message=rendered_body,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=final_recipient_list,
            html_message=rendered_body,
            fail_silently=False,
        )

        # Log success to the database
        for recipient in final_recipient_list:
            EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='sent')

        # Log success to the file
        logger.info(f"Successfully sent email for event '{event_trigger}' to {', '.join(final_recipient_list)}")

    except Exception as e:
        error_message = str(e)
        # Log failure to the database
        for recipient in final_recipient_list:
            EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='failed',
                                    error_message=error_message)

        # Log failure to the file
        logger.error(f"FAILED to send email for event '{event_trigger}'. Error: {error_message}")