from datetime import timedelta
from unittest.mock import patch

import httpx
import jwt
from django.conf import settings
from django.test import TestCase, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from customer_accounts.models import (
    CustomerAccount,
    CustomerSupportTicket,
    CustomerTicketMessage,
)


class CustomerSupportTicketApiTests(TestCase):
    def setUp(self):
        self.owner_user_id = 4123
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

    def test_create_ticket_returns_legacy_shape_and_creates_initial_message(self):
        response = self.client.post(
            '/api/v1/customers/support-tickets/',
            {
                'subject': 'Missing order',
                'description': 'My order has not arrived',
                'category': 'DELIVERY',
                'priority': 'HIGH',
            },
            format='json',
        )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(
            set(response.data),
            {
                'id',
                'order',
                'subject',
                'description',
                'category',
                'priority',
                'status',
                'created_at',
                'updated_at',
                'resolved_at',
                'last_message',
            },
        )
        self.assertEqual(response.data['order'], None)
        self.assertEqual(response.data['status'], 'OPEN')
        self.assertEqual(
            response.data['last_message']['message'],
            'My order has not arrived',
        )
        self.assertEqual(CustomerAccount.objects.get().owner_user_id, self.owner_user_id)
        self.assertEqual(CustomerTicketMessage.objects.get().message, 'My order has not arrived')

    def test_ticket_list_messages_and_reply_are_owner_scoped(self):
        own_account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        ticket = CustomerSupportTicket.objects.create(
            customer=own_account,
            subject='My ticket',
            description='Details',
        )
        CustomerTicketMessage.objects.create(ticket=ticket, message='First message')
        other_account = CustomerAccount.objects.create(owner_user_id=9999)
        other_ticket = CustomerSupportTicket.objects.create(
            customer=other_account,
            subject='Private ticket',
            description='Private details',
        )

        listed = self.client.get('/api/v1/customers/support-tickets/')
        self.assertEqual(listed.status_code, 200)
        self.assertEqual([row['id'] for row in listed.data], [ticket.pk])
        self.assertEqual(listed.data[0]['last_message']['message'], 'First message')

        messages = self.client.get(f'/api/v1/customers/support-tickets/{ticket.pk}/messages/')
        self.assertEqual(messages.status_code, 200)
        self.assertEqual(messages.data[0]['message'], 'First message')
        self.assertEqual(
            self.client.get(f'/api/v1/customers/support-tickets/{other_ticket.pk}/messages/').status_code,
            404,
        )
        self.assertEqual(
            self.client.post(
                f'/api/v1/customers/support-tickets/{other_ticket.pk}/reply/',
                {'message': 'Unauthorized'},
                format='json',
            ).status_code,
            404,
        )

        ticket.status = 'CLOSED'
        ticket.resolved_at = timezone.now()
        ticket.save()
        reply = self.client.post(
            f'/api/v1/customers/support-tickets/{ticket.pk}/reply/',
            {'message': 'Please reopen this'},
            format='json',
        )
        self.assertEqual(reply.status_code, 201)
        self.assertEqual(reply.data['message'], 'Please reopen this')
        ticket.refresh_from_db()
        self.assertEqual(ticket.status, 'IN_PROGRESS')
        self.assertIsNone(ticket.resolved_at)

    def test_reply_validates_required_and_max_length(self):
        account = CustomerAccount.objects.create(owner_user_id=self.owner_user_id)
        ticket = CustomerSupportTicket.objects.create(
            customer=account,
            subject='Question',
            description='Description',
        )

        empty = self.client.post(
            f'/api/v1/customers/support-tickets/{ticket.pk}/reply/',
            {'message': '   '},
            format='json',
        )
        too_long = self.client.post(
            f'/api/v1/customers/support-tickets/{ticket.pk}/reply/',
            {'message': 'x' * 5001},
            format='json',
        )
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(empty.data, {'error': 'Message is required'})
        self.assertEqual(too_long.status_code, 400)
        self.assertEqual(too_long.data, {'error': 'Message is too long (max 5000 characters)'})

    @override_settings(ORDERS_SERVICE_URL='https://orders.example', UPSTREAM_TIMEOUT_SECONDS=5)
    def test_ticket_order_reference_is_checked_against_authenticated_orders_service(self):
        received = {}

        def handle_upstream(request):
            received['url'] = str(request.url)
            received['authorization'] = request.headers.get('authorization')
            return httpx.Response(200, json={'id': 88})

        real_client = httpx.Client
        transport = httpx.MockTransport(handle_upstream)
        with patch(
            'customer_accounts.views.httpx.Client',
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = self.client.post(
                '/api/v1/customers/support-tickets/',
                {
                    'subject': 'Order issue',
                    'description': 'Where is my order?',
                    'order': 88,
                },
                format='json',
            )

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['order'], 88)
        self.assertEqual(received['url'], 'https://orders.example/api/v1/orders/88/')
        self.assertTrue(received['authorization'].startswith('Bearer '))

    @override_settings(ORDERS_SERVICE_URL='https://orders.example', UPSTREAM_TIMEOUT_SECONDS=5)
    def test_rejects_order_not_visible_to_authenticated_customer(self):
        real_client = httpx.Client
        transport = httpx.MockTransport(lambda request: httpx.Response(404))
        with patch(
            'customer_accounts.views.httpx.Client',
            side_effect=lambda **kwargs: real_client(transport=transport, **kwargs),
        ):
            response = self.client.post(
                '/api/v1/customers/support-tickets/',
                {'subject': 'Order issue', 'description': 'Details', 'order': 900},
                format='json',
            )

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data, {'error': 'Order not found'})
        self.assertEqual(CustomerSupportTicket.objects.count(), 0)
