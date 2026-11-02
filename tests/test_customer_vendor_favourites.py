from datetime import timedelta
from unittest.mock import patch

import httpx
import jwt
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from customer_accounts.models import CustomerAccount, CustomerVendorFavourite


class CustomerVendorFavouriteApiTests(TestCase):
    def setUp(self):
        self.owner_user_id = 731
        self.client = APIClient()
        token = jwt.encode(
            {
                "token_type": "access",
                "user_id": self.owner_user_id,
                "iat": timezone.now(),
                "exp": timezone.now() + timedelta(minutes=5),
            },
            settings.JWT_SIGNING_KEY,
            algorithm="HS256",
        )
        self.client.credentials(HTTP_AUTHORIZATION=f"Bearer {token}")

    @override_settings(
        VENDOR_SERVICE_URL="https://vendor.example", UPSTREAM_TIMEOUT_SECONDS=2
    )
    def test_list_add_and_remove_vendor_favourite(self):
        empty = self.client.get("/api/v1/customers/vendor-favourites/")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data, {"results": []})

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(
                200,
                json={"results": [{"id": 52, "business_name": "Mango Market"}]},
            )
            created = self.client.post(
                "/api/v1/customers/vendor-favourites/",
                {"vendor_id": 52},
                format="json",
            )
            upstream.get.assert_called_once_with(
                "https://vendor.example/api/v1/vendors/public/vendors/lookup/",
                params={"ids": "52"},
            )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data, {"message": "Added to favourites"})
        favourite = CustomerVendorFavourite.objects.get()
        self.assertEqual(favourite.customer.owner_user_id, self.owner_user_id)
        self.assertEqual(favourite.vendor_id, 52)

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(
                200,
                json={"results": [{"id": 52, "business_name": "Mango Market"}]},
            )
            listed = self.client.get("/api/v1/customers/vendor-favourites/")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(listed.data["results"][0]["id"], favourite.pk)
        self.assertEqual(listed.data["results"][0]["vendor_id"], 52)
        self.assertEqual(listed.data["results"][0]["vendor_name"], "Mango Market")

        removed = self.client.delete(
            "/api/v1/customers/vendor-favourites/?vendor_id=52"
        )
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(CustomerVendorFavourite.objects.exists())
        missing = self.client.delete(
            "/api/v1/customers/vendor-favourites/?vendor_id=52"
        )
        self.assertEqual(missing.status_code, 404)

    @override_settings(VENDOR_SERVICE_URL="https://vendor.example")
    def test_duplicate_add_is_idempotent_and_unknown_vendor_is_not_saved(self):
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(
                200,
                json={"results": [{"id": 52, "business_name": "Mango Market"}]},
            )
            first = self.client.post(
                "/api/v1/customers/vendor-favourites/", {"vendor_id": 52}, format="json"
            )
            second = self.client.post(
                "/api/v1/customers/vendor-favourites/", {"vendor_id": 52}, format="json"
            )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(CustomerVendorFavourite.objects.count(), 1)

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(200, json={"results": []})
            missing = self.client.post(
                "/api/v1/customers/vendor-favourites/", {"vendor_id": 99}, format="json"
            )

        self.assertEqual(missing.status_code, 404)
        self.assertEqual(CustomerVendorFavourite.objects.count(), 1)

    @override_settings(VENDOR_SERVICE_URL="")
    def test_missing_vendor_service_returns_503_without_writing(self):
        response = self.client.post(
            "/api/v1/customers/vendor-favourites/", {"vendor_id": 52}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(CustomerVendorFavourite.objects.exists())

    @override_settings(VENDOR_SERVICE_URL="https://vendor.example")
    def test_vendor_service_failure_and_malformed_response_return_503(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        CustomerVendorFavourite.objects.create(customer=account, vendor_id=52)
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.side_effect = httpx.ConnectError(
                "unavailable",
                request=httpx.Request("GET", "https://vendor.example"),
            )
            unavailable = self.client.get("/api/v1/customers/vendor-favourites/")
        self.assertEqual(unavailable.status_code, 503)

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(200, json={"unexpected": []})
            malformed = self.client.get("/api/v1/customers/vendor-favourites/")
        self.assertEqual(malformed.status_code, 503)

    def test_vendor_favourites_are_owner_scoped_and_require_authentication(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        CustomerVendorFavourite.objects.create(customer=account, vendor_id=52)
        CustomerVendorFavourite.objects.create(
            customer=CustomerAccount.objects.create(owner_user_id=999),
            vendor_id=53,
        )

        with (
            override_settings(VENDOR_SERVICE_URL="https://vendor.example"),
            patch("customer_accounts.views.httpx.Client") as client_factory,
        ):
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(
                200,
                json={"results": [{"id": 52, "business_name": "Mango Market"}]},
            )
            response = self.client.get("/api/v1/customers/vendor-favourites/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual([item["vendor_id"] for item in response.data["results"]], [52])

        self.client.credentials()
        unauthorized = self.client.get("/api/v1/customers/vendor-favourites/")
        self.assertIn(unauthorized.status_code, (401, 403))
