# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\urls.py

from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

app_name = 'booking_app' # Define app_name for namespacing

urlpatterns = [
    # Core Authentication & Home URLs
    path('', views.home, name='home'),
    path('login/', views.login_user, name='login_user'),
    path('logout/', views.logout_user, name='logout_user'),

    # Public/User-facing Vehicle & Booking URLs
    path('vehicles/', views.vehicle_list_view, name='vehicle_list'),
    path('vehicles/<int:pk>/', views.vehicle_detail_view, name='vehicle_detail'),
    path('vehicles/<int:vehicle_pk>/book/', views.book_vehicle_view, name='book_vehicle'),

    # User's Personal Booking Management URLs
    path('my-bookings/', views.my_bookings_view, name='my_bookings'),
    path('bookings/update/<int:booking_pk>/', views.update_booking_view, name='update_booking'),
    path('bookings/cancel/<int:booking_pk>/', views.cancel_booking_view, name='cancel_booking'),

    # User Profile Management URLs
    path('my-account/', views.my_account_view, name='my_account'),
    path('my-account/update-data/', views.update_user_data_view, name='update_user_data'),
    path('my-account/change-password/', views.change_password_view, name='change_password'),

    # Admin Dashboard & Management URLs (Requires staff/superuser permissions in views)
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),

    # Admin User Management URLs
    path('admin-dashboard/users/', views.user_list_view, name='admin_user_list'),
    path('admin-dashboard/users/create/', views.user_create_view, name='admin_user_create'),
    # User PK is UUID for your custom user model
    path('admin-dashboard/users/edit/<uuid:pk>/', views.admin_user_edit_view, name='admin_user_edit'),
    # Corrected PK type to UUID for password reset
    path('admin-dashboard/users/<uuid:pk>/reset-password/', views.admin_user_reset_password_view, name='admin_user_reset_password'),

    # Admin Group Management (THIS IS THE NEW SECTION YOU NEED TO VERIFY)
    path('admin-dashboard/groups/', views.group_list_view, name='admin_group_list'),
    path('admin-dashboard/groups/create/', views.group_create_view, name='admin_group_create'),
    path('admin-dashboard/groups/edit/<int:pk>/', views.group_edit_view, name='admin_group_edit'),
    path('admin-dashboard/groups/delete/<int:pk>/', views.group_delete_view, name='admin_group_delete'),

    # Admin Vehicle Management URLs
    path('admin-dashboard/vehicles/', views.admin_vehicle_list_view, name='admin_vehicle_list'),
    # Place 'create' before '<int:pk>' to ensure correct URL resolution
    path('admin-dashboard/vehicles/create/', views.vehicle_create_view, name='admin_vehicle_create'),
    path('admin-dashboard/vehicles/<int:pk>/', views.admin_vehicle_detail_view, name='admin_vehicle_detail'),
    path('admin-dashboard/vehicles/<int:pk>/edit/', views.vehicle_edit_view, name='admin_vehicle_edit'),
    path('admin-dashboard/vehicles/<int:pk>/delete/', views.vehicle_delete_view, name='admin_vehicle_delete'),

    # Admin Location Management URLs
    path('admin-dashboard/locations/', views.location_list_view, name='admin_location_list'),
    path('admin-dashboard/locations/create/', views.location_create_view, name='admin_location_create'),
    path('admin-dashboard/locations/edit/<int:pk>/', views.location_edit_view, name='admin_location_edit'),
    # Add location delete if needed:
    # path('admin-dashboard/locations/delete/<int:pk>/', views.location_delete_view, name='location_delete'),
]

# Serve media and static files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Typically, static files are served by Django's runserver automatically in DEBUG mode,
    # but explicit inclusion is harmless and ensures it.
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)