# PayPal Package

A comprehensive Python package for managing PayPal credentials and webhooks securely.

## Features

- 🔐 Secure credential storage with encryption
- 🌐 Webhook management and validation
- 🔄 PayPal API integration
- 📝 Comprehensive logging
- 🛡️ Security best practices
- 🧪 Full test coverage

## Installation

```bash
pip install paypal-package
```

Or install from source:

```bash
git clone https://github.com/yourusername/paypal-package.git
cd paypal-package
pip install -e .
```

## Quick Start

### 1. Setup Database Configuration

Add the package to your Django settings and run migrations:

```python
# settings.py
INSTALLED_APPS = [
    # ... your other apps
    'paypal_package',
]

# PayPal encryption key (required for credential security)
PAYPAL_ENCRYPTION_KEY = 'your-32-character-encryption-key-here'
```

```bash
# Run migrations
python manage.py migrate
```

### 2. Store PayPal Credentials

First, store your PayPal credentials in the database using the management command:

```bash
python manage.py setup_paypal \
    --name "My PayPal Account" \
    --client-id "your_paypal_client_id" \
    --client-secret "your_paypal_client_secret" \
    --mode sandbox
```

Or programmatically:

```python
from paypal_package.credentials import CredentialManager

# Store credentials securely in database
credential_manager = CredentialManager()
config = credential_manager.store_credentials(
    name="My PayPal Account",
    client_id="your_paypal_client_id",
    client_secret="your_paypal_client_secret",
    mode="sandbox"  # or "live"
)
```

### 3. Basic Usage

```python
from paypal_package import PayPalClient, WebhookManager

# Initialize PayPal client (uses database credentials)
paypal = PayPalClient()

# Create a webhook
webhook_manager = WebhookManager()
webhook_url = "https://your-domain.com/webhook/paypal"
events = ["PAYMENT.CAPTURE.COMPLETED", "PAYMENT.CAPTURE.DENIED"]

webhook = webhook_manager.create_webhook(webhook_url, events)
print(f"Webhook created: {webhook.id}")
```

### 4. Handle Webhooks

```python
from paypal_package.webhooks import WebhookHandler

# In your Django views
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

@csrf_exempt
@require_http_methods(["POST"])
def handle_paypal_webhook(request):
    handler = WebhookHandler()
    return handler.process_webhook(request)
```

Or using Django REST Framework:

```python
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from paypal_package.webhooks import WebhookHandler

@api_view(['POST'])
@permission_classes([AllowAny])
def paypal_webhook(request):
    handler = WebhookHandler()
    return handler.process_webhook_drf(request)
```

## Documentation

For detailed documentation, visit [docs/](docs/) or run:

```bash
python -m paypal_package --help
```

## Security

This package implements several security measures:

- Credentials are encrypted at rest
- Webhook signatures are validated
- Environment variables for sensitive data
- Secure HTTP headers
- Input validation and sanitization

## Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests
5. Submit a pull request

## License

MIT License - see [LICENSE](LICENSE) file for details.
"# raramarket-vendor-marketplace-paypal-plugin" 
