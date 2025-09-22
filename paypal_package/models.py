from django.db import models


class PayPalConfig(models.Model):
    """Model to store PayPal configuration settings."""

    name = models.CharField(max_length=100, unique=True, help_text="Configuration name")
    client_id = models.CharField(max_length=600, help_text="PayPal Client ID")
    client_secret = models.CharField(max_length=600, help_text="PayPal Client Secret")

    use_sandbox = models.BooleanField(
        default=True,
        help_text="If enabled, use PayPal Sandbox; if disabled, use Live"
    )

    is_active = models.BooleanField(
        default=True,
        help_text="Whether this configuration is currently active"
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "PayPal Configuration"
        verbose_name_plural = "PayPal Configurations"
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({'Sandbox' if self.use_sandbox else 'Live'})"

    @property
    def api_base_url(self):
        """Get the PayPal API base URL based on sandbox toggle."""
        return (
            "https://api-m.sandbox.paypal.com"
            if self.use_sandbox
            else "https://api-m.paypal.com"
        )

    def save(self, *args, **kwargs):
        # Optional: ensure only one active config per environment
        if self.is_active:
            PayPalConfig.objects.filter(
                use_sandbox=self.use_sandbox, is_active=True
            ).exclude(pk=self.pk).update(is_active=False)

        super().save(*args, **kwargs)
