# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\models.py
import uuid

from django.db import models, transaction
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


def get_contract_upload_path(instance, filename):
    return f'bookings/{instance.pk}/contract/{filename}'


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


# --- START: Added for Inactive User Management ---

class InactiveUserManager(BaseUserManager):
    """
    Custom manager for the InactiveUser proxy model.
    It returns only users who have their `is_active` flag set to False.
    """
    def get_queryset(self):
        return super().get_queryset().filter(is_active=False)


class InactiveUser(User):
    """
    Proxy model to manage inactive users in the Django admin.
    This model doesn't create a new database table but provides a separate
    interface in the admin for users with `is_active=False`.
    """
    objects = InactiveUserManager()

    class Meta:
        proxy = True
        verbose_name = _('Inactive User')
        verbose_name_plural = _('Inactive Users')

# --- END: Added for Inactive User Management ---


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

    license_plate = models.CharField(
        max_length=15, unique=True,
        help_text=_("License Plate of the vehicle.")
    )
    vehicle_type = models.CharField(
        max_length=50, choices=VEHICLE_TYPE_CHOICES,
        help_text=_("Vehicle Type (LIGHT, HEAVY, APV).")
    )
    is_available = models.BooleanField(
        default=True, help_text=_("Is Vehicle Available.")
    )
    model = models.CharField(
        _("Model Name"), max_length=100, blank=True, default="N/A",
        help_text=_("The Model of the vehicle.")
    )
    is_electric = models.BooleanField(
        default=False, help_text=_("Is Vehicle Electric.")
    )
    viaverde_id = models.CharField(
        max_length=100, blank=True, null=True,
        help_text=_("ID of the ViaVerde Identifier.")
    )
    vehicle_km = models.CharField(
        max_length=100, blank=True, null=True,
        help_text=_("The KM of the vehicle.")
    )
    chassis = models.CharField(
        _("Chassis Number"), max_length=100, unique=True,
        blank=True, null=True,
        help_text=_("The unique chassis number of the vehicle.")
    )
    picture = models.ImageField(
        _("Picture"), upload_to='vehicle_pics/', blank=True, null=True,
        help_text=_("Upload a picture of the vehicle.")
    )
    insurance_document = models.FileField(
        _("Insurance"), upload_to=get_insurance_upload_path,
        blank=True, null=True,
        help_text=_("Upload the vehicle's insurance document (PDF, DOCX, etc.).")
    )
    registration_document = models.FileField(
        _("Registration"), upload_to=get_registration_upload_path,
        blank=True, null=True,
        help_text=_("Upload the vehicle's registration document (PDF, DOCX, etc.).")
    )
    current_location = models.ForeignKey(
        "Location", on_delete=models.SET_NULL, null=True, blank=True,
        related_name='vehicles_at_location', verbose_name=_("Current Location"),
        help_text=_("The current physical location of the vehicle.")
    )
    next_maintenance_date = models.DateField(
        _("Next Maintenance Date"), null=True, blank=True,
        help_text=_("Required only for APV vehicles.")
    )

    # --- NEW FIELDS ---
    start_date = models.DateField(
        _("Available From"), null=True, blank=True,
        help_text=_("Date from which the vehicle can be booked.")
    )
    end_date = models.DateField(
        _("Available Until"), null=True, blank=True,
        help_text=_("Last date the vehicle can be booked.")
    )
    active_status = models.BooleanField(
        default=True, help_text=_("Is vehicle active?")
    )
    vehicle_value = models.DecimalField(
        _("Vehicle Value"), max_digits=12, decimal_places=2,
        null=True, blank=True,
        help_text=_("Estimated value of the vehicle (for reference/insurance).")
    )

    # --- EXISTING METHODS ---
    def get_availability_slots(self):
        from .utils import add_business_days, subtract_business_days

        today = date.today()
        tomorrow = today + timedelta(days=1)

        # Filter bookings
        relevant_bookings = self.bookings.filter(
            status__in=['pending', 'confirmed', 'pending_final_km'],
            end_date__gte=today
        ).order_by('start_date')

        slots = []
        next_available_start = tomorrow

        # Respect start_date restriction if defined
        if self.start_date and self.start_date > next_available_start:
            next_available_start = self.start_date

        if not relevant_bookings.exists():
            # If no bookings, but enforce end_date limit
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
    client = models.ForeignKey(
        'Client',
        on_delete=models.PROTECT,
        related_name='bookings',
        verbose_name=_("Client"),
        null=True,
        blank=True
    )
    start_date = models.DateField()
    end_date = models.DateField()
    start_location = models.ForeignKey('Location', on_delete=models.CASCADE, related_name='start_bookings')
    end_location = models.ForeignKey('Location', on_delete=models.CASCADE, related_name='end_bookings')
    booking_time = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=20,
        choices=BOOKING_STATUS_CHOICES,
        default='pending',
        verbose_name=_("Booking Status")
    )
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='cancelled_bookings',
        verbose_name=_("Cancelled By")
    )
    cancellation_reason = models.TextField(blank=True, null=True, verbose_name=_("Cancellation Reason"))
    cancellation_time = models.DateTimeField(null=True, blank=True, verbose_name=_("Cancellation Time"))

    # Removed old contract_document FileField
    initial_km = models.PositiveIntegerField(
        _("Initial Kilometers"),
        null=True,
        blank=True,
        help_text=_("The vehicle's kilometers at the start of the booking.")
    )
    final_km = models.PositiveIntegerField(
        _("Final Kilometers"),
        null=True,
        blank=True,
        help_text=_("The vehicle's kilometers at the end of the booking.")
    )
    motive = models.TextField(
        _("Motive"),
        blank=True,
        help_text=_("Required only for APV vehicle bookings.")
    )
    created_at = models.DateTimeField(
        _("Created At"),
        auto_now_add=True,
        help_text=_("The date and time the booking was created.")
    )
    needs_transport = models.BooleanField(
        _("Transport Required Before Booking"),
        default=False,
        help_text=_("Indicates if the vehicle needs to be moved from a different location before this booking can start.")
    )

    def get_absolute_url(self):
        return reverse('booking_app:booking_detail', kwargs={'booking_pk': self.pk})

    @property
    def current_status_display(self):
        today = timezone.now().date()
        if self.status == 'confirmed' and self.start_date <= today <= self.end_date:
            return _('On Going')
        return self.get_status_display()

    @property
    def latest_contract(self):
        return self.contracts.first()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)

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
            ('contract_generated', _('New Contract Generated')),
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
            ('automation_settings_updated', _('BAutomation Settings Updated')),
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

    def get_emails_as_list(self): return [email.strip() for email in self.emails.split(',') if email.strip()]

    def __str__(self): return self.name

class ContractTemplateSettings(models.Model):
    template = models.FileField(upload_to="contract_templates/", blank=True, null=True)
    placeholder_map = models.JSONField(default=list, blank=True)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

    def get_template_path(self):
        from django.conf import settings
        import os

        if self.template:
            return self.template.path
        return os.path.join(settings.BASE_DIR, "document_templates", "contract_template.docx")

class EmailLog(models.Model):
    recipient = models.EmailField()
    subject = models.CharField(max_length=255)
    sent_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=10)  # e.g., 'sent', 'failed'
    error_message = models.TextField(blank=True, null=True)

    def __str__(self): return f"To: {self.recipient} - {self.subject} ({self.status})"


class AutomationSettings(models.Model):
    pending_booking_automation_active = models.BooleanField(default=True)
    enable_pending_reminders = models.BooleanField(default=True)
    reminder_days_pending = models.PositiveIntegerField(default=3)
    require_crc_verification = models.BooleanField(default=False)
    contract_start_number = models.PositiveIntegerField(default=0)

    @classmethod
    def load(cls):
        return cls.objects.get_or_create(pk=1)[0]

class Contract(models.Model):
    booking = models.ForeignKey("Booking", on_delete=models.CASCADE, related_name="contracts")
    contract_number = models.PositiveIntegerField(unique=True, editable=False)
    file = models.FileField(upload_to="contracts/", blank=True, null=True)  # store generated PDF
    created_at = models.DateTimeField(auto_now_add=True)

    # Optional metadata
    version = models.PositiveIntegerField(default=1)  # amendments, renewals
    signed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args, **kwargs):
        if not self.contract_number:
            # Make number assignment concurrency-safe
            with transaction.atomic():
                last_number = (
                    Contract.objects.select_for_update()
                    .aggregate(models.Max("contract_number"))["contract_number__max"]
                    or 0
                )
                self.contract_number = last_number + 1
        super().save(*args, **kwargs)

    @property
    def formatted_number(self):
        """Show with prefix, e.g. CA0107"""
        return f"CA{self.contract_number:04d}"

    def __str__(self):
        return f"Contract {self.formatted_number} for Booking {self.booking.pk}"