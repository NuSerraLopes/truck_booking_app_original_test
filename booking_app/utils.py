# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\utils.py

import logging
from datetime import timedelta

import msal  # <-- ADDED for Microsoft Auth
import requests
from django.conf import settings
from django.template import Template, Context

from .models import EmailTemplate, EmailLog

logger = logging.getLogger('booking_app')


# ==============================================================================
# NEW MICROSOFT GRAPH API FUNCTIONS
# ==============================================================================

def get_graph_api_access_token():
    """
    Acquires an access token from Microsoft Identity Platform.
    """
    # Use credentials from your settings.py
    authority = f"https://login.microsoftonline.com/{settings.MS_GRAPH_TENANT_ID}"
    app = msal.ConfidentialClientApplication(
        client_id=settings.MS_GRAPH_CLIENT_ID,
        authorities=[authority],
        client_credential=settings.MS_GRAPH_CLIENT_SECRET,
    )

    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_silent(scopes=scopes, account=None)

    if not result:
        logger.info("No cached token found. Acquiring a new token from AAD.")
        result = app.acquire_token_for_client(scopes=scopes)

    if "access_token" in result:
        return result['access_token']
    else:
        logger.error(f"Failed to acquire token: {result.get('error_description')}")
        return None


def send_email_with_graph_api(subject, body, recipient_list):
    """
    Sends an email to a list of recipients using the Microsoft Graph API.

    Args:
        subject (str): The email subject.
        body (str): The HTML content of the email.
        recipient_list (list): A list of recipient email addresses.

    Returns:
        tuple: (bool, str) indicating success and the response text or error message.
    """
    access_token = get_graph_api_access_token()
    if not access_token:
        return False, "Failed to get API access token."

    # Use the sender email from your settings.py
    sender_email = settings.MS_GRAPH_SENDER_EMAIL
    url = f"https://graph.microsoft.com/v1.0/users/{sender_email}/sendMail"

    headers = {
        'Authorization': f'Bearer {access_token}',
        'Content-Type': 'application/json'
    }

    # Format the recipient list for the Graph API JSON payload
    to_recipients_json = [{"emailAddress": {"address": email}} for email in recipient_list]

    email_payload = {
        "message": {
            "subject": subject,
            "body": {
                "contentType": "HTML",
                "content": body
            },
            "toRecipients": to_recipients_json
        },
        "saveToSentItems": "true"
    }

    response = requests.post(url, headers=headers, json=email_payload)

    if response.status_code == 202:  # 202 Accepted is the success code for sendMail
        return True, "Email sent successfully via MS Graph."
    else:
        error_details = f"Status Code: {response.status_code} - Body: {response.text}"
        return False, error_details


# ==============================================================================
# UNCHANGED UTILITY FUNCTIONS
# ==============================================================================

def add_business_days(start_date, num_business_days):
    current_date = start_date
    days_added = 0
    while days_added < num_business_days:
        current_date += timedelta(days=1)
        if current_date.weekday() < 5:  # Check if it's a weekday (Monday-Friday)
            days_added += 1
    return current_date


def subtract_business_days(from_date, days):
    current_date = from_date
    while days > 0:
        current_date -= timedelta(days=1)
        if current_date.weekday() < 5:
            days -= 1
    return current_date


# ==============================================================================
# UPDATED MAIN EMAIL NOTIFICATION FUNCTION
# ==============================================================================

def send_booking_notification(event_trigger, booking_instance=None, context_data=None, test_email_recipient=None):
    """
    Finds ALL active email templates, builds recipient lists,
    sends emails via MS Graph API, and logs the attempt.
    """
    final_trigger = event_trigger

    # Dynamic Trigger Logic (remains the same)
    if event_trigger in ['booking_created', 'booking_reverted'] and booking_instance:
        vehicle_type = booking_instance.vehicle.vehicle_type.lower()
        final_trigger = f"{vehicle_type}_{event_trigger}"

    template_list = EmailTemplate.objects.filter(event_trigger=final_trigger, is_active=True)

    if not template_list.exists():
        logger.info(f"No active email templates found for event '{final_trigger}'. Skipping email.")
        return

    # Loop through each found template and send an email
    for template_obj in template_list:
        # Build the recipient list (remains the same)
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
            continue

        # Render the email content (remains the same)
        context = Context({'booking': booking_instance, **(context_data or {})})
        subject_template = Template(template_obj.subject)
        body_template = Template(template_obj.body)
        rendered_subject = subject_template.render(context)
        rendered_body = body_template.render(context)
        final_recipient_list = list(recipient_list)

        # --- MODIFIED: Send email using MS Graph API and log the result ---
        try:
            # Call the new function instead of Django's send_mail
            success, response_message = send_email_with_graph_api(
                subject=rendered_subject,
                body=rendered_body,
                recipient_list=final_recipient_list
            )

            if success:
                for recipient in final_recipient_list:
                    EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='sent')
                logger.info(
                    f"Successfully sent email using template '{template_obj.name}' to {', '.join(final_recipient_list)}")
            else:
                # Log the detailed error from the API
                for recipient in final_recipient_list:
                    EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='failed',
                                            error_message=response_message)
                logger.error(
                    f"FAILED to send email using template '{template_obj.name}'. API Error: {response_message}")

        except Exception as e:
            # Catch any other unexpected errors during the process
            error_message = f"An unexpected error occurred: {str(e)}"
            for recipient in final_recipient_list:
                EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='failed',
                                        error_message=error_message)
            logger.error(
                f"FAILED to send email using template '{template_obj.name}'. Unexpected Error: {error_message}")


# ==============================================================================
# UNCHANGED COMPANY CHECKER FUNCTION
# ==============================================================================

def check_company_by_crc(crc: str):
    url = f"https://www2.gov.pt/RegistoOnline/Services/CertidaoPermanente/consultaCertidao.aspx?id={crc}"
    print(f"\nChecking for company with CRC: {crc}...")
    try:
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            error_message = "O código de acesso introduzido não é válido"
            return error_message not in response.text
        else:
            print(f"Error: The server responded with status code {response.status_code}")
            return False
    except requests.exceptions.RequestException as e:
        print(f"An error occurred during the request: {e}")
        return False