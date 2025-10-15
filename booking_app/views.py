import csv
import io
import os
import platform
import re
import shutil
import subprocess
import json
import logging
import traceback
from io import BytesIO
from datetime import date, timedelta

import requests
from bs4 import BeautifulSoup
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, SetPasswordForm, PasswordChangeForm
from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db.models import Q, Prefetch, Count
from django.db.models.functions import TruncMonth
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.utils.translation import gettext as _
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth import get_user_model, login, logout, update_session_auth_hash
from django.contrib.auth.models import Group
from django.core.paginator import Paginator
from django.db import transaction
from django.http import HttpResponseForbidden, Http404, JsonResponse, HttpResponse, FileResponse
from django.template import Context, Template
from django.contrib.sites.shortcuts import get_current_site

from docxtpl import DocxTemplate
from PyPDF2 import PdfWriter

from .models import (
    Vehicle,
    Location,
    Booking,
    EmailTemplate,
    DistributionList,
    AutomationSettings,
    ContractTemplateSettings,
    EmailLog,
    Client,
    InactiveUser,
    Contract,
)
from .forms import (
    BookingForm, VehicleCreateForm, VehicleEditForm, LocationCreateForm,
    UserCreateForm, UpdateUserForm, ClientForm, GroupForm, DistributionListForm,
    EmailTemplateForm, LocationUpdateForm, AutomationSettingsForm, ContractTemplateSettingsForm,
    BookingFilterForm, VehicleImportForm
)
from .utils import (
    add_business_days, subtract_business_days, kill_user_sessions, kill_all_sessions,
    kill_session_by_key, get_user_sessions, get_last_activity_for_user, is_user_logged_in,
    send_system_notification
)

logger = logging.getLogger(__name__)

User = get_user_model()

# ------------------------------
# Permission Checks
# ------------------------------
def is_admin(user): return user.is_authenticated and user.is_admin_member


def is_booking_manager(user): return user.is_authenticated and user.is_booking_admin_member


def is_group_leader(user): return user.groups.filter(name__in=['tlheavy', 'tllight', 'tlapv', 'sd']).exists() or (
        user.is_authenticated and user.is_booking_admin_member)


def get_managed_vehicle_types(user):
    user_groups = user.groups.values_list('name', flat=True)
    vehicle_types = []
    if user.is_booking_admin_member:
        vehicle_types.extend(['LIGHT', 'HEAVY', 'APV'])
    else:
        if 'sd' in user_groups: vehicle_types.extend(['LIGHT', 'HEAVY'])
        if 'tlheavy' in user_groups: vehicle_types.append('HEAVY')
        if 'tllight' in user_groups: vehicle_types.append('LIGHT')
        if 'tlapv' in user_groups: vehicle_types.append('APV')
    return list(set(vehicle_types))

def resolve_placeholder_path(path, base_context):
    """Resolve dotted attribute paths against a context of objects/dicts."""
    if not path:
        return ''

    current = base_context
    for segment in path.split('.'):
        if isinstance(current, dict):
            current = current.get(segment)
        else:
            current = getattr(current, segment, None)

        if current is None:
            return ''

        if callable(current):
            try:
                current = current()
            except TypeError:
                return ''

    if current is None:
        return ''

    return current

# ------------------------------
# Core / Auth Views
# ------------------------------

def home(request):
    return render(request, 'home.html')


def login_user(request):
    """
    Simple username/password login using Django's AuthenticationForm.
    Respects the 'requires_password_change' flag.
    """
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()  # uses the authenticated user from the form
            login(request, user)

            # Force password change flow once per flag set
            if user.requires_password_change:
                user.requires_password_change = False
                user.save(update_fields=['requires_password_change'])
                messages.info(
                    request,
                    _("For your security, you must change your password before proceeding.")
                )
                return redirect("booking_app:change_password")

            messages.success(
                request,
                _("You are now logged in as %(username)s.") % {"username": user.username}
            )
            return redirect("booking_app:home")
        else:
            messages.error(request, _("Invalid username or password."))
    else:
        form = AuthenticationForm(request)

    return render(request, 'registration/login.html', {'form': form})


@login_required
def logout_user(request):
    logout(request)
    messages.info(request, _("You have successfully logged out."))
    return redirect("booking_app:home")



# ------------------------------
# Booking Views
# ------------------------------

@login_required
def book_vehicle_view(request, vehicle_pk):
    vehicle = get_object_or_404(Vehicle, pk=vehicle_pk)
    settings_obj = AutomationSettings.load()
    crc_is_mandatory = settings_obj.require_crc_verification
    if request.method == 'POST':
        form = BookingForm(request.POST, vehicle=vehicle, is_create_page=True, crc_is_mandatory=crc_is_mandatory)
        if form.is_valid():
            should_redirect, response = _handle_booking_form_submission(request, form, vehicle, is_new_booking=True)
            return response
        else:
            print("--- FORM IS INVALID ---")
            print(form.errors.as_json())
            print("-----------------------")
            messages.error(request, _('Form is not valid. Please check the errors.'))
    else:
        form = BookingForm(vehicle=vehicle, is_create_page=True, crc_is_mandatory=crc_is_mandatory)

    unavailable_statuses = ['pending', 'pending_contract', 'confirmed', 'pending_final_km']
    all_bookings = Booking.objects.filter(vehicle=vehicle, status__in=unavailable_statuses).order_by('start_date')
    unavailable_ranges = [
        {"start": subtract_business_days(b.start_date, 3).strftime('%Y-%m-%d'),
         "end": add_business_days(b.end_date, 3).strftime('%Y-%m-%d')}
        for b in all_bookings
    ]
    context = {
        'form': form,
        'vehicle': vehicle,
        'unavailable_ranges_json': json.dumps(unavailable_ranges),
        'crc_is_mandatory': crc_is_mandatory
    }
    return render(request, 'book_vehicle.html', context)


def _handle_booking_form_submission(request, form, vehicle, is_new_booking=True):
    try:
        resolution = form.cleaned_data.get('conflict_resolution')
        client_id = form.cleaned_data.get('client_id')
        form_data = {
            'name': form.cleaned_data['client_name'],
            'tax_number': form.cleaned_data['client_tax_number'],
            'address': form.cleaned_data.get('client_address'),
            'email': form.cleaned_data.get('client_email'),
            'phone_number': form.cleaned_data.get('client_phone'),
        }

        client = None

        if resolution:
            if resolution == 'update_existing':
                client = get_object_or_404(Client, pk=client_id)
                Client.objects.filter(pk=client_id).update(**form_data)
                client.refresh_from_db()
            elif resolution == 'create_new':
                client = Client.objects.create(**form_data)
            elif resolution == 'discard_changes':
                client = get_object_or_404(Client, pk=client_id)
        else:
            existing_clients = Client.objects.filter(tax_number=form_data['tax_number'])
            if not existing_clients.exists():
                client = Client.objects.create(**form_data)
            else:
                conflict_data = []
                client_to_silently_update = None
                for existing_client in existing_clients:
                    changes = {}
                    if form_data['name'] and form_data['name'] != existing_client.name:
                        changes['name'] = {'old': existing_client.name, 'new': form_data['name']}
                    if form_data['address'] and form_data['address'] != existing_client.address:
                        changes['address'] = {'old': existing_client.address, 'new': form_data['address']}
                    if form_data['email'] and form_data['email'] != existing_client.email:
                        changes['email'] = {'old': existing_client.email, 'new': form_data['email']}
                    if form_data['phone_number'] and form_data['phone_number'] != existing_client.phone_number:
                        changes['phone_number'] = {'old': existing_client.phone_number, 'new': form_data['phone_number']}

                    if not changes:
                        client = existing_client
                        break

                    is_only_filling_blanks = all(not v['old'] for v in changes.values() if v['old'] is not None)
                    if len(existing_clients) == 1 and is_only_filling_blanks:
                        client_to_silently_update = existing_client
                        break

                    conflict_data.append({'client': existing_client, 'changes': changes})

                if client_to_silently_update:
                    update_fields = {k: v for k, v in form_data.items() if v and not getattr(client_to_silently_update, k)}
                    if update_fields:
                        Client.objects.filter(pk=client_to_silently_update.pk).update(**update_fields)
                    client = client_to_silently_update
                    client.refresh_from_db()

                if not client and conflict_data:
                    context = {
                        'form': form, 'vehicle': vehicle, 'show_conflict_modal': True,
                        'conflict_data': conflict_data, 'form_data': form_data,
                        'unavailable_ranges_json': json.dumps([]),
                        'crc_is_mandatory': AutomationSettings.load().require_crc_verification
                    }
                    messages.warning(request, _("Please resolve the client data conflict below."))
                    return (False, render(request, 'book_vehicle.html', context))

        if client:
            # track previous state for updates
            prev_needs_transport = None
            if form.instance and form.instance.pk:
                prev_needs_transport = Booking.objects.only("needs_transport").get(pk=form.instance.pk).needs_transport

            booking = form.save(commit=False)
            if is_new_booking:
                booking.user = request.user
                booking.vehicle = vehicle
                booking.status = 'pending'

            booking.client = client

            # --- 🚚 Transport logic ---
            expected_vehicle_location = get_vehicle_location_for_date(vehicle, booking.start_date)
            s_loc = booking.start_location
            booking.needs_transport = bool(expected_vehicle_location and s_loc and expected_vehicle_location != s_loc)
            # -------------------------

            booking.save()
            form.save_m2m()

            # --- Notifications ---
            ctx = {
                "booking": booking,
                "vehicle": booking.vehicle,
                "user": request.user,
                "previous_needs_transport": prev_needs_transport,
                "current_needs_transport": booking.needs_transport,
                "previous_end_location":expected_vehicle_location,
            }

            if is_new_booking:
                if booking.vehicle.vehicle_type=='LIGHT':
                    send_system_notification('light_booking_created', context_data=ctx)
                elif booking.vehicle.vehicle_type=='HEAVY':
                    send_system_notification('heavy_booking_created', context_data=ctx)
                elif booking.vehicle.vehicle_type == 'APV':
                    send_system_notification('apv_booking_created', context_data=ctx)
                if booking.needs_transport:
                    send_system_notification('transport_required', context_data=ctx)
                messages.success(request, _('Your booking request has been submitted successfully!'))
                return (True, redirect('booking_app:my_bookings'))
            else:
                if prev_needs_transport is not None and prev_needs_transport != booking.needs_transport:
                    send_system_notification('transport_status_changed', context_data=ctx)
                messages.success(request, _('Booking has been updated successfully.'))
                redirect_url = reverse('booking_app:group_booking_update', kwargs={'booking_pk': form.instance.pk})
                return (True, redirect(redirect_url))
            # ---------------------

    except Exception as e:
        print("!!!!!!!!!! CAUGHT A CRITICAL ERROR IN SUBMISSION HANDLER !!!!!!!!!!!")
        traceback.print_exc()
        print("!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!")
        messages.error(request, f"A critical server error occurred: {e}")
        context = {'form': form, 'vehicle': vehicle}
        return (False, render(request, 'book_vehicle.html', context))

    messages.error(request, _("An unknown error occurred. Could not determine a client to save."))
    context = {'form': form, 'vehicle': vehicle}
    return (False, render(request, 'book_vehicle.html', context))

def get_vehicle_location_for_date(vehicle, date):
    """
    Determine where the vehicle will be on a given date.
    Uses the most recent confirmed/pending booking that overlaps or ends before the date.
    Falls back to vehicle.current_location if no bookings found.
    """
    # Find the latest booking that ends before this date (or overlaps it)
    last_booking = (
        Booking.objects.filter(vehicle=vehicle, status__in=['pending', 'confirmed', 'pending_final_km'])
        .filter(end_date__lte=date)
        .order_by('-end_date')
        .first()
    )

    if last_booking:
        return last_booking.end_location
    return vehicle.current_location


@login_required
def cancel_booking_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk, user=request.user)
    if booking.status in ['cancelled', 'completed']:
        messages.warning(request, _("This booking cannot be cancelled."))
        return redirect('booking_app:my_bookings')
    if request.method == 'POST':
        booking.status = 'cancelled'
        booking.cancelled_by = request.user
        booking.cancellation_time = timezone.now()
        booking.cancellation_reason = _("Cancelled by user.")
        booking.save()
        ctx = {
            "booking": booking,
            "vehicle": booking.vehicle,
            "user": request.user,
        }
        send_system_notification('booking_canceled_by_user', context_data=ctx)
        messages.success(request, _("Booking cancelled successfully."))
        return redirect('booking_app:my_bookings')
    return render(request, 'cancel_booking.html', {'booking': booking})

# ------------------------------
# Contract Views
# ------------------------------

@login_required
def generate_and_save_contract_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)
    contract = Contract.objects.create(booking=booking)

    template_settings = ContractTemplateSettings.load()
    template_dir = os.path.join(settings.BASE_DIR, 'document_templates')
    docx_template_path = template_settings.get_template_path()
    static_pdf_path = os.path.join(template_dir, 'terms_and_conditions.pdf')
    temp_dir = os.path.join(settings.MEDIA_ROOT, 'temp')
    os.makedirs(temp_dir, exist_ok=True)

    # --- Render DOCX ---
    doc = DocxTemplate(docx_template_path)
    context = {'booking': booking, 'contract': contract}
    base_context = {'booking': booking, 'contract': contract}
    for entry in template_settings.placeholder_map:
        handle = (entry.get('handle') or '').strip()
        path = (entry.get('path') or '').strip()
        if not handle or not path:
            continue

        value = resolve_placeholder_path(path, base_context)
        if value is None:
            value = ''
        elif not isinstance(value, (str, int, float)):
            value = str(value)

        context[handle] = value
    doc.render(context)

    temp_docx_path = os.path.join(temp_dir, f'temp_contract_{contract.pk}.docx')
    doc.save(temp_docx_path)

    try:
        soffice_path = shutil.which('soffice') or 'soffice'
        if platform.system() == 'Windows':
            soffice_path = r"C:\\Program Files\\LibreOffice\\program\\soffice.exe"
        subprocess.run(
            [soffice_path, '--headless', '--convert-to', 'pdf', temp_docx_path, '--outdir', temp_dir],
            check=True, timeout=15
        )
    except Exception as e:
        messages.error(request, f"{_('Could not convert document.')} ({e})")
        contract.delete()
        return redirect('booking_app:group_booking_detail', booking_pk=booking.pk)

    temp_pdf_path = os.path.join(temp_dir, f'temp_contract_{contract.pk}.pdf')
    merger = PdfWriter()
    pdf_buffer = BytesIO()
    try:
        merger.append(temp_pdf_path)
        merger.append(static_pdf_path)
        merger.write(pdf_buffer)
        pdf_buffer.seek(0)
    finally:
        merger.close()

    final_pdf_filename = f'contract_{contract.formatted_number}.pdf'
    contract.file.save(final_pdf_filename, ContentFile(pdf_buffer.getvalue()), save=True)

    for path in (temp_docx_path, temp_pdf_path):
        if os.path.exists(path):
            os.remove(path)

    ctx = {
        "booking": booking,
        "vehicle": booking.vehicle,
        "user": request.user,
    }

    send_system_notification('contract_generated', context_data=ctx)
    messages.success(request, _("Contract %(number)s has been generated.") % {"number": contract.formatted_number})
    return redirect('booking_app:group_booking_detail', booking_pk=booking.pk)


# ------------------------------
# Vehicle CRUD Views
# ------------------------------

@login_required
def vehicle_list_view(request, group_name=None):
    """
    Public-facing list of vehicles with filtering, sorting, and availability.
    Applies group-based restrictions for non-admins.
    """
    sort_by = request.GET.get('sort', 'license_plate')
    direction = request.GET.get('dir', 'asc')
    valid_sort_fields = ['license_plate', 'model', 'vehicle_type', 'current_location', 'next_available']
    if sort_by not in valid_sort_fields:
        sort_by = 'license_plate'

    today = date.today()

    vehicles_qs = Vehicle.objects.select_related('current_location').prefetch_related(
        Prefetch(
            'bookings',
            queryset=Booking.objects.filter(
                status__in=['pending', 'confirmed', 'pending_final_km'],
                end_date__gte=today
            ).order_by('start_date')
        )
    )

    all_groups = Group.objects.all().order_by('name')

    if not group_name and request.user.is_booking_admin_member:
        pass  # admins see all
    else:
        effective_group_for_filter = None
        if group_name:
            effective_group_for_filter = group_name.lower()
        else:
            for group in request.user.groups.all():
                gname = group.name.lower()
                if gname in ['light', 'tllight', 'heavy', 'tlheavy', 'apv', 'tlapv']:
                    effective_group_for_filter = gname
                    break

        if effective_group_for_filter in ['light', 'tllight']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='LIGHT')
        elif effective_group_for_filter in ['heavy', 'tlheavy']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='HEAVY')
        elif effective_group_for_filter in ['apv', 'tlapv']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='APV')

    order_by_field = 'current_location__name' if sort_by == 'current_location' else sort_by
    if direction == 'desc':
        order_by_field = f'-{order_by_field}'
    vehicles_qs = vehicles_qs.order_by(order_by_field)

    paginator = Paginator(vehicles_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    for vehicle in page_obj:
        vehicle.availability_slots = vehicle.get_availability_slots()
        vehicle.is_available_now = (
            vehicle.availability_slots and
            vehicle.availability_slots[0]['start'] <= (today + timedelta(days=1))
        )

    context = {
        'vehicles': page_obj,
        'all_groups': all_groups,
        'selected_group': group_name,
        'page_title': _("Vehicle Fleet"),
        'current_sort': sort_by,
        'current_dir': direction,
        'opposite_dir': 'desc' if direction == 'asc' else 'asc',
    }
    return render(request, 'vehicle_list.html', context)


@login_required
def vehicle_detail_view(request, pk):
    """
    Show details for a single vehicle including availability slots.
    """
    vehicle = get_object_or_404(Vehicle, pk=pk)
    availability_slots = vehicle.get_availability_slots()
    tomorrow = date.today() + timedelta(days=1)
    return render(
        request,
        'vehicle_detail.html',
        {
            'vehicle': vehicle,
            'availability_slots': availability_slots,
            'tomorrow': tomorrow,
            'page_title': _("Vehicle Details"),
        }
    )

@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def vehicle_create_view(request):
    if request.method == 'POST':
        form = VehicleCreateForm(request.POST, request.FILES)
        if form.is_valid():
            vehicle = form.save()
            ctx = {
                "vehicle": vehicle,
                "user": request.user,
            }
            send_system_notification('vehicle_created', context_data=ctx)
            messages.success(request, _("Vehicle created successfully!"))
            return redirect(reverse('booking_app:admin_vehicle_list'))
    else:
        form = VehicleCreateForm()
    return render(request, 'admin/admin_vehicle_create.html', {'form': form, 'page_title': _("Create New Vehicle")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def vehicle_edit_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == 'POST':
        form = VehicleEditForm(request.POST, request.FILES, instance=vehicle)
        if form.is_valid():
            vehicle = form.save()
            ctx = {
                "vehicle": vehicle,
                "user": request.user,
            }
            send_system_notification('vehicle_updated', context_data=ctx)
            messages.success(request, _("Vehicle updated successfully!"))
            return redirect('booking_app:admin_vehicle_list')
    else:
        form = VehicleEditForm(instance=vehicle)
    return render(request, 'admin/admin_vehicle_edit.html', {'form': form, 'vehicle': vehicle})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def vehicle_delete_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if vehicle.bookings.exists():
        messages.error(request, _(f"Vehicle '{vehicle.license_plate}' cannot be deleted because it has bookings."))
        return redirect('booking_app:admin_vehicle_list')

    if request.method == 'POST':
        vehicle.delete()
        ctx = {
            "vehicle": vehicle,
            "user": request.user,
        }
        send_system_notification('vehicle_deleted', context_data=ctx)
        messages.success(request, _(f"Vehicle '{vehicle.license_plate}' deleted successfully!"))
        return redirect('booking_app:admin_vehicle_list')

    return render(request, 'admin/admin_vehicle_delete.html', {'vehicle_obj': vehicle})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_vehicle_list_view(request):
    vehicles = Vehicle.objects.select_related('current_location').all().order_by('license_plate')
    paginator = Paginator(vehicles, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_vehicle_list.html', {'vehicles': page_obj, 'page_title': _("Manage Vehicles")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_vehicle_detail_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    availability_slots = vehicle.get_availability_slots()
    tomorrow = date.today() + timedelta(days=1)
    upcoming_bookings = vehicle.bookings.filter(end_date__gte=date.today()).select_related('user', 'client').order_by('start_date')

    context = {
        'vehicle': vehicle,
        'page_title': _("Admin Vehicle Details"),
        'upcoming_bookings': upcoming_bookings,
        'availability_slots': availability_slots,
        'tomorrow': tomorrow,
    }
    return render(request, 'admin/admin_vehicle_detail.html', context)

# ------------------------------
# Location CRUD Views
# ------------------------------

@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def location_create_view(request):
    if request.method == 'POST':
        form = LocationCreateForm(request.POST)
        if form.is_valid():
            location = form.save()
            ctx = {
                "location": location,
                "user": request.user,
            }
            send_system_notification('location_created', context_data=ctx)
            messages.success(request, _("Location created successfully!"))
            return redirect(reverse('booking_app:admin_location_list'))
    else:
        form = LocationCreateForm()
    return render(request, 'admin/admin_location_create.html', {'form': form, 'page_title': _("Create New Location")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def location_list_view(request):
    locations = Location.objects.all().order_by('name')
    paginator = Paginator(locations, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_location_list.html', {'locations': page_obj})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def location_edit_view(request, pk):
    location = get_object_or_404(Location, pk=pk)
    if request.method == 'POST':
        form = LocationUpdateForm(request.POST, instance=location)
        if form.is_valid():
            location = form.save()
            ctx = {
                "location": location,
                "user": request.user,
            }
            send_system_notification('location_updated', context_data=ctx)
            messages.success(request, _(f"Location '{location.name}' updated successfully!"))
            return redirect(reverse('booking_app:admin_location_list'))
    else:
        form = LocationUpdateForm(instance=location)
    return render(request, 'admin/admin_location_edit.html', {'form': form, 'location_obj': location})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def location_delete_view(request, pk):
    location = get_object_or_404(Location, pk=pk)
    if Booking.objects.filter(Q(start_location=location) | Q(end_location=location)).exists():
        messages.error(request, _(f"Location '{location.name}' cannot be deleted because it is used in bookings."))
        return redirect(reverse('booking_app:admin_location_list'))

    if request.method == 'POST':
        location.delete()
        ctx = {
            "location": location,
            "user": request.user,
        }
        send_system_notification('location_deleted', context_data=ctx)
        messages.success(request, _(f"Location '{location.name}' deleted successfully!"))
        return redirect('booking_app:admin_location_list')

    return render(request, 'admin/admin_location_confirm_delete.html', {'location': location})


# ------------------------------
# Client CRUD Views
# ------------------------------

@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_client_list_view(request):
    clients = Client.objects.all().order_by('name')
    paginator = Paginator(clients, 15)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_client_list.html', {'clients_page': page_obj, 'page_title': _("Manage Clients")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_client_create_view(request):
    if request.method == 'POST':
        form = ClientForm(request.POST)
        if form.is_valid():
            client = form.save()
            ctx = {
                "client": client,
                "user": request.user,
            }
            send_system_notification('client_created', context_data=ctx)
            messages.success(request, _("Client created successfully."))
            return redirect('booking_app:admin_client_list')
    else:
        form = ClientForm()
    return render(request, 'admin/admin_client_form.html', {'form': form, 'page_title': _("Create New Client")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_client_update_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if request.method == 'POST':
        form = ClientForm(request.POST, instance=client)
        if form.is_valid():
            client = form.save()
            ctx = {
                "client": client,
                "user": request.user,
            }
            send_system_notification('client_updated', context_data=ctx)
            messages.success(request, _("Client updated successfully."))
            return redirect('booking_app:admin_client_list')
    else:
        form = ClientForm(instance=client)
    return render(request, 'admin/admin_client_form.html', {'form': form, 'page_title': _(f"Edit Client: {client.name}")})


@login_required
@user_passes_test(lambda u: u.is_booking_admin_member, login_url='booking_app:login_user')
def admin_client_delete_view(request, pk):
    client = get_object_or_404(Client, pk=pk)
    if client.bookings.exists():
        messages.error(request, _("This client cannot be deleted because they have bookings."))
        return redirect('booking_app:admin_client_list')

    if request.method == 'POST':
        client.delete()
        ctx = {
            "client": client,
            "user": request.user,
        }
        send_system_notification('client_deleted', context_data=ctx)
        messages.success(request, _(f"Client '{client.name}' deleted successfully."))
        return redirect('booking_app:admin_client_list')

    return render(request, 'admin/admin_client_confirm_delete.html', {'client': client, 'page_title': _("Confirm Deletion")})


# ------------------------------
# Group CRUD Views
# ------------------------------

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_list_view(request):
    groups = Group.objects.all().order_by('name')
    paginator = Paginator(groups, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_group_list.html', {'groups': page_obj})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_create_view(request):
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            group = form.save()
            ctx = {
                "group": group,
                "user": request.user,
            }
            send_system_notification('group_created', context_data=ctx)
            messages.success(request, _("Group created successfully!"))
            return redirect('booking_app:admin_group_list')
    else:
        form = GroupForm()
    return render(request, 'admin/admin_group_form.html', {'form': form})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_edit_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=group)
        if form.is_valid():
            group = form.save()
            ctx = {
                "group": group,
                "user": request.user,
            }
            send_system_notification('group_updated', context_data=ctx)
            messages.success(request, _(f"Group '{group.name}' updated successfully!"))
            return redirect('booking_app:admin_group_list')
    else:
        form = GroupForm(instance=group)
    return render(request, 'admin/admin_group_form.html', {'form': form, 'group_obj': group})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_delete_view(request, pk):
    group = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        group.delete()
        ctx = {
            "group": group,
            "user": request.user,
        }
        send_system_notification('group_deleted', context_data=ctx)
        messages.success(request, _(f"Group '{group.name}' deleted successfully!"))
        return redirect('booking_app:admin_group_list')
    return render(request, 'admin/admin_group_delete.html', {'group_obj': group})

# ------------------------------
# User Management Views
# ------------------------------

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_create_view(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST)
        if form.is_valid():
            user = form.save()
            ctx = {
                "user": user,
            }
            send_system_notification('user_created', context_data=ctx)
            messages.success(request, _(f"User '{user.username}' created successfully."))
            return redirect(reverse('booking_app:admin_user_edit', kwargs={'pk': user.pk}))
    else:
        form = UserCreateForm()
    return render(request, 'admin/admin_user_create.html', {'form': form})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_list_view(request):
    users_qs = User.objects.filter(is_active=True).order_by('username')
    paginator = Paginator(users_qs, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    for user in page_obj:
        user.last_activity = get_last_activity_for_user(user)
        user.is_logged_in = is_user_logged_in(user)

    context = {"users": page_obj, "page_title": _("Manage Active Users")}
    return render(request, "admin/admin_user_list.html", context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def inactive_user_list_view(request):
    users = InactiveUser.objects.all().order_by('username')
    paginator = Paginator(users, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_inactive_user_list.html', {'users': page_obj, 'page_title': _("Manage Inactive Users")})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_deactivate_view(request, pk):
    user_to_deactivate = get_object_or_404(User, pk=pk)
    if user_to_deactivate == request.user:
        messages.error(request, _("You cannot deactivate your own account."))
        return redirect('booking_app:admin_user_list')

    if request.method == 'POST':
        user_to_deactivate.is_active = False
        user_to_deactivate.save(update_fields=['is_active'])
        ctx={
            "user": user_to_deactivate,
            "performed_by": request.user
        }
        send_system_notification('user_deactivated', context_data= ctx)
        messages.success(request, _(f"User '{user_to_deactivate.username}' has been deactivated."))
        return redirect('booking_app:admin_user_list')

    return render(request, 'admin/admin_user_confirm_deactivate.html', {'user_to_deactivate': user_to_deactivate})


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_reactivate_view(request, pk):
    user_to_reactivate = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        user_to_reactivate.is_active = True
        user_to_reactivate.save(update_fields=['is_active'])
        ctx = {
            "user": user_to_reactivate,
            "performed_by": request.user
        }
        send_system_notification('user_reactivated', context_data=ctx)
        messages.success(request, _(f"User '{user_to_reactivate.username}' has been reactivated."))
    return redirect('booking_app:admin_inactive_user_list')


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_user_edit_view(request, pk):
    user_to_edit = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = UpdateUserForm(request.POST, instance=user_to_edit)
        if form.is_valid():
            form.save()
            ctx={
                "user": user_to_edit,
                "performed_by": request.user,
            }
            send_system_notification('user_updated', context_data=ctx)
            messages.success(request, _(f"User '{user_to_edit.username}' updated successfully!"))
            return redirect(
                'booking_app:admin_user_list' if user_to_edit.is_active else 'booking_app:admin_inactive_user_list'
            )
    else:
        form = UpdateUserForm(instance=user_to_edit)
    return render(request, 'admin/admin_user_edit.html', {'form': form, 'user_to_edit': user_to_edit})


# ------------------------------
# User Session Management
# ------------------------------

@login_required
@user_passes_test(is_admin)
def admin_user_sessions_view(request, pk):
    user = get_object_or_404(User, pk=pk)
    sessions = get_user_sessions(user)
    return render(request, "admin/admin_user_sessions.html", {"user_to_edit": user, "sessions": sessions})


@login_required
@user_passes_test(is_admin)
def admin_kill_user_sessions(request, pk):
    user = get_object_or_404(User, pk=pk)
    kill_user_sessions(user)
    ctx = {
        "user": user,
        "performed_by": request.user,
    }
    send_system_notification('user_sessions_terminated', context_data=ctx)
    messages.success(request, f"All sessions for {user.username} were terminated.")
    return redirect("booking_app:admin_user_edit", pk=user.pk)


@login_required
@user_passes_test(is_admin)
def admin_kill_all_sessions(request):
    kill_all_sessions()
    ctx = {
        "performed_by": request.user,
    }
    send_system_notification('all_sessions_terminated', context_data=ctx)
    messages.success(request, "All user sessions were terminated.")
    return redirect("booking_app:admin_user_list")


@login_required
@user_passes_test(is_admin)
def admin_kill_session(request, pk, session_key):
    user = get_object_or_404(User, pk=pk)
    kill_session_by_key(session_key)
    ctx = {
        "user": user,
        "performed_by": request.user,
    }
    send_system_notification('user_session_terminated', context_data=ctx)
    messages.success(request, _("Session terminated."))
    return redirect("booking_app:admin_user_sessions", pk=user.pk)


# ------------------------------
# User Password / Credentials
# ------------------------------

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_user_reset_password_view(request, pk):
    user_to_reset = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        form = SetPasswordForm(user_to_reset, request.POST)
        if form.is_valid():
            form.save()
            user_to_reset.requires_password_change = True
            user_to_reset.save(update_fields=['requires_password_change'])
            send_system_notification(
                event_trigger='password_reset',
                context_data={'user': user_to_reset}
            )
            messages.success(request, _(f"Password for user '{user_to_reset.username}' has been reset successfully!"))
            return redirect('booking_app:admin_user_edit', pk=user_to_reset.pk)
    else:
        form = SetPasswordForm(user_to_reset)
    return render(
        request,
        'admin/admin_user_reset_password.html',
        {'form': form, 'user_to_reset': user_to_reset}
    )


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def send_credentials_view(request, pk):
    user_to_notify = get_object_or_404(User, pk=pk)
    domain = get_current_site(request).domain
    send_system_notification(
        event_trigger='send_user_credentials',
        context_data={'user': user_to_notify, 'domain': domain},
        test_email_recipient=user_to_notify.email
    )
    messages.success(request, _(f"Login credentials sent to {user_to_notify.email}."))
    return redirect('booking_app:admin_user_edit', pk=pk)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def send_temporary_password_view(request, pk):
    user_to_reset = get_object_or_404(User, pk=pk)
    temp_password = get_random_string(length=10)
    user_to_reset.set_password(temp_password)
    user_to_reset.requires_password_change = True
    user_to_reset.save()
    send_system_notification(
        event_trigger='send_temporary_password',
        context_data={'user': user_to_reset, 'temp_password': temp_password},
        test_email_recipient=user_to_reset.email
    )
    messages.success(request, _(f"A temporary password was sent to {user_to_reset.email}."))
    return redirect('booking_app:admin_user_edit', pk=pk)



# ------------------------------
# Email Template Management
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_email_template_list_view(request):
    templates = EmailTemplate.objects.all()
    return render(request, 'admin/admin_email_template_list.html', {'templates': templates})


@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_email_template_form_view(request, pk=None):
    template = get_object_or_404(EmailTemplate, pk=pk) if pk else None
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template)
        if form.is_valid():
            instance = form.save()
            #event = 'email_template_updated' if pk else 'email_template_created'
            #send_system_notification(event, template=instance, user=request.user)
            messages.success(request, _(f"Email template '{instance.name}' saved successfully!"))
            return redirect('booking_app:admin_email_template_list')
    else:
        form = EmailTemplateForm(instance=template)
    return render(request, 'admin/admin_email_template_form.html', {'form': form, 'template': template})


@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_email_template_test_view(request, pk):
    template = get_object_or_404(EmailTemplate, pk=pk)
    test_user = request.user
    test_vehicle = Vehicle.objects.order_by('-pk').first()
    test_location = Location.objects.order_by('-pk').first()
    if not test_vehicle or not test_location:
        messages.error(request, _("Cannot run test: vehicle and location required."))
        return redirect('booking_app:admin_email_template_list')

    mock_client = Client(name='Test Client Name', tax_number='999999999')
    mock_booking = Booking(
        pk=999, user=test_user, vehicle=test_vehicle,
        client=mock_client,
        start_date=date.today(), end_date=date.today() + timedelta(days=5),
        start_location=test_location, end_location=test_location, status='pending'
    )
    context_data = {
        'booking': mock_booking, 'user': test_user, 'vehicle': test_vehicle,
        'location': test_location, 'temp_password': 'test_password_123',
        'domain': request.get_host(),
    }
    try:
        send_system_notification(
            event_trigger=template.event_trigger,
            context_data=context_data,
            test_email_recipient=request.user.email
        )
        messages.success(request, _(f"Test email for '{template.name}' sent to {request.user.email}."))
    except Exception as e:
        messages.error(request, _(f"Failed to send test email for '{template.name}'. Error: {e}"))
    return redirect('booking_app:admin_email_template_list')


# ------------------------------
# Distribution Lists Management
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_dl_list_view(request):
    distribution_lists = DistributionList.objects.all()
    return render(request, 'admin/admin_dl_list.html', {'distribution_lists': distribution_lists})


@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_dl_form_view(request, pk=None):
    instance = get_object_or_404(DistributionList, pk=pk) if pk else None
    if request.method == 'POST':
        form = DistributionListForm(request.POST, instance=instance)
        if form.is_valid():
            dl = form.save()
            event = 'distribution_list_updated' if pk else 'distribution_list_created'
            ctx={
                "distribution_list": dl,
                "user": request.user,
            }
            send_system_notification(event, context_data=ctx)
            messages.success(request, _("Distribution list saved successfully!"))
            return redirect('booking_app:admin_dl_list')
    else:
        form = DistributionListForm(instance=instance)
    return render(request, 'admin/admin_dl_form.html', {'form': form, 'distribution_list': instance})


@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_dl_delete_view(request, pk):
    dl = get_object_or_404(DistributionList, pk=pk)
    if request.method == 'POST':
        dl.delete()
        ctx = {
            "distribution_list": dl,
            "user": request.user,
        }
        send_system_notification('distribution_list_deleted', context_data=ctx)
        messages.success(request, _("Distribution list deleted successfully!"))
        return redirect('booking_app:admin_dl_list')
    return render(request, 'admin/admin_dl_confirm_delete.html', {'distribution_list': dl})


# ------------------------------
# Automation Settings
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def automation_settings_view(request):
    settings_instance = AutomationSettings.load()
    if request.method == 'POST':
        form = AutomationSettingsForm(request.POST, instance=settings_instance)
        if form.is_valid():
            settings_instance = form.save()
            ctx={
                "settings": settings_instance,
                "user": request.user
            }
            send_system_notification('automation_settings_updated', context_data=ctx)
            messages.success(request, _("Automation settings updated successfully."))
            return redirect('booking_app:automation_settings')
    else:
        form = AutomationSettingsForm(instance=settings_instance)
    return render(request, 'admin/admin_automation_settings.html', {'form': form})

# ------------------------------
# Contract Generation
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def contract_template_settings_view(request):
    settings_instance = ContractTemplateSettings.load()

    placeholders = settings_instance.placeholder_map

    if request.method == 'POST':
        form = ContractTemplateSettingsForm(request.POST, request.FILES, instance=settings_instance)
        if form.is_valid():
            settings_instance = form.save()
            send_system_notification('contract_template_settings_updated', settings=settings_instance,
                                     user=request.user)
            messages.success(request, _("Contract template settings updated successfully."))
            return redirect('booking_app:contract_template_settings')
        else:
            try:
                placeholders = json.loads(request.POST.get('placeholders_json', '[]'))
            except json.JSONDecodeError:
                placeholders = settings_instance.placeholder_map
    else:
        form = ContractTemplateSettingsForm(instance=settings_instance)
        form.fields['placeholders_json'].initial = json.dumps(settings_instance.placeholder_map)
        form.fields['remove_template'].initial = 'false'
        form.fields['rendered_html'].initial = ''

    template_preview_url = reverse('booking_app:contract_template_file')
    default_template_preview_url = f"{template_preview_url}?default=1"

    return render(
        request,
        'admin/admin_contract_template_settings.html',
        {
            'form': form,
            'settings': settings_instance,
            'placeholders': placeholders,
            'template_preview_url': template_preview_url,
            'default_template_preview_url': default_template_preview_url,
            'page_title': _("Contract Template Settings"),
        },
    )

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def contract_template_file_view(request):
    settings_instance = ContractTemplateSettings.load()
    use_default = request.GET.get('default') == '1'
    if settings_instance.template and not use_default:
        template_path = settings_instance.template.path
    else:
        template_path = os.path.join(settings.BASE_DIR, 'document_templates', 'contract_template.docx')
    if not os.path.exists(template_path):
        raise Http404("Template file not found.")

    return FileResponse(
        open(template_path, 'rb'),
        content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    )


# ------------------------------
# Client Management
# ------------------------------

@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def client_booking_history_view(request, tax_number):
    clients = Client.objects.filter(tax_number=tax_number)
    if not clients.exists():
        raise Http404("No client found with this tax number.")
    client = clients.first()
    bookings = client.bookings.all().order_by('-start_date')
    return render(request, 'client_booking_history.html', {
        'client': client,
        'bookings': bookings,
        'page_title': _(f"Booking History for {client.name} (Tax ID: {tax_number})")
    })

# ------------------------------
# Client Check / External APIs
# ------------------------------

@login_required
def check_client_in_db_view(request):
    tax_number = request.GET.get('tax_number')
    if not tax_number:
        return JsonResponse({'error': 'Tax number is required.'}, status=400)

    clients = Client.objects.filter(tax_number__iexact=tax_number)
    if clients.exists():
        client_data = [
            {'id': c.id, 'name': c.name, 'address': c.address, 'email': c.email, 'phone_number': c.phone_number}
            for c in clients
        ]
        return JsonResponse({'clients': client_data})
    return JsonResponse({'error': 'Client not found in local database.'}, status=404)


@login_required
def get_company_details_view(request):
    crc = request.GET.get('crc')
    if not crc:
        return JsonResponse({'error': _('CRC code is required.')}, status=400)
    url = f"https://www2.gov.pt/RegistoOnline/Services/CertidaoPermanente/consultaCertidao.aspx?id={crc}"
    try:
        response = requests.get(url, headers={'User-Agent': 'Mozilla/5.0'}, timeout=10)
        if response.status_code == 200:
            if "Não existe qualquer certidão" in response.text:
                return JsonResponse({'error': _("Company not found or CRC is invalid.")}, status=404)
            soup = BeautifulSoup(response.text, 'html.parser')
            details_table = soup.find('table', class_='tabela_matricula')
            details_td = details_table.find_all('tr')[1].find('td')
            full_text = details_td.get_text(separator='\n', strip=True)
            lines = [line.strip() for line in full_text.split('\n')]
            company_data, address_parts, capture_address = {}, [], False
            for i, line in enumerate(lines):
                if line == 'NIPC:':
                    company_data['nif'] = lines[i + 1]
                elif line == 'Firma:':
                    company_data['company_name'] = lines[i + 1]
                elif line == 'Sede:':
                    address_parts.append(lines[i + 1]); capture_address = True
                elif capture_address:
                    if re.match(r'\d{4}\s*-\s*\d{3}', line):
                        address_parts.append(line); capture_address = False
                    elif ':' in line:
                        capture_address = False
            company_data['address'] = ' '.join(address_parts)
            return JsonResponse(company_data)
        return JsonResponse({'error': f'Server responded with {response.status_code}'}, status=500)
    except requests.exceptions.RequestException as e:
        return JsonResponse({'error': str(e)}, status=500)


@login_required
def get_vies_countries_view(request):
    try:
        response = requests.get("https://ec.europa.eu/taxation_customs/vies/rest-api/check-status", timeout=10)
        if response.ok:
            return JsonResponse(response.json().get('countries', []), safe=False)
    except requests.exceptions.RequestException:
        pass
    return JsonResponse([], safe=False)


@login_required
def validate_vat_view(request):
    vat_number = request.GET.get('vat_number')
    country_code = request.GET.get('country_code')
    if not all([vat_number, country_code]):
        return JsonResponse({'error': _('Country code and VAT number are required.')}, status=400)
    try:
        api_url = f"https://ec.europa.eu/taxation_customs/vies/rest-api/ms/{country_code}/vat/{vat_number}"
        response = requests.get(api_url, timeout=10)
        if response.status_code == 200:
            data = response.json()
            if data.get('isValid', False):
                return JsonResponse({'valid': True, 'company_name': data.get('name', ''), 'address': data.get('address', '')})
            return JsonResponse({'valid': False, 'error': _('Invalid VAT number.')}, status=404)
    except requests.exceptions.RequestException:
        return JsonResponse({'valid': False, 'error': _('Could not connect to VIES service.')}, status=503)


# ------------------------------
# API Views
# ------------------------------

@login_required
def my_bookings_api_view(request):
    user_bookings = Booking.objects.filter(
        user=request.user,
        status__in=['pending', 'pending_contract', 'confirmed', 'on_going', 'pending_final_km']
    ).select_related('vehicle', 'client')

    events = []
    for booking in user_bookings:
        client_name = booking.client.name if booking.client else _("N/A")
        events.append({
            'id': booking.pk,
            'text': f"{booking.vehicle.license_plate} - {client_name}",
            'start': booking.start_date.isoformat(),
            'end': (booking.end_date + timedelta(days=1)).isoformat(),
            'url': reverse('booking_app:booking_detail', kwargs={'booking_pk': booking.pk}),
            'backColor': {'LIGHT': '#3c78d8', 'HEAVY': '#cc0000', 'APV': '#6aa84f'}.get(booking.vehicle.vehicle_type, '#dddddd'),
        })
    return JsonResponse(events, safe=False)


@login_required
def booking_api_view(request):
    all_bookings = Booking.objects.filter(status__in=['pending', 'confirmed']).select_related('vehicle', 'client')
    event_list = []
    for booking in all_bookings:
        client_name = booking.client.name if booking.client else _("N/A")
        event_list.append({
            "id": booking.pk,
            "text": f"{booking.vehicle.license_plate} - {client_name}",
            "start": booking.start_date.isoformat(),
            "end": (booking.end_date + timedelta(days=1)).isoformat(),
        })
    return JsonResponse(event_list, safe=False)

# --- User's Personal Views ---

@login_required
def my_bookings_view(request):
    """
    Show all bookings made by the current logged-in user.
    """
    bookings = Booking.objects.filter(user=request.user).select_related('vehicle', 'client').order_by('-start_date')
    return render(request, 'my_bookings.html', {'bookings': bookings})


@login_required
def booking_detail_view(request, booking_pk):
    """
    Show details for a specific booking (only if owned by the user).
    """
    booking = get_object_or_404(Booking, pk=booking_pk, user=request.user)
    return render(request, 'booking_detail.html', {'booking': booking})


@login_required
def update_booking_view(request, booking_pk):
    """
    Update an existing booking (only if owned by user or group leader).
    """
    booking = get_object_or_404(Booking, pk=booking_pk)
    if request.user != booking.user and not request.user.is_group_leader:
        messages.error(request, _("You do not have permission to access this booking."))
        return redirect('booking_app:my_bookings')

    if request.method == 'POST':
        form = BookingForm(request.POST, request.FILES, instance=booking, vehicle=booking.vehicle)
        if form.is_valid():
            should_redirect, response = _handle_booking_form_submission(
                request, form, booking.vehicle, is_new_booking=False
            )
            return response
    else:
        form = BookingForm(instance=booking, vehicle=booking.vehicle)

    return render(request, 'update_booking.html', {'form': form, 'booking': booking})

@login_required
def my_account_view(request):
    """
    Show account details and latest 5 bookings.
    """
    bookings = Booking.objects.filter(user=request.user).order_by('-start_date')[:5]
    return render(request, 'my_account.html', {'user': request.user, 'bookings': bookings})


@login_required
def update_user_data_view(request):
    """
    Allow user to update their own profile data.
    """
    user = request.user
    if request.method == 'POST':
        form = UpdateUserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, _('Your personal data was successfully updated!'))
            return redirect('booking_app:my_account')
    else:
        form = UpdateUserForm(instance=user)
    return render(request, 'update_user_data.html', {'form': form, 'user': user})


@login_required
def change_password_view(request):
    """
    Allow user to change their password.
    """
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, _('Your password was successfully updated!'))
            return redirect('booking_app:my_account')
    else:
        form = PasswordChangeForm(request.user)

    return render(request, 'change_password.html', {'form': form})

# --- Group Dashboard Views ---
@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_dashboard_view(request):
    vehicle_types_to_manage = get_managed_vehicle_types(request.user)
    filter_form = BookingFilterForm(request.GET, user=request.user)
    selected_status = request.GET.get('status', '')

    base_query = Booking.objects.filter(
        vehicle__vehicle_type__in=vehicle_types_to_manage
    ).select_related('client', 'vehicle')

    if selected_status:
        actionable_bookings = base_query.filter(status=selected_status).order_by('-start_date')
    else:
        actionable_bookings = base_query.filter(
            status__in=['pending', 'pending_contract', 'confirmed'],
            end_date__gte=timezone.now().date()
        ).order_by('start_date')

    context = {
        'page_title': _("Group Dashboard"),
        'actionable_bookings': actionable_bookings,
        'filter_form': filter_form
    }
    return render(request, 'group_dashboard.html', context)


@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_booking_detail_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)
    user = request.user
    managed_vehicle_types = get_managed_vehicle_types(user)
    can_view_as_leader = booking.vehicle.vehicle_type in managed_vehicle_types

    if not (can_view_as_leader or user.is_booking_admin_member):
        messages.error(request, _("You do not have permission to view this group booking."))
        return redirect('booking_app:group_dashboard')

    context = {
        'booking': booking,
        'page_title': _("Group Booking Details")
    }
    return render(request, 'group_booking_detail.html', context)


@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_booking_update_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- APPROVE ---
        if action == 'approve':
            if booking.status == 'pending':
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])

                send_system_notification(
                    event_trigger='booking_approved',
                    context_data={"booking":booking}
                )
                messages.success(request, _("Booking has been approved."))
            return redirect('booking_app:group_booking_detail', booking_pk=booking.pk)

        # --- APPROVE APV ---
        elif action == 'approve_apv':
            if booking.vehicle.vehicle_type == 'APV' and booking.status == 'pending':
                booking.status = 'confirmed'
                booking.initial_km = booking.vehicle.vehicle_km
                booking.save(update_fields=['status', 'initial_km'])

                send_system_notification(
                    event_trigger='apv_booking_approved',
                    context_data={"booking":booking}
                )
                messages.success(request, _("APV booking has been approved."))
            return redirect('booking_app:group_booking_detail', booking_pk=booking.pk)

        # --- CONFIRM WITH CONTRACT ---
        elif action == 'confirm_with_contract':
            if booking.status == 'pending_contract' and booking.contract_document:
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])

                send_system_notification(
                    event_trigger='booking_approved',
                    context_data={"booking":booking}
                )
                messages.success(request, _("Booking has been finalized and confirmed."))
            else:
                messages.error(request, _("Contract must be uploaded before confirming."))
            return redirect('booking_app:group_booking_update', booking_pk=booking.pk)

        # --- CANCEL BY MANAGER ---
        elif action == 'cancel_by_manager':
            if booking.status in ['pending', 'pending_contract', 'confirmed']:
                booking.status = 'cancelled'
                booking.cancellation_reason = _("Cancelled by manager")
                booking.cancellation_time = timezone.now()
                booking.cancelled_by = request.user
                booking.save(update_fields=['status','cancellation_reason','cancellation_time','cancelled_by'])

                send_system_notification(
                    event_trigger='booking_canceled_by_manager',
                    context_data={"booking":booking}
                )
                messages.success(request, _("Booking has been cancelled."))
            return redirect('booking_app:group_dashboard')

        # --- REQUEST FINAL KM ---
        elif action == 'request_final_km':
            if booking.vehicle.vehicle_type == 'APV' and booking.status == 'confirmed':
                booking.status = 'pending_final_km'
                booking.save(update_fields=['status'])

                send_system_notification(
                    event_trigger='booking_ended_pending_km',
                    context_data={"booking":booking}
                )
                messages.info(request, _("Final KM request has been sent."))
            return redirect('booking_app:group_booking_detail', booking_pk=booking.pk)

        # --- DEFAULT: update form normally ---
        form = BookingForm(request.POST, request.FILES, instance=booking, vehicle=booking.vehicle)
        if form.is_valid():
            should_redirect, response = _handle_booking_form_submission(
                request, form, booking.vehicle, is_new_booking=False
            )
            return response

    else:
        form = BookingForm(instance=booking, vehicle=booking.vehicle)

    context = {
        'form': form,
        'booking': booking,
        'can_approve': booking.status == 'pending',
        'can_approve_apv': booking.status == 'pending' and booking.vehicle.vehicle_type == 'APV',
        'can_confirm_contract': booking.status == 'pending_contract' and booking.contract_document,
        'can_cancel_by_manager': booking.status in ['pending','pending_contract','confirmed'],
        'can_update_form_fields': booking.status in ['pending','pending_contract'],
        'can_request_final_km': booking.vehicle.vehicle_type == 'APV' and booking.status == 'confirmed',
        'is_apv_booking': booking.vehicle.vehicle_type == 'APV',
    }
    return render(request, 'group_booking_update.html', context)
# ------------------------------
# Admin Dashboard
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def admin_dashboard_view(request):
    recent_email_logs = EmailLog.objects.order_by('-sent_at')[:10]
    context = {
        'page_title': _("Admin Dashboard"),
        'recent_email_logs': recent_email_logs,
    }
    return render(request, 'admin/admin_dashboard.html', context)


# ------------------------------
# Vehicles: CSV Template + Import
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def download_vehicle_template_view(request):
    """
    Generates and serves a CSV template file for importing vehicles.
    """
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="vehicle_import_template.csv"'

    writer = csv.writer(response)
    # CSV headers
    writer.writerow([
        'license_plate', 'model', 'vehicle_type', 'chassis',
        'vehicle_km', 'viaverde_id', 'is_electric', 'current_location'
    ])
    # Example row
    writer.writerow([
        'AA-00-BB', 'Tesla Model 3', 'LIGHT', 'ABC123XYZ',
        '50000', '123456789', 'True', 'Main Warehouse'
    ])
    return response


@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def import_vehicles_view(request):
    if request.method == 'POST':
        form = VehicleImportForm(request.POST, request.FILES)
        if form.is_valid():
            csv_file = request.FILES['csv_file']

            if not csv_file.name.endswith('.csv'):
                messages.error(request, _("This is not a CSV file. Please upload a valid .csv file."))
                return redirect('booking_app:import_vehicles')

            try:
                with transaction.atomic():
                    decoded_file = csv_file.read().decode('utf-8')
                    io_string = io.StringIO(decoded_file)
                    reader = csv.DictReader(io_string)

                    vehicles_to_create = []
                    errors = []

                    for i, row in enumerate(reader, start=2):  # start=2 because of header
                        license_plate = row.get('license_plate')
                        if not license_plate:
                            errors.append(f"Row {i}: Missing license_plate.")
                            continue

                        vehicle_data = {
                            'license_plate': license_plate,
                            'model': row.get('model', 'N/A'),
                            'vehicle_type': (row.get('vehicle_type') or '').upper(),
                            'chassis': row.get('chassis') or '',
                            'vehicle_km': row.get('vehicle_km') or 0,
                            'viaverde_id': row.get('viaverde_id') or '',
                            'is_electric': (row.get('is_electric') or '').lower() in ['true', '1', 'yes'],
                        }

                        # Validate vehicle_type
                        valid_types = [choice[0] for choice in Vehicle.VEHICLE_TYPE_CHOICES]
                        if vehicle_data['vehicle_type'] not in valid_types:
                            errors.append(
                                f"Row {i}: Invalid vehicle_type '{vehicle_data['vehicle_type']}'. "
                                f"Must be one of {valid_types}."
                            )
                            continue

                        # Resolve location FK by name
                        location_name = row.get('current_location')
                        if location_name:
                            try:
                                vehicle_data['current_location'] = Location.objects.get(name__iexact=location_name)
                            except Location.DoesNotExist:
                                errors.append(f"Row {i}: Location '{location_name}' does not exist.")
                                continue

                        vehicles_to_create.append(Vehicle(**vehicle_data))

                    if errors:
                        raise ValidationError(errors)

                    Vehicle.objects.bulk_create(vehicles_to_create, ignore_conflicts=True)
                    messages.success(request, _(f"Successfully imported {len(vehicles_to_create)} vehicles."))
                    return redirect('booking_app:admin_vehicle_list')

            except ValidationError as e:
                for err in e.messages:
                    messages.error(request, err)
            except Exception as e:
                messages.error(request, _(f"An unexpected error occurred: {e}"))

            return redirect('booking_app:import_vehicles')
    else:
        form = VehicleImportForm()

    context = {
        'form': form,
        'page_title': _("Import Vehicles from CSV"),
    }
    return render(request, 'admin/import_vehicles.html', context)


# ------------------------------
# Group Reports & Calendar
# ------------------------------

@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_reports_view(request):
    vehicle_types_to_manage = get_managed_vehicle_types(request.user)
    twelve_months_ago = timezone.now().date() - timedelta(days=365)

    bookings_per_month = (
        Booking.objects
        .filter(
            vehicle__vehicle_type__in=vehicle_types_to_manage,
            start_date__gte=twelve_months_ago,
            status__in=['confirmed', 'completed', 'on_going', 'pending_final_km']
        )
        .annotate(month=TruncMonth('start_date'))
        .values('month')
        .annotate(count=Count('id'))
        .order_by('month')
    )

    bookings_chart_labels = [item['month'].strftime('%Y-%m') for item in bookings_per_month]
    bookings_chart_data = [item['count'] for item in bookings_per_month]

    vehicle_usage = (
        Booking.objects
        .filter(
            vehicle__vehicle_type__in=vehicle_types_to_manage,
            status__in=['confirmed', 'completed', 'on_going', 'pending_final_km']
        )
        .values('vehicle__license_plate')
        .annotate(count=Count('id'))
        .order_by('-count')
    )

    vehicle_chart_labels = [item['vehicle__license_plate'] for item in vehicle_usage[:10]]
    vehicle_chart_data = [item['count'] for item in vehicle_usage[:10]]

    context = {
        'page_title': _("Group Reports & Charts"),
        'bookings_chart_labels': json.dumps(bookings_chart_labels),
        'bookings_chart_data': json.dumps(bookings_chart_data),
        'vehicle_chart_labels': json.dumps(vehicle_chart_labels),
        'vehicle_chart_data': json.dumps(vehicle_chart_data),
        'vehicle_usage_table': vehicle_usage,
    }
    return render(request, 'group_reports.html', context)


@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_calendar_view(request):
    vehicle_types_to_manage = get_managed_vehicle_types(request.user)
    calendar_bookings = (
        Booking.objects
        .filter(
            vehicle__vehicle_type__in=vehicle_types_to_manage,
            status__in=['pending', 'pending_contract', 'confirmed', 'on_going', 'pending_final_km']
        )
        .select_related('vehicle', 'client')
    )

    unique_vehicles = {b.vehicle for b in calendar_bookings}
    colors = [
        '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4', '#46f0f0', '#f032e6', '#bcf60c',
        '#fabebe', '#008080', '#e6beff', '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1',
        '#000075', '#808080'
    ]
    license_plate_color_map = {
        v.license_plate: colors[i % len(colors)]
        for i, v in enumerate(sorted(unique_vehicles, key=lambda vv: vv.license_plate))
    }

    calendar_events = []
    for booking in calendar_bookings:
        client_name = booking.client.name if booking.client else "N/A"
        calendar_events.append({
            'id': booking.pk,
            'text': f"{booking.vehicle.license_plate} - {client_name}",
            'start': booking.start_date.isoformat(),
            'end': (booking.end_date + timedelta(days=1)).isoformat(),  # dayPilot-like end exclusive
            'url': reverse('booking_app:group_booking_detail', kwargs={'booking_pk': booking.pk}),
            'backColor': license_plate_color_map.get(booking.vehicle.license_plate, '#dddddd'),
        })

    context = {
        'page_title': _("Group Bookings Calendar"),
        'calendar_events': json.dumps(calendar_events),
        'color_legend': license_plate_color_map,
    }
    return render(request, 'group_calendar.html', context)


# ------------------------------
# Email Logs
# ------------------------------

@login_required
@user_passes_test(is_booking_manager, login_url='booking_app:login_user')
def email_log_list_view(request):
    log_list = EmailLog.objects.all().order_by('-sent_at')
    paginator = Paginator(log_list, 25)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    return render(request, 'admin/admin_email_log_list.html', {'page_obj': page_obj, 'page_title': _("Email Logs")})
