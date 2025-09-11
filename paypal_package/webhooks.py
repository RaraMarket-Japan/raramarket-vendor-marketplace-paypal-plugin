import logging
import json
from typing import Dict, Any
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.views import View
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework import status
from order.models import Payment, Order, OrderGroup
from product.models import Activitylog
from .client import PayPalClient  # your PayPal client

logger = logging.getLogger(__name__)

class WebhookHandler:
    """Handles incoming PayPal webhook events."""

    def __init__(self, client=None):
        self.client = client or PayPalClient()

    def _log_activity(self, action: str, payload: dict, status: str = "INFO",
                    order: Order = None, order_group: OrderGroup = None):
        """Insert record into Activitylog for debugging/audit."""
        try:
            Activitylog.objects.create(
                action=action,
                description=json.dumps(payload)[:5000],
                status=status,
                order=order if order else None,
                order_group=order_group if order_group else None
            )
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")

    def process_webhook_drf(self, request) -> Response:
        """Process incoming webhook request (Django REST Framework)."""
        try:
            body = request.body.decode('utf-8')
            webhook_data = json.loads(body)
            self._process_event(webhook_data)
            return Response({'status': 'success'}, status=status.HTTP_200_OK)
        except json.JSONDecodeError:
            self._log_activity("WEBHOOK_INVALID_JSON", {}, status="ERROR")
            return Response({'error': 'Invalid JSON'}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            self._log_activity("WEBHOOK_ERROR", {"error": str(e)}, status="ERROR")
            return Response({'error': 'Internal server error'}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _process_event(self, webhook_data: Dict[str, Any]):
        """Process webhook event based on type."""
        try:
            event_type = webhook_data.get("event_type")
            resource = webhook_data.get("resource", {})
            order_id = None

            # Extract order_id from purchase units if available
            for pu_item in resource.get("purchase_units", []):
                order_id = pu_item.get("custom_id") or pu_item.get("invoice_id") or order_id

            if event_type == "CHECKOUT.ORDER.COMPLETED":
                self._handle_order_completed(order_id, resource)

            elif event_type == "PAYMENT.CAPTURE.COMPLETED":
                self._handle_payment_completed(order_id, resource)

            elif event_type == "PAYMENT.CAPTURE.PENDING":
                self._handle_payment_pending(order_id, resource)

            else:
                logger.info(f"Unhandled event type: {event_type}")
        except Exception as e:
            self._log_activity("PROCESS_EVENT_ERROR", {"error": str(e)}, status="ERROR")
            logger.exception(f"Error processing webhook: {e}")

    def _handle_order_completed(self, order_id: str, resource: Dict[str, Any]):
        """Handle order completed event (approved by buyer)."""
        order = Order.objects.filter(id=order_id).first()
        if order:
            order.order_status = Order.OrderStatus.PENDING  # awaiting capture
            order.save()
            self._log_activity("ORDER_COMPLETED", resource, status="INFO", order=order)
            logger.info(f"Order approved, awaiting capture: {order_id}")
        else:
            logger.warning(f"Order not found for checkout completed: {order_id}")
            self._log_activity("ORDER_NOT_FOUND", resource, status="WARNING")

    def _handle_payment_completed(self, order_id: str, resource: Dict[str, Any]):
        """Handle completed payment capture."""
        payment = Payment.objects.filter(order__id=order_id).first()
        if payment:
            payment.status = Payment.PAYMENT_COMPLETE
            paid_amount = resource.get("amount", {}).get("value")
            if paid_amount:
                try:
                    payment.paid_amount = float(paid_amount)
                except Exception:
                    pass
            payment.payment_id = resource.get("id") or payment.payment_id
            payment.save()

            if payment.order:
                payment.order.order_status = Order.OrderStatus.PROCESSING
                payment.order.save()
            elif payment.order_group:
                payment.order_group.order_status = OrderGroup.OrderStatus.PROCESSING
                payment.order_group.save()

            self._log_activity("PAYMENT_CAPTURE_COMPLETED", resource, status="SUCCESS", order=payment.order)
            logger.info(f"Payment completed for order: {order_id}")
        else:
            logger.warning(f"No Payment record found for order: {order_id}")
            self._log_activity("PAYMENT_NOT_FOUND", resource, status="WARNING")

    def _handle_payment_pending(self, order_id: str, resource: Dict[str, Any]):
        """Handle pending payment capture."""
        payment = Payment.objects.filter(order__id=order_id).first()
        if payment:
            payment.status = Payment.PAYMENT_PENDING
            payment.save()
            if payment.order:
                payment.order.order_status = Order.OrderStatus.PENDING
                payment.order.save()
            elif payment.order_group:
                payment.order_group.order_status = OrderGroup.OrderStatus.PENDING
                payment.order_group.save()
            self._log_activity("PAYMENT_PENDING", resource, status="PENDING", order=payment.order)
            logger.info(f"Payment pending for order: {order_id}")
        else:
            logger.warning(f"No Payment record found for pending capture: {order_id}")
            self._log_activity("PAYMENT_NOT_FOUND", resource, status="WARNING")



# Django view decorators for easy integration
@csrf_exempt
@require_http_methods(["POST"])
def paypal_webhook_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# Class-based view for more complex webhook handling
@method_decorator(csrf_exempt, name='dispatch')
class PayPalWebhookView(View):
    """Class-based view for PayPal webhook handling."""
    def post(self, request, *args, **kwargs):
        handler = WebhookHandler()
        return handler.process_webhook_drf(request)
