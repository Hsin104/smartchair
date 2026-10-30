"""
重新計算每張椅子與全部椅子的預設中立點（沒校正的人坐時使用），並送給相關的椅子。

用法：python manage.py update_default_neutral
建議每週執行一次（crontab，例如每週日凌晨）：
    0 3 * * 0 cd /path/to/smartchair && docker compose exec -T django python manage.py update_default_neutral

計算方式與分層規則見 api/calibration.py 的 update_default_neutrals、demo/calibration_design.md 第三節。
"""

from django.core.management.base import BaseCommand

from api.calibration import DEFAULT_MIN_SAMPLES, update_default_neutrals


class Command(BaseCommand):
    help = '重新計算每張椅子與全部椅子的預設中立點'
    requires_system_checks = []   # 不載入 views（TensorFlow 模型），只需要資料庫

    def handle(self, *args, **options):
        summary = update_default_neutrals()
        for key, info in summary.items():
            note = info.get('source', '')
            self.stdout.write(f'{key:16} 中立點 {info["neutral"]}  取樣 {info["samples"]} 筆  {note}')
        self.stdout.write(self.style.SUCCESS(f'完成（椅子需 ≥ {DEFAULT_MIN_SAMPLES} 筆才用自己的預設值）'))
