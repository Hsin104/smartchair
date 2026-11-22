"""
標註資料匯出／匯入（export_remote_posture_data.py → import_remote_posture_data.py）的測試：
    python manage.py test api.tests_import
確認匯入後保留收集時間、各自的帳號與韌體判斷，重複匯入會略過。
"""

import importlib
import json
import os
import sys
import tempfile
from datetime import timedelta
from unittest import mock

from django.test import TestCase
from django.utils import timezone

from api.models import PostureRecord, User

SEAT = {'left_back': 1, 'left_mid': 1, 'left_front': 1, 'center_back': 1,
        'center_front': 1, 'right_back': 1, 'right_mid': 1, 'right_front': 1}
BACK = {'spine_upper': 1, 'spine_mid': 1, 'spine_lower': 1}


def run_script(module, args, answer='yes'):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    sys.path.insert(0, root)
    try:
        with mock.patch.object(sys, 'argv', [module] + args), mock.patch('builtins.input', return_value=answer):
            importlib.reload(importlib.import_module(module)).main()
    finally:
        sys.path.remove(root)


class ImportExportTests(TestCase):
    def setUp(self):
        self.cwd = os.getcwd()
        self.tmp = tempfile.TemporaryDirectory()
        os.chdir(self.tmp.name)
        self.when = timezone.now() - timedelta(days=3)
        for name, posture in (('collector1', 'left'), ('collector2', 'right')):
            user = User.objects.create_user(name)
            rec = PostureRecord.objects.create(user=user, posture=posture, source='real', device_posture='normal',
                                               seat_pressure_data=SEAT, back_pressure_data=BACK)
            PostureRecord.objects.filter(pk=rec.pk).update(timestamp=self.when)

    def tearDown(self):
        os.chdir(self.cwd)
        self.tmp.cleanup()

    def test_round_trip_keeps_user_time_and_device_posture(self):
        run_script('export_remote_posture_data', [])
        rows = json.load(open('posture_real_export.json', encoding='utf-8'))
        self.assertEqual({r['username'] for r in rows}, {'collector1', 'collector2'})

        # 模擬正式主機：清空後匯入
        PostureRecord.objects.all().delete()
        User.objects.filter(username='collector2').delete()          # 正式主機沒有這個帳號
        run_script('import_remote_posture_data', [])

        recs = PostureRecord.objects.filter(source='real').select_related('user')
        self.assertEqual(recs.count(), 2)
        for r in recs:
            self.assertEqual(r.timestamp, self.when)                  # 保留收集時間
            self.assertEqual(r.device_posture, 'normal')              # 保留韌體判斷
        self.assertEqual({r.user.username for r in recs}, {'collector1', 'collector2'})
        self.assertFalse(User.objects.get(username='collector2').has_usable_password())

        run_script('import_remote_posture_data', [])                  # 重複匯入
        self.assertEqual(PostureRecord.objects.filter(source='real').count(), 2)

    def test_since_filter(self):
        run_script('export_remote_posture_data', ['--since', timezone.localdate().isoformat()])
        self.assertFalse(os.path.exists('posture_real_export.json'))  # 3 天前的資料不會匯出
