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
            object_id = None

            if obj:
                object_id = obj.id
            elif payload.get("custom_id"):
                # Handle PayPal IDs like "P-53" or "C-12"
                cid = payload["custom_id"]
                if "-" in cid:
                    _, num = cid.split("-", 1)
                    if num.isdigit():
                        object_id = int(num)
            elif payload.get("id"):
                # If ID is something like "P-53"
                raw_id = str(payload["id"])
                if raw_id.startswith(("P-", "C-")):
                    num = raw_id.split("-", 1)[1]
                    if num.isdigit():
                        object_id = int(num)

            Activitylog.objects.create(
                activity_log_type=action,
                message=json.dumps(payload)[:5000],
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
        Extracts scope ('P' for parent OrderGroup, 'C' for child Order, or None) and numeric id
        from different PayPal webhook structures (custom_id, invoice_id, related_ids).
        Returns a tuple: (scope, numeric_id_or_None, raw_value_or_None)
        """
        raw = None
        scope = None
        num_id = None

        # Case 1: CHECKOUT.ORDER.* events
        if "purchase_units" in resource:
            for pu_item in resource.get("purchase_units", []):
                raw = pu_item.get("custom_id") or pu_item.get("invoice_id") or raw
                if raw:
                    break

        # Case 2: CAPTURE events (custom_id or invoice_id)
        if not raw:
            raw = (
                resource.get("custom_id")
                or resource.get("invoice_id")
                or (resource.get("supplementary_data", {})
                    .get("related_ids", {})
                    .get("order_id"))
            )

        # Parse scope/id when raw like 'P-53' or 'C-12'
        if isinstance(raw, str) and "-" in raw:
            pref, tail = raw.split("-", 1)
            if tail.isdigit():
                scope = pref.upper()
                num_id = int(tail)
        elif isinstance(raw, str) and raw.isdigit():
            scope = "C"  # default assume child order if no prefix
            num_id = int(raw)

        return scope, num_id, raw

    def _process_event(self, webhook_data: Dict[str, Any], request=None):
        """Process webhook event based on type."""
        try:
            event_type = webhook_data.get("event_type")
            resource = webhook_data.get("resource", {})
            scope, numeric_id, raw_value = self._extract_order_id(resource)

            logger.info(f"Processing event: {event_type}, scope={scope}, id={numeric_id}, raw={raw_value}")

            if event_type in ["CHECKOUT.ORDER.APPROVED", "CHECKOUT.ORDER.COMPLETED"]:
                self._handle_order_completed(scope, numeric_id, resource, request)
            elif event_type == "PAYMENT.CAPTURE.COMPLETED":
                self._handle_payment_completed(scope, numeric_id, resource, request)
            elif event_type == "PAYMENT.CAPTURE.PENDING":
                self._handle_payment_pending(scope, numeric_id, resource, request)
            else:
                logger.info(f"Unhandled event type: {event_type} with scope={scope} id={numeric_id}")
        except Exception as e:
            self._log_activity("PROCESS_EVENT_ERROR", {"error": str(e)})
            return Response(status=200)

    def _handle_order_completed(self, scope: str, numeric_id: int, resource: Dict[str, Any], request=None):
        if scope == "C" and numeric_id:
            order = Order.objects.filter(id=numeric_id).first()
            if order:
                order.order_status = Order.OrderStatus.PENDING
                order.save()
                self._log_activity("ORDER_COMPLETED", resource, obj=order)
                logger.info(f"Order approved, awaiting capture: {numeric_id}")
                return
        elif scope == "P" and numeric_id:
            og = OrderGroup.objects.filter(id=numeric_id).first()
            if og:
                # Keep parent in pending until child captures complete
                og.order_status = OrderGroup.OrderStatus.PENDING
                og.save()

                # Log for parent
                self._log_activity("ORDER_APPROVED_PARENT", resource, obj=og)
                logger.info(f"Parent order approved, awaiting capture: {numeric_id}")

                # 🔹 Also log for all child orders
                child_orders = getattr(og, "order_set", None)
                if child_orders:
                    for child in child_orders.all():
                        self._log_activity("ORDER_COMPLETED_CHILD", resource, obj=child)
                        logger.info(f"Child order approved, awaiting capture: {child.id}")

                return
        logger.warning(f"Order/OrderGroup not found for checkout completed: scope={scope} id={numeric_id}")
        self._log_activity("ORDER_NOT_FOUND", resource)

    def _handle_payment_completed(self, scope: str, numeric_id: int, resource: Dict[str, Any], request=None):
        payment = None
        if scope == "C" and numeric_id:
            payment = Payment.objects.filter(order__id=numeric_id).first()
        elif scope == "P" and numeric_id:
            payment = Payment.objects.filter(order_group__id=numeric_id).first()

        # fallback: try matching by PayPal capture id
        if not payment:
            capture_id = resource.get("id")
            payment = Payment.objects.filter(payment_id=capture_id).first()

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

            obj = None
            if payment.order:
                payment.order.order_status = Order.OrderStatus.PROCESSING
                payment.order.save()
                obj = payment.order
            elif hasattr(payment, "order_group") and payment.order_group:
                payment.order_group.order_status = OrderGroup.OrderStatus.PROCESSING
                payment.order_group.save()
                obj = payment.order_group

            self._log_activity("PAYMENT_CAPTURE_COMPLETED", resource, obj=obj)
            logger.info(f"Payment completed for scope={scope} id={numeric_id}")
        else:
            logger.warning(f"No Payment record found for completed capture: scope={scope} id={numeric_id}")
            self._log_activity("PAYMENT_NOT_FOUND", resource)

    def _handle_payment_pending(self, scope: str, numeric_id: int, resource: Dict[str, Any], request=None):
        payment = None
        if scope == "C" and numeric_id:
            payment = Payment.objects.filter(order__id=numeric_id).first()
        elif scope == "P" and numeric_id:
            payment = Payment.objects.filter(order_group__id=numeric_id).first()

        # fallback: try matching by PayPal capture id
        if not payment:
            capture_id = resource.get("id")
            payment = Payment.objects.filter(payment_id=capture_id).first()

        if payment:
            payment.status = Payment.PAYMENT_PENDING
            payment.save()

            obj = None
            if payment.order:
                payment.order.order_status = Order.OrderStatus.PENDING
                payment.order.save()
                obj = payment.order
            elif hasattr(payment, "order_group") and payment.order_group:
                payment.order_group.order_status = OrderGroup.OrderStatus.PENDING
                payment.order_group.save()
                obj = payment.order_group

            self._log_activity("PAYMENT_PENDING", resource, obj=obj)
            logger.info(f"Payment pending for scope={scope} id={numeric_id}")
        else:
            logger.warning(f"No Payment record found for pending capture: scope={scope} id={numeric_id}")
            self._log_activity("PAYMENT_NOT_FOUND", resource)


# Django function-based view
@csrf_exempt
@require_http_methods(["POST"])
def paypal_webhook_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# Django REST Framework view
@api_view(["POST"])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)


# Class-based view for more complex webhook handling
@method_decorator(csrf_exempt, name="dispatch")
class PayPalWebhookView(View):
    """Class-based view for PayPal webhook handling."""

    def post(self, request, *args, **kwargs):
        handler = WebhookHandler()
        return handler.process_webhook_drf(request)
