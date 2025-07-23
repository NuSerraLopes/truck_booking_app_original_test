# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\views.py
import json

from django.utils.crypto import get_random_string
from django.contrib.sites.shortcuts import get_current_site
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
from django.http import HttpResponseRedirect, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import login, authenticate, logout
from django.contrib import messages
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.forms import PasswordChangeForm
from django.contrib.auth import update_session_auth_hash
from django.utils import timezone
from django.utils.translation import gettext as _
from django.urls import reverse
from django.db.models import Q, Max, Count
from datetime import date, timedelta
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from .forms import UserCreateForm, VehicleCreateForm, LocationCreateForm, BookingForm, UpdateUserForm, \
    LocationUpdateForm, VehicleEditForm, GroupForm, EmailTemplateForm, DistributionListForm, AutomationSettingsForm, \
    BookingFilterForm
from .models import User, Vehicle, Location, Booking, EmailTemplate, DistributionList, AutomationSettings, EmailLog
from .utils import add_business_days, send_booking_notification, subtract_business_days
from django.db.models.functions import TruncMonth


def is_admin(user):
    return user.is_authenticated and user.is_admin_member

def is_group_leader(user):
    """Checks if a user is in any of the team leader groups."""
    return user.groups.filter(name__in=['tlheavy', 'tllight', 'tlapv', 'sd']).exists() or user.is_admin_member

def home(request):
    """
    Renders the home page of the application.
    """
    return render(request, 'home.html')


def login_user(request):
    """
    Handles user login and checks if a password change is required.
    """
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)

                # --- ADD THIS LOGIC ---
                # Check if a password change is required for this user.
                if user.requires_password_change:
                    # Set the flag back to False to prevent a loop
                    user.requires_password_change = False
                    user.save(update_fields=['requires_password_change'])

                    messages.info(request, _("For your security, you must change your password before proceeding."))
                    return redirect("booking_app:change_password")
                # --- END OF LOGIC ---

                messages.success(request, _(f"You are now logged in as {username}."))
                return redirect("booking_app:home")
            else:
                messages.error(request, _("Invalid username or password."))
        else:
            messages.error(request, _("Invalid username or password."))

    form = AuthenticationForm()
    return render(request, 'registration/login.html', {'form': form})


@login_required
def logout_user(request):
    """
    Handles user logout.
    """
    logout(request)
    messages.info(request, _("You have successfully logged out."))
    return redirect("booking_app:home")


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def vehicle_create_view(request):
    if request.method == 'POST':
        # --- DEBUGGING: Check if the file is in the request ---
        print("Request method is POST")
        print("request.FILES:", request.FILES)

        form = VehicleCreateForm(request.POST, request.FILES)

        if form.is_valid():
            print("Form is valid. Saving...")
            vehicle = form.save()
            # ... your email notification logic ...
            messages.success(request, _("Vehicle created successfully!"))
            return redirect(reverse('booking_app:admin_dashboard'))
        else:
            # --- DEBUGGING: Print the exact form errors to the console ---
            print("Form is NOT valid.")
            print("Form errors:", form.errors.as_json())

            messages.error(request, _("Error creating vehicle. Please check the form."))
    else:
        form = VehicleCreateForm()

    return render(request, 'admin/admin_vehicle_create.html', {'form': form, 'page_title': _("Create New Vehicle")})

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def vehicle_edit_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    if request.method == 'POST':
        form = VehicleEditForm(request.POST, request.FILES, instance=vehicle)
        if form.is_valid():
            form.save()
            send_booking_notification('vehicle_updated', context_data={'vehicle': vehicle})
            messages.success(request, _("Vehicle updated successfully!"))
            return redirect('booking_app:admin_vehicle_list')
    else:
        form = VehicleEditForm(instance=vehicle)
    context = {
        'form': form,
        'vehicle': vehicle,
    }
    return render(request, 'admin/admin_vehicle_edit.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def vehicle_delete_view(request, pk):
    vehicle_to_delete = get_object_or_404(Vehicle, pk=pk)
    if vehicle_to_delete.bookings.exists():
        messages.error(request, _(f"Vehicle '{vehicle_to_delete.license_plate}' cannot be deleted because it has associated bookings."))
        return redirect(reverse('booking_app:admin_vehicle_list'))
    if request.method == 'POST':
        send_booking_notification('vehicle_deleted', context_data={'vehicle': vehicle_to_delete})
        vehicle_to_delete.delete()
        messages.success(request, _(f"Vehicle '{vehicle_to_delete.license_plate}' deleted successfully!"))
        return redirect(reverse('booking_app:admin_vehicle_list'))
    else:
        context = {
            'vehicle_obj': vehicle_to_delete,
            'page_title': _(f"Confirm Delete Vehicle: {vehicle_to_delete.license_plate}")
        }
        return render(request, 'admin/admin_vehicle_delete.html', context)


@login_required
def vehicle_list_view(request, group_name=None):
    # This initial section for filtering by group remains the same
    vehicles_qs = Vehicle.objects.all()
    all_groups = Group.objects.all().order_by('name')
    effective_group_for_filter = None
    if group_name:
        effective_group_for_filter = group_name.lower()
    else:
        user_groups = request.user.groups.all()
        for group in user_groups:
            normalized_user_group_name = group.name.lower()
            if normalized_user_group_name in ['light', 'tllight', 'heavy', 'tlheavy']:
                effective_group_for_filter = normalized_user_group_name
                break
    if effective_group_for_filter:
        if effective_group_for_filter in ['light', 'tllight']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='LIGHT')
        elif effective_group_for_filter in ['heavy', 'tlheavy']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='HEAVY')

    vehicles_with_availability = []
    today = date.today()
    tomorrow = today + timedelta(days=1)

    for vehicle in vehicles_qs.order_by('vehicle_type', 'model', 'license_plate'):
        # Get all bookings that are not yet finished (includes ongoing and future)
        relevant_bookings = vehicle.bookings.filter(
            status__in=['pending', 'confirmed'],
            end_date__gte=today
        ).order_by('start_date')

        slots = []
        # Start by assuming the next availability begins tomorrow
        next_start = tomorrow

        if not relevant_bookings:
            # If no relevant bookings, it's available from tomorrow
            slots.append({'start': tomorrow, 'end': None})
        else:
            # Check if the first booking is already ongoing
            first_booking = relevant_bookings[0]
            if first_booking.start_date <= today:
                # If it's ongoing, the next availability is after it ends
                next_start = add_business_days(first_booking.end_date, 3)

            # Loop through all future bookings to find gaps
            for booking in relevant_bookings:
                gap_end = subtract_business_days(booking.start_date, 3)

                # If a valid gap exists between our last known start and this booking
                if next_start <= gap_end:
                    slots.append({'start': next_start, 'end': gap_end})

                # The next potential start is after this booking's buffer
                potential_next_start = add_business_days(booking.end_date, 3)
                if potential_next_start > next_start:
                    next_start = potential_next_start

            # Add the final, open-ended slot
            slots.append({'start': next_start, 'end': None})

        # To determine "Available Now" status, we check if the first slot can be booked tomorrow
        # The user defined "Available Now" as "can be booked for tomorrow"
        if slots and slots[0]['start'] <= tomorrow:
            vehicle.is_available_now = True
        else:
            vehicle.is_available_now = False

        vehicle.availability_slots = slots
        vehicles_with_availability.append(vehicle)

    context = {
        'vehicles': vehicles_with_availability,
        'all_groups': Group.objects.all().order_by('name'),
        'selected_group': group_name,
        'page_title': _("Vehicle List"),
    }
    return render(request, 'vehicle_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_vehicle_list_view(request):
    vehicles = Vehicle.objects.all()
    paginator = Paginator(vehicles, 10)
    page = request.GET.get('page')
    vehicles = paginator.get_page(page)
    context = {
        'vehicles': vehicles,
        'page_title': _("Manage Vehicles"),
    }
    return render(request, 'admin/admin_vehicle_list.html', context)

@login_required
def vehicle_detail_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    latest_booking_data = Booking.objects.filter(
        vehicle=vehicle,
        status__in=['pending', 'confirmed']
    ).aggregate(max_end_date=Max('end_date'))
    latest_end_date = latest_booking_data['max_end_date']
    next_available_date = None
    if latest_end_date:
        calculated_date = add_business_days(latest_end_date, 3)
        if calculated_date > date.today():
            next_available_date = calculated_date
    context = {
        'vehicle': vehicle,
        'next_available_date': next_available_date,
        'page_title': _("Vehicle Details")
    }
    return render(request, 'vehicle_detail.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_vehicle_detail_view(request, pk):
    vehicle = get_object_or_404(Vehicle, pk=pk)
    current_date = timezone.now().date()
    upcoming_bookings = vehicle.bookings.filter(
        end_date__gte=current_date
    ).order_by('start_date')
    for booking in upcoming_bookings:
        if booking.end_date:
            booking.next_available_date_display = add_business_days(booking.end_date, 3)
        else:
            booking.next_available_date_display = None
    context = {
        'vehicle': vehicle,
        'page_title': _("Vehicle Details"),
        'current_time': current_date,
        'upcoming_bookings': upcoming_bookings,
    }
    return render(request, 'admin/admin_vehicle_detail.html', context)

@login_required
def vehicle_api_view(request):
    """Provides vehicle data as JSON for DayPilot resources."""
    vehicles = Vehicle.objects.all()

    resource_list = [
        {"name": f"{v.license_plate} ({v.model})", "id": v.pk}
        for v in vehicles
    ]
    return JsonResponse(resource_list, safe=False)


@login_required
def book_vehicle_view(request, vehicle_pk):
    """
    Handles the creation of a new booking for a specific vehicle.
    This view now dynamically determines a vehicle's availability based on its type.
    """
    vehicle = get_object_or_404(Vehicle, pk=vehicle_pk)

    # --- UPDATED LOGIC: Determine unavailable statuses based on vehicle type ---
    if vehicle.vehicle_type == 'APV':
        # For APVs, a booking is unavailable if it's pending, confirmed, or awaiting final KMs.
        unavailable_statuses = ['pending', 'confirmed', 'pending_final_km']
    else:
        # For Light/Heavy vehicles, it's unavailable if pending, awaiting contract, or confirmed.
        unavailable_statuses = ['pending', 'pending_contract', 'confirmed']

    # --- The rest of the view now uses the dynamic 'unavailable_statuses' list ---

    # Determine the earliest possible start date for a new booking
    latest_booking_data = Booking.objects.filter(
        vehicle=vehicle,
        status__in=unavailable_statuses
    ).aggregate(max_end_date=Max('end_date'))

    latest_end_date = latest_booking_data['max_end_date']
    if latest_end_date:
        vehicle.available_after = add_business_days(latest_end_date, 3)
        if vehicle.available_after <= date.today():
            vehicle.available_after = None
    else:
        vehicle.available_after = None

    # Find the next upcoming booking to help the date-picker logic
    next_booking = Booking.objects.filter(
        vehicle=vehicle,
        status__in=unavailable_statuses,
        start_date__gt=date.today()
    ).order_by('start_date').first()

    # Get all relevant bookings to generate disabled date ranges for the calendar
    all_bookings = Booking.objects.filter(
        vehicle=vehicle,
        status__in=unavailable_statuses
    ).order_by('start_date')

    unavailable_ranges = [
        {
            "start": subtract_business_days(booking.start_date, 3).strftime('%Y-%m-%d'),
            "end": add_business_days(booking.end_date, 3).strftime('%Y-%m-%d')
        }
        for booking in all_bookings
    ]

    # --- Handle form submission ---
    if request.method == 'POST':
        form = BookingForm(request.POST, vehicle=vehicle, is_create_page=True)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.user = request.user
            booking.vehicle = vehicle
            booking.status = 'pending'
            booking.save()
            send_booking_notification('booking_created', booking_instance=booking)
            messages.success(request, _('Your booking request has been submitted successfully!'))
            return redirect('booking_app:my_bookings')
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = BookingForm(vehicle=vehicle, is_create_page=True)

    context = {
        'form': form,
        'vehicle': vehicle,
        'next_booking_start_date': next_booking.start_date if next_booking else None,
        'unavailable_ranges_json': json.dumps(unavailable_ranges),
    }
    return render(request, 'book_vehicle.html', context)



@login_required
def my_bookings_view(request):
    bookings = Booking.objects.filter(user=request.user).order_by('-start_date')
    context = {'bookings': bookings}
    return render(request, 'my_bookings.html', context)


@login_required
def update_booking_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)
    is_admin = getattr(request.user, 'is_admin_member', False)
    is_sd_group = request.user.groups.filter(name='sd').exists()
    is_tl_heavy_group = request.user.groups.filter(name='tlheavy').exists()
    is_tl_light_group = request.user.groups.filter(name='tllight').exists()
    is_tlapv_member = request.user.groups.filter(name='tlapv').exists()
    can_manage_booking_status = (
            is_admin or is_sd_group or
            (is_tl_heavy_group and booking.vehicle.vehicle_type == 'HEAVY') or
            (is_tl_light_group and booking.vehicle.vehicle_type == 'LIGHT')
    )

    is_apv_booking = booking.vehicle.vehicle_type == 'APV'

    can_approve_apv = is_apv_booking and booking.status == 'pending' and (is_admin or is_tlapv_member)
    can_request_final_km = is_apv_booking and booking.status == 'confirmed' and can_approve_apv
    can_complete_apv_booking = (
            is_apv_booking and
            booking.status == 'pending_final_km' and
            booking.final_km is not None and
            can_approve_apv
    )

    # Non-APV Permissions
    can_approve = not is_apv_booking and booking.status == 'pending' and can_manage_booking_status
    can_confirm_contract = not is_apv_booking and booking.status == 'pending_contract' and booking.contract_document and can_manage_booking_status

    # General Permissions
    can_cancel_by_manager = booking.status in ['pending', 'pending_contract', 'confirmed'] and can_manage_booking_status
    can_complete_booking = not is_apv_booking and booking.status == 'confirmed' and can_manage_booking_status
    can_update_form_fields = (
                                     request.user == booking.user or can_manage_booking_status
                             ) and booking.status not in ['confirmed', 'cancelled', 'completed']

    # --- Page Access Check ---
    if not (request.user == booking.user or can_manage_booking_status):
        messages.error(request, _("You do not have permission to access or manage this booking."))
        return redirect('booking_app:my_bookings')

    if request.method == 'POST':
        action = request.POST.get('action')

        # --- APV ACTIONS ---
        if action == 'request_final_km' and can_request_final_km:
            last_booking = Booking.objects.filter(
                vehicle=booking.vehicle, status='completed', final_km__isnull=False
            ).order_by('-end_date').first()

            if last_booking:
                booking.initial_km = last_booking.final_km
            else:
                booking.initial_km = 0
                messages.warning(request,
                                 _("This is the first trip for this APV. Initial KM set to 0. Please verify and update if necessary."))

            booking.status = 'pending_final_km'
            booking.save()
            messages.info(request,
                          _("Booking is now awaiting final kilometers. Please enter the final reading to complete."))
            return redirect(request.path_info)

        elif action == 'approve_apv' and can_approve_apv:
            booking.status = 'confirmed'
            booking.save()
            send_booking_notification('apv_booking_approved', booking_instance=booking)
            messages.success(request, _("APV Booking has been approved successfully."))
            return redirect(request.path_info)

        # --- NON-APV ACTIONS ---
        elif action == 'approve' and can_approve:
            booking.status = 'pending_contract'
            booking.save()
            send_booking_notification('booking_awaiting_contract', booking_instance=booking)
            messages.success(request, _(f"Booking {booking.pk} approved. Status is now 'Pending Contract'."))
            return redirect(request.path_info)

        elif action == 'confirm_with_contract' and can_confirm_contract:
            booking.status = 'confirmed'
            booking.save()
            send_booking_notification('booking_approved', booking_instance=booking)
            messages.success(request, _(f"Booking {booking.pk} has been confirmed with the uploaded contract."))
            return redirect('booking_app:my_group_bookings')

        # --- GENERAL ACTIONS ---
        elif action == 'cancel_by_manager' and can_cancel_by_manager:
            booking.status = 'cancelled'
            booking.cancelled_by = request.user
            booking.cancellation_time = timezone.now()
            booking.cancellation_reason = _("Cancelled by management.")
            booking.save()
            send_booking_notification('booking_canceled_by_manager', booking_instance=booking)
            messages.success(request, _(f"Booking {booking.pk} has been cancelled by management."))
            return redirect('booking_app:my_group_bookings')

        elif action == 'complete' and can_complete_booking:
            booking.status = 'completed'
            booking.save()
            send_booking_notification('booking_completed', booking_instance=booking)
            messages.success(request, _(f"Booking {booking.pk} has been marked as completed."))
            return redirect('booking_app:my_group_bookings')

        # --- FORM SUBMISSION (SAVE CHANGES) ---
        else:
            if can_update_form_fields:
                form = BookingForm(request.POST, request.FILES, instance=booking, vehicle=booking.vehicle)
                if form.is_valid():
                    updated_booking = form.save(commit=False)
                    # If completing an APV booking, set status to 'completed'
                    if can_complete_apv_booking:
                        updated_booking.status = 'completed'

                    updated_booking.save()
                    messages.success(request, _("Your booking has been updated successfully."))

                    if updated_booking.status == 'completed':
                        return redirect('booking_app:my_group_bookings')
                    return redirect(request.path_info)
                else:
                    messages.error(request, _("Error updating booking. Please check the form."))
            else:
                messages.error(request,
                               _("You do not have permission to update this booking's details or its status prevents it."))
                return redirect(request.path_info)
    else:
        form = BookingForm(instance=booking, vehicle=booking.vehicle)
        if not can_update_form_fields:
            for field in form.fields.values():
                field.widget.attrs['readonly'] = 'readonly'
                field.widget.attrs['disabled'] = 'disabled'

    context = {
        'form': form,
        'booking': booking,
        'is_apv_booking': is_apv_booking,
        'can_request_final_km': can_request_final_km,
        'can_approve': can_approve,
        'can_approve_apv': can_approve_apv,
        'can_confirm_contract': can_confirm_contract,
        'can_cancel_by_manager': can_cancel_by_manager,
        'can_complete_booking': can_complete_booking,
        'can_update_form_fields': can_update_form_fields,
    }
    return render(request, 'update_booking.html', context)


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
        send_booking_notification('booking_canceled_by_user', booking_instance=booking)
        messages.success(request, _("Booking cancelled successfully."))
        return redirect('booking_app:my_bookings')
    context = {'booking': booking}
    return render(request, 'cancel_booking.html', context)

@login_required
def my_group_bookings_view(request):
    user = request.user
    bookings = Booking.objects.select_related('user', 'vehicle', 'start_location', 'end_location').all()
    is_admin_user = getattr(user, 'is_admin_member', False)
    is_sd_group = user.groups.filter(name='sd').exists()
    is_tllight_group = user.groups.filter(name='tllight').exists()
    is_tlheavy_group = user.groups.filter(name='tlheavy').exists()
    if is_admin_user or is_sd_group:
        pass
    elif is_tllight_group:
        bookings = bookings.filter(vehicle__vehicle_type='LIGHT')
    elif is_tlheavy_group:
        bookings = bookings.filter(vehicle__vehicle_type='HEAVY')
    else:
        bookings = bookings.filter(user=user)
    bookings = bookings.order_by('-start_date')
    paginator = Paginator(bookings, 10)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)
    context = {
        'page_obj': page_obj,
        'page_title': _("Group Bookings Overview"),
    }
    return render(request, 'my_group_bookings.html', context)

@login_required
def booking_detail_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)
    if request.user != booking.user:
        messages.error(request, _("You do not have permission to view this booking."))
        return redirect('booking_app:my_bookings')
    context = {
        'booking': booking,
        'page_title': _("Booking Details")
    }
    return render(request, 'booking_detail.html', context)

@login_required
def group_booking_detail_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)
    user = request.user
    is_admin = getattr(user, 'is_admin_member', False)
    is_sd_group = user.groups.filter(name='sd').exists()
    is_tllight_group = user.groups.filter(name='tllight').exists()
    is_tlheavy_group = user.groups.filter(name='tlheavy').exists()
    can_view_in_group = (
        is_admin or is_sd_group or
        (is_tllight_group and booking.vehicle.vehicle_type == 'LIGHT') or
        (is_tlheavy_group and booking.vehicle.vehicle_type == 'HEAVY')
    )
    if not can_view_in_group:
        messages.error(request, _("You do not have permission to view this group booking."))
        return redirect('booking_app:my_group_bookings')
    can_approve = booking.status == 'pending' and can_view_in_group
    can_cancel_by_manager = booking.status in ['pending', 'confirmed'] and can_view_in_group
    context = {
        'booking': booking,
        'can_approve': can_approve,
        'can_cancel_by_manager': can_cancel_by_manager,
        'page_title': _("Group Booking Details")
    }
    return render(request, 'group_booking_detail.html', context)


@login_required
def booking_api_view(request):
    """Provides booking data as JSON for the DayPilot Month view."""

    # --- ADD THIS: Create a color map for vehicles ---
    vehicles = Vehicle.objects.all()
    colors = ["#6aa84f", "#3c78d8", "#f1c232", "#cc0000", "#674ea7", "#e69138", "#3d85c6"]
    vehicle_color_map = {
        vehicle.pk: colors[i % len(colors)] for i, vehicle in enumerate(vehicles)
    }

    all_bookings = Booking.objects.filter(status__in=['pending', 'confirmed'])
    event_list = []
    for booking in all_bookings:
        event_list.append({
            "id": booking.pk,
            "text": f"{booking.vehicle.license_plate} - {booking.customer_name}",
            "start": booking.start_date.isoformat(),
            "end": (booking.end_date + timedelta(days=1)).isoformat(),  # End date is exclusive
            "backColor": vehicle_color_map.get(booking.vehicle.pk)  # Assign color based on vehicle
        })
    return JsonResponse(event_list, safe=False)

@login_required
def my_bookings_api_view(request):
    """
    Provides booking data as a JSON feed for the current user's calendar.
    """
    user_bookings = Booking.objects.filter(
        user=request.user,
        status__in=['pending', 'pending_contract', 'confirmed', 'on_going', 'pending_final_km']
    )

    color_map = {
        'LIGHT': '#3c78d8',  # Blue
        'HEAVY': '#cc0000',  # Red
        'APV': '#6aa84f',  # Green
    }

    events = []
    for booking in user_bookings:
        events.append({
            'id': booking.pk,
            'text': f"{booking.vehicle.license_plate} - {booking.customer_name}",
            'start': booking.start_date.isoformat(),
            'end': (booking.end_date + timedelta(days=1)).isoformat(),
            'url': booking.get_absolute_url(),
            'backColor': color_map.get(booking.vehicle.vehicle_type, '#dddddd'),
        })

    return JsonResponse(events, safe=False)

@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_dashboard_view(request):
    user_groups = request.user.groups.values_list('name', flat=True)

    vehicle_types_to_manage = []
    if 'sd' in user_groups:
        vehicle_types_to_manage.extend(['LIGHT', 'HEAVY'])
    if 'tlheavy' in user_groups:
        vehicle_types_to_manage.append('HEAVY')
    if 'tllight' in user_groups:
        vehicle_types_to_manage.append('LIGHT')
    if 'tlapv' in user_groups:
        vehicle_types_to_manage.append('APV')
    vehicle_types_to_manage = list(set(vehicle_types_to_manage))

    # --- FILTERING LOGIC ---
    # Pass the user to the form to dynamically set choices
    filter_form = BookingFilterForm(request.GET, user=request.user)
    selected_status = request.GET.get('status', '')

    # Start with a base query for all bookings managed by this leader
    base_query = Booking.objects.filter(
        vehicle__vehicle_type__in=vehicle_types_to_manage
    )

    if selected_status:
        # If a specific status is selected, filter by it
        actionable_bookings = base_query.filter(status=selected_status).order_by('-start_date')
    else:
        # By default, show bookings that are "actionable" (pending or upcoming)
        actionable_bookings = base_query.filter(
            status__in=['pending', 'pending_contract', 'confirmed'],
            end_date__gte=timezone.now().date()
        ).order_by('start_date')

    context = {
        'page_title': _("Group Dashboard"),
        'actionable_bookings': actionable_bookings,
        'filter_form': filter_form,  # 👈 Pass the form to the template
    }
    return render(request, 'group_dashboard.html', context)


@login_required
@user_passes_test(is_group_leader, login_url='booking_app:home')
def group_reports_view(request):
    """
    Displays a page with charts and usage reports for group leaders.
    """
    user_groups = request.user.groups.values_list('name', flat=True)

    vehicle_types_to_manage = []
    if 'sd' in user_groups:
        vehicle_types_to_manage.extend(['LIGHT', 'HEAVY'])
    if 'tlheavy' in user_groups:
        vehicle_types_to_manage.append('HEAVY')
    if 'tllight' in user_groups:
        vehicle_types_to_manage.append('LIGHT')
    if 'tlapv' in user_groups:
        vehicle_types_to_manage.append('APV')
    vehicle_types_to_manage = list(set(vehicle_types_to_manage))

    # --- Chart 1: Bookings per Month (Last 12 Months) ---
    twelve_months_ago = timezone.now().date() - timedelta(days=365)
    bookings_per_month = Booking.objects.filter(
        vehicle__vehicle_type__in=vehicle_types_to_manage,
        start_date__gte=twelve_months_ago,
        status__in=['confirmed', 'completed', 'on_going', 'pending_final_km']
    ).annotate(month=TruncMonth('start_date')).values('month').annotate(count=Count('id')).order_by('month')

    bookings_chart_labels = [item['month'].strftime('%Y-%m') for item in bookings_per_month]
    bookings_chart_data = [item['count'] for item in bookings_per_month]

    # --- Chart 2: Most Frequently Booked Vehicles ---
    vehicle_usage = Booking.objects.filter(
        vehicle__vehicle_type__in=vehicle_types_to_manage,
        status__in=['confirmed', 'completed', 'on_going', 'pending_final_km']
    ).values('vehicle__license_plate').annotate(count=Count('id')).order_by('-count')

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
    """
    Displays a full-page DayPilot calendar for the user's group, with colors
    assigned per unique license plate.
    """
    user_groups = request.user.groups.values_list('name', flat=True)

    vehicle_types_to_manage = []
    if 'sd' in user_groups:
        vehicle_types_to_manage.extend(['LIGHT', 'HEAVY', 'APV'])
    if 'tlheavy' in user_groups:
        vehicle_types_to_manage.append('HEAVY')
    if 'tllight' in user_groups:
        vehicle_types_to_manage.append('LIGHT')
    if 'tlapv' in user_groups:
        vehicle_types_to_manage.append('APV')
    vehicle_types_to_manage = list(set(vehicle_types_to_manage))

    # --- Calendar Events ---
    calendar_bookings = Booking.objects.filter(
        vehicle__vehicle_type__in=vehicle_types_to_manage,
        status__in=['pending', 'pending_contract', 'confirmed', 'on_going', 'pending_final_km']
    ).select_related('vehicle')

    # --- DYNAMIC COLOR LOGIC ---
    # Get unique vehicles from the booking query
    unique_vehicles = {booking.vehicle for booking in calendar_bookings}

    # A palette of distinct colors
    colors = [
        '#e6194b', '#3cb44b', '#ffe119', '#4363d8', '#f58231', '#911eb4',
        '#46f0f0', '#f032e6', '#bcf60c', '#fabebe', '#008080', '#e6beff',
        '#9a6324', '#fffac8', '#800000', '#aaffc3', '#808000', '#ffd8b1',
        '#000075', '#808080'
    ]

    # Create a color map for each unique license plate
    license_plate_color_map = {
        vehicle.license_plate: colors[i % len(colors)]
        for i, vehicle in enumerate(sorted(unique_vehicles, key=lambda v: v.license_plate))
    }

    calendar_events = []
    for booking in calendar_bookings:
        calendar_events.append({
            'id': booking.pk,
            'text': f"{booking.vehicle.license_plate} - {booking.customer_name}",
            'start': booking.start_date.isoformat(),
            'end': (booking.end_date + timedelta(days=1)).isoformat(),
            'url': booking.get_absolute_url(),
            'backColor': license_plate_color_map.get(booking.vehicle.license_plate, '#dddddd'),
        })

    context = {
        'page_title': _("Group Bookings Calendar"),
        'calendar_events': json.dumps(calendar_events),
        'color_legend': license_plate_color_map,  # Pass the map to the template for the legend
    }
    return render(request, 'group_calendar.html', context)

@login_required
def my_account_view(request):
    bookings = Booking.objects.filter(user=request.user).order_by('-start_date')[:5]
    context = {
        'user': request.user,
        'bookings': bookings,
    }
    return render(request, 'my_account.html', context)


@login_required
def update_user_data_view(request):
    user = request.user
    if request.method == 'POST':
        form = UpdateUserForm(request.POST, instance=user)
        if form.is_valid():
            form.save()
            messages.success(request, _('Your personal data was successfully updated!'))
            return redirect('booking_app:my_account')
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = UpdateUserForm(instance=user)
    context = {
        'form': form,
        'user': user,
    }
    return render(request, 'update_user_data.html', context)


@login_required
def change_password_view(request):
    if request.method == 'POST':
        form = PasswordChangeForm(request.user, request.POST)
        if form.is_valid():
            user = form.save()
            update_session_auth_hash(request, user)
            messages.success(request, _('Your password was successfully updated!'))
            return redirect('booking_app:my_account')
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = PasswordChangeForm(request.user)
    context = {'form': form}
    return render(request, 'change_password.html', context)

# --- ADMIN-FACING VIEWS ---
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

            send_booking_notification('password_reset', context_data={'user': user_to_reset})
            messages.success(request, _(f"Password for user '{user_to_reset.username}' has been reset successfully!"))

            return redirect('booking_app:admin_user_edit', pk=user_to_reset.pk)
        else:
            messages.error(request, _("Error resetting password. Please check the form."))
    else:
        form = SetPasswordForm(user_to_reset)

    context = {
        'form': form,
        'user_to_reset': user_to_reset,
    }
    return render(request, 'admin/admin_user_reset_password.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_dashboard_view(request):
    context = {'page_title': _("Admin Dashboard")}
    return render(request, 'admin/admin_dashboard.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_create_view(request):
    if request.method == 'POST':
        # This line correctly passes the request to your form's __init__
        form = UserCreateForm(request.POST, request=request)
        if form.is_valid():
            # This line correctly passes the request to your form's save() method
            user = form.save(request=request)

            user.requires_password_change = True
            user.save(update_fields=['requires_password_change'])

            send_booking_notification('user_created', context_data={'user': user})
            return redirect(reverse('booking_app:admin_user_list'))
        else:
            messages.error(request, _("Error creating user. Please check the form for errors."))
    else:
        # This line is also correct for GET requests
        form = UserCreateForm(request=request)
    context = {
        'form': form,  # You are correctly passing the form instance here
        'page_title': _("Create New User")
    }
    # The magic will happen in this template file
    return render(request, 'admin/admin_user_create.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_list_view(request):
    users = User.objects.all().order_by('username')
    paginator = Paginator(users, 10)
    page = request.GET.get('page')
    users = paginator.get_page(page)
    context = {
        'users': users,
        'page_title': _("Manage Users")
    }
    return render(request, 'admin/admin_user_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_user_edit_view(request, pk):
    user_to_edit = get_object_or_404(User, pk=pk)
    if request.method == 'POST':
        # The 'request=request' argument has been removed here
        form = UpdateUserForm(request.POST, instance=user_to_edit)
        if form.is_valid():
            form.save()  # The save method no longer needs the request
            messages.success(request, _(f"User '{user_to_edit.username}' updated successfully!"))
            return redirect(reverse('booking_app:admin_user_list'))
        else:
            messages.error(request, _("Error updating user. Please check the form."))
    else:
        # The 'request=request' argument has been removed here as well
        form = UpdateUserForm(instance=user_to_edit)

    context = {
        'form': form,
        'page_title': _("Edit User"),
        'user_to_edit': user_to_edit,
    }
    return render(request, 'admin/admin_user_edit.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def send_credentials_view(request, pk):
    """
    Sends an email to the user with their username and a password reset link.
    """
    user_to_notify = get_object_or_404(User, pk=pk)

    # Get the current domain to build a full URL
    current_site = get_current_site(request)
    domain = current_site.domain

    # Use your existing email function to send the notification
    send_booking_notification(
        event_trigger='send_user_credentials',
        context_data={
            'user': user_to_notify,
            'domain': domain
        },
        test_email_recipient=user_to_notify.email  # Send directly to the user
    )

    messages.success(request, _(f"Login credentials have been sent to {user_to_notify.email}."))
    return redirect('booking_app:admin_user_edit', pk=pk)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def send_temporary_password_view(request, pk):
    """
    Generates a temporary password, sets it for the user, and emails it.
    Forces the user to change the password on their next login.
    """
    user_to_reset = get_object_or_404(User, pk=pk)

    # Generate a random, temporary password
    temp_password = User.objects.make_random_password(length=10)

    # Set the new password for the user
    user_to_reset.set_password(temp_password)

    # IMPORTANT: Flag the user to require a password change on next login
    user_to_reset.requires_password_change = True

    # Save the changes to the user object
    user_to_reset.save()

    # Use your existing email function to send the notification
    send_booking_notification(
        event_trigger='send_temporary_password',  # A new, specific trigger
        context_data={
            'user': user_to_reset,
            'temp_password': temp_password,
        },
        test_email_recipient=user_to_reset.email  # Send directly to the user
    )

    messages.success(request, _(f"A temporary password has been sent to {user_to_reset.email}."))
    return redirect('booking_app:admin_user_edit', pk=pk)@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def send_temporary_password_view(request, pk):
    """
    Generates a temporary password, sets it for the user, and emails it.
    Forces the user to change the password on their next login.
    """
    user_to_reset = get_object_or_404(User, pk=pk)

    # Generate a random, temporary password
    temp_password = get_random_string(length=10)

    # Set the new password for the user
    user_to_reset.set_password(temp_password)

    # IMPORTANT: Flag the user to require a password change on next login
    user_to_reset.requires_password_change = True

    # Save the changes to the user object
    user_to_reset.save()

    # Use your existing email function to send the notification
    send_booking_notification(
        event_trigger='send_temporary_password', # A new, specific trigger
        context_data={
            'user': user_to_reset,
            'temp_password': temp_password,
        },
        test_email_recipient=user_to_reset.email # Send directly to the user
    )

    messages.success(request, _(f"A temporary password has been sent to {user_to_reset.email}."))
    return redirect('booking_app:admin_user_edit', pk=pk)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def location_create_view(request):
    if request.method == 'POST':
        form = LocationCreateForm(request.POST)
        if form.is_valid():
            location = form.save()
            send_booking_notification('location_created', context_data={'location': location})
            messages.success(request, _("Location created successfully!"))
            return redirect(reverse('booking_app:admin_location_list'))
        else:
            messages.error(request, _("Error creating location. Please check the form."))
    else:
        form = LocationCreateForm()
    return render(request, 'admin/admin_location_create.html', {'form': form, 'page_title': _("Create New Location")})

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def location_list_view(request):
    locations = Location.objects.all().order_by('name')
    paginator = Paginator(locations, 10)
    page = request.GET.get('page')
    locations = paginator.get_page(page)
    context = {
        'locations': locations,
        'page_title': _("Manage Locations")
    }
    return render(request, 'admin/admin_location_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def location_edit_view(request, pk):
    location_to_edit = get_object_or_404(Location, pk=pk)
    if request.method == 'POST':
        form = LocationUpdateForm(request.POST, instance=location_to_edit)
        if form.is_valid():
            form.save()
            send_booking_notification('location_updated', context_data={'location': location_to_edit})
            messages.success(request, _(f"Location '{location_to_edit.name}' updated successfully!"))
            return redirect(reverse('booking_app:admin_location_list'))
        else:
            messages.error(request, _("Error updating location. Please correct the errors below."))
    else:
        form = LocationUpdateForm(instance=location_to_edit)
    context = {
        'form': form,
        'location_obj': location_to_edit,
        'page_title': _(f"Edit Location: {location_to_edit.name}")
    }
    return render(request, 'admin/admin_location_edit.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def location_delete_view(request, pk):
    location_to_delete = get_object_or_404(Location, pk=pk)
    is_used = Booking.objects.filter(
        Q(start_location=location_to_delete) | Q(end_location=location_to_delete)
    ).exists()
    if is_used:
        messages.error(request, _(f"Location '{location_to_delete.name}' cannot be deleted because it is used in existing bookings."))
        return redirect(reverse('booking_app:admin_location_list'))
    if request.method == 'POST':
        send_booking_notification('location_deleted', context_data={'location': location_to_delete})
        location_to_delete.delete()
        messages.success(request, _(f"Location '{location_to_delete.name}' deleted successfully!"))
        return redirect(reverse('booking_app:admin_location_list'))
    else:
        context = {
            'location': location_to_delete,
            'page_title': _(f"Confirm Delete Location: {location_to_delete.name}")
        }
        return render(request, 'admin/admin_location_confirm_delete.html', context)

# --- Admin Group Management Views ---
@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_list_view(request):
    groups = Group.objects.all().order_by('name')
    paginator = Paginator(groups, 10)
    page = request.GET.get('page')
    groups = paginator.get_page(page)
    context = {
        'groups': groups,
        'page_title': _("Manage Groups")
    }
    return render(request, 'admin/admin_group_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_create_view(request):
    if request.method == 'POST':
        form = GroupForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _("Group created successfully!"))
            return redirect(reverse('booking_app:admin_group_list'))
        else:
            messages.error(request, _("Error creating group. Please check the form."))
    else:
        form = GroupForm()
    context = {
        'form': form,
        'page_title': _("Create New Group")
    }
    return render(request, 'admin/admin_group_form.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_edit_view(request, pk):
    group_to_edit = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        form = GroupForm(request.POST, instance=group_to_edit)
        if form.is_valid():
            form.save()
            messages.success(request, _(f"Group '{group_to_edit.name}' updated successfully!"))
            return redirect(reverse('booking_app:admin_group_list'))
        else:
            messages.error(request, _("Error updating group. Please check the form."))
    else:
        form = GroupForm(instance=group_to_edit)
    context = {
        'form': form,
        'group_obj': group_to_edit,
        'page_title': _(f"Edit Group: {group_to_edit.name}")
    }
    return render(request, 'admin/admin_group_form.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_delete_view(request, pk):
    group_to_delete = get_object_or_404(Group, pk=pk)
    if request.method == 'POST':
        group_to_delete.delete()
        messages.success(request, _(f"Group '{group_to_delete.name}' deleted successfully!"))
        return redirect(reverse('booking_app:admin_group_list'))
    else:
        context = {
            'group_obj': group_to_delete,
            'page_title': _(f"Confirm Delete Group: {group_to_delete.name}")
        }
        return render(request, 'admin/admin_group_delete.html', context)

# --- Admin Email Templates ---
@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_email_template_list_view(request):
    templates = EmailTemplate.objects.all()
    context = {
        'templates': templates,
        'page_title': _("Manage Email Templates")
    }
    return render(request, 'admin/admin_email_template_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_email_template_form_view(request, pk=None):
    if pk:
        template = get_object_or_404(EmailTemplate, pk=pk)
        page_title = _(f"Edit Email Template: {template.name}")
    else:
        template = None
        page_title = _("Create New Email Template")
    if request.method == 'POST':
        form = EmailTemplateForm(request.POST, instance=template)
        if form.is_valid():
            instance = form.save()
            action = _("created") if template is None else _("updated")
            messages.success(request, _(f"Email template '{instance.name}' {action} successfully!"))
            return redirect('booking_app:admin_email_template_list')
        else:
            messages.error(request, _("Error processing template. Please check the form."))
    else:
        form = EmailTemplateForm(instance=template)
    context = {
        'form': form,
        'template': template,
        'page_title': page_title
    }
    return render(request, 'admin/admin_email_template_form.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_email_template_test_view(request, pk):
    """
    Sends a test version of an email template to the current user.
    """
    template = get_object_or_404(EmailTemplate, pk=pk)

    # Create mock context data to render the template
    # This simulates a real object that would be passed during an actual event
    mock_user = request.user
    mock_vehicle = Vehicle.objects.first() or {
        'model': 'Test Model S-Way', 'license_plate': 'XX-99-ZZ'
    }
    mock_location = Location.objects.first() or {'name': 'Test Location'}

    mock_context_data = {
        'booking': {
            'pk': 123,
            'customer_name': 'John Doe (Test Client)',
            'customer_email': 'client@example.com',
            'customer_phone': '+1234567890',
            'client_tax_number': '999999999',
            'client_company_registration': 'Test Company Reg.',
            'start_date': date.today(),
            'end_date': date.today() + timedelta(days=2),
            'start_location': mock_location,
            'end_location': mock_location,
            'user': mock_user,
            'vehicle': mock_vehicle,
        },
        'user': mock_user,
        'vehicle': mock_vehicle,
        'location': mock_location,
    }

    # Use the existing email sending logic
    # The recipient list will be overridden to only include the current user
    try:
        from .utils import send_booking_notification
        # Temporarily override the recipient logic to send only to the admin
        send_booking_notification(
            template.event_trigger,
            booking_instance=mock_context_data.get('booking'),
            context_data=mock_context_data,
            test_email_recipient=request.user.email
        )
        messages.success(request, _(f"Test email for '{template.name}' sent to {request.user.email}."))
    except Exception as e:
        messages.error(request, _(f"Failed to send test email. Error: {e}"))

    return HttpResponseRedirect(reverse('booking_app:admin_email_template_list'))

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def email_log_list_view(request):
    """
    Displays a paginated list of all email logs.
    """
    log_list = EmailLog.objects.all()
    paginator = Paginator(log_list, 25)  # Show 25 logs per page

    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    context = {
        'page_title': _("Email Sending Logs"),
        'page_obj': page_obj,
    }
    return render(request, 'admin/admin_email_log_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_dl_list_view(request):
    """
    Displays a list of all distribution lists.
    """
    distribution_lists = DistributionList.objects.all()
    context = {
        'distribution_lists': distribution_lists,
        'page_title': _("Manage Distribution Lists")
    }
    return render(request, 'admin/admin_dl_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_dl_form_view(request, pk=None):
    """
    Handles both creating and editing a distribution list.
    """
    if pk:
        instance = get_object_or_404(DistributionList, pk=pk)
        page_title = _("Edit Distribution List")
    else:
        instance = None
        page_title = _("Create Distribution List")

    if request.method == 'POST':
        form = DistributionListForm(request.POST, instance=instance)
        if form.is_valid():
            form.save()
            action = _("updated") if instance else _("created")
            messages.success(request, _(f"Distribution list has been {action} successfully!"))
            return redirect('booking_app:admin_dl_list')
        else:
            messages.error(request, _("Please correct the errors below."))
    else:
        form = DistributionListForm(instance=instance)

    context = {
        'form': form,
        'page_title': page_title
    }
    return render(request, 'admin/admin_dl_form.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_dl_delete_view(request, pk):
    """
    Handles the deletion of a distribution list.
    """
    distribution_list = get_object_or_404(DistributionList, pk=pk)
    if request.method == 'POST':
        distribution_list.delete()
        messages.success(request, _("Distribution list deleted successfully!"))
        return redirect('booking_app:admin_dl_list')

    context = {
        'distribution_list': distribution_list,
        'page_title': _("Confirm Delete Distribution List")
    }
    return render(request, 'admin/admin_dl_confirm_delete.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def automation_settings_view(request):
    settings_instance = AutomationSettings.load()
    if request.method == 'POST':
        form = AutomationSettingsForm(request.POST, instance=settings_instance)
        if form.is_valid():
            form.save()
            messages.success(request, _("Automation settings updated successfully."))
            return redirect('booking_app:automation_settings')
    else:
        form = AutomationSettingsForm(instance=settings_instance)

    context = {
        'form': form,
        'page_title': _("Automation Settings")
    }
    return render(request, 'admin/admin_automation_settings.html', context)