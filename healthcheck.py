"""
後端服務共用的 Docker HEALTHCHECK 腳本，偵測到服務卡死時會真的讓容器重啟。

用法（docker-compose.yml 的 healthcheck.test）：
    python healthcheck.py http http://localhost:8000/api/health   # django
    python healthcheck.py http http://localhost:8010/mcp           # mcp
    python healthcheck.py mqtt                                     # mqtt-subscriber
    python healthcheck.py agent                                    # agent-worker

為什麼不能只靠 Docker 的 healthcheck＋restart policy：
  一般 Docker（非 Swarm）只會把容器標成 unhealthy，不會因此重啟；restart: unless-stopped
  只在主程式真正結束時才生效。process 卡住（沒當掉）時，容器會一直維持 unhealthy 但照樣卡著。

做法：
  連續失敗 FAIL_THRESHOLD 次後，對主程式送 SIGKILL。docker-compose.yml 為這三個服務設了
  init: true，PID 1 是 tini、主程式是它的子 process（PPid == 1），SIGKILL 對卡住的 process
  一樣有效；主程式結束後 tini 跟著結束，restart policy 就會把容器重新啟動。
  （沒有 init 時主程式自己就是 PID 1，核心不讓容器內部的 SIGKILL 送到 PID 1，砍不掉。）

不是所有失敗都該重啟：
  django 的 /api/health 回 503 代表 server 活著、只是資料庫連不上，重啟 django 也修不好資料庫，
  所以只回報 unhealthy、不計入重啟次數；連不上或逾時才代表 server 本身卡死。

不用 Django 環境，保持輕量快速，避免拖慢 HEALTHCHECK 間隔。
"""

import json
import os
import signal
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

FAIL_THRESHOLD = 3          # 搭配 interval 30s，約 90 秒連續失敗才重啟，避免短暫抖動誤殺
HTTP_TIMEOUT = 5
FAIL_COUNT_PATH = Path(tempfile.gettempdir()) / 'healthcheck_failures'
# 容器啟動後的寬限期：載入 TensorFlow／FAISS 需要十幾秒，而 Docker 在 start_period 期間
# 每 5 秒就檢查一次（start_interval），不設寬限的話服務還沒開完就累積 3 次失敗被砍掉
STARTUP_GRACE_SECONDS = 90

# mqtt_subscriber.py 寫入的心跳檔；超過 HEARTBEAT_TIMEOUT 秒沒更新視為卡住
HEARTBEAT_PATH = Path(tempfile.gettempdir()) / 'mqtt_heartbeat.json'
HEARTBEAT_TIMEOUT = 120     # 遠大於 keepalive 60 秒與 reconnect_delay_set 的 max_delay=30

# agent_worker.py 主迴圈每 0.5 秒更新一次；60 秒沒更新代表 event loop 卡住
AGENT_HEARTBEAT_PATH = Path(tempfile.gettempdir()) / 'agent_worker_heartbeat.json'
AGENT_HEARTBEAT_TIMEOUT = 60


def check_http(url):
    """回傳 (healthy, 是否應計入重啟)。收到任何 HTTP 回應都代表 server 沒卡死。"""
    try:
        with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT) as r:
            return True, False, f'HTTP {r.status}'
    except urllib.error.HTTPError as e:
        # MCP 的 /mcp 不接受單純 GET，會回 406，但這代表 server 有在處理請求
        if e.code == 503:
            return False, False, 'HTTP 503（服務活著但相依服務異常，不重啟）'
        return True, False, f'HTTP {e.code}'
    except Exception as e:
        return False, True, f'無回應：{e}'


def check_heartbeat(path, timeout):
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        return False, True, '心跳檔案尚未建立'
    except Exception as e:
        return False, True, f'讀取心跳檔案失敗：{e}'
    age = time.time() - data['ts']
    if age > timeout:
        return False, True, f'心跳已 {age:.0f} 秒未更新（上限 {timeout} 秒）'
    extra = {k: v for k, v in data.items() if k != 'ts'}
    return True, False, f'心跳 {age:.0f} 秒前更新 {extra}'


def _read_fail_count():
    try:
        return int(FAIL_COUNT_PATH.read_text())
    except (FileNotFoundError, ValueError):
        return 0


def _container_uptime():
    """PID 1（tini）啟動至今的秒數，即容器這次啟動多久了。"""
    starttime_ticks = int(Path('/proc/1/stat').read_text().rsplit(')', 1)[1].split()[19])
    system_uptime = float(Path('/proc/uptime').read_text().split()[0])
    return system_uptime - starttime_ticks / os.sysconf('SC_CLK_TCK')


def _kill_main_process():
    """SIGKILL tini 底下的主程式（PPid == 1）；healthcheck 自己是 docker exec 起的，PPid 是 0。"""
    killed = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) == 1:
            continue
        try:
            status = (proc / 'status').read_text()
        except OSError:
            continue
        ppid = next((line.split()[1] for line in status.splitlines() if line.startswith('PPid:')), None)
        if ppid == '1':
            os.kill(int(proc.name), signal.SIGKILL)
            killed.append(proc.name)
    return killed


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'http' and len(sys.argv) > 2:
        healthy, count_failure, detail = check_http(sys.argv[2])
    elif mode == 'mqtt':
        healthy, count_failure, detail = check_heartbeat(HEARTBEAT_PATH, HEARTBEAT_TIMEOUT)
    elif mode == 'agent':
        healthy, count_failure, detail = check_heartbeat(AGENT_HEARTBEAT_PATH, AGENT_HEARTBEAT_TIMEOUT)
    else:
        print('用法：healthcheck.py http <url> | healthcheck.py mqtt | healthcheck.py agent')
        sys.exit(2)

    if healthy:
        FAIL_COUNT_PATH.write_text('0')
        print(f'healthy: {detail}')
        sys.exit(0)

    if count_failure and _container_uptime() < STARTUP_GRACE_SECONDS:
        print(f'unhealthy: {detail}（啟動寬限期內，不計入重啟）')
        sys.exit(1)

    fails = _read_fail_count() + 1 if count_failure else _read_fail_count()
    FAIL_COUNT_PATH.write_text(str(fails))
    if count_failure and fails >= FAIL_THRESHOLD:
        killed = _kill_main_process()
        FAIL_COUNT_PATH.write_text('0')
        print(f'unhealthy: {detail}；連續 {fails} 次失敗，已終止主程式 {killed} 讓容器重啟')
    else:
        print(f'unhealthy: {detail}（連續失敗 {fails}/{FAIL_THRESHOLD}）')
    sys.exit(1)


if __name__ == '__main__':
    main()
