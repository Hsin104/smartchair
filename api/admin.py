from django.contrib import admin
from .models import User, PostureRecord, Notification, AgentLog, PasswordResetCode


@admin.register(PostureRecord)
class PostureRecordAdmin(admin.ModelAdmin):
    list_display  = ['id', 'user', 'posture', 'timestamp']
    list_filter   = ['posture', 'user']
    search_fields = ['user__username']
    ordering      = ['-timestamp']


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'message', 'is_sent', 'timestamp']
    list_filter  = ['is_sent']
    ordering     = ['-timestamp']


@admin.register(AgentLog)
class AgentLogAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'posture', 'timestamp']
    list_filter  = ['posture']
    ordering     = ['-timestamp']


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'code', 'is_used', 'created_at']
    list_filter  = ['is_used']
    search_fields = ['user__username']
    ordering     = ['-created_at']
