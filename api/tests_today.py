"""
今日坐姿摘要 GET /api/posture/today 的測試（需要資料庫）：
    python manage.py test api.tests_today
"""

from datetime import datetime, time, timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import PostureRecord, User
from api.posture_summary import today_summary


class TodaySummaryTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('sitter', password='pw-123456')
        self.start = timezone.make_aware(datetime.combine(timezone.localdate(), time(9, 0)))

    def add(self, seconds, posture, user=None):
        rec = PostureRecord.objects.create(user=user or self.user, posture=posture, source='auto')
        PostureRecord.objects.filter(pk=rec.pk).update(timestamp=self.start + timedelta(seconds=seconds))

    def summary(self, at_seconds):
        s = today_summary(self.user, now=self.start + timedelta(seconds=at_seconds))
        return s, {p['posture']: p for p in s['postures']}

    def test_minutes_follow_time_not_record_count(self):
        # 正常坐 2 分鐘只有 25 筆（每 5 秒），左傾 30 秒卻有 60 筆（每 0.5 秒）
        for i in range(25):
            self.add(i * 5, 'normal')
        for i in range(60):
            self.add(125 + i * 0.5, 'left')
        s, p = self.summary(155)
        self.assertEqual(p['normal']['minutes'], round(125 / 60, 1))
        self.assertEqual(p['left']['minutes'], 0.5)
        self.assertGreater(p['normal']['ratio'], p['left']['ratio'])   # 筆數少但時間長
        self.assertEqual((p['normal']['records'], p['left']['records']), (25, 60))

    def test_episodes_count_changes(self):
        for t, posture in ((0, 'normal'), (5, 'left'), (10, 'left'), (15, 'normal'), (20, 'left')):
            self.add(t, posture)
        _, p = self.summary(25)
        self.assertEqual(p['left']['episodes'], 2)
        self.assertEqual(p['normal']['episodes'], 2)

    def test_gap_is_capped_and_empty_stops_clock(self):
        self.add(0, 'normal')
        self.add(600, 'normal')       # 中間斷了 10 分鐘：只算 60 秒，並算新的一次
        self.add(630, 'empty')        # 離座
        self.add(2000, 'recline')     # 回來
        s, p = self.summary(2010)
        self.assertEqual(p['normal']['minutes'], round((60 + 30) / 60, 1))
        self.assertEqual(p['normal']['episodes'], 2)
        self.assertEqual(p['recline']['minutes'], round(10 / 60, 1))
        self.assertNotIn('empty', p)
        self.assertEqual(s['sitting_minutes'], round(100 / 60, 1))

    def test_yesterday_and_other_users_excluded(self):
        self.add(-10 * 3600, 'forward')                                # 昨天 23:00
        self.add(0, 'normal', user=User.objects.create_user('other'))
        s, _ = self.summary(60)
        self.assertEqual(s['postures'], [])
        self.assertEqual(s['sitting_minutes'], 0)

    def test_numbers_never_decrease_as_records_accumulate(self):
        """前端原本用最近 100 筆計算，舊資料被擠掉時數字會變小；累計今天全部資料就不會。"""
        last = 0
        for i in range(150):
            self.add(i * 2, 'left' if i < 60 else 'normal')
            _, p = self.summary(i * 2 + 1)
            self.assertGreaterEqual(p['left']['minutes'], last)
            last = p['left']['minutes']

    def test_api(self):
        client = APIClient()
        self.assertEqual(client.get('/api/posture/today').status_code, 401)
        client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.user).key}')
        res = client.get('/api/posture/today')
        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['date'], timezone.localdate().isoformat())
        self.assertIn('postures', res.data)
