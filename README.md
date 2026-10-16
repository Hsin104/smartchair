# Smart Chair App

智慧座椅 Flutter 前端，將坐姿監測延伸為 AI 主動健康介入。使用者可以查看即時姿勢、取得 AI 物理治療師建議、觀看推薦伸展影片，並將完成的健康任務累積到健康養成花園。

## 目前功能

- **儀表板**：即時姿勢、分數、風險、就座時間、提醒次數與健康花園進度。
- **AI 物理治療師**：呼叫 `/api/agent` 取得文字建議與 `recommended_exercises`，分開呈現兩種資料。
- **推薦伸展影片**：最多顯示 3 張影片卡片，可直接開啟 YouTube。
- **健康養成花園**：接受建議、完成每日任務、回報身體感受、累積能量與連續天數。
- **歷史報表**：已整合在「健康總覽」，顯示姿勢分布、平均分數、提醒次數、有效健康介入與最近紀錄。
- **通知**：姿勢提醒紀錄與當日健康介入數。
- **設定**：帳號、個人資料、頭像與健康介入進度。

## 技術堆疊

- Flutter / Dart SDK `^3.11.1`
- `http`：REST API 呼叫
- `shared_preferences`：登入狀態、個人設定與健康花園本地持久化
- `fl_chart`：姿勢報表圖表
- `url_launcher`：開啟 YouTube 推薦影片

## 開發環境

- Flutter SDK stable
- Dart SDK（由 Flutter 提供）
- VS Code 或 Android Studio
- Chrome、Android、iOS、Windows、macOS 或 Linux 執行環境

## 快速開始

```powershell
cd C:\Users\DPZ\smart_chair_app
flutter pub get
```

一般啟動：

```powershell
flutter run
```

Web 預覽建議使用固定 port，以保留瀏覽器登入與本地設定：

```powershell
powershell -ExecutionPolicy Bypass -File scripts/start_web.ps1 -FixedPort 7357 -ApiBaseUrl "https://sandbar-badass-subfloor.ngrok-free.dev/api"
```

也可以直接使用 [開啟網頁指令.txt](開啟網頁指令.txt) 內的 Web 指令。API 網址也能透過 `--dart-define` 覆寫：

```powershell
flutter run -d chrome --dart-define=API_BASE_URL=https://example.com
```

預設 API 網址目前是 `https://sandbar-badass-subfloor.ngrok-free.dev`，正式環境請使用自己的後端網址，不要依賴 ngrok 預設值。

## API 整合

目前前端使用的主要端點：

- `/api/login`
- `/api/users/exists`
- `/api/me`
- `/api/posture/history`
- `/api/chair/status`
- `/api/notification/history`
- `/api/agent`

`POST /api/agent` 的成功回應可包含：

```json
{
	"posture": "left",
	"posture_display": "身體左傾",
	"advice": "文字建議",
	"steps": [],
	"recommended_exercises": [
		{
			"id": 5,
			"name": "坐姿側身伸展",
			"target_muscles": "腰側肌群、闊背肌",
			"reps": "左右各維持 20 秒",
			"duration_sec": 40,
			"youtube_url": "https://www.youtube.com/watch?v=example",
			"youtube_title": "伸展影片",
			"description": "動作說明"
		}
	]
}
```

`advice` 與 `recommended_exercises` 是獨立資料。即使文字建議為空，只要陣列有內容，前端仍會顯示影片卡片；前端最多渲染 3 筆。

## 專案結構

```text
lib/
	main.dart
	models/
		wellness_models.dart
	services/
		api_service.dart
	state/
		chair_sync_controller.dart
		wellness_controller.dart
	screens/
		home_page.dart
		dashboard.dart
		ai_advice_page.dart
		health_garden_page.dart
		notification.dart
		setting.dart
		auth_page.dart
test/
	widget_test.dart
	wellness_controller_test.dart
```

主要資料流程：

```text
姿勢同步
	-> ChairSyncController
	-> AI Advice Page / Dashboard
	-> 接受伸展建議
	-> WellnessController
	-> 完成任務與身體回饋
	-> 健康花園、報表、通知與設定
```

## 品質檢查

```powershell
flutter analyze
flutter test
```

健康花園目前以 `SharedPreferences` 保存本地資料；若要進行跨裝置研究或正式上線，應再將介入接受、完成時間、姿勢前後分數與主觀回饋同步到後端。研究定位、資料欄位與比較實驗指標請參考 [AI_HEALTH_INTERVENTION_RESEARCH.md](AI_HEALTH_INTERVENTION_RESEARCH.md)。

## 授權

目前尚未指定授權條款。

