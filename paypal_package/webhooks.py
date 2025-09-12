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
from .client import PayPalClient
from django.contrib.contenttypes.models import ContentType

logger = logging.getLogger(__name__)


class WebhookHandler:
    """Handles incoming PayPal webhook events."""

    def __init__(self, client=None):
        self.client = client or PayPalClient()

    def _log_activity(self, action: str, payload: dict, obj=None, ip_address=None):
        """Insert record into Activitylog for debugging/audit."""
        try:
            content_type = ContentType.objects.get_for_model(obj) if obj else None
            object_id = getattr(obj, "id", None)

            if not object_id and payload.get("custom_id"):
                cid = payload["custom_id"]
                if "-" in cid:
                    _, num = cid.split("-", 1)
                    if num.isdigit():
                        object_id = int(num)
            elif not object_id and payload.get("id"):
                raw_id = str(payload["id"])
                if "-" in raw_id:
                    num = raw_id.split("-", 1)[1]
                    if num.isdigit():
                        object_id = int(num)

            Activitylog.objects.create(
                activity_log_type=action,
                message=json.dumps(payload),
                content_type=content_type,
                object_id=object_id,
                ip_address=ip_address
            )
        except Exception as e:
            logger.error(f"Failed to log activity: {e}")

    def process_webhook_drf(self, request) -> Response:
        """Process incoming webhook request (Django REST Framework)."""
        try:
            body = request.body.decode("utf-8")
            webhook_data = json.loads(body)
            self._process_event(webhook_data, request)
            return Response({"status": "success"}, status=status.HTTP_200_OK)
        except json.JSONDecodeError:
            self._log_activity("WEBHOOK_INVALID_JSON", {})
            return Response({"error": "Invalid JSON"}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as e:
            self._log_activity("WEBHOOK_ERROR", {"error": str(e)})
            return Response({"error": "Internal server error"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    def _extract_order_id(self, resource: dict):
        """
        Extracts scope ('OG' for OrderGroup, 'G' for Order) and numeric id
        from different PayPal webhook structures.
        Returns: (scope, numeric_id, raw)
        """
        raw = None
        scope = None
        num_id = None

        # Case 1: purchase_units
        if "purchase_units" in resource:
            for pu_item in resource.get("purchase_units", []):
                raw = pu_item.get("custom_id") or pu_item.get("invoice_id") or raw
                if raw:
                    break

        # Case 2: capture
        if not raw:
            raw = (
                resource.get("custom_id")
                or resource.get("invoice_id")
                or (resource.get("supplementary_data", {})
                    .get("related_ids", {})
                    .get("order_id"))
            )

        # Parse
        if isinstance(raw, str) and "-" in raw:
            pref, tail = raw.split("-", 1)
            if tail.isdigit():
                scope = pref.upper()   # "OG" or "G"
                num_id = int(tail)
        elif isinstance(raw, str) and raw.isdigit():
            scope = "G"  # default single order
            num_id = int(raw)

        return scope, num_id, raw

    def _process_event(self, webhook_data: Dict[str, Any], request=None):
        """Route event based on type."""
        try:
            event_type = webhook_data.get("event_type")
            resource = webhook_data.get("resource", {})
            scope, numeric_id, raw_value = self._extract_order_id(resource)

            logger.info(f"Processing event: {event_type}, scope={scope}, id={numeric_id}, raw={raw_value}")

            if event_type in ["CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED"]:
                self._handle_order_completed(scope, numeric_id, resource)
            elif event_type == "PAYMENT.CAPTURE.COMPLETED":
                self._handle_payment_completed(scope, numeric_id, resource)
            elif event_type == "PAYMENT.CAPTURE.PENDING":
                self._handle_payment_pending(scope, numeric_id, resource)
            else:
                logger.info(f"Unhandled event type: {event_type} with scope={scope} id={numeric_id}")
        except Exception as e:
            self._log_activity("PROCESS_EVENT_ERROR", {"error": str(e)})

    def _handle_order_completed(self, scope: str, numeric_id: int, resource: Dict[str, Any]):
        if scope == "G" and numeric_id:
            order = Order.objects.filter(id=numeric_id).first()
            if order:
                order.order_status = Order.OrderStatus.PENDING
                order.save()
                self._log_activity("ORDER_COMPLETED", resource, obj=order)
                logger.info(f"Order approved, awaiting capture: {numeric_id}")
                return
        elif scope == "OG" and numeric_id:
            og = OrderGroup.objects.filter(id=numeric_id).first()
            if og:
                og.order_status = OrderGroup.OrderStatus.PENDING
                og.save()

                self._log_activity("ORDER_APPROVED_PARENT", resource, obj=og)
                logger.info(f"Parent order approved, awaiting capture: {numeric_id}")

                # also log for children
                for child in og.orders_group.all():  # ✅ orders_group is correct
                    self._log_activity("ORDER_COMPLETED_CHILD", resource, obj=child)
                return
        self._log_activity("ORDER_NOT_FOUND", resource)

    def _handle_payment_completed(self, scope: str, numeric_id: int, resource: Dict[str, Any]):
        """
        Handles PayPal PAYMENT.CAPTURE.COMPLETED webhook.
        Updates Payment and related Order/OrderGroup statuses.
        """
        payment = None

        # Find payment by scope and ID
        if scope == "G" and numeric_id:
            payment = Payment.objects.filter(order__id=numeric_id).first()
        elif scope == "OG" and numeric_id:
            payment = Payment.objects.filter(order_group__id=numeric_id).first()

        # Fallback: find payment by capture ID
        if not payment:
            capture_id = resource.get("id")
            if capture_id:
                payment = Payment.objects.filter(payment_id=capture_id).first()

        if payment:
            # Update payment fields
            payment.status = Payment.PAYMENT_COMPLETE
            amt = resource.get("amount", {}).get("value")
            if amt:
                try:
                    payment.paid_amount = float(amt)
                except (ValueError, TypeError):
                    self._log_activity("PAYMENT_AMOUNT_INVALID", resource, obj=payment)
            
            payment.payment_id = resource.get("id") or payment.payment_id
            payment.save()

            # Update related order/order group status
            related_obj = payment.order or payment.order_group
            if related_obj:
                # Set status to PROCESSING or COMPLETED based on your business logic
                if hasattr(related_obj, "order_status"):
                    related_obj.order_status = "PROCESSING"
                related_obj.save()

            # Log successful payment capture
            self._log_activity("PAYMENT_CAPTURE_COMPLETED", resource, obj=related_obj)
        else:
            # Log when payment is not found
            self._log_activity("PAYMENT_NOT_FOUND", resource)

    def _handle_payment_pending(self, scope: str, numeric_id: int, resource: Dict[str, Any]):
        payment = None
        if scope == "G" and numeric_id:
            payment = Payment.objects.filter(order__id=numeric_id).first()
        elif scope == "OG" and numeric_id:
            payment = Payment.objects.filter(order_group__id=numeric_id).first()

        if not payment:
            capture_id = resource.get("id")
            payment = Payment.objects.filter(payment_id=capture_id).first()

        if payment:
            payment.status = Payment.PAYMENT_PENDING
            payment.save()

            obj = payment.order or payment.order_group
            if obj:
                obj.order_status = obj.OrderStatus.PENDING
                obj.save()

            self._log_activity("PAYMENT_PENDING", resource, obj=obj)
        else:
            self._log_activity("PAYMENT_NOT_FOUND", resource)


# Django function-based view
@csrf_exempt
@require_http_methods(["POST"])
def paypal_webhook_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# DRF view
@api_view(["POST"])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# Class-based view
@method_decorator(csrf_exempt, name="dispatch")
class PayPalWebhookView(View):
    """Class-based view for PayPal webhook handling."""

    def post(self, request, *args, **kwargs):
        handler = WebhookHandler()
        return handler.process_webhook_drf(request)
