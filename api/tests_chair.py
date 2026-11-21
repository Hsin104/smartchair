"""
韌體 2.0 配合項目（11/21）的測試（需要資料庫）：
    python manage.py test api.tests_chair
    - 電量：存最後一次 power、沒偵測到電池時不存數值、椅子狀態 API 回傳
    - 舊韌體 topic（chair/pressure/01 等）已移除
    - 綠環半徑 0.055（硬體建議）
"""

from unittest import mock

from django.test import TestCase
from rest_framework.test import APIClient

from api import calibration
from api.chairs import (
    battery_json, device_id_from_status_topic, device_id_from_topic, motor_topic, update_battery,
)
from api.models import Chair

SYNC = {'device_id': 'chair_TEST01', 'type': 'sync', 'norm': [0] * 11,
        'power': {'voltage_v': 7.567, 'battery_pct': 65, 'battery_present': True}}


class BatteryTests(TestCase):
    def setUp(self):
        self.chair = Chair.objects.create(device_id='chair_TEST01')

    def test_sync_payload_updates_battery(self):
        self.assertTrue(update_battery(self.chair, SYNC))
        self.chair.refresh_from_db()
        self.assertEqual((self.chair.battery_pct, self.chair.battery_voltage, self.chair.battery_present),
                         (65, 7.567, True))

    def test_change_payload_without_power_keeps_last_value(self):
        update_battery(self.chair, SYNC)
        self.assertFalse(update_battery(self.chair, {'type': 'change', 'norm': [0] * 11}))
        self.chair.refresh_from_db()
        self.assertEqual(self.chair.battery_pct, 65)

    def test_no_battery_detected_stores_no_numbers(self):
        update_battery(self.chair, {'power': {'voltage_v': 0.1, 'battery_pct': 0, 'battery_present': False}})
        self.chair.refresh_from_db()
        self.assertIs(self.chair.battery_present, False)
        self.assertIsNone(self.chair.battery_pct)
        self.assertIsNone(self.chair.battery_voltage)

    def test_status_api_returns_battery(self):
        client = APIClient()
        res = client.get('/api/chair/status', {'device_id': 'chair_TEST01'})
        self.assertIsNone(res.data['battery'])          # 還沒收到過
        update_battery(self.chair, SYNC)
        res = client.get('/api/chair/status', {'device_id': 'chair_TEST01'})
        self.assertEqual(res.data['battery']['percent'], 65)
        self.assertTrue(res.data['battery']['present'])
        listed = next(c for c in client.get('/api/chairs').data['chairs'] if c['device_id'] == 'chair_TEST01')
        self.assertEqual(listed['battery']['voltage'], 7.567)

    def test_battery_json_none_before_first_report(self):
        self.assertIsNone(battery_json(self.chair))


class TopicTests(TestCase):
    def test_new_topics_still_parsed(self):
        self.assertEqual(device_id_from_topic('chair/chair_A1B2C3/pressure', {}), 'chair_A1B2C3')
        self.assertEqual(device_id_from_status_topic('chair/chair_A1B2C3/vibration/status'), 'chair_A1B2C3')
        self.assertEqual(motor_topic('chair_A1B2C3'), 'chair/chair_A1B2C3/vibration/cmd')

    def test_legacy_topics_removed(self):
        self.assertIsNone(device_id_from_topic('chair/pressure/01', {'device_id': 'chair_01'}))
        self.assertIsNone(device_id_from_status_topic('chair/vibration/01/status'))
        self.assertEqual(motor_topic('chair_01'), 'chair/chair_01/vibration/cmd')


class NeutralRadiusTests(TestCase):
    def test_pushed_neutral_uses_hardware_radius(self):
        chair = Chair.objects.create(device_id='chair_TEST02')
        with mock.patch('api.calibration.publish_json', return_value=True) as pub:
            calibration.push_neutral(chair)
        payload = pub.call_args[0][1]
        self.assertEqual(payload['normal_radius'], 0.055)
        self.assertEqual(calibration.STABILITY_LIMIT, 0.035)
