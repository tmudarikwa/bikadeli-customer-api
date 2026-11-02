from unittest.mock import patch

from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.urls import resolve

from customer_api.urls import (
    proxy_customer_payment_intent,
    proxy_customer_wallet_payment,
    proxy_customer_wallet_topup,
)


class PaymentIntentServiceProxyTests(SimpleTestCase):
    def test_payment_intent_path_uses_feature_gated_proxy(self):
        route = resolve("/api/v1/payments/transactions/create-payment-intent/")

        self.assertIs(route.func, proxy_customer_payment_intent)

    def test_payment_confirmation_path_uses_feature_gated_proxy(self):
        route = resolve(
            "/api/v1/payments/transactions/704/confirm-stripe-payment/"
        )

        self.assertIs(route.func, proxy_customer_payment_intent)

    def test_wallet_topup_path_uses_feature_gated_proxy(self):
        route = resolve("/api/v1/wallet/top-up/")

        self.assertIs(route.func, proxy_customer_wallet_topup)

    def test_wallet_payment_path_uses_feature_gated_proxy(self):
        route = resolve("/api/v1/wallet/pay/")

        self.assertIs(route.func, proxy_customer_wallet_payment)

    @override_settings(FINANCE_WALLET_TOPUP_ENABLED=True)
    @patch(
        "customer_api.urls.proxy_to_finance_service",
        return_value=HttpResponse("finance"),
    )
    def test_enabled_stripe_topup_uses_finance_proxy(self, finance_proxy):
        request = RequestFactory().post(
            "/api/v1/wallet/top-up/",
            data=b'{"amount":"12.50","gateway":"stripe"}',
            content_type="application/json",
        )

        response = proxy_customer_wallet_topup(request)

        self.assertEqual(response.content, b"finance")
        finance_proxy.assert_called_once_with(request)

    @override_settings(FINANCE_WALLET_TOPUP_ENABLED=True)
    @patch("customer_api.urls.proxy_to_monolith", return_value=HttpResponse("legacy"))
    @patch("customer_api.urls.proxy_to_finance_service")
    def test_non_stripe_topup_preserves_monolith_owner(
        self, finance_proxy, legacy_proxy
    ):
        request = RequestFactory().post(
            "/api/v1/wallet/top-up/",
            data=b'{"amount":"12.50","gateway":"paynow"}',
            content_type="application/json",
        )

        response = proxy_customer_wallet_topup(request)

        self.assertEqual(response.content, b"legacy")
        legacy_proxy.assert_called_once_with(request)
        finance_proxy.assert_not_called()

    @override_settings(FINANCE_PAYNOW_WALLET_TOPUP_ENABLED=True)
    @patch(
        "customer_api.urls.proxy_to_finance_service",
        return_value=HttpResponse("finance"),
    )
    def test_enabled_paynow_topup_uses_finance_proxy(self, finance_proxy):
        request = RequestFactory().post(
            "/api/v1/wallet/top-up/",
            data=b'{"amount":"12.50","gateway":"ecocash","phone_number":"+263771234567"}',
            content_type="application/json",
        )

        response = proxy_customer_wallet_topup(request)

        self.assertEqual(response.content, b"finance")
        finance_proxy.assert_called_once_with(request)

    @override_settings(FINANCE_WALLET_PAYMENT_ENABLED=False)
    @patch("customer_api.urls.proxy_to_monolith", return_value=HttpResponse("legacy"))
    def test_disabled_wallet_payment_route_preserves_monolith_owner(
        self, legacy_proxy
    ):
        request = RequestFactory().post(
            "/api/v1/wallet/pay/",
            data=b'{"order_id":704}',
            content_type="application/json",
        )

        response = proxy_customer_wallet_payment(request)

        self.assertEqual(response.content, b"legacy")
        legacy_proxy.assert_called_once_with(request)

    @override_settings(FINANCE_WALLET_PAYMENT_ENABLED=True)
    @patch(
        "customer_api.urls.proxy_to_finance_service",
        return_value=HttpResponse("finance"),
    )
    def test_enabled_wallet_payment_route_uses_finance_proxy(self, finance_proxy):
        request = RequestFactory().post(
            "/api/v1/wallet/pay/",
            data=b'{"order_id":704}',
            content_type="application/json",
        )

        response = proxy_customer_wallet_payment(request)

        self.assertEqual(response.content, b"finance")
        finance_proxy.assert_called_once_with(request)

    @override_settings(FINANCE_PAYMENT_INTENTS_ENABLED=False)
    @patch("customer_api.urls.proxy_to_monolith", return_value=HttpResponse("legacy"))
    def test_disabled_route_preserves_monolith_owner(self, legacy_proxy):
        request = RequestFactory().post(
            "/api/v1/payments/transactions/create-payment-intent/",
            data=b'{"order_id":704}',
            content_type="application/json",
        )

        response = proxy_customer_payment_intent(request)

        self.assertEqual(response.content, b"legacy")
        legacy_proxy.assert_called_once_with(request)

    @override_settings(FINANCE_PAYMENT_INTENTS_ENABLED=True)
    @patch(
        "customer_api.urls.proxy_to_finance_service",
        return_value=HttpResponse("finance"),
    )
    def test_enabled_route_uses_finance_proxy(self, finance_proxy):
        request = RequestFactory().post(
            "/api/v1/payments/transactions/create-payment-intent/",
            data=b'{"order_id":704}',
            content_type="application/json",
        )

        response = proxy_customer_payment_intent(request)

        self.assertEqual(response.content, b"finance")
        finance_proxy.assert_called_once_with(request)
