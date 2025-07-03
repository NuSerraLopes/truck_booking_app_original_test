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


def send_booking_notification(booking, template_key):
    try:
        template_obj = EmailTemplate.objects.get(template_key=template_key)

        context = Context({'booking': booking})

        subject_template = Template(template_obj.subject)
        body_template = Template(template_obj.body)

        rendered_subject = subject_template.render(context)
        rendered_body = body_template.render(context)

        send_mail(
            rendered_subject,
            rendered_body,
            'geral@nulopes.me',  # Replace with your from-email
            [booking.user.email],
            html_message=rendered_body,
            fail_silently=False,
        )
    except EmailTemplate.DoesNotExist:
        print(f"ERROR: Email template with key '{template_key}' not found.")
    except Exception as e:
        print(f"ERROR sending email: {e}")