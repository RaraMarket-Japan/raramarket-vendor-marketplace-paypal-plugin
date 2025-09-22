"""
Django REST Framework views for PayPal package.
"""

import logging
import json
from rest_framework import viewsets, status
from rest_framework.decorators import action, api_view, permission_classes
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from django.db import transaction
from django.views.decorators.csrf import csrf_exempt
from django.db.models import Q

from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter

from .models import PayPalConfig
from .serializers import (
    PayPalConfigSerializer,
    PayPalOrderSerializer
)
from .client import PayPalClient
from order.models import Payment, Order, OrderGroup
from product.models import Activitylog
from .webhooks import WebhookHandler

# -----------------------------
# PayPal Configuration ViewSet
# -----------------------------
class PayPalConfigViewSet(viewsets.ModelViewSet):
    queryset = PayPalConfig.objects.all()
    serializer_class = PayPalConfigSerializer
    permission_classes = [IsAuthenticated]



# PayPal Payment ViewSet
# -----------------------------
class PayPalPaymentViewSet(viewsets.ViewSet):
    """ViewSet for PayPal payment operations."""

    permission_classes = [IsAuthenticated]

    # ---- Create Order ----
    def create_order(self, request):
        serializer = PayPalOrderSerializer(data=request.data)
        if serializer.is_valid():
            try:
                client = PayPalClient()
                order_data = serializer.validated_data
                response = client.create_order(order_data)
                return Response(response, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    # ---- Get Order Details ----
    def get_order(self, request, order_id):
        try:
            client = PayPalClient()
            response = client.get_order(order_id)
            return Response(response)
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    # ---- Capture Payment ----




    def capture_payment(self, request, order_id):
        """
        Capture a PayPal payment for a single order or order group.
        Handles both CAPTURE and AUTHORIZE intents.
        Updates payment and order statuses based on capture status.
        """
        try:
            client = PayPalClient()
            order_data = client.get_order(order_id)

            order_status = order_data.get("status")
            intent = order_data.get("intent")

            if order_status not in ["APPROVED", "COMPLETED", "PENDING"]:
                return Response(
                    {"detail": f"Order not in a capturable state. Status: {order_status}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Get first purchase unit
            pu = order_data.get("purchase_units", [{}])[0]
            custom_id = pu.get("custom_id")
            if not custom_id:
                return Response(
                    {"detail": f"No custom_id in PayPal order {order_id}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Parse custom_id
            custom_id_upper = custom_id.upper()
            if custom_id_upper.startswith("OG") and custom_id_upper[2:].isdigit():
                prefix = "OG"
                obj_id = int(custom_id_upper[2:])
            elif custom_id_upper.startswith("G") and custom_id_upper[1:].isdigit():
                prefix = "G"
                obj_id = int(custom_id_upper[1:])
            else:
                return Response(
                    {"detail": f"Invalid custom_id format in PayPal order {order_id}: {custom_id}"},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            # Capture the payment depending on intent
            capture_response = {}
            if intent.upper() == "AUTHORIZE":
                authorize_resp = client.authorize_order(order_id)
                auths = authorize_resp.get("purchase_units", [{}])[0].get("payments", {}).get("authorizations", [])
                if not auths:
                    return Response(
                        {"detail": f"No authorizations found for PayPal order {order_id}"},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                auth_id = auths[0]["id"]
                capture_response = client.capture_authorization(auth_id)
            else:  # CAPTURE intent
                capture_response = client.capture_payment(order_id)

            # Extract captures
            captures = pu.get("payments", {}).get("captures", [])
            paid_amount = 0.0
            capture_id = None
            capture_status = "PENDING"

            for cap in captures:
                capture_id = cap.get("id")
                capture_status = cap.get("status", "PENDING").upper()
                amt = cap.get("amount", {})
                try:
                    paid_amount += float(str(amt.get("value", 0)).replace(",", ""))
                except (ValueError, TypeError):
                    continue

            # Determine local payment/order status
            if capture_status == "COMPLETED":
                payment_status = Payment.PAYMENT_COMPLETE  # Paid
                order_status_value = Order.OrderStatus.PROCESSING
            else:  # Pending or other
                payment_status = Payment.PAYMENT_PENDING
                order_status_value = Order.OrderStatus.PENDING

            # Update database
            if prefix.upper() == "OG":
                order_group = OrderGroup.objects.filter(id=obj_id).first()
                if order_group:
                    parent_payments = Payment.objects.filter(order_group=order_group)
                    for payment in parent_payments:
                        with transaction.atomic():
                            payment.status = payment_status
                            payment.paid_amount = paid_amount
                            if capture_id:
                                payment.payment_id = capture_id
                            payment.save()

                    order_group.order_status = order_status_value
                    order_group.save()

                    # Activity log for child orders
                    child_orders = Order.objects.filter(parent_order=order_group)
                    for order in child_orders:
                        Activitylog.objects.create(
                            activity_log_type="PAYMENT_CAPTURE_INITIATED",
                            message=json.dumps(pu)[:5000],
                            content_object=order
                        )

            elif prefix.upper() == "G":  # Single Order
                order = Order.objects.filter(id=obj_id).first()
                if order:
                    payment = Payment.objects.filter(order=order).first()
                    if payment:
                        with transaction.atomic():
                            payment.status = payment_status
                            payment.paid_amount = paid_amount
                            if capture_id:
                                payment.payment_id = capture_id
                            payment.save()

                    order.order_status = order_status_value
                    order.save()

                    # Activity log
                    Activitylog.objects.create(
                        activity_log_type="PAYMENT_CAPTURE_COMPLETED",
                        message=json.dumps(payload),
                        content_object=order
                    )

            return Response(capture_response, status=status.HTTP_200_OK)

        except Exception as e:
            return Response(
                {"detail": f"Internal server error: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


    def _map_status(self, paypal_status: str):
        """Map PayPal status to local Payment status."""
        status_map = {
            "COMPLETED": Payment.PAYMENT_COMPLETE,
            "APPROVED": Payment.PAYMENT_PENDING,
            "PENDING": Payment.PAYMENT_PENDING,
            "REVIEW": Payment.PAYMENT_PENDING,
            "DECLINED": Payment.PAYMENT_FAILED,
            "FAILED": Payment.PAYMENT_FAILED,
        }
        return status_map.get(paypal_status.upper(), Payment.PAYMENT_PENDING)


# -----------------------------
# Webhook view (no auth required)
# -----------------------------
@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    """Receive PayPal webhook and acknowledge immediately."""
    try:


        handler = WebhookHandler()
        handler.process_webhook_drf(request) 

        # Always respond 200 OK to PayPal
        return Response({'status': 'ok'}, status=200)
    
    except Exception as e:
  
        return Response({'status': 'ok'}, status=200)