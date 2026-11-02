from rest_framework import serializers

from .models import CustomerSupportTicket, CustomerTicketMessage, SavedAddress


class CustomerProductFavouriteIdSerializer(serializers.Serializer):
    product_id = serializers.IntegerField(min_value=1)


class CustomerProductFavouriteSerializer(serializers.Serializer):
    product_id = serializers.IntegerField()
    product_name = serializers.CharField()
    product_price = serializers.DecimalField(max_digits=10, decimal_places=2)
    product_image = serializers.CharField(allow_null=True, allow_blank=True)
    created_at = serializers.DateTimeField()


class SavedAddressSerializer(serializers.ModelSerializer):
    location_lat = serializers.FloatField(required=False, allow_null=True)
    location_lng = serializers.FloatField(required=False, allow_null=True)
    location = serializers.SerializerMethodField()

    class Meta:
        model = SavedAddress
        fields = (
            'id',
            'label',
            'full_address',
            'address_type',
            'location',
            'location_lat',
            'location_lng',
            'what3words',
            'delivery_instructions',
            'is_default',
            'created_at',
        )

    def get_location(self, instance):
        if instance.location_lat is None or instance.location_lng is None:
            return None
        return {
            'type': 'Point',
            'coordinates': [instance.location_lng, instance.location_lat],
        }

    def validate(self, attrs):
        lat = attrs.get('location_lat')
        lng = attrs.get('location_lng')
        if (lat is None) != (lng is None):
            raise serializers.ValidationError('Both location_lat and location_lng are required together')
        if lat is not None and not -90 <= lat <= 90:
            raise serializers.ValidationError({'location_lat': 'Must be between -90 and 90.'})
        if lng is not None and not -180 <= lng <= 180:
            raise serializers.ValidationError({'location_lng': 'Must be between -180 and 180.'})
        return attrs


class CustomerSupportTicketSerializer(serializers.ModelSerializer):
    order = serializers.IntegerField(source='order_id', required=False, allow_null=True)
    last_message = serializers.SerializerMethodField()

    class Meta:
        model = CustomerSupportTicket
        fields = (
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
        )
        read_only_fields = ('id', 'status', 'created_at', 'updated_at', 'resolved_at', 'last_message')

    def get_last_message(self, obj):
        last = getattr(obj, 'last_message', None)
        if last is None:
            last_id = getattr(obj, 'last_message_id', None)
            if last_id is not None:
                last = CustomerTicketMessage.objects.filter(pk=last_id).first()
            else:
                last = obj.messages.order_by('-created_at').first()
        if last is None:
            return None
        return {
            'message': last.message[:120],
            'sender_is_customer': last.sender_is_customer,
            'created_at': last.created_at.isoformat(),
        }


class CustomerTicketMessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = CustomerTicketMessage
        fields = ('id', 'sender_is_customer', 'message', 'created_at')
        read_only_fields = fields


class CustomerVendorFavouriteIdSerializer(serializers.Serializer):
    vendor_id = serializers.IntegerField(min_value=1)


class CustomerVendorFavouriteSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    vendor_id = serializers.IntegerField()
    vendor_name = serializers.CharField()
    created_at = serializers.DateTimeField()
