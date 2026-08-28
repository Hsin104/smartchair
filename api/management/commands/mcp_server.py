"""
Physio Agent MCP Server 啟動指令。

執行方式：
    python manage.py mcp_server

跟 mqtt_subscriber 一樣是長駐服務，需另開一個終端機視窗跑著不關。
監聽位址／port 由 settings.MCP_SERVER_HOST / MCP_SERVER_PORT 決定（預設 0.0.0.0:8010，
避開常見的 8001 — 曾在本機撞上 VS Code 佔用該 port 導致連線被攔截）。
"""

from django.conf import settings
from django.core.management.base import BaseCommand

from api.mcp_server import mcp


class Command(BaseCommand):
    help = 'Physio Agent MCP Server：透過 Streamable HTTP 暴露 4 個工具供 Agent 端呼叫'

    def handle(self, *args, **options):
        host = getattr(settings, 'MCP_SERVER_HOST', 'localhost')
        port = getattr(settings, 'MCP_SERVER_PORT', 8010)
        self.stdout.write(self.style.SUCCESS(
            f'啟動 Physio Agent MCP Server（Streamable HTTP）於 http://{host}:{port}/mcp ...'
        ))
        try:
            mcp.run(transport='streamable-http')
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING('\n已停止 MCP Server'))
