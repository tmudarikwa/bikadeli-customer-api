import hashlib
import hmac
import json
import time
import uuid
from decimal import ROUND_FLOOR, Decimal, InvalidOperation

from django.conf import settings
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.throttling import UserRateThrottle
from rest_framework.views import APIView

from .models import (
    CustomerAccount,
    LoyaltyCreditOutbox,
    LoyaltyOrderAward,
    LoyaltyTransaction,
)

POINTS_PER_DOLLAR = 1
POINTS_PER_WALLET_DOLLAR = 100
MAX_CALLBACK_SKEW_SECONDS = 300
MAX_CALLBACK_BODY_BYTES = 4096


class RedeemPointsSerializer(serializers.Serializer):
    points = serializers.IntegerField(min_value=POINTS_PER_WALLET_DOLLAR)

    def validate_points(self, value):
        if value % POINTS_PER_WALLET_DOLLAR:
            raise serializers.ValidationError(
                f'Points must be redeemed in multiples of {POINTS_PER_WALLET_DOLLAR}.'
            )
        return value


class LoyaltyMutationThrottle(UserRateThrottle):
    scope = 'mutation'

    def get_cache_key(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return None
        return self.cache_format % {'scope': self.scope, 'ident': request.user.id}


def _redemption_response(entry, balance, replay=False):
    result = {
        'points_redeemed': entry.points,
        'wallet_credit': format(entry.wallet_credit, '.2f'),
        'points_balance': balance,
        'wallet_credit_status': entry.status,
    }
    if replay:
        result['already_processed'] = True
    return result


def _is_customer(request):
    return bool(request.auth and request.auth.get('user_type') == 'CUSTOMER')


class LoyaltyBalanceView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not _is_customer(request):
            return Response({'error': 'Customer access required'}, status=status.HTTP_403_FORBIDDEN)
        account, _ = CustomerAccount.objects.get_or_create(owner_user_id=request.user.id)
        points = account.loyalty_points
        return Response({
            'points': points,
            'wallet_credit_value': format((Decimal(points) / POINTS_PER_WALLET_DOLLAR).quantize(Decimal('0.01')), '.2f'),
            'points_per_wallet_dollar': POINTS_PER_WALLET_DOLLAR,
        })


class LoyaltyTransactionHistoryView(APIView):
    permission_classes = (IsAuthenticated,)

    def get(self, request):
        if not _is_customer(request):
            return Response({'error': 'Customer access required'}, status=status.HTTP_403_FORBIDDEN)
        try:
            page_number = int(request.query_params.get('page', '1'))
            page_size = int(request.query_params.get('page_size', '20'))
        except (TypeError, ValueError):
            return Response({'error': 'Page and page_size must be integers'}, status=status.HTTP_400_BAD_REQUEST)
        if page_number < 1 or not 1 <= page_size <= 100:
            return Response(
                {'error': 'Page must be positive and page_size must be between 1 and 100'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        transactions = LoyaltyTransaction.objects.filter(customer__owner_user_id=request.user.id).order_by(
            '-created_at', '-id'
        )
        page = Paginator(transactions, page_size).get_page(page_number)
        return Response(
            {
                'count': page.paginator.count,
                'next': page.next_page_number() if page.has_next() else None,
                'previous': page.previous_page_number() if page.has_previous() else None,
                'results': [
                    {
                        'id': entry.id,
                        'order_id': entry.order_id,
                        'transaction_type': entry.transaction_type,
                        'points': entry.points,
                        'wallet_credit': format(entry.wallet_credit, '.2f'),
                        'status': entry.status,
                        'created_at': entry.created_at,
                    }
                    for entry in page.object_list
                ],
            }
        )


class RedeemLoyaltyPointsView(APIView):
    permission_classes = (IsAuthenticated,)
    throttle_classes = (LoyaltyMutationThrottle,)

    def post(self, request):
        if not _is_customer(request):
            return Response({'error': 'Customer access required'}, status=status.HTTP_403_FORBIDDEN)
        key = request.headers.get('Idempotency-Key', '').strip()
        if not key or len(key) > 64:
            return Response(
                {'error': 'A unique Idempotency-Key header (up to 64 characters) is required.'},
                status=status.HTTP_400_BAD_REQUEST,
            )
        serializer = RedeemPointsSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        points = serializer.validated_data['points']

        with transaction.atomic():
            account, _ = CustomerAccount.objects.get_or_create(owner_user_id=request.user.id)
            account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
            existing = LoyaltyTransaction.objects.filter(
                customer=account, idempotency_key=key, transaction_type=LoyaltyTransaction.REDEEM
            ).first()
            if existing:
                if existing.points != points:
                    return Response(
                        {'error': 'Idempotency-Key was already used for a different redemption.'},
                        status=status.HTTP_409_CONFLICT,
                    )
                return Response(_redemption_response(existing, account.loyalty_points, replay=True))
            if account.loyalty_points < points:
                return Response(
                    {'error': 'Not enough loyalty points.', 'points_balance': account.loyalty_points},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            credit = (Decimal(points) / POINTS_PER_WALLET_DOLLAR).quantize(Decimal('0.01'))
            entry = LoyaltyTransaction.objects.create(
                customer=account,
                transaction_type=LoyaltyTransaction.REDEEM,
                points=points,
                wallet_credit=credit,
                idempotency_key=key,
                status=LoyaltyTransaction.STATUS_PENDING,
            )
            account.loyalty_points -= points
            account.save(update_fields=['loyalty_points', 'updated_at'])
            LoyaltyCreditOutbox.objects.create(
                transaction=entry,
                event_id=uuid.uuid4(),
                owner_user_id=account.owner_user_id,
                amount=credit,
            )
        return Response(_redemption_response(entry, account.loyalty_points))


class OrderLoyaltyAwardCallbackView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    def post(self, request):
        secret = settings.ORDERS_LOYALTY_CALLBACK_SECRET
        timestamp_header = request.headers.get('X-Loyalty-Timestamp', '')
        signature = request.headers.get('X-Loyalty-Signature', '')
        try:
            timestamp = int(timestamp_header)
        except (TypeError, ValueError):
            return Response({'error': 'Invalid signature timestamp'}, status=401)
        if abs(time.time() - timestamp) > MAX_CALLBACK_SKEW_SECONDS:
            return Response({'error': 'Expired signature timestamp'}, status=401)
        raw_body = request.body
        if len(raw_body) > MAX_CALLBACK_BODY_BYTES:
            return Response({'error': 'Payload is too large'}, status=413)
        expected = hmac.new(secret.encode(), timestamp_header.encode() + b'.' + raw_body, hashlib.sha256).hexdigest()
        if not secret or not hmac.compare_digest(signature, expected):
            return Response({'error': 'Invalid signature'}, status=401)
        try:
            payload = json.loads(raw_body)
            event_id = uuid.UUID(payload['event_id'])
            order_id = payload['order_id']
            owner_user_id = payload['customer_user_id']
            if not isinstance(payload['eligible_spend'], str):
                raise TypeError('eligible_spend must be a decimal string')
            spend = Decimal(payload['eligible_spend'])
            prime_multiplier = payload.get('prime_multiplier', 1)
            order_status = payload['status']
            payment_status = payload['payment_status']
        except (json.JSONDecodeError, UnicodeDecodeError, TypeError, ValueError, KeyError, InvalidOperation):
            return Response({'error': 'Invalid loyalty event'}, status=400)
        if (
            not isinstance(payload, dict)
            or type(order_id) is not int or order_id < 1
            or type(owner_user_id) is not int or owner_user_id < 1
            or type(prime_multiplier) is not int or prime_multiplier not in (1, 2)
            or order_status != 'DELIVERED' or payment_status != 'PAID'
            or not spend.is_finite() or spend < 0 or spend >= Decimal(1000000)
            or spend.as_tuple().exponent < -2
        ):
            return Response({'error': 'Invalid loyalty event'}, status=400)
        points = int((spend * POINTS_PER_DOLLAR).to_integral_value(rounding=ROUND_FLOOR)) * prime_multiplier
        payload_hash = hashlib.sha256(raw_body).hexdigest()
        try:
            with transaction.atomic():
                award = LoyaltyOrderAward.objects.filter(order_id=order_id).first()
                if award:
                    if award.event_id != event_id or award.payload_hash != payload_hash:
                        return Response({'error': 'Order already has a loyalty award'}, status=409)
                    return Response({'event_id': str(event_id), 'awarded_points': award.awarded_points, 'already_processed': True})
                account, _ = CustomerAccount.objects.get_or_create(owner_user_id=owner_user_id)
                account = CustomerAccount.objects.select_for_update().get(pk=account.pk)
                LoyaltyOrderAward.objects.create(
                    order_id=order_id, customer_user_id=owner_user_id, event_id=event_id,
                    payload_hash=payload_hash, eligible_spend=spend, awarded_points=points,
                )
                if points:
                    LoyaltyTransaction.objects.create(
                        customer=account,
                        order_id=order_id,
                        transaction_type=LoyaltyTransaction.EARN,
                        points=points,
                        source_event_id=event_id,
                        status=LoyaltyTransaction.STATUS_COMPLETED,
                    )
                    account.loyalty_points += points
                    account.save(update_fields=['loyalty_points', 'updated_at'])
        except IntegrityError:
            award = LoyaltyOrderAward.objects.filter(order_id=order_id).first()
            if award and award.event_id == event_id and award.payload_hash == payload_hash:
                return Response({'event_id': str(event_id), 'awarded_points': award.awarded_points, 'already_processed': True})
            return Response({'error': 'Loyalty event conflicts with an existing award'}, status=409)
        return Response({'event_id': str(event_id), 'awarded_points': points})


def validate_wallet_callback(*, raw_body, timestamp_header, signature, secret):
    try:
        timestamp = int(timestamp_header)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - timestamp) > MAX_CALLBACK_SKEW_SECONDS or len(raw_body) > MAX_CALLBACK_BODY_BYTES:
        return False
    expected = hmac.new(secret.encode(), timestamp_header.encode() + b'.' + raw_body, hashlib.sha256).hexdigest()
    return bool(secret) and hmac.compare_digest(signature, expected)
