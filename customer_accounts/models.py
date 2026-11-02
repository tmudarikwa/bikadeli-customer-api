from django.db import models
from django.utils import timezone


class CustomerAccount(models.Model):
    owner_user_id = models.PositiveBigIntegerField(unique=True, db_index=True)
    loyalty_points = models.PositiveIntegerField(default=0, db_default=0)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['id']


class LoyaltyTransaction(models.Model):
    EARN = 'EARN'
    REDEEM = 'REDEEM'
    TRANSACTION_TYPES = ((EARN, 'Earned'), (REDEEM, 'Redeemed'))
    STATUS_PENDING = 'PENDING'
    STATUS_COMPLETED = 'COMPLETED'
    STATUS_CHOICES = ((STATUS_PENDING, 'Pending'), (STATUS_COMPLETED, 'Completed'))

    customer = models.ForeignKey(CustomerAccount, on_delete=models.PROTECT, related_name='loyalty_transactions')
    order_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    transaction_type = models.CharField(max_length=8, choices=TRANSACTION_TYPES)
    points = models.PositiveIntegerField()
    wallet_credit = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    idempotency_key = models.CharField(max_length=64, blank=True)
    source_event_id = models.UUIDField(null=True, blank=True, unique=True)
    source_legacy_id = models.PositiveBigIntegerField(null=True, blank=True, unique=True)
    status = models.CharField(max_length=12, choices=STATUS_CHOICES, default=STATUS_COMPLETED)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(fields=['order_id'], condition=models.Q(transaction_type='EARN', order_id__isnull=False), name='uq_loyalty_earn_order'),
            models.UniqueConstraint(fields=['customer', 'idempotency_key'], condition=models.Q(idempotency_key__gt=''), name='uq_loyalty_customer_idempotency'),
        ]
        indexes = [models.Index(fields=['customer', '-created_at'])]


class LoyaltyOrderAward(models.Model):
    order_id = models.PositiveBigIntegerField(unique=True, db_index=True)
    customer_user_id = models.PositiveBigIntegerField(db_index=True)
    event_id = models.UUIDField(unique=True)
    payload_hash = models.CharField(max_length=64)
    eligible_spend = models.DecimalField(max_digits=10, decimal_places=2)
    awarded_points = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['created_at']


class LoyaltyCreditOutbox(models.Model):
    transaction = models.OneToOneField(LoyaltyTransaction, on_delete=models.PROTECT, related_name='credit_outbox')
    event_id = models.UUIDField(unique=True)
    owner_user_id = models.PositiveBigIntegerField(db_index=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(default=timezone.now)
    delivered_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now, db_index=True)
    last_error = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ['created_at']


class SavedAddress(models.Model):
    ADDRESS_TYPES = (
        ('HOME', 'Home'),
        ('WORK', 'Work'),
        ('OTHER', 'Other'),
        ('FRIEND', 'Friend/Family'),
        ('HOTEL', 'Hotel/Guesthouse'),
    )

    customer = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='saved_addresses')
    address_type = models.CharField(max_length=20, choices=ADDRESS_TYPES, default='OTHER')
    label = models.CharField(max_length=100)
    full_address = models.TextField()
    what3words = models.CharField(max_length=100, blank=True)
    location_lat = models.FloatField(null=True, blank=True)
    location_lng = models.FloatField(null=True, blank=True)
    delivery_instructions = models.TextField(blank=True)
    is_default = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-is_default', '-created_at']
        indexes = [
            models.Index(fields=['customer', 'is_default']),
        ]


class CustomerVendorFavourite(models.Model):
    customer = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='vendor_favourites')
    vendor_id = models.PositiveBigIntegerField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'vendor_id'],
                name='uq_customer_vendor_favourite',
            ),
        ]
        indexes = [
            models.Index(fields=['customer', 'created_at']),
        ]


class CustomerProductFavourite(models.Model):
    customer = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='product_favourites')
    product_id = models.PositiveBigIntegerField(db_index=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['customer', 'product_id'],
                name='uq_customer_product_favourite',
            ),
        ]
        indexes = [
            models.Index(fields=['customer', 'created_at']),
        ]


class CustomerSupportTicket(models.Model):
    PRIORITY_CHOICES = (
        ('LOW', 'Low'),
        ('MEDIUM', 'Medium'),
        ('HIGH', 'High'),
        ('URGENT', 'Urgent'),
    )
    STATUS_CHOICES = (
        ('OPEN', 'Open'),
        ('IN_PROGRESS', 'In Progress'),
        ('WAITING_CUSTOMER', 'Waiting for Customer'),
        ('RESOLVED', 'Resolved'),
        ('CLOSED', 'Closed'),
    )
    CATEGORY_CHOICES = (
        ('DELIVERY', 'Delivery'),
        ('PAYMENT', 'Payment'),
        ('REFUND', 'Refund'),
        ('VENDOR', 'Vendor'),
        ('DRIVER', 'Driver'),
        ('ACCOUNT', 'Account'),
        ('TECHNICAL', 'Technical'),
        ('SAFETY', 'Safety'),
        ('FRAUD', 'Fraud'),
        ('ACCESSIBILITY', 'Accessibility'),
        ('GENERAL', 'General'),
    )

    customer = models.ForeignKey(CustomerAccount, on_delete=models.CASCADE, related_name='support_tickets')
    order_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    subject = models.CharField(max_length=200)
    description = models.TextField()
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default='GENERAL')
    priority = models.CharField(max_length=10, choices=PRIORITY_CHOICES, default='MEDIUM')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='OPEN')
    escalated = models.BooleanField(default=False)
    escalation_reason = models.CharField(max_length=200, blank=True)
    escalation_team = models.CharField(max_length=20, blank=True, default='')
    assigned_to_user_id = models.PositiveBigIntegerField(null=True, blank=True, db_index=True)
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(default=timezone.now)
    resolved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-created_at']  # noqa: RUF012
        indexes = [models.Index(fields=['customer', 'status'])]  # noqa: RUF012


class CustomerTicketMessage(models.Model):
    ticket = models.ForeignKey(CustomerSupportTicket, on_delete=models.CASCADE, related_name='messages')
    sender_is_customer = models.BooleanField(default=True)
    message = models.TextField()
    channel = models.CharField(max_length=10, blank=True, default='')
    delivery_result = models.CharField(max_length=50, blank=True, default='PENDING')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['created_at']  # noqa: RUF012
        indexes = [models.Index(fields=['ticket', 'created_at'])]  # noqa: RUF012
