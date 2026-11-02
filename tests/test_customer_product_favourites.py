from datetime import timedelta
from unittest.mock import patch

import httpx
import jwt
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from customer_accounts.models import CustomerAccount, CustomerProductFavourite


class CustomerProductFavouriteApiTests(TestCase):
    def setUp(self):
        self.owner_user_id = 732
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
    def test_list_add_and_remove_product_favourite(self):
        empty = self.client.get("/api/v1/customers/favourites/")
        self.assertEqual(empty.status_code, 200)
        self.assertEqual(empty.data, {"results": []})

        product = {
            "id": 501,
            "name": "Mango",
            "price": "2.50",
            "image": "https://gateway.example/api/v1/vendors/product-images/601/file/",
        }
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(200, json={"results": [product]})
            created = self.client.post(
                "/api/v1/customers/favourites/",
                {"product_id": 501},
                format="json",
            )
            upstream.get.assert_called_once_with(
                "https://vendor.example/api/v1/vendors/public/products/lookup/",
                params={"ids": "501"},
            )

        self.assertEqual(created.status_code, 201)
        self.assertEqual(created.data, {"message": "Added to favourites"})
        favourite = CustomerProductFavourite.objects.get()
        self.assertEqual(favourite.customer.owner_user_id, self.owner_user_id)
        self.assertEqual(favourite.product_id, 501)

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(200, json={"results": [product]})
            listed = self.client.get("/api/v1/customers/favourites/")

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            {
                key: value
                for key, value in listed.data["results"][0].items()
                if key != "created_at"
            },
            {
                "product_id": 501,
                "product_name": "Mango",
                "product_price": "2.50",
                "product_image": product["image"],
            },
        )
        self.assertEqual(
            parse_datetime(listed.data["results"][0]["created_at"]),
            favourite.created_at,
        )
        removed = self.client.delete("/api/v1/customers/favourites/?product_id=501")
        self.assertEqual(removed.status_code, 200)
        self.assertFalse(CustomerProductFavourite.objects.exists())
        missing = self.client.delete("/api/v1/customers/favourites/?product_id=501")
        self.assertEqual(missing.status_code, 404)

    @override_settings(VENDOR_SERVICE_URL="https://vendor.example")
    def test_duplicate_add_is_idempotent_and_unknown_product_is_not_saved(self):
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(
                200,
                json={
                    "results": [
                        {"id": 501, "name": "Mango", "price": "2.50", "image": None}
                    ]
                },
            )
            first = self.client.post(
                "/api/v1/customers/favourites/", {"product_id": 501}, format="json"
            )
            second = self.client.post(
                "/api/v1/customers/favourites/", {"product_id": 501}, format="json"
            )
        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(CustomerProductFavourite.objects.count(), 1)

        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.return_value = httpx.Response(200, json={"results": []})
            missing = self.client.post(
                "/api/v1/customers/favourites/", {"product_id": 999}, format="json"
            )
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(CustomerProductFavourite.objects.count(), 1)

    @override_settings(VENDOR_SERVICE_URL="")
    def test_missing_vendor_service_returns_503_without_writing(self):
        response = self.client.post(
            "/api/v1/customers/favourites/", {"product_id": 501}, format="json"
        )
        self.assertEqual(response.status_code, 503)
        self.assertFalse(CustomerProductFavourite.objects.exists())

    @override_settings(VENDOR_SERVICE_URL="https://vendor.example")
    def test_vendor_service_errors_incomplete_data_and_invalid_price_return_503(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        CustomerProductFavourite.objects.create(customer=account, product_id=501)
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.side_effect = httpx.ConnectError(
                "unavailable",
                request=httpx.Request("GET", "https://vendor.example"),
            )
            unavailable = self.client.get("/api/v1/customers/favourites/")
        self.assertEqual(unavailable.status_code, 503)

        for payload in (
            {"unexpected": []},
            {"results": []},
            {
                "results": [
                    {"id": 501, "name": "Mango", "price": "invalid", "image": None}
                ]
            },
        ):
            with patch("customer_accounts.views.httpx.Client") as client_factory:
                upstream = client_factory.return_value.__enter__.return_value
                upstream.get.return_value = httpx.Response(200, json=payload)
                invalid = self.client.get("/api/v1/customers/favourites/")
            self.assertEqual(invalid.status_code, 503)

    @override_settings(VENDOR_SERVICE_URL="https://vendor.example")
    def test_lookup_batches_ids_and_favourites_are_owner_scoped(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        CustomerProductFavourite.objects.bulk_create(
            [
                CustomerProductFavourite(customer=account, product_id=product_id)
                for product_id in range(1, 202)
            ]
        )
        CustomerProductFavourite.objects.create(
            customer=CustomerAccount.objects.create(owner_user_id=999),
            product_id=999,
        )
        with patch("customer_accounts.views.httpx.Client") as client_factory:
            upstream = client_factory.return_value.__enter__.return_value
            upstream.get.side_effect = lambda _url, params: httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": int(product_id),
                            "name": f"Product {product_id}",
                            "price": "1.00",
                            "image": None,
                        }
                        for product_id in params["ids"].split(",")
                    ]
                },
            )
            response = self.client.get("/api/v1/customers/favourites/")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data["results"]), 201)
        self.assertEqual(upstream.get.call_count, 2)
        self.assertEqual(
            len(upstream.get.call_args_list[0].kwargs["params"]["ids"].split(",")), 200
        )
        self.assertEqual(
            len(upstream.get.call_args_list[1].kwargs["params"]["ids"].split(",")), 1
        )

        self.client.credentials()
        unauthorized = self.client.get("/api/v1/customers/favourites/")
        self.assertIn(unauthorized.status_code, (401, 403))
