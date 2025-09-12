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
    PayPalConfigSerializer, PayPalConfigUpdateSerializer,
    PayPalOrderSerializer
)
from .client import PayPalClient
from order.models import Payment, Order, OrderGroup
from product.models import Activitylog
from .webhooks import WebhookHandler
logger = logging.getLogger(__name__)

# -----------------------------
# PayPal Configuration ViewSet
# -----------------------------
class PayPalConfigViewSet(viewsets.ModelViewSet):
    """ViewSet for managing PayPal configurations."""

    queryset = PayPalConfig.objects.all()
    serializer_class = PayPalConfigSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['mode', 'is_active', 'name']

    search_fields = ['name']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']

    def get_serializer_class(self):
        if self.action == 'create':
            return PayPalConfigSerializer
        elif self.action in ['update', 'partial_update']:
            return PayPalConfigUpdateSerializer
        return PayPalConfigSerializer

    @action(detail=True, methods=['post'])
    def set_active(self, request, pk=None):
        from .credentials import CredentialManager
        config = self.get_object()
        credential_manager = CredentialManager()
        try:
            credential_manager.set_active_configuration(config.name)
            return Response({'status': 'Configuration activated'})
        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=False, methods=['get'])
    def active(self, request):
        from .credentials import CredentialManager
        credential_manager = CredentialManager()
        config = credential_manager.get_active_configuration()
        if config:
            serializer = self.get_serializer(config)
            return Response(serializer.data)
        return Response({'error': 'No active configuration found'}, status=status.HTTP_404_NOT_FOUND)

# -----------------------------
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
        try:
            client = PayPalClient()
            order_data = client.get_order(order_id)
            logger.info(f"PayPal order data: {order_data}")
            order_status = order_data.get("status")

            if order_status not in ["APPROVED", "COMPLETED"]:
                return Response({"detail": f"Order not approved. Status: {order_status}"}, status=status.HTTP_400_BAD_REQUEST)

            # Parse custom_id
            pu_list = order_data.get("purchase_units", [])
            custom_id_str = ""
            for pu in pu_list:
                if pu.get("custom_id"):
                    custom_id_str = pu["custom_id"]
                    break

            if not custom_id_str:
                return Response({"detail": f"No custom_id in PayPal order {order_id}"}, status=status.HTTP_400_BAD_REQUEST)

            parent_ids, child_ids = [], []
            for part in custom_id_str.split(","):
                part = part.strip()
                if "-" not in part:
                    continue
                prefix, id_str = part.split("-", 1)
                if not id_str.isdigit():
                    continue
                if prefix.upper() == "P":
                    parent_ids.append(int(id_str))
                elif prefix.upper() == "C":
                    child_ids.append(int(id_str))

            if not parent_ids and not child_ids:
                return Response({"detail": "No parent/child IDs found in PayPal order."}, status=status.HTTP_400_BAD_REQUEST)

            # Capture from PayPal
            capture_response = client.capture_payment(order_id)
            logger.info(f"PayPal capture response: {capture_response}")

            updated_ids = []
            last_capture_status = None
            last_capture_id = None

            for pu in capture_response.get("purchase_units", []):
                pu_custom_id = pu.get("custom_id")
                if not pu_custom_id:
                    continue

                prefix, id_str = pu_custom_id.split("-", 1)
                if not id_str.isdigit():
                    continue
                obj_id = int(id_str)

                # Sum all captures
                capture_id = None
                capture_status = None
                paid_amount = 0.0
                for cap in pu.get("payments", {}).get("captures", []):
                    capture_id = cap.get("id")
                    capture_status = cap.get("status")
                    last_capture_id = capture_id
                    last_capture_status = capture_status
                    amt = cap.get("amount", {})
                    try:
                        paid_amount += float(str(amt.get("value", 0)).replace(",", ""))
                    except (ValueError, TypeError):
                        continue

                # Parent (OrderGroup)
                if prefix.upper() == "P" and obj_id in parent_ids:
                    parent_payments = Payment.objects.filter(order_group__id=obj_id)
                    order_group = OrderGroup.objects.filter(id=obj_id).first()
                    for payment in parent_payments:
                        with transaction.atomic():
                            payment.status = self._map_status(capture_status)
                            payment.paid_amount = paid_amount
                            if capture_id:
                                payment.payment_id = capture_id
                            payment.save()
                            updated_ids.append(payment.id)
                    if order_group:
                        order_group.order_status = (
                            OrderGroup.OrderStatus.COMPLETED
                            if capture_status == "COMPLETED"
                            else OrderGroup.OrderStatus.PROCESSING
                        )
                        order_group.save()
                    Activitylog.objects.create(
                        action="PAYMENT_CAPTURE_COMPLETED",
                        description=json.dumps(pu)[:5000],
                        status="SUCCESS",
                        order_group=order_group,
                    )

                # Child (Order)
                elif prefix.upper() == "C" and obj_id in child_ids:
                    child_payment = Payment.objects.filter(order__id=obj_id).first()
                    if child_payment:
                        with transaction.atomic():
                            child_payment.status = self._map_status(capture_status)
                            child_payment.paid_amount = paid_amount
                            if capture_id:
                                child_payment.payment_id = capture_id
                            child_payment.save()
                            updated_ids.append(child_payment.id)
                        if child_payment.order:
                            child_payment.order.order_status = (
                                Order.OrderStatus.COMPLETED
                                if capture_status == "COMPLETED"
                                else Order.OrderStatus.PROCESSING
                            )
                            child_payment.order.save()
                        Activitylog.objects.create(
                            action="PAYMENT_CAPTURE_COMPLETED",
                            description=json.dumps(pu)[:5000],
                            status="SUCCESS",
                            order=child_payment.order,
                        )

      
            return Response(capture_response, status=status.HTTP_200_OK)

        except Exception as e:
            logger.exception("Error during PayPal capture")
            return Response({"detail": f"Internal server error: {str(e)}"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    # Map PayPal status to Payment status
    def _map_status(self, paypal_status: str):
        if paypal_status == "COMPLETED":
            return Payment.PAYMENT_COMPLETE
        elif paypal_status == "PENDING":
            return Payment.PAYMENT_PENDING
        elif paypal_status in ["DECLINED", "FAILED"]:
            return Payment.PAYMENT_FAILED
        return Payment.PAYMENT_PENDING

# -----------------------------
# Webhook view (no auth required)
# -----------------------------
@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook_drf_view(request):
    """Receive PayPal webhook and acknowledge immediately."""
    try:
        # Log receipt
        logger.info("Received PayPal webhook")
        print(request.body)
        # Optionally process asynchronously
        handler = WebhookHandler()
        handler.process_webhook_drf(request)  # you can do this in a background task if needed

        # Always respond 200 OK to PayPal
        return Response({'status': 'ok'}, status=200)
    
    except Exception as e:
        logger.exception("Error processing PayPal webhook")
        # Still return 200 to avoid retries
        return Response({'status': 'ok'}, status=200)