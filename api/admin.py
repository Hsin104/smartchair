from django.contrib import admin
from django.utils.html import format_html_join
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
    list_display  = ['id', 'user', 'posture', 'step_count', 'timestamp']
    list_filter   = ['posture']
    ordering      = ['-timestamp']
    readonly_fields = ['steps_trace']
    fields = ['user', 'posture', 'user_message', 'agent_reply', 'steps_trace', 'timestamp']

    def step_count(self, obj):
        return len(obj.steps or [])
    step_count.short_description = 'ReAct 步數'

    def steps_trace(self, obj):
        if not obj.steps:
            return '（無 ReAct 步驟紀錄）'
        return format_html_join(
            '',
            '<div style="margin-bottom:10px;padding:8px;border-left:3px solid #999;">'
            '<b>Step {}</b> — Action: <code>{}</code>({})<br>'
            '<i>Thought</i>: {}<br>'
            '<i>Observation</i>: {}'
            '</div>',
            (
                (s.get('step'), s.get('action'), s.get('action_input'),
                 s.get('thought') or '（無）', s.get('observation'))
                for s in obj.steps
            ),
        )
    steps_trace.short_description = 'ReAct 執行步驟（Thought / Action / Observation）'


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'code', 'is_used', 'created_at']
    list_filter  = ['is_used']
    search_fields = ['user__username']
    ordering     = ['-created_at']
