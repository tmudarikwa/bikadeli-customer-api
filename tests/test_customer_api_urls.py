import json
from unittest.mock import patch

import httpx
from bikadeli_common.gateway import (
    proxy_to_driver_service_path,
    proxy_to_identity_service,
    proxy_to_monolith,
    proxy_to_orders_service,
    proxy_to_pricing_service,
    proxy_to_vendor_service,
    readiness,
)
from django.http import HttpResponse
from django.test import Client, RequestFactory, TestCase, override_settings
from django.urls import Resolver404, resolve

from customer_api.urls import proxy_customer_order_cancel


class CustomerApiUrlTests(TestCase):
    urlconf = "customer_api.urls"

    def test_customer_routes_are_routed_but_callbacks_are_not(self):
        self.assertEqual(
            resolve(
                "/api/v1/orders/42/cancel/", urlconf=self.urlconf
            ).url_name,
            "orders-service-customer-cancel",
        )
        self.assertEqual(
            resolve("/api/v1/customers/addresses/", urlconf=self.urlconf).url_name,
            "address-list",
        )
        self.assertEqual(
            resolve(
                "/api/v1/customers/vendor-favourites/", urlconf=self.urlconf
            ).url_name,
            "vendor-favourites",
        )
        self.assertEqual(
            resolve("/api/v1/customers/favourites/", urlconf=self.urlconf).url_name,
            "product-favourites",
        )
        self.assertEqual(
            resolve(
                "/api/v1/customers/map/tiles/2/1/3/", urlconf=self.urlconf
            ).url_name,
            "customer-map-tiles",
        )
        self.assertEqual(
            resolve(
                "/api/v1/customers/support-tickets/", urlconf=self.urlconf
            ).url_name,
            "support-ticket-list-create",
        )
        self.assertEqual(
            resolve(
                "/api/v1/customers/support-tickets/12/messages/", urlconf=self.urlconf
            ).url_name,
            "support-ticket-messages",
        )
        self.assertEqual(
            resolve(
                "/api/v1/customers/support-tickets/12/reply/", urlconf=self.urlconf
            ).url_name,
            "support-ticket-reply",
        )
        self.assertEqual(
            resolve("/api/v1/customers/register/", urlconf=self.urlconf).url_name,
            "identity-service-auth",
        )
        self.assertEqual(
            resolve("/api/v1/customers/login/", urlconf=self.urlconf).url_name,
            "identity-service-auth",
        )
        for path in (
            "/api/v1/customers/verify-email/",
            "/api/v1/customers/resend-verification/",
            "/api/v1/user/request-deletion/",
            "/api/v1/user/cancel-deletion/",
        ):
            with self.subTest(path=path):
                self.assertEqual(
                    resolve(path, urlconf=self.urlconf).url_name,
                    "identity-service-auth",
                )
        self.assertEqual(
            resolve("/api/v1/auth/token/refresh/", urlconf=self.urlconf).url_name,
            "identity-service-auth",
        )
        self.assertEqual(
            resolve("/api/v1/auth/logout-all/", urlconf=self.urlconf).url_name,
            "identity-service-auth",
        )
        self.assertEqual(
            resolve("/api/v1/profile/me/", urlconf=self.urlconf).url_name,
            "customer-profile-me",
        )
        self.assertEqual(
            resolve(
                "/drivers/profile/update_fcm_token/",
                urlconf=self.urlconf,
            ).url_name,
            "identity-service-driver-fcm-token",
        )
        self.assertEqual(
            resolve("/auth/login/", urlconf=self.urlconf).url_name,
            "identity-service-driver-login",
        )
        self.assertEqual(
            resolve("/drivers/auth/register/", urlconf=self.urlconf).url_name,
            "driver-service-registration",
        )
        self.assertEqual(
            resolve("/api/v1/orders/cart/", urlconf=self.urlconf).url_name,
            "orders-service-food-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/orders/checkout/", urlconf=self.urlconf).url_name,
            "orders-service-food-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/orders/42/cancel/", urlconf=self.urlconf).url_name,
            "orders-service-customer-cancel",
        )
        self.assertEqual(
            resolve("/api/v1/orders/", urlconf=self.urlconf).url_name,
            "orders-service-food-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/pricing/estimate/", urlconf=self.urlconf).url_name,
            "pricing-service-estimate",
        )
        self.assertEqual(
            resolve("/api/v1/orders/parcels/pricing/", urlconf=self.urlconf).url_name,
            "pricing-service-parcel-pricing",
        )
        self.assertEqual(
            resolve("/api/v1/orders/parcels/create/", urlconf=self.urlconf).url_name,
            "orders-service-parcel-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/marketplace/products/", urlconf=self.urlconf).url_name,
            "vendor-service-marketplace-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/marketplace/categories/", urlconf=self.urlconf).url_name,
            "vendor-service-marketplace-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/balance/", urlconf=self.urlconf).url_name,
            "finance-service-wallet-read",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/transactions", urlconf=self.urlconf).url_name,
            "finance-service-wallet-read",
        )
        self.assertEqual(
            resolve("/api/v1/vendors/public/vendors/", urlconf=self.urlconf).url_name,
            "vendor-service-public-vendors-proxy",
        )
        self.assertEqual(
            resolve(
                "/api/v1/vendors/public/vendors/42/", urlconf=self.urlconf
            ).url_name,
            "vendor-service-public-vendors-proxy",
        )
        self.assertEqual(
            resolve(
                "/api/v1/vendors/product-images/42/file/", urlconf=self.urlconf
            ).url_name,
            "vendor-service-image-proxy",
        )
        self.assertEqual(
            resolve(
                "/api/v1/vendors/menu-images/42/file/", urlconf=self.urlconf
            ).url_name,
            "vendor-service-image-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/vendors/menu/add-item/", urlconf=self.urlconf).url_name,
            "vendor-service-menu-management-proxy",
        )
        self.assertEqual(
            resolve(
                "/api/v1/vendors/public/menu-items/42/", urlconf=self.urlconf
            ).url_name,
            "vendor-service-public-menu-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/top-up/", urlconf=self.urlconf).url_name,
            "finance-service-wallet-topup",
        )
        self.assertEqual(
            resolve("/api/v1/subscription/status/", urlconf=self.urlconf).url_name,
            "finance-service-prime",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/transfer/", urlconf=self.urlconf).url_name,
            "finance-service-wallet-transfer",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/recipients/", urlconf=self.urlconf).url_name,
            "customer-api-proxy",
        )
        self.assertEqual(
            resolve("/api/v1/wallet/recipient/202/", urlconf=self.urlconf).url_name,
            "finance-service-wallet-recipient",
        )
        self.assertEqual(
            resolve("/api/v1/delivery-zones/check/", urlconf=self.urlconf).url_name,
            "pricing-service-delivery-zone-check",
        )
        self.assertEqual(
            resolve(
                "/api/v1/orders/parcels/sizes/pricing/", urlconf=self.urlconf
            ).url_name,
            "pricing-service-parcel-pricing",
        )
        with self.assertRaises(Resolver404):
            resolve("/api/v1/payments/provider-callback/", urlconf=self.urlconf)

    def test_address_paths_are_not_forwarded_to_the_monolith(self):
        with override_settings(MONOLITH_BASE_URL="https://backend.example"):
            response = Client().get("/api/v1/customers/addresses/")
        self.assertEqual(response.status_code, 401)

    def test_vendor_favourites_are_not_forwarded_to_the_monolith(self):
        with override_settings(MONOLITH_BASE_URL="https://backend.example"):
            response = Client().get("/api/v1/customers/vendor-favourites/")
        self.assertEqual(response.status_code, 401)

    def test_product_favourites_are_not_forwarded_to_the_monolith(self):
        with override_settings(MONOLITH_BASE_URL="https://backend.example"):
            response = Client().get("/api/v1/customers/favourites/")
        self.assertEqual(response.status_code, 401)

    def test_map_tile_paths_are_not_forwarded_to_the_monolith(self):
        with override_settings(MONOLITH_BASE_URL="https://backend.example"):
            response = Client().get("/api/v1/customers/map/tiles/2/1/3/")
            unsupported = Client().get("/api/v1/customers/map/tiles/invalid/")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(unsupported.status_code, 404)

    def test_support_ticket_paths_are_not_forwarded_to_the_monolith(self):
        with override_settings(MONOLITH_BASE_URL="https://backend.example"):
            response = Client().get("/api/v1/customers/support-tickets/")
            unsupported_attachment = Client().get(
                "/api/v1/customers/support-tickets/12/attachments/"
            )
        self.assertEqual(response.status_code, 401)
        self.assertEqual(unsupported_attachment.status_code, 404)

    def test_health_endpoints(self):
        client = Client()
        self.assertEqual(client.get("/health/").status_code, 200)
        with patch("bikadeli_common.gateway.connection.cursor") as cursor:
            response = client.get("/health/ready/")

        self.assertEqual(response.status_code, 200)
        cursor.return_value.__enter__.return_value.execute.assert_called_once_with(
            "SELECT 1"
        )

    @override_settings(
        MONOLITH_BASE_URL="https://backend.example", DATABASE_READINESS_CHECK=False
    )
    def test_readiness_requires_healthy_upstream(self):
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(200))
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = readiness(RequestFactory().get("/health/ready/"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(json.loads(response.content)["status"], "ready")

    @override_settings(MONOLITH_BASE_URL="https://backend.example")
    def test_proxy_forwards_request_and_relays_response(self):
        request = RequestFactory().post(
            "/api/v1/customers/support-tickets/?source=mobile",
            data=b'{"item":"example"}',
            content_type="application/json",
            HTTP_AUTHORIZATION="Bearer test-token",
            HTTP_X_REQUEST_ID="request-123",
        )
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["method"] = upstream_request.method
            received["body"] = upstream_request.read()
            received["authorization"] = upstream_request.headers.get("authorization")
            received["forwarded_for"] = upstream_request.headers.get("x-forwarded-for")
            return httpx.Response(
                201,
                headers=[
                    ("content-type", "application/json"),
                    ("set-cookie", "sessionid=example; HttpOnly; Path=/"),
                ],
                stream=httpx.ByteStream(b'{"created":true}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_monolith(request)

        self.assertEqual(
            received["url"],
            "https://backend.example/api/v1/customers/support-tickets/?source=mobile",
        )
        self.assertEqual(received["method"], "POST")
        self.assertEqual(received["body"], b'{"item":"example"}')
        self.assertEqual(received["authorization"], "Bearer test-token")
        self.assertEqual(received["forwarded_for"], "127.0.0.1")
        self.assertEqual(response.status_code, 201)
        self.assertEqual(b"".join(response.streaming_content), b'{"created":true}')
        self.assertTrue(response.cookies["sessionid"]["httponly"])
        response.close()

    @override_settings(ORDERS_CUSTOMER_CANCEL_ENABLED=True)
    def test_customer_cancel_proxy_uses_orders_service_when_enabled(self):
        request = RequestFactory().post(
            "/api/v1/orders/42/cancel/", data=b"{}", content_type="application/json"
        )
        expected = HttpResponse(status=200)
        with patch(
            "customer_api.urls.proxy_to_orders_service", return_value=expected
        ) as service, patch("customer_api.urls.proxy_to_monolith") as monolith:
            response = proxy_customer_order_cancel(request)

        self.assertIs(response, expected)
        service.assert_called_once_with(request)
        monolith.assert_not_called()

    @override_settings(ORDERS_CUSTOMER_CANCEL_ENABLED=False)
    def test_customer_cancel_proxy_preserves_monolith_owner_by_default(self):
        request = RequestFactory().post(
            "/api/v1/orders/42/cancel/", data=b"{}", content_type="application/json"
        )
        expected = HttpResponse(status=200)
        with patch(
            "customer_api.urls.proxy_to_orders_service"
        ) as service, patch(
            "customer_api.urls.proxy_to_monolith", return_value=expected
        ) as monolith:
            response = proxy_customer_order_cancel(request)

        self.assertIs(response, expected)
        service.assert_not_called()
        monolith.assert_called_once_with(request)

    @override_settings(MONOLITH_BASE_URL="https://backend.example")
    def test_upstream_transport_failure_returns_service_unavailable(self):
        request = RequestFactory().get("/api/v1/customers/support-tickets/")
        real_client = httpx.Client
        transport = httpx.MockTransport(
            lambda upstream_request: (_ for _ in ()).throw(
                httpx.ConnectError("connection failed")
            )
        )
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_monolith(request)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"], "Upstream service is unavailable."
        )

    @override_settings(
        ORDERS_SERVICE_URL="https://orders.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_food_order_routes_are_forwarded_to_orders_service(self):
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["body"] = upstream_request.read()
            return httpx.Response(
                201,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"message":"Added to cart"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = Client().post(
                "/api/v1/orders/cart/items/?source=mobile",
                data=b'{"item_id":12,"qty":2}',
                content_type="application/json",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            received["url"],
            "https://orders.example/api/v1/orders/cart/items/?source=mobile",
        )
        self.assertEqual(received["body"], b'{"item_id":12,"qty":2}')
        response.close()

    @override_settings(
        ORDERS_SERVICE_URL="https://orders.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_orders_service_receives_device_id_header(self):
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["device_id"] = upstream_request.headers.get("x-device-id")
            return httpx.Response(
                200, headers={"content-type": "application/json"}, json={}
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = Client().get(
                "/api/v1/orders/?page=2",
                HTTP_X_DEVICE_ID="device-abc",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            received["url"], "https://orders.example/api/v1/orders/?page=2"
        )
        self.assertEqual(received["device_id"], "device-abc")
        response.close()

    @override_settings(PRICING_SERVICE_URL="https://pricing.example")
    def test_pricing_estimate_is_forwarded_to_pricing_service(self):
        request = RequestFactory().get("/api/v1/pricing/estimate/?distance_km=5")
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"vehicle_type":"bike"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_pricing_service(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            received["url"],
            "https://pricing.example/api/v1/pricing/estimate/?distance_km=5",
        )
        self.assertEqual(
            b"".join(response.streaming_content), b'{"vehicle_type":"bike"}'
        )
        response.close()

    @override_settings(
        ORDERS_SERVICE_URL="https://orders.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_parcel_routes_are_forwarded_to_orders_service(self):
        request = RequestFactory().get(
            "/api/v1/orders/parcels/my-parcels/?status=IN_TRANSIT",
            HTTP_AUTHORIZATION="Bearer caller-token",
        )
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["authorization"] = upstream_request.headers.get("authorization")
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"results":[]}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_orders_service(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            received["url"],
            "https://orders.example/api/v1/orders/parcels/my-parcels/?status=IN_TRANSIT",
        )
        self.assertEqual(received["authorization"], "Bearer caller-token")
        self.assertEqual(b"".join(response.streaming_content), b'{"results":[]}')
        response.close()

    @override_settings(
        ORDERS_SERVICE_URL="", MONOLITH_BASE_URL="https://backend.example"
    )
    def test_parcel_routes_do_not_fall_back_to_monolith(self):
        request = RequestFactory().get("/api/v1/orders/parcels/")
        response = proxy_to_orders_service(request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"],
            "Upstream service is not configured.",
        )

    @override_settings(
        VENDOR_SERVICE_URL="https://vendor.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_marketplace_routes_are_forwarded_to_vendor_service(self):
        request = RequestFactory().get("/api/v1/marketplace/products/?category=7")
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"results":[]}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_vendor_service(request)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            received["url"],
            "https://vendor.example/api/v1/marketplace/products/?category=7",
        )
        self.assertEqual(b"".join(response.streaming_content), b'{"results":[]}')
        response.close()

    @override_settings(
        VENDOR_SERVICE_URL="", MONOLITH_BASE_URL="https://backend.example"
    )
    def test_marketplace_routes_do_not_fall_back_to_monolith(self):
        request = RequestFactory().get("/api/v1/marketplace/products/")
        response = proxy_to_vendor_service(request)
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"],
            "Upstream service is not configured.",
        )

    @override_settings(
        FINANCE_SERVICE_URL="https://finance.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_wallet_read_routes_are_forwarded_to_finance_service(self):
        received = []

        def handle_upstream(upstream_request):
            received.append((str(upstream_request.url), upstream_request.method))
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"balance":"25.00"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            responses = [
                Client().get(path)
                for path in (
                    "/api/v1/wallet/balance/?currency=USD",
                    "/api/v1/wallet/transactions/?page=2",
                )
            ]

        self.assertEqual([response.status_code for response in responses], [200, 200])
        self.assertEqual(
            received,
            [
                ("https://finance.example/api/v1/wallet/balance/?currency=USD", "GET"),
                ("https://finance.example/api/v1/wallet/transactions/?page=2", "GET"),
            ],
        )
        for response in responses:
            self.assertEqual(
                b"".join(response.streaming_content), b'{"balance":"25.00"}'
            )
            response.close()

    @override_settings(
        FINANCE_SERVICE_URL="", MONOLITH_BASE_URL="https://backend.example"
    )
    def test_wallet_read_routes_do_not_fall_back_to_monolith(self):
        response = Client().get("/api/v1/wallet/transactions/")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"],
            "Upstream service is not configured.",
        )

    @override_settings(MONOLITH_BASE_URL="https://backend.example")
    def test_wallet_mutations_remain_on_monolith(self):
        received = []

        def handle_upstream(upstream_request):
            received.append((str(upstream_request.url), upstream_request.method))
            return httpx.Response(200, json={"ok": True})

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            responses = [
                Client().post(path, data=b"{}", content_type="application/json")
                for path in (
                    "/api/v1/wallet/balance/",
                    "/api/v1/wallet/top-up/",
                    "/api/v1/wallet/transfer/",
                    "/api/v1/wallet/recipients/",
                )
            ]

        self.assertEqual(
            received,
            [
                ("https://backend.example/api/v1/wallet/balance/", "POST"),
                ("https://backend.example/api/v1/wallet/top-up/", "POST"),
                ("https://backend.example/api/v1/wallet/transfer/", "POST"),
                ("https://backend.example/api/v1/wallet/recipients/", "POST"),
            ],
        )
        self.assertEqual([response.status_code for response in responses], [200] * 4)
        for response in responses:
            response.close()

    @override_settings(
        FINANCE_PRIME_ENABLED=True,
        FINANCE_SERVICE_URL="https://finance.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_prime_routes_to_finance_when_enabled(self):
        requests = []
        paths = (
            ("/api/v1/subscription/plans/", "GET"),
            ("/api/v1/subscription/status/", "GET"),
            ("/api/v1/subscription/subscribe/", "POST"),
            ("/api/v1/subscription/cancel/", "POST"),
            ("/api/v1/subscription/payment/", "POST"),
            ("/api/v1/subscription/payment-status/ZDP-9-ABC/", "GET"),
            ("/api/v1/subscription/paynow/callback/", "POST"),
        )

        def handle_upstream(upstream_request):
            requests.append((str(upstream_request.url), upstream_request.method))
            return httpx.Response(200, json={"ok": True})

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            responses = []
            for path, method in paths:
                if method == "GET":
                    responses.append(Client().get(path))
                else:
                    responses.append(
                        Client().post(
                            path,
                            data=b'{"plan":"MONTHLY","payment_reference":"PAYNOW-1"}',
                            content_type="application/json",
                        )
                    )

        self.assertEqual(
            [response.status_code for response in responses],
            [200] * len(paths),
        )
        self.assertEqual(
            requests,
            [
                (f"https://finance.example{path}", method)
                for path, method in paths
            ],
        )
        for response in responses:
            response.close()

    @override_settings(
        FINANCE_PRIME_ENABLED=True,
        FINANCE_SERVICE_URL="https://finance.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_prime_paynow_callback_forwards_signed_raw_body(self):
        received = {}
        body = b"reference=ZDP-9-ABC&status=paid"

        def handle_upstream(upstream_request):
            received["body"] = upstream_request.content
            received["signature"] = upstream_request.headers.get(
                "X-Paynow-Signature"
            )
            received["content_type"] = upstream_request.headers.get("content-type")
            return httpx.Response(200, json={"received": True})

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = Client().post(
                "/api/v1/subscription/paynow/callback/",
                data=body,
                content_type="application/x-www-form-urlencoded",
                HTTP_X_PAYNOW_SIGNATURE="signed-test-callback",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(received["body"], body)
        self.assertEqual(received["signature"], "signed-test-callback")
        self.assertEqual(
            received["content_type"],
            "application/x-www-form-urlencoded",
        )
        response.close()

    @override_settings(
        FINANCE_PRIME_ENABLED=False,
        FINANCE_SERVICE_URL="https://finance.example",
        MONOLITH_BASE_URL="https://backend.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_prime_routes_remain_on_monolith_when_disabled(self):
        requests = []

        def handle_upstream(upstream_request):
            requests.append((str(upstream_request.url), upstream_request.method))
            return httpx.Response(200, json={"ok": True})

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            responses = [
                Client().post(
                    "/api/v1/subscription/subscribe/",
                    data=b'{"plan":"MONTHLY","payment_reference":"PAYNOW-1"}',
                    content_type="application/json",
                ),
                Client().post(
                    "/api/v1/subscription/payment/",
                    data=b'{"plan":"MONTHLY","phone_number":"+263771234567"}',
                    content_type="application/json",
                ),
                Client().get(
                    "/api/v1/subscription/payment-status/ZDP-9-ABC/"
                ),
                Client().post(
                    "/api/v1/subscription/paynow/callback/",
                    data=b"reference=ZDP-9-ABC&status=paid",
                    content_type="application/x-www-form-urlencoded",
                ),
            ]

        self.assertEqual(
            [response.status_code for response in responses],
            [200, 503, 200, 200],
        )
        self.assertEqual(
            requests,
            [
                (
                    "https://backend.example/api/v1/subscription/subscribe/",
                    "POST",
                ),
                (
                    "https://finance.example/api/v1/subscription/payment-status/ZDP-9-ABC/",
                    "GET",
                ),
                (
                    "https://finance.example/api/v1/subscription/paynow/callback/",
                    "POST",
                ),
            ],
        )
        for response in responses:
            response.close()

    @override_settings(
        FINANCE_WALLET_TRANSFER_ENABLED=True,
        FINANCE_SERVICE_URL="https://finance.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_wallet_transfer_routes_to_finance_only_when_enabled(self):
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["method"] = upstream_request.method
            received["idempotency_key"] = upstream_request.headers.get(
                "idempotency-key"
            )
            received["body"] = upstream_request.read()
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"message":"Transfer successful"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = Client().post(
                "/api/v1/wallet/transfer/",
                data=b'{"recipient_id":202,"amount":"25.00"}',
                content_type="application/json",
                HTTP_IDEMPOTENCY_KEY="wallet-transfer-1",
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            received,
            {
                "url": "https://finance.example/api/v1/wallet/transfer/",
                "method": "POST",
                "idempotency_key": "wallet-transfer-1",
                "body": b'{"recipient_id":202,"amount":"25.00"}',
            },
        )
        self.assertEqual(
            b"".join(response.streaming_content),
            b'{"message":"Transfer successful"}',
        )
        response.close()

    @override_settings(
        FINANCE_WALLET_TRANSFER_ENABLED=True,
        FINANCE_SERVICE_URL="https://finance.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_wallet_recipient_lookup_routes_to_finance_when_enabled(self):
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["method"] = upstream_request.method
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"id":202,"name":"Customer Example"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = Client().get("/api/v1/wallet/recipient/202/")

        self.assertEqual(
            received,
            {
                "url": "https://finance.example/api/v1/wallet/recipient/202/",
                "method": "GET",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            b"".join(response.streaming_content),
            b'{"id":202,"name":"Customer Example"}',
        )
        response.close()

    @override_settings(
        VENDOR_SERVICE_URL="https://vendor.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_vendor_public_and_menu_routes_are_forwarded_to_vendor_service(self):
        urls = (
            "/api/v1/vendors/public/vendors/?city=Harare",
            "/api/v1/vendors/public/vendors/42/",
            "/api/v1/vendors/public/menu-items/?vendor_id=42",
            "/api/v1/vendors/menu/add-item/",
        )
        received = []

        def handle_upstream(upstream_request):
            received.append(str(upstream_request.url))
            return httpx.Response(
                200,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"results":[]}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            responses = [Client().get(url) for url in urls]

        self.assertEqual(
            [response.status_code for response in responses], [200] * len(urls)
        )
        self.assertEqual(
            received,
            [
                "https://vendor.example/api/v1/vendors/public/vendors/?city=Harare",
                "https://vendor.example/api/v1/vendors/public/vendors/42/",
                "https://vendor.example/api/v1/vendors/public/menu-items/?vendor_id=42",
                "https://vendor.example/api/v1/vendors/menu/add-item/",
            ],
        )
        for response in responses:
            response.close()

    @override_settings(
        IDENTITY_SERVICE_URL="https://identity.example", UPSTREAM_TIMEOUT_SECONDS=10
    )
    def test_auth_requests_are_forwarded_to_identity_service(self):
        request = RequestFactory().post(
            "/api/v1/customers/register/",
            data=b'{"email":"person@example.test"}',
            content_type="application/json",
        )
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["body"] = upstream_request.read()
            return httpx.Response(
                201,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"message":"Registration successful"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_identity_service(request)

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            received["url"], "https://identity.example/api/v1/customers/register/"
        )
        self.assertEqual(received["body"], b'{"email":"person@example.test"}')
        response.close()

    @override_settings(IDENTITY_DRIVER_FCM_TOKEN_ENABLED=False)
    @patch("customer_api.urls.proxy_to_monolith")
    def test_driver_fcm_route_preserves_legacy_default(self, proxy):
        proxy.return_value = HttpResponse(status=200)
        response = Client().post(
            "/drivers/profile/update_fcm_token/",
            data={"fcm_token": "device-token"},
        )

        self.assertEqual(response.status_code, 200)
        proxy.assert_called_once()

    @override_settings(
        IDENTITY_DRIVER_FCM_TOKEN_ENABLED=True,
        IDENTITY_SERVICE_URL="https://identity.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    @patch("customer_api.urls.proxy_to_identity_service_path")
    def test_driver_fcm_route_can_be_enabled_for_identity(self, proxy):
        proxy.return_value = HttpResponse(status=200)
        response = Client().post(
            "/drivers/profile/update_fcm_token/",
            data={"fcm_token": "device-token"},
        )

        self.assertEqual(response.status_code, 200)
        proxy.assert_called_once_with(
            proxy.call_args.args[0],
            "/api/v1/drivers/profile/update_fcm_token/",
        )

    @override_settings(
        IDENTITY_DRIVER_LOGIN_ENABLED=True,
        IDENTITY_SERVICE_URL="https://identity.example",
    )
    @patch("customer_api.urls.proxy_to_identity_service_path")
    def test_driver_login_alias_rewrites_to_identity_login(self, proxy):
        proxy.return_value = HttpResponse(status=200)
        response = Client().post(
            "/auth/login/",
            data={
                "email": "driver@example.test",
                "password": "pw",
                "user_type": "DRIVER",
            },
        )

        self.assertEqual(response.status_code, 200)
        proxy.assert_called_once_with(
            proxy.call_args.args[0],
            "/api/v1/auth/login/",
        )

    @override_settings(
        DRIVER_REGISTRATION_SERVICE_ENABLED=True,
        DRIVER_SERVICE_URL="https://driver.example",
    )
    @patch("customer_api.urls.proxy_to_driver_service_path")
    def test_driver_registration_rewrites_to_driver_service(self, proxy):
        proxy.return_value = HttpResponse(status=201)
        response = Client().post(
            "/drivers/auth/register/",
            data={"email": "driver@example.test"},
        )

        self.assertEqual(response.status_code, 201)
        proxy.assert_called_once_with(
            proxy.call_args.args[0],
            "/api/v1/drivers/auth/register/",
        )

    @override_settings(
        DRIVER_SERVICE_URL="https://driver.example",
        UPSTREAM_TIMEOUT_SECONDS=10,
    )
    def test_driver_registration_path_is_forwarded_to_driver_api(self):
        request = RequestFactory().post(
            "/drivers/auth/register/",
            data=b'{"email":"driver@example.test"}',
            content_type="application/json",
        )
        received = {}

        def handle_upstream(upstream_request):
            received["url"] = str(upstream_request.url)
            received["body"] = upstream_request.read()
            return httpx.Response(
                201,
                headers={"content-type": "application/json"},
                stream=httpx.ByteStream(b'{"access":"identity-token"}'),
            )

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            "bikadeli_common.gateway.httpx.Client",
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = proxy_to_driver_service_path(
                request,
                "/api/v1/drivers/auth/register/",
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            received["url"],
            "https://driver.example/api/v1/drivers/auth/register/",
        )
        self.assertEqual(received["body"], b'{"email":"driver@example.test"}')
        response.close()

    @override_settings(
        IDENTITY_SERVICE_URL="", MONOLITH_BASE_URL="https://backend.example"
    )
    def test_auth_requests_do_not_fall_back_to_monolith(self):
        response = Client().post(
            "/api/v1/customers/register/", {}, content_type="application/json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertEqual(
            json.loads(response.content)["detail"],
            "Upstream service is not configured.",
        )
