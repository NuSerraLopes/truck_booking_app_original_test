# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\forms.py
import os

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, HTML, Div, Field
from django import forms
from django.db import transaction
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

from .utils import subtract_business_days, add_business_days


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
            'contract_document', 'final_km', 'motive',
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
            'contract_document': _("Contract"),
            'final_km': _("Final Kilometers"),
            'motive': _("Motive"),
        }

    def __init__(self, *args, **kwargs):
        self.vehicle = kwargs.pop('vehicle', None)
        is_create_page = kwargs.pop('is_create_page', False)
        upload_only = kwargs.pop('upload_only', False)
        super().__init__(*args, **kwargs)

        if self.instance and self.instance.pk:
            self.initial_contract_document = self.instance.contract_document
        else:
            self.initial_contract_document = None

        if self.vehicle and self.vehicle.vehicle_type == 'APV':
            self.fields['motive'].required = True
            self.fields['motive'].label = _("Motive (Required for APV)")
            if self.instance and self.instance.status == 'pending_final_km':
                self.fields['final_km'].required = True
            else:
                self.fields['final_km'].widget = forms.HiddenInput()
                self.fields['final_km'].required = False
        else:
            self.fields['motive'].widget = forms.HiddenInput()
            self.fields['motive'].required = False
            self.fields['final_km'].widget = forms.HiddenInput()
            self.fields['final_km'].required = False

        if upload_only:
            for field_name, field in self.fields.items():
                if field_name != 'contract_document':
                    field.widget.attrs['disabled'] = 'disabled'
                    field.widget.attrs['readonly'] = 'readonly'

        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            HTML(f'<h5>{_("Client Information")}</h5><hr>'),
            Row(Column('customer_name', css_class='form-group col-md-6 mb-0'),
                Column('customer_phone', css_class='form-group col-md-6 mb-0')),
            'customer_email',
            Row(Column('client_tax_number', css_class='form-group col-md-6 mb-0'),
                Column('client_company_registration', css_class='form-group col-md-6 mb-0')),
            HTML(f'<h5 class="mt-4">{_("Booking Details")}</h5><hr>'),
            'motive',
            Row(Column('start_location', css_class='form-group col-md-6 mb-0'),
                Column('end_location', css_class='form-group col-md-6 mb-0')),
            Row(Column('start_date', css_class='form-group col-md-6 mb-0'),
                Column('end_date', css_class='form-group col-md-6 mb-0')),
            'contract_document',
            'final_km',
        )

        if is_create_page:
            self.helper.layout.append(
                Div(
                    Submit('submit', _('Submit Booking Request'), css_class='btn btn-primary'),
                    HTML(
                        f'<a href="{reverse_lazy("booking_app:vehicle_list")}" class="btn btn-secondary">{_("Back to Vehicle List")}</a>'),
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

    @transaction.atomic
    def save(self, commit=True):
        # Logic for clearing the contract document
        if self.data.get("contract_document-clear") and self.initial_contract_document:
            self.initial_contract_document.delete(save=False)

        booking = super().save(commit=False)

        # --- CORRECTED LOGIC: Use self.vehicle which is guaranteed to exist ---
        vehicle_for_check = self.vehicle if self.vehicle else booking.vehicle

        # --- Logic to check the PREVIOUS booking ---
        previous_booking = Booking.objects.filter(
            vehicle=vehicle_for_check,
            end_date__lt=booking.start_date
        ).order_by('-end_date').first()

        if previous_booking:
            if previous_booking.end_location != booking.start_location:
                booking.needs_transport = True
            else:
                booking.needs_transport = False
        else:
            booking.needs_transport = False

        if commit:
            booking.save()
            self.save_m2m()

        # --- Logic to check and update the NEXT booking ---
        next_booking = Booking.objects.filter(
            vehicle=vehicle_for_check,
            start_date__gt=booking.end_date
        ).order_by('start_date').first()

        if next_booking:
            if booking.end_location != next_booking.start_location:
                next_booking.needs_transport = True
            else:
                next_booking.needs_transport = False
            next_booking.save(update_fields=['needs_transport'])

        return booking

    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')
        tomorrow = date.today() + timedelta(days=1)
        if start_date and start_date < tomorrow:
            raise ValidationError(
                _("Booking date cannot be today or in the past. Please select tomorrow or a future date."),
                code='invalid_start_date')
        return start_date

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        final_km = cleaned_data.get('final_km')
        motive = cleaned_data.get('motive')

        if start_date and end_date and start_date > end_date:
            raise ValidationError(_("End date must be after start date."))

        # --- UPDATED OVERLAP VALIDATION LOGIC ---
        if self.vehicle and start_date and end_date:
            if self.vehicle.vehicle_type == 'APV':
                unavailable_statuses = ['pending', 'confirmed', 'pending_final_km']
            else:
                unavailable_statuses = ['pending', 'pending_contract', 'confirmed']

            new_booking_start_buffer = subtract_business_days(start_date, 3)
            new_booking_end_buffer = add_business_days(end_date, 3)

            conflicting_bookings = Booking.objects.filter(
                vehicle=self.vehicle,
                status__in=unavailable_statuses,
                start_date__lte=new_booking_end_buffer,
                end_date__gte=new_booking_start_buffer,
            )

            if self.instance and self.instance.pk:
                conflicting_bookings = conflicting_bookings.exclude(pk=self.instance.pk)

            if conflicting_bookings.exists():
                conflict = conflicting_bookings.first()
                raise ValidationError(
                    _("The selected date range conflicts with an existing booking (ID: %(booking_id)s) for this vehicle from %(start)s to %(end)s.") % {
                        'booking_id': conflict.pk,
                        'start': conflict.start_date.strftime('%Y-%m-%d'),
                        'end': conflict.end_date.strftime('%Y-%m-%d'),
                    }
                )

        # --- Other validations ---
        if self.vehicle and self.vehicle.vehicle_type == 'APV':
            if not motive and not self.instance.pk:
                self.add_error('motive', _("This field is required for APV bookings."))

        if self.instance and self.instance.initial_km is not None and final_km is not None:
            if final_km <= self.instance.initial_km:
                raise ValidationError(
                    _("Final kilometers (%(final)s) must be greater than the initial kilometers (%(initial)s).") %
                    {'final': final_km, 'initial': self.instance.initial_km}
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
    """
    A form for creating new users by an admin.
    This form does not handle passwords. It creates a user with an
    unusable password that must be set later by an admin sending credentials.
    """

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
            'groups': _("Assign to Groups"),
        }
        # This widget requires a custom implementation or a third-party package
        # to render checkboxes correctly with Bootstrap styling.
        widgets = {
            'groups': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super().__init__(*args, **kwargs)

    @transaction.atomic
    def save(self, request=None, commit=True):
        user = super().save(commit=False)
        user.is_active = True

        # Set an unusable password. An admin must send credentials to activate.
        user.set_unusable_password()

        if commit:
            user.save()
            # self.save_m2m() is needed to save the groups relationship
            self.save_m2m()

        # The success message is now handled in the view after redirecting.
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


class VehicleCreateForm(forms.ModelForm):
    class Meta:
        model = Vehicle
        fields = ['license_plate', 'vehicle_type', 'model', 'picture', 'current_location',
                  'insurance_document','registration_document','next_maintenance_date',
                  ]
        labels = {
            'license_plate': _('License Plate'),
            'vehicle_type': _('Vehicle Type'),
            'model': _('Model Name'),
            'picture': _('Vehicle Picture'),
            'current_location': _('Current Location'),
            'insurance_document': _('Insurance'),
            'registration_document': _('Registration'),
            'next_maintenance_date': _('Next Maintenance Date'),
        }

        widgets = {
            'next_maintenance_date': forms.DateInput(attrs={'type': 'date'}),
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
            'next_maintenance_date',
        ]
        widgets = {
            'picture': forms.FileInput(),
            'next_maintenance_date': forms.DateInput(attrs={'type': 'date'}),
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
        fields = [
            'pending_booking_automation_active',
            'enable_pending_reminders',
            'reminder_days_pending',
        ]
        labels = {
            'enable_pending_reminders': _("Enable Reminders for Pending Bookings"),
            'reminder_days_pending': _("Send Reminder After (Days)"),
        }
        help_texts = {
            'enable_pending_reminders': _("If checked, the system will send reminders for bookings that are pending for too long."),
            'reminder_days_pending': _("The number of days a booking can be in 'Pending' status before a reminder is sent."),
        }

class BookingFilterForm(forms.Form):
    """
    A form for filtering bookings on the group dashboard.
    The status choices are dynamically adjusted based on the user's group.
    """
    status = forms.ChoiceField(
        required=False,
        label=_("Filter by Status"),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)


        choices = [
            ('', _('All Actionable')),
            ('pending', _('Pending Approval')),
            ('pending_contract', _('Pending Contract')),
            ('confirmed', _('Confirmed / Upcoming')),
            ('completed', _('Completed')),
            ('cancelled', _('Cancelled')),
        ]

        if user and user.groups.filter(name='tlapv').exists():
            choices.insert(4, ('pending_final_km', _('Pending Final KM')))

        # Set the choices for the status field
        self.fields['status'].choices = choices