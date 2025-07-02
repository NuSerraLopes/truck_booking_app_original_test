# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\admin.py

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.utils.translation import gettext_lazy as _
from django import forms
from django.contrib import messages  # Import Django's messages framework

import secrets  # For secure random string generation
import string  # For character sets for passwords
import uuid  # For generating unique default emails

# Import your models from the current app
from .models import Vehicle, Booking, Location, User

# Register your other models here (if they are not already registered elsewhere)
admin.site.register(Location)
admin.site.register(Vehicle)
admin.site.register(Booking)

# Form for creating a new user in the admin
class MyUserCreationForm(UserCreationForm):
    class Meta:
        model = User
        fields = ('username', 'email', 'first_name', 'last_name', 'phone_number', 'is_active', 'is_staff',
                  'is_superuser')

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # REMOVE these two lines to make password fields REQUIRED again:
        # if 'password' in self.fields:
        #     self.fields['password'].required = False
        # if 'password2' in self.fields:
        #     self.fields['password2'].required = False

        # Keep email field optional if you still want auto-generation for email if left blank
        if 'email' in self.fields:
            self.fields['email'].required = False

    def clean_email(self):
        email = self.cleaned_data.get('email')

        if not email:  # If the email field was left blank in the admin form
            # Generate a unique default email for development purposes
            default_email = f"temp_user_{uuid.uuid4().hex[:8]}@example.com"

            # Very unlikely, but ensure the generated email is truly unique
            while User.objects.filter(email=default_email).exists():
                default_email = f"temp_user_{uuid.uuid4().hex[:8]}@example.com"

            email = default_email

        # Ensure the (potentially generated or manually entered) email is unique among existing users
        # This check prevents both new and existing users from having duplicate emails.
        # self.instance is used when editing an existing object; for creation, it's None.
        if User.objects.filter(email=email).exists() and (self.instance is None or self.instance.email != email):
            raise forms.ValidationError(_("A user with that email already exists."))

        return email

    def save(self, commit=True):
        user = super().save(commit=False)  # Get the user object without saving it to DB yet

        password = self.cleaned_data.get('password')
        password2 = self.cleaned_data.get('password2')

        if not password:  # If password fields were left blank in the form
            # Generate a random password (e.g., 12 characters, alphanumeric + symbols)
            alphabet = string.ascii_letters + string.digits + string.punctuation
            random_password = ''.join(secrets.choice(alphabet) for i in range(12))
            user.set_password(random_password)  # Set the hashed password
            user.requires_password_change = True  # Set flag for forced password change

            # Display the generated password and email to the admin user
            if self.request:  # Ensure request is available for messages
                messages.info(self.request,
                              _(f"User '{user.username}' created with temporary password: '{random_password}'. They will be required to change it on first login."))
        else:
            # If a password was provided manually, set it and no change is required
            if password != password2:
                raise forms.ValidationError(_("The two password fields didn't match."))
            user.set_password(password)
            user.requires_password_change = False

        if commit:
            user.save()  # Finally save the user object to the database
        return user


# Form for changing an existing user in the admin
class MyUserChangeForm(UserChangeForm):
    class Meta:
        model = User
        # Explicitly list the fields for clarity and control over order
        fields = ('username', 'email', 'first_name', 'last_name', 'phone_number',
                  'is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions',
                  'last_login', 'date_joined', 'requires_password_change')


# Custom Admin class for your User model
class CustomUserAdmin(BaseUserAdmin):
    form = MyUserChangeForm  # Form to use when editing an existing user
    add_form = MyUserCreationForm  # Form to use when adding a new user

    # Fieldsets for editing an existing user.
    # 'password' field uses the default Django password change mechanism.
    fieldsets = (
        (None, {"fields": ("username", "email", "password")}),
        (_("Personal info"), {"fields": ("first_name", "last_name", "phone_number")}),
        (_("Permissions"), {"fields": ("is_active", "is_staff", "is_superuser", "groups", "user_permissions",
                                       "requires_password_change")}),  # Include the new field
        (_("Important dates"), {"fields": ("last_login", "date_joined")}),
    )

    # Fieldsets for adding a NEW user.
    # Note: 'password' and 'password2' are NOT listed here because MyUserCreationForm
    # handles the password generation internally if they are left blank.
    add_fieldsets = (
        (None, {
            "classes": ("wide",),
            "fields": ('username', 'email', 'first_name', 'last_name', 'phone_number', 'is_active', 'is_staff',
                       'is_superuser'),
        }),
    )

    # Fields to display in the list view of users
    list_display = ("username", "email", "first_name", "last_name", "is_staff", "is_active", "requires_password_change")
    # Fields to filter the user list by
    list_filter = ("is_staff", "is_superuser", "is_active", "groups", "requires_password_change")
    # Fields to search by
    search_fields = ("username", "email", "first_name", "last_name")
    # Default ordering of users in the list
    ordering = ("username",)
    # For many-to-many fields (groups, user_permissions)
    filter_horizontal = ("groups", "user_permissions")

    # Override get_form to pass the request object to the form,
    # so messages.info can be used within the form's save method.
    def get_form(self, request, obj=None, **kwargs):
        Form = super().get_form(request, obj, **kwargs)
        # Pass the request only to the creation form
        if obj is None:  # This means it's the 'add user' view
            Form.request = request
        return Form


# Unregister the default User admin if it was somehow registered automatically,
# then register your CustomUserAdmin. This prevents errors if you change AUTH_USER_MODEL.
try:
    admin.site.unregister(User)
except admin.sites.NotRegistered:
    pass

admin.site.register(User, CustomUserAdmin)