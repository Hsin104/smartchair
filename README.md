# Smart Chair App

智慧座椅 Flutter 前端，提供 Web 與多平台的坐姿監測、AI 建議、通知、個人設定及健康介入任務。

## 目前功能

- **儀表板**：即時姿勢、分數、風險、就座時間、提醒次數與健康花園進度。
- **AI 物理治療師**：透過 `/api/agent/jobs` 非同步取得文字建議與伸展影片。
- **推薦伸展影片**：最多顯示 3 張影片卡片，可直接開啟 YouTube。
- **健康養成花園**：接受建議、完成每日任務、回報身體感受、累積能量與連續天數。
- **歷史報表**：已整合在「健康總覽」，顯示姿勢分布、平均分數、提醒次數、有效健康介入與最近紀錄。
- **通知**：姿勢提醒紀錄與當日健康介入數。
- **設定**：帳號、個人資料、頭像與健康介入進度。
- **頭像**：Web 端使用 multipart 上傳 PNG/JPG/JPEG，最大 5 MB；圖片顯示會帶 ngrok header 下載 bytes，避免免費網域警告頁造成破圖。

## 技術堆疊

- Flutter / Dart SDK `^3.11.1`
- `http`：REST API 呼叫
- `shared_preferences`：登入狀態、個人設定與健康花園本地持久化
- `fl_chart`：姿勢報表圖表
- `url_launcher`：開啟 YouTube 推薦影片
- `file_picker`：Web 與桌面端選擇頭像檔案

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
- `/api/register`
- `/api/users/exists`
- `/api/me`
- `/api/me/update`
- `/api/me/avatar/upload`（multipart 欄位 `file`）
- `/api/posture/history`
- `/api/chair/checkin`
- `/api/chair/calibration`
- `/api/chair/checkout`
- `/api/chair/status`
- `/api/notification/history`
- `/api/agent/jobs`
- `/api/agent/jobs/<job_id>`
- `/api/agent/stretch-plan`
- `/api/wellness/complete`
- `/api/wellness/history`

AI 建議流程：

1. `POST /api/agent/jobs` 取得 `job_id`。
2. 每 2 秒查詢 `/api/agent/jobs/<job_id>`。
3. `done` 時顯示 `advice`、`posture_display` 和最多 3 筆 `recommended_exercises`。

健康花園每天從 `/api/agent/stretch-plan` 取得一次 AI 伸展計畫，只顯示 3 個任務，並在當天以本地快取保持任務一致；下一天才重新取得計畫。

每日任務使用後端回傳的數字 `id` 與 `group` 判斷動作，AI 建議完成後會重新取得今日計畫，讓後端替換與 AI 建議重複的動作。完成任務會呼叫 `/api/wellness/complete`，登入時也會從 `/api/wellness/history` 同步跨裝置的完成紀錄。

登入 API 使用 `Authorization: Token <token>`，不是 `Bearer`。Web 啟動時會自動加入 ngrok 所需的 `ngrok-skip-browser-warning` header。

通知頁的「周報」只顯示後端 `/api/notification/history` 回傳的 `kind: weekly` 資料，不在前端自行產生周報。坐姿同步遇到暫時的空回應時會保留上一次有效坐姿，避免畫面因網路波動清空。

頭像上傳不使用 base64，前端會以 `multipart/form-data` 上傳原始圖片。後端會驗證圖片實際內容、限制 5 MB，並回傳新的 `avatar_url`。

登入後的顯示名稱會透過 `PATCH /api/me/update` 的 `display_name` 欄位儲存到後端；重新登入、換瀏覽器或換裝置後，前端會從 `GET /api/me` 讀取名稱。

## 專案結構

```text
lib/
	main.dart
	models/
		wellness_models.dart
	services/
		api_service.dart
		browser_notification_stub.dart
		browser_notification_web.dart
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
