# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\forms.py

# --- Consolidated Imports ---
from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from datetime import date, timedelta

from crispy_forms.helper import FormHelper
from crispy_forms.layout import Layout, Row, Column, Submit, HTML, Div

from .models import Vehicle, Booking, Location, EmailTemplate, DistributionList, AutomationSettings, Client
from .utils import subtract_business_days, add_business_days, send_booking_notification

# Re-assign User model for clarity
User = get_user_model()


# --- Custom Widgets & Forms ---

class BootstrapCheckboxSelectMultiple(forms.CheckboxSelectMultiple):
    def __init__(self, attrs=None):
        super().__init__(attrs={'class': 'form-check-input'})


class BookingForm(forms.ModelForm):
    # Unbound fields to capture client data
    client_name = forms.CharField(label=_("Client Name"))
    client_tax_number = forms.CharField(label=_("Client Tax Number"))
    client_address = forms.CharField(
        label=_("Client Address"),
        widget=forms.Textarea(attrs={'rows': 3}),
        required=False
    )
    client_email = forms.EmailField(label=_("Client Email"), required=False)
    client_phone = forms.CharField(label=_("Client Phone"), max_length=20, required=False)
    client_company_registration = forms.CharField(label=_("Client CRC"), max_length=100, required=False)
    client_id = forms.IntegerField(widget=forms.HiddenInput(), required=False)
    conflict_resolution = forms.CharField(widget=forms.HiddenInput(), required=False)

    class Meta:
        model = Booking
        fields = [
            'start_location', 'end_location', 'start_date', 'end_date',
            'final_km', 'motive', 'needs_transport',
        ]
        widgets = {
            'start_date': forms.DateInput(attrs={'type': 'date'}),
            'end_date': forms.DateInput(attrs={'type': 'date'}),
        }

    def __init__(self, *args, **kwargs):
        self.vehicle = kwargs.pop('vehicle', None)
        is_create_page = kwargs.pop('is_create_page', False)
        crc_is_mandatory = kwargs.pop('crc_is_mandatory', False)
        super().__init__(*args, **kwargs)

        # Pre-fill client info if booking has client
        if self.instance and self.instance.pk and self.instance.client:
            self.initial['client_name'] = self.instance.client.name
            self.initial['client_tax_number'] = self.instance.client.tax_number
            self.initial['client_address'] = self.instance.client.address
            self.initial['client_email'] = self.instance.client.email
            self.initial['client_phone'] = self.instance.client.phone_number

        if crc_is_mandatory:
            self.fields['client_company_registration'].required = True

        if self.vehicle and self.vehicle.vehicle_type == 'APV':
            self.fields['motive'].required = True
        else:
            self.fields['motive'].widget = forms.HiddenInput()
            self.fields['motive'].required = False

        if self.instance and self.instance.status == 'pending_final_km':
            self.fields['final_km'].required = True
            for field_name, field in self.fields.items():
                if field_name not in [
                    'final_km', 'client_name', 'client_tax_number', 'client_address',
                    'client_email', 'client_phone', 'client_company_registration',
                    'client_id', 'conflict_resolution'
                ]:
                    field.widget.attrs['readonly'] = 'readonly'
        else:
            self.fields['final_km'].widget = forms.HiddenInput()
            self.fields['final_km'].required = False

        # Crispy Forms layout
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        self.helper.layout = Layout(
            HTML(f'<h5>{_("Client Information")}</h5><hr>'),
            Row(Column('client_tax_number', css_class='form-group col-md-12 mb-3')),
            Row(
                Column('client_name', css_class='form-group col-md-6 mb-3'),
                Column('client_phone', css_class='form-group col-md-6 mb-3')
            ),
            Row(Column('client_email', css_class='form-group col-md-12 mb-3')),
            Row(Column('client_address', css_class='form-group col-md-12 mb-3')),
            Row(Column('client_company_registration', css_class='form-group col-md-12 mb-3')),

            HTML(f'<h5 class="mt-4">{_("Booking Details")}</h5><hr>'),
            'motive',
            Row(
                Column('start_location', css_class='form-group col-md-6 mb-3'),
                Column('end_location', css_class='form-group col-md-6 mb-3')
            ),
            Row(
                Column('start_date', css_class='form-group col-md-6 mb-3'),
                Column('end_date', css_class='form-group col-md-6 mb-3')
            ),
            'needs_transport',
            'final_km',
            'client_id',
            'conflict_resolution',
        )

        if is_create_page:
            self.helper.layout.append(
                Div(
                    Submit('submit', _('Submit Booking Request'), css_class='btn btn-primary mt-4'),
                    HTML(f'<a href="{reverse_lazy("booking_app:vehicle_list")}" '
                         f'class="btn btn-secondary mt-4">{_("Back to Vehicle List")}</a>'),
                    css_class='d-flex justify-content-between'
                )
            )

    def clean(self):
        cleaned_data = super().clean()
        client_email = cleaned_data.get('client_email')
        client_phone = cleaned_data.get('client_phone')

        if not client_email and not client_phone:
            raise ValidationError(_("Please provide either a Client Email or a Client Phone Number."))

        start_date = cleaned_data.get('start_date')
        end_date = cleaned_data.get('end_date')
        final_km = cleaned_data.get('final_km')
        motive = cleaned_data.get('motive')

        if start_date and end_date and start_date > end_date:
            raise ValidationError(_("End date must be after start date."))

        if self.vehicle and start_date and end_date:
            unavailable_statuses = ['pending', 'pending_contract', 'confirmed', 'pending_final_km']
            new_booking_start_buffer = subtract_business_days(start_date, 3)
            new_booking_end_buffer = add_business_days(end_date, 3)
            conflicting_bookings = Booking.objects.filter(
                vehicle=self.vehicle,
                status__in=unavailable_statuses,
                start_date__lte=new_booking_end_buffer,
                end_date__gte=new_booking_start_buffer
            )
            if self.instance and self.instance.pk:
                conflicting_bookings = conflicting_bookings.exclude(pk=self.instance.pk)
            if conflicting_bookings.exists():
                conflict = conflicting_bookings.first()
                raise ValidationError(
                    _("The selected date range conflicts with an existing booking "
                      "(ID: %(booking_id)s) for this vehicle from %(start)s to %(end)s.") % {
                        'booking_id': conflict.pk,
                        'start': conflict.start_date.strftime('%Y-%m-%d'),
                        'end': conflict.end_date.strftime('%Y-%m-%d'),
                    }
                )

        if self.vehicle and self.vehicle.vehicle_type == 'APV' and not motive and not self.instance.pk:
            self.add_error('motive', _("This field is required for APV bookings."))

        if self.instance and self.instance.initial_km is not None and final_km is not None:
            if final_km <= self.instance.initial_km:
                raise ValidationError(
                    _("Final kilometers (%(final)s) must be greater than the initial kilometers (%(initial)s).") % {
                        'final': final_km,
                        'initial': self.instance.initial_km,
                    }
                )
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        booking = super().save(commit=False)

        if booking.final_km is not None:
            vehicle = booking.vehicle
            vehicle.vehicle_km = booking.final_km
            vehicle.save(update_fields=['vehicle_km'])

        vehicle_for_check = self.vehicle if self.vehicle else booking.vehicle
        previous_booking = Booking.objects.filter(
            vehicle=vehicle_for_check, end_date__lt=booking.start_date
        ).order_by('-end_date').first()

        booking.needs_transport = (
            previous_booking.end_location != booking.start_location
        ) if previous_booking else False

        if commit:
            booking.save()
            self.save_m2m()

        # Update next booking’s transport requirement
        next_booking = Booking.objects.filter(
            vehicle=vehicle_for_check, start_date__gt=booking.end_date
        ).order_by('start_date').first()

        if next_booking:
            next_booking.needs_transport = (booking.end_location != next_booking.start_location)
            next_booking.save(update_fields=['needs_transport'])

        return booking

    def clean_start_date(self):
        start_date = self.cleaned_data.get('start_date')

        if self.instance and self.instance.pk and self.instance.status == 'pending_final_km':
            return start_date

        tomorrow = timezone.now().date() + timedelta(days=1)

        if start_date and start_date < tomorrow:
            raise ValidationError(
                _("Booking date cannot be today or in the past. "
                  "Please select tomorrow or a future date."),
                code='invalid_start_date_past'
            )

        if start_date and start_date.weekday() >= 5:
            raise ValidationError(
                _("Bookings cannot start on a weekend. "
                  "Please select a business day."),
                code='invalid_start_date_weekend'
            )
        return start_date


class UpdateUserForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['email', 'first_name', 'last_name', 'phone_number', 'groups', 'language']
        widgets = {'groups': BootstrapCheckboxSelectMultiple}

    def clean_email(self):
        email = self.cleaned_data['email']
        if User.objects.filter(email__iexact=email).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError(_("A user with that email already exists."))
        return email


class UserCreateForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'phone_number', 'groups']
        widgets = {'groups': forms.CheckboxSelectMultiple}

    def save(self, commit=True):
        user = super().save(commit=False)
        user.is_active = True
        user.set_unusable_password()
        if commit:
            user.save()
            self.save_m2m()
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
        fields = [
            'license_plate', 'vehicle_type', 'model', 'is_electric', 'viaverde_id', 'chassis',
            'picture', 'current_location', 'insurance_document', 'registration_document',
            'next_maintenance_date', 'vehicle_km'
        ]
        widgets = {'next_maintenance_date': forms.DateInput(attrs={'type': 'date'})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_tag = False
        self.helper.layout = Layout(
            Row(Column('license_plate', css_class='form-group col-md-6 mb-3'),
                Column('model', css_class='form-group col-md-6 mb-3')),
            Row(Column('chassis', css_class='form-group col-md-6 mb-3'),
                Column('viaverde_id', css_class='form-group col-md-6 mb-3')),
            Row(Column('vehicle_type', css_class='form-group col-md-6 mb-3'),
                Column('current_location', css_class='form-group col-md-6 mb-3')),
            Row(Column('vehicle_km', css_class='form-group col-md-6 mb-3'),
                Column('next_maintenance_date', css_class='form-group col-md-6 mb-3')),
            'is_electric', 'picture', 'registration_document', 'insurance_document'
        )

class VehicleImportForm(forms.Form):
    csv_file = forms.FileField(
        label=_("Upload CSV File"),
        help_text=_("The file must be in CSV format with the correct headers.")
    )

class VehicleEditForm(VehicleCreateForm):
    class Meta(VehicleCreateForm.Meta):
        widgets = {
            'picture': forms.FileInput(),
            'next_maintenance_date': forms.DateInput(attrs={'type': 'date'}),
        }


class LocationCreateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name']


class LocationUpdateForm(forms.ModelForm):
    class Meta:
        model = Location
        fields = ['name']


class GroupForm(forms.ModelForm):
    users = forms.ModelMultipleChoiceField(
        queryset=User.objects.all().order_by('username'),
        widget=forms.CheckboxSelectMultiple,
        required=False, label=_("Group Members")
    )

    class Meta:
        model = Group
        fields = ['name']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['users'].initial = self.instance.user_set.all()

    def save(self, commit=True):
        group = super().save(commit=commit)
        if group.pk:
            group.user_set.set(self.cleaned_data['users'])
        return group


class EmailTemplateForm(forms.ModelForm):
    class Meta:
        model = EmailTemplate
        fields = [
            'name', 'event_trigger', 'subject', 'body', 'is_active',
            'send_to_salesperson', 'send_to_groups', 'send_to_users',
            'send_to_distribution_lists'
        ]
        widgets = {
            'send_to_groups': forms.CheckboxSelectMultiple,
            'send_to_users': forms.CheckboxSelectMultiple,
            'send_to_distribution_lists': forms.CheckboxSelectMultiple,
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk:
            self.fields['event_trigger'].widget.attrs['disabled'] = True
            self.fields['event_trigger'].help_text = _("The event trigger cannot be changed after creation.")


class DistributionListForm(forms.ModelForm):
    class Meta:
        model = DistributionList
        fields = ['name', 'emails']


class AutomationSettingsForm(forms.ModelForm):
    class Meta:
        model = AutomationSettings
        fields = [
            'pending_booking_automation_active', 'enable_pending_reminders',
            'reminder_days_pending', 'require_crc_verification'
        ]


class BookingFilterForm(forms.Form):
    status = forms.ChoiceField(
        required=False,
        label=_("Filter by Status"),
        widget=forms.Select(attrs={'class': 'form-select'})
    )

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user', None)
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [
            ('', _('All Actionable')), ('pending', _('Pending Approval')),
            ('pending_contract', _('Pending Contract')), ('confirmed', _('Confirmed / Upcoming')),
            ('completed', _('Completed')), ('cancelled', _('Cancelled')),
            ('pending_final_km', _('Pending Final KM')),
        ]

class ClientForm(forms.ModelForm):
    class Meta:
        model = Client
        fields = ['name', 'tax_number', 'address', 'email', 'phone_number']
        widgets = {
            'address': forms.Textarea(attrs={'rows': 3}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.helper = FormHelper()
        self.helper.form_method = 'post'
        # Add a submit button to the form's layout
        self.helper.layout = Layout(
            'name',
            'tax_number',
            'email',
            'phone_number',
            'address',
            Div(
                Submit('submit', _('Save Client'), css_class='btn btn-primary mt-3'),
                css_class='d-flex justify-content-end'
            )
        )