import uuid

from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """使用者帳號，繼承 Django 內建的 AbstractUser（含帳號、密碼、Email）。"""
    height       = models.FloatField(null=True, blank=True, verbose_name='身高(cm)')
    weight       = models.FloatField(null=True, blank=True, verbose_name='體重(kg)')
    display_name = models.CharField(max_length=100, null=True, blank=True, verbose_name='顯示名稱')
    avatar_url   = models.CharField(max_length=500, null=True, blank=True, verbose_name='頭像 URL')

    def __str__(self):
        return self.username


class PostureRecord(models.Model):
    """坐姿紀錄，儲存每次感測器的數值與辨識結果。"""

    # 6 種坐姿類別
    POSTURE_CHOICES = [
        ('normal',    '標準坐姿'),
        ('left',      '左傾'),
        ('right',     '右傾'),
        ('forward',   '前傾（烏龜頸）'),
        ('recline',   '過度後仰'),
        ('sedentary', '久坐未動'),
    ]

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='posture_records', verbose_name='使用者'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='時間戳')
    posture = models.CharField(max_length=20, choices=POSTURE_CHOICES, verbose_name='坐姿類別')

    SOURCE_CHOICES = [
        ('real', '真實採集'),
        ('fake', '假資料'),
        ('auto', '自動預測'),
    ]

    # 感測器原始數值（座墊 8 個 FSR、椅背 3 個 FSR）
    seat_pressure_data = models.JSONField(null=True, blank=True, verbose_name='座墊壓力感測數值（8點）')
    back_pressure_data = models.JSONField(null=True, blank=True, verbose_name='椅背脊椎壓力感測數值（3點）')
    physio_advice      = models.TextField(null=True, blank=True, verbose_name='AI 物理治療建議')
    source             = models.CharField(max_length=10, choices=SOURCE_CHOICES, default='auto', verbose_name='資料來源')
    # 模型 softmax 最大機率值（信心分數），0~1；規則層覆蓋判斷（極端姿勢）或手動輸入 posture 時無意義，留 null
    confidence         = models.FloatField(null=True, blank=True, verbose_name='模型信心分數')
    # ESP32 依重心規則自己判斷的坐姿（payload 的 pose.label，已轉成跟 posture 相同的代碼）。
    # 正式紀錄以雲端 AI 模型的 posture 為準，這欄留作對照：兩者不一致的比例可用來評估邊緣端判斷的可靠度
    device_posture     = models.CharField(max_length=20, null=True, blank=True, verbose_name='椅子端判斷坐姿')
    # 來自哪張椅子：用來計算每張椅子自己的預設中立點（api/calibration.py update_default_neutrals）
    chair              = models.ForeignKey(
        'Chair', on_delete=models.SET_NULL, null=True, blank=True, related_name='posture_records',
        verbose_name='椅子',
    )

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '坐姿紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.posture} - {self.timestamp}'


class Notification(models.Model):
    """推播通知紀錄，記錄傳送給使用者的振動提醒。"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notifications', verbose_name='使用者'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='時間戳')
    # TextField 而非 CharField：週報通知（weekly_advice）會塞入完整 Physio Agent 建議文字，長度不固定
    message = models.TextField(verbose_name='通知內容')
    is_sent = models.BooleanField(default=False, verbose_name='是否已發送')

    # 通知類型：前端依此決定顯示方式（例如自動離座要跳出「重新入座」），
    # GET /notification/pending（硬體輪詢震動用）只回傳 posture，避免自動離座、週報也觸發震動
    KIND_POSTURE       = 'posture'
    KIND_AUTO_CHECKOUT = 'auto_checkout'
    KIND_WEEKLY        = 'weekly'
    KIND_CHOICES = [
        (KIND_POSTURE,       '坐姿提醒'),
        (KIND_AUTO_CHECKOUT, '自動離座'),
        (KIND_WEEKLY,        '每週報告'),
    ]
    kind = models.CharField(max_length=20, choices=KIND_CHOICES, default=KIND_POSTURE, verbose_name='類型')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '通知紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.message}'


class Chair(models.Model):
    """
    一張實體智慧椅，以 ESP32 的 device_id 識別（例如 chair_A1B2C3）。

    後端第一次收到某張椅子的 MQTT 資料就會自動登記，量產時不需要先手動建立。
    舊韌體固定送 chair/pressure/01、device_id 為 chair_01，視為 LEGACY_DEVICE_ID 這張椅子；
    App 呼叫 checkin 沒指定椅子時也預設坐這張，舊版 App 不用改。
    """
    LEGACY_DEVICE_ID = 'chair_01'

    device_id  = models.CharField(max_length=40, unique=True, verbose_name='裝置 ID')
    name       = models.CharField(max_length=100, blank=True, verbose_name='名稱（例如擺放位置）')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='首次登記時間')
    last_seen  = models.DateTimeField(null=True, blank=True, verbose_name='最後收到資料時間')

    # 這張椅子自己的預設中立點（沒校正的人坐時用）：由這張椅子累積的正常坐姿資料算出，
    # 每週重新計算（python manage.py update_default_neutral），資料不足時為 null、改用全部椅子的平均
    default_neutral_x  = models.FloatField(null=True, blank=True, verbose_name='預設中立點 X')
    default_neutral_y  = models.FloatField(null=True, blank=True, verbose_name='預設中立點 Y')
    default_samples    = models.PositiveIntegerField(default=0, verbose_name='預設中立點取樣筆數')
    default_updated_at = models.DateTimeField(null=True, blank=True, verbose_name='預設中立點計算時間')

    class Meta:
        ordering = ['device_id']
        verbose_name = '智慧椅'

    def __str__(self):
        return self.name or self.device_id


class UserCalibration(models.Model):
    """
    使用者的個人坐姿校正（坐正時的平均壓力與重心），記在使用者身上，換椅子也通用，只要校正一次。

    - neutral_x / neutral_y：個人化中立點，入座時透過 MQTT 送給那張椅子（chair/{device_id}/config），
      ESP32 用它判斷坐姿與震動提醒，取代固定的感測器座標平均
    - baseline_seat / baseline_back：給雲端 AI 坐姿模型的校準模式（posture_model_calibrated）
    """
    user          = models.OneToOneField(User, on_delete=models.CASCADE, related_name='calibration')
    neutral_x     = models.FloatField(verbose_name='中立點 X（0 左～1 右）')
    neutral_y     = models.FloatField(verbose_name='中立點 Y（0 後～1 前）')
    baseline_seat = models.JSONField(verbose_name='坐正時座墊平均壓力')
    baseline_back = models.JSONField(null=True, blank=True, verbose_name='坐正時椅背平均壓力')
    samples       = models.PositiveIntegerField(default=0, verbose_name='取樣筆數')
    device_id     = models.CharField(max_length=40, blank=True, verbose_name='在哪張椅子校正')
    METHOD_DEVICE  = 'device'
    METHOD_BACKEND = 'backend'
    method        = models.CharField(
        max_length=10, default=METHOD_BACKEND, verbose_name='計算方式',
        choices=[(METHOD_DEVICE, '椅子計算'), (METHOD_BACKEND, '後端計算（備案）')],
    )
    calibrated_at = models.DateTimeField(auto_now=True, verbose_name='校正時間')

    class Meta:
        verbose_name = '使用者坐姿校正'

    def __str__(self):
        return f'{self.user.username}（{self.neutral_x:.3f}, {self.neutral_y:.3f}）'


class CalibrationRequest(models.Model):
    """
    一次校正的進度（App 用 GET /chair/calibration 查詢）。

    正式流程由椅子計算：後端送 calibrate 指令，椅子取樣 5 秒後回報 calibrated／calibration_failed；
    超過 DEVICE_TIMEOUT_SECONDS 沒回應時，改用後端收到的資料計算（備案）。
    """
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name='calibration_requests')
    chair       = models.ForeignKey('Chair', on_delete=models.CASCADE, related_name='calibration_requests')
    status      = models.CharField(
        max_length=10, default=STATUS_RUNNING, verbose_name='狀態',
        choices=[(STATUS_RUNNING, '校正中'), (STATUS_DONE, '完成'), (STATUS_FAILED, '失敗')],
    )
    method      = models.CharField(max_length=10, blank=True, verbose_name='計算方式（device／backend）')
    reason      = models.CharField(max_length=40, blank=True, verbose_name='失敗原因代碼')
    created_at  = models.DateTimeField(auto_now_add=True, verbose_name='開始時間')
    finished_at = models.DateTimeField(null=True, blank=True, verbose_name='結束時間')

    class Meta:
        ordering = ['-created_at']
        verbose_name = '校正請求'


class SystemSetting(models.Model):
    """系統層級的設定值（key／JSON value），例如全部椅子平均的預設中立點 default_neutral。"""
    key        = models.CharField(max_length=50, unique=True)
    value      = models.JSONField()
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = '系統設定'

    def __str__(self):
        return self.key


class ChairSession(models.Model):
    """記錄誰坐在哪張椅子上：每張椅子最多一筆 is_active=True，每位使用者同一時間也只坐一張。"""
    chair         = models.ForeignKey(
        Chair, on_delete=models.CASCADE, related_name='sessions', null=True, blank=True, verbose_name='椅子'
    )
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chair_sessions')
    started_at    = models.DateTimeField(auto_now_add=True)
    is_active     = models.BooleanField(default=True)
    baseline_seat = models.JSONField(null=True, blank=True, verbose_name='校準基準值（座墊）')
    baseline_back = models.JSONField(null=True, blank=True, verbose_name='校準基準值（椅背）')

    class Meta:
        verbose_name = '座椅使用紀錄'

    def __str__(self):
        return f'{self.chair} — {self.user.username} — {"使用中" if self.is_active else "已結束"}'


class AgentLog(models.Model):
    """Physio Agent 對話紀錄，儲存 LLM 的輸入與輸出。"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_logs', verbose_name='使用者'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='時間戳')
    posture = models.CharField(max_length=20, verbose_name='觸發坐姿')
    user_message = models.TextField(blank=True, verbose_name='使用者輸入')
    agent_reply = models.TextField(verbose_name='Agent 回覆')
    steps = models.JSONField(default=list, blank=True, verbose_name='ReAct 執行步驟')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Agent 對話紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.posture} - {self.timestamp}'


class PasswordResetCode(models.Model):
    """忘記密碼用的一次性驗證碼，寄送到使用者註冊時填寫的 Email。"""

    user       = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='password_reset_codes', verbose_name='使用者'
    )
    code       = models.CharField(max_length=6, verbose_name='驗證碼')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='建立時間')
    is_used    = models.BooleanField(default=False, verbose_name='是否已使用')

    class Meta:
        ordering = ['-created_at']
        verbose_name = '密碼重設驗證碼'

    def __str__(self):
        return f'{self.user.username} - {self.code} - {"已使用" if self.is_used else "未使用"}'


class MotorLog(models.Model):
    """馬達觸發紀錄，記錄每次震動馬達的觸發坐姿與啟動清單。"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='motor_logs', verbose_name='使用者'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='時間戳')
    posture   = models.CharField(max_length=20, verbose_name='觸發坐姿')
    motors    = models.JSONField(verbose_name='啟動馬達清單')  # e.g. ['M1', 'M2']
    reason    = models.CharField(max_length=100, verbose_name='觸發原因')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '馬達觸發紀錄'

    def __str__(self):
        return f'{self.user.username} — {self.posture} — {",".join(self.motors)}'


class AgentJob(models.Model):
    """
    Physio Agent 非同步任務。

    App 呼叫 POST /api/agent/jobs 只建立一筆 queued 任務就立刻回應（202），
    由獨立的 agent_worker（python manage.py agent_worker）以 async/await 同時處理多筆，
    App 再用 GET /api/agent/jobs/<id> 查詢結果。OpenAI 回應再慢也不會佔住網頁伺服器的執行緒。
    """

    STATUS_QUEUED  = 'queued'
    STATUS_RUNNING = 'running'
    STATUS_DONE    = 'done'
    STATUS_FAILED  = 'failed'
    STATUS_CHOICES = [
        (STATUS_QUEUED,  '排隊中'),
        (STATUS_RUNNING, '處理中'),
        (STATUS_DONE,    '完成'),
        (STATUS_FAILED,  '失敗'),
    ]

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user         = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_jobs', verbose_name='使用者'
    )
    posture      = models.CharField(max_length=20, verbose_name='坐姿')
    user_message = models.TextField(blank=True, verbose_name='使用者補充描述')
    status       = models.CharField(
        max_length=10, choices=STATUS_CHOICES, default=STATUS_QUEUED, verbose_name='狀態'
    )
    # 完成時的完整回應（posture、posture_display、advice、steps、recommended_exercises），
    # 格式與舊的同步 POST /api/agent 相同，App 不用改解析邏輯
    result       = models.JSONField(null=True, blank=True, verbose_name='結果')
    error        = models.TextField(blank=True, verbose_name='失敗原因')
    created_at   = models.DateTimeField(auto_now_add=True, verbose_name='建立時間')
    started_at   = models.DateTimeField(null=True, blank=True, verbose_name='開始處理時間')
    finished_at  = models.DateTimeField(null=True, blank=True, verbose_name='完成時間')

    class Meta:
        ordering = ['created_at']
        verbose_name = 'Agent 非同步任務'
        # worker 每次輪詢都查「狀態 = queued、依建立時間排序」，加複合索引避免任務累積後全表掃描
        indexes = [models.Index(fields=['status', 'created_at'])]

    def __str__(self):
        return f'{self.user.username} — {self.posture} — {self.get_status_display()}'


class DailyStretchPlan(models.Model):
    """
    健康花園的每日任務：每人每天一份，同一天內固定不變（前端用任務 id 判斷今天做過沒）。
    使用者當天之後才問 AI，只換掉跟 AI 建議重複的任務，其他任務 id 不變。
    """

    SOURCE_AI      = 'ai'        # AI 依 7 天坐姿挑選並寫個人化說明
    SOURCE_RULE    = 'rule'      # AI 失敗時，依坐姿頻率查表
    SOURCE_GENERAL = 'general'   # 坐姿資料不足，通用安全動作
    SOURCE_CHOICES = [(SOURCE_AI, 'AI'), (SOURCE_RULE, '查表備援'), (SOURCE_GENERAL, '通用動作')]

    user         = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='stretch_plans', verbose_name='使用者'
    )
    date         = models.DateField(verbose_name='日期（台灣時間）')
    tasks        = models.JSONField(default=list, verbose_name='任務')
    source       = models.CharField(max_length=10, choices=SOURCE_CHOICES, verbose_name='產生方式')
    # 去重時參考的最近一次 AI 建議；有更新的 AI 建議時才需要重新檢查重複
    agent_job_id = models.UUIDField(null=True, blank=True, verbose_name='參考的 AI 建議任務')
    generated_at = models.DateTimeField(auto_now_add=True, verbose_name='產生時間')
    updated_at   = models.DateTimeField(auto_now=True, verbose_name='更新時間')

    class Meta:
        unique_together = [('user', 'date')]
        verbose_name = '每日伸展任務'

    def __str__(self):
        return f'{self.user.username} — {self.date} — {self.source}'


class WellnessCompletion(models.Model):
    """使用者完成的伸展動作（每日任務或 AI 建議），同一動作同一天只記一次。"""

    SOURCE_CHOICES = [('daily', '每日任務'), ('ai', 'AI 建議')]

    user         = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='wellness_completions', verbose_name='使用者'
    )
    exercise_id  = models.PositiveIntegerField(verbose_name='動作編號（知識庫）')
    source       = models.CharField(max_length=10, choices=SOURCE_CHOICES, verbose_name='來源')
    feedback     = models.CharField(max_length=200, blank=True, verbose_name='使用者回饋')
    date         = models.DateField(verbose_name='日期（台灣時間）')
    completed_at = models.DateTimeField(auto_now_add=True, verbose_name='完成時間')

    class Meta:
        ordering = ['-completed_at']
        unique_together = [('user', 'exercise_id', 'date')]
        verbose_name = '伸展完成紀錄'

    def __str__(self):
        return f'{self.user.username} — {self.exercise_id} — {self.date}'
