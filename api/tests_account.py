"""
刪除帳號 POST /api/me/delete 的測試（需要資料庫）：
    python manage.py test api.tests_account
"""

import tempfile
from pathlib import Path
from unittest import mock

from django.test import TestCase, override_settings
from rest_framework.authtoken.models import Token
from rest_framework.test import APIClient

from api.models import ChairSession, Notification, PostureRecord, User

SEAT = {'left_back': 10, 'left_mid': 10, 'left_front': 10, 'center_back': 10,
        'center_front': 10, 'right_back': 10, 'right_mid': 10, 'right_front': 10}


class DeleteAccountTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('alice', password='pw-123456')
        self.other = User.objects.create_user('bob', password='pw-654321')
        self.token = Token.objects.create(user=self.user)
        self.client = APIClient()
        self.client.credentials(HTTP_AUTHORIZATION=f'Token {self.token.key}')
        for source in ('real', 'real', 'auto', 'fake'):
            PostureRecord.objects.create(user=self.user, posture='left', source=source, seat_pressure_data=SEAT)
        PostureRecord.objects.create(user=self.other, posture='normal', source='auto')
        Notification.objects.create(user=self.user, message='測試通知')

    def delete(self, password):
        return self.client.post('/api/me/delete', {'password': password}, format='json')

    def test_wrong_password_keeps_everything(self):
        res = self.delete('wrong')
        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data['error_code'], 'INVALID_PASSWORD')
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())
        self.assertEqual(PostureRecord.objects.filter(user=self.user).count(), 4)

    def test_missing_password_rejected(self):
        res = self.client.post('/api/me/delete', {}, format='json')
        self.assertEqual(res.status_code, 401)
        self.assertTrue(User.objects.filter(pk=self.user.pk).exists())

    def test_requires_login(self):
        res = APIClient().post('/api/me/delete', {'password': 'pw-123456'}, format='json')
        self.assertEqual(res.status_code, 401)

    def test_delete_removes_personal_data_and_keeps_labelled_data_anonymous(self):
        res = self.delete('pw-123456')
        self.assertEqual(res.status_code, 204)
        self.assertFalse(User.objects.filter(pk=self.user.pk).exists())
        self.assertFalse(Token.objects.filter(key=self.token.key).exists())
        self.assertFalse(Notification.objects.filter(message='測試通知').exists())
        # 人工標註資料去識別化保留，其他紀錄刪除
        self.assertEqual(PostureRecord.objects.filter(user__isnull=True, source='real').count(), 2)
        self.assertFalse(PostureRecord.objects.filter(user__isnull=True).exclude(source='real').exists())
        # 別人的資料不受影響
        self.assertEqual(PostureRecord.objects.filter(user=self.other).count(), 1)
        self.assertTrue(User.objects.filter(pk=self.other.pk).exists())

    def test_old_token_stops_working(self):
        self.delete('pw-123456')
        self.assertEqual(self.client.get('/api/me').status_code, 401)

    def test_active_chair_session_is_ended_first(self):
        ChairSession.objects.create(user=self.user, is_active=True)
        seen = []
        # 在呼叫當下記錄（查詢是延遲執行的，帳號刪除後再查會是空的）
        with mock.patch('api.views._end_sessions', side_effect=lambda qs: seen.extend(qs.values_list('user_id', flat=True))):
            self.assertEqual(self.delete('pw-123456').status_code, 204)
        self.assertEqual(seen, [self.user.pk])

    def test_uploaded_avatar_file_is_removed(self):
        with tempfile.TemporaryDirectory() as media, override_settings(MEDIA_ROOT=media):
            avatar_dir = Path(media) / 'avatars'
            avatar_dir.mkdir()
            (avatar_dir / 'abc.png').write_bytes(b'png')
            (avatar_dir / 'someone_else.png').write_bytes(b'png')
            self.user.avatar_url = 'http://testserver/media/avatars/abc.png'
            self.user.save()
            self.assertEqual(self.delete('pw-123456').status_code, 204)
            self.assertFalse((avatar_dir / 'abc.png').exists())
            self.assertTrue((avatar_dir / 'someone_else.png').exists())
