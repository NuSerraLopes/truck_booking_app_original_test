# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\views.py
from django.core.paginator import Paginator, PageNotAnInteger, EmptyPage
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
from django.db.models import Q, Max, OuterRef, Subquery
import datetime
from datetime import date, timedelta
from django.contrib.auth.forms import SetPasswordForm
from django.contrib.auth.models import Group
from .forms import UserCreateForm, VehicleCreateForm, LocationCreateForm, BookingForm, UpdateUserForm, \
    LocationUpdateForm, VehicleEditForm, GroupForm, EmailTemplateForm
from .models import User, Vehicle, Location, Booking, EmailTemplate
from .utils import add_business_days, send_booking_notification


def is_admin(user):
    return user.is_authenticated and user.is_admin_member

def home(request):
    """
    Renders the home page of the application.
    """
    return render(request, 'home.html')


def login_user(request):
    """
    Handles user login.
    """
    if request.method == "POST":
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            username = form.cleaned_data.get('username')
            password = form.cleaned_data.get('password')
            user = authenticate(username=username, password=password)
            if user is not None:
                login(request, user)
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
        form = VehicleCreateForm(request.POST, request.FILES) # IMPORTANT: Add request.FILES for image uploads
        if form.is_valid():
            form.save()
            messages.success(request, _("Vehicle created successfully!"))
            return redirect(reverse('booking_app:admin_dashboard'))
        else:
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
            messages.success(request, _("Vehicle updated successfully!"))
            # Redirect back to the admin vehicle list
            return redirect('booking_app:admin_vehicle_list')
    else:
        # If it's a GET request, pre-populate the form with existing vehicle data
        form = VehicleEditForm(instance=vehicle)

    context = {
        'form': form,
        'vehicle': vehicle, # Pass the vehicle instance to the template if needed
    }
    return render(request, 'admin/admin_vehicle_edit.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def vehicle_delete_view(request, pk):
    vehicle_to_delete = get_object_or_404(Vehicle, pk=pk)

    # Optional: Check for related bookings before deleting
    # This prevents integrity errors. Adjust if you want cascading deletes (models.CASCADE)
    if vehicle_to_delete.bookings.exists():
        messages.error(request, _(f"Vehicle '{vehicle_to_delete.license_plate}' cannot be deleted because it has associated bookings."))
        return redirect(reverse('booking_app:admin_vehicle_list'))

    if request.method == 'POST':
        vehicle_to_delete.delete()
        messages.success(request, _(f"Vehicle '{vehicle_to_delete.license_plate}' deleted successfully!"))
        return redirect(reverse('booking_app:admin_vehicle_list'))
    else:
        # For GET request, show confirmation page
        context = {
            'vehicle_obj': vehicle_to_delete,
            'page_title': _(f"Confirm Delete Vehicle: {vehicle_to_delete.license_plate}")
        }
        return render(request, 'admin/admin_vehicle_delete.html', context)


@login_required
def vehicle_list_view(request, group_name=None):
    vehicles_qs = Vehicle.objects.all()  # Renamed to avoid confusion in the loop
    all_groups = Group.objects.all().order_by('name')

    effective_group_for_filter = None

    # Determine filter based on URL or user group
    if group_name:
        effective_group_for_filter = group_name.lower()
    else:
        user_groups = request.user.groups.all()
        for group in user_groups:
            normalized_user_group_name = group.name.lower()
            if normalized_user_group_name in ['light', 'tllight', 'heavy', 'tlheavy']:
                effective_group_for_filter = normalized_user_group_name
                break

    # Apply type filter
    if effective_group_for_filter:
        if effective_group_for_filter in ['light', 'tllight']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='LIGHT')
        elif effective_group_for_filter in ['heavy', 'tlheavy']:
            vehicles_qs = vehicles_qs.filter(vehicle_type='HEAVY')

    vehicles_with_dates = []
    for vehicle in vehicles_qs.order_by('vehicle_type', 'model', 'license_plate'):
        latest_booking_data = Booking.objects.filter(
            vehicle=vehicle,
            status__in=['pending', 'confirmed']
        ).aggregate(max_end_date=Max('end_date'))

        latest_end_date = latest_booking_data['max_end_date']

        calculated_date = None
        if latest_end_date:
            possible_next_date = add_business_days(latest_end_date, 3)
            if possible_next_date > date.today():
                calculated_date = possible_next_date

        vehicle.next_available_date = calculated_date
        vehicles_with_dates.append(vehicle)

    context = {
        'vehicles': vehicles_with_dates,
        'all_groups': all_groups,
        'selected_group': group_name,
        'page_title': _("Vehicle List") + (f" ({group_name})" if group_name else "")
    }
    return render(request, 'vehicle_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_vehicle_list_view(request):
    vehicles = Vehicle.objects.all()
    paginator = Paginator(vehicles, 10)
    page = request.GET.get('page')
    try:
        vehicles = paginator.page(page)
    except PageNotAnInteger:
        vehicles = paginator.page(1)
    except EmptyPage:
        vehicles = paginator.page(paginator.num_pages)

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
def book_vehicle_view(request, vehicle_pk):
    vehicle = get_object_or_404(Vehicle, pk=vehicle_pk)

    latest_booking_data = Booking.objects.filter(
        vehicle=vehicle,
        status__in=['pending', 'confirmed']
    ).aggregate(max_end_date=Max('end_date'))
    latest_end_date = latest_booking_data['max_end_date']

    if latest_end_date:
        vehicle.available_after = add_business_days(latest_end_date, 3)
        if vehicle.available_after <= date.today():
            vehicle.available_after = None
    else:
        vehicle.available_after = None

    if request.method == 'POST':
        form = BookingForm(request.POST, vehicle=vehicle)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.user = request.user
            booking.vehicle = vehicle
            booking.status = 'pending'
            booking.save()
            send_booking_notification(booking, 'booking_created')
            messages.success(request, _('Your booking request has been submitted successfully!'))
            return redirect('booking_app:my_bookings')
        else:
            messages.error(request, _('Please correct the errors below.'))
    else:
        form = BookingForm(vehicle=vehicle)

    context = {
        'form': form,
        'vehicle': vehicle,
    }
    return render(request, 'book_vehicle.html', context)


@login_required
def my_bookings_view(request):
    bookings = Booking.objects.filter(user=request.user).order_by('-start_date')
    context = {
        'bookings': bookings,
    }
    return render(request, 'my_bookings.html', context)


@login_required
def update_booking_view(request, booking_pk):
    booking = get_object_or_404(Booking, pk=booking_pk)

    is_admin = getattr(request.user, 'is_admin_member', False)
    is_sd_group = request.user.groups.filter(name='sd').exists()
    is_tl_heavy_group = request.user.groups.filter(name='tlheavy').exists()
    is_tl_light_group = request.user.groups.filter(name='tllight').exists()

    can_manage_booking_status = (
        is_admin or
        is_sd_group or
        (is_tl_heavy_group and booking.vehicle.vehicle_type == 'HEAVY') or
        (is_tl_light_group and booking.vehicle.vehicle_type == 'LIGHT')
    )

    can_approve = booking.status == 'pending' and can_manage_booking_status
    can_cancel_by_manager = booking.status in ['pending', 'confirmed'] and can_manage_booking_status

    can_update_form_fields = (
        request.user == booking.user and
        booking.status not in ['confirmed', 'cancelled', 'completed']
    )

    if not (request.user == booking.user or can_manage_booking_status):
        messages.error(request, _("You do not have permission to access or manage this booking."))
        return redirect('booking_app:my_bookings')

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'approve' and can_approve:
            booking.status = 'confirmed'
            booking.save()
            send_booking_notification(booking, 'booking_approved')
            messages.success(request, _(f"Booking {booking.pk} for {booking.vehicle.license_plate} has been approved."))
            return redirect('booking_app:my_group_bookings')

        elif action == 'cancel_by_manager' and can_cancel_by_manager:
            booking.status = 'cancelled'
            booking.save()
            send_booking_notification(booking, 'booking_canceled_by_manager')
            messages.success(request, _(f"Booking {booking.pk} for {booking.vehicle.license_plate} has been cancelled by management."))
            return redirect('booking_app:my_group_bookings')

        else:
            if can_update_form_fields:
                form = BookingForm(request.POST, instance=booking, vehicle=booking.vehicle)
                if form.is_valid():
                    form.save()
                    send_booking_notification(booking, 'booking_updated')
                    messages.success(request, _("Your booking has been updated successfully."))
                    return redirect('booking_app:my_bookings')
                else:
                    messages.error(request, _("Error updating booking. Please check the form."))
            else:
                messages.error(request, _("You do not have permission to update this booking's details or its status prevents it."))
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
        'can_approve': can_approve,
        'can_cancel_by_manager': can_cancel_by_manager,
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
        booking.save()
        messages.success(request, _("Booking cancelled successfully."))
        return redirect('booking_app:my_bookings')
    context = {
        'booking': booking,
    }
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
    """
    Displays the details of a specific booking for the user who created it.
    """
    booking = get_object_or_404(Booking, pk=booking_pk)

    # Simplified permission check: only the owner can view this page.
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
    """
    Displays booking details for managers with appropriate permissions.
    """
    booking = get_object_or_404(Booking, pk=booking_pk)
    user = request.user

    is_admin = getattr(user, 'is_admin_member', False)
    is_sd_group = user.groups.filter(name='sd').exists()
    is_tllight_group = user.groups.filter(name='tllight').exists()
    is_tlheavy_group = user.groups.filter(name='tlheavy').exists()

    # Check if the user has permission to view this booking in a group context
    can_view_in_group = (
        is_admin or
        is_sd_group or
        (is_tllight_group and booking.vehicle.vehicle_type == 'LIGHT') or
        (is_tlheavy_group and booking.vehicle.vehicle_type == 'HEAVY')
    )

    if not can_view_in_group:
        messages.error(request, _("You do not have permission to view this group booking."))
        return redirect('booking_app:my_group_bookings')

    # Determine if manager can take action
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

    context = {
        'form': form,
    }
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
    context = {
        'page_title': _("Admin Dashboard")
    }
    return render(request, 'admin/admin_dashboard.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def user_create_view(request):
    if request.method == 'POST':
        form = UserCreateForm(request.POST, request=request)
        if form.is_valid():
            form.save(request=request)
            return redirect(reverse('booking_app:admin_user_list'))
        else:
            messages.error(request, _("Error creating user. Please check the form for errors."))
    else:
        form = UserCreateForm(request=request)

    context = {
        'form': form,
        'page_title': _("Create New User")
    }
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
        form = UpdateUserForm(request.POST, instance=user_to_edit, request=request)
        if form.is_valid():
            form.save(commit=True)
            messages.success(request, _(f"User '{user_to_edit.username}' updated successfully!"))
            return redirect(reverse('booking_app:admin_user_list'))
        else:
            messages.error(request, _("Error updating user. Please check the form."))
    else:
        form = UpdateUserForm(instance=user_to_edit, request=request)

    context = {
        'form': form,
        'page_title': _("Edit User"),
        'user_to_edit': user_to_edit,
    }
    return render(request, 'admin/admin_user_edit.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def location_create_view(request):
    if request.method == 'POST':
        form = LocationCreateForm(request.POST)
        if form.is_valid():
            form.save()
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
    """
    Displays a list of all email templates for editing.
    """
    templates = EmailTemplate.objects.all()
    context = {
        'templates': templates,
        'page_title': _("Manage Email Templates")
    }
    return render(request, 'admin/admin_email_template_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_email_template_form_view(request, pk=None):
    """
    Handles both creating a new email template and editing an existing one.
    """
    if pk:
        # This is an edit request for an existing template.
        template = get_object_or_404(EmailTemplate, pk=pk)
        page_title = _(f"Edit Email Template: {template.name}")
    else:
        # This is a request to create a new template.
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
    # Use the generic form template for both create and edit
    return render(request, 'admin/admin_email_template_form.html', context)