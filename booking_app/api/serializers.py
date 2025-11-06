# In booking_app/api/serializers.py

from rest_framework import serializers
from booking_app.models import User, Vehicle, Booking, Location
from django.forms.models import model_to_dict
from django.db.models import Model, QuerySet, Manager
from decimal import Decimal
from datetime import datetime, date


class UserSerializer(serializers.ModelSerializer):
    """
    Serializer for the User model, exposing basic user information.
    """

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name']


class VehicleSerializer(serializers.ModelSerializer):
    """
    Serializer for the Vehicle model.
    """

    class Meta:
        model = Vehicle
        fields = [
            'id', 'license_plate', 'vehicle_type', 'model', 'is_electric',
            'chassis', 'vehicle_km', 'get_picture_url'
        ]
        read_only_fields = ['get_picture_url']


class LocationSerializer(serializers.ModelSerializer):
    """
    Serializer for the Location model.
    """

    class Meta:
        model = Location
        fields = ['id', 'name']


class BookingSerializer(serializers.ModelSerializer):
    """
    Serializer for the Booking model. Includes nested details for related models.
    """
    # Use nested serializers to show details of related objects, not just their IDs.
    user = UserSerializer(read_only=True)
    vehicle = VehicleSerializer(read_only=True)
    start_location = LocationSerializer(read_only=True)
    end_location = LocationSerializer(read_only=True)

    # Add the custom property to the serializer output
    current_status_display = serializers.CharField(read_only=True)

    class Meta:
        model = Booking
        # Define all the fields you want to expose in your API
        fields = [
            'id', 'user', 'vehicle', 'customer_name', 'customer_email',
            'customer_phone', 'customer_address', 'client_tax_number',
            'client_company_registration', 'start_date', 'end_date',
            'start_location', 'end_location', 'status', 'current_status_display',
            'motive', 'initial_km', 'final_km', 'needs_transport', 'created_at'
        ]
        # Make some fields read-only as they are set by the server
        read_only_fields = ['status', 'initial_km', 'created_at', 'needs_transport']

def safe_context(context):
    """
    Recursively make a context JSON-serializable for Celery.
    Converts Django models, QuerySets, Managers, and other non-serializable
    types into simple dicts, lists, or strings.
    """
    def make_serializable(value):
        if isinstance(value, Model):
            data = model_to_dict(value)
            # Include model name for reference
            data["_model"] = f"{value._meta.app_label}.{value._meta.model_name}"
            return data

        elif isinstance(value, (QuerySet, Manager)):
            return [make_serializable(v) for v in value.all()]

        elif isinstance(value, dict):
            return {k: make_serializable(v) for k, v in value.items()}

        elif isinstance(value, (list, tuple, set)):
            return [make_serializable(v) for v in value]

        elif isinstance(value, (datetime, date)):
            return value.isoformat()

        elif isinstance(value, Decimal):
            return float(value)

        elif hasattr(value, "__dict__") and not isinstance(value, type):
            # Fallback for custom objects
            return make_serializable(value.__dict__)

        else:
            return value

    return make_serializable(context)