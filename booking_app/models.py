#models.py
import uuid

from django.db import models
from django.conf import settings
from django.contrib.auth.models import AbstractUser, Group, BaseUserManager
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from datetime import date, timedelta
from django.templatetags.static import static


# --- Helper Functions for File Uploads ---

def get_insurance_upload_path(instance, filename):
    return f'vehicles/{instance.license_plate}/insurance/{filename}'


def get_registration_upload_path(instance, filename):
    return f'vehicles/{instance.license_plate}/registration/{filename}'


# --- Models ---

class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    phone_number = models.CharField(max_length=20, blank=True, default='')
    requires_password_change = models.BooleanField(default=False)
    language = models.CharField(max_length=10, choices=settings.LANGUAGES, default='en')

    @property
    def is_admin_member(self):
        return self.groups.filter(name='Admin').exists()

    @property
    def is_booking_admin_member(self):
        return self.is_admin_member or self.groups.filter(name='Booking Admin').exists()

    @property
    def is_group_leader(self):
        return self.is_booking_admin_member or self.groups.filter(
            name__in=['tlheavy', 'tllight', 'tlapv', 'sd']).exists()


# --- START: Inactive User Management ---

class InactiveUserManager(BaseUserManager):
    def get_queryset(self):
        return super().get_queryset().filter(is_active=False)


class InactiveUser(User):
    objects = InactiveUserManager()

    class Meta:
        proxy = True
        verbose_name = _('Inactive User')
        verbose_name_plural = _('Inactive Users')

# --- END: Inactive User Management ---


class Location(models.Model):
    name = models.CharField(max_length=255, unique=True)

    def __str__(self):
        return self.name


class Vehicle(models.Model):
    VEHICLE_TYPE_CHOICES = [
        ('HEAVY', _('Heavy')),
        ('LIGHT', _('Light')),
        ('APV', _('APV')),
    ]

    license_plate = models.CharField(max_length=15, unique=True)
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPE_CHOICES)
    is_available = models.BooleanField(default=True)
    model = models.CharField(_("Model Name"), max_length=100, blank=True, default="N/A")
    is_electric = models.BooleanField(default=False)
    viaverde_id = models.CharField(max_length=100, blank=True, null=True)
    vehicle_km = models.CharField(max_length=100, blank=True, null=True)
    chassis = models.CharField(_("Chassis Number"), max_length=100, unique=True, blank=True, null=True)
    picture = models.ImageField(_("Picture"), upload_to='vehicle_pics/', blank=True, null=True)
    insurance_document = models.FileField(_("Insurance"), upload_to=get_insurance_upload_path, blank=True, null=True)
    registration_document = models.FileField(_("Registration"), upload_to=get_registration_upload_path, blank=True, null=True)
    current_location = models.ForeignKey("Location", on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name='vehicles_at_location', verbose_name=_("Current Location"))
    next_maintenance_date = models.DateField(_("Next Maintenance Date"), null=True, blank=True)

    # --- NEW FIELDS ---
    start_date = models.DateField(_("Available From"), null=True, blank=True)
    end_date = models.DateField(_("Available Until"), null=True, blank=True)
    active_status = models.BooleanField(default=True)
    vehicle_value = models.DecimalField(_("Vehicle Value"), max_digits=12, decimal_places=2, null=True, blank=True)

    def get_availability_slots(self):
        from .utils import add_business_days, subtract_business_days

        today = date.today()
        tomorrow = today + timedelta(days=1)

        relevant_bookings = self.bookings.filter(
            status__in=['pending', 'pending_contract', 'confirmed', 'pending_final_km'],
            end_date__gte=today
        ).order_by('start_date')

        slots = []
        next_available_start = tomorrow

        if self.start_date and self.start_date > next_available_start:
            next_available_start = self.start_date

        if not relevant_bookings.exists():
            slots.append({'start': next_available_start, 'end': self.end_date})
            return slots

        first_booking = relevant_bookings.first()
        if first_booking.start_date <= today:
            next_available_start = add_business_days(first_booking.end_date, 3)

        for booking in relevant_bookings:
            gap_end = subtract_business_days(booking.start_date, 3)
            if next_available_start <= gap_end:
                slots.append({'start': next_available_start, 'end': gap_end})

            potential_next_start = add_business_days(booking.end_date, 3)
            if potential_next_start > next_available_start:
                next_available_start = potential_next_start

        slots.append({'start': next_available_start, 'end': self.end_date})
        return slots

    @property
    def get_picture_url(self):
        if self.picture and hasattr(self.picture, 'url'):
            return self.picture.url
        return static('media/Default/no_image.png')

    def get_active_status(self):
        return self.active_status

    def __str__(self):
        return f"{self.vehicle_type} - {self.model} ({self.license_plate})"


class Client(models.Model):
    tax_number = models.CharField(_("Tax Number"), max_length=50, db_index=True)
    name = models.CharField(_("Full Name"), max_length=255)
    address = models.TextField(_("Address"), blank=True, null=True)
    email = models.EmailField(_("Email Address"), blank=True, null=True)
    phone_number = models.CharField(_("Phone Number"), max_length=50, blank=True, null=True)
    permanent_registration_number = models.CharField(_("Permanent Registration Number"), max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = _("Client")
        verbose_name_plural = _("Clients")

    def __str__(self):
        return f"{self.name} ({self.tax_number})"


class Booking(models.Model):
    BOOKING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('pending_contract', _('Pending Contract')),
        ('confirmed', _('Confirmed')),
        ('pending_final_km', _('Pending Final KM')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    )

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    vehicle = models.ForeignKey('Vehicle', on_delete=models.CASCADE, related_name='bookings')
    client = models.ForeignKey('Client', on_delete=models.PROTECT, related_name='bookings',
                               verbose_name=_("Client"), null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField()
    start_location = models.ForeignKey('Location', on_delete=models.CASCADE, related_name='start_bookings')
    end_location = models.ForeignKey('Location', on_delete=models.CASCADE, related_name='end_bookings')
    booking_time = models.DateTimeField(auto_now_add=True)

    status = models.CharField(max_length=20, choices=BOOKING_STATUS_CHOICES,
                              default='pending', verbose_name=_("Booking Status"))
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name='cancelled_bookings', verbose_name=_("Cancelled By"))
    cancellation_reason = models.TextField(blank=True, null=True, verbose_name=_("Cancellation Reason"))
    cancellation_time = models.DateTimeField(null=True, blank=True, verbose_name=_("Cancellation Time"))

    initial_km = models.PositiveIntegerField(_("Initial Kilometers"), null=True, blank=True)
    final_km = models.PositiveIntegerField(_("Final Kilometers"), null=True, blank=True)
    motive = models.TextField(_("Motive"), blank=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    needs_transport = models.BooleanField(_("Transport Required Before Booking"), default=False)

    # --- NEW FIELD for external workflow ---
    external_contract_number = models.CharField(
        _("External Contract Number"),
        max_length=100,
        blank=True,
        null=True,
        help_text=_("Contract number received from the external service.")
    )

    def get_absolute_url(self):
        return reverse('booking_app:booking_detail', kwargs={'booking_pk': self.pk})

    @property
    def current_status_display(self):
        today = timezone.now().date()
        if self.status == 'confirmed' and self.start_date <= today <= self.end_date:
            return _('On Going')
        return self.get_status_display()

    def __str__(self):
        client_name = self.client.name if self.client else _("N/A")
        return f"Booking {self.pk} for {client_name} ({self.vehicle.license_plate})"

    class Meta:
        ordering = ['-booking_time']
        verbose_name = _("Booking")
        verbose_name_plural = _("Bookings")


class EmailTemplate(models.Model):
    EVENT_CHOICES = [
        ('Booking Events', (
            ('light_booking_created', _('New LIGHT Vehicle Booking Created')),
            ('heavy_booking_created', _('New HEAVY Vehicle Booking Created')),
            ('apv_booking_created', _('New APV Vehicle Booking Created')),
            ('light_booking_reverted', _('LIGHT Booking Reverted to Pending')),
            ('heavy_booking_reverted', _('HEAVY Booking Reverted to Pending')),
            ('apv_booking_reverted', _('APV Booking Reverted to Pending')),
            ('booking_canceled_by_manager', _('Booking Canceled by Manager')),
            ('booking_canceled_by_user', _('Booking Canceled by User')),
            ('booking_completed', _('Booking Completed')),
            ('booking_pending_reminder', _('Booking Pending Reminder')),
            ('transport_required', _('Booking Transport is required')),
            ('transport_status_changed', _('Booking Transport Status Changed')),
            ('booking_ended_pending_km', _('Booking Ended Pending KM')),
        )),
        ('Manager Actions', (
            ('booking_approved', _('Booking Approved')),
            ('apv_booking_approved', _('APV Booking Approved')),
        )),
        ('Admin Actions', (
            ('user_sessions_terminated', _('User Sessions Terminated')),
            ('all_sessions_terminated', _('All Sessions Terminated')),
            ('user_session_terminated', _('User Current Session Terminated')),
            ('password_reset', _('User Password Was Reset')),
            ('send_user_credentials', _('Send User Credentials')),
            ('send_temporary_password', _('Send Temporary Password')),
        )),
        ('Automated Notifications', (
            ('booking_reminder_7_days', _('Booking Reminder (7 Days Away)')),
            ('booking_auto_cancelled', _('Booking Auto-Cancelled (Unapproved)')),
            ('automation_settings_updated', _('Automation Settings Updated')),
        )),
        ('Account Events', (
            ('user_created', _('New User Account Created')),
            ('user_updated', _('User Updated')),
            ('group_created', _('Group Created')),
            ('group_updated', _('Group Updated')),
            ('group_deleted', _('Group Deleted')),
            ('user_deactivated', _('User Deactivated')),
            ('user_reactivated', _('User Reactivated')),
        )),
        ('Vehicle Events', (
            ('vehicle_created', _('Vehicle Created')),
            ('vehicle_updated', _('Vehicle Updated')),
            ('vehicle_inactive', _('Vehicle Deactivated')),
            ('vehicles_deactivated_auto', _('Vehicles Deactivated Automatically')),
        )),
        ('Location Events', (
            ('location_created', _('Location Created')),
            ('location_updated', _('Location Updated')),
            ('location_deleted', _('Location Deleted')),
        )),
        ('Client Events', (
            ('client_created', _('Client Created')),
            ('client_updated', _('Client Updated')),
            ('client_deleted', _('Client Deleted')),
        )),
        ('Distribution List Events', (
            ('distribution_list_created', _('Distribution List Created')),
            ('distribution_list_updated', _('Distribution List Updated')),
            ('distribution_list_deleted', _('Distribution List Deleted')),
        )),
    ]

    name = models.CharField(max_length=100, unique=True)
    event_trigger = models.CharField(max_length=50, choices=EVENT_CHOICES)
    subject = models.CharField(max_length=255)
    body = models.TextField()
    is_active = models.BooleanField(default=True)
    send_to_salesperson = models.BooleanField(default=False)
    send_to_groups = models.ManyToManyField(Group, blank=True)
    send_to_users = models.ManyToManyField(User, blank=True)
    send_to_distribution_lists = models.ManyToManyField('DistributionList', blank=True)

    def __str__(self):
        return self.name


class DistributionList(models.Model):
    name = models.CharField(max_length=100, unique=True)
    emails = models.TextField(help_text="Comma-separated email addresses.")

    def get_emails_as_list(self):
        return [email.strip() for email in self.emails.split(',') if email.strip()]

    def __str__(self):
        return self.name


class EmailLog(models.Model):
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10)  # e.g., 'sent', 'failed'
    error_message = models.TextField(blank=True, null=True)

    def __str__(self):
        return f"To: {self.recipient} - {self.subject} ({self.status})"


class AutomationSettings(models.Model):
    pending_booking_automation_active = models.BooleanField(default=True)
    enable_pending_reminders = models.BooleanField(default=True)
    reminder_days_pending = models.PositiveIntegerField(default=3)
    require_crc_verification = models.BooleanField(default=False)
    contract_start_number = models.PositiveIntegerField(default=0)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]


class Transport(models.Model):
    booking = models.OneToOneField("Booking", on_delete=models.CASCADE, related_name="transport", verbose_name=_("Booking"))
    origin_location = models.ForeignKey("Location", on_delete=models.CASCADE, related_name="transports_from", verbose_name=_("Origin"))
    destination_location = models.ForeignKey("Location", on_delete=models.CASCADE, related_name="transports_to", verbose_name=_("Destination"))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Transport for booking {self.booking_id}: {self.origin_location} → {self.destination_location}"
