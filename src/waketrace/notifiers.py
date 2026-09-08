from __future__ import annotations

import json
import logging
from typing import Protocol

from .config import Settings
from .storage import SQLiteStore

logger = logging.getLogger(__name__)


class Notifier(Protocol):
    def send(self, title: str, body: str, *, message_id: str) -> bool: ...


class ConsoleNotifier:
    def send(self, title: str, body: str, *, message_id: str) -> bool:
        print(f"[{title}] {body} ({message_id})", flush=True)
        return True


class WebPushNotifier:
    def __init__(self, settings: Settings, store: SQLiteStore):
        self.settings = settings
        self.store = store

    def send(self, title: str, body: str, *, message_id: str) -> bool:
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            return False
        if not self.settings.vapid_private_key:
            return False

        payload = json.dumps(
            {
                "title": title,
                "body": body,
                "tag": "waketrace-message",
                "messageId": message_id,
            },
            ensure_ascii=False,
        )
        delivered = 0
        for subscription in self.store.subscriptions():
            endpoint = str(subscription.get("endpoint", ""))
            try:
                webpush(
                    subscription_info=subscription,
                    data=payload,
                    vapid_private_key=self.settings.vapid_private_key,
                    vapid_claims={"sub": self.settings.vapid_claims_email},
                    ttl=3600,
                )
                delivered += 1
            except WebPushException as exc:
                status = getattr(getattr(exc, "response", None), "status_code", None)
                if status in {404, 410} and endpoint:
                    self.store.remove_subscription(endpoint)
            except Exception as exc:  # noqa: BLE001 - 第三方推送客户端的异常类型并不统一
                logger.warning("web push failed with %s", type(exc).__name__)
        return delivered > 0
