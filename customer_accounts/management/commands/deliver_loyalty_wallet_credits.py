import hashlib
import hmac
import json
import logging
from datetime import timedelta

import httpx
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from customer_accounts.models import LoyaltyCreditOutbox, LoyaltyTransaction

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Deliver pending loyalty wallet credits to finance-service."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        if not settings.FINANCE_LOYALTY_CREDIT_URL or not settings.FINANCE_LOYALTY_CREDIT_SECRET:
            raise CommandError("Finance loyalty credit callback URL and secret must be configured.")
        limit = options["limit"]
        if limit < 1 or limit > 1000:
            raise CommandError("--limit must be between 1 and 1000.")
        failures = 0
        for _ in range(limit):
            event = self._claim_event()
            if event is None:
                break
            try:
                self._deliver(event)
            except (httpx.RequestError, ValueError) as exc:
                failures += 1
                self._schedule_retry(event, type(exc).__name__)
                logger.error("Loyalty wallet credit %s failed: %s", event.event_id, type(exc).__name__)
                continue
            self._mark_delivered(event)
            self.stdout.write(f"Delivered loyalty wallet credit {event.event_id}.")
        if failures:
            raise CommandError(f"{failures} wallet credit event(s) failed and were scheduled for retry.")

    def _claim_event(self):
        now = timezone.now()
        with transaction.atomic():
            event = (LoyaltyCreditOutbox.objects.select_for_update(skip_locked=True)
                     .filter(delivered_at__isnull=True, next_attempt_at__lte=now)
                     .select_related("transaction").order_by("created_at").first())
            if event is None:
                return None
            event.attempts += 1
            event.next_attempt_at = now + timedelta(minutes=5)
            event.save(update_fields=["attempts", "next_attempt_at"])
            return event

    def _deliver(self, event):
        payload = {
            "event_id": str(event.event_id),
            "owner_user_id": event.owner_user_id,
            "amount": format(event.amount, ".2f"),
            "idempotency_key": event.transaction.idempotency_key,
        }
        body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        timestamp = str(int(timezone.now().timestamp()))
        signature = hmac.new(settings.FINANCE_LOYALTY_CREDIT_SECRET.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
        with httpx.Client(timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.post(settings.FINANCE_LOYALTY_CREDIT_URL, content=body, headers={
                "Content-Type": "application/json", "X-Loyalty-Timestamp": timestamp, "X-Loyalty-Signature": signature,
            })
        if not 200 <= response.status_code < 300:
            raise ValueError(f"finance callback returned HTTP {response.status_code}")
        result = response.json()
        if not isinstance(result, dict) or result.get("event_id") != payload["event_id"]:
            raise ValueError("finance callback did not acknowledge the event")

    def _mark_delivered(self, event):
        now = timezone.now()
        with transaction.atomic():
            LoyaltyCreditOutbox.objects.filter(pk=event.pk, delivered_at__isnull=True).update(delivered_at=now, last_error="")
            LoyaltyTransaction.objects.filter(pk=event.transaction_id).update(status=LoyaltyTransaction.STATUS_COMPLETED)

    def _schedule_retry(self, event, error_name):
        delay = min(60 * (2 ** min(max(event.attempts - 1, 0), 12)), 21600)
        LoyaltyCreditOutbox.objects.filter(pk=event.pk, delivered_at__isnull=True).update(
            next_attempt_at=timezone.now() + timedelta(seconds=delay), last_error=error_name[:300])
