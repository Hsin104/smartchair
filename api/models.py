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

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '通知紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.message}'


class ChairSession(models.Model):
    """記錄目前正在使用椅子的使用者（全系統只會有一筆 is_active=True）。"""
    user          = models.ForeignKey(User, on_delete=models.CASCADE, related_name='chair_sessions')
    started_at    = models.DateTimeField(auto_now_add=True)
    is_active     = models.BooleanField(default=True)
    baseline_seat = models.JSONField(null=True, blank=True, verbose_name='校準基準值（座墊）')
    baseline_back = models.JSONField(null=True, blank=True, verbose_name='校準基準值（椅背）')

    class Meta:
        verbose_name = '座椅使用紀錄'

    def __str__(self):
        return f'{self.user.username} — {"使用中" if self.is_active else "已結束"}'


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
