# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\forms.py
import os

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, HTML, Div, Field
from django import forms
from django.contrib.auth import get_user_model
from django.forms.widgets import PasswordInput, TextInput
from django.db import transaction
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from datetime import date, timedelta
from .models import Vehicle, Booking, Location, User, EmailTemplate, DistributionList, AutomationSettings
from django.contrib.auth.models import Group
from django.contrib import messages
from django.urls import reverse_lazy

class BootstrapCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def __init__(self, attrs=None):
        if attrs is None:
            attrs = {}
        attrs['class'] = attrs.get('class', '') + ' form-check-input'
        super().__init__(attrs)

class BookingForm(forms.ModelForm):
    class Meta:
        model = Booking
        fields = [
            'customer_name', 'customer_email', 'customer_phone',
            'client_tax_number', 'client_company_registration',
            'start_location', 'end_location', 'start_date', 'end_date',
            'contract_document',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }
        labels = {
            'customer_name': _("Customer Name"),
            'customer_email': _("Customer Email"),
            'customer_phone': _("Customer Phone"),
            'client_tax_number': _("Client Tax Number"),
            'client_company_registration': _("Client Company Registration Code"),
            'start_location': _("Start Location"),
            'end_location': _("End Location"),
            'start_date': _("Start Date"),
            'end_date': _("End Date"),
            'contract_document': _("Contract Document"),
        }

    def __init__(self, *args, **kwargs):
        self.vehicle = kwargs.pop('vehicle', None)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.initial_contract_document = self.instance.contract_document
        else:
            self.initial_contract_document = None

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
            'contract_document',
            Div(
                Submit('submit', _('Save Changes'), css_class='btn btn-primary'),
                HTML(
                    f'<a href="{self.instance.get_absolute_url() if self.instance and self.instance.pk else reverse_lazy("booking_app:vehicle_list")}" class="btn btn-secondary">{_("Cancel")}</a>'),
                css_class='d-flex justify-content-between mt-4'
            )
        )

    def has_changed(self):
        has_changed = super().has_changed()
        if has_changed:
            return True
        if 'contract_document-clear' in self.data:
            return True
        return False

    def save(self, commit=True):
        if self.data.get("contract_document-clear") and self.initial_contract_document:
            self.initial_contract_document.delete(save=False)
        return super().save(commit)

    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        tomorrow = date.today() + timedelta(days=1)

        if start_date and start_date < tomorrow:
            raise ValidationError(
                _("Booking date cannot be today or in the past. Please select tomorrow or a future date."),
                code='invalid_start_date'
            )
        return start_date

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')

        if start_date and end_date:
            if start_date > end_date:
                raise ValidationError(_("End date must be after start date."))

        if self.vehicle:
            earliest_booking_date = getattr(self.vehicle, 'available_after', None)
            if earliest_booking_date and start_date and start_date < earliest_booking_date:
                raise ValidationError(
                    _("This vehicle is only available after %(earliest_date)s. Please select a later date.") % {
                        'earliest_date': earliest_booking_date.strftime('%d/%m/%Y')
                    }
                )

        return cleaned_data


class UpdateUserForm(forms.ModelForm):
    class Meta:
        model = User
        # The permission fields have been removed from this list
        fields = [
            'email', 'first_name', 'last_name', 'phone_number', 'groups','language',
        ]
        labels = {
            'email': _('Email'),
            'first_name': _('First Name'),
            'last_name': _('Last Name'),
            'phone_number': _('Phone Number'),
            'groups': _('Assign to Groups'),
        }
        widgets = {
            'groups': BootstrapCheckboxSelectMultiple,
        }

    # The save and clean methods remain the same
    @transaction.atomic
    def save(self, commit=True):
        user = super().save(commit=commit)
        return user

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email


class UserCreateForm(forms.ModelForm):
    # Form-only fields (not on the User model) are defined here.
    password = forms.CharField(
        label=_("Password"),
        widget=forms.PasswordInput(),
        strip=False,
        help_text=_("Enter a password for the new user. Must be at least 8 characters long.")
    )
    password2 = forms.CharField(
        label=_("Password confirmation"),
        widget=forms.PasswordInput(),
        strip=False,
        help_text=_("Enter the same password as above, for verification.")
    )

    class Meta:
        model = User
        fields = [
            'username', 'email', 'first_name', 'last_name', 'phone_number', 'groups',
        ]
        labels = {
            'username': _('Username'),
            'email': _('Email'),
            'first_name': _('First Name'),
            'last_name': _('Last Name'),
            'phone_number': _('Phone Number'),
            'groups': _("Assign to Other Groups"),
        }
        widgets = {
            'groups': BootstrapCheckboxSelectMultiple,
        }

    # The __init__, save, and clean methods remain the same.
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    @transaction.atomic
    def save(self, request=None, commit=True):
        user = super().save(commit=False)
        user.is_active = True
        password = self.cleaned_data.get("password")
        if password:
            user.set_password(password)
        if commit:
            user.save()

        # This logic handles both the 'groups' and 'is_admin_member_checkbox' fields.
        selected_groups_from_form = set(self.cleaned_data.get('groups', []))

        user.groups.set(list(selected_groups_from_form))

        if request:
            messages.success(request, _(f"User '{user.username}' created successfully!"))
        return user

    # The clean methods remain unchanged.
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
        fields = ['license_plate', 'vehicle_type', 'model', 'picture', 'current_location','insurance_document','registration_document',]
        labels = {
            'license_plate': _('License Plate'),
            'vehicle_type': _('Vehicle Type'),
            'model': _('Model Name'),
            'picture': _('Vehicle Picture'),
            'current_location': _('Current Location'),
            'insurance_document': _('Insurance Document'),
            'registration_document': _('Registration Document'),
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
        fields = [
            'license_plate',
            'vehicle_type',
            'model',
            'picture',
            'current_location',
            'is_available',
            'insurance_document',
            'registration_document',
        ]
        widgets = {
            'picture': forms.FileInput(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # --- Store the initial file info BEFORE anything happens ---
        if self.instance and self.instance.pk:
            self.initial_insurance = self.instance.insurance_document
            self.initial_registration = self.instance.registration_document
        else:
            self.initial_insurance = None
            self.initial_registration = None

        # Your styling loop
        for field_name, field in self.fields.items():
            if isinstance(field.widget, (forms.TextInput, forms.Select, forms.ClearableFileInput, forms.FileInput)):
                field.widget.attrs.update({'class': 'form-control'})
            elif isinstance(field.widget, forms.CheckboxInput):
                field.widget.attrs.update({'class': 'form-check-input'})

    def has_changed(self):
        """Checks if the form has changed, including 'clear' checkboxes."""
        has_changed = super().has_changed()
        if has_changed:
            return True
        if 'insurance_document-clear' in self.data or 'registration_document-clear' in self.data:
            return True
        return False

    def save(self, commit=True):
        # Use the initial file information we stored in __init__
        if self.data.get("insurance_document-clear") and self.initial_insurance:
            self.initial_insurance.delete(save=False)

        if self.data.get("registration_document-clear") and self.initial_registration:
            self.initial_registration.delete(save=False)

        # Let the parent save method handle updating the database
        return super().save(commit)


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

class AutomationSettingsForm(forms.ModelForm):
    class Meta:
        model = AutomationSettings
        fields = ['pending_booking_automation_active']
        widgets = {
            'pending_booking_automation_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }