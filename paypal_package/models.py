"""
Django models for PayPal package.
"""

from django.db import models
from django.conf import settings
from django.core.validators import URLValidator
from django.utils import timezone
import json


class PayPalConfig(models.Model):
    """Model to store PayPal configuration settings."""
    
    name = models.CharField(max_length=100, unique=True, help_text="Configuration name")
    client_id = models.CharField(max_length=600, help_text="PayPal Client ID")
    client_secret = models.CharField(max_length=600, help_text="PayPal Client Secret")
    mode = models.CharField(
        max_length=10,
        choices=[('sandbox', 'Sandbox'), ('live', 'Live')],
        default='sandbox',
        help_text="PayPal environment mode"
    )
    is_active = models.BooleanField(default=True, help_text="Whether this configuration is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "PayPal Configuration"
        verbose_name_plural = "PayPal Configurations"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} ({self.mode})"
    
    @property
    def api_base_url(self):
        """Get the PayPal API base URL based on mode."""
        if self.mode == 'live':
            return 'https://api-m.paypal.com'
        return 'https://api-m.sandbox.paypal.com'

