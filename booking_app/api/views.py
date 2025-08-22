# In booking_app/api/views.py

from rest_framework import viewsets, permissions
from booking_app.models import Booking, Vehicle, Location
from .serializers import BookingSerializer, VehicleSerializer, LocationSerializer

class IsOwnerOrReadOnly(permissions.BasePermission):
    """
    Custom permission to only allow owners of an object to edit it.
    """
    def has_object_permission(self, request, view, obj):
        # Read permissions are allowed to any request,
        # so GET, HEAD or OPTIONS requests are always allowed.
        if request.method in permissions.SAFE_METHODS:
            return True
        # Write permissions are only allowed to the owner of the booking.
        return obj.user == request.user


class BookingViewSet(viewsets.ModelViewSet):
    """
    API endpoint that allows a user's bookings to be viewed or edited.
    """
    serializer_class = BookingSerializer
    # Users must be authenticated to access this endpoint.
    permission_classes = [permissions.IsAuthenticated, IsOwnerOrReadOnly]

    def get_queryset(self):
        """
        This view should return a list of all the bookings
        for the currently authenticated user.
        """
        return Booking.objects.filter(user=self.request.user)

    def perform_create(self, serializer):
        """
        Associate the booking with the logged-in user when creating a new booking.
        """
        serializer.save(user=self.request.user)


class VehicleViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows vehicles to be viewed.
    This is a read-only endpoint.
    """
    queryset = Vehicle.objects.all()
    serializer_class = VehicleSerializer
    permission_classes = [permissions.IsAuthenticated]


class LocationViewSet(viewsets.ReadOnlyModelViewSet):
    """
    API endpoint that allows locations to be viewed.
    This is a read-only endpoint.
    """
    queryset = Location.objects.all()
    serializer_class = LocationSerializer
    permission_classes = [permissions.IsAuthenticated]