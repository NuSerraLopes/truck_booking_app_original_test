# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\utils.py

from datetime import timedelta, date
from django.core.mail import send_mail
from django.template import Template, Context
from .models import EmailTemplate

def add_business_days(start_date, num_business_days):
    """
    Adds a specified number of business days (excluding weekends) to a start date.
    Args:
        start_date (datetime.date): The date from which to start counting.
        num_business_days (int): The number of business days to add.
    Returns:
        datetime.date: The calculated date after adding business days.
    """
    current_date = start_date
    days_added = 0
    while days_added < num_business_days:
        current_date += timedelta(days=1)
        # weekday() returns 0 for Monday, 1 for Tuesday, ..., 5 for Saturday, 6 for Sunday
        if current_date.weekday() < 5:  # Check if it's a weekday (Monday-Friday)
            days_added += 1
    return current_date


def send_booking_notification(event_trigger, booking_instance=None, context_data=None, test_email_recipient=None):
    """
    Finds the active email template, builds the recipient list, and sends the email.
    If test_email_recipient is provided, it sends only to that address.
    """
    try:
        template_obj = EmailTemplate.objects.get(event_trigger=event_trigger, is_active=True)
    except EmailTemplate.DoesNotExist:
        # ... (error handling remains the same) ...
        return

    # --- Build the recipient list ---
    recipient_list = set()

    if test_email_recipient:
        # If this is a test, only send to the specified recipient
        recipient_list.add(test_email_recipient)
    else:
        # --- Original recipient logic ---
        if template_obj.send_to_salesperson and booking_instance and booking_instance.user.email:
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

    # ... (the rest of the function remains the same) ...
    # --- Render the email content ---
    context_dict = {'booking': booking_instance}
    if context_data:
        context_dict.update(context_data)
    context = Context(context_dict)
    subject_template = Template(template_obj.subject)
    body_template = Template(template_obj.body)
    rendered_subject = subject_template.render(context)
    rendered_body = body_template.render(context)

    # --- Send the email ---
    try:
        send_mail(
            rendered_subject,
            rendered_body,
            'no-reply@yourcompany.com',
            list(recipient_list),
            html_message=rendered_body,
            fail_silently=False,
        )
        print(f"Successfully sent email for event '{event_trigger}' to {list(recipient_list)}")
    except Exception as e:
        print(f"ERROR sending email for event '{event_trigger}': {e}")