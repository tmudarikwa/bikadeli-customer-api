# Customer API

The customer API owns saved customer addresses, customer-facing support-ticket create/list/message-read/reply workflows, product/vendor favourites, and customer map-tile access in its own service. These endpoints use `customer_accounts.CustomerAccount` and service-owned records; `owner_user_id` is an external identity reference, not a user-table foreign key, and favourite vendor/product IDs are external references resolved through vendor-api. Customer registration/login, shared auth login/logout/token refresh, email verification/resend, account-deletion request/cancellation, and basic identity profile reads/updates are routed to `identity-service`. Parcel and extracted food cart/checkout/order routes go to `orders-service`; customer food-order cancellation is routed there only when `ORDERS_CUSTOMER_CANCEL_ENABLED=true`. Pricing estimates and delivery-zone checks go to `pricing-service`; marketplace product/category reads, public vendor listing/detail, public menu reads, and the legacy vendor menu-management paths go to `vendor-api`. Legacy wallet balance and transaction GET requests go to `finance-service`; wallet mutations, payment transactions, and Prime subscriptions have Finance routes behind off-by-default gates and remain on the monolith by default. Support-ticket, favourite, and map-tile routes are local and excluded from the compatibility catch-all, so unsupported subpaths return 404 instead of silently proxying to the monolith. Favourite product metadata and images are resolved in bounded batches through vendor-api. Guest map access validates its opaque token through orders-service; Google Maps credentials remain server-side in customer-api. A ticket's optional order reference is checked through the authenticated orders-service detail API. Service-owned routes do not fall back to the backend when their service URL is missing. Remaining monolith-owned APIs include payment transactions, wallet mutations, referral, internal support notes, staff support-management workflows, and legacy customer/order paths not listed above. Loyalty balance and redemption plus their transaction records are customer-api-owned; the existing mobile balance route `/api/v1/customers/loyalty/` is retained as an alias. Redemption credits are delivered asynchronously through finance-service.

Prime plan/status/subscribe/cancel and EcoCash payment initiation use `FINANCE_PRIME_ENABLED` to select Finance; keep it false until payment records and subscription history are reconciled and order services consume the same Prime entitlement owner. Payment-status reads and the signed PayNow callback stay pinned to Finance even when new Prime routing is off, allowing pending Finance attempts to settle. Finance accepts the legacy PayNow provider reference for a paid payment and verifies the reference, customer, and plan amount. New EcoCash attempts are idempotent and become paid only after Finance validates the signed callback and polls PayNow for the stored reference and exact amount. Configure the provider's HTTPS result URL to reach `/api/v1/subscription/paynow/callback/` through customer-api before enabling `FINANCE_PAYNOW_PRIME_ENABLED` in Finance. The historical subscription importer is dry-run by default.

## Customer loyalty

`GET /api/v1/customers/loyalty/` and its `/balance/` alias return the authenticated customer's points, wallet credit value, and conversion ratio. `GET /api/v1/customers/loyalty/transactions/` returns that customer's paginated earning/redemption history (`page` defaults to 1; `page_size` defaults to 20 and is capped at 100). `POST /api/v1/customers/loyalty/redeem/` debits points idempotently using `Idempotency-Key`, records a pending redemption and an outbox event, then relies on `deliver_loyalty_wallet_credits` to post a signed, retryable credit to finance-service. Configure `FINANCE_LOYALTY_CREDIT_SECRET` to match finance-service's `LOYALTY_CREDIT_CALLBACK_SECRET`; the callback URL defaults to the finance internal wallet-credit endpoint.

Delivered, paid food-order awards are accepted through a signed internal callback from orders-service. Service-owned driver completion queues base-multiplier awards; Prime entitlement lookup is not service-owned yet. The backend now contains a durable, signed lifecycle relay for legacy order updates, but it is disabled pending order-state reconciliation and removal of the monolith loyalty writer; do not enable both award writers. Schedule the award worker only after its peer URL/secret is configured and monitor failures. `backfill_customer_loyalty` dry-runs by default and reads the legacy customer profile and loyalty transaction tables; review its reconciliation report before any separately approved `--apply`. No production backfill or cutover was performed.

## Vendor favourites

| Method | Local route | Behavior |
| --- | --- | --- |
| `GET`, `POST`, `DELETE` | `/api/v1/customers/vendor-favourites/` | List, add, or remove the authenticated customer's saved vendor IDs. |

List responses retain the legacy `{results: [...]}` shape and resolve vendor names in bounded batches from vendor-api. Add validates that the vendor exists. Vendor-service errors return `503`; customer-api does not create or serve vendor favourites from an incomplete lookup. The customer database stores the vendor ID as an external scalar reference, not a foreign key.

## Product favourites

| Method | Local route | Behavior |
| --- | --- | --- |
| `GET`, `POST`, `DELETE` | `/api/v1/customers/favourites/` | List, add, or remove the authenticated customer's saved product IDs. |

List responses retain the legacy `{results: [...]}` shape and product fields (`product_id`, `product_name`, `product_price`, `product_image`, and `created_at`). Vendor-api resolves product metadata in batches of at most 200 IDs. Add validates that the product exists; vendor-service errors or incomplete favourite data return `503`, and unknown products return `404`. Product IDs remain external scalar references, not cross-service foreign keys.

## Customer support tickets

| Method | Local route | Behavior |
| --- | --- | --- |
| `GET`, `POST` | `/api/v1/customers/support-tickets/` | List the authenticated customer's tickets or create one (creation also creates the first customer message). |
| `GET` | `/api/v1/customers/support-tickets/<id>/messages/` | Read messages for an owned ticket. |
| `POST` | `/api/v1/customers/support-tickets/<id>/reply/` | Add a customer reply; reopening a resolved/closed ticket moves it to `IN_PROGRESS`. |

All three routes require the existing authenticated access token and return `404` for another customer's ticket. Ticket creation preserves `order`, `subject`, `description`, `category`, and `priority`; replies accept `message` up to 5,000 characters. The customer contract has no ticket-detail, ticket-update/delete, or attachment endpoint.

From the workspace root:

```powershell
docker build -f customer_api/Dockerfile -t bikadeli-customer-api:local .
```

Configure `DJANGO_SECRET_KEY`, `DATABASE_URL`, `JWT_PUBLIC_KEYS_JSON`, `JWT_ISSUER`, `IDENTITY_SERVICE_URL`, `PRICING_SERVICE_URL`, `ORDERS_SERVICE_URL`, `VENDOR_SERVICE_URL`, `FINANCE_SERVICE_URL`, and `ALLOWED_HOSTS`. Production settings require all five service URLs, an issuer, and RSA public verification keys. RS256 requests are checked against identity-service's persisted session endpoint; keep `JWT_VALIDATE_IDENTITY_SESSIONS` enabled and provide the identity base URL over HTTPS. Never provide identity-service's private signing key to customer-api. Keep overlapping public keys in the map during rotation. Local Compose uses the shared development HS256 key only with `DJANGO_DEBUG=true`. Run `python customer_api/manage.py migrate` when provisioning the customer database. `/health/` checks process liveness; `/health/ready/` checks the local database.

Set `GOOGLE_MAPS_API_KEY` in customer-api to enable `GET /api/v1/customers/map/tiles/<z>/<x>/<y>/`. Only customer access tokens or valid guest tracking tokens are accepted. Guest tokens are validated by orders-service through `/api/v1/orders/guest-token/validate/`; tile coordinates are bounded to zoom 0�22 and valid tile ranges.

The production JWT integration validates identity-issued RS256 tokens against configured public keys, so customer-api cannot mint identity tokens. Identity registration/login routing still requires the identity data backfill and compatibility validation before production traffic is switched.

## Customer address backfill

The `backfill_customer_data` command copies customer-profile identities, saved addresses, customer support tickets, public ticket messages, and product/vendor favourites from `customers_customerprofile`, `customers_customeraddress`, `customers_customersupportticket`, `customers_customerticketmessage`, `customers_customerfavourite`, and `customers_customervendorfavourite`. It preserves IDs, customer/ticket ownership, external product/vendor IDs, order IDs, timestamps, and ticket/message fields. Staff user references such as `assigned_to` and favourite product/vendor IDs are retained as external IDs and are not user-table, product-table, or vendor-table foreign keys. It expects a PostgreSQL/PostGIS source for the current address schema; SQLite is supported for isolated tests and older latitude/longitude source schemas. It does not copy unrelated profile fields, notifications, devices, reviews, internal support notes, loyalty points, orders, or payment details. Loyalty balances and history have a separate `backfill_customer_loyalty` command.

Set `SOURCE_DATABASE_URL` to a read-only monolith database connection and `DATABASE_URL` to a distinct customer database. Run a dry-run first:

```powershell
python customer_api/manage.py backfill_customer_data
```

After reviewing the counts and SHA-256 checksums against the intended source/destination, explicitly apply the transactional, insert-only copy:

```powershell
python customer_api/manage.py backfill_customer_data --apply
```

The command rejects same-database targets, conflicting IDs/owners, missing customer/ticket references, and invalid coordinates. It never updates existing rows; each table report includes SHA-256 checksums and repeat applications are insert-only/idempotent. `backfill_customer_addresses` remains as a compatibility alias for existing operators. No production backfill, migration, or traffic change is part of this extraction.

**Attachment limitation:** the customer ticket serializer and customer routes do not expose attachments. The separate backend staff upload (`dashboard.views.support_portal.support_ticket_attachments`) requires admin authentication plus support-write authorization, accepts multipart `file` uploads (up to five per request, 5 MB each; JPEG/PNG/WebP/PDF), and writes to `support-attachments/customer/<ticket-id>/<uuid>.<ext>` using Django `default_storage`. Backend `default_storage` is configured as private S3-compatible `ImageMediaStorage` when `USE_S3_MEDIA` is enabled, otherwise filesystem storage under `MEDIA_ROOT`; it also generates backend storage URLs. Customer-api has no corresponding storage configuration, bucket credentials/object-access contract, safe URL-signing behavior, or equivalent upload-validation/authorization workflow. Therefore attachment metadata and bytes are not backfilled or served here, and attachment subpaths do not fall through to the monolith. Existing attachment records/files and staff upload/view/audit behavior remain backend-owned until storage ownership, authorized URL delivery, and a safe transfer plan are defined. Internal notes and other staff ticket-management operations remain backend-owned too.

Run service tests and static checks from `customer-api`:

```powershell
python manage.py test
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check .
docker build -f Dockerfile -t bikadeli-customer-api:local ..
```


## Customer loyalty

Customer-api owns the loyalty point balance and auditable earn/redeem history. The authenticated balance and redemption endpoints preserve the legacy response fields and contract:

- `GET /api/v1/customers/loyalty/balance/` returns `points`, `wallet_credit_value`, and `points_per_wallet_dollar` (100 points per wallet dollar).
- `POST /api/v1/customers/loyalty/redeem/` accepts `{"points": 200}` and requires a unique `Idempotency-Key` of 1-64 characters. Points must be at least 100 and redeemed in multiples of 100. The points debit and finance-credit outbox event are committed together. A retry with the same key and request returns the existing redemption; reusing the key for a different amount returns `409`. The legacy `points_redeemed`, `wallet_credit`, and `points_balance` fields remain, with `wallet_credit_status` exposing the asynchronous finance delivery state.
- Internal `POST /internal/v1/customers/loyalty/orders/award/` accepts only signed order events. Award amount is `floor(max(subtotal - discount_amount, 0))` points; the trusted orders callback supplies the equivalent `eligible_spend`, and a multiplier of two represents the legacy active-Prime double-points rule. Non-customer JWT roles cannot read or redeem a customer's points. Order IDs and identity IDs are scalar external references, not foreign keys.

Orders-service must send qualifying food-order lifecycle changes to `POST /internal/v1/orders/<id>/lifecycle/`, then its `deliver_customer_loyalty_awards` worker sends the durable event to customer-api. The customer receiver authenticates the raw callback body with `X-Loyalty-Timestamp` and `X-Loyalty-Signature` (HMAC-SHA256, five-minute clock window, 4096-byte limit). The order/event receipt and earn ledger are idempotent even when retries arrive after a lost acknowledgment.

Redemption writes a customer-api outbox row in the same transaction as the point debit. Schedule `python manage.py deliver_loyalty_wallet_credits` periodically. It signs and retries requests to finance-service with exponential backoff; the redemption remains `PENDING` until finance acknowledges the idempotent wallet credit. Configure `FINANCE_LOYALTY_CREDIT_URL` (defaults to the finance-service callback under `FINANCE_SERVICE_URL`), `FINANCE_LOYALTY_CREDIT_SECRET`, and `ORDERS_LOYALTY_CALLBACK_SECRET`; callback secrets must be at least 32 characters in production and shared only between the named services. No cross-service database transaction is claimed.

### Loyalty history backfill

`backfill_customer_loyalty` reads legacy `customers_customerprofile` balances and `customers_loyaltytransaction` history, preserving owner IDs, transaction IDs as `source_legacy_id`, external order IDs, points, wallet credit, idempotency keys, and timestamps. It is dry-run by default and insert-only on `--apply`; conflicting existing balances or transaction IDs fail preflight. Set distinct `SOURCE_DATABASE_URL` and `DATABASE_URL`, inspect the dry-run results, and use `--apply` only after separately approved reconciliation. This task did not run a production backfill, migrations, or traffic cutover.

**Remaining dependencies:** the existing order lifecycle owner still needs to call orders-service's signed lifecycle endpoint after every delivery/payment status transition. That trusted caller must calculate whether legacy Prime is active and pass `prime_multiplier=2` when it is; absent this producer/entitlement integration, no events arrive and Prime doubling cannot be inferred locally. Finance-service currently credits its own wallet account/read model; existing monolith wallet mutations and balances remain separately owned, so this does not synchronize legacy wallet balances or establish full wallet-domain independence.
