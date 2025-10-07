from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .utils import kill_user_sessions

User = get_user_model()

@receiver(post_save, sender=User)
def logout_inactive_users(sender, instance, **kwargs):
    if not instance.is_active:
        kill_user_sessions(instance)