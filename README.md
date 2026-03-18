# Smart Chair App

智慧座椅管理與監控的 Flutter 應用程式。

此專案目前提供多頁面結構與基礎儀表板流程，適合作為智慧座椅資料視覺化與使用者通知功能的開發起點。

## 功能概覽

- Dashboard: 顯示座椅狀態與核心資訊入口
- Report: 圖表與報表頁面（使用 `fl_chart`）
- Alert: 通知與提醒頁面
- Setting: 使用者設定頁面
- Bottom Navigation: 以底部分頁快速切換主要功能

## 技術堆疊

- Flutter
- Dart (SDK `^3.11.1`)
- `fl_chart`

## 開發環境需求

- Flutter SDK（建議使用穩定版）
- Dart SDK（由 Flutter 一併提供）
- Android Studio / VS Code（擇一）
- 可用的模擬器或實機裝置

## 快速開始

1. 下載專案

```bash
git clone https://github.com/daipeizhen/smart_chair_app.git
cd smart_chair_app
```

2. 安裝套件

```bash
flutter pub get
```

3. 啟動 App

```bash
flutter run
```

4. （可選）檢查程式品質

```bash
flutter analyze
flutter test
```

## 專案結構

```text
lib/
	main.dart
	screens/
		dashboard.dart
		home_page.dart
		notification.dart
		report.dart
		setting.dart
```

## 版本控制流程（建議）

```bash
git checkout -b feature/your-feature-name
git add .
git commit -m "feat: add your feature"
git push -u origin feature/your-feature-name
```

## 後續可擴充方向

- 串接感測器或後端 API（座椅壓力、姿勢、使用時長）
- 新增登入與使用者權限管理
- 導入推播服務（例如 FCM）
- 增加圖表互動與資料篩選能力

## 授權

目前尚未指定授權條款。若要開源，建議加入 `MIT` 或 `Apache-2.0` 授權檔案。
