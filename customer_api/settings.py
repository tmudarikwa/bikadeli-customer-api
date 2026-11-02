import os
from urllib.parse import urlsplit

from bikadeli_common.settings import (
    configure_database,
    configure_gateway_settings,
    configure_token_verification,
    configure_upstream_url,
)

configure_gateway_settings(globals(), "customer-api")
configure_database(globals(), "customer-api")
configure_token_verification(globals())
configure_upstream_url(globals(), "PRICING_SERVICE_URL", "PRICING_SERVICE_URL")
configure_upstream_url(globals(), "ORDERS_SERVICE_URL", "ORDERS_SERVICE_URL")
configure_upstream_url(globals(), "DRIVER_SERVICE_URL", "DRIVER_SERVICE_URL")
configure_upstream_url(globals(), "VENDOR_SERVICE_URL", "VENDOR_SERVICE_URL")
configure_upstream_url(globals(), "IDENTITY_SERVICE_URL", "IDENTITY_SERVICE_URL")
configure_upstream_url(globals(), "FINANCE_SERVICE_URL", "FINANCE_SERVICE_URL")
configure_upstream_url(globals(), "FINANCE_LOYALTY_CREDIT_URL", "FINANCE_LOYALTY_CREDIT_URL")
ORDERS_CUSTOMER_CANCEL_ENABLED = os.getenv(
    "ORDERS_CUSTOMER_CANCEL_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_WALLET_TRANSFER_ENABLED = os.getenv(
    "FINANCE_WALLET_TRANSFER_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_PAYMENT_INTENTS_ENABLED = os.getenv(
    "FINANCE_PAYMENT_INTENTS_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_WALLET_TOPUP_ENABLED = os.getenv(
    "FINANCE_WALLET_TOPUP_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_PAYNOW_WALLET_TOPUP_ENABLED = os.getenv(
    "FINANCE_PAYNOW_WALLET_TOPUP_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_WALLET_PAYMENT_ENABLED = os.getenv(
    "FINANCE_WALLET_PAYMENT_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
FINANCE_LOYALTY_CREDIT_SECRET = os.getenv("FINANCE_LOYALTY_CREDIT_SECRET", "")
FINANCE_PRIME_ENABLED = os.getenv("FINANCE_PRIME_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
IDENTITY_DRIVER_FCM_TOKEN_ENABLED = os.getenv(
    "IDENTITY_DRIVER_FCM_TOKEN_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
IDENTITY_DRIVER_LOGIN_ENABLED = os.getenv(
    "IDENTITY_DRIVER_LOGIN_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
DRIVER_REGISTRATION_SERVICE_ENABLED = os.getenv(
    "DRIVER_REGISTRATION_SERVICE_ENABLED", "false"
).strip().lower() in {"1", "true", "yes", "on"}
if IDENTITY_DRIVER_FCM_TOKEN_ENABLED and not globals()["IDENTITY_SERVICE_URL"]:
    raise ValueError(
        "IDENTITY_SERVICE_URL is required when driver FCM token routing is enabled."
    )
if IDENTITY_DRIVER_LOGIN_ENABLED and not globals()["IDENTITY_SERVICE_URL"]:
    raise ValueError(
        "IDENTITY_SERVICE_URL is required when driver login routing is enabled."
    )
if DRIVER_REGISTRATION_SERVICE_ENABLED and not globals()["DRIVER_SERVICE_URL"]:
    raise ValueError(
        "DRIVER_SERVICE_URL is required when driver registration routing is enabled."
    )
if FINANCE_PRIME_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError("FINANCE_SERVICE_URL is required when Prime routing is enabled.")
ORDERS_LOYALTY_CALLBACK_SECRET = os.getenv("ORDERS_LOYALTY_CALLBACK_SECRET", "")
UPSTREAM_TIMEOUT_SECONDS = float(os.getenv("UPSTREAM_TIMEOUT_SECONDS", "5"))
GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY", "").strip()
if not DEBUG and not ORDERS_SERVICE_URL:
    raise ValueError("ORDERS_SERVICE_URL must be configured.")
if ORDERS_CUSTOMER_CANCEL_ENABLED and not ORDERS_SERVICE_URL:
    raise ValueError("ORDERS_SERVICE_URL is required when customer cancellation is enabled.")
if FINANCE_WALLET_TRANSFER_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError(
        "FINANCE_SERVICE_URL is required when wallet transfer routing is enabled."
    )
if FINANCE_PAYMENT_INTENTS_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError(
        "FINANCE_SERVICE_URL is required when payment intent routing is enabled."
    )
if FINANCE_WALLET_TOPUP_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError(
        "FINANCE_SERVICE_URL is required when wallet top-up routing is enabled."
    )
if FINANCE_PAYNOW_WALLET_TOPUP_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError(
        "FINANCE_SERVICE_URL is required when PayNow wallet top-up routing is enabled."
    )
if FINANCE_WALLET_PAYMENT_ENABLED and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError(
        "FINANCE_SERVICE_URL is required when wallet payment routing is enabled."
    )
if not DEBUG and not PRICING_SERVICE_URL:
    raise ValueError("PRICING_SERVICE_URL must be configured.")
if not DEBUG and not VENDOR_SERVICE_URL:
    raise ValueError("VENDOR_SERVICE_URL must be configured.")
if not DEBUG and not IDENTITY_SERVICE_URL:
    raise ValueError("IDENTITY_SERVICE_URL must be configured.")
if not DEBUG and not globals()["FINANCE_SERVICE_URL"]:
    raise ValueError("FINANCE_SERVICE_URL must be configured.")
if not FINANCE_LOYALTY_CREDIT_URL:
    FINANCE_LOYALTY_CREDIT_URL = f"{FINANCE_SERVICE_URL}/api/v1/internal/finance/wallet/loyalty-credit/" if FINANCE_SERVICE_URL else ""
if FINANCE_LOYALTY_CREDIT_URL:
    finance_loyalty_url = urlsplit(FINANCE_LOYALTY_CREDIT_URL)
    if not DEBUG and finance_loyalty_url.scheme != "https":
        raise ValueError("FINANCE_LOYALTY_CREDIT_URL must use HTTPS in production.")
if not DEBUG and (len(FINANCE_LOYALTY_CREDIT_SECRET) < 32 or len(ORDERS_LOYALTY_CALLBACK_SECRET) < 32):
    raise ValueError("Loyalty service callback secrets must contain at least 32 characters.")

ROOT_URLCONF = "customer_api.urls"
WSGI_APPLICATION = "customer_api.wsgi.application"
ASGI_APPLICATION = "customer_api.asgi.application"
DATABASE_READINESS_CHECK = True
INSTALLED_APPS = [
    "rest_framework",
    "customer_accounts.apps.CustomerAccountsConfig",
]
REST_FRAMEWORK = {
    "UNAUTHENTICATED_USER": None,
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "bikadeli_common.authentication.AccessTokenAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_THROTTLE_RATES": {
        "mutation": "60/hour",
    },
}
