"""
Django REST Framework views for PayPal package.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import PayPalConfig
from .serializers import (
    PayPalConfigSerializer, PayPalConfigUpdateSerializer,
    PayPalOrderSerializer, PayPalCaptureSerializer, PayPalRefundSerializer
)
from .client import PayPalClient
from .webhooks import  paypal_webhook_drf_view
import logging

from rest_framework.response import Response
from rest_framework import status
from order.models import Payment, Order, OrderGroup
from django.db import transaction
logger = logging.getLogger(__name__)
from product.models import Activitylog
from django.http import HttpResponse
from django.views.decorators.csrf import csrf_exempt
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
        """Use different serializers for different actions."""
        if self.action in ['create']:
            return PayPalConfigSerializer
        elif self.action in ['update', 'partial_update']:
            return PayPalConfigUpdateSerializer
        return PayPalConfigSerializer
    
    @action(detail=True, methods=['post'])
    def set_active(self, request, pk=None):
        """Set a configuration as active."""
        from .credentials import CredentialManager
        
        config = self.get_object()
        credential_manager = CredentialManager()
        
        try:
            credential_manager.set_active_configuration(config.name)
            return Response({'status': 'Configuration activated'})
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    
    @action(detail=False, methods=['get'])
    def active(self, request):
        """Get the active configuration."""
        from .credentials import CredentialManager
        
        credential_manager = CredentialManager()
        config = credential_manager.get_active_configuration()
        
        if config:
            serializer = self.get_serializer(config)
            return Response(serializer.data)
        else:
            return Response(
                {'error': 'No active configuration found'}, 
                status=status.HTTP_404_NOT_FOUND
            )






class PayPalPaymentViewSet(viewsets.ViewSet):
    """ViewSet for PayPal payment operations."""
    
    permission_classes = [IsAuthenticated]
    
    def create_order(self, request):
        """Create a PayPal order."""
        serializer = PayPalOrderSerializer(data=request.data)
        if serializer.is_valid():
            try:
                client = PayPalClient()
                order_data = serializer.validated_data
                response = client.create_order(order_data)
                return Response(response, status=status.HTTP_201_CREATED)
            except Exception as e:
                return Response(
                    {'error': str(e)}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get_order(self, request, order_id):
        """Get order details."""
        try:
            client = PayPalClient()
            response = client.get_order(order_id)
            return Response(response)
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )
    




    def capture_payment(self, request, order_id):
        """Capture payment for an order."""
        try:
            serializer = PayPalCaptureSerializer(data=request.data)
            if not serializer.is_valid():
                logger.warning(f"Invalid serializer data: {serializer.errors}")
                # return "OK" anyway
                return HttpResponse("OK", status=200)

            client = PayPalClient()

            # 1️⃣ Check order status first
            order_data = client.get_order(order_id)

            print("order_data", order_data)
            logger.info(f"PayPal order data: {order_data}")
            order_status = order_data.get("status")

            if order_status not in ["APPROVED", "COMPLETED"]:
                logger.warning(f"Order not approved. Current status: {order_status}")
                return HttpResponse("OK", status=200)

            # 2️⃣ Capture the payment
            response = client.capture_payment(order_id)
            logger.info(f"PayPal capture response: {response}")

            # 3️⃣ Parse capture info
            capture_id = None
            capture_status = None
            paid_amount = None
            internal_order_id = None

            if isinstance(response, dict):
                pu_list = response.get("purchase_units", [])
                if pu_list:
                    first = pu_list[0]
                    internal_order_id = first.get("custom_id")
                    payments = first.get("payments", {})
                    captures = payments.get("captures", [])

                    if captures:
                        cap = captures[0]
                        capture_id = cap.get("id")
                        capture_status = cap.get("status")
                        amt = cap.get("amount") or {}
                        if isinstance(amt, dict):
                            paid_amount = amt.get("value")
                        internal_order_id = cap.get("custom_id") or internal_order_id

                # fallback capture_id
                if not capture_id:
                    capture_id = response.get("id")

            # 4️⃣ Fetch Payment record
            payment = None
            if internal_order_id and str(internal_order_id).isdigit():
                payment = Payment.objects.filter(order__id=int(internal_order_id)).first()
            if not payment:
                payment = Payment.objects.filter(paypal_order_id=order_id).first()
            if not payment:
                logger.warning(f"No Payment found for internal_order_id={internal_order_id}, paypal_order_id={order_id}")
                return HttpResponse("OK", status=200)

            # 5️⃣ Update payment info
            with transaction.atomic():
                if capture_status == "COMPLETED":
                    payment.status = Payment.PAYMENT_COMPLETE
                elif capture_status in ["PENDING", "DECLINED"]:
                    payment.status = Payment.PAYMENT_PENDING

                if paid_amount:
                    try:
                        payment.paid_amount = float(paid_amount)
                    except Exception:
                        logger.exception(f"Failed to parse paid_amount: {paid_amount}")

                if capture_id:
                    payment.payment_id = capture_id

                payment.save()
                logger.info(f"Updated Payment: {payment}")

                # 6️⃣ Update order or order group status
                target_obj = getattr(payment, "order", None) or getattr(payment, "order_group", None)
                if target_obj:
                    new_status = (
                        Order.OrderStatus.COMPLETED if capture_status == "COMPLETED" else Order.OrderStatus.PROCESSING
                    ) if isinstance(target_obj, Order) else (
                        OrderGroup.OrderStatus.COMPLETED if capture_status == "COMPLETED" else OrderGroup.OrderStatus.PROCESSING
                    )
                    target_obj.order_status = new_status
                    target_obj.save()
                    logger.info(f"Updated target order/order group: {target_obj}")

        except Exception as e:
            logger.exception("Error during PayPal capture")

        # 🔹 Always return plain OK to PayPal
        return HttpResponse("OK", status=200)

 

    
    def refund_payment(self, request, capture_id):
        """Refund a payment."""
        serializer = PayPalRefundSerializer(data=request.data)
        if serializer.is_valid():
            try:
                client = PayPalClient()
                refund_data = serializer.validated_data
                response = client.refund_payment(capture_id, refund_data)
                return Response(response)
            except Exception as e:
                return Response(
                    {'error': str(e)}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
    def get_payment_details(self, request, payment_id):
        """Get payment details."""
        try:
            client = PayPalClient()
            response = client.get_payment_details(payment_id)
            return Response(response)
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
            )


# Webhook view (no authentication required)
@csrf_exempt
def paypal_webhook_view(request):

    return paypal_webhook_drf_view(request)
