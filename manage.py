#!/usr/bin/env python
"""Django 命令列管理工具。"""
import os
import sys


def main():
    """執行管理任務。"""
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
    try:
        from django.core.management import execute_from_command_line
    except ImportError as exc:
        raise ImportError(
            "無法匯入 Django。請確認已安裝並加入 PYTHONPATH 環境變數，"
            "也請確認虛擬環境是否已啟動。"
        ) from exc
    execute_from_command_line(sys.argv)


if __name__ == '__main__':
    main()
