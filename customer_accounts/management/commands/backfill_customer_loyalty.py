import os
from urllib.parse import unquote, urlsplit

from bikadeli_common.settings import database_config_from_url
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.utils.dateparse import parse_datetime

from customer_accounts.models import CustomerAccount, LoyaltyTransaction


def _identity(url):
    parsed = urlsplit(url.strip())
    if parsed.scheme == "sqlite":
        return ("sqlite", unquote(parsed.path))
    return (parsed.scheme.replace("+psycopg", ""), parsed.hostname, parsed.port or 5432, unquote(parsed.path))


class Command(BaseCommand):
    help = "Dry-run or apply an insert-only copy of legacy customer loyalty balances and history."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Apply after preflight; default is read-only.")

    def handle(self, *args, **options):
        source_url = os.getenv("SOURCE_DATABASE_URL", "").strip()
        destination_url = os.getenv("DATABASE_URL", "").strip()
        if not source_url or not destination_url:
            raise CommandError("Set SOURCE_DATABASE_URL and DATABASE_URL explicitly.")
        if _identity(source_url) == _identity(destination_url):
            raise CommandError("Source and destination must be different databases.")
        source_config = connections.databases["default"].copy()
        source_config.update(database_config_from_url(source_url))
        if source_config["ENGINE"] == "django.db.backends.sqlite3":
            source_config["OPTIONS"] = {}
        connections.databases["loyalty_source"] = source_config
        try:
            with connections["loyalty_source"].cursor() as cursor:
                cursor.execute("SELECT id, user_id, loyalty_points FROM customers_customerprofile ORDER BY id")
                profiles = cursor.fetchall()
                cursor.execute("SELECT id, customer_id, order_id, transaction_type, points, wallet_credit, idempotency_key, created_at FROM customers_loyaltytransaction ORDER BY id")
                history = cursor.fetchall()
            accounts = {row.owner_user_id: row for row in CustomerAccount.objects.filter(owner_user_id__in=[row[1] for row in profiles])}
            conflicts = []
            for profile_id, user_id, points in profiles:
                if user_id is None or points is None or points < 0:
                    conflicts.append(f"invalid customer profile {user_id}")
                account = accounts.get(user_id)
                if account and account.loyalty_points not in (0, points):
                    conflicts.append(f"customer {user_id} already has a conflicting balance")
            legacy_ids = {row[0] for row in history}
            if len(legacy_ids) != len(history):
                conflicts.append("duplicate legacy transaction IDs")
            existing_ids = set(LoyaltyTransaction.objects.filter(source_legacy_id__in=legacy_ids).values_list("source_legacy_id", flat=True))
            customers_by_id = {row[0]: row[1] for row in profiles}
            for transaction_id, customer_id, order_id, kind, points, credit, key, created_at in history:
                if customer_id not in customers_by_id or kind not in ("EARN", "REDEEM") or points is None or points < 0:
                    conflicts.append(f"invalid loyalty transaction {transaction_id}")
            if conflicts:
                raise CommandError("Backfill preflight failed: " + "; ".join(conflicts[:20]))
            existing_history = {row.source_legacy_id: row for row in LoyaltyTransaction.objects.filter(source_legacy_id__in=legacy_ids).select_related("customer")}
            for transaction_id, customer_id, order_id, kind, points, credit, key, created_at in history:
                entry = existing_history.get(transaction_id)
                if entry and (entry.customer.owner_user_id != customers_by_id.get(customer_id) or entry.order_id != order_id or entry.transaction_type != kind or entry.points != points or entry.wallet_credit != (credit or 0) or entry.idempotency_key != (key or "")):
                    conflicts.append(f"legacy transaction {transaction_id} conflicts with destination")
            if conflicts:
                raise CommandError("Backfill preflight failed: " + "; ".join(conflicts[:20]))
            missing_accounts = sum(user_id not in accounts for _, user_id, _ in profiles)
            missing_history = len(history) - len(existing_ids)
            if options["apply"]:
                with transaction.atomic():
                    for profile_id, user_id, points in profiles:
                        account = accounts.get(user_id)
                        if account is None:
                            account = CustomerAccount.objects.create(owner_user_id=user_id, loyalty_points=points)
                            accounts[user_id] = account
                        elif account.loyalty_points == 0 and points:
                            CustomerAccount.objects.filter(pk=account.pk, loyalty_points=0).update(loyalty_points=points)
                    for transaction_id, customer_id, order_id, kind, points, credit, key, created_at in history:
                        if LoyaltyTransaction.objects.filter(source_legacy_id=transaction_id).exists():
                            continue
                        account = accounts.get(customers_by_id[customer_id])
                        LoyaltyTransaction.objects.create(
                            customer=account, order_id=order_id, transaction_type=kind, points=points,
                            wallet_credit=credit or 0, idempotency_key=key or "", source_legacy_id=transaction_id,
                            status=LoyaltyTransaction.STATUS_COMPLETED,
                            created_at=parse_datetime(created_at.isoformat()) if hasattr(created_at, "isoformat") else parse_datetime(str(created_at)),
                        )
            mode = "APPLIED" if options["apply"] else "DRY RUN"
            self.stdout.write(f"{mode}: profiles={len(profiles)}, new_accounts={missing_accounts}, history={len(history)}, new_history={missing_history}.")
        finally:
            connections["loyalty_source"].close()
            del connections["loyalty_source"]
            connections.databases.pop("loyalty_source", None)
