# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\utils.py

import logging
from datetime import timedelta

import msal
import json
import requests
from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.template import Template, Context
from django.utils import timezone

from .models import EmailTemplate, EmailLog

logger = logging.getLogger('booking_app')


# ==============================================================================
# NEW MICROSOFT GRAPH API FUNCTIONS
# ==============================================================================

def get_graph_api_access_token():
    """
    Acquires an access token from Microsoft Identity Platform.
    """
    # --- FINAL DEBUGGING STEP: Inspect credentials before use ---
    client_id = settings.MS_GRAPH_CLIENT_ID
    client_secret = settings.MS_GRAPH_CLIENT_SECRET
    tenant_id = settings.MS_GRAPH_TENANT_ID

    authority = f"https://login.microsoftonline.com/{tenant_id}"
    app = msal.ConfidentialClientApplication(
        client_id=client_id,
        authority=authority,
        client_credential=client_secret,
    )

    scopes = ["https://graph.microsoft.com/.default"]
    result = app.acquire_token_silent(scopes=scopes, account=None)

    if not result:
        logger.info("No cached token found. Acquiring a new token from AAD.")
        result = app.acquire_token_for_client(scopes=scopes)

    if "access_token" in result:
        return result['access_token']
    else:
        # Also print the error from MSAL if it fails
        error_description = result.get("error_description", "No error description from MSAL.")
        logger.error(f"Failed to acquire token: {error_description}")
        #print(f"--- MSAL ERROR: {error_description} ---")
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

# booking_app/utils.py

def send_booking_notification(event_trigger, booking_instance=None, context_data=None, test_email_recipient=None):
    """
    Finds ALL active email templates, builds recipient lists,
    sends emails via MS Graph API, and logs the attempt.
    """
    final_trigger = event_trigger

    if event_trigger in ['booking_created', 'booking_reverted'] and booking_instance:
        vehicle_type = booking_instance.vehicle.vehicle_type.lower()
        final_trigger = f"{vehicle_type}_{event_trigger}"

    template_list = EmailTemplate.objects.filter(event_trigger=final_trigger, is_active=True)

    if not template_list.exists():
        logger.info(f"No active email templates found for event '{final_trigger}'. Skipping email.")
        return

    for template_obj in template_list:
        print(f"--- DEBUG: Preparing to send template '{template_obj.name}' for event '{final_trigger}' ---")
        recipient_list = set()
        if test_email_recipient:
            recipient_list.add(test_email_recipient)
        else:
            if template_obj.send_to_salesperson and booking_instance and booking_instance.user and hasattr(
                    booking_instance.user, 'email'):
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

        final_recipient_list = list(recipient_list)
        print(f"--- DEBUG: Final recipient list: {final_recipient_list} ---")

        context_dict = {'booking': booking_instance}
        if context_data:
            context_dict.update(context_data)

        # --- DEBUG: We will now try to render the templates one by one ---
        try:
            print("--- DEBUG: Attempting to render SUBJECT template... ---")
            context = Context(context_dict)
            subject_template = Template(template_obj.subject)
            rendered_subject = subject_template.render(context)
            print("--- DEBUG: SUBJECT rendered successfully. ---")

            print("--- DEBUG: Attempting to render BODY template... ---")
            body_template = Template(template_obj.body)
            rendered_body = body_template.render(context)
            print("--- DEBUG: BODY rendered successfully. ---")

        except Exception as e:
            # This will catch the error during rendering and tell us exactly where it failed.
            print(f"!!!!!!!!!! FATAL ERROR DURING TEMPLATE RENDERING !!!!!!!!!!!")
            print(f"Error of type {type(e).__name__}: {e}")
            logger.error(f"CRITICAL: Failed to render template '{template_obj.name}'. Error: {e}")
            print(f"!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
            # Stop execution for this email if rendering fails
            continue

        # --- Send email using the MS Graph API ---
        try:
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
                for recipient in final_recipient_list:
                    EmailLog.objects.create(recipient=recipient, subject=rendered_subject, status='failed',
                                            error_message=response_message)
                logger.error(
                    f"FAILED to send email using template '{template_obj.name}'. API Error: {response_message}")

        except Exception as e:
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

# ==============================================================================
# LICENSING CLIENT FUNCTIONS
# ==============================================================================

# The key we'll use to store the license status in Django's cache
LICENSE_CACHE_KEY = "license_status_cache"


def verify_license_with_server():
    """
    Makes an API call to the central license server to verify the key.
    """
    try:
        response = requests.post(
            f"{settings.LICENSE_SERVER_URL}/api/verify-license",
            json={
                "license_key": settings.LICENSE_KEY,
                "instance_id": settings.INSTANCE_ID,
            },
            timeout=10,  # Set a timeout to prevent long waits
        )
        response.raise_for_status()  # Raise an exception for bad status codes (4xx or 5xx)
        return response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"Could not connect to license server: {e}")
        # Return a default "invalid" state if the server is unreachable
        return {"valid": False, "reason": "server_unreachable"}


def get_license_status():
    """
    Gets the license status, using a cache to avoid frequent API calls.
    This provides a "grace period" if the license server is temporarily down.
    """
    # 1. Try to get the status from the cache first
    cached_status = cache.get(LICENSE_CACHE_KEY)
    if cached_status:
        return cached_status

    # 2. If not in cache, call the license server
    status = verify_license_with_server()

    # 3. Store the result in the cache for 1 hour (3600 seconds)
    cache.set(LICENSE_CACHE_KEY, status, 3600)

    return status


def is_license_valid():
    """Return True if DEBUG is on, otherwise check real license status."""
    if getattr(settings, "DEBUG", False):
        return True
    status = get_license_status()
    return status.get("valid", False)

def get_license_tier():
    """A helper to get the license tier (e.g., 'basic', 'pro')."""
    status = get_license_status()
    if status.get("valid"):
        return status.get("tier", "basic")
    return None

# ==============================================================================
# KILL CLIENT SESSIONS FUNCTIONS
# ==============================================================================

def get_user_sessions(user):
    """
    Return list of session info dicts for given user.
    Each dict: {session_key, expire_date, session_data, created_at, last_activity, ip, user_agent}
    Note: created_at/last_activity/ip/user_agent are present only if you populate them in middleware.
    """
    sessions = []
    qs = Session.objects.filter(expire_date__gt=timezone.now())
    for s in qs:
        data = s.get_decoded()
        if str(user.pk) == str(data.get('_auth_user_id')):
            info = {
                "session_key": s.session_key,
                "expire_date": s.expire_date,
                "session_data": data,
                # optional keys populated by middleware:
                "created_at": data.get('session_created_at'),
                "last_activity": data.get('last_activity'),
                "ip": data.get('session_ip'),
                "user_agent": data.get('session_user_agent'),
            }
            sessions.append(info)
    return sessions

def is_user_logged_in(user):
    """Return True if there is any non-expired session tied to user."""
    return len(get_user_sessions(user)) > 0

def kill_session_by_key(session_key):
    Session.objects.filter(session_key=session_key).delete()

def kill_user_sessions(user):
    """Delete all sessions for a specific user."""
    for s in Session.objects.all():
        data = s.get_decoded()
        if data.get('_auth_user_id') == str(user.pk):
            s.delete()

def kill_all_sessions():
    Session.objects.all().delete()

def get_last_activity_for_user(user):
    """Return last_activity ISO string (or None) among all sessions of a user."""
    from django.contrib.sessions.models import Session
    sessions = Session.objects.filter(expire_date__gt=timezone.now())
    last_seen = None
    for s in sessions:
        data = s.get_decoded()
        if str(user.pk) == str(data.get('_auth_user_id')):
            la = data.get("last_activity")
            if la:
                try:
                    ts = timezone.datetime.fromisoformat(la)
                    if not last_seen or ts > last_seen:
                        last_seen = ts
                except Exception:
                    continue
    return last_seen