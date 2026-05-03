from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    """使用者帳號，繼承 Django 內建的 AbstractUser（含帳號、密碼、Email）。"""
    height = models.FloatField(null=True, blank=True, verbose_name='身高(cm)')
    weight = models.FloatField(null=True, blank=True, verbose_name='體重(kg)')

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

    # 感測器原始數值（座墊 8 個 FSR、椅背 3 個 FSR）
    seat_pressure_data = models.JSONField(null=True, blank=True, verbose_name='座墊壓力感測數值（8點）')
    back_pressure_data = models.JSONField(null=True, blank=True, verbose_name='椅背脊椎壓力感測數值（3點）')

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
    message = models.CharField(max_length=255, verbose_name='通知內容')
    is_sent = models.BooleanField(default=False, verbose_name='是否已發送')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = '通知紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.message}'


class AgentLog(models.Model):
    """Physio Agent 對話紀錄，儲存 LLM 的輸入與輸出。"""

    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='agent_logs', verbose_name='使用者'
    )
    timestamp = models.DateTimeField(auto_now_add=True, verbose_name='時間戳')
    posture = models.CharField(max_length=20, verbose_name='觸發坐姿')
    user_message = models.TextField(blank=True, verbose_name='使用者輸入')
    agent_reply = models.TextField(verbose_name='Agent 回覆')

    class Meta:
        ordering = ['-timestamp']
        verbose_name = 'Agent 對話紀錄'

    def __str__(self):
        return f'{self.user.username} - {self.posture} - {self.timestamp}'
