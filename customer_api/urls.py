import json

from bikadeli_common.gateway import (
    liveness,
    proxy_to_driver_service_path,
    proxy_to_finance_service,
    proxy_to_identity_service,
    proxy_to_identity_service_path,
    proxy_to_monolith,
    proxy_to_orders_service,
    proxy_to_pricing_service,
    proxy_to_vendor_service,
    readiness,
    service_metadata_view,
)
from django.conf import settings
from django.http import JsonResponse
from django.urls import include, path, re_path
from django.views.decorators.csrf import csrf_exempt

from customer_accounts.map_tiles import customer_map_tile


@csrf_exempt
def proxy_wallet_reads(request, *args, **kwargs):
    if request.method == "GET":
        return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_order_cancel(request, *args, **kwargs):
    if settings.ORDERS_CUSTOMER_CANCEL_ENABLED:
        return proxy_to_orders_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_wallet_transfer(request, *args, **kwargs):
    if settings.FINANCE_WALLET_TRANSFER_ENABLED:
        return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_payment_intent(request, *args, **kwargs):
    if settings.FINANCE_PAYMENT_INTENTS_ENABLED:
        return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_wallet_topup(request, *args, **kwargs):
    if (
        request.method == "POST"
        and request.content_type == "application/json"
    ):
        try:
            payload = json.loads(request.body)
            gateway = payload.get("gateway") if isinstance(payload, dict) else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            gateway = None
        if gateway == "stripe" and settings.FINANCE_WALLET_TOPUP_ENABLED:
            return proxy_to_finance_service(request, *args, **kwargs)
        if (
            gateway in {"ecocash", "paynow"}
            and settings.FINANCE_PAYNOW_WALLET_TOPUP_ENABLED
        ):
            return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_wallet_payment(request, *args, **kwargs):
    if request.method == "POST" and settings.FINANCE_WALLET_PAYMENT_ENABLED:
        return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_customer_prime(request, *args, **kwargs):
    path_info = request.path_info.rstrip("/")
    if path_info.endswith("/paynow/callback") or "/payment-status/" in path_info:
        return proxy_to_finance_service(request, *args, **kwargs)
    if path_info.endswith("/payment") and not settings.FINANCE_PRIME_ENABLED:
        return JsonResponse(
            {"detail": "Prime payment initiation is not enabled."},
            status=503,
        )
    if settings.FINANCE_PRIME_ENABLED:
        return proxy_to_finance_service(request, *args, **kwargs)
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_driver_fcm_token(request, *args, **kwargs):
    if settings.IDENTITY_DRIVER_FCM_TOKEN_ENABLED:
        return proxy_to_identity_service_path(
            request,
            "/api/v1/drivers/profile/update_fcm_token/",
        )
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_driver_login(request, *args, **kwargs):
    if settings.IDENTITY_DRIVER_LOGIN_ENABLED:
        return proxy_to_identity_service_path(request, "/api/v1/auth/login/")
    return proxy_to_monolith(request, *args, **kwargs)


@csrf_exempt
def proxy_driver_registration(request, *args, **kwargs):
    if settings.DRIVER_REGISTRATION_SERVICE_ENABLED:
        return proxy_to_driver_service_path(
            request,
            "/api/v1/drivers/auth/register/",
        )
    return proxy_to_monolith(request, *args, **kwargs)


urlpatterns = [
    path('internal/service-metadata/', service_metadata_view, name='customer-service-metadata'),
    re_path(
        r"^api/v1/subscription/(?:plans|status|subscribe|cancel|payment|payment-status/[^/]+|paynow/callback)/?$",
        proxy_customer_prime,
        name="finance-service-prime",
    ),
    path("health/", liveness, name="health-liveness"),
    path("health/ready/", readiness, name="health-readiness"),
    path("", include("customer_accounts.urls")),
    path(
        "api/v1/customers/map/tiles/<int:z>/<int:x>/<int:y>/",
        customer_map_tile,
        name="customer-map-tiles",
    ),
    re_path(
        r"^api/v1/(?:auth/(?:register|login|logout|logout-all|token/refresh)|customers/(?:register|login|verify-email|resend-verification)|user/(?:request-deletion|cancel-deletion))/?$",
        proxy_to_identity_service,
        name="identity-service-auth",
    ),
    re_path(
        r"^api/v1/profile(?:/.*)?$",
        proxy_to_identity_service,
        name="identity-service-profile",
    ),
    re_path(
        r"^(?:api/v1/)?drivers/profile/update_fcm_token/?$",
        proxy_driver_fcm_token,
        name="identity-service-driver-fcm-token",
    ),
    path("auth/login/", proxy_driver_login, name="identity-service-driver-login"),
    path(
        "drivers/auth/register/",
        proxy_driver_registration,
        name="driver-service-registration",
    ),
    re_path(
        r"^api/v1/pricing/estimate/$",
        proxy_to_pricing_service,
        name="pricing-service-estimate",
    ),
    re_path(
        r"^api/v1/orders/parcels/(?:pricing|sizes/pricing)/$",
        proxy_to_pricing_service,
        name="pricing-service-parcel-pricing",
    ),
    re_path(
        r"^api/v1/orders/parcels(?:/.*)?$",
        proxy_to_orders_service,
        name="orders-service-parcel-proxy",
    ),
    re_path(
        r"^api/v1/orders/[0-9]+/cancel/$",
        proxy_customer_order_cancel,
        name="orders-service-customer-cancel",
    ),
    re_path(
        r"^api/v1/orders(?:/(?:cart(?:/.*)?|checkout|[0-9]+))?/?$",
        proxy_to_orders_service,
        name="orders-service-food-proxy",
    ),
    re_path(
        r"^api/v1/marketplace/(?:products|categories)(?:/.*)?$",
        proxy_to_vendor_service,
        name="vendor-service-marketplace-proxy",
    ),
    re_path(
        r"^api/v1/wallet/(?:balance|transactions)/?$",
        proxy_wallet_reads,
        name="finance-service-wallet-read",
    ),
    re_path(
        r"^api/v1/wallet/transfer/?$",
        proxy_customer_wallet_transfer,
        name="finance-service-wallet-transfer",
    ),
    re_path(
        r"^api/v1/wallet/top-up/?$",
        proxy_customer_wallet_topup,
        name="finance-service-wallet-topup",
    ),
    re_path(
        r"^api/v1/wallet/pay/?$",
        proxy_customer_wallet_payment,
        name="finance-service-wallet-payment",
    ),
    re_path(
        r"^api/v1/wallet/recipient/(?P<user_id>[0-9]+)/?$",
        proxy_customer_wallet_transfer,
        name="finance-service-wallet-recipient",
    ),
    re_path(
        r"^api/v1/payments/transactions/create-payment-intent/$",
        proxy_customer_payment_intent,
        name="finance-service-payment-intent",
    ),
    re_path(
        r"^api/v1/payments/transactions/(?P<order_id>[0-9]+)/confirm-stripe-payment/$",
        proxy_customer_payment_intent,
        name="finance-service-payment-confirm",
    ),
    re_path(
        r"^api/v1/vendors/public/vendors(?:/.*)?$",
        proxy_to_vendor_service,
        name="vendor-service-public-vendors-proxy",
    ),
    re_path(
        r"^api/v1/vendors/public/menu-items(?:/.*)?$",
        proxy_to_vendor_service,
        name="vendor-service-public-menu-proxy",
    ),
    re_path(
        r"^api/v1/vendors/(?:menu-images/[0-9]+/file|product-images/[0-9]+/file)/$",
        proxy_to_vendor_service,
        name="vendor-service-image-proxy",
    ),
    re_path(
        r"^api/v1/vendors/menu(?:/.*)?$",
        proxy_to_vendor_service,
        name="vendor-service-menu-management-proxy",
    ),
    re_path(
        r"^api/v1/delivery-zones/check/$",
        proxy_to_pricing_service,
        name="pricing-service-delivery-zone-check",
    ),
    re_path(
        r"^api/v1/(?:customers(?!/addresses(?:/|$)|/support-tickets(?:/|$)|/vendor-favourites(?:/|$)|/favourites(?:/|$)|/map/tiles(?:/|$)|/(?:register|login)(?:/|$))|orders(?!/parcels(?:/|$))|payments/transactions|wallet|auth/referral(?:/list|/apply)?|subscription/(?:plans|status|subscribe|cancel|payment|payment-status|paynow/callback))(?:/.*)?$",
        proxy_to_monolith,
        name="customer-api-proxy",
    ),
]
