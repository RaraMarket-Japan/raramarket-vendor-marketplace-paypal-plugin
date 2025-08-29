"""
Credential management for PayPal package.
"""

import os
import base64
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import get_random_string
from .models import PayPalConfig


class CredentialManager:
    """Manages PayPal credentials securely."""
    
    def __init__(self, encryption_key=None):
        self.encryption_key = encryption_key or self._get_encryption_key()
        self.cipher_suite = Fernet(self.encryption_key)
    
    def _get_encryption_key(self):
        """Get encryption key from environment or generate one."""
        key = getattr(settings, 'PAYPAL_ENCRYPTION_KEY', None)
        if not key:
            key = os.environ.get('PAYPAL_ENCRYPTION_KEY')
        
        if not key:
            # Generate a new key if none exists
            key = Fernet.generate_key()
            print(f"Generated new encryption key: {key.decode()}")
            print("Please set PAYPAL_ENCRYPTION_KEY in your environment variables.")
        
        if isinstance(key, str):
            key = key.encode()
        
        return key
    
    def encrypt(self, data):
        """Encrypt sensitive data."""
        if isinstance(data, str):
            data = data.encode()
        return self.cipher_suite.encrypt(data)
    
    def decrypt(self, encrypted_data):
        """Decrypt sensitive data."""
        if isinstance(encrypted_data, str):
            encrypted_data = encrypted_data.encode()
        return self.cipher_suite.decrypt(encrypted_data).decode()
    
    def store_credentials(self, name, client_id, client_secret, mode='sandbox'):
        """Store PayPal credentials securely."""
        # Encrypt sensitive data
        encrypted_client_id = self.encrypt(client_id)
        encrypted_client_secret = self.encrypt(client_secret)
        
        # Store in database
        config, created = PayPalConfig.objects.update_or_create(
            name=name,
            defaults={
                'client_id': base64.b64encode(encrypted_client_id).decode(),
                'client_secret': base64.b64encode(encrypted_client_secret).decode(),
                'mode': mode,
                'is_active': True,
            }
        )
        
        return config
    
    def get_credentials(self, name=None):
        """Retrieve PayPal credentials."""
        if name:
            config = PayPalConfig.objects.filter(name=name, is_active=True).first()
        else:
            config = PayPalConfig.objects.filter(is_active=True).first()
        
        if not config:
            raise ImproperlyConfigured("No active PayPal configuration found.")
        
        # Decrypt sensitive data
        encrypted_client_id = base64.b64decode(config.client_id.encode())
        encrypted_client_secret = base64.b64decode(config.client_secret.encode())
        
        return {
            'client_id': self.decrypt(encrypted_client_id),
            'client_secret': self.decrypt(encrypted_client_secret),
            'mode': config.mode,
            'api_base_url': config.api_base_url,
        }
    
    def update_credentials(self, name, client_id=None, client_secret=None, mode=None):
        """Update existing credentials."""
        try:
            config = PayPalConfig.objects.get(name=name)
            
            if client_id:
                encrypted_client_id = self.encrypt(client_id)
                config.client_id = base64.b64encode(encrypted_client_id).decode()
            
            if client_secret:
                encrypted_client_secret = self.encrypt(client_secret)
                config.client_secret = base64.b64encode(encrypted_client_secret).decode()
            
            if mode:
                config.mode = mode
            
            config.save()
            return config
            
        except PayPalConfig.DoesNotExist:
            raise ValueError(f"Configuration '{name}' not found.")
    
    def delete_credentials(self, name):
        """Delete PayPal credentials."""
        try:
            config = PayPalConfig.objects.get(name=name)
            config.delete()
            return True
        except PayPalConfig.DoesNotExist:
            return False
    
    def list_configurations(self):
        """List all PayPal configurations."""
        return PayPalConfig.objects.all()
    
    def get_active_configuration(self):
        """Get the active PayPal configuration."""
        return PayPalConfig.objects.filter(is_active=True).first()
    
    def set_active_configuration(self, name):
        """Set a configuration as active and deactivate others."""
        PayPalConfig.objects.update(is_active=False)
        try:
            config = PayPalConfig.objects.get(name=name)
            config.is_active = True
            config.save()
            return config
        except PayPalConfig.DoesNotExist:
            raise ValueError(f"Configuration '{name}' not found.")


class DatabaseCredentialManager:
    """Credential manager that only uses database storage."""
    
    def __init__(self):
        pass
    
    def get_credentials(self):
        """Get credentials from database."""
        config = PayPalConfig.objects.filter(is_active=True).first()
        
        if not config:
            raise ImproperlyConfigured(
                "No active PayPal configuration found in database. "
                "Please create a PayPal configuration first."
            )
        
        # Decrypt sensitive data
        credential_manager = CredentialManager()
        encrypted_client_id = base64.b64decode(config.client_id.encode())
        encrypted_client_secret = base64.b64decode(config.client_secret.encode())
        
        return {
            'client_id': credential_manager.decrypt(encrypted_client_id),
            'client_secret': credential_manager.decrypt(encrypted_client_secret),
            'mode': config.mode,
            'api_base_url': config.api_base_url,
        }
