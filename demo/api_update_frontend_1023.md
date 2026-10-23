# 後端 API 更新：AI 建議改成非同步（給 Android／Flutter 前端）

教授要求 AI 建議不能讓使用者一直卡著等，所以新增一組「先拿任務編號、再查結果」的 API。
舊的 `POST /api/agent` 暫時保留，App 改完之後才會移除，所以**現在的 App 不會壞**。

## 新流程

### 1. 送出任務
```
POST /api/agent/jobs
Authorization: Token <token>

{ "posture": "left", "user_message": "" }
```
欄位規則跟舊的 `/api/agent` 完全一樣（`user_message` 選填）。

立刻回應（通常 1 秒內）：
```
HTTP 202
{
  "job_id": "60c1d0d5-53c4-4f8d-a846-8ab11cd8a432",
  "status": "queued",
  "poll_url": "/api/agent/jobs/60c1d0d5-53c4-4f8d-a846-8ab11cd8a432"
}
```

### 2. 每 2 秒查一次結果
```
GET /api/agent/jobs/<job_id>
Authorization: Token <token>
```

| status | 意思 | App 要做什麼 |
|---|---|---|
| `queued` | 排隊中 | 繼續等，顯示「AI 分析中…」 |
| `running` | AI 處理中 | 繼續等 |
| `done` | 完成 | 讀取結果，停止查詢 |
| `failed` | 失敗 | 顯示 `error` 欄位的中文訊息，停止查詢 |

`done` 的回應會多出這些欄位，**格式跟舊的 `/api/agent` 一模一樣**，原本解析結果的程式可以直接沿用：
`posture`、`posture_display`、`advice`、`steps`、`recommended_exercises`

```
HTTP 200
{
  "job_id": "...",
  "status": "done",
  "created_at": "...", "started_at": "...", "finished_at": "...",
  "posture": "forward",
  "posture_display": "頭部前傾（烏龜頸）",
  "advice": "⚠️ 問題分析 ...",
  "steps": [...],
  "recommended_exercises": [...]
}
```

`failed` 範例：
```
{ "job_id": "...", "status": "failed", "error": "Agent 暫時無法使用：Physio Agent 請求逾時，請稍後再試", ... }
```

## 注意事項

- 通常 6～25 秒會完成；後端最多等 AI 60 秒，超過會變成 `failed`，所以 App 不用自己設很長的 timeout，**查詢到 90 秒還沒結果就可以停止**。
- 只能查自己的任務，查別人的會回 404。
- 使用者等待時 App 畫面不會卡住，可以讓使用者先做別的事，回來再看結果。
