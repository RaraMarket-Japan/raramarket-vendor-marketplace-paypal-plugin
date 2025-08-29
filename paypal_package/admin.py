"""
Django admin interface for PayPal package.
"""

from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils.safestring import mark_safe
from .models import PayPalConfig, WebhookEvent, WebhookEndpoint


@admin.register(PayPalConfig)
class PayPalConfigAdmin(admin.ModelAdmin):
    """Admin interface for PayPal configurations."""
    
    list_display = ['name', 'mode', 'is_active', 'created_at', 'updated_at']
    list_filter = ['mode', 'is_active', 'created_at']
    search_fields = ['name']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'mode', 'is_active')
        }),
        ('Credentials', {
            'fields': ('client_id', 'client_secret'),
            'description': 'Credentials are encrypted and stored securely.'
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make credentials read-only in admin."""
        if obj:  # Editing an existing object
            return self.readonly_fields + ('client_id', 'client_secret')
        return self.readonly_fields
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of active configurations."""
        if obj and obj.is_active:
            return False
        return super().has_delete_permission(request, obj)
    
    actions = ['activate_configuration', 'deactivate_configuration']
    
    def activate_configuration(self, request, queryset):
        """Activate selected configurations."""
        updated = queryset.update(is_active=True)
        self.message_user(
            request, 
            f'Successfully activated {updated} configuration(s).'
        )
    activate_configuration.short_description = "Activate selected configurations"
    
    def deactivate_configuration(self, request, queryset):
        """Deactivate selected configurations."""
        updated = queryset.update(is_active=False)
        self.message_user(
            request, 
            f'Successfully deactivated {updated} configuration(s).'
        )
    deactivate_configuration.short_description = "Deactivate selected configurations"


@admin.register(WebhookEvent)
class WebhookEventAdmin(admin.ModelAdmin):
    """Admin interface for webhook events."""
    
    list_display = [
        'event_id', 'event_type', 'resource_type', 'resource_id', 
        'processed', 'created_at'
    ]
    list_filter = ['event_type', 'processed', 'resource_type', 'created_at']
    search_fields = ['event_id', 'resource_id', 'summary']
    readonly_fields = [
        'event_id', 'event_type', 'resource_type', 'resource_id', 
        'summary', 'raw_data', 'created_at'
    ]
    ordering = ['-created_at']
    
    fieldsets = (
        ('Event Information', {
            'fields': ('event_id', 'event_type', 'resource_type', 'resource_id')
        }),
        ('Content', {
            'fields': ('summary', 'raw_data')
        }),
        ('Status', {
            'fields': ('processed', 'processed_at')
        }),
        ('Timestamps', {
            'fields': ('created_at',),
            'classes': ('collapse',)
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent manual creation of webhook events."""
        return False
    
    def has_change_permission(self, request, obj=None):
        """Only allow changing processed status."""
        return True
    
    def get_readonly_fields(self, request, obj=None):
        """Make most fields read-only."""
        if obj:
            return self.readonly_fields + ('event_id', 'event_type', 'resource_type', 'resource_id', 'summary', 'raw_data', 'created_at')
        return self.readonly_fields
    
    actions = ['mark_as_processed', 'mark_as_unprocessed']
    
    def mark_as_processed(self, request, queryset):
        """Mark selected events as processed."""
        for event in queryset:
            event.mark_as_processed()
        self.message_user(
            request, 
            f'Successfully marked {queryset.count()} event(s) as processed.'
        )
    mark_as_processed.short_description = "Mark selected events as processed"
    
    def mark_as_unprocessed(self, request, queryset):
        """Mark selected events as unprocessed."""
        updated = queryset.update(processed=False, processed_at=None)
        self.message_user(
            request, 
            f'Successfully marked {updated} event(s) as unprocessed.'
        )
    mark_as_unprocessed.short_description = "Mark selected events as unprocessed"
    
    def get_queryset(self, request):
        """Optimize queryset for admin."""
        return super().get_queryset(request).select_related()


@admin.register(WebhookEndpoint)
class WebhookEndpointAdmin(admin.ModelAdmin):
    """Admin interface for webhook endpoints."""
    
    list_display = ['name', 'url', 'webhook_id', 'is_active', 'created_at']
    list_filter = ['is_active', 'created_at']
    search_fields = ['name', 'url']
    readonly_fields = ['webhook_id', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'url', 'is_active')
        }),
        ('Configuration', {
            'fields': ('events', 'webhook_id')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
    
    def get_readonly_fields(self, request, obj=None):
        """Make webhook_id read-only."""
        if obj:
            return self.readonly_fields + ('webhook_id',)
        return self.readonly_fields
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of active endpoints."""
        if obj and obj.is_active:
            return False
        return super().has_delete_permission(request, obj)
    
    actions = ['activate_endpoint', 'deactivate_endpoint']
    
    def activate_endpoint(self, request, queryset):
        """Activate selected endpoints."""
        updated = queryset.update(is_active=True)
        self.message_user(
            request, 
            f'Successfully activated {updated} endpoint(s).'
        )
    activate_endpoint.short_description = "Activate selected endpoints"
    
    def deactivate_endpoint(self, request, queryset):
        """Deactivate selected endpoints."""
        updated = queryset.update(is_active=False)
        self.message_user(
            request, 
            f'Successfully deactivated {updated} endpoint(s).'
        )
    deactivate_endpoint.short_description = "Deactivate selected endpoints"
