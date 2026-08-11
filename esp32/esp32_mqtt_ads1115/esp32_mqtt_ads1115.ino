#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

const char* WIFI_SSID = "xiao";
const char* WIFI_PASSWORD = "1234567890";

const char* MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com";  // EMQX Cloud
const int   MQTT_PORT   = 8883;  // TLS
const char* MQTT_TOPIC_SENSOR = "chair/pressure/01";
const char* MQTT_TOPIC_VIB_CMD = "chair/vibration/01/cmd";
const char* MQTT_TOPIC_VIB_ACK = "chair/vibration/01/ack";
const char* MQTT_TOPIC_VIB_STATE = "chair/vibration/01/state";
const char* MQTT_TOPIC_VIB_STATUS = "chair/vibration/01/status";
const char* MQTT_CLIENT_ID = "esp32-chair-01";
const char* MQTT_USER   = "xiao";
const char* MQTT_PASS   = "zxzcindy1";

// 💡 定義外接指示燈腳位在 D2 (GPIO 2)
const int DETECT_LED_PIN = 2; 

const int MOTOR_COUNT = 4;
const int MOTOR_PINS[MOTOR_COUNT] = {14, 27, 26, 25};  // D14, D27, D26, D25
const int MOTOR_PWM_CHANNELS[MOTOR_COUNT] = {0, 1, 2, 3};
const int MOTOR_PWM_FREQ = 250;
const int MOTOR_PWM_RESOLUTION = 8;
const int MOTOR_INTENSITY_MAX = 100;
const int MOTOR_DURATION_MIN_MS = 50;
const int MOTOR_DURATION_MAX_MS = 5000;
const int MOTOR_STAGGER_DEFAULT_MS = 80;
const int MOTOR_STAGGER_MAX_MS = 500;
const unsigned long MOTOR_SAFETY_TIMEOUT_MS = 15000;
const unsigned long MOTOR_STATE_INTERVAL_MS = 1000;
const int SENSOR_SIGNAL_THRESHOLD_RAW = 120;
const int SENSOR_NOISE_BAND_RAW = 40;
const unsigned long SENSOR_DETECT_WINDOW_MS = 15000;

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);

Adafruit_ADS1115 ads1;  // 位址 0x48，ADDR 接 GND
Adafruit_ADS1115 ads2;  // 位址 0x49，ADDR 接 3V3
Adafruit_ADS1115 ads3;  // 位址 0x4A，ADDR 接 SDA（預留）

const int SENSOR_COUNT = 11;

bool ads1_available = false;
bool ads2_available = false;
bool ads3_available = false;

bool sensorSeenSignal[SENSOR_COUNT];
int sensorMinRaw[SENSOR_COUNT];
int sensorMaxRaw[SENSOR_COUNT];
unsigned long sensorDetectStartMs = 0;

const bool SENSOR_ACTIVE[SENSOR_COUNT] = {
  true, true, true, true, true, true, true, true, true, true, true
};

int adcMin[SENSOR_COUNT] = {
  2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400
};
int adcMax[SENSOR_COUNT] = {
  20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500
};

unsigned long lastPublishMs = 0;
const unsigned long PUBLISH_INTERVAL_MS = 500;  // 每秒 2 次
unsigned long lastMotorStateMs = 0;
unsigned long lastValidMotorCmdMs = 0;
bool safetyTimeoutTriggered = false;

struct MotorRuntime {
  bool running;
  bool scheduled;
  int intensity;
  unsigned long startAtMs;
  unsigned long stopAtMs;
};

MotorRuntime motors[MOTOR_COUNT];

#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
void pwmAttachMotor(int motorIndex) {
  ledcAttach(MOTOR_PINS[motorIndex], MOTOR_PWM_FREQ, MOTOR_PWM_RESOLUTION);
}

void pwmWriteMotor(int motorIndex, int duty) {
  ledcWrite(MOTOR_PINS[motorIndex], duty);
}
#else
void pwmAttachMotor(int motorIndex) {
  ledcSetup(MOTOR_PWM_CHANNELS[motorIndex], MOTOR_PWM_FREQ, MOTOR_PWM_RESOLUTION);
  ledcAttachPin(MOTOR_PINS[motorIndex], MOTOR_PWM_CHANNELS[motorIndex]);
}

void pwmWriteMotor(int motorIndex, int duty) {
  ledcWrite(MOTOR_PWM_CHANNELS[motorIndex], duty);
}
#endif

bool timeReached(unsigned long nowMs, unsigned long targetMs) {
  return (long)(nowMs - targetMs) >= 0;
}

int clampInt(int value, int minValue, int maxValue) {
  if (value < minValue) return minValue;
  if (value > maxValue) return maxValue;
  return value;
}

void setMotorOutput(int motorIndex, int intensity) {
  int duty = map(clampInt(intensity, 0, MOTOR_INTENSITY_MAX), 0, MOTOR_INTENSITY_MAX, 0, 255);
  pwmWriteMotor(motorIndex, duty);
}

void stopMotor(int motorIndex) {
  setMotorOutput(motorIndex, 0);
  motors[motorIndex].running = false;
  motors[motorIndex].scheduled = false;
  motors[motorIndex].intensity = 0;
}

void stopAllMotors() {
  for (int i = 0; i < MOTOR_COUNT; i++) {
    stopMotor(i);
  }
}

bool extractIntField(const String& text, const char* key, int& outValue) {
  String token = String("\"") + key + "\":";
  int start = text.indexOf(token);
  if (start < 0) return false;

  start += token.length();
  while (start < (int)text.length() && (text[start] == ' ' || text[start] == '\t')) start++;

  bool neg = false;
  if (start < (int)text.length() && text[start] == '-') {
    neg = true;
    start++;
  }

  int end = start;
  while (end < (int)text.length() && isDigit(text[end])) end++;
  if (end == start) return false;

  int value = text.substring(start, end).toInt();
  outValue = neg ? -value : value;
  return true;
}

bool extractStringField(const String& text, const char* key, String& outValue) {
  String token = String("\"") + key + "\":";
  int start = text.indexOf(token);
  if (start < 0) return false;

  start += token.length();
  while (start < (int)text.length() && (text[start] == ' ' || text[start] == '\t')) start++;
  if (start >= (int)text.length() || text[start] != '"') return false;
  start++;
  int end = text.indexOf('"', start);
  if (end < 0) return false;

  outValue = text.substring(start, end);
  return true;
}

bool extractBoolField(const String& text, const char* key, bool& outValue) {
  String token = String("\"") + key + "\":";
  int start = text.indexOf(token);
  if (start < 0) return false;

  start += token.length();
  while (start < (int)text.length() && (text[start] == ' ' || text[start] == '\t')) start++;

  if (text.startsWith("true", start)) {
    outValue = true;
    return true;
  }
  if (text.startsWith("false", start)) {
    outValue = false;
    return true;
  }
  return false;
}

bool isSensorModuleAvailable(int sensorIndex) {
  if (sensorIndex < 4) return ads1_available;
  if (sensorIndex < 8) return ads2_available;
  return ads3_available;
}

void updateSensorDetectionStats(int sensorIndex, int rawValue) {
  if (!isSensorModuleAvailable(sensorIndex)) return;

  if (rawValue < sensorMinRaw[sensorIndex]) sensorMinRaw[sensorIndex] = rawValue;
  if (rawValue > sensorMaxRaw[sensorIndex]) sensorMaxRaw[sensorIndex] = rawValue;
  if (rawValue >= SENSOR_SIGNAL_THRESHOLD_RAW) sensorSeenSignal[sensorIndex] = true;
}

const char* getSensorStateText(int sensorIndex, unsigned long nowMs) {
  if (!isSensorModuleAvailable(sensorIndex)) return "not_detected";
  if (sensorSeenSignal[sensorIndex]) return "installed";

  if (nowMs - sensorDetectStartMs < SENSOR_DETECT_WINDOW_MS) {
    return "detecting";
  }

  int spread = sensorMaxRaw[sensorIndex] - sensorMinRaw[sensorIndex];
  if (sensorMaxRaw[sensorIndex] < SENSOR_SIGNAL_THRESHOLD_RAW && spread <= SENSOR_NOISE_BAND_RAW) {
    return "not_installed";
  }
  return "installed";
}

void publishMotorAck(const char* cmdId, const char* status, const char* message) {
  String payload = "{\"device_id\":\"chair_01\",\"ts\":";
  payload += String((unsigned long)(millis() / 1000));
  payload += ",\"cmd_id\":\"";
  payload += String(cmdId);
  payload += "\",\"status\":\"";
  payload += String(status);
  payload += "\",\"message\":\"";
  payload += String(message);
  payload += "\"}";
  mqttClient.publish(MQTT_TOPIC_VIB_ACK, payload.c_str());
}

void publishMotorStatus(const char* eventName, const char* message) {
  String payload = "{\"device_id\":\"chair_01\",\"ts\":";
  payload += String((unsigned long)(millis() / 1000));
  payload += ",\"event\":\"";
  payload += String(eventName);
  payload += "\",\"message\":\"";
  payload += String(message);
  payload += "\"}";
  mqttClient.publish(MQTT_TOPIC_VIB_STATUS, payload.c_str());
}

void publishHardwareReport() {
  String payload = "{\"device_id\":\"chair_01\",\"ts\":";
  payload += String((unsigned long)(millis() / 1000));
  payload += ",\"event\":\"hardware_report\",\"motor_detection_supported\":false";
  payload += ",\"ads\":{";
  payload += "\"ads1\":";
  payload += ads1_available ? "true" : "false";
  payload += ",\"ads2\":";
  payload += ads2_available ? "true" : "false";
  payload += ",\"ads3\":";
  payload += ads3_available ? "true" : "false";
  payload += "}";

  payload += ",\"sensor_detected\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    bool detected = false;
    if (i < 4) {
      detected = ads1_available;
    } else if (i < 8) {
      detected = ads2_available;
    } else {
      detected = ads3_available;
    }
    if (i > 0) payload += ",";
    payload += detected ? "true" : "false";
  }

  payload += "],\"motor_detected\":[";
  for (int i = 0; i < MOTOR_COUNT; i++) {
    if (i > 0) payload += ",";
    payload += "\"unknown\"";
  }
  payload += "]}";
  mqttClient.publish(MQTT_TOPIC_VIB_STATUS, payload.c_str());
}

void publishMotorState(const char* eventName, const char* cmdId) {
  unsigned long nowMs = millis();

  String payload = "{\"device_id\":\"chair_01\",\"ts\":";
  payload += String((unsigned long)(nowMs / 1000));
  payload += ",\"event\":\"";
  payload += String(eventName);
  payload += "\",\"cmd_id\":\"";
  payload += String(cmdId);
  payload += "\",\"motors\":[";

  for (int i = 0; i < MOTOR_COUNT; i++) {
    unsigned long remainingMs = 0;
    if (motors[i].running && motors[i].stopAtMs > nowMs) {
      remainingMs = motors[i].stopAtMs - nowMs;
    }

    if (i > 0) payload += ",";
    payload += "{\"id\":";
    payload += String(i + 1);
    payload += ",\"pin\":";
    payload += String(MOTOR_PINS[i]);
    payload += ",\"running\":";
    payload += motors[i].running ? "true" : "false";
    payload += ",\"intensity\":";
    payload += String(motors[i].intensity);
    payload += ",\"remaining_ms\":";
    payload += String(remainingMs);
    payload += "}";
  }
  payload += "]}";
  mqttClient.publish(MQTT_TOPIC_VIB_STATE, payload.c_str());
}

void scheduleMotor(int motorIndex, int intensity, int durationMs, int startDelayMs) {
  unsigned long nowMs = millis();
  motors[motorIndex].running = false;
  motors[motorIndex].scheduled = true;
  motors[motorIndex].intensity = clampInt(intensity, 0, MOTOR_INTENSITY_MAX);
  motors[motorIndex].startAtMs = nowMs + (unsigned long)startDelayMs;
  motors[motorIndex].stopAtMs = motors[motorIndex].startAtMs + (unsigned long)durationMs;
  setMotorOutput(motorIndex, 0);
}

bool scheduleSingleCommand(int motorId, int intensity, int durationMs, int order, int staggerMs) {

  if (motorId < 1 || motorId > MOTOR_COUNT) {
    return false;
  }

  intensity = clampInt(intensity, 0, MOTOR_INTENSITY_MAX);
  durationMs = clampInt(durationMs, MOTOR_DURATION_MIN_MS, MOTOR_DURATION_MAX_MS);
  int delayMs = order * staggerMs;

  scheduleMotor(motorId - 1, intensity, durationMs, delayMs);
  return true;
}

void handleMotorCommand(const char* payloadText) {
  String text = String(payloadText);
  String cmdId = "no_cmd_id";
  extractStringField(text, "cmd_id", cmdId);

  bool stopAll = false;
  if (extractBoolField(text, "stop_all", stopAll) && stopAll) {
    stopAllMotors();
    publishMotorAck(cmdId.c_str(), "ok", "all_motors_stopped");
    publishMotorState("stop_all", cmdId.c_str());
    return;
  }

  int staggerMs = MOTOR_STAGGER_DEFAULT_MS;
  extractIntField(text, "stagger_ms", staggerMs);
  staggerMs = clampInt(staggerMs, 0, MOTOR_STAGGER_MAX_MS);

  int scheduledCount = 0;
  int motorsPos = text.indexOf("\"motors\"");
  if (motorsPos >= 0) {
    int arrStart = text.indexOf('[', motorsPos);
    int arrEnd = text.indexOf(']', arrStart);
    if (arrStart >= 0 && arrEnd > arrStart) {
      String arrText = text.substring(arrStart + 1, arrEnd);
      int cursor = 0;
      int order = 0;
      while (cursor < (int)arrText.length() && order < MOTOR_COUNT) {
        int objStart = arrText.indexOf('{', cursor);
        if (objStart < 0) break;
        int objEnd = arrText.indexOf('}', objStart);
        if (objEnd < 0) break;

        String item = arrText.substring(objStart, objEnd + 1);
        int motorId = 0;
        int intensity = 0;
        int durationMs = 0;

        bool ok = extractIntField(item, "id", motorId) &&
                  extractIntField(item, "intensity", intensity) &&
                  extractIntField(item, "duration_ms", durationMs);

        if (ok && scheduleSingleCommand(motorId, intensity, durationMs, order, staggerMs)) {
          scheduledCount++;
          order++;
        }

        cursor = objEnd + 1;
      }
    }
  }

  if (scheduledCount <= 0) {
    int motorId = 0;
    int intensity = 0;
    int durationMs = 0;
    bool ok = extractIntField(text, "motor_id", motorId) &&
              extractIntField(text, "intensity", intensity) &&
              extractIntField(text, "duration_ms", durationMs);

    if (ok && scheduleSingleCommand(motorId, intensity, durationMs, 0, staggerMs)) {
      scheduledCount = 1;
    }
  }

  if (scheduledCount <= 0) {
    publishMotorAck(cmdId.c_str(), "error", "no_valid_motor_command");
    return;
  }

  lastValidMotorCmdMs = millis();
  safetyTimeoutTriggered = false;
  publishMotorAck(cmdId.c_str(), "ok", "scheduled");
  publishMotorState("cmd_accepted", cmdId.c_str());
}

bool updateMotorStateMachine() {
  bool changed = false;
  unsigned long nowMs = millis();

  for (int i = 0; i < MOTOR_COUNT; i++) {
    if (motors[i].scheduled && !motors[i].running && timeReached(nowMs, motors[i].startAtMs)) {
      setMotorOutput(i, motors[i].intensity);
      motors[i].running = true;
      motors[i].scheduled = false;
      changed = true;
    }

    if (motors[i].running && timeReached(nowMs, motors[i].stopAtMs)) {
      stopMotor(i);
      changed = true;
    }
  }

  return changed;
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  String topicStr = String(topic);
  String payloadText;
  payloadText.reserve(length + 1);

  for (unsigned int i = 0; i < length; i++) {
    payloadText += (char)payload[i];
  }

  if (topicStr == MQTT_TOPIC_VIB_CMD) {
    handleMotorCommand(payloadText.c_str());
  }
}

float clamp01(float x) {
  if (x < 0.0f) return 0.0f;
  if (x > 1.0f) return 1.0f;
  return x;
}

int normalizeTo100(int value, int vmin, int vmax) {
  if (vmax <= vmin) return 0;
  float ratio = (float)(value - vmin) / (float)(vmax - vmin);
  ratio = clamp01(ratio);
  return (int)(ratio * 100.0f + 0.5f);
}

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("連線 Wi-Fi: ");
  Serial.println(WIFI_SSID);

  int retry = 0;
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
    retry++;
    if (retry >= 20) {
      Serial.println();
      Serial.println("Wi-Fi 連線失敗，重試中...");
      WiFi.disconnect();
      delay(1000);
      WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      retry = 0;
    }
  }
  Serial.println();
  Serial.print("Wi-Fi 已連線，IP: ");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  Serial.print("連線 MQTT Broker: ");
  Serial.println(MQTT_BROKER);
  while (!mqttClient.connected()) {
    if (mqttClient.connect(MQTT_CLIENT_ID, MQTT_USER, MQTT_PASS)) {
      Serial.println("MQTT 已連線！");
      mqttClient.subscribe(MQTT_TOPIC_VIB_CMD);
      publishMotorStatus("mqtt_connected", "subscribed_vibration_command_topic");
      publishHardwareReport();
      publishMotorState("boot", "none");
    } else {
      Serial.print("MQTT 連線失敗，rc=");
      Serial.print(mqttClient.state());
      Serial.println(" 1秒後重試...");
      delay(1000);
    }
  }
}

String buildPayload(const int raw[], const int normalized[], unsigned long ts) {
  unsigned long nowMs = millis();
  String payload = "{\"device_id\":\"chair_01\",\"ts\":";
  payload += String(ts);
  payload += ",\"raw\":[";

  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) payload += ",";
    payload += String(raw[i]);
  }

  payload += "],\"norm\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) payload += ",";
    payload += String(normalized[i]);
  }

  payload += "],\"sensor_detected\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    bool detected = false;
    if (i < 4) {
      detected = ads1_available;
    } else if (i < 8) {
      detected = ads2_available;
    } else {
      detected = ads3_available;
    }
    if (i > 0) payload += ",";
    payload += detected ? "true" : "false";
  }

  payload += "],\"sensor_state\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) payload += ",";
    payload += "\"";
    payload += getSensorStateText(i, nowMs);
    payload += "\"";
  }

  payload += "]}";
  return payload;
}

void setup() {
  Serial.begin(115200);
  delay(800); 
  Serial.println("\n--- 🚀 智慧感測椅系統開機 ---");

  // 初始化外接指示燈腳位
  pinMode(DETECT_LED_PIN, OUTPUT);
  digitalWrite(DETECT_LED_PIN, LOW); 

  for (int i = 0; i < SENSOR_COUNT; i++) {
    sensorSeenSignal[i] = false;
    sensorMinRaw[i] = 32767;
    sensorMaxRaw[i] = -32768;
  }
  sensorDetectStartMs = millis();

  for (int i = 0; i < MOTOR_COUNT; i++) {
    pwmAttachMotor(i);
    motors[i].running = false;
    motors[i].scheduled = false;
    motors[i].intensity = 0;
    motors[i].startAtMs = 0;
    motors[i].stopAtMs = 0;
    setMotorOutput(i, 0);
  }

  // 🔧 核心修正：換回先前測試 100% 成功、最直覺的 I2C 初始化寫法
  Wire.begin(21, 22);
  delay(200); // 讓總線完全穩定下來

  // 🔧 ADS1115 #1 (0x48) 初始化重試機制
  int retry = 0;
  while (retry < 3) {
    if (ads1.begin(0x48)) {
      ads1_available = true;
      ads1.setGain(GAIN_ONE);
      Serial.println("✓ ADS1115 #1 (0x48) 初始化成功");
      break;
    }
    retry++;
    Serial.print("⚠️ 找不到 ADS1115 #1，正在進行第 ");
    Serial.print(retry);
    Serial.println(" 次重試...");
    delay(200);
  }
  if (!ads1_available) {
    Serial.println("✗ ADS1115 #1 (0x48) 未找到，S1-S4 將強制給 0");
  }

  // 🔧 ADS1115 #2 (0x49) 初始化重試機制
  retry = 0;
  while (retry < 3) {
    if (ads2.begin(0x49)) {
      ads2_available = true;
      ads2.setGain(GAIN_ONE);
      Serial.println("✓ ADS1115 #2 (0x49) 初始化成功");
      break;
    }
    retry++;
    delay(100);
  }
  if (!ads2_available) {
    Serial.println("✗ ADS1115 #2 (0x49) 未找到，S5-S8 將強制給 0");
  }

  // 🔧 ADS1115 #3 (0x4A) 初始化（預留）
  if (ads3.begin(0x4A)) {
    ads3_available = true;
    ads3.setGain(GAIN_ONE);
    Serial.println("✓ ADS1115 #3 (0x4A) 初始化成功");
  } else {
    ads3_available = false;
    Serial.println("✗ ADS1115 #3 (0x4A) 未找到，S9-S11 將強制給 0");
  }

  // 🎯 【閃燈回報功能】計算順利連接的晶片總數，並透過燈號閃爍回報
  int online_modules_count = 0;
  if (ads1_available) online_modules_count++;
  if (ads2_available) online_modules_count++;
  if (ads3_available) online_modules_count++;

  Serial.print("--- 💡 硬體自檢完畢：共偵測到 ");
  Serial.print(online_modules_count);
  Serial.println(" 顆感測晶片模組 ---");

  if (online_modules_count > 0) {
    delay(500); 
    for (int i = 0; i < online_modules_count; i++) {
      digitalWrite(DETECT_LED_PIN, HIGH);  // 亮燈
      delay(300);                          
      digitalWrite(DETECT_LED_PIN, LOW);   // 滅燈
      delay(300);                          
    }
  }

  // 連線網路與雲端（放在硬體自檢後面，確保不受網路搶電干擾）
  connectWiFi();
  wifiClient.setInsecure();  
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);
  connectMQTT();

  lastValidMotorCmdMs = millis();
  lastMotorStateMs = millis();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!mqttClient.connected()) {
    connectMQTT();
  }

  mqttClient.loop();

  if (updateMotorStateMachine()) {
    publishMotorState("motor_changed", "none");
  }

  unsigned long now = millis();
  if (!safetyTimeoutTriggered && (now - lastValidMotorCmdMs > MOTOR_SAFETY_TIMEOUT_MS)) {
    stopAllMotors();
    publishMotorStatus("safety_timeout", "stop_all_motors");
    publishMotorState("safety_timeout", "none");
    safetyTimeoutTriggered = true;
  }

  if (now - lastMotorStateMs >= MOTOR_STATE_INTERVAL_MS) {
    lastMotorStateMs = now;
    publishMotorState("heartbeat", "none");
  }

  if (now - lastPublishMs < PUBLISH_INTERVAL_MS) {
    return;
  }
  lastPublishMs = now;

  int raw[SENSOR_COUNT];
  int normalized[SENSOR_COUNT];

  // 📊 處理 S1-S4：來自 ADS1115 #1
  for (int i = 0; i < 4; i++) {
    if (SENSOR_ACTIVE[i]) {
      if (ads1_available) {
        raw[i] = ads1.readADC_SingleEnded(i);
      } else {
        raw[i] = 0; // 沒偵測到晶片，直接給 0
      }
      normalized[i] = normalizeTo100(raw[i], adcMin[i], adcMax[i]);
      updateSensorDetectionStats(i, raw[i]);
    } else {
      raw[i] = 0;
      normalized[i] = 0;
    }
  }

  // 📊 處理 S5-S8：來自 ADS1115 #2
  for (int i = 0; i < 4; i++) {
    int idx = i + 4;
    if (SENSOR_ACTIVE[idx]) {
      if (ads2_available) {
        raw[idx] = ads2.readADC_SingleEnded(i);
      } else {
        raw[idx] = 0; // 沒偵測到晶片，直接給 0
      }
      normalized[idx] = normalizeTo100(raw[idx], adcMin[idx], adcMax[idx]);
      updateSensorDetectionStats(idx, raw[idx]);
    } else {
      raw[idx] = 0;
      normalized[idx] = 0;
    }
  }

  // 📊 處理 S9-S11：來自 ADS1115 #3（只使用 A0-A2）
  for (int i = 0; i < 3; i++) {
    int idx = i + 8;
    if (SENSOR_ACTIVE[idx]) {
      if (ads3_available) {
        raw[idx] = ads3.readADC_SingleEnded(i);
      } else {
        raw[idx] = 0; // 沒偵測到晶片，直接給 0
      }
      normalized[idx] = normalizeTo100(raw[idx], adcMin[idx], adcMax[idx]);
      updateSensorDetectionStats(idx, raw[idx]);
    } else {
      raw[idx] = 0;
      normalized[idx] = 0;
    }
  }

  // 打包 MQTT JSON 封包
  unsigned long ts = (unsigned long)(millis() / 1000);
  String payload = buildPayload(raw, normalized, ts);
  mqttClient.publish(MQTT_TOPIC_SENSOR, payload.c_str());
  Serial.println(payload);
}