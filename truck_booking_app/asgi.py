import os
from django.core.asgi import get_asgi_application
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.auth import AuthMiddlewareStack
import booking_app.routing

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "truck_booking_app.settings")

# Wrap Django’s ASGI app with Channels routing
application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": AuthMiddlewareStack(
        URLRouter(
            booking_app.routing.websocket_urlpatterns
        )
    ),
})