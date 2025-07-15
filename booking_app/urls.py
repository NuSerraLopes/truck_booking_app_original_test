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
    path('my-bookings/<int:booking_pk>/', views.booking_detail_view, name='bookings_detail'),
    path('group_bookings/', views.my_group_bookings_view, name='my_group_bookings'),
    path('group_bookings/<int:booking_pk>/', views.group_booking_detail_view, name='group_bookings_detail'),
    path('bookings/update/<int:booking_pk>/', views.update_booking_view, name='update_booking'),
    path('bookings/cancel/<int:booking_pk>/', views.cancel_booking_view, name='cancel_booking'),

    # User Profile Management URLs
    path('my-account/', views.my_account_view, name='my_account'),
    path('my-account/update-data/', views.update_user_data_view, name='update_user_data'),
    path('my-account/change-password/', views.change_password_view, name='change_password'),

    # Admin Dashboard & Management URLs
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),

    # Admin User Management URLs
    path('admin-dashboard/users/', views.user_list_view, name='admin_user_list'),
    path('admin-dashboard/users/create/', views.user_create_view, name='admin_user_create'),
    path('admin-dashboard/users/edit/<uuid:pk>/', views.admin_user_edit_view, name='admin_user_edit'),
    path('admin-dashboard/users/<uuid:pk>/reset-password/', views.admin_user_reset_password_view, name='admin_user_reset_password'),

    # Admin Group Management
    path('admin-dashboard/groups/', views.group_list_view, name='admin_group_list'),
    path('admin-dashboard/groups/create/', views.group_create_view, name='admin_group_create'),
    path('admin-dashboard/groups/edit/<int:pk>/', views.group_edit_view, name='admin_group_edit'),
    path('admin-dashboard/groups/delete/<int:pk>/', views.group_delete_view, name='admin_group_delete'),

    # Admin Vehicle Management URLs
    path('admin-dashboard/vehicles/', views.admin_vehicle_list_view, name='admin_vehicle_list'),
    path('admin-dashboard/vehicles/create/', views.vehicle_create_view, name='admin_vehicle_create'),
    path('admin-dashboard/vehicles/<int:pk>/', views.admin_vehicle_detail_view, name='admin_vehicle_detail'),
    path('admin-dashboard/vehicles/<int:pk>/edit/', views.vehicle_edit_view, name='admin_vehicle_edit'),
    path('admin-dashboard/vehicles/<int:pk>/delete/', views.vehicle_delete_view, name='admin_vehicle_delete'),

    # Admin Location Management URLs
    path('admin-dashboard/locations/', views.location_list_view, name='admin_location_list'),
    path('admin-dashboard/locations/create/', views.location_create_view, name='admin_location_create'),
    path('admin-dashboard/locations/edit/<int:pk>/', views.location_edit_view, name='admin_location_edit'),
    path('admin-dashboard/locations/delete/<int:pk>/', views.location_delete_view, name='admin_location_delete'),

    # --- NEW: Admin Email Template Management URLs ---
    path('admin-dashboard/email-templates/', views.admin_email_template_list_view, name='admin_email_template_list'),
    path('admin-dashboard/email-templates/edit/<int:pk>/', views.admin_email_template_form_view, name='admin_email_template_edit'),
    path('admin-dashboard/email-templates/create/', views.admin_email_template_form_view, name='admin_email_template_create'),
    path('admin-dashboard/email-templates/test/<int:pk>/', views.admin_email_template_test_view, name='admin_email_template_test'),
    # --- NEW: Admin Distribution List Management URLs ---
    path('admin-dashboard/distribution-lists/', views.admin_dl_list_view, name='admin_dl_list'),
    path('admin-dashboard/distribution-lists/create/', views.admin_dl_form_view, name='admin_dl_create'),
    path('admin-dashboard/distribution-lists/edit/<int:pk>/', views.admin_dl_form_view, name='admin_dl_edit'),
    path('admin-dashboard/distribution-lists/delete/<int:pk>/', views.admin_dl_delete_view, name='admin_dl_delete'),
    path('admin-dashboard/settings/', views.automation_settings_view, name='automation_settings'),
]

# Serve media and static files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
