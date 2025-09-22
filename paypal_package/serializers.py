"""
Django REST Framework serializers for PayPal package.
"""

from rest_framework import serializers
from .models import PayPalConfig


class PayPalConfigSerializer(serializers.ModelSerializer):


    class Meta:
        model = PayPalConfig
        fields = [
            'id', 'name', 'is_active', 'use_sandbox',
            'client_id', 'client_secret',
            'created_at', 'updated_at',
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


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