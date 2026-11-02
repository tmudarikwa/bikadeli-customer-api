import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from unittest import TestCase

WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
MANAGE_PY = Path(__file__).resolve().parents[1] / "manage.py"


def _sqlite_url(path):
    return f"sqlite:///{Path(path).as_posix()}"


class CustomerAddressBackfillTests(TestCase):
    def setUp(self):
        self.source_path = Path(__file__).with_name(".customer_backfill_source.sqlite3")
        self.destination_path = Path(__file__).with_name(
            ".customer_backfill_destination.sqlite3"
        )
        for path in (self.source_path, self.destination_path):
            if path.exists():
                path.unlink()
        self.addCleanup(self._remove_databases)
        self._create_source_database()
        self.environment = os.environ.copy()
        self.environment.update(
            {
                "DJANGO_DEBUG": "1",
                "DATABASE_URL": _sqlite_url(self.destination_path),
                "SOURCE_DATABASE_URL": _sqlite_url(self.source_path),
            }
        )
        self._run_manage("migrate", "--noinput")

    def _remove_databases(self):
        for path in (self.source_path, self.destination_path):
            if os.path.exists(path):
                path.unlink()

    def _create_source_database(self):
        connection = sqlite3.connect(self.source_path)
        try:
            connection.executescript(
                """
                CREATE TABLE customers_customerprofile (
                    id INTEGER PRIMARY KEY, user_id INTEGER, created_at TEXT, updated_at TEXT
                );
                CREATE TABLE customers_customeraddress (
                    id INTEGER PRIMARY KEY, customer_id INTEGER, address_type TEXT, label TEXT,
                    full_address TEXT, what3words TEXT, location_lat REAL, location_lng REAL,
                    delivery_instructions TEXT, is_default INTEGER, created_at TEXT
                );
                CREATE TABLE customers_customersupportticket (
                    id INTEGER PRIMARY KEY, customer_id INTEGER, order_id INTEGER, subject TEXT,
                    description TEXT, category TEXT, priority TEXT, status TEXT, escalated INTEGER,
                    escalation_reason TEXT, escalation_team TEXT, assigned_to_id INTEGER,
                    resolution_notes TEXT, created_at TEXT, updated_at TEXT, resolved_at TEXT
                );
                CREATE TABLE customers_customerticketmessage (
                    id INTEGER PRIMARY KEY, ticket_id INTEGER, sender_is_customer INTEGER,
                    message TEXT, channel TEXT, delivery_result TEXT, created_at TEXT
                );
                CREATE TABLE customers_customervendorfavourite (
                    id INTEGER PRIMARY KEY, customer_id INTEGER, vendor_id INTEGER, created_at TEXT
                );
                CREATE TABLE customers_customerfavourite (
                    id INTEGER PRIMARY KEY, customer_id INTEGER, product_id INTEGER, created_at TEXT
                );
                """
            )
            connection.execute(
                "INSERT INTO customers_customerprofile VALUES (?, ?, ?, ?)",
                (81, 4101, "2025-03-01T08:00:00+00:00", "2025-03-02T08:00:00+00:00"),
            )
            connection.execute(
                """
                INSERT INTO customers_customeraddress VALUES
                (901, 81, 'HOME', 'Home', '12 Main Street', 'alpha.bravo.charlie',
                 -17.8252, 31.0335, 'Ring the bell', 1, '2025-03-03T08:00:00+00:00')
                """
            )
            connection.execute(
                """
                INSERT INTO customers_customersupportticket VALUES
                (701, 81, 501, 'Late delivery', 'My order is late', 'DELIVERY', 'HIGH',
                 'IN_PROGRESS', 1, 'Needs escalation', 'OPS', 901, 'Contacted vendor',
                 '2025-03-04T08:00:00+00:00', '2025-03-05T08:00:00+00:00', NULL)
                """
            )
            connection.execute(
                """
                INSERT INTO customers_customerticketmessage VALUES
                (801, 701, 1, 'My order is late', '', 'PENDING', '2025-03-04T08:00:00+00:00'),
                (802, 701, 0, 'We are checking', 'EMAIL', 'SENT', '2025-03-04T09:00:00+00:00')
                """
            )
            connection.execute(
                """
                INSERT INTO customers_customervendorfavourite VALUES
                (951, 81, 72, '2025-03-06T08:00:00+00:00')
                """
            )
            connection.execute(
                """
                INSERT INTO customers_customerfavourite VALUES
                (952, 81, 501, '2025-03-07T08:00:00+00:00')
                """
            )
            connection.commit()
        finally:
            connection.close()

    def _run_manage(self, *arguments, success=True):
        result = subprocess.run(
            [sys.executable, str(MANAGE_PY), *arguments],
            cwd=WORKSPACE_ROOT,
            env=self.environment,
            capture_output=True,
            text=True,
            check=False,
        )
        if success and result.returncode:
            self.fail(f"Command failed:\n{result.stdout}\n{result.stderr}")
        if not success and result.returncode == 0:
            self.fail(f"Command unexpectedly succeeded:\n{result.stdout}")
        return result

    def _count(self, table):
        connection = sqlite3.connect(self.destination_path)
        try:
            return connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        finally:
            connection.close()

    def test_dry_run_and_apply_preserve_account_address_and_location(self):
        dry_run = self._run_manage("backfill_customer_data")
        self.assertIn("Customer data backfill: DRY RUN", dry_run.stdout)
        self.assertIn(
            "accounts: source=1 already_matching=0 insertable=1", dry_run.stdout
        )
        self.assertIn(
            "addresses: source=1 already_matching=0 insertable=1", dry_run.stdout
        )
        self.assertIn(
            "tickets: source=1 already_matching=0 insertable=1", dry_run.stdout
        )
        self.assertIn(
            "messages: source=2 already_matching=0 insertable=2", dry_run.stdout
        )
        self.assertIn(
            "vendor_favourites: source=1 already_matching=0 insertable=1",
            dry_run.stdout,
        )
        self.assertIn(
            "product_favourites: source=1 already_matching=0 insertable=1",
            dry_run.stdout,
        )
        self.assertIn("source_checksum=", dry_run.stdout)
        self.assertEqual(self._count("customer_accounts_customeraccount"), 0)
        self.assertEqual(self._count("customer_accounts_savedaddress"), 0)
        self.assertEqual(self._count("customer_accounts_customersupportticket"), 0)
        self.assertEqual(self._count("customer_accounts_customerticketmessage"), 0)
        self.assertEqual(self._count("customer_accounts_customervendorfavourite"), 0)
        self.assertEqual(self._count("customer_accounts_customerproductfavourite"), 0)

        applied = self._run_manage("backfill_customer_data", "--apply")
        self.assertIn("Customer data backfill: APPLIED", applied.stdout)
        repeated = self._run_manage("backfill_customer_data", "--apply")
        self.assertIn(
            "accounts: source=1 already_matching=1 insertable=0", repeated.stdout
        )
        self.assertIn(
            "addresses: source=1 already_matching=1 insertable=0", repeated.stdout
        )
        self.assertIn(
            "tickets: source=1 already_matching=1 insertable=0", repeated.stdout
        )
        self.assertIn(
            "messages: source=2 already_matching=2 insertable=0", repeated.stdout
        )
        self.assertIn(
            "vendor_favourites: source=1 already_matching=1 insertable=0",
            repeated.stdout,
        )
        self.assertIn(
            "product_favourites: source=1 already_matching=1 insertable=0",
            repeated.stdout,
        )
        for line in repeated.stdout.splitlines():
            if line.startswith(
                (
                    "accounts:",
                    "addresses:",
                    "tickets:",
                    "messages:",
                    "vendor_favourites:",
                    "product_favourites:",
                )
            ):
                source_checksum = line.split("source_checksum=")[1].split()[0]
                destination_checksum = line.split("destination_matching_checksum=")[1]
                self.assertEqual(source_checksum, destination_checksum)

        destination = sqlite3.connect(self.destination_path)
        try:
            account = destination.execute(
                "SELECT id, owner_user_id, created_at FROM customer_accounts_customeraccount"
            ).fetchone()
            self.assertEqual(account[:2], (81, 4101))
            address = destination.execute(
                """
                SELECT id, customer_id, label, location_lat, location_lng, is_default
                FROM customer_accounts_savedaddress
                """
            ).fetchone()
            self.assertEqual(address, (901, 81, "Home", -17.8252, 31.0335, 1))
            ticket = destination.execute(
                """
                SELECT id, customer_id, order_id, status, escalated, assigned_to_user_id, resolution_notes
                FROM customer_accounts_customersupportticket
                """
            ).fetchone()
            self.assertEqual(
                ticket, (701, 81, 501, "IN_PROGRESS", 1, 901, "Contacted vendor")
            )
            messages = destination.execute(
                """
                SELECT id, ticket_id, sender_is_customer, message, channel, delivery_result
                FROM customer_accounts_customerticketmessage ORDER BY id
                """
            ).fetchall()
            self.assertEqual(
                messages,
                [
                    (801, 701, 1, "My order is late", "", "PENDING"),
                    (802, 701, 0, "We are checking", "EMAIL", "SENT"),
                ],
            )
            vendor_favourite = destination.execute(
                """
                SELECT id, customer_id, vendor_id, created_at
                FROM customer_accounts_customervendorfavourite
                """
            ).fetchone()
            self.assertEqual(vendor_favourite[:3], (951, 81, 72))
            product_favourite = destination.execute(
                """
                SELECT id, customer_id, product_id, created_at
                FROM customer_accounts_customerproductfavourite
                """
            ).fetchone()
            self.assertEqual(product_favourite[:3], (952, 81, 501))
        finally:
            destination.close()

    def test_identity_conflict_aborts_without_partial_address_copy(self):
        destination = sqlite3.connect(self.destination_path)
        try:
            destination.execute(
                """
                INSERT INTO customer_accounts_customeraccount
                (id, owner_user_id, created_at, updated_at)
                VALUES (99, 4101, '2025-01-01 00:00:00', '2025-01-01 00:00:00')
                """
            )
            destination.commit()
        finally:
            destination.close()

        result = self._run_manage("backfill_customer_data", "--apply", success=False)
        self.assertIn("already belongs to destination customer 99", result.stderr)
        self.assertEqual(self._count("customer_accounts_savedaddress"), 0)
        self.assertEqual(self._count("customer_accounts_customersupportticket"), 0)

    def test_ticket_conflict_aborts_without_partial_ticket_or_message_copy(self):
        destination = sqlite3.connect(self.destination_path)
        try:
            destination.execute(
                """
                INSERT INTO customer_accounts_customeraccount
                (id, owner_user_id, created_at, updated_at)
                VALUES (81, 4101, '2025-03-01 08:00:00+00:00', '2025-03-02 08:00:00+00:00')
                """
            )
            destination.execute(
                """
                INSERT INTO customer_accounts_customersupportticket
                (id, order_id, subject, description, category, priority, status, escalated,
                 escalation_reason, escalation_team, assigned_to_user_id, resolution_notes,
                 created_at, updated_at, resolved_at, customer_id)
                VALUES (701, 501, 'Different subject', 'My order is late', 'DELIVERY', 'HIGH',
                        'IN_PROGRESS', 1, 'Needs escalation', 'OPS', 901, 'Contacted vendor',
                        '2025-03-04 08:00:00+00:00', '2025-03-05 08:00:00+00:00', NULL, 81)
                """
            )
            destination.commit()
        finally:
            destination.close()

        result = self._run_manage("backfill_customer_data", "--apply", success=False)
        self.assertIn("Support ticket ID 701 conflicts on: subject", result.stderr)
        self.assertEqual(self._count("customer_accounts_customerticketmessage"), 0)
        self.assertEqual(self._count("customer_accounts_savedaddress"), 0)

    def test_refuses_to_use_same_source_and_destination_database(self):
        self.environment["SOURCE_DATABASE_URL"] = _sqlite_url(self.destination_path)

        result = self._run_manage("backfill_customer_data", success=False)
        self.assertIn(
            "Source and destination must be different databases", result.stderr
        )
