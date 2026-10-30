# SmartChair 後端 API 端點總表

- Base URL：`https://sandbar-badass-subfloor.ngrok-free.dev/api`
- 使用者識別：需要登入的 API 一律用 `Authorization: Token <token>` 辨識是哪一位使用者。網址裡不放 user ID，避免有人把網址改成別人的 ID 偷看資料。
- 椅子識別：每張椅子以 ESP32 的 `device_id` 識別（`chair_` ＋ WiFi MAC 後 6 碼），第一次傳資料時自動登記，量產時不需手動建立。
- 呼叫者：App＝手機 App、ESP32＝椅子硬體、系統＝監控／內部使用

| 分類 | 方法 | URI | 說明 | 需登入 | 呼叫者 |
|---|---|---|---|---|---|
| 帳號 | GET | /users/exists | 查詢帳號是否已被註冊 | 否 | App |
| 帳號 | POST | /register | 註冊新使用者，回傳 Token | 否 | App |
| 帳號 | POST | /login | 登入，回傳 Token | 否 | App |
| 帳號 | GET | /me | 取得目前使用者資料 | 是 | App |
| 帳號 | PATCH | /me/update | 更新身高、體重、Email 等個人資料 | 是 | App |
| 帳號 | POST | /me/avatar | 更新頭像網址 | 是 | App |
| 帳號 | POST | /auth/change-password | 已登入狀態下修改密碼 | 是 | App |
| 帳號 | POST | /auth/forgot-password/request | 忘記密碼：寄送 6 碼驗證碼到 Email | 否 | App |
| 帳號 | POST | /auth/forgot-password/verify | 忘記密碼：驗證碼正確後重設密碼 | 否 | App |
| 坐姿 | POST | /posture | 上傳感測值，模型判斷坐姿後寫入紀錄 | 是 | 測試工具（ESP32 實際走 MQTT） |
| 坐姿 | GET | /posture/history | 查詢自己的坐姿歷史紀錄 | 是 | App |
| AI 建議 | POST | /agent/jobs | 送出 AI 建議任務，立即回傳任務編號（非同步） | 是 | App |
| AI 建議 | GET | /agent/jobs/{job_id} | 查詢 AI 任務狀態與結果（只能查自己的） | 是 | App |
| AI 建議 | GET | /agent/stretch-plan | 依近 7 天壞坐姿統計推薦伸展動作與影片 | 是 | App |
| AI 建議 | POST | /agent | 舊版同步 AI 建議（等 App 改用 /agent/jobs 後移除） | 是 | App |
| 座椅 | POST | /chair/checkin | 登記坐上某張椅子（body 帶 `device_id`，不帶為 chair_01），之後這張椅子的資料算在他名下 | 是 | App |
| 座椅 | POST | /chair/checkout | 登記離座 | 是 | App |
| 座椅 | GET | /chair/status | 查詢某張椅子目前是誰在使用（`?device_id=`，不帶為 chair_01） | 否 | App |
| 座椅 | GET | /chairs | 列出所有椅子、是否在線、誰在使用（椅子第一次傳資料時自動登記） | 否 | App／管理 |
| 座椅 | POST | /chair/calibrate | 以送來的感測值作為個人坐姿基準 | 是 | 測試工具 |
| 座椅 | POST | /chair/calibrate/auto | 以最近 15 秒感測資料平均作為坐姿基準 | 是 | App |
| 提醒 | GET | /notification/history | 查詢坐姿提醒通知紀錄 | 是 | App |
| 提醒 | GET | /notification/pending | 取出尚未震動的提醒並標記已送出 | 是 | ESP32 |
| 提醒 | POST | /notification/ack | 回報馬達已震動完成 | 是 | ESP32 |
| 提醒 | POST | /motor/trigger | 依坐姿手動觸發對應馬達震動 | 是 | 測試工具 |
| 系統 | GET | /health | 健康檢查：確認服務與資料庫正常 | 否 | 系統 |

共 26 支。另有 MQTT 通道（不是 HTTP API）：每張椅子發布感測資料到 `chair/{device_id}/pressure`，手動馬達指令送到 `chair/{device_id}/vibration/cmd`；舊韌體的 `chair/pressure/01`、`chair/vibration/01/cmd` 仍支援（視為 chair_01）。
