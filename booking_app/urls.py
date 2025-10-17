# C:\Users\f19705e\PycharmProjects\truck_booking_app\booking_app\urls.py

from django.urls import path
from . import views
from django.conf import settings
from django.conf.urls.static import static

app_name = 'booking_app'

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
    path('my-bookings/api/', views.my_bookings_api_view, name='my_bookings_api'),
    path('my-bookings/<int:booking_pk>/', views.booking_detail_view, name='booking_detail'),
    path('bookings/update/<int:booking_pk>/', views.update_booking_view, name='update_booking'),
    path('bookings/cancel/<int:booking_pk>/', views.cancel_booking_view, name='cancel_booking'),
    path('bookings/<int:booking_pk>/generate-word-contract/', views.generate_and_save_contract_view, name='generate_word_contract'),

    # User Profile Management URLs
    path('my-account/', views.my_account_view, name='my_account'),
    path('my-account/update-data/', views.update_user_data_view, name='update_user_data'),
    path('my-account/change-password/', views.change_password_view, name='change_password'),

    # Group Dashboard & Management URLs
    path('group-dashboard/', views.group_dashboard_view, name='group_dashboard'),
    path('group-bookings/<int:booking_pk>/', views.group_booking_detail_view, name='group_booking_detail'),
    path('group-bookings/update/<int:booking_pk>/', views.group_booking_update_view, name='group_booking_update'),
    path('group-dashboard/reports/', views.group_reports_view, name='group_reports'),
    path('group-dashboard/calendar/', views.group_calendar_view, name='group_calendar'),
    path('group-dashboard/client-history/<str:tax_number>/', views.client_booking_history_view, name='client_booking_history'),

    # Admin Dashboard & Management URLs
    path('admin-dashboard/', views.admin_dashboard_view, name='admin_dashboard'),

    # Admin User Management URLs
    path('admin-dashboard/users/', views.user_list_view, name='admin_user_list'),
    path('admin-dashboard/users/create/', views.user_create_view, name='admin_user_create'),
    path('admin-dashboard/users/edit/<uuid:pk>/', views.admin_user_edit_view, name='admin_user_edit'),
    path('admin-dashboard/users/<uuid:pk>/reset-password/', views.admin_user_reset_password_view, name='admin_user_reset_password'),
    path('admin-dashboard/users/<uuid:pk>/send-credentials/', views.send_credentials_view, name='admin_send_credentials'),
    path('admin-dashboard/users/<uuid:pk>/send-temporary-password/', views.send_temporary_password_view, name='admin_send_temp_password'),
    path('admin-dashboard/users/inactive/', views.inactive_user_list_view, name='admin_inactive_user_list'),
    path('admin-dashboard/users/<uuid:pk>/deactivate/', views.user_deactivate_view, name='admin_user_deactivate'),
    path('admin-dashboard/users/<uuid:pk>/reactivate/', views.user_reactivate_view, name='admin_user_reactivate'),
    path("admin-dashboard/users/<uuid:pk>/kill-sessions/", views.admin_kill_user_sessions, name="admin_kill_user_sessions"),
    path("admin-dashboard/users/kill-all-sessions/", views.admin_kill_all_sessions, name="admin_kill_all_sessions"),
    path("admin-dashboard/users/<uuid:pk>/sessions/", views.admin_user_sessions_view, name="admin_user_sessions"),

    # Admin Group Management
    path('admin-dashboard/groups/', views.group_list_view, name='admin_group_list'),
    path('admin-dashboard/groups/create/', views.group_create_view, name='admin_group_create'),
    path('admin-dashboard/groups/edit/<int:pk>/', views.group_edit_view, name='admin_group_edit'),
    path('admin-dashboard/groups/delete/<int:pk>/', views.group_delete_view, name='admin_group_delete'),

    # Admin Vehicle Management URLs
    path('admin-dashboard/vehicles/', views.admin_vehicle_list_view, name='admin_vehicle_list'),
    path('admin-dashboard/vehicles/create/', views.vehicle_create_view, name='admin_vehicle_create'),
    path('admin-dashboard/vehicles/download-template/', views.download_vehicle_template_view, name='download_vehicle_template'),
    path('admin-dashboard/vehicles/import/', views.import_vehicles_view, name='import_vehicles'),
    path('admin-dashboard/vehicles/<int:pk>/', views.admin_vehicle_detail_view, name='admin_vehicle_detail'),
    path('admin-dashboard/vehicles/<int:pk>/edit/', views.vehicle_edit_view, name='admin_vehicle_edit'),
    path('admin-dashboard/vehicles/<int:pk>/inactive/', views.vehicle_inactive_view, name='admin_vehicle_inactive'),

    # Admin Client Management URLs
    path('admin-dashboard/clients/', views.admin_client_list_view, name='admin_client_list'),
    path('admin-dashboard/clients/create/', views.admin_client_create_view, name='admin_client_create'),
    path('admin-dashboard/clients/update/<int:pk>/', views.admin_client_update_view, name='admin_client_update'),
    path('admin-dashboard/clients/delete/<int:pk>/', views.admin_client_delete_view, name='admin_client_delete'),

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
    path('admin-dashboard/email-logs/', views.email_log_list_view, name='admin_email_log_list'),
    # --- NEW: Admin Distribution List Management URLs ---
    path('admin-dashboard/distribution-lists/', views.admin_dl_list_view, name='admin_dl_list'),
    path('admin-dashboard/distribution-lists/create/', views.admin_dl_form_view, name='admin_dl_create'),
    path('admin-dashboard/distribution-lists/edit/<int:pk>/', views.admin_dl_form_view, name='admin_dl_edit'),
    path('admin-dashboard/distribution-lists/delete/<int:pk>/', views.admin_dl_delete_view, name='admin_dl_delete'),
    path('admin-dashboard/settings/', views.automation_settings_view, name='automation_settings'),
    path('admin-dashboard/contract-template/', views.contract_template_settings_view,
         name='contract_template_settings'),
    path('admin-dashboard/contract-template/preview/', views.contract_template_file_view,
         name='contract_template_file'),

    # API URLs
    path('api/bookings/', views.booking_api_view, name='booking_api'),
    path('api/check-client/', views.check_client_in_db_view, name='check_client_in_db'),
    path('api/get-company-details/', views.get_company_details_view, name='get_company_details'),
    path('api/validate-vat/', views.validate_vat_view, name='validate_vat'),
    path('api/get-vies-countries/', views.get_vies_countries_view, name='get_vies_countries'),
]

# Serve media and static files during development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)
