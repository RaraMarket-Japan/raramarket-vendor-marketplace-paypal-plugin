"""
Django REST Framework serializers for PayPal package.
"""

from rest_framework import serializers
from .models import PayPalConfig


class PayPalConfigSerializer(serializers.ModelSerializer):
    """Serializer for PayPal configuration."""
    
    class Meta:
        model = PayPalConfig
        fields = [
            'id', 'name', 'mode', 'is_active','client_id', 'client_secret',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def create(self, validated_data):
        """Create a new PayPal configuration with encrypted credentials."""
        from .credentials import CredentialManager
        
        # Get credentials from request data
        client_id = self.context['request'].data.get('client_id')
        client_secret = self.context['request'].data.get('client_secret')
        
        if not client_id or not client_secret:
            raise serializers.ValidationError("client_id and client_secret are required")
        
        # Use credential manager to store encrypted credentials
        credential_manager = CredentialManager()
        config = credential_manager.store_credentials(
            name=validated_data['name'],
            client_id=client_id,
            client_secret=client_secret,
            mode=validated_data.get('mode', 'sandbox')
        )
        
        return config


class PayPalConfigUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating PayPal configuration."""
    
    client_id = serializers.CharField(write_only=True, required=False)
    client_secret = serializers.CharField(write_only=True, required=False)
    
    class Meta:
        model = PayPalConfig
        fields = [
            'id', 'name', 'mode', 'is_active', 
            'client_id', 'client_secret',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def update(self, instance, validated_data):
        """Update PayPal configuration."""
        from .credentials import CredentialManager
        
        client_id = validated_data.pop('client_id', None)
        client_secret = validated_data.pop('client_secret', None)
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        
        # Update credentials if provided
        if client_id or client_secret or 'mode' in validated_data:
            credential_manager = CredentialManager()
            credential_manager.update_credentials(
                name=instance.name,
                client_id=client_id,
                client_secret=client_secret,
                mode=validated_data.get('mode')
            )
        
        instance.save()
        return instance


class PayPalOrderSerializer(serializers.Serializer):
    """Serializer for creating PayPal orders."""
    
    intent = serializers.ChoiceField(
        choices=[('CAPTURE', 'Capture'), ('AUTHORIZE', 'Authorize')],
        default='CAPTURE'
    )
    purchase_units = serializers.ListField(
        child=serializers.DictField(),
        min_length=1
    )
    application_context = serializers.DictField(required=False)
    
    def validate_purchase_units(self, value):
        """Validate purchase units."""
        for unit in value:
            if 'amount' not in unit:
                raise serializers.ValidationError("Each purchase unit must have an 'amount' field")
            
            amount = unit['amount']
            if 'currency_code' not in amount or 'value' not in amount:
                raise serializers.ValidationError("Amount must have 'currency_code' and 'value' fields")
        
        return value


class PayPalCaptureSerializer(serializers.Serializer):
    """Serializer for capturing PayPal payments."""
    
    note_to_payer = serializers.CharField(required=False, max_length=255)


class PayPalRefundSerializer(serializers.Serializer):
    """Serializer for refunding PayPal payments."""
    
    amount = serializers.DictField(required=False)
    note_to_payer = serializers.CharField(required=False, max_length=255)
    invoice_id = serializers.CharField(required=False, max_length=127)
    reason = serializers.ChoiceField(
        choices=[
            ('BUYER_REQUESTED', 'Buyer requested'),
            ('DUPLICATE_TRANSACTION', 'Duplicate transaction'),
            ('ITEM_NOT_RECEIVED', 'Item not received'),
            ('ITEM_NOT_AS_DESCRIBED', 'Item not as described'),
            ('UNAUTHORIZED_TRANSACTION', 'Unauthorized transaction'),
        ],
        required=False
    )
    
    def validate_amount(self, value):
        """Validate refund amount."""
        if 'currency_code' not in value or 'value' not in value:
            raise serializers.ValidationError("Amount must have 'currency_code' and 'value' fields")
        return value
