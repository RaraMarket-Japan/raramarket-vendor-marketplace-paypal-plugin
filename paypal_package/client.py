import requests
import json
import logging
import time
from typing import Dict, Any, Optional
from django.core.exceptions import ImproperlyConfigured
from .models import PayPalConfig   # assuming you store credentials in DB

logger = logging.getLogger(__name__)


class PayPalClient:
    """PayPal API client for making authenticated requests."""

    def __init__(self, config: Optional[PayPalConfig] = None):
        self.config = config or PayPalConfig.objects.filter(is_active=True).first()
        if not self.config:
            raise ImproperlyConfigured("No active PayPal configuration found.")

        self.access_token: Optional[str] = None
        self.token_expires_at: Optional[float] = None

    def _get_credentials(self) -> Dict[str, str]:
        """Get PayPal credentials (cleaned)."""
        if not self.config.client_id or not self.config.client_secret:
            raise ImproperlyConfigured("PayPal credentials missing in config")

        api_base_url = (
            "https://api-m.sandbox.paypal.com"
            if self.config.use_sandbox else
            "https://api-m.paypal.com"
        )

        # Strip whitespace/newlines just in case
        client_id = self.config.client_id.strip()
        client_secret = self.config.client_secret.strip()

        return {
            "client_id": client_id,
            "client_secret": client_secret,
            "api_base_url": api_base_url,
        }

    def _get_access_token(self) -> str:
        """Get or refresh PayPal access token."""
        if self.access_token and self.token_expires_at and time.time() < self.token_expires_at:
            return self.access_token

        credentials = self._get_credentials()

        auth_url = f"{credentials['api_base_url']}/v1/oauth2/token"
        auth_data = {"grant_type": "client_credentials"}
        auth_headers = {
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }

        try:
            response = requests.post(
                auth_url,
                data=auth_data,
                headers=auth_headers,
                auth=(credentials["client_id"], credentials["client_secret"]),
                timeout=30,
            )
            response.raise_for_status()
            token_data = response.json()

            # Save token with buffer (60s)
            self.access_token = token_data["access_token"]
            self.token_expires_at = time.time() + token_data.get("expires_in", 3600) - 60

            logger.info("✅ Successfully obtained PayPal access token")
            return self.access_token
        except requests.exceptions.RequestException as e:
            logger.error(f"❌ Failed to obtain PayPal access token: {e}")
            if hasattr(e, "response") and e.response:
                logger.error(f"Response: {e.response.text}")
            raise

    def _make_request(self, method: str, endpoint: str, json_data=None, params=None) -> Dict[str, Any]:
        """Make an authenticated request to PayPal API with JSON."""
        token = self._get_access_token()
        credentials = self._get_credentials()
        url = f"{credentials['api_base_url']}{endpoint}"

        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "Accept-Language": "en_US",
        }

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                json=json_data,
                params=params,
                timeout=30,
            )

            print(f"Response Status Code: {response.status_code}")
            response.raise_for_status()
            return response.json() if response.content else {}
        except requests.RequestException as e:
            logger.error(f"PayPal API request failed: {e}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    # === API METHODS ===
    def create_order(self, order_data: Dict[str, Any]):
        return self._make_request("POST", "/v2/checkout/orders", json_data=order_data)

    def get_order(self, order_id: str):
        return self._make_request("GET", f"/v2/checkout/orders/{order_id}")

    def capture_payment(self, order_id: str):
        return self._make_request("POST", f"/v2/checkout/orders/{order_id}/capture")

    def get_payment_details(self, payment_id: str):
        return self._make_request("GET", f"/v2/payments/captures/{payment_id}")

    def verify_webhook_signature(self, webhook_id: str, headers: Dict[str, Any], body: Any):
        verification_data = {
            "auth_algo": headers.get("PAYPAL-AUTH-ALGO"),
            "cert_url": headers.get("PAYPAL-CERT-URL"),
            "transmission_id": headers.get("PAYPAL-TRANSMISSION-ID"),
            "transmission_sig": headers.get("PAYPAL-TRANSMISSION-SIG"),
            "transmission_time": headers.get("PAYPAL-TRANSMISSION-TIME"),
            "webhook_id": webhook_id,
            "webhook_event": json.loads(body) if isinstance(body, str) else body,
        }
        # ✅ Fixed: use json_data instead of data
        return self._make_request("POST", "/v1/notifications/verify-webhook-signature", json_data=verification_data)
