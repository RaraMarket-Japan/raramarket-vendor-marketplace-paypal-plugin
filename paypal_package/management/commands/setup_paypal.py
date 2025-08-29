"""
Django management command to set up PayPal credentials.
"""

from django.core.management.base import BaseCommand, CommandError
from django.core.validators import URLValidator
from django.core.exceptions import ValidationError
from paypal_package.credentials import CredentialManager


class Command(BaseCommand):
    help = 'Set up PayPal credentials in the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--name',
            type=str,
            default='Default PayPal Account',
            help='Name for the PayPal configuration'
        )
        parser.add_argument(
            '--client-id',
            type=str,
            required=True,
            help='PayPal Client ID'
        )
        parser.add_argument(
            '--client-secret',
            type=str,
            required=True,
            help='PayPal Client Secret'
        )
        parser.add_argument(
            '--mode',
            type=str,
            choices=['sandbox', 'live'],
            default='sandbox',
            help='PayPal environment mode (sandbox or live)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force update if configuration already exists'
        )

    def handle(self, *args, **options):
        name = options['name']
        client_id = options['client_id']
        client_secret = options['client_secret']
        mode = options['mode']
        force = options['force']

        try:
            credential_manager = CredentialManager()
            
            # Check if configuration already exists
            from paypal_package.models import PayPalConfig
            existing_config = PayPalConfig.objects.filter(name=name).first()
            
            if existing_config and not force:
                self.stdout.write(
                    self.style.WARNING(
                        f'Configuration "{name}" already exists. Use --force to update.'
                    )
                )
                return
            
            # Store credentials
            config = credential_manager.store_credentials(
                name=name,
                client_id=client_id,
                client_secret=client_secret,
                mode=mode
            )
            
            self.stdout.write(
                self.style.SUCCESS(
                    f'Successfully created PayPal configuration: {config.name} ({config.mode})'
                )
            )
            
            if mode == 'sandbox':
                self.stdout.write(
                    self.style.WARNING(
                        'Note: Using sandbox mode. For production, use --mode live'
                    )
                )
            
        except Exception as e:
            raise CommandError(f'Failed to set up PayPal credentials: {e}')
