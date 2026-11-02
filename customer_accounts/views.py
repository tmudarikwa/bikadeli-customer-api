import logging
from decimal import Decimal, InvalidOperation

import httpx
from bikadeli_common.authentication import AccessTokenAuthentication
from django.conf import settings
from django.db import transaction
from django.db.models import OuterRef, Subquery
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes, throttle_classes
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import (
    CustomerAccount,
    CustomerProductFavourite,
    CustomerSupportTicket,
    CustomerTicketMessage,
    CustomerVendorFavourite,
    SavedAddress,
)
from .serializers import (
    CustomerProductFavouriteIdSerializer,
    CustomerProductFavouriteSerializer,
    CustomerSupportTicketSerializer,
    CustomerTicketMessageSerializer,
    CustomerVendorFavouriteIdSerializer,
    CustomerVendorFavouriteSerializer,
    SavedAddressSerializer,
)

logger = logging.getLogger(__name__)


class CustomerMutationRateThrottle(UserRateThrottle):
    scope = 'mutation'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.id}


def _validate_order_owner(request, order_id):
    if not settings.ORDERS_SERVICE_URL:
        return Response({'detail': 'Orders service is not configured.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    headers = {}
    authorization = request.headers.get('Authorization')
    if authorization:
        headers['Authorization'] = authorization
    try:
        with httpx.Client(timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.get(
                f'{settings.ORDERS_SERVICE_URL}/api/v1/orders/{order_id}/',
                headers=headers,
            )
    except httpx.RequestError as exc:
        logger.warning('Order ownership check failed: %s', type(exc).__name__)
        return Response({'detail': 'Orders service is unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

    if response.status_code == status.HTTP_404_NOT_FOUND:
        return Response({'error': 'Order not found'}, status=status.HTTP_404_NOT_FOUND)
    if not 200 <= response.status_code < 300:
        logger.warning('Order ownership check returned status %s', response.status_code)
        return Response({'detail': 'Orders service is unavailable.'}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
    return None


def _lookup_vendor_names(vendor_ids):
    if not settings.VENDOR_SERVICE_URL:
        return Response(
            {'detail': 'Vendor service is not configured.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        with httpx.Client(timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.get(
                f'{settings.VENDOR_SERVICE_URL}/api/v1/vendors/public/vendors/lookup/',
                params={'ids': ','.join(str(vendor_id) for vendor_id in vendor_ids)},
            )
    except httpx.RequestError as exc:
        logger.warning('Vendor favourite lookup failed: %s', type(exc).__name__)
        return Response(
            {'detail': 'Vendor service is unavailable.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if response.status_code != status.HTTP_200_OK:
        logger.warning('Vendor favourite lookup returned status %s', response.status_code)
        return Response(
            {'detail': 'Vendor service is unavailable.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning('Vendor favourite lookup returned invalid JSON.')
        return Response(
            {'detail': 'Vendor service returned an invalid response.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        logger.warning('Vendor favourite lookup returned an invalid response shape.')
        return Response(
            {'detail': 'Vendor service returned an invalid response.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    names = {}
    for vendor in payload['results']:
        if (
            not isinstance(vendor, dict)
            or type(vendor.get('id')) is not int
            or not isinstance(vendor.get('business_name'), str)
        ):
            logger.warning('Vendor favourite lookup returned an invalid vendor record.')
            return Response(
                {'detail': 'Vendor service returned an invalid response.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        names[vendor['id']] = vendor['business_name']
    return names


def _lookup_products(product_ids):
    if not settings.VENDOR_SERVICE_URL:
        return Response(
            {'detail': 'Vendor service is not configured.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        with httpx.Client(timeout=settings.UPSTREAM_TIMEOUT_SECONDS, follow_redirects=False) as client:
            response = client.get(
                f'{settings.VENDOR_SERVICE_URL}/api/v1/vendors/public/products/lookup/',
                params={'ids': ','.join(str(product_id) for product_id in product_ids)},
            )
    except httpx.RequestError as exc:
        logger.warning('Product favourite lookup failed: %s', type(exc).__name__)
        return Response(
            {'detail': 'Vendor service is unavailable.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if response.status_code != status.HTTP_200_OK:
        logger.warning('Product favourite lookup returned status %s', response.status_code)
        return Response(
            {'detail': 'Vendor service is unavailable.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    try:
        payload = response.json()
    except ValueError:
        logger.warning('Product favourite lookup returned invalid JSON.')
        return Response(
            {'detail': 'Vendor service returned an invalid response.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    if not isinstance(payload, dict) or not isinstance(payload.get('results'), list):
        logger.warning('Product favourite lookup returned an invalid response shape.')
        return Response(
            {'detail': 'Vendor service returned an invalid response.'},
            status=status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    products = {}
    for product in payload['results']:
        if (
            not isinstance(product, dict)
            or type(product.get('id')) is not int
            or not isinstance(product.get('name'), str)
            or not isinstance(product.get('price'), (str, int, float))
            or (product.get('image') is not None and not isinstance(product.get('image'), str))
        ):
            logger.warning('Product favourite lookup returned an invalid product record.')
            return Response(
                {'detail': 'Vendor service returned an invalid response.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        try:
            price = Decimal(str(product['price']))
        except (InvalidOperation, ValueError):
            logger.warning('Product favourite lookup returned an invalid product price.')
            return Response(
                {'detail': 'Vendor service returned an invalid response.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        if not price.is_finite():
            logger.warning('Product favourite lookup returned a non-finite product price.')
            return Response(
                {'detail': 'Vendor service returned an invalid response.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )
        products[product['id']] = {**product, 'price': str(price)}
    return products


class CustomerAddressListCreateView(generics.ListCreateAPIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SavedAddressSerializer

    def get_queryset(self):
        return SavedAddress.objects.filter(customer__owner_user_id=self.request.user.id)

    @transaction.atomic
    def perform_create(self, serializer):
        customer, _ = CustomerAccount.objects.get_or_create(owner_user_id=self.request.user.id)
        CustomerAccount.objects.select_for_update().get(pk=customer.pk)
        if SavedAddress.objects.filter(customer=customer).count() >= 10:
            raise ValidationError({'error': 'Maximum 10 saved addresses allowed'})
        if serializer.validated_data.get('is_default'):
            SavedAddress.objects.filter(customer=customer, is_default=True).update(is_default=False)
        serializer.save(customer=customer)


class CustomerDefaultAddressView(APIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        address = SavedAddress.objects.filter(
            customer__owner_user_id=request.user.id,
            is_default=True,
        ).first()
        if address is None:
            return Response({'detail': 'No saved address found'}, status=status.HTTP_404_NOT_FOUND)
        return Response(SavedAddressSerializer(address).data)


class CustomerAddressDetailView(generics.RetrieveUpdateDestroyAPIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)
    serializer_class = SavedAddressSerializer

    def get_queryset(self):
        return SavedAddress.objects.filter(customer__owner_user_id=self.request.user.id)

    @transaction.atomic
    def perform_update(self, serializer):
        address = serializer.instance
        if serializer.validated_data.get('is_default'):
            SavedAddress.objects.filter(customer=address.customer, is_default=True).exclude(
                pk=address.pk
            ).update(is_default=False)
        serializer.save()


class CustomerSetDefaultAddressView(APIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    @transaction.atomic
    def post(self, request, pk):
        address = get_object_or_404(
            SavedAddress.objects.select_related('customer'),
            pk=pk,
            customer__owner_user_id=request.user.id,
        )
        CustomerAccount.objects.select_for_update().get(pk=address.customer_id)
        SavedAddress.objects.filter(customer=address.customer, is_default=True).exclude(
            pk=address.pk
        ).update(is_default=False)
        address.is_default = True
        address.save(update_fields=['is_default'])
        return Response({'message': 'Default address updated'})


class CustomerVendorFavouritesView(APIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        favourites = list(
            CustomerVendorFavourite.objects.filter(
                customer__owner_user_id=request.user.id,
            ).values('id', 'vendor_id', 'created_at')
        )
        if not favourites:
            return Response({'results': []})

        names = {}
        vendor_ids = list(dict.fromkeys(item['vendor_id'] for item in favourites))
        for start in range(0, len(vendor_ids), 200):
            batch_names = _lookup_vendor_names(vendor_ids[start : start + 200])
            if isinstance(batch_names, Response):
                return batch_names
            names.update(batch_names)

        missing_ids = set(vendor_ids) - names.keys()
        if missing_ids:
            logger.warning('Vendor service did not resolve favourite vendor IDs: %s', sorted(missing_ids)[:10])
            return Response(
                {'detail': 'Vendor service returned incomplete favourite data.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        results = [
            {
                'id': favourite['id'],
                'vendor_id': favourite['vendor_id'],
                'vendor_name': names[favourite['vendor_id']],
                'created_at': favourite['created_at'],
            }
            for favourite in favourites
        ]
        return Response({'results': CustomerVendorFavouriteSerializer(results, many=True).data})

    def post(self, request):
        serializer = CustomerVendorFavouriteIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        vendor_id = serializer.validated_data['vendor_id']

        names = _lookup_vendor_names([vendor_id])
        if isinstance(names, Response):
            return names
        if vendor_id not in names:
            return Response({'error': 'Vendor not found'}, status=status.HTTP_404_NOT_FOUND)

        customer, _ = CustomerAccount.objects.get_or_create(owner_user_id=request.user.id)
        _, created = CustomerVendorFavourite.objects.get_or_create(customer=customer, vendor_id=vendor_id)
        if created:
            return Response({'message': 'Added to favourites'}, status=status.HTTP_201_CREATED)
        return Response({'message': 'Already in favourites'})

    def delete(self, request):
        serializer = CustomerVendorFavouriteIdSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        deleted, _ = CustomerVendorFavourite.objects.filter(
            customer__owner_user_id=request.user.id,
            vendor_id=serializer.validated_data['vendor_id'],
        ).delete()
        if deleted:
            return Response({'message': 'Removed from favourites'})
        return Response({'error': 'Not found in favourites'}, status=status.HTTP_404_NOT_FOUND)


class CustomerProductFavouritesView(APIView):
    authentication_classes = (AccessTokenAuthentication,)
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        favourites = list(
            CustomerProductFavourite.objects.filter(
                customer__owner_user_id=request.user.id,
            ).values('product_id', 'created_at')
        )
        if not favourites:
            return Response({'results': []})

        product_ids = list(dict.fromkeys(item['product_id'] for item in favourites))
        products = {}
        for start in range(0, len(product_ids), 200):
            batch_products = _lookup_products(product_ids[start : start + 200])
            if isinstance(batch_products, Response):
                return batch_products
            products.update(batch_products)

        missing_ids = set(product_ids) - products.keys()
        if missing_ids:
            logger.warning('Vendor service did not resolve favourite product IDs: %s', sorted(missing_ids)[:10])
            return Response(
                {'detail': 'Vendor service returned incomplete favourite data.'},
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        results = [
            {
                'product_id': favourite['product_id'],
                'product_name': products[favourite['product_id']]['name'],
                'product_price': products[favourite['product_id']]['price'],
                'product_image': products[favourite['product_id']]['image'],
                'created_at': favourite['created_at'],
            }
            for favourite in favourites
        ]
        return Response({'results': CustomerProductFavouriteSerializer(results, many=True).data})

    def post(self, request):
        serializer = CustomerProductFavouriteIdSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        product_id = serializer.validated_data['product_id']

        products = _lookup_products([product_id])
        if isinstance(products, Response):
            return products
        if product_id not in products:
            return Response({'error': 'Product not found'}, status=status.HTTP_404_NOT_FOUND)

        customer, _ = CustomerAccount.objects.get_or_create(owner_user_id=request.user.id)
        _, created = CustomerProductFavourite.objects.get_or_create(customer=customer, product_id=product_id)
        if created:
            return Response({'message': 'Added to favourites'}, status=status.HTTP_201_CREATED)
        return Response({'message': 'Already in favourites'})

    def delete(self, request):
        serializer = CustomerProductFavouriteIdSerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        deleted, _ = CustomerProductFavourite.objects.filter(
            customer__owner_user_id=request.user.id,
            product_id=serializer.validated_data['product_id'],
        ).delete()
        if deleted:
            return Response({'message': 'Removed from favourites'})
        return Response({'error': 'Not found in favourites'}, status=status.HTTP_404_NOT_FOUND)


@api_view(['GET', 'POST'])
@permission_classes([permissions.IsAuthenticated])
def support_tickets_view(request):
    if request.method == 'GET':
        last_message = CustomerTicketMessage.objects.filter(ticket=OuterRef('pk')).order_by('-created_at').values('pk')[:1]
        tickets = (
            CustomerSupportTicket.objects.filter(customer__owner_user_id=request.user.id)
            .annotate(last_message_id=Subquery(last_message))
            .order_by('-created_at')
        )
        return Response(CustomerSupportTicketSerializer(tickets, many=True).data)

    serializer = CustomerSupportTicketSerializer(data=request.data)
    if not serializer.is_valid():
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    order_id = serializer.validated_data.get('order_id')
    if order_id is not None:
        order_error = _validate_order_owner(request, order_id)
        if order_error:
            return order_error

    with transaction.atomic():
        customer, _ = CustomerAccount.objects.get_or_create(owner_user_id=request.user.id)
        ticket = serializer.save(customer=customer)
        CustomerTicketMessage.objects.create(
            ticket=ticket,
            sender_is_customer=True,
            message=ticket.description,
        )
    return Response(CustomerSupportTicketSerializer(ticket).data, status=status.HTTP_201_CREATED)


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def ticket_messages_view(request, pk):
    ticket = CustomerSupportTicket.objects.filter(pk=pk, customer__owner_user_id=request.user.id).first()
    if ticket is None:
        return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)
    messages = ticket.messages.all()
    return Response(CustomerTicketMessageSerializer(messages, many=True).data)


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
@throttle_classes([CustomerMutationRateThrottle])
def ticket_reply_view(request, pk):
    ticket = CustomerSupportTicket.objects.filter(pk=pk, customer__owner_user_id=request.user.id).first()
    if ticket is None:
        return Response({'error': 'Ticket not found'}, status=status.HTTP_404_NOT_FOUND)

    message_text = request.data.get('message', '')
    if not isinstance(message_text, str):
        return Response({'error': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)
    message_text = message_text.strip()
    if not message_text:
        return Response({'error': 'Message is required'}, status=status.HTTP_400_BAD_REQUEST)
    if len(message_text) > 5000:
        return Response(
            {'error': 'Message is too long (max 5000 characters)'},
            status=status.HTTP_400_BAD_REQUEST,
        )

    with transaction.atomic():
        ticket = CustomerSupportTicket.objects.select_for_update().get(pk=ticket.pk)
        if ticket.status in ('RESOLVED', 'CLOSED'):
            ticket.status = 'IN_PROGRESS'
            ticket.resolved_at = None
        ticket.updated_at = timezone.now()
        ticket.save(update_fields=['status', 'resolved_at', 'updated_at'])
        message = CustomerTicketMessage.objects.create(
            ticket=ticket,
            sender_is_customer=True,
            message=message_text,
        )
    return Response(CustomerTicketMessageSerializer(message).data, status=status.HTTP_201_CREATED)
