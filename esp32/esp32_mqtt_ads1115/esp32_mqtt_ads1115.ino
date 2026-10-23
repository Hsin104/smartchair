#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <ArduinoOTA.h>
#include "secrets.h"

const char* MQTT_TOPIC_SENSOR = "chair/pressure/01";
const char* MQTT_TOPIC_VIB_CMD = "chair/vibration/01/cmd";
const char* MQTT_TOPIC_VIB_ACK = "chair/vibration/01/ack";
const char* MQTT_TOPIC_VIB_STATE = "chair/vibration/01/state";
const char* MQTT_TOPIC_VIB_STATUS = "chair/vibration/01/status";

// 💡 定義外接指示燈腳位在 D2 (GPIO 2)123
const int DETECT_LED_PIN = 2; 

const int SENSOR_COUNT = 11;
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

const int BATTERY_VP_PIN = 36;  // VP = GPIO36 (ADC1_CH0)
// 分壓比 = 電池電壓 / VP 腳電壓。
// 校正方式：用三用電表同時量「電池正極對 GND」與「VP 對 GND」，兩者相除填入。
// 也可用電阻算：(電池到 VP 之間的電阻總和 + VP 到 GND 的電阻) / VP 到 GND 的電阻。
// 目前接線：電池+ → 10k → 10k → VP → 10k → GND，比值 = 30k / 10k = 3.0（滿電 8.4V 時 VP ≈ 2.8V）。
const float BATTERY_DIVIDER_RATIO = 3.0f;
const float BATTERY_EMPTY_V = 6.0f;  // 2S Li-ion 預設低壓保護值
const float BATTERY_FULL_V = 8.4f;  // 2S Li-ion 滿電電壓
const float BATTERY_PRESENT_MIN_V = 3.0f;  // 換算後低於此值視為沒接電池 / VP 空接
const int BATTERY_SAMPLE_COUNT = 16;  // 每次取樣平均次數，降低 ADC 雜訊
const float BATTERY_SMOOTHING_ALPHA = 0.2f;  // 電壓指數平滑係數，避免 % 數跳動

const float SENSOR_X_POS[SENSOR_COUNT] = {0.82f, 0.82f, 0.82f, 0.50f, 0.50f, 0.18f, 0.18f, 0.18f, 0.35f, 0.50f, 0.65f};
const float SENSOR_Y_POS[SENSOR_COUNT] = {0.18f, 0.42f, 0.72f, 0.18f, 0.72f, 0.72f, 0.42f, 0.18f, 0.10f, 0.05f, 0.10f};
const int SEAT_SENSOR_COUNT = 8;  // S1~S8 為坐墊，S9~S11 為椅背，重心只看坐墊
// 重心落在「中立點」半徑 POSE_NORMAL_RADIUS 內（demo 的綠環）判定為 normal，超出則依偏移最大的方向判定。
// 中立點 = 坐墊 8 顆感測器平均受力時的重心（座標平均值），於 setup() 計算。
const float POSE_NORMAL_RADIUS = 0.07f;
float poseNeutralX = 0.5f;
float poseNeutralY = 0.5f;
const unsigned long BAD_POSTURE_FIRST_ALERT_MS = 10000UL;
const unsigned long BAD_POSTURE_SECOND_ALERT_MS = 25000UL;
const unsigned long BAD_POSTURE_THIRD_ALERT_MS = 45000UL;
const unsigned long BAD_POSTURE_REPEAT_MS = 30000UL;
const unsigned long POSE_CONFIRM_MS = 2000UL;
const unsigned long SEDENTARY_REMINDER_MS = 1800000UL;  // 30 分鐘

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);

Adafruit_ADS1115 ads1;  // 位址 0x48，ADDR 接 GND
Adafruit_ADS1115 ads2;  // 位址 0x49，ADDR 接 3V3
Adafruit_ADS1115 ads3;  // 位址 0x4A，ADDR 接 SDA（預留）

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

float batteryFilteredV = -1.0f;

struct BatteryReading {
  int raw;            // VP 平均 ADC 原始值
  float pinVoltage;   // VP 腳實際電壓（已用晶片校正）
  float voltage;      // 換算回分壓前的電池電壓（平滑後）
  int pct;            // 電量百分比 0~100
  bool present;       // 是否偵測到電池
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

struct PostureSummary {
  float totalPressure;
  float leftTotal;
  float rightTotal;
  float frontTotal;
  float backTotal;
  float leftRightBalance;
  float frontBackBalance;
  float centerX;
  float centerY;
  float stability;
  String label;
  float confidence;
};

MotorRuntime motors[MOTOR_COUNT];
unsigned long lastPoseUpdateMs = 0;
unsigned long lastGoodPoseMs = 0;
unsigned long badPoseStartMs = 0;
unsigned long lastSedentaryReminderMs = 0;
String lastPoseLabel = "normal";
int lastReminderLevel = 0;
unsigned long lastReminderAtMs = 0;

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

void computePoseNeutralPoint() {
  float sumX = 0.0f;
  float sumY = 0.0f;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) {
    sumX += SENSOR_X_POS[i];
    sumY += SENSOR_Y_POS[i];
  }
  poseNeutralX = sumX / SEAT_SENSOR_COUNT;
  poseNeutralY = sumY / SEAT_SENSOR_COUNT;
}

// 依重心相對中立點的偏移判定姿勢。座標：x 小 = 左、y 小 = 後（靠椅背）、y 大 = 前。
String decidePoseLabel(float offsetX, float offsetY, float totalPressure) {
  if (totalPressure < 8.0f) return "no_occupancy";
  if (sqrtf(offsetX * offsetX + offsetY * offsetY) < POSE_NORMAL_RADIUS) return "normal";
  if (fabs(offsetX) >= fabs(offsetY)) {
    return (offsetX < 0.0f) ? "left_lean" : "right_lean";
  }
  return (offsetY > 0.0f) ? "forward_lean" : "backward_lean";
}

// normalized[] 為 0-based：normalized[0] = S1 ... normalized[7] = S8
PostureSummary computePostureSummary(const int normalized[]) {
  PostureSummary summary;
  summary.totalPressure = 0.0f;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) {
    summary.totalPressure += normalized[i];
  }

  summary.leftTotal = normalized[5] + normalized[6] + normalized[7];   // S6 S7 S8
  summary.rightTotal = normalized[0] + normalized[1] + normalized[2];  // S1 S2 S3
  summary.frontTotal = normalized[2] + normalized[4] + normalized[5];  // S3 S5 S6
  summary.backTotal = normalized[0] + normalized[3] + normalized[7];   // S1 S4 S8

  // < 0 偏左 / > 0 偏右
  float denom = max(summary.leftTotal + summary.rightTotal, 1.0f);
  summary.leftRightBalance = (summary.rightTotal - summary.leftTotal) / denom;

  // < 0 偏前 / > 0 偏後
  float fbDenom = max(summary.frontTotal + summary.backTotal, 1.0f);
  summary.frontBackBalance = (summary.backTotal - summary.frontTotal) / fbDenom;

  float xNumer = 0.0f;
  float yNumer = 0.0f;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) {
    float value = (float)normalized[i];
    xNumer += value * SENSOR_X_POS[i];
    yNumer += value * SENSOR_Y_POS[i];
  }
  summary.centerX = (summary.totalPressure > 0.0f) ? xNumer / summary.totalPressure : poseNeutralX;
  summary.centerY = (summary.totalPressure > 0.0f) ? yNumer / summary.totalPressure : poseNeutralY;

  float offsetX = summary.centerX - poseNeutralX;
  float offsetY = summary.centerY - poseNeutralY;
  float offset = sqrtf(offsetX * offsetX + offsetY * offsetY);
  // 偏移達綠環半徑 3 倍（demo 最外圈）時穩定度歸零
  summary.stability = clampFloat(1.0f - offset / (POSE_NORMAL_RADIUS * 3.0f), 0.0f, 1.0f);

  summary.label = decidePoseLabel(offsetX, offsetY, summary.totalPressure);
  summary.confidence = summary.stability;
  return summary;
}

bool triggerMotorReminderByPose(const String& postureLabel, int reminderLevel) {
  if (postureLabel == "no_occupancy" || postureLabel == "normal") {
    return false;
  }

  unsigned long nowMs = millis();
  if ((nowMs - lastReminderAtMs) < BAD_POSTURE_REPEAT_MS) {
    return false;
  }

  int intensity = 28;
  int durationMs = 120;
  if (reminderLevel == 2) {
    intensity = 42;
    durationMs = 170;
  } else if (reminderLevel >= 3) {
    intensity = 60;
    durationMs = 220;
  }

  stopAllMotors();

  if (postureLabel == "left_lean") {
    scheduleSingleCommand(3, intensity, durationMs, 0, 0);
    scheduleSingleCommand(4, intensity, durationMs, 1, 0);
  } else if (postureLabel == "right_lean") {
    scheduleSingleCommand(1, intensity, durationMs, 0, 0);
    scheduleSingleCommand(2, intensity, durationMs, 1, 0);
  } else if (postureLabel == "forward_lean") {
    scheduleSingleCommand(1, intensity, durationMs, 0, 0);
    scheduleSingleCommand(4, intensity, durationMs, 1, 0);
  } else if (postureLabel == "backward_lean") {
    scheduleSingleCommand(2, intensity, durationMs, 0, 0);
    scheduleSingleCommand(3, intensity, durationMs, 1, 0);
  }

  lastReminderLevel = reminderLevel;
  lastReminderAtMs = nowMs;
  return true;
}

void evaluatePoseReminder(const PostureSummary& summary, unsigned long nowMs) {
  if (summary.label == "normal" || summary.label == "no_occupancy") {
    lastGoodPoseMs = nowMs;
    badPoseStartMs = 0;
    lastReminderLevel = 0;
    lastReminderAtMs = 0;
    lastPoseLabel = "normal";
    return;
  }

  if (badPoseStartMs == 0) {
    badPoseStartMs = nowMs;
    lastPoseLabel = summary.label;
    return;
  }

  if (summary.label != lastPoseLabel) {
    lastPoseLabel = summary.label;
    badPoseStartMs = nowMs;
    return;
  }

  if (nowMs - badPoseStartMs < BAD_POSTURE_FIRST_ALERT_MS) {
    return;
  }

  unsigned long badPoseDuration = nowMs - badPoseStartMs;
  int reminderLevel = 0;
  if (badPoseDuration >= BAD_POSTURE_THIRD_ALERT_MS) {
    reminderLevel = 3;
  } else if (badPoseDuration >= BAD_POSTURE_SECOND_ALERT_MS) {
    reminderLevel = 2;
  } else if (badPoseDuration >= BAD_POSTURE_FIRST_ALERT_MS) {
    reminderLevel = 1;
  }

  if (reminderLevel > 0) {
    triggerMotorReminderByPose(summary.label, reminderLevel);
    publishMotorStatus("posture_reminder", summary.label.c_str());
  }
}

float clampFloat(float value, float minValue, float maxValue) {
  if (value < minValue) return minValue;
  if (value > maxValue) return maxValue;
  return value;
}

int voltageToBatteryPercent(float batteryVoltage) {
  float ratio = (batteryVoltage - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V);
  ratio = clampFloat(ratio, 0.0f, 1.0f);
  return (int)(ratio * 100.0f + 0.5f);
}

BatteryReading readBattery() {
  long rawSum = 0;
  long milliVoltSum = 0;
  for (int i = 0; i < BATTERY_SAMPLE_COUNT; i++) {
    rawSum += analogRead(BATTERY_VP_PIN);
    // analogReadMilliVolts 會套用晶片出廠校正，比 raw/4095*3.3 準確
    milliVoltSum += analogReadMilliVolts(BATTERY_VP_PIN);
  }

  BatteryReading reading;
  reading.raw = (int)(rawSum / BATTERY_SAMPLE_COUNT);
  reading.pinVoltage = (milliVoltSum / (float)BATTERY_SAMPLE_COUNT) / 1000.0f;

  // 1. 先換算回分壓前的電池電壓
  float packVoltage = reading.pinVoltage * BATTERY_DIVIDER_RATIO;
  reading.present = packVoltage >= BATTERY_PRESENT_MIN_V;
  if (!reading.present) {
    batteryFilteredV = -1.0f;
    reading.voltage = packVoltage;
    reading.pct = 0;
    return reading;
  }

  // 2. 平滑電壓，避免馬達震動等負載造成 % 數跳動
  if (batteryFilteredV < 0.0f) {
    batteryFilteredV = packVoltage;
  } else {
    batteryFilteredV = batteryFilteredV * (1.0f - BATTERY_SMOOTHING_ALPHA) + packVoltage * BATTERY_SMOOTHING_ALPHA;
  }
  reading.voltage = batteryFilteredV;

  // 3. 與滿電 / 沒電電壓比較，換算 %
  reading.pct = voltageToBatteryPercent(reading.voltage);
  return reading;
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

void setupArduinoOTA() {
  ArduinoOTA.setHostname(OTA_HOSTNAME);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() {
    String type = (ArduinoOTA.getCommand() == U_FLASH) ? "sketch" : "filesystem";
    Serial.println("OTA 開始更新: " + type);
  });
  ArduinoOTA.onEnd([]() {
    Serial.println("\nOTA 更新完成");
  });
  ArduinoOTA.onProgress([](unsigned int progress, unsigned int total) {
    Serial.printf("OTA 進度: %u%%\r", (progress / (total == 0 ? 1 : total)) * 100);
  });
  ArduinoOTA.onError([](ota_error_t error) {
    Serial.printf("OTA 錯誤[%u]: ", error);
    if (error == OTA_AUTH_ERROR) Serial.println("Auth Failed");
    else if (error == OTA_BEGIN_ERROR) Serial.println("Begin Failed");
    else if (error == OTA_CONNECT_ERROR) Serial.println("Connect Failed");
    else if (error == OTA_RECEIVE_ERROR) Serial.println("Receive Failed");
    else if (error == OTA_END_ERROR) Serial.println("End Failed");
  });
  ArduinoOTA.begin();
  Serial.println("OTA 已啟用，主機名: " + String(OTA_HOSTNAME));
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

String buildPayload(const int raw[], const int normalized[], const PostureSummary& pose, unsigned long ts, const BatteryReading& battery) {
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

  payload += "],\"pose\":{";
  payload += "\"label\":\"" + pose.label + "\",";
  payload += "\"left_right_balance\":" + String(pose.leftRightBalance, 3) + ",";
  payload += "\"front_back_balance\":" + String(pose.frontBackBalance, 3) + ",";
  payload += "\"center_x\":" + String(pose.centerX, 3) + ",";
  payload += "\"center_y\":" + String(pose.centerY, 3) + ",";
  payload += "\"neutral_x\":" + String(poseNeutralX, 3) + ",";
  payload += "\"neutral_y\":" + String(poseNeutralY, 3) + ",";
  payload += "\"normal_radius\":" + String(POSE_NORMAL_RADIUS, 3) + ",";
  payload += "\"stability\":" + String(pose.stability, 3) + ",";
  payload += "\"confidence\":" + String(pose.confidence, 3) + ",";
  payload += "\"total_pressure\":" + String(pose.totalPressure, 1) + ",";
  payload += "\"left_total\":" + String(pose.leftTotal, 1) + ",";
  payload += "\"right_total\":" + String(pose.rightTotal, 1) + ",";
  payload += "\"front_total\":" + String(pose.frontTotal, 1) + ",";
  payload += "\"back_total\":" + String(pose.backTotal, 1) + "}";

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

  payload += "],\"sensor_state\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) payload += ",";
    payload += "\"";
    payload += getSensorStateText(i, nowMs);
    payload += "\"";
  }

  payload += "],\"power\":{";
  payload += "\"pin\":\"VP(GPIO36)\",";
  payload += "\"raw\":";
  payload += String(battery.raw);
  payload += ",\"vp_v\":";
  payload += String(battery.pinVoltage, 3);
  payload += ",\"voltage_v\":";
  payload += String(battery.voltage, 3);
  payload += ",\"battery_pct\":";
  payload += String(battery.pct);
  payload += ",\"battery_present\":";
  payload += battery.present ? "true" : "false";
  payload += "}}";
  return payload;
}

void setup() {
  Serial.begin(115200);
  delay(800); 
  Serial.println("\n--- 🚀 智慧感測椅系統開機 ---");

  // 初始化外接指示燈腳位
  pinMode(DETECT_LED_PIN, OUTPUT);
  digitalWrite(DETECT_LED_PIN, LOW); 

  computePoseNeutralPoint();

  // VP 監測外接電源電量（GPIO36）
  analogReadResolution(12);
  analogSetPinAttenuation(BATTERY_VP_PIN, ADC_11db);

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
  setupArduinoOTA();
  wifiClient.setInsecure();  
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(1024);
  connectMQTT();

  lastValidMotorCmdMs = millis();
  lastMotorStateMs = millis();
}

void loop() {
  ArduinoOTA.handle();

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
  for (int i = 0; i < SENSOR_COUNT; i++) {
    raw[i] = 0;
    normalized[i] = 0;
  }

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

  BatteryReading battery = readBattery();

  PostureSummary pose = computePostureSummary(normalized);
  evaluatePoseReminder(pose, millis());

  // 打包 MQTT JSON 封包
  unsigned long ts = (unsigned long)(millis() / 1000);
  String payload = buildPayload(raw, normalized, pose, ts, battery);
  mqttClient.publish(MQTT_TOPIC_SENSOR, payload.c_str());
  Serial.println(payload);
}