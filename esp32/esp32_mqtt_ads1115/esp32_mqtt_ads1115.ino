#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <PubSubClient.h>
#include <Wire.h>
#include <Adafruit_ADS1X15.h>

// =========================
// Wi-Fi / MQTT 設定（請修改）
// =========================
const char* WIFI_SSID = "xiao";
const char* WIFI_PASSWORD = "1234567890";

const char* MQTT_BROKER = "d8806e09.ala.eu-central-1.emqxsl.com";  // EMQX Cloud
const int   MQTT_PORT   = 8883;  // TLS
const char* MQTT_TOPIC  = "chair/pressure/01";
const char* MQTT_CLIENT_ID = "esp32-chair-01";
const char* MQTT_USER   = "xiao";
const char* MQTT_PASS   = "zxzcindy1";

WiFiClientSecure wifiClient;
PubSubClient mqttClient(wifiClient);
Adafruit_ADS1115 ads1;  // 位址 0x48，ADDR 接 GND，S1-S4
Adafruit_ADS1115 ads2;  // 位址 0x49，ADDR 接 3V3，S5-S8
Adafruit_ADS1115 ads3;  // 位址 0x4A，ADDR 接 SDA，S9-S12（預留）

// 全部 8 路皆由 ADS1115 讀取
const int SENSOR_COUNT = 8;

// 標記各 ADS1115 是否已成功初始化
bool ads1_available = false;
bool ads2_available = false;
bool ads3_available = false;

// 標記哪些感測器已實際接上（未接的輸出 0）
const bool SENSOR_ACTIVE[SENSOR_COUNT] = {true, true, true, true, true, true, true, true};

// 每顆感測器各自校正區間（空載/受力後再調整，ADS1115 16bit 範圍 0~32767）
int adcMin[SENSOR_COUNT] = {2400, 2400, 2400, 2400, 2400, 2400, 2400, 2400};
int adcMax[SENSOR_COUNT] = {20500, 20500, 20500, 20500, 20500, 20500, 20500, 20500};

unsigned long lastPublishMs = 0;
const unsigned long PUBLISH_INTERVAL_MS = 500;  // 每秒2次，節省雲端流量

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
    } else {
      Serial.print("MQTT 連線失敗，rc=");
      Serial.print(mqttClient.state());
      Serial.println(" 1秒後重試...");
      delay(1000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(500);

  Wire.begin(21, 22);

  // 非阻塞式初始化 ADS1115
  if (ads1.begin(0x48)) {
    ads1_available = true;
    Serial.println("✓ ADS1115 #1 (0x48) 初始化成功");
    ads1.setGain(GAIN_ONE);
  } else {
    ads1_available = false;
    Serial.println("✗ ADS1115 #1 (0x48) 未找到，S1-S4 將使用亂數");
  }

  if (ads2.begin(0x49)) {
    ads2_available = true;
    Serial.println("✓ ADS1115 #2 (0x49) 初始化成功");
    ads2.setGain(GAIN_ONE);
  } else {
    ads2_available = false;
    Serial.println("✗ ADS1115 #2 (0x49) 未找到，S5-S8 將使用亂數");
  }

  if (ads3.begin(0x4A)) {
    ads3_available = true;
    Serial.println("✓ ADS1115 #3 (0x4A) 初始化成功");
    ads3.setGain(GAIN_ONE);
  } else {
    ads3_available = false;
    Serial.println("✗ ADS1115 #3 (0x4A) 未找到");
  }

  connectWiFi();

  wifiClient.setInsecure();  // 跳過憑證驗證（Serverless 免費版適用）
  mqttClient.setServer(MQTT_BROKER, MQTT_PORT);
  mqttClient.setBufferSize(512);
  connectMQTT();
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!mqttClient.connected()) {
    connectMQTT();
  }

  mqttClient.loop();

  unsigned long now = millis();
  if (now - lastPublishMs < PUBLISH_INTERVAL_MS) {
    return;
  }
  lastPublishMs = now;

  int raw[SENSOR_COUNT];
  int normalized[SENSOR_COUNT];

  // S1-S4：ADS1115 #1（0x48）或亂數
  for (int i = 0; i < 4; i++) {
    if (SENSOR_ACTIVE[i]) {
      if (ads1_available) {
        raw[i] = ads1.readADC_SingleEnded(i);
      } else {
        raw[i] = random(200, 15000);  // 亂數替代
      }
      normalized[i] = normalizeTo100(raw[i], adcMin[i], adcMax[i]);
    } else {
      raw[i] = 0;
      normalized[i] = 0;
    }
  }

  // S5-S8：ADS1115 #2（0x49）或亂數
  for (int i = 0; i < 4; i++) {
    int idx = i + 4;
    if (SENSOR_ACTIVE[idx]) {
      if (ads2_available) {
        raw[idx] = ads2.readADC_SingleEnded(i);
      } else {
        raw[idx] = random(200, 15000);  // 亂數替代
      }
      normalized[idx] = normalizeTo100(raw[idx], adcMin[idx], adcMax[idx]);
    } else {
      raw[idx] = 0;
      normalized[idx] = 0;
    }
  }

  char payload[320];
  unsigned long ts = (unsigned long)(millis() / 1000);

  snprintf(
      payload,
      sizeof(payload),
      "{\"device_id\":\"chair_01\",\"ts\":%lu,\"raw\":[%d,%d,%d,%d,%d,%d,%d,%d],\"norm\":[%d,%d,%d,%d,%d,%d,%d,%d]}",
      ts,
      raw[0], raw[1], raw[2], raw[3], raw[4], raw[5], raw[6], raw[7],
      normalized[0], normalized[1], normalized[2], normalized[3],
      normalized[4], normalized[5], normalized[6], normalized[7]);

  mqttClient.publish(MQTT_TOPIC, payload);

  Serial.println(payload);
}
