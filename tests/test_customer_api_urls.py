import sys
from pathlib import Path

from django.test import Client, SimpleTestCase
from django.urls import resolve

SERVICE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SERVICE_ROOT))


class CustomerApiUrlTests(SimpleTestCase):
    urlconf = 'customer_api.urls'

    def test_customer_and_order_routes_resolve(self):
        self.assertEqual(resolve('/api/v1/customers/register/', urlconf=self.urlconf).url_name, 'api-register')
        self.assertEqual(resolve('/api/v1/orders/cart/', urlconf=self.urlconf).url_name, 'cart-get')

    def test_customer_wallet_and_payment_routes_resolve(self):
        self.assertIsNotNone(resolve('/api/v1/wallet/balance/', urlconf=self.urlconf))
        self.assertEqual(
            resolve('/api/v1/payments/transactions/create-payment-intent/', urlconf=self.urlconf).url_name,
            'customer-payments-create-payment-intent',
        )

    def test_customer_profile_referral_and_subscription_routes_resolve(self):
        self.assertIsNotNone(resolve('/api/v1/profile/me/', urlconf=self.urlconf))
        self.assertEqual(
            resolve('/api/v1/auth/referral/', urlconf=self.urlconf).url_name,
            'customer-referral-data',
        )
        self.assertEqual(
            resolve('/api/v1/subscription/plans/', urlconf=self.urlconf).url_name,
            'customer-subscription-plans',
        )

    def test_health_routes_resolve(self):
        self.assertEqual(resolve('/health/', urlconf=self.urlconf).url_name, 'health-liveness')
        self.assertEqual(resolve('/health/ready/', urlconf=self.urlconf).url_name, 'health-readiness')
        self.assertEqual(Client().get('/health/').status_code, 200)
