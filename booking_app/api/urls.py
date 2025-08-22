# In booking_app/api/urls.py

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create a router and register our viewsets with it.
router = DefaultRouter()
router.register(r'bookings', views.BookingViewSet, basename='booking')
router.register(r'vehicles', views.VehicleViewSet, basename='vehicle')
router.register(r'locations', views.LocationViewSet, basename='location')

# The API URLs are now determined automatically by the router.
urlpatterns = [
    path('', include(router.urls)),
]