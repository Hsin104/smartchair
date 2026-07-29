# Agent Quickstart (No UI/Test Dependency)

這份給組員，只需要做兩件事：
1. 訂閱壓力資料
2. 發送馬達指令

## 1. Topic
- Sensor: chair/pressure/01
- Motor Command: chair/vibration/01/cmd
- Motor ACK: chair/vibration/01/ack
- Motor State: chair/vibration/01/state
- Motor Status: chair/vibration/01/status

## 2. 感測器資料格式
```json
{
  "device_id": "chair_01",
  "ts": 123,
  "raw": [11筆],
  "norm": [11筆]
}
```

## 3. 馬達指令格式
### 單顆
```json
{
  "cmd_id": "cmd-001",
  "motor_id": 1,
  "intensity": 70,
  "duration_ms": 800,
  "stagger_ms": 80
}
```

### 多顆
```json
{
  "cmd_id": "cmd-002",
  "stagger_ms": 100,
  "motors": [
    {"id": 1, "intensity": 60, "duration_ms": 900},
    {"id": 3, "intensity": 65, "duration_ms": 1100}
  ]
}
```

### 全停
```json
{
  "cmd_id": "cmd-stop",
  "stop_all": true
}
```

## 4. 參數限制
- motor_id / motors[].id: 1~4
- intensity: 0~100
- duration_ms: 50~5000
- stagger_ms: 0~500

韌體容錯行為：
- 參數超範圍會自動夾限。
- 多顆命令中部分項目無效時，會忽略無效項目並執行有效項目。
- 若 ADS 模組缺失，系統仍持續運作，對應感測值上報為 0。

## 5. ACK 格式
```json
{
  "device_id": "chair_01",
  "ts": 123,
  "cmd_id": "cmd-001",
  "status": "ok",
  "message": "scheduled"
}
```

## 6. 組員可直接使用的最小 Python 客戶端
檔案：receiver/agent_minimal_client.py

### 只聽資料
```powershell
& "e:/pccu/專題/感測器配置/.venv/Scripts/python.exe" "e:/pccu/專題/感測器配置/receiver/agent_minimal_client.py" --mode listen
```

### 送單顆馬達
```powershell
& "e:/pccu/專題/感測器配置/.venv/Scripts/python.exe" "e:/pccu/專題/感測器配置/receiver/agent_minimal_client.py" --mode single --motor-id 1 --intensity 70 --duration-ms 800 --stagger-ms 80 --listen-sec 2
```

### 送多顆馬達
```powershell
& "e:/pccu/專題/感測器配置/.venv/Scripts/python.exe" "e:/pccu/專題/感測器配置/receiver/agent_minimal_client.py" --mode multi --motors-json "[{\"id\":1,\"intensity\":60,\"duration_ms\":900},{\"id\":2,\"intensity\":60,\"duration_ms\":900}]" --stagger-ms 100 --listen-sec 2
```

### 全停
```powershell
& "e:/pccu/專題/感測器配置/.venv/Scripts/python.exe" "e:/pccu/專題/感測器配置/receiver/agent_minimal_client.py" --mode stop --listen-sec 2
```
