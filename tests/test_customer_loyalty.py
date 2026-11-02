import hashlib
import hmac
import json
import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import patch

from customer_accounts.models import (
    CustomerAccount,
    LoyaltyCreditOutbox,
    LoyaltyOrderAward,
    LoyaltyTransaction,
)
from django.test import TestCase, override_settings
from rest_framework.test import APIClient


def _signed_request(client, url, payload, secret):
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    timestamp = str(int(time.time()))
    signature = hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()
    return client.generic("POST", url, body, content_type="application/json", HTTP_X_LOYALTY_TIMESTAMP=timestamp, HTTP_X_LOYALTY_SIGNATURE=signature)


class CustomerLoyaltyApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=SimpleNamespace(id=41, is_authenticated=True), token={"user_type": "CUSTOMER"})

    def test_balance_and_redemption_are_owner_scoped_and_idempotent(self):
        account = CustomerAccount.objects.create(owner_user_id=41, loyalty_points=250)
        legacy_balance = self.client.get("/api/v1/customers/loyalty/")
        balance = self.client.get("/api/v1/customers/loyalty/balance/")
        self.assertEqual(legacy_balance.status_code, 200)
        self.assertEqual(legacy_balance.data, balance.data)
        self.assertEqual(balance.status_code, 200)
        self.assertEqual(balance.data, {"points": 250, "wallet_credit_value": "2.50", "points_per_wallet_dollar": 100})

        first = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 200}, format="json", HTTP_IDEMPOTENCY_KEY="redeem-1")
        replay = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 200}, format="json", HTTP_IDEMPOTENCY_KEY="redeem-1")
        conflict = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 100}, format="json", HTTP_IDEMPOTENCY_KEY="redeem-1")
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.data["wallet_credit"], "2.00")
        self.assertEqual(first.data["points_balance"], 50)
        self.assertEqual(first.data["wallet_credit_status"], "PENDING")
        self.assertTrue(replay.data["already_processed"])
        self.assertEqual(conflict.status_code, 409)
        account.refresh_from_db()
        self.assertEqual(account.loyalty_points, 50)
        self.assertEqual(LoyaltyTransaction.objects.filter(transaction_type="REDEEM").count(), 1)
        self.assertEqual(LoyaltyCreditOutbox.objects.count(), 1)

    def test_transaction_history_is_customer_scoped_and_paginated(self):
        account = CustomerAccount.objects.create(owner_user_id=41, loyalty_points=100)
        other_account = CustomerAccount.objects.create(owner_user_id=42, loyalty_points=100)
        own_entry = LoyaltyTransaction.objects.create(
            customer=account,
            transaction_type=LoyaltyTransaction.EARN,
            points=75,
            wallet_credit=Decimal("0.00"),
            order_id=900,
        )
        LoyaltyTransaction.objects.create(
            customer=other_account,
            transaction_type=LoyaltyTransaction.REDEEM,
            points=100,
            wallet_credit=Decimal("1.00"),
        )

        response = self.client.get("/api/v1/customers/loyalty/transactions/?page_size=1")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        self.assertIsNone(response.data["next"])
        self.assertIsNone(response.data["previous"])
        self.assertEqual(
            response.data["results"],
            [
                {
                    "id": own_entry.id,
                    "order_id": 900,
                    "transaction_type": "EARN",
                    "points": 75,
                    "wallet_credit": "0.00",
                    "status": "COMPLETED",
                    "created_at": own_entry.created_at,
                }
            ],
        )

    def test_transaction_history_rejects_non_customer_and_invalid_pagination(self):
        self.client.force_authenticate(
            user=SimpleNamespace(id=41, is_authenticated=True), token={"user_type": "VENDOR"}
        )
        self.assertEqual(
            self.client.get("/api/v1/customers/loyalty/transactions/").status_code, 403
        )

        self.client.force_authenticate(
            user=SimpleNamespace(id=41, is_authenticated=True), token={"user_type": "CUSTOMER"}
        )
        self.assertEqual(
            self.client.get("/api/v1/customers/loyalty/transactions/?page_size=101").status_code,
            400,
        )

    def test_non_customer_token_cannot_read_or_redeem_loyalty(self):
        CustomerAccount.objects.create(owner_user_id=41, loyalty_points=500)
        self.client.force_authenticate(
            user=SimpleNamespace(id=41, is_authenticated=True), token={"user_type": "VENDOR"}
        )
        self.assertEqual(self.client.get("/api/v1/customers/loyalty/balance/").status_code, 403)
        response = self.client.post(
            "/api/v1/customers/loyalty/redeem/", {"points": 100}, format="json",
            HTTP_IDEMPOTENCY_KEY="vendor-redeem",
        )
        self.assertEqual(response.status_code, 403)
        self.assertEqual(LoyaltyTransaction.objects.count(), 0)

    def test_redemption_rejects_invalid_and_insufficient_points(self):
        CustomerAccount.objects.create(owner_user_id=41, loyalty_points=150)
        invalid = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 150}, format="json", HTTP_IDEMPOTENCY_KEY="bad-1")
        insufficient = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 200}, format="json", HTTP_IDEMPOTENCY_KEY="bad-2")
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(insufficient.status_code, 400)
        self.assertEqual(LoyaltyTransaction.objects.count(), 0)

    @override_settings(ORDERS_LOYALTY_CALLBACK_SECRET="orders-test-secret")
    def test_signed_delivered_paid_order_award_is_idempotent(self):
        payload = {"event_id": "22d41ea5-f931-449d-9e47-89c2192d3073", "order_id": 800, "customer_user_id": 41, "eligible_spend": "24.99", "prime_multiplier": 2, "status": "DELIVERED", "payment_status": "PAID"}
        first = _signed_request(self.client, "/internal/v1/customers/loyalty/orders/award/", payload, "orders-test-secret")
        replay = _signed_request(self.client, "/internal/v1/customers/loyalty/orders/award/", payload, "orders-test-secret")
        self.assertEqual(first.status_code, 200, first.data)
        self.assertEqual(first.data["awarded_points"], 48)
        self.assertTrue(replay.data["already_processed"])
        self.assertEqual(CustomerAccount.objects.get(owner_user_id=41).loyalty_points, 48)
        self.assertEqual(LoyaltyTransaction.objects.filter(transaction_type="EARN", order_id=800).count(), 1)
        self.assertEqual(LoyaltyOrderAward.objects.filter(order_id=800).count(), 1)

    @override_settings(ORDERS_LOYALTY_CALLBACK_SECRET="orders-test-secret")
    def test_zero_point_order_is_recorded_and_replayable_without_ledger_entry(self):
        payload = {"event_id": "22d41ea5-f931-449d-9e47-89c2192d3074", "order_id": 801, "customer_user_id": 41, "eligible_spend": "0.99", "prime_multiplier": 1, "status": "DELIVERED", "payment_status": "PAID"}
        first = _signed_request(self.client, "/internal/v1/customers/loyalty/orders/award/", payload, "orders-test-secret")
        replay = _signed_request(self.client, "/internal/v1/customers/loyalty/orders/award/", payload, "orders-test-secret")
        self.assertEqual(first.data["awarded_points"], 0)
        self.assertTrue(replay.data["already_processed"])
        self.assertEqual(LoyaltyOrderAward.objects.filter(order_id=801).count(), 1)
        self.assertFalse(LoyaltyTransaction.objects.filter(order_id=801).exists())

    @override_settings(FINANCE_LOYALTY_CREDIT_URL="http://finance.test/api/v1/internal/finance/wallet/loyalty-credit/", FINANCE_LOYALTY_CREDIT_SECRET="finance-test-secret", UPSTREAM_TIMEOUT_SECONDS=2)
    @patch("customer_accounts.management.commands.deliver_loyalty_wallet_credits.httpx.Client")
    def test_credit_outbox_dispatch_marks_redemption_complete(self, client_class):
        CustomerAccount.objects.create(owner_user_id=41, loyalty_points=100)
        response = self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 100}, format="json", HTTP_IDEMPOTENCY_KEY="redeem-outbox")
        self.assertEqual(response.status_code, 200)
        mock_client = client_class.return_value.__enter__.return_value
        mock_client.post.return_value.status_code = 200
        mock_client.post.return_value.json.return_value = {"event_id": str(LoyaltyCreditOutbox.objects.get().event_id)}
        from django.core.management import call_command
        call_command("deliver_loyalty_wallet_credits", limit=1)
        entry = LoyaltyTransaction.objects.get(transaction_type="REDEEM")
        entry.refresh_from_db()
        self.assertEqual(entry.status, LoyaltyTransaction.STATUS_COMPLETED)
        self.assertIsNotNone(entry.credit_outbox.delivered_at)
        self.assertEqual(mock_client.post.call_count, 1)


    @override_settings(FINANCE_LOYALTY_CREDIT_URL="http://finance.test/credit/", FINANCE_LOYALTY_CREDIT_SECRET="finance-test-secret", UPSTREAM_TIMEOUT_SECONDS=2)
    @patch("customer_accounts.management.commands.deliver_loyalty_wallet_credits.httpx.Client")
    def test_credit_worker_schedules_retry_after_finance_failure(self, client_class):
        from django.core.management import call_command
        from django.core.management.base import CommandError
        from django.utils import timezone

        CustomerAccount.objects.create(owner_user_id=41, loyalty_points=100)
        self.client.post("/api/v1/customers/loyalty/redeem/", {"points": 100}, format="json", HTTP_IDEMPOTENCY_KEY="retry-credit")
        client_class.return_value.__enter__.return_value.post.return_value.status_code = 503
        with self.assertRaises(CommandError):
            call_command("deliver_loyalty_wallet_credits", limit=1)
        event = LoyaltyCreditOutbox.objects.get()
        self.assertEqual(event.attempts, 1)
        self.assertIsNone(event.delivered_at)
        self.assertGreater(event.next_attempt_at, timezone.now())


class FakeLoyaltySourceCursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, query):
        self.rows = self.connection.profiles if "customers_customerprofile" in query else self.connection.history

    def fetchall(self):
        return list(self.rows)


class FakeLoyaltySourceConnection:
    def __init__(self):
        from django.utils import timezone
        self.profiles = [(7, 41, 250)]
        self.history = [(5, 7, 800, "EARN", 100, Decimal("0.00"), "", timezone.now())]
        self.closed = False

    def cursor(self):
        return FakeLoyaltySourceCursor(self)

    def close(self):
        self.closed = True


class FakeLoyaltyConnectionHandler:
    def __init__(self):
        self.databases = {"default": {"ENGINE": "django.db.backends.sqlite3", "NAME": ":memory:"}}
        self.source = FakeLoyaltySourceConnection()

    def __getitem__(self, alias):
        return self.source

    def __delitem__(self, alias):
        pass


class CustomerLoyaltyBackfillTests(TestCase):
    def test_backfill_is_dry_run_by_default_and_replayable(self):
        import os
        from unittest.mock import patch

        from customer_accounts.management.commands import backfill_customer_loyalty
        from django.core.management import call_command

        handler = FakeLoyaltyConnectionHandler()
        with (
            patch.dict(os.environ, {"SOURCE_DATABASE_URL": "sqlite:///C:/legacy-loyalty.sqlite3", "DATABASE_URL": "sqlite:///:memory:"}),
            patch.object(backfill_customer_loyalty, "connections", handler),
        ):
            call_command("backfill_customer_loyalty")
            self.assertFalse(CustomerAccount.objects.exists())
            call_command("backfill_customer_loyalty", apply=True)
            account = CustomerAccount.objects.get(owner_user_id=41)
            self.assertEqual(account.loyalty_points, 250)
            entry = LoyaltyTransaction.objects.get(source_legacy_id=5)
            self.assertEqual(entry.order_id, 800)
            self.assertEqual(entry.transaction_type, LoyaltyTransaction.EARN)
            call_command("backfill_customer_loyalty", apply=True)
            self.assertEqual(LoyaltyTransaction.objects.filter(source_legacy_id=5).count(), 1)
            self.assertTrue(handler.source.closed)
