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
    LocationUpdateForm, VehicleEditForm, GroupForm
from .models import User, Vehicle, Location, Booking
from .utils import add_business_days

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

    #
    # --- KEY CHANGE IS HERE ---
    #

    # 1. Fetch all vehicles and pre-calculate dates
    # You can make this more efficient if needed, but the logic is sound.
    vehicles_with_dates = []
    for vehicle in vehicles_qs.order_by('vehicle_type', 'model', 'license_plate'):
        latest_booking_data = Booking.objects.filter(
            vehicle=vehicle,
            status__in=['pending', 'confirmed']
        ).aggregate(max_end_date=Max('end_date'))

        latest_end_date = latest_booking_data['max_end_date']

        calculated_date = None  # Default to None
        if latest_end_date:
            possible_next_date = add_business_days(latest_end_date, 3)
            if possible_next_date > date.today():
                calculated_date = possible_next_date

        # 2. Attach the calculated date as a new property to the vehicle object
        vehicle.next_available_date = calculated_date
        vehicles_with_dates.append(vehicle)

    # 3. Pass the modified list of vehicle objects to the context
    context = {
        'vehicles': vehicles_with_dates,  # This list now contains vehicles with the .next_available_date attribute
        'all_groups': all_groups,
        'selected_group': group_name,
        # 'next_available_date' dictionary is no longer needed here
        'page_title': _("Vehicle List") + (f" ({group_name})" if group_name else "")
    }
    return render(request, 'vehicle_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_vehicle_list_view(request):
    vehicles = Vehicle.objects.all() # Get all vehicles, not just available ones for admin
    paginator = Paginator(vehicles, 10) # 10 vehicles per page
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

@login_required # This is for general user vehicle detail, showing availability
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

        if calculated_date <= date.today():
            next_available_date = None
        else:
            next_available_date = calculated_date #
    else:
        next_available_date = None

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
    current_date = timezone.now()

    # Get upcoming bookings for this vehicle (filtered for future bookings)
    # Order by start_time to ensure they are processed chronologically
    upcoming_bookings = vehicle.bookings.filter(
        end_date__gt=current_date
    ).order_by('start_date')

    # Iterate through upcoming bookings and calculate the 'next_available_date' for each
    for booking in upcoming_bookings:
        if booking.end_date:
            # Calculate the end of the current booking + 3 business days
            booking.next_available_date_display = add_business_days(booking.end_date, 3)
        else:
            booking.next_available_date_display = None # Handle cases where end_time might be missing

    context = {
        'vehicle': vehicle,
        'page_title': _("Vehicle Details"),
        'current_time': current_date,
        'upcoming_bookings': upcoming_bookings, # Pass the filtered and modified bookings to the template
    }
    return render(request, 'admin/admin_vehicle_detail.html', context)


@login_required
def book_vehicle_view(request, vehicle_pk):
    vehicle = get_object_or_404(Vehicle, pk=vehicle_pk)

    # --- START: Recalculate vehicle availability for booking form ---
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
    # --- END: Recalculate vehicle availability for booking form ---

    if request.method == 'POST':
        form = BookingForm(request.POST, vehicle=vehicle)
        if form.is_valid():
            booking = form.save(commit=False)
            booking.user = request.user
            booking.vehicle = vehicle
            booking.status = 'pending'

            booking.save()
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
    """
    Displays bookings made by the current user.
    """
    bookings = Booking.objects.filter(user=request.user).order_by('-start_date')
    context = {
        'bookings': bookings,
    }
    return render(request, 'my_bookings.html', context)


@login_required
def update_booking_view(request, booking_pk):
    """
    Allows the user to update their own booking.
    """
    booking = get_object_or_404(Booking, pk=booking_pk, user=request.user)

    if booking.status in ['confirmed', 'cancelled']:
        messages.warning(request, _("This booking cannot be updated as it is already confirmed or cancelled."))
        return redirect('booking_app:my_bookings')

    if request.method == 'POST':
        form = BookingForm(request.POST, instance=booking)
        if form.is_valid():
            form.save()
            messages.success(request, _("Booking updated successfully."))
            return redirect('booking_app:my_bookings')
        else:
            messages.error(request, _("Error updating booking. Please check the form."))
    else:
        form = BookingForm(instance=booking)
    context = {
        'form': form,
        'booking': booking,
    }
    return render(request, 'update_booking.html', context)


@login_required
def cancel_booking_view(request, booking_pk): # This function is present here
    """
    Allows the user to cancel their own booking.
    """
    booking = get_object_or_404(Booking, pk=booking_pk, user=request.user)

    if booking.status in ['cancelled', 'completed']:
        messages.warning(request, _("This booking cannot be cancelled."))
        return redirect('booking_app:my_bookings')

    if request.method == 'POST':
        if booking.status not in ['cancelled', 'completed'] and not booking.vehicle.is_available:
            # Assuming 'is_available' is a field on your Vehicle model.
            # If not, you might need to adjust how vehicle availability is tracked.
            booking.vehicle.is_available = True
            booking.vehicle.save()

        booking.status = 'cancelled'
        booking.save()
        messages.success(request, _("Booking cancelled successfully."))
        return redirect('booking_app:my_bookings')
    context = {
        'booking': booking,
    }
    return render(request, 'cancel_booking.html', context)


@login_required
def my_account_view(request):
    """
    Displays the user's account dashboard.
    """
    context = {
        'user': request.user,
    }
    return render(request, 'my_account.html', context)


@login_required
def update_user_data_view(request):
    """
    Allows the user to update their personal data (email, first name, last name).
    """
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
    """
    Allows the user to change their password.
    """
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
        'user': request.user,
    }
    return render(request, 'change_password.html', context)

# --- ADMIN-FACING PASSWORD RESET VIEW ---
@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_user_reset_password_view(request, pk):
    """Allows an admin to reset a specific user's password."""
    user_to_reset = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        form = SetPasswordForm(user_to_reset, request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, _(f"Password for user '{user_to_reset.username}' has been reset successfully!"))
            # Redirect back to the user edit page after successful reset
            return redirect('booking_app:user_edit', pk=user_to_reset.pk) # Changed to user_edit
        else:
            messages.error(request, _("Error resetting password. Please check the form."))
    else:
        form = SetPasswordForm(user_to_reset)

    context = {
        'form': form,
        'user_to_reset': user_to_reset,
    }
    return render(request, 'admin/admin_user_reset_password.html', context)

# --- Admin Views (existing and new) ---
@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_dashboard_view(request):
    context = {
        'page_title': _("Admin Dashboard")
    }
    return render(request, 'admin/admin_dashboard.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user') # Ensure only admin users can access
def user_create_view(request):
    if request.method == 'POST':
        # Pass request.POST data and the request object itself to the form
        form = UserCreateForm(request.POST, request=request)
        if form.is_valid():
            form.save(request=request) # The form's save method now handles password setting and messages.success
            # No need for messages.success(request, ...) here, as the form handles it.
            return redirect(reverse('booking_app:admin_user_list')) # Redirect to the user list on success
        else:
            # If form is not valid, add an error message
            messages.error(request, _("Error creating user. Please check the form for errors."))
    else:
        # For GET request, initialize an empty form, passing the request object
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
    try:
        users = paginator.page(page)
    except PageNotAnInteger:
        users = paginator.page(1)
    except EmptyPage:
        users = paginator.page(paginator.num_pages)

    context = {
        'users': users,
        'page_title': _("Manage Users")
    }
    return render(request, 'admin/admin_user_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def admin_user_edit_view(request, pk): # Assuming your view is named something like this
    user_to_edit = get_object_or_404(User, pk=pk)

    if request.method == 'POST':
        # Pass the instance of the user being edited AND the request to the form
        form = UpdateUserForm(request.POST, instance=user_to_edit, request=request)
        if form.is_valid():
            form.save(commit=True) # The form's save method handles groups
            messages.success(request, _(f"User '{user_to_edit.username}' updated successfully!"))
            return redirect(reverse('booking_app:admin_user_list'))
        else:
            messages.error(request, _("Error updating user. Please check the form."))
    else:
        # For GET request, pre-populate the form with existing user data
        form = UpdateUserForm(instance=user_to_edit, request=request)

    context = {
        'form': form,
        'page_title': _("Edit User"),
        'user_to_edit': user_to_edit, # Pass the user object for template title
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
            # Redirect to location list or admin dashboard after creation
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
    try:
        locations = paginator.page(page)
    except PageNotAnInteger:
        locations = paginator.page(1)
    except EmptyPage:
        locations = paginator.page(paginator.num_pages)

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
            return redirect(reverse('booking_app:admin_location_list')) # Redirect to location list after edit
        else:
            messages.error(request, _("Error updating location. Please correct the errors below."))
    else:
        form = LocationUpdateForm(instance=location_to_edit)

    context = {
        'form': form,
        'location_obj': location_to_edit, # Pass the location object to the template
        'page_title': _(f"Edit Location: {location_to_edit.name}")
    }
    return render(request, 'admin/admin_location_edit.html', context)

# --- Admin Group Management Views ---
@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_list_view(request):
    """
    Displays a list of all user groups for admin management.
    """
    groups = Group.objects.all().order_by('name')
    paginator = Paginator(groups, 10) # 10 groups per page
    page = request.GET.get('page')
    try:
        groups = paginator.page(page)
    except PageNotAnInteger:
        groups = paginator.page(1)
    except EmptyPage:
        groups = paginator.page(paginator.num_pages)

    context = {
        'groups': groups,
        'page_title': _("Manage Groups")
    }
    return render(request, 'admin/admin_group_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='booking_app:login_user')
def group_create_view(request):
    """
    Handles the creation of new user groups.
    """
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
    """
    Handles the editing of an existing user group.
    """
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
    """
    Handles the deletion of an existing user group after confirmation.
    """
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