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
    Finds ALL active email templates for a given event, builds the recipient list
    for EACH template, sends the email, and logs the attempt.
    """
    final_trigger = event_trigger

    # --- Dynamic Trigger Logic (remains the same) ---
    if event_trigger in ['booking_created', 'booking_reverted'] and booking_instance:
        vehicle_type = booking_instance.vehicle.vehicle_type.lower()
        final_trigger = f"{vehicle_type}_{event_trigger}"

    # --- UPDATED LOGIC: Use .filter() to get all matching templates ---
    template_list = EmailTemplate.objects.filter(event_trigger=final_trigger, is_active=True)

    if not template_list.exists():
        logger.info(f"No active email templates found for event '{final_trigger}'. Skipping email.")
        return

    # --- Loop through each found template and send an email ---
    for template_obj in template_list:
        # Build the recipient list specifically for THIS template
        recipient_list = set()
        if test_email_recipient:
            recipient_list.add(test_email_recipient)
        else:
            if template_obj.send_to_salesperson and booking_instance and booking_instance.user and booking_instance.user.email:
                recipient_list.add(booking_instance.user.email)
            if template_obj.send_to_groups.exists():
                for group in template_obj.send_to_groups.all():
                    for user in group.user_set.filter(is_active=True, email__isnull=False):
                        recipient_list.add(user.email)
            if template_obj.send_to_users.exists():
                for user in template_obj.send_to_users.filter(is_active=True, email__isnull=False):
                    recipient_list.add(user.email)
            if template_obj.send_to_distribution_lists.exists():
                for dl in template_obj.send_to_distribution_lists.all():
                    recipient_list.update(dl.get_emails_as_list())

        if not recipient_list:
            logger.info(f"Template '{template_obj.name}' for event '{final_trigger}' has no recipients. Skipping.")
            continue # Move to the next template

        # --- Render the email content ---
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
            for recipient in final_recipient_list:
                EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='sent')
            logger.info(f"Successfully sent email using template '{template_obj.name}' to {', '.join(final_recipient_list)}")
        except Exception as e:
            error_message = str(e)
            for recipient in final_recipient_list:
                EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='failed', error_message=error_message)
            logger.error(f"FAILED to send email using template '{template_obj.name}'. Error: {error_message}")