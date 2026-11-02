from datetime import timedelta

import jwt
from django.conf import settings
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient

from customer_accounts.models import CustomerAccount, SavedAddress


class CustomerAddressApiTests(TestCase):
    def setUp(self):
        self.owner_user_id = 415
        self.client = APIClient()
        token = jwt.encode(
            {
                'token_type': 'access',
                'user_id': self.owner_user_id,
                'iat': timezone.now(),
                'exp': timezone.now() + timedelta(minutes=5),
            },
            settings.JWT_SIGNING_KEY,
            algorithm='HS256',
        )
        self.client.credentials(HTTP_AUTHORIZATION=f'Bearer {token}')

    def test_address_creation_and_default_response_preserve_coordinates(self):
        response = self.client.post(
            '/api/v1/customers/addresses/',
            {
                'label': 'Home',
                'full_address': '12 Main Street',
                'address_type': 'HOME',
                'location_lat': -17.8252,
                'location_lng': 31.0335,
                'is_default': True,
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertAlmostEqual(response.data['location_lat'], -17.8252)
        self.assertAlmostEqual(response.data['location_lng'], 31.0335)
        self.assertEqual(
            response.data['location'],
            {'type': 'Point', 'coordinates': [31.0335, -17.8252]},
        )
        address_id = response.data['id']

        default = self.client.get('/api/v1/customers/addresses/default/')
        self.assertEqual(default.status_code, 200)
        self.assertEqual(default.data['id'], address_id)
        self.assertEqual(CustomerAccount.objects.get().owner_user_id, self.owner_user_id)

    def test_rejects_partial_and_out_of_range_coordinates(self):
        partial = self.client.post(
            '/api/v1/customers/addresses/',
            {'label': 'Home', 'full_address': '12 Main Street', 'location_lat': -17.8},
            format='json',
        )
        invalid = self.client.post(
            '/api/v1/customers/addresses/',
            {
                'label': 'Home',
                'full_address': '12 Main Street',
                'location_lat': 120,
                'location_lng': 31,
            },
            format='json',
        )

        self.assertEqual(partial.status_code, 400)
        self.assertEqual(invalid.status_code, 400)
        self.assertEqual(SavedAddress.objects.count(), 0)

    def test_customer_cannot_read_or_mutate_another_customers_address(self):
        other = CustomerAccount.objects.create(owner_user_id=999)
        address = SavedAddress.objects.create(
            customer=other,
            label='Private',
            full_address='Other customer address',
        )

        self.assertEqual(self.client.get(f'/api/v1/customers/addresses/{address.pk}/').status_code, 404)
        self.assertEqual(
            self.client.patch(
                f'/api/v1/customers/addresses/{address.pk}/',
                {'label': 'Changed'},
                format='json',
            ).status_code,
            404,
        )

    def test_setting_default_unsets_previous_default_for_same_customer(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        old_default = SavedAddress.objects.create(
            customer=account,
            label='Old',
            full_address='Old address',
            is_default=True,
        )
        new_default = SavedAddress.objects.create(
            customer=account,
            label='New',
            full_address='New address',
        )

        response = self.client.post(f'/api/v1/customers/addresses/{new_default.pk}/set_default/')

        self.assertEqual(response.status_code, 200)
        old_default.refresh_from_db()
        new_default.refresh_from_db()
        self.assertFalse(old_default.is_default)
        self.assertTrue(new_default.is_default)

    def test_limits_saved_addresses_to_ten(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        SavedAddress.objects.bulk_create(
            [
                SavedAddress(customer=account, label=f'Address {index}', full_address='Address')
                for index in range(10)
            ]
        )

        response = self.client.post(
            '/api/v1/customers/addresses/',
            {'label': 'Eleventh', 'full_address': 'Too many'},
            format='json',
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(SavedAddress.objects.filter(customer=account).count(), 10)
