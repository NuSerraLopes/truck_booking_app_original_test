# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\forms.py
from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, HTML, Div, Field
from django import forms
from django.contrib.auth import get_user_model
from django.forms.widgets import PasswordInput, TextInput
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from datetime import date
from .models import Vehicle, Booking, Location, User, EmailTemplate, DistributionList
from django.contrib.auth.models import Group
from django.contrib import messages
from django.urls import reverse_lazy


class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = [
            'customer_name', 'customer_email', 'customer_phone',
            'client_tax_number', 'client_company_registration',
            'start_location', 'end_location', 'start_date', 'end_date',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
            'end_date': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
        }
        labels = {
            'customer_name': _("Customer Name"),
            'customer_email': _("Customer Email"),
            'customer_phone': _("Customer Phone"),
            'client_tax_number': _("Client Tax Number"),
            'client_company_registration': _("Client Company Registration"),
            'start_location': _("Start Location"),
            'end_location': _("End Location"),
            'start_date': _("Start Date"),
            'end_date': _("End Date"),
        }

    def __init__(self, *args, **kwargs):
        self.vehicle = kwargs.pop('vehicle', None)
        super().__init__(*args, **kwargs)

        # --- Crispy Forms Helper ---
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            HTML(f'<h5>{_("Client Information")}</h5><hr>'),
            Row(
                Column('customer_name', css_class='form-group col-md-6 mb-0'),
                Column('customer_phone', css_class='form-group col-md-6 mb-0'),
            ),
            'customer_email',
            Row(
                Column('client_tax_number', css_class='form-group col-md-6 mb-0'),
                Column('client_company_registration', css_class='form-group col-md-6 mb-0'),
            ),
            HTML(f'<h5 class="mt-4">{_("Booking Details")}</h5><hr>'),
            Row(
                Column('start_location', css_class='form-group col-md-6 mb-0'),
                Column('end_location', css_class='form-group col-md-6 mb-0'),
            ),
            Row(
                Column('start_date', css_class='form-group col-md-6 mb-0'),
                Column('end_date', css_class='form-group col-md-6 mb-0'),
            ),
            Div(
                Submit('submit', _('Submit Booking Request'), css_class='btn btn-primary'),
                HTML(
                    f'<a href="{reverse_lazy("booking_app:vehicle_list")}" class="btn btn-secondary">{_("Back to Vehicle List")}</a>'),
                css_class='d-flex justify-content-between mt-4'
            )
        )

    # ... (Your clean methods remain the same) ...
    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_("End date must be after start date."))

        if self.vehicle:
            earliest_booking_date = getattr(self.vehicle, 'available_after', None) or date.today()
            if start_date and start_date < earliest_booking_date:
                raise ValidationError(
                    _("Your selected start date (%(start_date)s) is before the earliest available date for this vehicle (%(earliest_date)s). Please select a date on or after %(earliest_date)s.") % {
                        'start_date': start_date.strftime('%Y-%m-%d'),
                        'earliest_date': earliest_booking_date.strftime('%Y-%m-%d')
                    },
                    code='vehicle_unavailable_too_early',
                )

        if start_date and start_date < date.today():
            raise ValidationError(_("Start date cannot be in the past."))

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
        fields = ['license_plate', 'vehicle_type', 'model', 'picture', 'current_location']
        labels = {
            'license_plate': _('License Plate'),
            'vehicle_type': _('Vehicle Type'),
            'model': _('Model Name'),
            'picture': _('Vehicle Picture'),
            'current_location': _('Current Location'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(
                Column('license_plate', css_class='form-group col-md-6 mb-3'),
                Column('model', css_class='form-group col-md-6 mb-3'),
            ),
            Row(
                Column('vehicle_type', css_class='form-group col-md-6 mb-3'),
                Column('current_location', css_class='form-group col-md-6 mb-3'),
            ),
            'picture',
        )


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
        # --- UPDATED: Added send_to_distribution_lists ---
        fields = [
            'name', 'event_trigger', 'subject', 'body', 'is_active',
            'send_to_salesperson', 'send_to_groups', 'send_to_users',
            'send_to_distribution_lists'
        ]
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'event_trigger': forms.Select(attrs={'class': 'form-select'}),
            'subject': forms.TextInput(attrs={'class': 'form-control'}),
            'body': forms.Textarea(attrs={'class': 'form-control', 'rows': 15}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'send_to_salesperson': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'send_to_groups': forms.CheckboxSelectMultiple,
            'send_to_users': forms.CheckboxSelectMultiple,
            'send_to_distribution_lists': forms.CheckboxSelectMultiple,
        }
        labels = {
            'name': _('Template Name'),
            'event_trigger': _('Event Trigger'),
            'subject': _('Email Subject'),
            'body': _('Email Body (HTML is allowed)'),
            'is_active': _('Is this template active?'),
            'send_to_salesperson': _('Send to Salesperson'),
            'send_to_groups': _('Send to Groups'),
            'send_to_users': _('Send to Specific Users'),
            'send_to_distribution_lists': _('Send to Distribution Lists'),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # If editing, make the event trigger read-only
        if self.instance and self.instance.pk:
            self.fields['event_trigger'].widget.attrs['disabled'] = True
            self.fields['event_trigger'].help_text = _("The event trigger cannot be changed after creation.")

class DistributionListForm(forms.ModelForm):
    class Meta:
        model = DistributionList
        fields = ['name', 'emails']
        widgets = {
            'name': forms.TextInput(attrs={'class': 'form-control'}),
            'emails': forms.Textarea(attrs={'class': 'form-control', 'rows': 8}),
        }
        labels = {
            'name': _('List Name'),
            'emails': _('Email Addresses'),
        }