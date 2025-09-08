"""
URL configuration for PayPal package.
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from . import views

# Create router for ViewSets
router = DefaultRouter()
router.register(r'configs', views.PayPalConfigViewSet, basename='paypal-config')
router.register(r'webhook-events', views.WebhookEventViewSet, basename='webhook-event')
router.register(r'webhook-endpoints', views.WebhookEndpointViewSet, basename='webhook-endpoint')

# URL patterns
urlpatterns = [
    path('paypal-config/', include(router.urls)),
    # Webhook endpoint (no authentication required)
    path('webhook/paypal/', views.paypal_webhook_view, name='paypal-webhook'),
    
    # Payment endpoints
    path('paypal-orders/', views.PayPalPaymentViewSet.as_view({
        'post': 'create_order'
    }), name='create-paypal-order'),

    
    path('paypal-orders/<str:order_id>/', views.PayPalPaymentViewSet.as_view({
        'get': 'get_order'
    }), name='get-order'),
    
    path('paypal-orders/<str:order_id>/capture/', views.PayPalPaymentViewSet.as_view({

        'post': 'capture_payment'
    }), name='capture-payment'),
    
    # path('api/payments/<str:capture_id>/refund/', views.PayPalPaymentViewSet.as_view({
    #     'post': 'refund_payment'
    # }), name='refund-payment'),
    
    path('api/payments/<str:payment_id>/', views.PayPalPaymentViewSet.as_view({
        'get': 'get_payment_details'
    }), name='get-payment-details'),
]
