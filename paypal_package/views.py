"""
Django REST Framework views for PayPal package.
"""

from rest_framework import viewsets, status, permissions
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, AllowAny
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework.filters import SearchFilter, OrderingFilter
from .models import PayPalConfig, WebhookEvent, WebhookEndpoint
from .serializers import (
    PayPalConfigSerializer, PayPalConfigUpdateSerializer,
    WebhookEventSerializer, WebhookEventDetailSerializer,
    WebhookEndpointSerializer, WebhookEndpointCreateSerializer,
    PayPalOrderSerializer, PayPalCaptureSerializer, PayPalRefundSerializer
)
from .client import PayPalClient
from .webhooks import WebhookManager, paypal_webhook_drf_view
import logging

from rest_framework.response import Response
from rest_framework import status
from order.models import Payment, Order, OrderGroup
from django.db import transaction
logger = logging.getLogger(__name__)


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


class WebhookEventViewSet(viewsets.ReadOnlyModelViewSet):
    """ViewSet for viewing webhook events."""
    
    queryset = WebhookEvent.objects.all()
    serializer_class = WebhookEventSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['event_type', 'processed', 'resource_type']
    search_fields = ['event_id', 'resource_id', 'summary']
    ordering_fields = ['created_at', 'processed_at', 'event_type']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Use detailed serializer for retrieve action."""
        if self.action == 'retrieve':
            return WebhookEventDetailSerializer
        return WebhookEventSerializer
    
    @action(detail=True, methods=['post'])
    def mark_processed(self, request, pk=None):
        """Mark an event as processed."""
        event = self.get_object()
        event.mark_as_processed()
        return Response({'status': 'Event marked as processed'})
    
    @action(detail=False, methods=['get'])
    def unprocessed(self, request):
        """Get unprocessed events."""
        events = self.get_queryset().filter(processed=False)
        page = self.paginate_queryset(events)
        if page is not None:
            serializer = self.get_serializer(page, many=True)
            return self.get_paginated_response(serializer.data)
        
        serializer = self.get_serializer(events, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        """Get webhook event statistics."""
        total_events = WebhookEvent.objects.count()
        processed_events = WebhookEvent.objects.filter(processed=True).count()
        unprocessed_events = total_events - processed_events
        
        event_types = WebhookEvent.objects.values_list('event_type', flat=True).distinct()
        event_type_counts = {}
        for event_type in event_types:
            count = WebhookEvent.objects.filter(event_type=event_type).count()
            event_type_counts[event_type] = count
        
        return Response({
            'total_events': total_events,
            'processed_events': processed_events,
            'unprocessed_events': unprocessed_events,
            'event_type_counts': event_type_counts
        })


class WebhookEndpointViewSet(viewsets.ModelViewSet):
    """ViewSet for managing webhook endpoints."""
    
    queryset = WebhookEndpoint.objects.all()
    serializer_class = WebhookEndpointSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend, SearchFilter, OrderingFilter]
    filterset_fields = ['is_active']
    search_fields = ['name', 'url']
    ordering_fields = ['name', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def get_serializer_class(self):
        """Use different serializers for different actions."""
        if self.action == 'create':
            return WebhookEndpointCreateSerializer
        return WebhookEndpointSerializer
    
    def destroy(self, request, *args, **kwargs):
        """Delete webhook endpoint and remove from PayPal."""
        instance = self.get_object()
        
        if instance.webhook_id:
            try:
                webhook_manager = WebhookManager()
                webhook_manager.delete_webhook(instance.webhook_id)
            except Exception as e:
                return Response(
                    {'error': f'Failed to delete webhook from PayPal: {str(e)}'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        
        return super().destroy(request, *args, **kwargs)
    
    @action(detail=True, methods=['post'])
    def update_events(self, request, pk=None):
        """Update webhook events."""
        endpoint = self.get_object()
        events = request.data.get('events', [])
        
        if not events:
            return Response(
                {'error': 'Events list is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        try:
            webhook_manager = WebhookManager()
            success = webhook_manager.update_webhook_events(endpoint.webhook_id, events)
            
            if success:
                return Response({'status': 'Events updated'})
            else:
                return Response(
                    {'error': 'Failed to update events'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
        except Exception as e:
            return Response(
                {'error': str(e)}, 
                status=status.HTTP_400_BAD_REQUEST
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
        serializer = PayPalCaptureSerializer(data=request.data)
        if serializer.is_valid():
            try:
                client = PayPalClient()
                capture_data = serializer.validated_data
                response = client.capture_payment(order_id)
                
                print("PayPal response:", response)

                try:
                    with transaction.atomic():
                        capture_id = None
                        capture_status = None
                        paid_amount = None
                        internal_order_id = None

                        # Extract info from PayPal response
                        pu = response.get("purchase_units") if isinstance(response, dict) else None
                        if pu and isinstance(pu, list) and len(pu) > 0:
                            first = pu[0]
                            internal_order_id = first.get("custom_id") or internal_order_id
                            payments = first.get("payments") or {}
                            captures = payments.get("captures") if isinstance(payments, dict) else None
                            if captures and isinstance(captures, list) and len(captures) > 0:
                                cap = captures[0]
                                capture_id = cap.get("id")
                                capture_status = cap.get("status")
                                amt = cap.get("amount") or cap.get("seller_receivable_breakdown") or {}
                                
                                if isinstance(amt, dict):
                                    # Try both structures
                                    paid_amount = (
                                        amt.get("value") or
                                        (amt.get("gross_amount") or {}).get("value") or
                                        (amt.get("net_amount") or {}).get("value")
                                    )
                                internal_order_id = cap.get("custom_id") or internal_order_id

                        # fallback capture_id
                        if not capture_id and isinstance(response, dict):
                            capture_id = response.get("id")

                        # Find payment
                        payment = None
                        try:
                            if internal_order_id:
                                payment = Payment.objects.filter(order__id=internal_order_id).first()
                            if not payment:
                                payment = Payment.objects.filter(order__id=order_id).first()
                        except Exception as e:
                            print("Error fetching Payment:", e)
                            payment = None

                        if payment:
                            # Update payment info
                            if capture_status == "COMPLETED":
                                print("Capture status: COMPLETED")
                                payment.status = Payment.PAYMENT_COMPLETE
                            elif capture_status in ["PENDING", "DECLINED"]:
                                print("Capture status:", capture_status)
                                payment.status = Payment.PAYMENT_PENDING

                            if paid_amount:
                                try:
                                    payment.paid_amount = float(paid_amount)
                                except Exception:
                                    print("Failed to parse paid_amount from PayPal response:", paid_amount)

                            if capture_id:
                                payment.payment_id = capture_id

                            payment.save()
                            print("Updated Payment:", payment)

                            # Update order or order group status
                            if hasattr(payment, "order_group") and payment.order_group:
                                og = payment.order_group
                                og.order_status = (
                                    OrderGroup.OrderStatus.COMPLETED
                                    if capture_status == "COMPLETED"
                                    else OrderGroup.OrderStatus.PROCESSING
                                )
                                og.save()
                                print("Updated OrderGroup:", og)
                            elif hasattr(payment, "order") and payment.order:
                                order = payment.order
                                order.order_status = (
                                    Order.OrderStatus.COMPLETED
                                    if capture_status == "COMPLETED"
                                    else Order.OrderStatus.PROCESSING
                                )
                                order.save()
                                print("Updated Order:", order)
                        else:
                            print(
                                f"No Payment record found for internal_order_id={internal_order_id} order_id={order_id}"
                            )

                except Exception as e:
                    print("Unexpected error while handling PayPal capture response:", e)

                return Response(response)

            except Exception as e:
                print("Error during PayPal capture:", e)
                return Response(
                    {'error': str(e)},
                    status=status.HTTP_400_BAD_REQUEST
                )

        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    
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
def paypal_webhook_view(request):
    """PayPal webhook endpoint."""
    return paypal_webhook_drf_view(request)
