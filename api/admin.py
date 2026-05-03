from django.contrib import admin
from .models import User, PostureRecord, Notification, AgentLog


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
