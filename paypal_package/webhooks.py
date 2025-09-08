"""
Webhook management and handling for PayPal package.
"""
import os
import json
import logging
import hashlib
import hmac
from typing import Dict, Any, List, Optional
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from .client import PayPalClient
from .models import WebhookEvent, WebhookEndpoint

logger = logging.getLogger(__name__)


class WebhookManager:
    """Manages PayPal webhook creation and configuration."""
    
    def __init__(self, client=None):
        self.client = client or PayPalClient()
    
    def create_webhook(self, url: str, events: List[str], name: str = None) -> Dict[str, Any]:
        """Create a new PayPal webhook."""
        webhook_data = {
            'url': url,
            'event_types': [{'name': event} for event in events]
        }
        
        try:
            response = self.client.create_webhook(webhook_data)
            
            # Store webhook endpoint in database
            webhook_endpoint = WebhookEndpoint.objects.create(
                name=name or f"Webhook for {url}",
                url=url,
                events=events,
                webhook_id=response.get('id'),
                is_active=True
            )
            
            logger.info(f"Created webhook: {webhook_endpoint.name} with ID: {webhook_endpoint.webhook_id}")
            return response
            
        except Exception as e:
            logger.error(f"Failed to create webhook: {e}")
            raise
    
    def list_webhooks(self) -> List[Dict[str, Any]]:
        """List all PayPal webhooks."""
        try:
            response = self.client.list_webhooks()
            return response.get('webhooks', [])
        except Exception as e:
            logger.error(f"Failed to list webhooks: {e}")
            raise
    
    def delete_webhook(self, webhook_id: str) -> bool:
        """Delete a PayPal webhook."""
        try:
            self.client.delete_webhook(webhook_id)
            
            # Remove from database
            WebhookEndpoint.objects.filter(webhook_id=webhook_id).delete()
            
            logger.info(f"Deleted webhook: {webhook_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to delete webhook {webhook_id}: {e}")
            raise
    
    def get_webhook_endpoints(self) -> List[WebhookEndpoint]:
        """Get all webhook endpoints from database."""
        return WebhookEndpoint.objects.filter(is_active=True)
    
    def update_webhook_events(self, webhook_id: str, events: List[str]) -> bool:
        """Update webhook events."""
        try:
            webhook_endpoint = WebhookEndpoint.objects.get(webhook_id=webhook_id)
            webhook_endpoint.events = events
            webhook_endpoint.save()
            return True
        except WebhookEndpoint.DoesNotExist:
            logger.error(f"Webhook endpoint not found: {webhook_id}")
            return False


class WebhookHandler:
    """Handles incoming PayPal webhook events."""
    
    def __init__(self, client=None):
        self.client = client or PayPalClient()
    
    def process_webhook(self, request) -> HttpResponse:
        """Process incoming webhook request (Django view)."""
        try:
            # Get webhook data
            body = request.body.decode('utf-8')
            headers = dict(request.headers)
            
            # Parse webhook event
            webhook_data = json.loads(body)
            event_id = webhook_data.get('id')
            event_type = webhook_data.get('event_type')
            
            # Check if event already processed
            if WebhookEvent.objects.filter(event_id=event_id).exists():
                logger.warning(f"Duplicate webhook event received: {event_id}")
                return JsonResponse({'status': 'already_processed'}, status=200)
            
            # Verify webhook signature (optional but recommended)
            if not self._verify_webhook_signature(headers, body):
                logger.warning(f"Invalid webhook signature for event: {event_id}")
                return JsonResponse({'error': 'Invalid signature'}, status=400)
            
            # Store webhook event
            webhook_event = WebhookEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                resource_type=webhook_data.get('resource_type', ''),
                resource_id=webhook_data.get('resource_id', ''),
                summary=webhook_data.get('summary', ''),
                raw_data=webhook_data
            )
            
            # Process the event
            self._process_event(webhook_event)
            
            logger.info(f"Successfully processed webhook event: {event_id}")
            return JsonResponse({'status': 'success'}, status=200)
            
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook request")
            return JsonResponse({'error': 'Invalid JSON'}, status=400)
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return JsonResponse({'error': 'Internal server error'}, status=500)
    
    def process_webhook_drf(self, request) -> Response:
        """Process incoming webhook request (Django REST Framework)."""
        try:
            # Get webhook data
            body = request.body.decode('utf-8')
            headers = dict(request.headers)
            
            # Parse webhook event
            webhook_data = json.loads(body)
            event_id = webhook_data.get('id')
            event_type = webhook_data.get('event_type')
            
            # Check if event already processed
            if WebhookEvent.objects.filter(event_id=event_id).exists():
                logger.warning(f"Duplicate webhook event received: {event_id}")
                return Response({'status': 'already_processed'}, status=status.HTTP_200_OK)
            
            # Verify webhook signature (optional but recommended)
            if not self._verify_webhook_signature(headers, body):
                logger.warning(f"Invalid webhook signature for event: {event_id}")
                return Response({'error': 'Invalid signature'}, status=status.HTTP_400_BAD_REQUEST)
            
            # Store webhook event
            webhook_event = WebhookEvent.objects.create(
                event_id=event_id,
                event_type=event_type,
                resource_type=webhook_data.get('resource_type', ''),
                resource_id=webhook_data.get('resource_id', ''),
                summary=webhook_data.get('summary', ''),
                raw_data=webhook_data
            )
            
            # Process the event
            self._process_event(webhook_event)
            
            logger.info(f"Successfully processed webhook event: {event_id}")
            return Response({'status': 'success'}, status=status.HTTP_200_OK)
            
        except json.JSONDecodeError:
            logger.error("Invalid JSON in webhook request")
            return Response({'error': 'Invalid JSON'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            logger.error(f"Error processing webhook: {e}")
            return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _verify_webhook_signature(self, headers: Dict[str, str], body: str) -> bool:
        """Verify webhook signature from PayPal."""
        try:
            # Get webhook ID from database (you might want to store this)
            # webhook_endpoints = WebhookEndpoint.objects.filter(is_active=True)
            # if not webhook_endpoints.exists():
            #     logger.warning("No active webhook endpoints found")
            #     return True  # Skip verification if no endpoints configured
            
            # Use the first active webhook endpoint
            webhook_id = os.environ.get("PAYPAL_WEBHOOK_ID")
            
            # Verify signature using PayPal API
            verification_result = self.client.verify_webhook_signature(
                webhook_id, headers, body
            )
            
            return verification_result.get('verification_status') == 'SUCCESS'
            
        except Exception as e:
            logger.error(f"Error verifying webhook signature: {e}")
            return False  # Fail closed for security
    
    def _process_event(self, webhook_event: WebhookEvent):
        """Process webhook event based on type."""
        try:
            if webhook_event.event_type == 'PAYMENT.CAPTURE.COMPLETED':
                self._handle_payment_completed(webhook_event)
            elif webhook_event.event_type == 'PAYMENT.CAPTURE.DENIED':
                self._handle_payment_denied(webhook_event)
            # elif webhook_event.event_type == 'PAYMENT.CAPTURE.REFUNDED':
            #     self._handle_payment_refunded(webhook_event)
            elif webhook_event.event_type == 'CHECKOUT.ORDER.COMPLETED':
                self._handle_order_completed(webhook_event)
            # elif webhook_event.event_type == 'BILLING.SUBSCRIPTION.ACTIVATED':
            #     self._handle_subscription_activated(webhook_event)
            # elif webhook_event.event_type == 'BILLING.SUBSCRIPTION.CANCELLED':
            #     self._handle_subscription_cancelled(webhook_event)
            else:
                logger.info(f"Unhandled event type: {webhook_event.event_type}")
            
            # Mark event as processed
            webhook_event.mark_as_processed()
            
        except Exception as e:
            logger.error(f"Error processing event {webhook_event.event_id}: {e}")
    
    def _handle_payment_completed(self, webhook_event: WebhookEvent):
        """Handle payment completed event."""
        logger.info(f"Payment completed: {webhook_event.resource_id}")
        # Update Payment and related Order/OrderGroup status
        try:
            from order.models import Payment, Order, OrderGroup
            data = webhook_event.raw_data or {}
            resource = data.get('resource', {})
            # capture ID or payment id
            capture_id = resource.get('id') or webhook_event.resource_id
            # Try to find a Payment record by payment_id or capture_id
            payment = Payment.objects.filter(payment_id__iexact=capture_id).first()
            if not payment:
                # sometimes custom_id contains order id in purchase_units
                pu = resource.get('supplementary_data', {}) or {}
                # fallback: try to read order id from invoice/custom_id
                order_id = None
                for pu_item in (resource.get('purchase_units') or []):
                    order_id = pu_item.get('custom_id') or order_id

                if order_id:
                    # mark payment for order
                    order = Order.objects.filter(id=order_id).first()
                    if order:
                        payment = Payment.objects.filter(order=order).first()

            if payment:
                payment.status = Payment.PAYMENT_COMPLETE
                # set paid amount if available
                paid = resource.get('amount', {}).get('value') or resource.get('amount', {}).get('total')
                if paid:
                    try:
                        payment.paid_amount = float(paid)
                    except Exception:
                        pass
                payment.payment_id = capture_id
                payment.save()

                # Update order/order group statuses
                if hasattr(payment, 'order') and payment.order:
                    order = payment.order
                    order.order_status = Order.OrderStatus.PROCESSING
                    order.save()
                elif hasattr(payment, 'order_group') and payment.order_group:
                    og = payment.order_group
                    og.order_status = OrderGroup.OrderStatus.PROCESSING
                    og.save()

                logger.info(f"Payment record updated for capture {capture_id}")
            else:
                logger.warning(f"No Payment record found for capture {capture_id}")
        except Exception as e:
            logger.exception(f"Error updating payment on capture: {e}")
    
    def _handle_payment_denied(self, webhook_event: WebhookEvent):
        """Handle payment denied event."""
        logger.info(f"Payment denied: {webhook_event.resource_id}")
        # Add your payment denial logic here
    
    def _handle_payment_refunded(self, webhook_event: WebhookEvent):
        """Handle payment refunded event."""
        logger.info(f"Payment refunded: {webhook_event.resource_id}")
        try:
            from order.models import Payment, Order
            data = webhook_event.raw_data or {}
            resource = data.get('resource', {})
            refund_id = resource.get('id') or webhook_event.resource_id

            # Try to find payment by payment_id or capture id
            payment = Payment.objects.filter(payment_id__iexact=refund_id).first()
            if not payment:
                # try to link via related resources
                related_id = resource.get('supplementary_data', {}).get('related_ids', {}).get('capture_id')
                if related_id:
                    payment = Payment.objects.filter(payment_id__iexact=related_id).first()

            if payment:
                payment.status = Payment.PAYMENT_PENDING
                payment.save()
                # Optionally mark order as cancelled/refunded
                if hasattr(payment, 'order') and payment.order:
                    order = payment.order
                    order.order_status = Order.OrderStatus.PENDING
                    order.save()
                logger.info(f"Payment {payment.id} marked pending/refunded")
            else:
                logger.warning(f"No Payment record found for refund {refund_id}")
        except Exception as e:
            logger.exception(f"Error updating payment on refund: {e}")
    
    def _handle_order_completed(self, webhook_event: WebhookEvent):
        """Handle order completed event."""
        logger.info(f"Order completed: {webhook_event.resource_id}")
        # Add your order completion logic here
    
    def _handle_subscription_activated(self, webhook_event: WebhookEvent):
        """Handle subscription activated event."""
        logger.info(f"Subscription activated: {webhook_event.resource_id}")
        # Add your subscription activation logic here
    
    def _handle_subscription_cancelled(self, webhook_event: WebhookEvent):
        """Handle subscription cancelled event."""
        logger.info(f"Subscription cancelled: {webhook_event.resource_id}")
        # Add your subscription cancellation logic here


# Django view decorators for easy integration
@csrf_exempt
@require_http_methods(["POST"])
def paypal_webhook_view(request):
    """Django view for handling PayPal webhooks."""
    handler = WebhookHandler()
    return handler.process_webhook(request)


@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    """Django REST Framework view for handling PayPal webhooks."""
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# Class-based view for more complex webhook handling
@method_decorator(csrf_exempt, name='dispatch')
class PayPalWebhookView(View):
    """Class-based view for PayPal webhook handling."""
    
    def post(self, request, *args, **kwargs):
        handler = WebhookHandler()
        return handler.process_webhook(request)
