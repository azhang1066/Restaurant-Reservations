import os

from .base import BaseNotifier
from .ntfy import NtfyNotifier
from .pushover import PushoverNotifier

__all__ = ["BaseNotifier", "NtfyNotifier", "PushoverNotifier", "get_notifier"]


def get_notifier() -> BaseNotifier:
    provider = os.getenv("NOTIFY_PROVIDER", "ntfy").lower().strip()
    if provider == "pushover":
        return PushoverNotifier()
    return NtfyNotifier()
