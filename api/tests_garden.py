"""
健康花園點數與等級 GET /api/wellness/garden 的測試（需要資料庫）：
    python manage.py test api.tests_garden
規則需與前端 wellness_controller.dart 相同：每個動作 +10、當天首個 +5、每 100 點升一級。
"""

from datetime import timedelta

from django.test import TestCase
from django.utils import timezone
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import User, WellnessCompletion
from api.stretch import exercises_by_id


class GardenTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('gardener', password='pw-123456')
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {Token.objects.create(user=self.user).key}')
        self.ids = sorted(exercises_by_id())[:4]
        self.today = timezone.localdate()

    def done(self, exercise_id, days_ago=0, user=None):
        WellnessCompletion.objects.create(user=user or self.user, exercise_id=exercise_id, source='daily',
                                          date=self.today - timedelta(days=days_ago))

    def garden(self):
        res = self.client.get('/api/wellness/garden')
        self.assertEqual(res.status_code, 200)
        return res.data

    def test_new_user_starts_at_level_1(self):
        g = self.garden()
        self.assertEqual((g['points'], g['level'], g['points_in_level'], g['streak']), (0, 1, 0, 0))
        self.assertEqual(g['level_size'], 100)

    def test_points_follow_frontend_rules(self):
        # 今天 3 個（3×10＋5）、昨天 1 個（10＋5）＝ 50
        for i in self.ids[:3]:
            self.done(i)
        self.done(self.ids[0], days_ago=1)
        g = self.garden()
        self.assertEqual(g['points'], 50)
        self.assertEqual(g['total_completions'], 4)
        self.assertEqual(g['active_days'], 2)
        self.assertEqual(g['completed_today'], 3)

    def test_level_up_every_100_points(self):
        # 7 天各 1 個：7 ×（10＋5）＝ 105 → Lv.2、本級 5 點
        for d in range(7):
            self.done(self.ids[0], days_ago=d)
        g = self.garden()
        self.assertEqual((g['points'], g['level'], g['points_in_level']), (105, 2, 5))

    def test_streak_counts_back_from_today(self):
        for d in (0, 1, 2, 4):          # 第 3 天中斷
            self.done(self.ids[0], days_ago=d)
        self.assertEqual(self.garden()['streak'], 3)

    def test_streak_is_zero_until_first_task_today(self):
        self.done(self.ids[0], days_ago=1)
        self.done(self.ids[0], days_ago=2)
        self.assertEqual(self.garden()['streak'], 0)

    def test_only_own_completions_count(self):
        other = User.objects.create_user('someone', password='pw-123456')
        self.done(self.ids[0], user=other)
        self.assertEqual(self.garden()['points'], 0)

    def test_complete_response_includes_garden(self):
        res = self.client.post('/api/wellness/complete', {'exercise_id': self.ids[0], 'source': 'daily'}, format='json')
        self.assertEqual(res.status_code, 201)
        self.assertEqual(res.data['garden']['points'], 15)
        again = self.client.post('/api/wellness/complete', {'exercise_id': self.ids[0], 'source': 'daily'}, format='json')
        self.assertEqual(again.status_code, 200)
        self.assertEqual(again.data['garden']['points'], 15)     # 重複回報不加點

    def test_requires_login(self):
        self.assertEqual(APIClient().get('/api/wellness/garden').status_code, 401)
