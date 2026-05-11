import os

from .base import BaseNotifier
from .ntfy import NtfyNotifier
from .pushover import PushoverNotifier

__all__ = ["BaseNotifier", "NtfyNotifier", "PushoverNotifier", "get_notifier"]


def get_notifier(settings: dict = None) -> BaseNotifier:
    s = settings or {}
    provider = (s.get("NOTIFY_PROVIDER") or os.getenv("NOTIFY_PROVIDER", "ntfy")).lower().strip()
    if provider == "pushover":
        return PushoverNotifier(s)
    return NtfyNotifier(s)
