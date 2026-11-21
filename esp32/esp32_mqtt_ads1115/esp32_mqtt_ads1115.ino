// 智慧感測椅 ESP32 韌體 v2
// 架構：
//   Core 1（Arduino loop）：感測器取樣 → 坐姿判斷 → 震動提醒 → 久坐計時 → LED 燈條。完全不等網路。
//   Core 0（netTask）    ：WiFi / MQTT 連線、送出資料、接收指令。斷線卡住也不影響 Core 1。
//   兩邊用 FreeRTOS queue 交換資料，所有馬達 / 姿勢狀態只由 Core 1 修改。
// 資料格式說明見 ../../MQTT資料說明.md

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>
#include <Adafruit_NeoPixel.h>
#include <ArduinoJson.h>
#include <ArduinoOTA.h>
#include <esp_mac.h>
#include <time.h>
#include "secrets.h"

const char* FW_VERSION = "2.0.0";

// 1 = pressure 封包附帶 raw，並在序列埠印出（重新量測 adcMin / adcMax 時使用）
#define DEBUG_RAW 0

// ───────────────────────── 久坐 / 提醒設定 ─────────────────────────
const uint32_t SITTING_LIMIT_MIN = 30;                       // 久坐上限（分鐘），後端需用同一個值
const uint32_t SITTING_LIMIT_MS = SITTING_LIMIT_MIN * 60000UL;
const uint32_t SEDENTARY_REPEAT_MS = 5UL * 60000UL;          // 久坐提醒後仍未起身，每 5 分鐘再提醒
const uint32_t LEAVE_RESET_MS = 30000UL;                     // 連續 30 秒沒人坐才算真的起身離開（計時歸零）
// 震動強度一律 100%（震動馬達低於約 50% 常常轉不起來、短於 0.3 秒幾乎感覺不到），不同情境用「震動時長」區分
const int REMINDER_INTENSITY = 100;
const int POSTURE_DURATION_MS[3] = {400, 700, 1000};   // 壞坐姿提醒第 1 / 2 / 3 級
const int SEDENTARY_INTENSITY = REMINDER_INTENSITY;
const int SEDENTARY_DURATION_MS = 1500;                 // 久坐提醒：四顆一起震 1.5 秒
const int SEDENTARY_STAGGER_MS = 80;

const uint32_t BAD_POSTURE_FIRST_ALERT_MS = 10000UL;
const uint32_t BAD_POSTURE_SECOND_ALERT_MS = 25000UL;
const uint32_t BAD_POSTURE_THIRD_ALERT_MS = 45000UL;
const uint32_t BAD_POSTURE_REPEAT_MS = 30000UL;

// ───────────────────────── 取樣 / 判斷設定 ─────────────────────────
const uint32_t SAMPLE_INTERVAL_MS = 40;       // 25 Hz 取樣
const int SMOOTH_N = 5;                       // 每顆感測器取最近 5 筆平均（約 0.2 秒）
const uint32_t POSE_CONFIRM_MS = 1000UL;      // 姿勢需連續 1 秒相同才更新 label
const float OCCUPANCY_MIN_TOTAL = 8.0f;       // S1~S8 norm 總和低於此值 = 沒人坐

// ───────────────────────── 傳送規則 ─────────────────────────
const uint32_t PUBLISH_MIN_GAP_MS = 500;      // 兩筆 pressure 至少間隔 0.5 秒
const uint32_t SYNC_INTERVAL_MS = 5000;       // 有人坐：5 秒沒變動也送一筆 sync
const uint32_t SYNC_INTERVAL_EMPTY_MS = 30000;// 沒人坐：30 秒一筆
const int CHANGE_NORM_DELTA = 10;             // 任一感測器 norm 變化 ≥ 10 視為變動
const float CHANGE_CENTER_DELTA = 0.035f;     // 重心移動 ≥ 0.035（綠環半徑一半）視為變動；設 0 = 關閉此條件
const uint32_t POWER_MAX_GAP_MS = 30000;      // 一直有變動時，最多 30 秒也要帶一次 power
const uint32_t MOTOR_STATE_HEARTBEAT_MS = 30000;

// ───────────────────────── 網路 ─────────────────────────
const uint32_t WIFI_RETRY_MS = 20000;
const uint32_t MQTT_RETRY_MS = 5000;
const uint16_t MQTT_BUFFER_SIZE = 1024;
const uint16_t MQTT_KEEPALIVE_S = 15;

// ───────────────────────── 腳位 ─────────────────────────
const int DETECT_LED_PIN = 2;      // 板上 / 外接指示燈：開機閃 ADS 數量；之後常亮 = 已連線、閃爍 = 離線
const int LED_PIN_RIGHT = 18;      // 右扶手燈條資料線
const int LED_PIN_LEFT = 19;       // 左扶手燈條資料線
const int LEDS_PER_STRIP = 35;     // 每條燈珠數（依實物修改）

const int SENSOR_COUNT = 11;
const int SEAT_SENSOR_COUNT = 8;   // S1~S8 坐墊，S9~S11 椅背；左右重心只看坐墊，前後重心含椅背
const int MOTOR_COUNT = 4;
// M1 右扶手、M2 右靠背（腰部）、M3 左靠背（腰部）、M4 左扶手
const int MOTOR_PINS[MOTOR_COUNT] = {14, 27, 26, 25};
const int MOTOR_PWM_CHANNELS[MOTOR_COUNT] = {0, 1, 2, 3};
const int MOTOR_PWM_FREQ = 250;
const int MOTOR_PWM_RESOLUTION = 8;
const int MOTOR_INTENSITY_MAX = 100;
const int MOTOR_DURATION_MIN_MS = 50;
const int MOTOR_DURATION_MAX_MS = 5000;
const int MOTOR_STAGGER_DEFAULT_MS = 80;
const int MOTOR_STAGGER_MAX_MS = 500;
const uint32_t MOTOR_SAFETY_MAX_ON_MS = MOTOR_DURATION_MAX_MS + 1000;  // 單顆連續開超過這麼久 = 異常，強制停機

const int SENSOR_SIGNAL_THRESHOLD_RAW = 120;
const int SENSOR_NOISE_BAND_RAW = 40;
const uint32_t SENSOR_DETECT_WINDOW_MS = 15000;

// ───────────────────────── LED 燈條 ─────────────────────────
// 顏色 = 久坐程度（綠 → 琥珀 → 紅，紅綠兩色總量固定，電流不會在中段變兩倍）
//   滿 SITTING_LIMIT_MIN 時跟馬達一起紅色閃爍 10 秒，之後維持紅色常亮；
//   每次 5 分鐘重複提醒震動時，再一起閃 10 秒
// 耗電：每顆燈任何時刻只用到紅＋綠合計一個通道的量（約 20 mA × 實際輸出%），35 顆 × 2 條：基準（實際 25%）約 0.4 A、最亮（實際 64%）約 1.0 A
// 亮度 = 重心偏移方向：基準 50%，範圍 20% ~ 80%
//   左右：偏左時左扶手整條變亮、右扶手變暗
//   前後：燈條中段 = 扶手前端，兩端 = 扶手後端；前傾時中段變亮，後傾時兩端變亮
//   兩者疊加，例如左前傾：左扶手中段 80%、右扶手中段與左扶手兩端約 50%、右扶手兩端 20%
const int LED_MIN_PCT = 20;
const int LED_BASE_PCT = 50;
const int LED_MAX_PCT = 80;
const float LED_LEAN_FULL_RADII = 1.0f;   // 重心偏移達綠環半徑（剛好判定為傾斜）時亮度到極限；嫌太敏感可調大
const float LED_GAMMA = 2.0f;             // 亮度百分比 → 實際 PWM 用 gamma 修正，人眼才看得出 20/50/80% 的差別
const float LED_SMOOTH_ALPHA = 0.3f;      // 亮度變化平滑，避免閃動
const uint32_t LED_UPDATE_MS = 100;       // 10 Hz 更新，畫面沒變就不送資料給燈條
const uint32_t LED_ALERT_BLINK_MS = 500;           // 閃爍時紅色亮 0.5 秒、暗 0.5 秒
const uint32_t LED_ALERT_BLINK_DURATION_MS = 10000;  // 每次久坐提醒閃 10 秒，之後紅色常亮

// ───────────────────────── 電池 ─────────────────────────
const int BATTERY_VP_PIN = 36;  // VP = GPIO36 (ADC1_CH0)
// 目前接線：電池+ → 10k → 10k → VP → 10k → GND，比值 = 30k / 10k = 3.0（滿電 8.4V 時 VP ≈ 2.8V）。
const float BATTERY_DIVIDER_RATIO = 3.0f;
const float BATTERY_EMPTY_V = 6.0f;
const float BATTERY_FULL_V = 8.4f;
const float BATTERY_PRESENT_MIN_V = 3.0f;
const int BATTERY_SAMPLE_COUNT = 16;
const float BATTERY_SMOOTHING_ALPHA = 0.2f;
const uint32_t BATTERY_READ_INTERVAL_MS = 1000;

// ───────────────────────── 感測器座標 ─────────────────────────
const float SENSOR_X_POS[SENSOR_COUNT] = {0.82f, 0.82f, 0.82f, 0.50f, 0.50f, 0.18f, 0.18f, 0.18f, 0.35f, 0.50f, 0.65f};
const float SENSOR_Y_POS[SENSOR_COUNT] = {0.18f, 0.42f, 0.72f, 0.18f, 0.72f, 0.72f, 0.42f, 0.18f, 0.10f, 0.05f, 0.10f};
const bool SENSOR_ACTIVE[SENSOR_COUNT] = {true, true, true, true, true, true, true, true, true, true, true};
// 坐墊感測器直接貼椅面、上蓋坐墊；椅背感測器加凸墊。更換安裝方式後需重新量測（DEBUG_RAW 設 1 看 raw）
int adcMin[SENSOR_COUNT] = {2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400};
// S9~S11（椅背）背後沒有支撐、受力小，adcMax 先調低讓輕靠也有讀值（暫定 8000，約 3 倍靈敏；量到實際 raw 後再改）
// 加裝凸點後：S9、S11 不需那麼敏感（14000），S10（中間）較難受力，再調敏感（5000）
int adcMax[SENSOR_COUNT] = {20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500, 14000, 5000, 14000};

// ───────────────────────── 中立點 ─────────────────────────
const float DEFAULT_NORMAL_RADIUS = 0.055f;  // 綠環（正常範圍）半徑；原 0.07 實測範圍太大
// 前後方向：往後靠時重量會壓到椅背，坐墊重心幾乎不動，所以前後重心把椅背 S9~S11 也算進去
const float BACKREST_Y_WEIGHT = 1.5f;      // 椅背壓力在前後重心的權重；0 = 只看坐墊（舊做法）
// 各方向的判定範圍 = 綠環半徑 × 倍率；倍率越小越容易判定（越鬆），越大越嚴格
const float BACKWARD_RADIUS_SCALE = 0.6f;  // 後仰
const float LATERAL_RADIUS_SCALE = 0.8f;   // 左右傾
const float FORWARD_RADIUS_SCALE = 1.1f;   // 前傾
const float CALIB_STABLE_RADIUS = 0.035f;  // 校正時重心需在平均位置 0.035 內
const int CALIB_STABLE_PCT = 95;           // 至少 95% 的取樣要在範圍內
const int CALIB_MAX_SAMPLES = 250;         // 10 秒 × 25 Hz

// ═════════════════════════ 型別 ═════════════════════════
enum PoseLabel : uint8_t { POSE_EMPTY, POSE_NORMAL, POSE_LEFT, POSE_RIGHT, POSE_FORWARD, POSE_BACKWARD };
const char* POSE_NAMES[] = {"no_occupancy", "normal", "left_lean", "right_lean", "forward_lean", "backward_lean"};

struct PostureSummary {
  float totalPressure, leftTotal, rightTotal, frontTotal, backTotal;
  float leftRightBalance, frontBackBalance;
  float centerX, centerY, stability, confidence;
  PoseLabel label;
};

struct MotorRuntime {
  bool running;
  bool scheduled;
  int intensity;
  uint32_t startAtMs;
  uint32_t stopAtMs;
};

struct BatteryReading {
  int raw;
  float pinVoltage;
  float voltage;
  int pct;
  bool present;
};

enum OutTopic : uint8_t { OT_PRESSURE, OT_STATE, OT_STATUS, OT_ACK };
struct OutMsg { uint8_t topic; char* payload; };
enum InKind : uint8_t { IN_VIB_CMD, IN_CONFIG, IN_CALIB };
struct InMsg { uint8_t kind; char* payload; };

// ═════════════════════════ 全域狀態 ═════════════════════════
char deviceId[20];       // chair_A1B2C3
char mqttClientId[24];   // esp32-A1B2C3
char otaHostname[24];    // chair-a1b2c3
char topicPressure[64], topicVibState[64], topicVibStatus[64], topicVibAck[64], topicVibCmd[64];
char topicConfig[64], topicCalibCmd[64], topicOnline[64];
char willPayload[96];

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);

QueueHandle_t telemetryQ;  // pressure / state：滿了丟最舊的（舊資料沒意義）
QueueHandle_t eventQ;      // status / ack：斷線期間保留，連線後補送
QueueHandle_t inQ;         // MQTT 收到的指令 → Core 1 執行

volatile bool netOnline = false;
volatile bool needBootReport = false;
volatile bool otaInProgress = false;

Adafruit_ADS1115 ads1;  // 0x48
Adafruit_ADS1115 ads2;  // 0x49
Adafruit_ADS1115 ads3;  // 0x4A
bool ads1_available = false, ads2_available = false, ads3_available = false;

bool sensorSeenSignal[SENSOR_COUNT];
int sensorMinRaw[SENSOR_COUNT];
int sensorMaxRaw[SENSOR_COUNT];
uint32_t sensorDetectStartMs = 0;
uint8_t lastReportedSensorState[SENSOR_COUNT];
uint32_t lastSensorStateCheckMs = 0;

int rawHist[SENSOR_COUNT][SMOOTH_N];
int histPos = 0, histFill = 0;
int rawAvg[SENSOR_COUNT];
int normNow[SENSOR_COUNT];

float geometricNeutralX = 0.5f, geometricNeutralY = 0.4425f;
float poseNeutralX = 0.5f, poseNeutralY = 0.4425f, poseNormalRadius = DEFAULT_NORMAL_RADIUS;
bool hasFleetNeutral = false;
float fleetNeutralX = 0, fleetNeutralY = 0, fleetNormalRadius = DEFAULT_NORMAL_RADIUS;
bool neutralIsUser = false;

PostureSummary poseNow;
PoseLabel candidatePose = POSE_EMPTY, stablePose = POSE_EMPTY;
uint32_t candidateSinceMs = 0;

PoseLabel badPoseLabel = POSE_NORMAL;
uint32_t badPoseStartMs = 0;
bool badPoseTiming = false;
bool hasRemindedThisBout = false;
uint32_t lastReminderAtMs = 0;
uint32_t postureHoldUntilMs = 0;
bool postureHoldActive = false;

bool sitting = false;
uint32_t sitStartMs = 0;
bool emptyPending = false;
uint32_t emptySinceMs = 0;
bool sedentaryAlert = false;
uint32_t lastSedentaryMs = 0;
uint32_t ledBlinkUntilMs = 0;  // 久坐提醒閃爍到什麼時候

struct {
  bool active;
  char requestId[64];
  uint32_t endMs;
  int n, empty;
  float cx[CALIB_MAX_SAMPLES], cy[CALIB_MAX_SAMPLES];
  long normSum[SENSOR_COUNT];
} calib;

MotorRuntime motors[MOTOR_COUNT];
uint32_t motorOnSinceMs[MOTOR_COUNT];
uint32_t lastMotorStateMs = 0;

float batteryFilteredV = -1.0f;
BatteryReading battery = {0, 0, 0, 0, false};
uint32_t lastBatteryReadMs = 0;

uint32_t pressureSeq = 0;
bool hasSentPressure = false;
uint32_t lastPressureSentMs = 0, lastPowerSentMs = 0;
PoseLabel lastSentPose = POSE_EMPTY;
int lastSentNorm[SENSOR_COUNT];
float lastSentCenterX = 0, lastSentCenterY = 0;

uint32_t lastSampleMs = 0;

Adafruit_NeoPixel stripRight(LEDS_PER_STRIP, LED_PIN_RIGHT, NEO_GRB + NEO_KHZ800);
Adafruit_NeoPixel stripLeft(LEDS_PER_STRIP, LED_PIN_LEFT, NEO_GRB + NEO_KHZ800);
float ledPos[LEDS_PER_STRIP];        // -1 = 燈條兩端（扶手後端），+1 = 中段（扶手前端）
uint32_t ledFrameL[LEDS_PER_STRIP], ledFrameR[LEDS_PER_STRIP];
bool ledFrameValid = false;
float ledLeanLeft = 0, ledLeanFront = 0;
uint32_t lastLedMs = 0;

// ═════════════════════════ 小工具 ═════════════════════════
int clampInt(int v, int lo, int hi) { return v < lo ? lo : (v > hi ? hi : v); }
float clampFloat(float v, float lo, float hi) { return v < lo ? lo : (v > hi ? hi : v); }
bool timeReached(uint32_t now, uint32_t target) { return (int32_t)(now - target) >= 0; }

bool timeSynced() { return time(nullptr) > 1700000000; }

// 所有訊息共通開頭：device_id + ts（NTP 對時成功為 Unix 秒，否則為開機秒數並標 time_synced:false）
String msgHead() {
  String s;
  s.reserve(160);
  s = "{\"device_id\":\"";
  s += deviceId;
  s += "\",\"ts\":";
  if (timeSynced()) {
    s += String((unsigned long)time(nullptr));
  } else {
    s += String((unsigned long)(millis() / 1000));
    s += ",\"time_synced\":false";
  }
  return s;
}

const char* topicFor(uint8_t t) {
  switch (t) {
    case OT_PRESSURE: return topicPressure;
    case OT_STATE: return topicVibState;
    case OT_ACK: return topicVibAck;
    default: return topicVibStatus;
  }
}

// telemetry：滿了丟最舊；event：滿了丟最新（避免與 netTask 讀取競爭）
void enqueueOut(uint8_t topic, const String& s) {
  char* p = strdup(s.c_str());
  if (!p) return;
  OutMsg m = {topic, p};
  bool isEvent = (topic == OT_STATUS || topic == OT_ACK);
  QueueHandle_t q = isEvent ? eventQ : telemetryQ;
  if (xQueueSend(q, &m, 0) == pdTRUE) return;
  if (!isEvent) {
    OutMsg old;
    if (xQueueReceive(q, &old, 0) == pdTRUE) free(old.payload);
    if (xQueueSend(q, &m, 0) == pdTRUE) return;
  }
  free(p);
}

void sendStatusEvent(const char* eventName, const String& extra) {
  String s = msgHead();
  s += ",\"event\":\"";
  s += eventName;
  s += "\"";
  s += extra;
  s += "}";
  enqueueOut(OT_STATUS, s);
}

String jsonStr(const char* key, const char* value) {
  String s = ",\"";
  s += key;
  s += "\":\"";
  s += value;
  s += "\"";
  return s;
}

// ═════════════════════════ 馬達 ═════════════════════════
#if defined(ESP_ARDUINO_VERSION_MAJOR) && (ESP_ARDUINO_VERSION_MAJOR >= 3)
void pwmAttachMotor(int i) { ledcAttach(MOTOR_PINS[i], MOTOR_PWM_FREQ, MOTOR_PWM_RESOLUTION); }
void pwmWriteMotor(int i, int duty) { ledcWrite(MOTOR_PINS[i], duty); }
#else
void pwmAttachMotor(int i) {
  ledcSetup(MOTOR_PWM_CHANNELS[i], MOTOR_PWM_FREQ, MOTOR_PWM_RESOLUTION);
  ledcAttachPin(MOTOR_PINS[i], MOTOR_PWM_CHANNELS[i]);
}
void pwmWriteMotor(int i, int duty) { ledcWrite(MOTOR_PWM_CHANNELS[i], duty); }
#endif

void setMotorOutput(int i, int intensity) {
  pwmWriteMotor(i, map(clampInt(intensity, 0, MOTOR_INTENSITY_MAX), 0, MOTOR_INTENSITY_MAX, 0, 255));
}

void stopMotor(int i) {
  setMotorOutput(i, 0);
  motors[i].running = false;
  motors[i].scheduled = false;
  motors[i].intensity = 0;
}

void stopAllMotors() {
  for (int i = 0; i < MOTOR_COUNT; i++) stopMotor(i);
}

bool scheduleSingleCommand(int motorId, int intensity, int durationMs, int order, int staggerMs) {
  if (motorId < 1 || motorId > MOTOR_COUNT) return false;
  int i = motorId - 1;
  uint32_t now = millis();
  motors[i].running = false;
  motors[i].scheduled = true;
  motors[i].intensity = clampInt(intensity, 0, MOTOR_INTENSITY_MAX);
  motors[i].startAtMs = now + (uint32_t)(order * staggerMs);
  motors[i].stopAtMs = motors[i].startAtMs + (uint32_t)clampInt(durationMs, MOTOR_DURATION_MIN_MS, MOTOR_DURATION_MAX_MS);
  setMotorOutput(i, 0);
  return true;
}

bool updateMotorStateMachine(uint32_t now) {
  bool changed = false;
  for (int i = 0; i < MOTOR_COUNT; i++) {
    if (motors[i].scheduled && !motors[i].running && timeReached(now, motors[i].startAtMs)) {
      setMotorOutput(i, motors[i].intensity);
      motors[i].running = true;
      motors[i].scheduled = false;
      motorOnSinceMs[i] = now;
      changed = true;
    }
    if (motors[i].running && timeReached(now, motors[i].stopAtMs)) {
      stopMotor(i);
      changed = true;
    }
  }
  return changed;
}

void publishMotorState(const char* eventName, const char* cmdId) {
  uint32_t now = millis();
  String s = msgHead();
  s += jsonStr("event", eventName);
  s += jsonStr("cmd_id", cmdId);
  s += ",\"motors\":[";
  for (int i = 0; i < MOTOR_COUNT; i++) {
    uint32_t remaining = (motors[i].running && !timeReached(now, motors[i].stopAtMs)) ? motors[i].stopAtMs - now : 0;
    if (i > 0) s += ",";
    s += "{\"id\":" + String(i + 1) + ",\"pin\":" + String(MOTOR_PINS[i]);
    s += ",\"running\":";
    s += motors[i].running ? "true" : "false";
    s += ",\"intensity\":" + String(motors[i].intensity);
    s += ",\"remaining_ms\":" + String(remaining) + "}";
  }
  s += "]}";
  enqueueOut(OT_STATE, s);
}

void publishMotorAck(const char* cmdId, const char* status, const char* message) {
  String s = msgHead();
  s += jsonStr("cmd_id", cmdId);
  s += jsonStr("status", status);
  s += jsonStr("message", message);
  s += "}";
  enqueueOut(OT_ACK, s);
}

// 後端手動震動指令（格式 A / B / C）
void handleMotorCommand(const char* text) {
  JsonDocument doc;
  if (deserializeJson(doc, text)) {
    publishMotorAck("no_cmd_id", "error", "invalid_json");
    return;
  }
  const char* cmdId = doc["cmd_id"] | "no_cmd_id";

  if (doc["stop_all"] == true) {
    stopAllMotors();
    publishMotorAck(cmdId, "ok", "all_motors_stopped");
    publishMotorState("stop_all", cmdId);
    return;
  }

  int staggerMs = clampInt((int)(doc["stagger_ms"] | (float)MOTOR_STAGGER_DEFAULT_MS), 0, MOTOR_STAGGER_MAX_MS);
  int scheduled = 0;

  JsonArrayConst arr = doc["motors"].as<JsonArrayConst>();
  if (!arr.isNull()) {
    for (JsonObjectConst m : arr) {
      if (scheduled >= MOTOR_COUNT) break;
      if (!m["id"].is<float>() || !m["intensity"].is<float>() || !m["duration_ms"].is<float>()) continue;
      if (scheduleSingleCommand((int)m["id"].as<float>(), (int)lroundf(m["intensity"].as<float>()),
                                (int)m["duration_ms"].as<float>(), scheduled, staggerMs)) {
        scheduled++;
      }
    }
  }

  if (scheduled == 0 && doc["motor_id"].is<float>() && doc["intensity"].is<float>() && doc["duration_ms"].is<float>()) {
    if (scheduleSingleCommand((int)doc["motor_id"].as<float>(), (int)lroundf(doc["intensity"].as<float>()),
                              (int)doc["duration_ms"].as<float>(), 0, staggerMs)) {
      scheduled = 1;
    }
  }

  if (scheduled == 0) {
    publishMotorAck(cmdId, "error", "no_valid_motor_command");
    return;
  }
  publishMotorAck(cmdId, "ok", "scheduled");
  publishMotorState("cmd_accepted", cmdId);
}

// ═════════════════════════ 感測器 ═════════════════════════
bool isSensorModuleAvailable(int i) {
  if (i < 4) return ads1_available;
  if (i < 8) return ads2_available;
  return ads3_available;
}

void updateSensorDetectionStats(int i, int raw) {
  if (!isSensorModuleAvailable(i)) return;
  if (raw < sensorMinRaw[i]) sensorMinRaw[i] = raw;
  if (raw > sensorMaxRaw[i]) sensorMaxRaw[i] = raw;
  if (raw >= SENSOR_SIGNAL_THRESHOLD_RAW) sensorSeenSignal[i] = true;
}

// 0 installed / 1 detecting / 2 not_installed / 3 not_detected
uint8_t getSensorStateCode(int i, uint32_t now) {
  if (!isSensorModuleAvailable(i)) return 3;
  if (sensorSeenSignal[i]) return 0;
  if (now - sensorDetectStartMs < SENSOR_DETECT_WINDOW_MS) return 1;
  int spread = sensorMaxRaw[i] - sensorMinRaw[i];
  if (sensorMaxRaw[i] < SENSOR_SIGNAL_THRESHOLD_RAW && spread <= SENSOR_NOISE_BAND_RAW) return 2;
  return 0;
}
const char* SENSOR_STATE_NAMES[] = {"installed", "detecting", "not_installed", "not_detected"};

String sensorArraysJson(uint32_t now) {
  String s = ",\"sensor_detected\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) s += ",";
    s += isSensorModuleAvailable(i) ? "true" : "false";
  }
  s += "],\"sensor_state\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) s += ",";
    s += "\"";
    s += SENSOR_STATE_NAMES[getSensorStateCode(i, now)];
    s += "\"";
  }
  s += "]";
  return s;
}

int readSensorRaw(int i) {
  if (!SENSOR_ACTIVE[i]) return 0;
  if (i < 4) return ads1_available ? ads1.readADC_SingleEnded(i) : 0;
  if (i < 8) return ads2_available ? ads2.readADC_SingleEnded(i - 4) : 0;
  return ads3_available ? ads3.readADC_SingleEnded(i - 8) : 0;
}

int normalizeTo100(int value, int vmin, int vmax) {
  if (vmax <= vmin) return 0;
  float ratio = clampFloat((float)(value - vmin) / (float)(vmax - vmin), 0.0f, 1.0f);
  return (int)(ratio * 100.0f + 0.5f);
}

void sampleSensors() {
  for (int i = 0; i < SENSOR_COUNT; i++) {
    int v = readSensorRaw(i);
    rawHist[i][histPos] = v;
    updateSensorDetectionStats(i, v);
  }
  histPos = (histPos + 1) % SMOOTH_N;
  if (histFill < SMOOTH_N) histFill++;

  for (int i = 0; i < SENSOR_COUNT; i++) {
    long sum = 0;
    for (int k = 0; k < histFill; k++) sum += rawHist[i][k];
    rawAvg[i] = (int)(sum / histFill);
    normNow[i] = SENSOR_ACTIVE[i] ? normalizeTo100(rawAvg[i], adcMin[i], adcMax[i]) : 0;
  }
}

// ═════════════════════════ 姿勢 ═════════════════════════
void computeGeometricNeutral() {
  float sx = 0, sy = 0;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) {
    sx += SENSOR_X_POS[i];
    sy += SENSOR_Y_POS[i];
  }
  geometricNeutralX = sx / SEAT_SENSOR_COUNT;
  geometricNeutralY = sy / SEAT_SENSOR_COUNT;
  poseNeutralX = geometricNeutralX;
  poseNeutralY = geometricNeutralY;
  poseNormalRadius = DEFAULT_NORMAL_RADIUS;
}

// 座標：x 小 = 左、y 小 = 後（靠椅背）、y 大 = 前
PoseLabel decidePoseLabel(float ox, float oy, float total) {
  if (total < OCCUPANCY_MIN_TOTAL) return POSE_EMPTY;
  // 左右、往後方向放大，等於綠環在這些方向變小（比較容易判定）
  float oxEff = ox / LATERAL_RADIUS_SCALE;
  float oyEff = (oy < 0.0f) ? oy / BACKWARD_RADIUS_SCALE : oy / FORWARD_RADIUS_SCALE;
  if (sqrtf(oxEff * oxEff + oyEff * oyEff) < poseNormalRadius) return POSE_NORMAL;
  if (fabsf(oxEff) >= fabsf(oyEff)) return (ox < 0.0f) ? POSE_LEFT : POSE_RIGHT;
  return (oy > 0.0f) ? POSE_FORWARD : POSE_BACKWARD;
}

PostureSummary computePostureSummary(const int n[]) {
  PostureSummary p;
  p.totalPressure = 0;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) p.totalPressure += n[i];

  p.leftTotal = n[5] + n[6] + n[7];   // S6 S7 S8
  p.rightTotal = n[0] + n[1] + n[2];  // S1 S2 S3
  p.frontTotal = n[2] + n[4] + n[5];  // S3 S5 S6
  p.backTotal = n[0] + n[3] + n[7];   // S1 S4 S8
  p.leftRightBalance = (p.rightTotal - p.leftTotal) / max(p.leftTotal + p.rightTotal, 1.0f);
  p.frontBackBalance = (p.backTotal - p.frontTotal) / max(p.frontTotal + p.backTotal, 1.0f);

  // 左右重心只看坐墊；前後重心另外加上椅背（往後靠時椅背受力 → 重心往後）
  float xn = 0, yn = 0, yw = p.totalPressure;
  for (int i = 0; i < SEAT_SENSOR_COUNT; i++) {
    xn += n[i] * SENSOR_X_POS[i];
    yn += n[i] * SENSOR_Y_POS[i];
  }
  for (int i = SEAT_SENSOR_COUNT; i < SENSOR_COUNT; i++) {
    yn += BACKREST_Y_WEIGHT * n[i] * SENSOR_Y_POS[i];
    yw += BACKREST_Y_WEIGHT * n[i];
  }
  p.centerX = (p.totalPressure > 0) ? xn / p.totalPressure : poseNeutralX;
  p.centerY = (yw > 0) ? yn / yw : poseNeutralY;

  float ox = p.centerX - poseNeutralX, oy = p.centerY - poseNeutralY;
  p.stability = clampFloat(1.0f - sqrtf(ox * ox + oy * oy) / (poseNormalRadius * 3.0f), 0.0f, 1.0f);
  p.confidence = p.stability;
  p.label = decidePoseLabel(ox, oy, p.totalPressure);
  return p;
}

// label 需連續 POSE_CONFIRM_MS 都一樣才更新（避免在綠環邊界來回跳）
void updatePoseDebounce(uint32_t now) {
  if (poseNow.label != candidatePose) {
    candidatePose = poseNow.label;
    candidateSinceMs = now;
  }
  if (candidatePose != stablePose && now - candidateSinceMs >= POSE_CONFIRM_MS) {
    stablePose = candidatePose;
  }
}

// ═════════════════════════ 震動提醒 ═════════════════════════
// 坐姿對應馬達：M1 右扶手、M2 右靠背、M3 左靠背、M4 左扶手
//   前傾 → 兩側扶手（提醒抬頭）；後仰 → 兩側靠背（提醒坐直）；左右傾 → 同側扶手＋靠背
void motorsForPose(PoseLabel p, int out[2]) {
  switch (p) {
    case POSE_LEFT: out[0] = 4; out[1] = 3; break;
    case POSE_RIGHT: out[0] = 1; out[1] = 2; break;
    case POSE_FORWARD: out[0] = 1; out[1] = 4; break;
    case POSE_BACKWARD: out[0] = 2; out[1] = 3; break;
    default: out[0] = 0; out[1] = 0; break;
  }
}

void triggerPostureReminder(PoseLabel p, int level, uint32_t now, uint32_t badMs) {
  int ids[2];
  motorsForPose(p, ids);
  if (ids[0] == 0) return;

  int intensity = REMINDER_INTENSITY;
  int durationMs = POSTURE_DURATION_MS[clampInt(level, 1, 3) - 1];

  stopAllMotors();
  scheduleSingleCommand(ids[0], intensity, durationMs, 0, 0);
  scheduleSingleCommand(ids[1], intensity, durationMs, 1, 0);
  lastReminderAtMs = now;
  hasRemindedThisBout = true;

  String extra = jsonStr("message", POSE_NAMES[p]);
  extra += ",\"motors\":[" + String(ids[0]) + "," + String(ids[1]) + "]";
  extra += ",\"intensity\":" + String(intensity);
  extra += ",\"vibration_ms\":" + String(durationMs);
  extra += ",\"level\":" + String(level);
  extra += ",\"duration_s\":" + String(badMs / 1000);
  sendStatusEvent("posture_reminder", extra);
}

void evaluatePoseReminder(uint32_t now) {
  if (stablePose == POSE_NORMAL || stablePose == POSE_EMPTY) {
    badPoseTiming = false;
    hasRemindedThisBout = false;
    return;
  }
  if (!badPoseTiming || stablePose != badPoseLabel) {
    badPoseTiming = true;
    badPoseLabel = stablePose;
    badPoseStartMs = now;
    hasRemindedThisBout = false;
    return;
  }

  uint32_t badMs = now - badPoseStartMs;
  if (badMs < BAD_POSTURE_FIRST_ALERT_MS) return;
  if (hasRemindedThisBout && now - lastReminderAtMs < BAD_POSTURE_REPEAT_MS) return;
  if (postureHoldActive) {
    if (!timeReached(now, postureHoldUntilMs)) return;  // 剛震過久坐提醒，壞坐姿延後
    postureHoldActive = false;
  }

  int level = (badMs >= BAD_POSTURE_THIRD_ALERT_MS) ? 3 : (badMs >= BAD_POSTURE_SECOND_ALERT_MS) ? 2 : 1;
  triggerPostureReminder(stablePose, level, now, badMs);
}

// ═════════════════════════ 久坐 ═════════════════════════
void triggerSedentaryReminder(uint32_t now, uint32_t satMs) {
  stopAllMotors();
  for (int id = 1; id <= MOTOR_COUNT; id++) {
    scheduleSingleCommand(id, SEDENTARY_INTENSITY, SEDENTARY_DURATION_MS, id - 1, SEDENTARY_STAGGER_MS);
  }
  sedentaryAlert = true;
  lastSedentaryMs = now;
  ledBlinkUntilMs = now + LED_ALERT_BLINK_DURATION_MS;  // 震動與燈號閃爍同時開始
  postureHoldActive = true;  // 同時成立時先震久坐，壞坐姿延到下一輪
  postureHoldUntilMs = now + BAD_POSTURE_REPEAT_MS;

  String extra = ",\"sitting_min\":" + String(satMs / 60000UL);
  extra += ",\"limit_min\":" + String(SITTING_LIMIT_MIN);
  extra += ",\"motors\":[1,2,3,4],\"intensity\":" + String(SEDENTARY_INTENSITY);
  extra += ",\"vibration_ms\":" + String(SEDENTARY_DURATION_MS);
  sendStatusEvent("sedentary_reminder", extra);
}

void revertNeutralAfterLeave();

// 坐下開始計時；挪動、換姿勢、短暫起身（< 30 秒）都不中斷；連續 30 秒沒人才歸零
void updateSitting(uint32_t now) {
  bool occupied = (stablePose != POSE_EMPTY);
  if (occupied) {
    emptyPending = false;
    if (!sitting) {
      sitting = true;
      sitStartMs = now;
      sedentaryAlert = false;
    }
    uint32_t sat = now - sitStartMs;
    if (!sedentaryAlert) {
      if (sat >= SITTING_LIMIT_MS) triggerSedentaryReminder(now, sat);
    } else if (now - lastSedentaryMs >= SEDENTARY_REPEAT_MS) {
      triggerSedentaryReminder(now, sat);
    }
    return;
  }

  if (!sitting) return;
  if (!emptyPending) {
    emptyPending = true;
    emptySinceMs = now;
    return;
  }
  if (now - emptySinceMs >= LEAVE_RESET_MS) {
    uint32_t satMs = emptySinceMs - sitStartMs;
    sitting = false;
    emptyPending = false;
    sedentaryAlert = false;
    sendStatusEvent("left_seat", ",\"sitting_min\":" + String(satMs / 60000UL) + ",\"sitting_s\":" + String(satMs / 1000UL));
    revertNeutralAfterLeave();
  }
}

uint32_t sittingSeconds(uint32_t now) { return sitting ? (now - sitStartMs) / 1000UL : 0; }

// ═════════════════════════ 中立點設定 / 校正 ═════════════════════════
void applyNeutral(float x, float y, float r) {
  poseNeutralX = x;
  poseNeutralY = y;
  poseNormalRadius = r;
}

void revertNeutralAfterLeave() {
  if (!neutralIsUser) return;
  if (hasFleetNeutral) applyNeutral(fleetNeutralX, fleetNeutralY, fleetNormalRadius);
  else applyNeutral(geometricNeutralX, geometricNeutralY, DEFAULT_NORMAL_RADIUS);
  neutralIsUser = false;
  String extra = jsonStr("reason", "left_seat");
  extra += ",\"neutral_x\":" + String(poseNeutralX, 4) + ",\"neutral_y\":" + String(poseNeutralY, 4);
  extra += ",\"normal_radius\":" + String(poseNormalRadius, 3);
  sendStatusEvent("neutral_reset", extra);
}

// chair/{id}/config：set_neutral / reset_neutral。只存在 RAM，不寫入快閃記憶體。
void handleConfig(const char* text) {
  if (!text[0]) return;  // 後端清除 retained 訊息時會收到空 payload
  JsonDocument doc;
  if (deserializeJson(doc, text)) {
    sendStatusEvent("config_rejected", jsonStr("reason", "invalid_json"));
    return;
  }
  const char* cmd = doc["cmd"] | "";
  bool isSet = strcmp(cmd, "set_neutral") == 0;
  bool isReset = strcmp(cmd, "reset_neutral") == 0;
  if (!isSet && !isReset) {
    sendStatusEvent("config_rejected", jsonStr("cmd", cmd) + jsonStr("reason", "unknown_cmd"));
    return;
  }
  float x = doc["neutral_x"] | -1.0f;
  float y = doc["neutral_y"] | -1.0f;
  float r = doc["normal_radius"] | poseNormalRadius;
  if (x < 0.05f || x > 0.95f || y < 0.05f || y > 0.95f || r < 0.02f || r > 0.3f) {
    sendStatusEvent("config_rejected", jsonStr("cmd", cmd) + jsonStr("reason", "out_of_range"));
    return;
  }

  applyNeutral(x, y, r);
  if (isReset) {
    hasFleetNeutral = true;
    fleetNeutralX = x;
    fleetNeutralY = y;
    fleetNormalRadius = r;
  }
  neutralIsUser = isSet;

  String extra = jsonStr("cmd", cmd);
  extra += ",\"neutral_x\":" + String(x, 4) + ",\"neutral_y\":" + String(y, 4) + ",\"normal_radius\":" + String(r, 3);
  sendStatusEvent("config_applied", extra);
}

void handleCalibrationCmd(const char* text) {
  JsonDocument doc;
  if (deserializeJson(doc, text)) return;
  const char* cmd = doc["cmd"] | "";
  if (strcmp(cmd, "calibrate") != 0) return;
  const char* reqId = doc["request_id"] | "";
  int durationS = clampInt((int)(doc["duration_s"] | 5.0f), 2, CALIB_MAX_SAMPLES * (int)SAMPLE_INTERVAL_MS / 1000);

  memset(&calib, 0, sizeof(calib));
  strlcpy(calib.requestId, reqId, sizeof(calib.requestId));
  calib.active = true;
  calib.endMs = millis() + (uint32_t)durationS * 1000UL;
  sendStatusEvent("calibration_started", jsonStr("request_id", calib.requestId) + ",\"duration_s\":" + String(durationS));
}

// 每次取樣呼叫：用平滑後的重心（不是 debounce 後的 label）
void updateCalibration(uint32_t now) {
  if (!calib.active) return;
  if (calib.n + calib.empty < CALIB_MAX_SAMPLES) {
    if (poseNow.label == POSE_EMPTY) {
      calib.empty++;
    } else {
      calib.cx[calib.n] = poseNow.centerX;
      calib.cy[calib.n] = poseNow.centerY;
      for (int i = 0; i < SENSOR_COUNT; i++) calib.normSum[i] += normNow[i];
      calib.n++;
    }
  }
  if (!timeReached(now, calib.endMs)) return;
  calib.active = false;

  String idField = jsonStr("request_id", calib.requestId);
  int total = calib.n + calib.empty;
  if (calib.n == 0 || calib.empty * 5 > total) {  // 超過 20% 的時間沒人坐
    sendStatusEvent("calibration_failed", idField + jsonStr("reason", "no_occupancy") + ",\"samples\":" + String(total));
    return;
  }

  float mx = 0, my = 0;
  for (int k = 0; k < calib.n; k++) { mx += calib.cx[k]; my += calib.cy[k]; }
  mx /= calib.n;
  my /= calib.n;
  int within = 0;
  for (int k = 0; k < calib.n; k++) {
    float dx = calib.cx[k] - mx, dy = calib.cy[k] - my;
    if (sqrtf(dx * dx + dy * dy) <= CALIB_STABLE_RADIUS) within++;
  }
  int stablePct = within * 100 / calib.n;
  if (stablePct < CALIB_STABLE_PCT) {
    sendStatusEvent("calibration_failed", idField + jsonStr("reason", "unstable") + ",\"stable_pct\":" + String(stablePct));
    return;
  }

  String extra = idField;
  extra += ",\"neutral_x\":" + String(mx, 4) + ",\"neutral_y\":" + String(my, 4);
  extra += ",\"norm_avg\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) extra += ",";
    extra += String((int)lroundf((float)calib.normSum[i] / calib.n));
  }
  extra += "],\"samples\":" + String(calib.n) + ",\"stable_pct\":" + String(stablePct);
  sendStatusEvent("calibrated", extra);  // 不自己改中立點，等後端回送 set_neutral
}

// ═════════════════════════ 電池 ═════════════════════════
int voltageToBatteryPercent(float v) {
  float ratio = clampFloat((v - BATTERY_EMPTY_V) / (BATTERY_FULL_V - BATTERY_EMPTY_V), 0.0f, 1.0f);
  return (int)(ratio * 100.0f + 0.5f);
}

BatteryReading readBattery() {
  long rawSum = 0, mvSum = 0;
  for (int i = 0; i < BATTERY_SAMPLE_COUNT; i++) {
    rawSum += analogRead(BATTERY_VP_PIN);
    mvSum += analogReadMilliVolts(BATTERY_VP_PIN);  // 套用晶片出廠校正
  }
  BatteryReading r;
  r.raw = (int)(rawSum / BATTERY_SAMPLE_COUNT);
  r.pinVoltage = (mvSum / (float)BATTERY_SAMPLE_COUNT) / 1000.0f;
  float packV = r.pinVoltage * BATTERY_DIVIDER_RATIO;
  r.present = packV >= BATTERY_PRESENT_MIN_V;
  if (!r.present) {
    batteryFilteredV = -1.0f;
    r.voltage = packV;
    r.pct = 0;
    return r;
  }
  batteryFilteredV = (batteryFilteredV < 0) ? packV
                     : batteryFilteredV * (1.0f - BATTERY_SMOOTHING_ALPHA) + packV * BATTERY_SMOOTHING_ALPHA;
  r.voltage = batteryFilteredV;
  r.pct = voltageToBatteryPercent(r.voltage);
  return r;
}

// ═════════════════════════ pressure 傳送 ═════════════════════════
String buildPressurePayload(bool isChange, bool withPower, uint32_t now) {
  String s = msgHead();
  s.reserve(900);
  s += ",\"seq\":" + String(pressureSeq);
  s += jsonStr("type", isChange ? "change" : "sync");
  s += ",\"norm\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) s += ",";
    s += String(normNow[i]);
  }
  s += "]";
#if DEBUG_RAW
  s += ",\"raw\":[";
  for (int i = 0; i < SENSOR_COUNT; i++) {
    if (i > 0) s += ",";
    s += String(rawAvg[i]);
  }
  s += "]";
#endif
  s += ",\"pose\":{\"label\":\"";
  s += POSE_NAMES[stablePose];
  s += "\",\"left_right_balance\":" + String(poseNow.leftRightBalance, 3);
  s += ",\"front_back_balance\":" + String(poseNow.frontBackBalance, 3);
  s += ",\"center_x\":" + String(poseNow.centerX, 3);
  s += ",\"center_y\":" + String(poseNow.centerY, 3);
  s += ",\"neutral_x\":" + String(poseNeutralX, 3);
  s += ",\"neutral_y\":" + String(poseNeutralY, 3);
  s += ",\"normal_radius\":" + String(poseNormalRadius, 3);
  s += ",\"stability\":" + String(poseNow.stability, 3);
  s += ",\"confidence\":" + String(poseNow.confidence, 3);
  s += ",\"total_pressure\":" + String(poseNow.totalPressure, 1);
  s += ",\"left_total\":" + String(poseNow.leftTotal, 1);
  s += ",\"right_total\":" + String(poseNow.rightTotal, 1);
  s += ",\"front_total\":" + String(poseNow.frontTotal, 1);
  s += ",\"back_total\":" + String(poseNow.backTotal, 1) + "}";

  s += ",\"sitting\":{\"active\":";
  s += sitting ? "true" : "false";
  s += ",\"seconds\":" + String(sittingSeconds(now));
  s += ",\"limit_min\":" + String(SITTING_LIMIT_MIN);
  s += ",\"alert\":";
  s += sedentaryAlert ? "true" : "false";
  s += "}";

  if (withPower) {
    s += ",\"power\":{\"voltage_v\":" + String(battery.voltage, 3);
    s += ",\"battery_pct\":" + String(battery.pct);
    s += ",\"battery_present\":";
    s += battery.present ? "true" : "false";
#if DEBUG_RAW
    s += ",\"raw\":" + String(battery.raw) + ",\"vp_v\":" + String(battery.pinVoltage, 3);
#endif
    s += "}";
  }
  s += "}";
  return s;
}

// 有變動立即送（≥ 0.5 秒間隔），沒變動則 5 秒（沒人坐 30 秒）送一筆 sync
void maybePublishPressure(uint32_t now) {
  if (histFill < SMOOTH_N) return;
  if (hasSentPressure && now - lastPressureSentMs < PUBLISH_MIN_GAP_MS) return;

  // reason 只用於除錯：DEBUG_RAW = 1 時印在序列埠，用來統計各條件實際觸發幾次
  const char* reason = nullptr;
  if (!hasSentPressure || stablePose != lastSentPose) reason = "label";
  for (int i = 0; !reason && i < SENSOR_COUNT; i++) {
    if (abs(normNow[i] - lastSentNorm[i]) >= CHANGE_NORM_DELTA) reason = "norm";
  }
  if (!reason && CHANGE_CENTER_DELTA > 0 && stablePose != POSE_EMPTY) {
    float dx = poseNow.centerX - lastSentCenterX, dy = poseNow.centerY - lastSentCenterY;
    if (sqrtf(dx * dx + dy * dy) >= CHANGE_CENTER_DELTA) reason = "center";
  }
  bool change = (reason != nullptr);
  uint32_t syncMs = (stablePose == POSE_EMPTY) ? SYNC_INTERVAL_EMPTY_MS : SYNC_INTERVAL_MS;
  bool sync = now - lastPressureSentMs >= syncMs;
  if (!change && !sync) return;
  if (!change) reason = "sync";

  bool withPower = !change || !hasSentPressure || (now - lastPowerSentMs >= POWER_MAX_GAP_MS);
  pressureSeq++;
  String payload = buildPressurePayload(change, withPower, now);
  enqueueOut(OT_PRESSURE, payload);
#if DEBUG_RAW
  Serial.printf("[pressure #%lu] reason=%s\n", (unsigned long)pressureSeq, reason);
  Serial.println(payload);
#else
  (void)reason;
#endif

  hasSentPressure = true;
  lastPressureSentMs = now;
  if (withPower) lastPowerSentMs = now;
  lastSentPose = stablePose;
  for (int i = 0; i < SENSOR_COUNT; i++) lastSentNorm[i] = normNow[i];
  lastSentCenterX = poseNow.centerX;
  lastSentCenterY = poseNow.centerY;
}

// ═════════════════════════ 硬體報告 ═════════════════════════
void publishHardwareReport(uint32_t now) {
  String s = msgHead();
  s += ",\"event\":\"hardware_report\"";
  s += jsonStr("fw", FW_VERSION);
  s += ",\"ads\":{\"ads1\":";
  s += ads1_available ? "true" : "false";
  s += ",\"ads2\":";
  s += ads2_available ? "true" : "false";
  s += ",\"ads3\":";
  s += ads3_available ? "true" : "false";
  s += "}";
  s += sensorArraysJson(now);
  s += ",\"motor_detection_supported\":false,\"motor_detected\":[\"unknown\",\"unknown\",\"unknown\",\"unknown\"]";
  s += ",\"motor_layout\":[\"right_armrest\",\"right_lumbar\",\"left_lumbar\",\"left_armrest\"]";
  s += ",\"sitting_limit_min\":" + String(SITTING_LIMIT_MIN);
  s += ",\"sample_hz\":" + String(1000UL / SAMPLE_INTERVAL_MS);
  s += "}";
  enqueueOut(OT_STATUS, s);
  for (int i = 0; i < SENSOR_COUNT; i++) lastReportedSensorState[i] = getSensorStateCode(i, now);
}

void checkSensorStateChange(uint32_t now) {
  if (now - lastSensorStateCheckMs < 1000) return;
  lastSensorStateCheckMs = now;
  bool changed = false;
  for (int i = 0; i < SENSOR_COUNT; i++) {
    uint8_t code = getSensorStateCode(i, now);
    if (code != lastReportedSensorState[i]) {
      lastReportedSensorState[i] = code;
      changed = true;
    }
  }
  if (changed) sendStatusEvent("sensor_state_changed", sensorArraysJson(now));
}

// ═════════════════════════ LED 燈條 ═════════════════════════
// pct 是「人眼感覺的亮度」：人眼對亮度是非線性的，PWM 直接乘 50%→80% 看起來只亮一點點，
// 所以實際輸出 = (pct/100)^LED_GAMMA：80% → 64%、50% → 25%、20% → 4%（最大輸出仍 ≤ 80%）
uint32_t scaleColor(uint8_t r, uint8_t g, uint8_t b, int pct) {
  float k = powf(pct / 100.0f, LED_GAMMA);
  return Adafruit_NeoPixel::Color((uint8_t)(r * k), (uint8_t)(g * k), (uint8_t)(b * k));
}

void ledShowFrame() {
  for (int i = 0; i < LEDS_PER_STRIP; i++) {
    stripLeft.setPixelColor(i, ledFrameL[i]);
    stripRight.setPixelColor(i, ledFrameR[i]);
  }
  stripLeft.show();
  stripRight.show();
}

void ledSetup() {
  stripLeft.begin();
  stripRight.begin();
  stripLeft.setBrightness(255);   // 亮度由程式自己縮放（20%~80%），不用 setBrightness
  stripRight.setBrightness(255);
  for (int i = 0; i < LEDS_PER_STRIP; i++) {
    float f = (LEDS_PER_STRIP > 1) ? 1.0f - fabsf(2.0f * i / (LEDS_PER_STRIP - 1) - 1.0f) : 1.0f;  // 0 兩端 ~ 1 中段
    ledPos[i] = 2.0f * f - 1.0f;
  }
  // 開機自我測試：紅 → 綠 → 藍各 0.2 秒（50% 亮度）
  const uint8_t test[3][3] = {{255, 0, 0}, {0, 255, 0}, {0, 0, 255}};
  for (int c = 0; c < 3; c++) {
    for (int i = 0; i < LEDS_PER_STRIP; i++) ledFrameL[i] = ledFrameR[i] = scaleColor(test[c][0], test[c][1], test[c][2], 50);
    ledShowFrame();
    delay(200);
  }
  for (int i = 0; i < LEDS_PER_STRIP; i++) ledFrameL[i] = ledFrameR[i] = 0;
  ledShowFrame();
  ledFrameValid = true;
}

void ledUpdate(uint32_t now) {
  bool on = (stablePose != POSE_EMPTY) && !otaInProgress;

  // 重心偏移 → -1 ~ 1（leanLeft > 0 偏左，leanFront > 0 偏前），再平滑
  float tl = 0, tf = 0;
  if (on && poseNow.label != POSE_EMPTY) {
    float full = poseNormalRadius * LED_LEAN_FULL_RADII;
    tl = clampFloat(-(poseNow.centerX - poseNeutralX) / (full * LATERAL_RADIUS_SCALE), -1.0f, 1.0f);
    float oy = poseNow.centerY - poseNeutralY;
    oy /= (oy < 0) ? BACKWARD_RADIUS_SCALE : FORWARD_RADIUS_SCALE;  // 與前後傾判定一致
    tf = clampFloat(oy / full, -1.0f, 1.0f);
  }
  ledLeanLeft += (tl - ledLeanLeft) * LED_SMOOTH_ALPHA;
  ledLeanFront += (tf - ledLeanFront) * LED_SMOOTH_ALPHA;

  // 顏色：久坐進度 0 → 1 = 綠 → 琥珀 → 紅（r + g = 255）；
  //       提醒後：震動那一刻起閃 10 秒，之後紅色常亮，直到下一次提醒再閃
  uint8_t r = 0, g = 0, b = 0;
  if (on) {
    if (sedentaryAlert) {
      bool blinking = !timeReached(now, ledBlinkUntilMs);
      if (!blinking || (now / LED_ALERT_BLINK_MS) % 2 == 0) r = 255;
    } else {
      float t = clampFloat((float)(now - sitStartMs) / (float)SITTING_LIMIT_MS, 0.0f, 1.0f);
      r = (uint8_t)(255 * t);
      g = 255 - r;
    }
  }

  bool dirty = !ledFrameValid;
  for (int side = 0; side < 2; side++) {
    float sideLean = (side == 0) ? ledLeanLeft : -ledLeanLeft;  // 0 = 左扶手、1 = 右扶手
    uint32_t* frame = (side == 0) ? ledFrameL : ledFrameR;
    for (int i = 0; i < LEDS_PER_STRIP; i++) {
      float s = clampFloat(sideLean + ledLeanFront * ledPos[i], -1.0f, 1.0f);
      int pct = (s >= 0) ? LED_BASE_PCT + (int)(s * (LED_MAX_PCT - LED_BASE_PCT))
                         : LED_BASE_PCT + (int)(s * (LED_BASE_PCT - LED_MIN_PCT));
      uint32_t c = scaleColor(r, g, b, pct);
      if (c != frame[i]) { frame[i] = c; dirty = true; }
    }
  }
  if (dirty) {  // 畫面沒變就不送資料給燈條
    ledShowFrame();
    ledFrameValid = true;
  }
}

// ═════════════════════════ 網路（Core 0）═════════════════════════
void mqttCallback(char* topic, byte* payload, unsigned int length) {
  InMsg m;
  if (strcmp(topic, topicVibCmd) == 0) m.kind = IN_VIB_CMD;
  else if (strcmp(topic, topicConfig) == 0) m.kind = IN_CONFIG;
  else if (strcmp(topic, topicCalibCmd) == 0) m.kind = IN_CALIB;
  else return;
  m.payload = (char*)malloc(length + 1);
  if (!m.payload) return;
  memcpy(m.payload, payload, length);
  m.payload[length] = '\0';
  if (xQueueSend(inQ, &m, 0) != pdTRUE) free(m.payload);
}

void setupArduinoOTA() {
  ArduinoOTA.setHostname(otaHostname);
  ArduinoOTA.setPassword(OTA_PASSWORD);
  ArduinoOTA.onStart([]() { otaInProgress = true; Serial.println("OTA 開始更新"); });
  ArduinoOTA.onEnd([]() { Serial.println("\nOTA 更新完成"); });
  ArduinoOTA.onError([](ota_error_t e) { otaInProgress = false; Serial.printf("OTA 錯誤[%u]\n", e); });
  ArduinoOTA.begin();
  Serial.printf("OTA 已啟用，主機名: %s\n", otaHostname);
}

void mqttTryConnect() {
  Serial.println("連線 MQTT Broker...");
  if (!mqttClient.connect(mqttClientId, MQTT_USER, MQTT_PASS, topicOnline, 1, true, willPayload)) {
    Serial.printf("MQTT 連線失敗，rc=%d，%lu 秒後重試\n", mqttClient.state(), (unsigned long)(MQTT_RETRY_MS / 1000));
    return;
  }
  Serial.println("MQTT 已連線");
  mqttClient.subscribe(topicVibCmd, 0);
  mqttClient.subscribe(topicConfig, 1);    // retained：訂閱後會立刻收到目前的中立點
  mqttClient.subscribe(topicCalibCmd, 0);
  String online = "{\"device_id\":\"";
  online += deviceId;
  online += "\",\"online\":true,\"fw\":\"";
  online += FW_VERSION;
  online += "\"}";
  mqttClient.publish(topicOnline, online.c_str(), true);
  needBootReport = true;
}

// 只有 netTask 會從 queue 取出 → 不會跟產生端競爭
void drainOutQueues() {
  OutMsg m;
  for (int k = 0; k < 8 && xQueuePeek(eventQ, &m, 0) == pdTRUE; k++) {
    const char* t = topicFor(m.topic);
    bool tooBig = strlen(m.payload) + strlen(t) + 8 > MQTT_BUFFER_SIZE;
    if (!tooBig && !mqttClient.publish(t, m.payload)) break;  // 發送失敗就保留，下次再送
    xQueueReceive(eventQ, &m, 0);
    free(m.payload);
  }
  for (int k = 0; k < 4 && xQueueReceive(telemetryQ, &m, 0) == pdTRUE; k++) {
    mqttClient.publish(topicFor(m.topic), m.payload);
    free(m.payload);
  }
}

void netTask(void*) {
  WiFi.mode(WIFI_STA);
  WiFi.setAutoReconnect(true);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.printf("連線 Wi-Fi: %s（背景進行，不影響感測與震動）\n", WIFI_SSID);
  uint32_t lastWifiKick = millis();
  uint32_t lastMqttTry = 0;
  bool mqttTried = false;
  bool servicesStarted = false;
  bool wasWifi = false;

  for (;;) {
    uint32_t now = millis();
    if (WiFi.status() != WL_CONNECTED) {
      netOnline = false;
      wasWifi = false;
      if (now - lastWifiKick >= WIFI_RETRY_MS) {
        lastWifiKick = now;
        WiFi.disconnect();
        WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
      }
    } else {
      if (!wasWifi) {
        wasWifi = true;
        Serial.print("Wi-Fi 已連線，IP: ");
        Serial.println(WiFi.localIP());
      }
      if (!servicesStarted) {
        servicesStarted = true;
        configTime(8 * 3600, 0, "pool.ntp.org", "time.google.com");
        setupArduinoOTA();
      }
      ArduinoOTA.handle();
      if (!mqttClient.connected()) {
        netOnline = false;
        if (!mqttTried || now - lastMqttTry >= MQTT_RETRY_MS) {
          mqttTried = true;
          lastMqttTry = now;
          mqttTryConnect();  // TLS 握手可能卡幾秒，只卡這個核心
        }
      } else {
        mqttClient.loop();
        netOnline = true;
        drainOutQueues();
      }
    }
    vTaskDelay(pdMS_TO_TICKS(10));
  }
}

// ═════════════════════════ 指令處理（Core 1）═════════════════════════
void processIncoming() {
  InMsg m;
  while (xQueueReceive(inQ, &m, 0) == pdTRUE) {
    if (m.kind == IN_VIB_CMD) handleMotorCommand(m.payload);
    else if (m.kind == IN_CONFIG) handleConfig(m.payload);
    else if (m.kind == IN_CALIB) handleCalibrationCmd(m.payload);
    free(m.payload);
  }
}

void checkMotorSafety(uint32_t now) {
  for (int i = 0; i < MOTOR_COUNT; i++) {
    if (motors[i].running && now - motorOnSinceMs[i] > MOTOR_SAFETY_MAX_ON_MS) {
      stopAllMotors();
      sendStatusEvent("safety_timeout", jsonStr("message", "stop_all_motors"));
      publishMotorState("safety_timeout", "none");
      return;
    }
  }
}

// ═════════════════════════ setup / loop ═════════════════════════
void setupIdentity() {
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  snprintf(deviceId, sizeof(deviceId), "chair_%02X%02X%02X", mac[3], mac[4], mac[5]);
  snprintf(mqttClientId, sizeof(mqttClientId), "esp32-%02X%02X%02X", mac[3], mac[4], mac[5]);
  snprintf(otaHostname, sizeof(otaHostname), "chair-%02x%02x%02x", mac[3], mac[4], mac[5]);
  snprintf(topicPressure, sizeof(topicPressure), "chair/%s/pressure", deviceId);
  snprintf(topicVibState, sizeof(topicVibState), "chair/%s/vibration/state", deviceId);
  snprintf(topicVibStatus, sizeof(topicVibStatus), "chair/%s/vibration/status", deviceId);
  snprintf(topicVibAck, sizeof(topicVibAck), "chair/%s/vibration/ack", deviceId);
  snprintf(topicVibCmd, sizeof(topicVibCmd), "chair/%s/vibration/cmd", deviceId);
  snprintf(topicConfig, sizeof(topicConfig), "chair/%s/config", deviceId);
  snprintf(topicCalibCmd, sizeof(topicCalibCmd), "chair/%s/calibration/cmd", deviceId);
  snprintf(topicOnline, sizeof(topicOnline), "chair/%s/online", deviceId);
  snprintf(willPayload, sizeof(willPayload), "{\"device_id\":\"%s\",\"online\":false}", deviceId);
}

bool beginAds(Adafruit_ADS1115& ads, uint8_t addr, int tries) {
  for (int t = 0; t < tries; t++) {
    if (ads.begin(addr)) {
      ads.setGain(GAIN_ONE);
      ads.setDataRate(RATE_ADS1115_860SPS);  // 每次轉換約 1.2 ms，11 顆約 20~30 ms
      return true;
    }
    delay(150);
  }
  return false;
}

void setup() {
  Serial.begin(115200);
  delay(800);
  setupIdentity();
  Serial.println("\n--- 智慧感測椅系統開機 ---");
  Serial.printf("device_id: %s   (請貼在椅子上)\n", deviceId);
  Serial.printf("firmware : %s\n", FW_VERSION);

  pinMode(DETECT_LED_PIN, OUTPUT);
  digitalWrite(DETECT_LED_PIN, LOW);
  computeGeometricNeutral();

  analogReadResolution(12);
  analogSetPinAttenuation(BATTERY_VP_PIN, ADC_11db);

  for (int i = 0; i < SENSOR_COUNT; i++) {
    sensorSeenSignal[i] = false;
    sensorMinRaw[i] = 32767;
    sensorMaxRaw[i] = -32768;
    lastSentNorm[i] = 0;
  }
  sensorDetectStartMs = millis();

  for (int i = 0; i < MOTOR_COUNT; i++) {
    pwmAttachMotor(i);
    motors[i] = {false, false, 0, 0, 0};
    setMotorOutput(i, 0);
  }

  Wire.begin(21, 22);
  delay(200);
  ads1_available = beginAds(ads1, 0x48, 3);
  ads2_available = beginAds(ads2, 0x49, 3);
  ads3_available = beginAds(ads3, 0x4A, 1);
  Serial.printf("ADS1115 #1(0x48)=%s #2(0x49)=%s #3(0x4A)=%s\n", ads1_available ? "OK" : "未找到",
                ads2_available ? "OK" : "未找到", ads3_available ? "OK" : "未找到");

  int online = ads1_available + ads2_available + ads3_available;
  for (int i = 0; i < online; i++) {  // 閃燈次數 = 偵測到的 ADS 數量
    digitalWrite(DETECT_LED_PIN, HIGH);
    delay(300);
    digitalWrite(DETECT_LED_PIN, LOW);
    delay(300);
  }

  ledSetup();
  battery = readBattery();
  for (int i = 0; i < SENSOR_COUNT; i++) lastReportedSensorState[i] = getSensorStateCode(i, millis());

  telemetryQ = xQueueCreate(4, sizeof(OutMsg));
  eventQ = xQueueCreate(24, sizeof(OutMsg));
  inQ = xQueueCreate(8, sizeof(InMsg));

  wifiClient.setInsecure();
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(MQTT_BUFFER_SIZE);
  mqttClient.setKeepAlive(MQTT_KEEPALIVE_S);
  mqttClient.setSocketTimeout(5);

  xTaskCreatePinnedToCore(netTask, "net", 12288, nullptr, 1, nullptr, 0);
  lastMotorStateMs = millis();
}

void loop() {
  uint32_t now = millis();

  processIncoming();

  if (otaInProgress) stopAllMotors();
  if (updateMotorStateMachine(now)) publishMotorState("motor_changed", "none");
  checkMotorSafety(now);

  if (needBootReport) {
    needBootReport = false;
    sendStatusEvent("mqtt_connected", jsonStr("message", "subscribed"));
    publishHardwareReport(now);
    publishMotorState("boot", "none");
  }

  if (now - lastBatteryReadMs >= BATTERY_READ_INTERVAL_MS) {
    lastBatteryReadMs = now;
    battery = readBattery();
  }

  if (now - lastSampleMs >= SAMPLE_INTERVAL_MS) {
    lastSampleMs = now;
    sampleSensors();
    poseNow = computePostureSummary(normNow);
    updatePoseDebounce(now);
    updateCalibration(now);
    updateSitting(now);         // 久坐先判斷，同時成立時優先
    evaluatePoseReminder(now);
    maybePublishPressure(now);
  }

  checkSensorStateChange(now);

  if (now - lastLedMs >= LED_UPDATE_MS) {
    lastLedMs = now;
    ledUpdate(now);
    digitalWrite(DETECT_LED_PIN, netOnline ? HIGH : ((now / 500) % 2 ? HIGH : LOW));
  }

  if (now - lastMotorStateMs >= MOTOR_STATE_HEARTBEAT_MS) {
    lastMotorStateMs = now;
    publishMotorState("heartbeat", "none");
  }

  delay(1);
}
