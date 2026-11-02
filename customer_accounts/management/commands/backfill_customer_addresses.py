import hashlib
import json
import os
from datetime import date, datetime, time
from datetime import timezone as datetime_timezone
from urllib.parse import unquote, urlsplit

from bikadeli_common.settings import database_config_from_url
from django.core.management.base import BaseCommand, CommandError
from django.core.management.color import no_style
from django.db import connections, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from customer_accounts.models import (
    CustomerAccount,
    CustomerProductFavourite,
    CustomerSupportTicket,
    CustomerTicketMessage,
    CustomerVendorFavourite,
    SavedAddress,
)

ACCOUNT_FIELDS = ('id', 'owner_user_id', 'created_at', 'updated_at')
ADDRESS_FIELDS = (
    'id',
    'customer_id',
    'address_type',
    'label',
    'full_address',
    'what3words',
    'location_lat',
    'location_lng',
    'delivery_instructions',
    'is_default',
    'created_at',
)
TICKET_FIELDS = (
    'id',
    'customer_id',
    'order_id',
    'subject',
    'description',
    'category',
    'priority',
    'status',
    'escalated',
    'escalation_reason',
    'escalation_team',
    'assigned_to_user_id',
    'resolution_notes',
    'created_at',
    'updated_at',
    'resolved_at',
)
MESSAGE_FIELDS = (
    'id',
    'ticket_id',
    'sender_is_customer',
    'message',
    'channel',
    'delivery_result',
    'created_at',
)
VENDOR_FAVOURITE_FIELDS = ('id', 'customer_id', 'vendor_id', 'created_at')
PRODUCT_FAVOURITE_FIELDS = ('id', 'customer_id', 'product_id', 'created_at')


def _database_identity(database_url):
    parsed = urlsplit(database_url.strip())
    if parsed.scheme == 'sqlite':
        path = unquote(parsed.path)
        if path in {'', '/:memory:'}:
            path = ':memory:'
        if os.name == 'nt' and len(path) > 3 and path[0] == '/' and path[2] == ':':
            path = path[1:]
        return ('sqlite', os.path.normcase(os.path.realpath(path)) if path != ':memory:' else path)
    scheme = parsed.scheme.replace('+psycopg', '')
    if scheme in {'postgres', 'postgresql'}:
        scheme = 'postgresql'
    return (
        scheme,
        (parsed.hostname or '').lower(),
        parsed.port or 5432,
        unquote(parsed.path),
    )


def _canonical(value):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, float):
        return format(value, '.15g')
    if isinstance(value, dict):
        return {key: _canonical(value[key]) for key in sorted(value)}
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    return value


def _checksum(rows, fields):
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda item: item['id']):
        serialized = {field: _canonical(row.get(field)) for field in fields}
        digest.update(json.dumps(serialized, sort_keys=True, separators=(',', ':')).encode())
        digest.update(b'\n')
    return digest.hexdigest()


class Command(BaseCommand):
    help = (
        'Dry-run or apply a repeatable copy of customer accounts, addresses, tickets, '
        'and customer favourites.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply',
            action='store_true',
            help='Insert missing rows into the customer database. Without this flag, no rows are written.',
        )

    def handle(self, *args, **options):
        source_url = os.getenv('SOURCE_DATABASE_URL', '').strip()
        destination_url = os.getenv('DATABASE_URL', '').strip()
        if not source_url or not destination_url:
            raise CommandError('Set both SOURCE_DATABASE_URL and DATABASE_URL explicitly.')
        if _database_identity(source_url) == _database_identity(destination_url):
            raise CommandError('Source and destination must be different databases.')

        source_config = connections.databases['default'].copy()
        source_config.update(database_config_from_url(source_url))
        if source_config['ENGINE'] == 'django.db.backends.sqlite3':
            source_config['OPTIONS'] = {}
        connections.databases['source'] = source_config
        try:
            expected = self._read_source()
            self._validate_source(expected)
            plans = self._preflight(expected)

            if options['apply']:
                with transaction.atomic(using='default'):
                    plans = self._preflight(expected)
                    self._insert_missing(plans)
                    self._verify_destination(expected)
            actual = self._read_destination()
            self._report(expected, actual, plans, options['apply'])
        finally:
            connections['source'].close()
            del connections['source']
            connections.databases.pop('source', None)

    def _query_rows(self, cursor, from_clause, expressions):
        connection = cursor.db
        selected = ', '.join(
            f'{expression} AS {connection.ops.quote_name(alias)}'
            for alias, expression in expressions
        )
        cursor.execute(f'SELECT {selected} FROM {from_clause}')
        names = [column[0] for column in cursor.description]
        return [dict(zip(names, row)) for row in cursor.fetchall()]

    def _read_source(self):
        source_connection = connections['source']
        try:
            with transaction.atomic(using='source'), source_connection.cursor() as cursor:
                    if source_connection.vendor == 'postgresql':
                        cursor.execute('SET TRANSACTION READ ONLY')
                    elif source_connection.vendor == 'sqlite':
                        cursor.execute('PRAGMA query_only = ON')

                    accounts = self._query_rows(
                        cursor,
                        source_connection.ops.quote_name('customers_customerprofile'),
                        [
                            ('id', 'id'),
                            ('owner_user_id', 'user_id'),
                            ('created_at', 'created_at'),
                            ('updated_at', 'updated_at'),
                        ],
                    )
                    if source_connection.vendor == 'postgresql':
                        latitude, longitude = 'ST_Y(address.location)', 'ST_X(address.location)'
                    elif source_connection.vendor == 'sqlite':
                        cursor.execute("PRAGMA table_info('customers_customeraddress')")
                        source_columns = {row[1] for row in cursor.fetchall()}
                        if {'location_lat', 'location_lng'} <= source_columns:
                            latitude, longitude = 'address.location_lat', 'address.location_lng'
                        elif 'location' in source_columns:
                            raise CommandError(
                                'SQLite spatial source schemas are unsupported; use a PostgreSQL/PostGIS source.'
                            )
                        else:
                            latitude = longitude = 'NULL'
                    else:
                        raise CommandError('Customer address backfill supports PostgreSQL or SQLite sources.')
                    addresses = self._query_rows(
                        cursor,
                        '{} AS address JOIN {} AS customer ON customer.id = address.customer_id'.format(
                            source_connection.ops.quote_name('customers_customeraddress'),
                            source_connection.ops.quote_name('customers_customerprofile'),
                        ),
                        [
                            ('id', 'address.id'),
                            ('customer_id', 'address.customer_id'),
                            ('address_type', 'address.address_type'),
                            ('label', 'address.label'),
                            ('full_address', 'address.full_address'),
                            ('what3words', 'address.what3words'),
                            ('location_lat', latitude),
                            ('location_lng', longitude),
                            ('delivery_instructions', 'address.delivery_instructions'),
                            ('is_default', 'address.is_default'),
                            ('created_at', 'address.created_at'),
                        ],
                    )
                    tickets = self._query_rows(
                        cursor,
                        source_connection.ops.quote_name('customers_customersupportticket'),
                        [
                            ('id', 'id'),
                            ('customer_id', 'customer_id'),
                            ('order_id', 'order_id'),
                            ('subject', 'subject'),
                            ('description', 'description'),
                            ('category', 'category'),
                            ('priority', 'priority'),
                            ('status', 'status'),
                            ('escalated', 'escalated'),
                            ('escalation_reason', 'escalation_reason'),
                            ('escalation_team', 'escalation_team'),
                            ('assigned_to_user_id', 'assigned_to_id'),
                            ('resolution_notes', 'resolution_notes'),
                            ('created_at', 'created_at'),
                            ('updated_at', 'updated_at'),
                            ('resolved_at', 'resolved_at'),
                        ],
                    )
                    messages = self._query_rows(
                        cursor,
                        source_connection.ops.quote_name('customers_customerticketmessage'),
                        [(field, field) for field in MESSAGE_FIELDS],
                    )
                    vendor_favourites = self._query_rows(
                        cursor,
                        source_connection.ops.quote_name('customers_customervendorfavourite'),
                        [(field, field) for field in VENDOR_FAVOURITE_FIELDS],
                    )
                    product_favourites = self._query_rows(
                        cursor,
                        source_connection.ops.quote_name('customers_customerfavourite'),
                        [(field, field) for field in PRODUCT_FAVOURITE_FIELDS],
                    )
            return {
                'accounts': accounts,
                'addresses': addresses,
                'tickets': tickets,
                'messages': messages,
                'vendor_favourites': vendor_favourites,
                'product_favourites': product_favourites,
            }
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(
                'Could not read expected customer source tables; verify the source schema and database access '
                f'({type(exc).__name__}: {exc}).'
            ) from exc

    def _validate_source(self, expected):
        account_ids = {row['id'] for row in expected['accounts']}
        owner_ids = set()
        for account in expected['accounts']:
            if not account['id'] or not account['owner_user_id']:
                raise CommandError('Customer profiles must have valid source and identity owner IDs.')
            if account['owner_user_id'] in owner_ids:
                raise CommandError(f'Duplicate customer profile for user ID {account["owner_user_id"]}.')
            owner_ids.add(account['owner_user_id'])
            for field in ('created_at', 'updated_at'):
                if isinstance(account[field], str):
                    account[field] = parse_datetime(account[field])
                if account[field] is not None and timezone.is_naive(account[field]):
                    account[field] = timezone.make_aware(account[field], datetime_timezone.utc)

        address_ids = set()
        for address in expected['addresses']:
            if not address['id'] or address['id'] in address_ids:
                raise CommandError('Customer saved addresses must have unique, nonzero IDs.')
            address_ids.add(address['id'])
            if address['customer_id'] not in account_ids:
                raise CommandError(
                    f'Saved address {address["id"]} references missing customer profile {address["customer_id"]}.'
                )
            if (address['location_lat'] is None) != (address['location_lng'] is None):
                raise CommandError(f'Saved address {address["id"]} has incomplete location coordinates.')
            if address['location_lat'] is not None:
                address['location_lat'] = float(address['location_lat'])
            if address['location_lng'] is not None:
                address['location_lng'] = float(address['location_lng'])
            if address['location_lat'] is not None and not -90 <= address['location_lat'] <= 90:
                raise CommandError(f'Saved address {address["id"]} has invalid latitude.')
            if address['location_lng'] is not None and not -180 <= address['location_lng'] <= 180:
                raise CommandError(f'Saved address {address["id"]} has invalid longitude.')
            address['is_default'] = bool(address['is_default'])
            if isinstance(address['created_at'], str):
                address['created_at'] = parse_datetime(address['created_at'])
            if address['created_at'] is not None and timezone.is_naive(address['created_at']):
                address['created_at'] = timezone.make_aware(address['created_at'], datetime_timezone.utc)

        ticket_ids = set()
        for ticket in expected['tickets']:
            if not ticket['id'] or ticket['id'] in ticket_ids:
                raise CommandError('Customer support tickets must have unique, nonzero IDs.')
            ticket_ids.add(ticket['id'])
            if ticket['customer_id'] not in account_ids:
                raise CommandError(
                    f'Support ticket {ticket["id"]} references missing customer profile {ticket["customer_id"]}.'
                )
            ticket['escalated'] = bool(ticket['escalated'])
            for field in ('created_at', 'updated_at', 'resolved_at'):
                if isinstance(ticket[field], str):
                    ticket[field] = parse_datetime(ticket[field])
                if ticket[field] is not None and timezone.is_naive(ticket[field]):
                    ticket[field] = timezone.make_aware(ticket[field], datetime_timezone.utc)

        message_ids = set()
        for message in expected['messages']:
            if not message['id'] or message['id'] in message_ids:
                raise CommandError('Customer support ticket messages must have unique, nonzero IDs.')
            message_ids.add(message['id'])
            if message['ticket_id'] not in ticket_ids:
                raise CommandError(
                    f'Support ticket message {message["id"]} references missing ticket {message["ticket_id"]}.'
                )
            message['sender_is_customer'] = bool(message['sender_is_customer'])
            if isinstance(message['created_at'], str):
                message['created_at'] = parse_datetime(message['created_at'])
            if message['created_at'] is not None and timezone.is_naive(message['created_at']):
                message['created_at'] = timezone.make_aware(message['created_at'], datetime_timezone.utc)

        favourite_ids = set()
        for favourite in expected['vendor_favourites']:
            if not favourite['id'] or favourite['id'] in favourite_ids:
                raise CommandError('Customer vendor favourites must have unique, nonzero IDs.')
            favourite_ids.add(favourite['id'])
            if favourite['customer_id'] not in account_ids:
                raise CommandError(
                    f'Vendor favourite {favourite["id"]} references missing customer profile '
                    f'{favourite["customer_id"]}.'
                )
            if not favourite['vendor_id'] or favourite['vendor_id'] <= 0:
                raise CommandError(f'Vendor favourite {favourite["id"]} has an invalid vendor ID.')
            if isinstance(favourite['created_at'], str):
                favourite['created_at'] = parse_datetime(favourite['created_at'])
            if favourite['created_at'] is not None and timezone.is_naive(favourite['created_at']):
                favourite['created_at'] = timezone.make_aware(favourite['created_at'], datetime_timezone.utc)

        favourite_ids = set()
        for favourite in expected['product_favourites']:
            if not favourite['id'] or favourite['id'] in favourite_ids:
                raise CommandError('Customer product favourites must have unique, nonzero IDs.')
            favourite_ids.add(favourite['id'])
            if favourite['customer_id'] not in account_ids:
                raise CommandError(
                    f'Product favourite {favourite["id"]} references missing customer profile '
                    f'{favourite["customer_id"]}.'
                )
            if not favourite['product_id'] or favourite['product_id'] <= 0:
                raise CommandError(f'Product favourite {favourite["id"]} has an invalid product ID.')
            if isinstance(favourite['created_at'], str):
                favourite['created_at'] = parse_datetime(favourite['created_at'])
            if favourite['created_at'] is not None and timezone.is_naive(favourite['created_at']):
                favourite['created_at'] = timezone.make_aware(favourite['created_at'], datetime_timezone.utc)

    def _read_destination(self):
        return {
            'accounts': [
                {field: getattr(row, field) for field in ACCOUNT_FIELDS}
                for row in CustomerAccount.objects.order_by('id')
            ],
            'addresses': [
                {
                    field: getattr(row, field)
                    for field in ADDRESS_FIELDS
                }
                for row in SavedAddress.objects.order_by('id')
            ],
            'tickets': [
                {field: getattr(row, field) for field in TICKET_FIELDS}
                for row in CustomerSupportTicket.objects.order_by('id')
            ],
            'messages': [
                {field: getattr(row, field) for field in MESSAGE_FIELDS}
                for row in CustomerTicketMessage.objects.order_by('id')
            ],
            'vendor_favourites': [
                {field: getattr(row, field) for field in VENDOR_FAVOURITE_FIELDS}
                for row in CustomerVendorFavourite.objects.order_by('id')
            ],
            'product_favourites': [
                {field: getattr(row, field) for field in PRODUCT_FAVOURITE_FIELDS}
                for row in CustomerProductFavourite.objects.order_by('id')
            ],
        }

    def _preflight(self, expected):
        actual = self._read_destination()
        plans = {}
        for table, model, fields in (
            ('accounts', CustomerAccount, ACCOUNT_FIELDS),
            ('addresses', SavedAddress, ADDRESS_FIELDS),
            ('tickets', CustomerSupportTicket, TICKET_FIELDS),
            ('messages', CustomerTicketMessage, MESSAGE_FIELDS),
            ('vendor_favourites', CustomerVendorFavourite, VENDOR_FAVOURITE_FIELDS),
            ('product_favourites', CustomerProductFavourite, PRODUCT_FAVOURITE_FIELDS),
        ):
            actual_by_id = {row['id']: row for row in actual[table]}
            missing = []
            for source_row in expected[table]:
                destination_row = actual_by_id.get(source_row['id'])
                if destination_row is None:
                    missing.append(source_row)
                    continue
                conflicts = [
                    field
                    for field in fields
                    if _canonical(destination_row.get(field)) != _canonical(source_row.get(field))
                ]
                if conflicts:
                    label = {
                        'accounts': 'Customer profile',
                        'addresses': 'Saved address',
                        'tickets': 'Support ticket',
                        'messages': 'Support ticket message',
                        'vendor_favourites': 'Customer vendor favourite',
                        'product_favourites': 'Customer product favourite',
                    }[table]
                    raise CommandError(
                        f'{label} ID {source_row["id"]} conflicts on: {", ".join(conflicts)}.'
                    )
            if table == 'accounts':
                owners = {row['owner_user_id']: row['id'] for row in actual[table]}
                for row in missing:
                    existing_id = owners.get(row['owner_user_id'])
                    if existing_id is not None:
                        raise CommandError(
                            f'Identity user ID {row["owner_user_id"]} already belongs to destination customer '
                            f'{existing_id}, not source profile {row["id"]}.'
                        )
            if table == 'tickets':
                customers = {row['id'] for row in actual['accounts']} | {
                    row['id'] for row in plans.get('accounts', [])
                }
                for row in missing:
                    if row['customer_id'] not in customers:
                        raise CommandError(
                            f'Support ticket {row["id"]} references missing destination customer '
                            f'{row["customer_id"]}.'
                        )
            if table == 'messages':
                tickets = {row['id'] for row in actual['tickets']} | {
                    row['id'] for row in plans.get('tickets', [])
                }
                for row in missing:
                    if row['ticket_id'] not in tickets:
                        raise CommandError(
                            f'Support ticket message {row["id"]} references missing destination ticket '
                            f'{row["ticket_id"]}.'
                        )
            if table == 'vendor_favourites':
                customers = {row['id'] for row in actual['accounts']} | {
                    row['id'] for row in plans.get('accounts', [])
                }
                for row in missing:
                    if row['customer_id'] not in customers:
                        raise CommandError(
                            f'Vendor favourite {row["id"]} references missing destination customer '
                            f'{row["customer_id"]}.'
                        )
                existing_pairs = {
                    (row['customer_id'], row['vendor_id']): row['id']
                    for row in actual[table]
                }
                for row in missing:
                    existing_id = existing_pairs.get((row['customer_id'], row['vendor_id']))
                    if existing_id is not None:
                        raise CommandError(
                            f'Customer/vendor pair {row["customer_id"]}/{row["vendor_id"]} already belongs '
                            f'to destination favourite {existing_id}, not source favourite {row["id"]}.'
                        )
            if table == 'product_favourites':
                customers = {row['id'] for row in actual['accounts']} | {
                    row['id'] for row in plans.get('accounts', [])
                }
                for row in missing:
                    if row['customer_id'] not in customers:
                        raise CommandError(
                            f'Product favourite {row["id"]} references missing destination customer '
                            f'{row["customer_id"]}.'
                        )
                existing_pairs = {
                    (row['customer_id'], row['product_id']): row['id']
                    for row in actual[table]
                }
                for row in missing:
                    existing_id = existing_pairs.get((row['customer_id'], row['product_id']))
                    if existing_id is not None:
                        raise CommandError(
                            f'Customer/product pair {row["customer_id"]}/{row["product_id"]} already belongs '
                            f'to destination favourite {existing_id}, not source favourite {row["id"]}.'
                        )
            plans[table] = missing
        return plans

    def _insert_missing(self, plans):
        for row in plans['accounts']:
            CustomerAccount.objects.create(**row)
        for row in plans['addresses']:
            SavedAddress.objects.create(**row)
        for row in plans['tickets']:
            CustomerSupportTicket.objects.create(**row)
        for row in plans['messages']:
            CustomerTicketMessage.objects.create(**row)
        for row in plans['vendor_favourites']:
            CustomerVendorFavourite.objects.create(**row)
        for row in plans['product_favourites']:
            CustomerProductFavourite.objects.create(**row)
        for statement in connections['default'].ops.sequence_reset_sql(
            no_style(),
            [
                CustomerAccount,
                SavedAddress,
                CustomerSupportTicket,
                CustomerTicketMessage,
                CustomerVendorFavourite,
                CustomerProductFavourite,
            ],
        ):
            with connections['default'].cursor() as cursor:
                cursor.execute(statement)

    def _verify_destination(self, expected):
        actual = self._read_destination()
        for table, fields in (
            ('accounts', ACCOUNT_FIELDS),
            ('addresses', ADDRESS_FIELDS),
            ('tickets', TICKET_FIELDS),
            ('messages', MESSAGE_FIELDS),
            ('vendor_favourites', VENDOR_FAVOURITE_FIELDS),
            ('product_favourites', PRODUCT_FAVOURITE_FIELDS),
        ):
            actual_by_id = {row['id']: row for row in actual[table]}
            for source_row in expected[table]:
                destination_row = actual_by_id.get(source_row['id'])
                if destination_row is None or any(
                    _canonical(destination_row.get(field)) != _canonical(source_row.get(field))
                    for field in fields
                ):
                    raise CommandError(
                        f'Post-write reconciliation failed for {table} ID {source_row["id"]}.'
                    )

    def _report(self, expected, actual, plans, applied):
        self.stdout.write('Customer data backfill: {}'.format('APPLIED' if applied else 'DRY RUN'))
        for table, fields in (
            ('accounts', ACCOUNT_FIELDS),
            ('addresses', ADDRESS_FIELDS),
            ('tickets', TICKET_FIELDS),
            ('messages', MESSAGE_FIELDS),
            ('vendor_favourites', VENDOR_FAVOURITE_FIELDS),
            ('product_favourites', PRODUCT_FAVOURITE_FIELDS),
        ):
            actual_by_id = {row['id']: row for row in actual[table]}
            matching = [
                actual_by_id[row['id']]
                for row in expected[table]
                if row['id'] in actual_by_id
            ]
            self.stdout.write(
                f'{table}: source={len(expected[table])} '
                f'already_matching={len(expected[table]) - len(plans[table])} '
                f'insertable={len(plans[table])} source_checksum={_checksum(expected[table], fields)} '
                f'destination_matching_checksum={_checksum(matching, fields)}'
            )
        if not applied:
            self.stdout.write('No destination rows were written. Re-run with --apply after reviewing this report.')
