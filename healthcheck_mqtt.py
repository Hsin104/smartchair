"""
MQTT subscriber 的 Docker HEALTHCHECK 腳本。

讀取 api/management/commands/mqtt_subscriber.py 寫入的心跳檔案（/tmp/mqtt_heartbeat.json），
心跳超過 HEARTBEAT_TIMEOUT 秒沒更新就視為不健康（process 卡住、連線卡死等 crash-loop
偵測不到的情況），讓 docker-compose.yml 的 restart: unless-stopped 能真正重啟服務。

不用 Django 環境，保持輕量快速，避免拖慢 HEALTHCHECK 間隔。
"""

import json
import sys
import tempfile
import time
from pathlib import Path

HEARTBEAT_PATH = Path(tempfile.gettempdir()) / 'mqtt_heartbeat.json'
HEARTBEAT_TIMEOUT = 120  # 秒；遠大於 reconnect_delay_set 的 max_delay=30，排除正常重連造成的誤判

try:
    data = json.loads(HEARTBEAT_PATH.read_text())
    age = time.time() - data['ts']
    if age > HEARTBEAT_TIMEOUT:
        print(f'unhealthy: 心跳已 {age:.0f} 秒未更新（上限 {HEARTBEAT_TIMEOUT} 秒）')
        sys.exit(1)
    print(f'healthy: 心跳 {age:.0f} 秒前更新，connected={data.get("connected")}')
    sys.exit(0)
except FileNotFoundError:
    print('unhealthy: 心跳檔案尚未建立（服務可能還在啟動中）')
    sys.exit(1)
except Exception as e:
    print(f'unhealthy: 讀取心跳檔案失敗：{e}')
    sys.exit(1)
