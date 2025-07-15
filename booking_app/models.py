# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\models.py

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager, Group
from django.conf import settings
import uuid
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.validators import UnicodeUsernameValidator
import os
from django.core.exceptions import ValidationError

from django.templatetags.static import static


# --- Custom User Manager ---
class CustomUserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError(_("The Username field must be set"))
        if not email:
            raise ValueError(_("The Email field must be set"))
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        extra_fields.setdefault('requires_password_change', False)

        if extra_fields.get('is_staff') is not True:
            raise ValueError(_("Superuser must have is_staff=True."))
        if extra_fields.get('is_superuser') is not True:
            raise ValueError(_("Superuser must have is_superuser=True."))

        return self.create_user(username, email, password, **extra_fields)


# --- Custom User Model ---
class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    username_validator = UnicodeUsernameValidator()
    username = models.CharField(
        _("username"),
        max_length=150,
        unique=True,
        validators=[username_validator],
        error_messages={
            "unique": _("A user with that username already exists."),
        },
    )

    email = models.EmailField(_("email address"), unique=True)
    first_name = models.CharField(_("first name"), max_length=30, blank=True)
    last_name = models.CharField(_("last name"), max_length=150, blank=True)
    phone_number = models.CharField(_("phone number"), max_length=20, blank=True, null=True)
    date_joined = models.DateTimeField(_("date joined"), default=timezone.now)
    is_active = models.BooleanField(_("active"), default=True)
    is_staff = models.BooleanField(_("staff status"), default=False)
    is_superuser = models.BooleanField(_("superuser status"), default=False)
    requires_password_change = models.BooleanField(default=False)

    @property
    def is_admin_member(self):
        """
        Checks if the user belongs to the 'Admin' group.
        Ensure you have a Django Group named 'Admin' created for this to work.
        """
        return self.groups.filter(name='Admin').exists()

    def __str__(self):
        return self.username

    objects = CustomUserManager()

    USERNAME_FIELD = 'username'
    REQUIRED_FIELDS = ['email', 'first_name', 'last_name']

    class Meta:
        verbose_name = _("user")
        verbose_name_plural = _("users")

    def get_full_name(self):
        full_name = "%s %s" % (self.first_name, self.last_name)
        return full_name.strip()

    def get_short_name(self):
        return self.first_name


# --- Location Model ---
class Location(models.Model):
    name = models.CharField(max_length=255)

    class Meta:
        verbose_name = _("Location")
        verbose_name_plural = _("Locations")

    def __str__(self):
        return self.name


# --- Vehicle Model (UPDATED) ---
class Vehicle(models.Model):
    VEHICLE_TYPES = [
        ('HEAVY', 'HEAVY'),
        ('LIGHT', 'LIGHT'),
        ('APV', 'APV'),
    ]
    license_plate = models.CharField(max_length=15, unique=True)
    vehicle_type = models.CharField(max_length=50, choices=VEHICLE_TYPES)
    is_available = models.BooleanField(default=True)
    model = models.CharField(_("Model Name"), max_length=100, blank=True, default="N/A")
    picture = models.ImageField(
        _("Picture"),
        upload_to='vehicle_pics/',
        blank=True,
        null=True,
        help_text=_("Upload a picture of the vehicle.")
    )
    current_location = models.ForeignKey(
        'Location',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='vehicles_at_location',
        verbose_name=_("Current Location"),
        help_text=_("The current physical location of the vehicle.")
    )

    def save(self, *args, **kwargs):
        """
        Override the save method to set a default picture based on vehicle type
        if no picture is uploaded.
        """
        # The `if not self.picture` check ensures we only set the default
        # if a user has not uploaded their own image.
        if not self.picture:
            if self.vehicle_type == 'LIGHT':
                self.picture = 'Default/light.jpg'
            elif self.vehicle_type == 'HEAVY':
                self.picture = 'Default/heavy.jpg'
            # You can add a default for 'APV' or a general fallback here
            else:
                 self.picture = 'Default/no_image.jpg'

        super().save(*args, **kwargs)  # Call the original save method

    @property
    def get_picture_url(self):
        # --- UPDATED: Simplified and more robust check ---
        # A file field with no file will evaluate to False.
        if self.picture:
            return self.picture.url
        elif self.vehicle_type == 'LIGHT':
            return static('Default/light.jpg')
        elif self.vehicle_type == 'HEAVY':
            return static('Default/light.jpg')

        return static('Default/light.jpg')  # Generic Default

    def __str__(self):
        return f"{self.vehicle_type} - {self.model} ({self.license_plate})"


# --- Booking Model ---
class Booking(models.Model):
    BOOKING_STATUS_CHOICES = (
        ('pending', _('Pending')),
        ('confirmed', _('Confirmed')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    )
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='bookings')
    vehicle = models.ForeignKey('Vehicle', on_delete=models.CASCADE, related_name='bookings')

    customer_name = models.CharField(max_length=255)
    customer_email = models.EmailField(blank=True, null=True)
    customer_phone = models.CharField(max_length=20, blank=True, null=True)
    client_tax_number = models.CharField(max_length=50, blank=False, verbose_name=_("Client Tax Number"))
    client_company_registration = models.CharField(max_length=100, blank=False,
                                                   verbose_name=_("Permanent registration certificate code"))

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

    @property
    def current_status_display(self):
        """
        Returns the dynamic status of the booking, showing 'On Going'
        for confirmed bookings that are currently active.
        """
        today = timezone.now().date()
        if self.status == 'confirmed' and self.start_date <= today <= self.end_date:
            return _('On Going')
        return self.get_status_display()

    class Meta:
        ordering = ['-booking_time']
        verbose_name = _("Booking")
        verbose_name_plural = _("Bookings")

    def __str__(self):
        return f"Booking {self.pk} by {self.user.username} for {self.vehicle.license_plate}"

    def is_active(self):
        return self.status in ['pending', 'confirmed']

    def clean(self):
        """
        Add custom model-level validation.
        """
        super().clean()
        if not self.customer_email and not self.customer_phone:
            raise ValidationError(
                _("A booking must have either a customer email or a customer phone number.")
            )


# --- NEW: Distribution List Model ---
class DistributionList(models.Model):
    name = models.CharField(max_length=100, unique=True, verbose_name=_("List Name"))
    emails = models.TextField(
        verbose_name=_("Email Addresses"),
        help_text=_("Enter one or more email addresses, separated by commas or new lines.")
    )

    def __str__(self):
        return self.name

    def get_emails_as_list(self):
        """
        Cleans and returns the email addresses as a Python list.
        """
        # Replace newlines and semicolons with commas, then split by comma
        emails_str = self.emails.replace('\n', ',').replace(';', ',')
        # Split by comma and strip whitespace from each email
        return [email.strip() for email in emails_str.split(',') if email.strip()]

    class Meta:
        verbose_name = _("Distribution List")
        verbose_name_plural = _("Distribution Lists")
        ordering = ['name']


class EmailTemplate(models.Model):
    """
    Stores email templates that can be edited in the Django admin.
    """
    EVENT_CHOICES = [
        ('Booking Events', (
            ('booking_created', _('Booking Created by Salesperson')),
            ('booking_updated', _('Booking Updated by Salesperson')),
            ('booking_completed', _('Booking Completed')),
            ('booking_reminder', _('Booking Reminder (Upcoming)')),
        )),
        ('Manager Actions', (
            ('booking_approved', _('Booking Approved by Manager')),
            ('booking_canceled_by_manager', _('Booking Canceled by Manager')),
        )),
        ('User Actions', (
            ('booking_canceled_by_user', _('Booking Canceled by User')),
        )),
        ('Automated Notifications', (
            ('booking_reminder_7_days', _('Booking Reminder (7 Days Away)')),
            ('booking_auto_cancelled', _('Booking Auto-Cancelled (Unapproved)')),
        )),
        ('Account Management', (
            ('user_created', _('New User Account Created')),
            ('password_reset', _('User Password Was Reset')),
        )),
        ('Vehicle Management', (
            ('vehicle_created', _('Vehicle Created')),
            ('vehicle_updated', _('Vehicle Updated')),
            ('vehicle_deleted', _('Vehicle Deleted')),
        )),
        ('Location Management', (
            ('location_created', _('Location Created')),
            ('location_updated', _('Location Updated')),
            ('location_deleted', _('Location Deleted')),
        )),
    ]

    event_trigger = models.CharField(
        max_length=50,
        unique=True,
        choices=EVENT_CHOICES,
        default='booking_created',
        help_text=_("Select the specific event that will trigger this email notification.")
    )

    name = models.CharField(max_length=100,
                            help_text=_("A descriptive name for this template (e.g., 'New Booking Confirmation')."))
    subject = models.CharField(max_length=255, help_text=_(
        "The email subject line. You can use template variables like {{ booking.pk }}."))
    body = models.TextField(
        help_text=_("The email body. Can contain HTML and template variables like {{ booking.customer_name }}."))
    is_active = models.BooleanField(default=True, help_text=_("Only active templates will be sent."))

    send_to_salesperson = models.BooleanField(default=True, verbose_name=_("Send to Salesperson"), help_text=_(
        "Check to send a notification to the salesperson who created the booking."))
    send_to_groups = models.ManyToManyField(
        Group,
        blank=True,
        verbose_name=_("Send to Groups"),
        help_text=_("Select groups whose members should receive this notification.")
    )
    send_to_users = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        blank=True,
        verbose_name=_("Send to Specific Users"),
        help_text=_("Select specific users who should receive this notification.")
    )
    send_to_distribution_lists = models.ManyToManyField(
        DistributionList,
        blank=True,
        verbose_name=_("Send to Distribution Lists"),
        help_text=_("Select distribution lists that should receive this notification.")
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name']
        verbose_name = _("Email Template")
        verbose_name_plural = _("Email Templates")

class AutomationSettings(models.Model):
    """A singleton model to hold site-wide automation settings."""
    pending_booking_automation_active = models.BooleanField(
        default=False,
        verbose_name=_("Activate Pending Booking Automation"),
        help_text=_("If checked, the system will automatically send reminders and cancel unapproved bookings.")
    )

    def save(self, *args, **kwargs):
        """Ensure there is only one instance of this model."""
        self.pk = 1
        super(AutomationSettings, self).save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        """Prevent deletion of the singleton instance."""
        pass

    @classmethod
    def load(cls):
        """Load the singleton instance, creating it if it doesn't exist."""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj

    def __str__(self):
        return _("Automation Settings")

    class Meta:
        verbose_name_plural = _("Automation Settings")