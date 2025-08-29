"""
PayPal API client for Django REST Framework.
"""

import requests
import json
import logging
from typing import Dict, Any, Optional
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from .credentials import CredentialManager, DatabaseCredentialManager

logger = logging.getLogger(__name__)


class PayPalClient:
    """PayPal API client for making authenticated requests."""
    
    def __init__(self, credential_manager=None):
        self.credential_manager = credential_manager or self._get_credential_manager()
        self.access_token = None
        self.token_expires_at = None
    
    def _get_credential_manager(self):
        """Get the appropriate credential manager."""
        # Use database-based manager only
        try:
            return CredentialManager()
        except ImproperlyConfigured:
            # Fall back to database-only manager
            return DatabaseCredentialManager()
    
    def _get_credentials(self):
        """Get PayPal credentials."""
        return self.credential_manager.get_credentials()
    
    def _get_access_token(self):
        """Get or refresh PayPal access token."""
        import time

        # ✅ If token exists and not expired, return cached one
        if self.access_token and self.token_expires_at:
            if time.time() < self.token_expires_at:
                return self.access_token

        # ✅ Otherwise, request a new token
        credentials = self._get_credentials()
        print("credentials", credentials)

        auth_url = f"{credentials['api_base_url']}/v1/oauth2/token"

        auth_data = {
            'grant_type': 'client_credentials'
        }

        auth_headers = {
            'Content-Type': 'application/x-www-form-urlencoded',
            'Accept': 'application/json',
            'Accept-Language': 'en_US'
        }

        try:
            response = requests.post(
                auth_url,
                data=auth_data,
                headers=auth_headers,
                auth=(credentials['client_id'], credentials['client_secret']),
                timeout=30
            )
            response.raise_for_status()

            token_data = response.json()

            # ✅ Save token and expiry time (with 60s buffer)
            self.access_token = token_data['access_token']
            self.token_expires_at = time.time() + token_data.get('expires_in', 3600) - 60

            logger.info("✅ Successfully obtained PayPal access token")
            return self.access_token

        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to obtain PayPal access token: {e}")
            raise
    
    def _make_request(self, method, endpoint, data=None, params=None):
        """Make an authenticated request to PayPal API."""
        token = self._get_access_token()
        credentials = self._get_credentials()
        
        url = f"{credentials['api_base_url']}{endpoint}"
        print ("credentials", credentials)
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json',
            'Accept': 'application/json',
            'Accept-Language': 'en_US'
        }
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=data,
                params=params,
                timeout=30
            )
            response.raise_for_status()
            
            if response.content:
                return response.json()
            return {}
            
        except requests.exceptions.RequestException as e:
            logger.error(f"PayPal API request failed: {e}")
            if hasattr(e, 'response') and e.response:
                logger.error(f"Response: {e.response.text}")
            raise
    
    def create_order(self, order_data):
        """Create a PayPal order."""
        endpoint = '/v2/checkout/orders'
        return self._make_request('POST', endpoint, data=order_data)
    
    def get_order(self, order_id):
        """Get order details."""
        endpoint = f'/v2/checkout/orders/{order_id}'
        return self._make_request('GET', endpoint)
    
    def capture_payment(self, order_id):
        """Capture payment for an order."""
        endpoint = f'/v2/checkout/orders/{order_id}/capture'
        return self._make_request('POST', endpoint)
    
    def refund_payment(self, capture_id, refund_data):
        """Refund a payment."""
        endpoint = f'/v2/payments/captures/{capture_id}/refund'
        return self._make_request('POST', endpoint, data=refund_data)
    
    def create_webhook(self, webhook_data):
        """Create a webhook."""
        endpoint = '/v1/notifications/webhooks'
        return self._make_request('POST', endpoint, data=webhook_data)
    
    def list_webhooks(self):
        """List all webhooks."""
        endpoint = '/v1/notifications/webhooks'
        return self._make_request('GET', endpoint)
    
    def delete_webhook(self, webhook_id):
        """Delete a webhook."""
        endpoint = f'/v1/notifications/webhooks/{webhook_id}'
        return self._make_request('DELETE', endpoint)
    
    def verify_webhook_signature(self, webhook_id, headers, body):
        """Verify webhook signature."""
        endpoint = '/v1/notifications/verify-webhook-signature'
        
        verification_data = {
            'auth_algo': headers.get('PAYPAL-AUTH-ALGO'),
            'cert_url': headers.get('PAYPAL-CERT-URL'),
            'transmission_id': headers.get('PAYPAL-TRANSMISSION-ID'),
            'transmission_sig': headers.get('PAYPAL-TRANSMISSION-SIG'),
            'transmission_time': headers.get('PAYPAL-TRANSMISSION-TIME'),
            'webhook_id': webhook_id,
            'webhook_event': json.loads(body) if isinstance(body, str) else body
        }
        
        return self._make_request('POST', endpoint, data=verification_data)
    
    def get_payment_details(self, payment_id):
        """Get payment details."""
        endpoint = f'/v2/payments/captures/{payment_id}'
        return self._make_request('GET', endpoint)
    
    def create_subscription(self, subscription_data):
        """Create a subscription."""
        endpoint = '/v1/billing/subscriptions'
        return self._make_request('POST', endpoint, data=subscription_data)
    
    def get_subscription(self, subscription_id):
        """Get subscription details."""
        endpoint = f'/v1/billing/subscriptions/{subscription_id}'
        return self._make_request('GET', endpoint)
    
    def cancel_subscription(self, subscription_id, reason=None):
        """Cancel a subscription."""
        endpoint = f'/v1/billing/subscriptions/{subscription_id}/cancel'
        data = {}
        if reason:
            data['reason'] = reason
        return self._make_request('POST', endpoint, data=data)
