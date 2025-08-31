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

