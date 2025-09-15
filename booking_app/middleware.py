from django.utils import translation
import os
import requests
from django.http import JsonResponse, HttpResponseForbidden
from django.utils.deprecation import MiddlewareMixin
from django.conf import settings

from booking_app.utils import is_license_valid


class UserLanguageMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            user_language = getattr(request.user, 'language', None)
            if user_language:
                translation.activate(user_language)

                request.session['_language'] = user_language

        response = self.get_response(request)
        return response

class LicenseCheckMiddleware:
    """
    Checks the license validity on each request using the centralized licensing client.
    """
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        # Allow access to the admin panel without a license check.
        # This allows an admin to log in to fix issues if the license expires.
        if request.path.startswith('/admin/'):
            return self.get_response(request)

        # Call the helper from our licensing_client.
        # This handles caching and API calls automatically.
        if not is_license_valid():
            return HttpResponseForbidden("<h1>License Invalid or Expired</h1>")

        # If the license is valid, continue to the view.
        response = self.get_response(request)
        return response