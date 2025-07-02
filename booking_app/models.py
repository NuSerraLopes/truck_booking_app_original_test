# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\models.py

from django.db import models
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin, BaseUserManager
from django.conf import settings
import uuid
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from django.contrib.auth.validators import UnicodeUsernameValidator
import os

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
        help_text=_(
            "Required. 150 characters or fewer. Letters, digits and @/./+/-/_ only."
        ),
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
    is_superuser = models.BooleanField(_("superuser status"), default=False) # Explicitly define for clarity
    requires_password_change = models.BooleanField(default=False)

    @property
    def is_admin_member(self):
        """
        Checks if the user belongs to the 'admin' group.
        Ensure you have a Django Group named 'admin' created for this to work.
        """
        return self.groups.filter(name='admin').exists()

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

    @property
    def get_picture_url(self):
        if self.picture and hasattr(self.picture, 'url'):
            return self.picture.url
        elif self.vehicle_type == 'LIGHT':
            return static('default_pics/light.jpg')
        elif self.vehicle_type == 'HEAVY':
            return static('default_pics/heavy.jpg')
        return static('static/images/no_image.png') # Generic Default

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
    customer_email = models.EmailField()
    customer_phone = models.CharField(max_length=20, blank=True, null=True)

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

    class Meta:
        ordering = ['-booking_time']
        verbose_name = _("Booking")
        verbose_name_plural = _("Bookings")

    def __str__(self):
        return f"Booking {self.pk} by {self.user.username} for {self.vehicle.license_plate}"

    def is_active(self):
        return self.status in ['pending', 'confirmed']