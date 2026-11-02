from datetime import timedelta
from unittest.mock import Mock, patch

import httpx
import jwt
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient


class CustomerMapTileTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        token = jwt.encode(
            {
                "token_type": "access",
                "user_id": 732,
                "user_type": "CUSTOMER",
                "iat": timezone.now(),
                "exp": timezone.now() + timedelta(minutes=5),
            },
            settings.JWT_SIGNING_KEY,
            algorithm="HS256",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @override_settings(GOOGLE_MAPS_API_KEY="map-secret")
    def test_customer_can_fetch_valid_tile_without_exposing_key(self):
        tile = Mock(
            status_code=200,
            headers={"content-type": "image/png"},
            content=b"png-data",
        )
        with patch("customer_accounts.map_tiles.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = tile
            response = self.client.get("/api/v1/customers/map/tiles/2/1/3/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response["Cache-Control"], "public, max-age=86400")
        self.assertEqual(response.content, b"png-data")
        self.assertEqual(
            upstream.get.call_args.kwargs["params"],
            {"lyrs": "m", "x": 1, "y": 3, "z": 2, "key": "map-secret"},
        )

    @override_settings(
        ORDERS_SERVICE_URL="https://orders.example",
        GOOGLE_MAPS_API_KEY="map-secret",
    )
    def test_guest_token_is_validated_by_orders_before_tile_fetch(self):
        validation = Mock(status_code=204)
        tile = Mock(
            status_code=200,
            headers={"content-type": "image/png"},
            content=b"guest-png",
        )
        with patch("customer_accounts.map_tiles.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.side_effect = [validation, tile]
            self.client.credentials()
            response = self.client.get(
                "/api/v1/customers/map/tiles/2/1/3/?guest_token=guest-secret"
            )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.content, b"guest-png")
        calls = upstream.get.call_args_list
        self.assertEqual(
            calls[0].args[0],
            "https://orders.example/api/v1/orders/guest-token/validate/",
        )
        self.assertEqual(calls[0].kwargs["params"], {"guest_token": "guest-secret"})
        self.assertNotIn("guest-secret", str(calls[1]))

    @override_settings(
        ORDERS_SERVICE_URL="https://orders.example",
        GOOGLE_MAPS_API_KEY="map-secret",
    )
    def test_guest_token_failure_does_not_fetch_tile(self):
        with patch("customer_accounts.map_tiles.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = Mock(status_code=404)
            self.client.credentials()
            response = self.client.get(
                "/api/v1/customers/map/tiles/2/1/3/?guest_token=invalid-token"
            )

        self.assertEqual(response.status_code, 403)
        upstream.get.assert_called_once()

    def test_anonymous_and_non_customer_users_are_denied(self):
        self.client.credentials()
        anonymous = self.client.get("/api/v1/customers/map/tiles/2/1/3/")
        self.assertEqual(anonymous.status_code, 403)

        token = jwt.encode(
            {
                "token_type": "access",
                "user_id": 733,
                "user_type": "VENDOR",
                "iat": timezone.now(),
                "exp": timezone.now() + timedelta(minutes=5),
            },
            settings.JWT_SIGNING_KEY,
            algorithm="HS256",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")
        vendor = self.client.get("/api/v1/customers/map/tiles/2/1/3/")
        self.assertEqual(vendor.status_code, 403)

    @override_settings(GOOGLE_MAPS_API_KEY="map-secret")
    def test_rejects_out_of_range_coordinates_before_upstream_request(self):
        response = self.client.get("/api/v1/customers/map/tiles/23/0/0/")
        self.assertEqual(response.status_code, 400)

    @override_settings(GOOGLE_MAPS_API_KEY="")
    def test_missing_maps_key_returns_service_unavailable(self):
        response = self.client.get("/api/v1/customers/map/tiles/2/1/3/")
        self.assertEqual(response.status_code, 503)

    @override_settings(GOOGLE_MAPS_API_KEY="map-secret")
    def test_map_provider_failures_return_bad_gateway(self):
        with patch("customer_accounts.map_tiles.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.side_effect = httpx.ConnectError(
                "unavailable",
                request=httpx.Request("GET", "https://mt1.google.com"),
            )
            response = self.client.get("/api/v1/customers/map/tiles/2/1/3/")
        self.assertEqual(response.status_code, 502)
