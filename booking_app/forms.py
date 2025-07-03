# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\forms.py

from django import forms
from django.contrib.auth import get_user_model
from django.forms.widgets import PasswordInput, TextInput
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from datetime import date
from .models import Vehicle, Booking, Location, User, EmailTemplate
from django.contrib.auth.models import Group
from django.contrib import messages


class BookingForm(forms.ModelForm):
    vehicle_type_hint = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Booking
        fields = [
            'customer_name', 'customer_email', 'customer_phone', 'client_tax_number', 'client_company_registration',
            'start_location', 'end_location', 'start_date', 'end_date',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'start_location': forms.Select(attrs={'class': 'form-control', 'id': 'start-location'}),
            'end_location': forms.Select(attrs={'class': 'form-control', 'id': 'end-location'}),
        }

    def __init__(self, *args, **kwargs):
        self.vehicle = kwargs.pop('vehicle', None)
        super().__init__(*args, **kwargs)

        self.fields['start_location'].empty_label = _("Select Start Location")
        self.fields['end_location'].empty_label = _("Select End Location")
        self.fields['start_location'].label = _("Start Location")
        self.fields['end_location'].label = _("End Location")
        self.fields['start_location'].error_messages = {'required': _('Please select a start location.')}
        self.fields['end_location'].error_messages = {'required': _('Please select a destination location.')}
        self.fields['customer_name'].label = _("Customer Name")
        self.fields['customer_email'].label = _("Customer Email")
        self.fields['customer_phone'].label = _("Customer Phone")
        self.fields['client_tax_number'].label = _("Client Tax Number")
        self.fields['client_company_registration'].label = _("Client Company Registration")
        self.fields['start_date'].label = _("Start Date")
        self.fields['end_date'].label = _("End Date")

        # --- UPDATED: Set field requirements ---
        self.fields['customer_email'].required = False
        self.fields['customer_phone'].required = False
        self.fields['client_tax_number'].required = True
        self.fields['client_company_registration'].required = True
        # --- END UPDATE ---

        # Apply form-control class to relevant fields for consistent styling
        for field_name in ['customer_name', 'customer_email', 'customer_phone', 'client_tax_number',
                           'client_company_registration', 'start_date', 'end_date']:
            if field_name in self.fields:  # Check if field exists before updating attrs
                self.fields[field_name].widget.attrs.update({'class': 'form-control'})

        if self.vehicle is not None and self.vehicle.pk is not None:
            self.fields['vehicle_type_hint'].initial = self.vehicle.vehicle_type

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        customer_email = cleaned_data.get('customer_email')
        customer_phone = cleaned_data.get('customer_phone')

        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_("End date must be after start date."))

        # This logic relies on vehicle.available_after being set in the view
        # (e.g., in book_vehicle_view).
        if self.vehicle:
            earliest_booking_date = None
            if hasattr(self.vehicle, 'available_after') and self.vehicle.available_after:
                earliest_booking_date = self.vehicle.available_after
            else:
                earliest_booking_date = date.today()

            if start_date and earliest_booking_date:
                if start_date < earliest_booking_date:
                    raise ValidationError(
                        _("Your selected start date (%(start_date)s) is before the earliest available date for this vehicle (%(earliest_date)s). Please select a date on or after %(earliest_date)s.") % {
                            'start_date': start_date.strftime('%Y-%m-%d'),
                            'earliest_date': earliest_booking_date.strftime('%Y-%m-%d')
                        },
                        code='vehicle_unavailable_too_early',
                    )

        if start_date and start_date < date.today():
            raise ValidationError(_("Start date cannot be in the past."))

        # --- UPDATED: Custom validation logic ---
        # Check that at least one contact method is provided.
        if not customer_email and not customer_phone:
            raise ValidationError(
                _("Please provide at least one contact method: either an email address or a phone number."),
                code='missing_contact_info'
            )
        # --- END UPDATE ---

        return cleaned_data


class UpdateUserForm(forms.ModelForm):
    # Add the fields for group management
    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'),
        widget=forms.CheckboxSelectMultiple,  # Renders as checkboxes
        required=False,
        label=_("Assign to Other Groups")
    )

    # Add the checkbox for custom admin dashboard access
    is_admin_member_checkbox = forms.BooleanField(
        required=False,
        label=_("Grant Custom Admin Dashboard Access (Adds to 'Admin' Group)")
    )

    class Meta:
        model = User
        fields = [
            'username',  # Re-add username if it was removed, it's essential for a user
            'email',
            'first_name',
            'last_name',
            'phone_number',
            'is_active',  # is_active should be here
            'is_staff',  # Keep if you manage Django admin access here
            'is_superuser',  # Keep if you manage superuser status here
            'requires_password_change',
        ]
        labels = {
            'username': _('Username'),
            'email': _('Email'),
            'first_name': _('First Name'),
            'last_name': _('Last Name'),
            'phone_number': _('Phone Number'),
            'is_active': _('Is Active'),
            'is_staff': _('Is Staff (Django Admin Access)'),  # Clarify label
            'is_superuser': _('Is Superuser'),
            'requires_password_change': _('Requires Password Change'),
        }

    def __init__(self, *args, **kwargs):
        # Retrieve the request object if it was passed from the view
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        # Apply Bootstrap classes for consistent styling
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.EmailInput)):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            elif isinstance(field.widget, forms.CheckboxSelectMultiple):
                pass

        if self.instance and self.instance.pk:  # For an existing user being edited
            # Pre-populate the 'groups' field with the user's current groups
            self.fields['groups'].initial = self.instance.groups.all()

            # Pre-populate 'is_admin_member_checkbox' based on 'Admin' group membership
            try:
                admin_group = Group.objects.get(name='Admin')
                if self.instance.groups.filter(pk=admin_group.pk).exists():
                    self.fields['is_admin_member_checkbox'].initial = True
            except Group.DoesNotExist:
                # If 'Admin' group doesn't exist, hide or disable this checkbox
                self.fields['is_admin_member_checkbox'].widget = forms.HiddenInput()
                self.fields['is_admin_member_checkbox'].required = False
                self.fields['is_admin_member_checkbox'].label = ""
                if self.request:  # Display warning if group missing during init
                    messages.warning(self.request,
                                     _("Warning: The 'Admin' group does not exist. Cannot manage admin privileges via checkbox."))

    @transaction.atomic  # Ensures all database operations are completed or rolled back together
    def save(self, commit=True):
        user = super().save(commit=False)  # Get the user instance (already existing)

        # No password setting logic here for UpdateUserForm; password reset is separate.

        if commit:
            user.save()  # Save the user's basic fields

        # Handle user's group assignments
        # Get selected groups from the 'groups' field
        selected_groups_from_form = set(self.cleaned_data.get('groups', []))

        # Handle the 'is_admin_member_checkbox' logic
        grant_admin_access = self.cleaned_data.get('is_admin_member_checkbox', False)

        try:
            admin_group = Group.objects.get(name='Admin')
            if grant_admin_access:
                selected_groups_from_form.add(admin_group)  # Add 'Admin' group if checkbox is checked
            else:
                selected_groups_from_form.discard(admin_group)  # Remove 'Admin' group if checkbox is unchecked
        except Group.DoesNotExist:
            if grant_admin_access and self.request:  # Display error if group missing during save
                messages.error(self.request,
                               _("Error: The 'Admin' group does not exist. User cannot be assigned admin privileges."))
            print("Warning: 'Admin' group does not exist. Cannot manage admin privileges via checkbox.")

        # Assign the final set of groups to the user
        user.groups.set(list(selected_groups_from_form))

        return user

    # Custom clean methods for uniqueness of username and email
    # These are crucial for update forms to prevent "already exists" errors on the current user's data
    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("A user with that username already exists."))
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email


class UserCreateForm(forms.ModelForm):
    password = forms.CharField(
        label=_("Password"),
        widget=PasswordInput(attrs={'class': 'form-control'}),
        strip=False,
        help_text=_("Enter a password for the new user. Must be at least 8 characters long.")
    )
    password2 = forms.CharField(
        label=_("Password confirmation"),
        widget=PasswordInput(attrs={'class': 'form-control'}),
        strip=False,
        help_text=_("Enter the same password as above, for verification.")
    )

    groups = forms.ModelMultipleChoiceField(
        queryset=Group.objects.all().order_by('name'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Assign to Other Groups")
    )

    is_admin_member_checkbox = forms.BooleanField(
        required=False,
        label=_("Grant Custom Admin Dashboard Access (Adds to 'Admin' Group)")
    )

    class Meta:
        model = User
        fields = [
            'username',
            'email',
            'first_name',
            'last_name',
            'phone_number',
            # 'is_active' removed from here, as it will always be True by default or set explicitly in save()
        ]
        labels = {
            'username': _('Username'),
            'email': _('Email'),
            'first_name': _('First Name'),
            'last_name': _('Last Name'),
            'phone_number': _('Phone Number'),
            # 'is_active' label removed
        }
        widgets = {
            'username': forms.TextInput(attrs={'class': 'form-control'}),
            'email': forms.EmailInput(attrs={'class': 'form-control'}),
            'first_name': forms.TextInput(attrs={'class': 'form-control'}),
            'last_name': forms.TextInput(attrs={'class': 'form-control'}),
            'phone_number': forms.TextInput(attrs={'class': 'form-control'}),
            # 'is_active' widget removed
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

        if 'is_admin_member_checkbox' in self.fields and isinstance(self.fields['is_admin_member_checkbox'].widget,
                                                                    forms.CheckboxInput):
            self.fields['is_admin_member_checkbox'].widget.attrs.update({'class': 'form-check-input'})

        try:
            Group.objects.get(name='Admin')
        except Group.DoesNotExist:
            self.fields['is_admin_member_checkbox'].widget = forms.HiddenInput()
            self.fields['is_admin_member_checkbox'].required = False
            self.fields['is_admin_member_checkbox'].label = ""
            if self.request:
                messages.warning(self.request,
                                 _("Warning: The 'Admin' group does not exist. Cannot manage admin privileges via checkbox."))
            print(
                "Warning: 'Admin' group does not exist. The 'Grant Custom Admin Dashboard Access' checkbox will be hidden.")

    @transaction.atomic
    def save(self, request=None, commit=True):
        user = super().save(commit=False)

        # Ensure is_active is True for new users, as it's no longer a form field
        # Django's AbstractUser sets is_active=True by default, but it's good to be explicit
        user.is_active = True

        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)

        if commit:
            user.save()

        selected_groups_from_form = set(self.cleaned_data.get('groups', []))
        grant_admin_access = self.cleaned_data.get('is_admin_member_checkbox', False)

        try:
            admin_group = Group.objects.get(name='Admin')
            if grant_admin_access:
                selected_groups_from_form.add(admin_group)
            else:
                selected_groups_from_form.discard(admin_group)
        except Group.DoesNotExist:
            if grant_admin_access and request:
                messages.error(request,
                               _("Error: The 'Admin' group does not exist. User cannot be assigned admin privileges."))
            print("Warning: 'Admin' group does not exist. Cannot manage admin privileges via checkbox.")

        user.groups.set(list(selected_groups_from_form))

        if request:
            messages.success(request, _(f"User '{user.username}' created successfully!"))

        return user

    def clean_username(self):
        username = self.cleaned_data['username']
        if User.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError(_("A user with that username already exists."))
        return username

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get("password")
        password2 = cleaned_data.get("password2")

        if password and password2:
            if password != password2:
                self.add_error('password2', _("The two password fields didn't match."))
            if len(password) < 8:
                self.add_error('password', _("Password must be at least 8 characters long."))
        elif password or password2:
            self.add_error('password', _("Both password fields are required."))

        return cleaned_data


class VehicleCreateForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['license_plate', 'vehicle_type', 'model', 'picture', 'current_location', 'is_available']
        labels = {
            'license_plate': _('License Plate'),
            'vehicle_type': _('Vehicle Type'),
            'model': _('Model Name'),
            'picture': _('Vehicle Picture'),
            'current_location': _('Current Location'),
            'is_available': _('Is Available'),
        }
        widgets = {
            'vehicle_type': forms.Select(attrs={'class': 'form-control'}),  # Added class
            'current_location': forms.Select(attrs={'class': 'form-control'}),  # Added class
            'license_plate': forms.TextInput(attrs={'class': 'form-control'}),  # Added class
            'model': forms.TextInput(attrs={'class': 'form-control'}),  # Added class
            'is_available': forms.CheckboxInput(attrs={'class': 'form-check-input'}),  # Added class
            # No class for picture as it's a FileInput, often styled differently
        }


class VehicleEditForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['license_plate', 'vehicle_type', 'model', 'picture', 'current_location', 'is_available']
        labels = {  # Added labels for consistency
            'license_plate': _('License Plate'),
            'vehicle_type': _('Vehicle Type'),
            'model': _('Model Name'),
            'picture': _('Vehicle Picture'),
            'current_location': _('Current Location'),
            'is_available': _('Is Available'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Apply Bootstrap classes for consistent styling
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Select)):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})
            # FileInput (for 'picture') usually doesn't get 'form-control' directly


class LocationCreateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name']
        labels = {
            'name': _('Location Name'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),  # Added class
        }


class LocationUpdateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name']
        labels = {
            'name': _('Location Name'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),  # Added class
        }


class GroupForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all().order_by('username'),
        widget=forms.CheckboxSelectMultiple,
        required=False,
        label=_("Group Members")
    )

    class Meta:
        model = Group
        fields = ['name']
        labels = {
            'name': _('Group Name'),
        }
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['users'].initial = self.instance.user_set.all()

    def save(self, commit=True):
        group = super().save(commit=commit)

        if group.pk:
            if 'users' in self.cleaned_data:
                group.user_set.set(self.cleaned_data['users'])
            else:
                group.user_set.clear()
        if commit:
            pass

        return group

    def clean_name(self):
        name = self.cleaned_data['name']
        if self.instance and self.instance.name == name:
            return name

        if Group.objects.filter(name=name).exists():
            raise forms.ValidationError(_("A group with this name already exists."))
        return name

class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = ['name', 'template_key', 'subject', 'body']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'template_key': forms.TextInput(attrs={'class': 'form-control'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 15}),
        }
        labels = {
            'name': _('Template Name (for internal reference)'),
            'template_key': _('Template Key'),
            'subject': _('Email Subject'),
            'body': _('Email Body (HTML is allowed)'),
        }
        help_texts = {
            'template_key': _("A unique key used by the system (e.g., 'booking_created'). Cannot be changed after creation.")
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If we are editing an existing template, make the key read-only
        if self.instance and self.instance.pk:
            self.fields['template_key'].widget.attrs['readonly'] = True

    def clean_template_key(self):
        # Ensure the template key is not changed on an existing object
        key = self.cleaned_data.get('template_key')
        if self.instance and self.instance.pk and self.instance.template_key != key:
            raise forms.ValidationError(_("The template key cannot be changed."))
        return key