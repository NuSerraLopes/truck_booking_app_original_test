# In booking_app/context_processors.py
from truck_booking_app import settings


def auth_extras(request):
    """
    Adds custom authentication-related variables to the template context.
    """
    # Start with a default value
    can_view_group_bookings = False

    # We can only check groups for an authenticated user
    if request.user.is_authenticated:
        # Assuming 'is_admin_member' is a custom property or method on your user model.
        # This checks for it safely.
        is_admin = getattr(request.user, 'is_admin_member', False)

        # If is_admin_member is a method, call it.
        if callable(is_admin):
            is_admin = is_admin()

        # Check if the user is an admin or in one of the specified groups
        if is_admin or request.user.groups.filter(name__in=['sd', 'tllight', 'tlheavy']).exists():
            can_view_group_bookings = True

    return {
        'can_view_group_bookings': can_view_group_bookings
    }

def site_info(request):
    """
    Makes site-wide variables from settings.py available to all templates.
    """
    return {
        'APP_VERSION': settings.APP_VERSION,
        'APP_UPDATE_DATE': settings.APP_UPDATE_DATE,
    }