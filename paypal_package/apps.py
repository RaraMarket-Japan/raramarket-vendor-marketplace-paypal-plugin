"""
Django app configuration for PayPal package.
"""

from django.apps import AppConfig


class PaypalPackageConfig(AppConfig):
    """Configuration for PayPal package app."""
    
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'paypal_package'
    verbose_name = 'PayPal Integration'
    
