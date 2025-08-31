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


class WebhookEvent(models.Model):
    """Model to store webhook events received from PayPal."""
    
    EVENT_TYPES = [
        ('PAYMENT.CAPTURE.COMPLETED', 'Payment Capture Completed'),
        ('PAYMENT.CAPTURE.DENIED', 'Payment Capture Denied'),
        ('PAYMENT.CAPTURE.PENDING', 'Payment Capture Pending'),
        ('PAYMENT.CAPTURE.REFUNDED', 'Payment Capture Refunded'),
        ('PAYMENT.CAPTURE.REVERSED', 'Payment Capture Reversed'),
        ('CHECKOUT.ORDER.APPROVED', 'Checkout Order Approved'),
        ('CHECKOUT.ORDER.COMPLETED', 'Checkout Order Completed'),
        ('CHECKOUT.ORDER.PROCESSED', 'Checkout Order Processed'),
        ('BILLING.SUBSCRIPTION.ACTIVATED', 'Billing Subscription Activated'),
        ('BILLING.SUBSCRIPTION.CANCELLED', 'Billing Subscription Cancelled'),
        ('BILLING.SUBSCRIPTION.CREATED', 'Billing Subscription Created'),
        ('BILLING.SUBSCRIPTION.SUSPENDED', 'Billing Subscription Suspended'),
        ('BILLING.SUBSCRIPTION.UPDATED', 'Billing Subscription Updated'),
    ]
    
    event_id = models.CharField(max_length=255, unique=True, help_text="PayPal event ID")
    event_type = models.CharField(max_length=100, choices=EVENT_TYPES, help_text="Type of webhook event")
    resource_type = models.CharField(max_length=100, help_text="Resource type from PayPal")
    resource_id = models.CharField(max_length=255, help_text="Resource ID from PayPal")
    summary = models.TextField(blank=True, help_text="Event summary")
    raw_data = models.JSONField(help_text="Raw webhook data from PayPal")
    processed = models.BooleanField(default=False, help_text="Whether the event has been processed")
    processed_at = models.DateTimeField(null=True, blank=True, help_text="When the event was processed")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Webhook Event"
        verbose_name_plural = "Webhook Events"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['event_type']),
            models.Index(fields=['processed']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.event_type} - {self.event_id}"
    
    def mark_as_processed(self):
        """Mark the event as processed."""
        self.processed = True
        self.processed_at = timezone.now()
        self.save(update_fields=['processed', 'processed_at'])


class WebhookEndpoint(models.Model):
    """Model to store webhook endpoint configurations."""
    
    name = models.CharField(max_length=100, help_text="Webhook endpoint name")
    url = models.URLField(validators=[URLValidator()], help_text="Webhook endpoint URL")
    events = models.JSONField(help_text="List of events to listen for")
    webhook_id = models.CharField(max_length=255, blank=True, help_text="PayPal webhook ID")
    is_active = models.BooleanField(default=True, help_text="Whether this webhook is active")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Webhook Endpoint"
        verbose_name_plural = "Webhook Endpoints"
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.name} - {self.url}"
    
    def get_events_list(self):
        """Get events as a list."""
        if isinstance(self.events, str):
            return json.loads(self.events)
        return self.events or []
