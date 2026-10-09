"""
坐姿辨識模型 — 混淆矩陣與各類別 precision/recall 分析

分析「目前已部署的模型」在真實標記資料（source='real'）上的分類表現，
系統化找出常見誤判組合（例如 forward 常被誤判成 normal），取代過去
「發現一個異常就手動加規則修正」的見招拆招方式。

注意：這裡用的是模型訓練時「看過」的資料（非獨立測試集），報告的準確率會
比 train_model_dl.py 訓練時的測試集準確率樂觀；本腳本的目的是找出誤判
模式（confusion matrix），不是重新衡量泛化能力。

執行方式：
    python analyze_posture_model.py              # 未校準模型（預設，real 資料需為絕對值格式）
    python analyze_posture_model.py --calibrated # 校準模型（real 資料需為 delta 值格式）

輸出：
    - 終端機列印混淆矩陣 + classification_report + 最常見誤判組合
    - charts/confusion_matrix_<mode>.png 混淆矩陣熱力圖
"""

import os
import sys
import django
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import confusion_matrix, classification_report, accuracy_score
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import seaborn as sns

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

import tensorflow as tf
from api.models import PostureRecord

CALIBRATED_MODE = '--calibrated' in sys.argv

MODEL_PATH  = 'posture_model_calibrated.keras' if CALIBRATED_MODE else 'posture_model_dl.keras'
LABEL_PATH  = 'label_encoder_calibrated.pkl'   if CALIBRATED_MODE else 'label_encoder_dl.pkl'
SCALER_PATH = 'feature_scaler_calibrated.pkl'  if CALIBRATED_MODE else 'feature_scaler_dl.pkl'

# 20 個特徵：椅墊原始值 8 個 + 椅墊區域統計 4 個 + 椅背原始值 3 個 + 椅背衍生 5 個
# （與 train_model_dl.py 的 FEATURES 定義一致，確保分析用的特徵跟訓練時相同）
FEATURES = [
    'left_back', 'left_mid', 'left_front',
    'center_back', 'center_front',
    'right_back', 'right_mid', 'right_front',
    'left_delta', 'right_delta', 'front_delta', 'back_delta',
    'spine_upper', 'spine_mid', 'spine_lower',
    'spine_total', 'spine_ratio', 'spine_upper_ratio', 'spine_lower_ratio', 'spine_upper_lower_delta',
]


def _is_delta_style(record):
    """real 資料依採集方式分兩種格式：校準模式存 delta 值（可負），未校準模式存絕對值。"""
    return any(v < 0 for v in (record.seat_pressure_data or {}).values())


def load_real_data(source='real'):
    qs = PostureRecord.objects.filter(
        source=source,
        seat_pressure_data__isnull=False,
        back_pressure_data__isnull=False,
    ).exclude(posture__in=['sedentary', 'empty'])
    qs = [r for r in qs if r.back_pressure_data and _is_delta_style(r) == CALIBRATED_MODE]

    rows = []
    for r in qs:
        seat = r.seat_pressure_data or {}
        back = r.back_pressure_data or {}
        rows.append({
            'posture':      r.posture,
            'left_back':    seat.get('left_back',    0),
            'left_mid':     seat.get('left_mid',     0),
            'left_front':   seat.get('left_front',   0),
            'center_back':  seat.get('center_back',  0),
            'center_front': seat.get('center_front', 0),
            'right_back':   seat.get('right_back',   0),
            'right_mid':    seat.get('right_mid',    0),
            'right_front':  seat.get('right_front',  0),
            'spine_upper':  back.get('spine_upper',   0),
            'spine_mid':    back.get('spine_mid',     0),
            'spine_lower':  back.get('spine_lower',   0),
        })
    return pd.DataFrame(rows)


def build_features(df):
    seat_total = (df['left_back'] + df['left_mid'] + df['left_front'] +
                  df['center_back'] + df['center_front'] +
                  df['right_back'] + df['right_mid'] + df['right_front'])

    if CALIBRATED_MODE:
        df['left_delta']  = df['left_back'] + df['left_mid'] + df['left_front']
        df['right_delta'] = df['right_back'] + df['right_mid'] + df['right_front']
        df['front_delta'] = df['left_front'] + df['center_front'] + df['right_front']
        df['back_delta']  = df['left_back'] + df['center_back'] + df['right_back']
    else:
        seat_total_safe = seat_total + 1e-6
        df['left_delta']  = (df['left_back'] + df['left_mid'] + df['left_front']) / seat_total_safe
        df['right_delta'] = (df['right_back'] + df['right_mid'] + df['right_front']) / seat_total_safe
        df['front_delta'] = (df['left_front'] + df['center_front'] + df['right_front']) / seat_total_safe
        df['back_delta']  = (df['left_back'] + df['center_back'] + df['right_back']) / seat_total_safe

    df['spine_total'] = df['spine_upper'] + df['spine_mid'] + df['spine_lower']
    spine_total_safe  = df['spine_total'].where(df['spine_total'].abs() > 1e-6, 1e-6)
    total_all         = seat_total + df['spine_total']
    total_all_safe    = total_all.where(total_all.abs() > 1e-6, 1e-6)

    df['spine_ratio']             = df['spine_total'] / total_all_safe
    df['spine_upper_ratio']       = df['spine_upper'] / spine_total_safe
    df['spine_lower_ratio']       = df['spine_lower'] / spine_total_safe
    df['spine_upper_lower_delta'] = df['spine_upper'] - df['spine_lower']
    return df


def main():
    mode_label = '校準（delta）' if CALIBRATED_MODE else '未校準（絕對值）'
    print(f'模式：{mode_label}')

    df = load_real_data(source='real')
    data_source = 'real（真實採集）'
    if len(df) < 20:
        print(f'[Warning] 真實資料（含椅背感測器）僅 {len(df)} 筆，不足以分析，改用合成測試資料（source=fake）')
        print('[Warning] fake 資料是依規則生成的合成樣本，不是真人實測，結果僅供初步檢查模型決策邊界，'
              '不能取代真實資料評測——這是目前真實數據採集的缺口，建議排進後續採集計畫')
        df = load_real_data(source='fake')
        data_source = 'fake（合成測試資料，非真人實測）'

    print(f'可用資料：{len(df)} 筆（來源：{data_source}）')
    if len(df) < 20:
        print('[Error] 資料量過少，無法做有意義的分析')
        sys.exit(1)

    df = build_features(df)

    model   = tf.keras.models.load_model(MODEL_PATH)
    encoder = joblib.load(LABEL_PATH)
    scaler  = joblib.load(SCALER_PATH)

    X = df[FEATURES].values.astype(np.float32)
    y_true = df['posture'].values

    X_norm = scaler.transform(X)
    probs  = model.predict(X_norm, verbose=0)
    y_pred = encoder.inverse_transform(np.argmax(probs, axis=1))

    acc = accuracy_score(y_true, y_pred)
    print(f'\n整體準確率：{acc:.4f}（{acc * 100:.2f}%），資料來源：{data_source}')
    print('※ 此為模型訓練時已見過的資料，非獨立測試集，數字會偏樂觀，僅供找出誤判模式參考')

    labels = sorted(set(y_true) | set(y_pred))
    cm = confusion_matrix(y_true, y_pred, labels=labels)

    print('\n混淆矩陣（列=實際，欄=預測）：')
    print('          ' + ''.join(f'{l:>10}' for l in labels))
    for i, l in enumerate(labels):
        print(f'{l:>10}' + ''.join(f'{cm[i][j]:>10}' for j in range(len(labels))))

    print('\n各類別 precision/recall/f1：')
    report = classification_report(y_true, y_pred, zero_division=0)
    for line in report.split('\n'):
        if line.strip():
            print(f'  {line}')

    print('\n最常見誤判組合（實際 → 誤判為，次數）：')
    mistakes = [
        (labels[i], labels[j], cm[i][j])
        for i in range(len(labels)) for j in range(len(labels))
        if i != j and cm[i][j] > 0
    ]
    mistakes.sort(key=lambda x: -x[2])
    if not mistakes:
        print('  （無誤判，所有樣本皆分類正確）')
    for actual, pred, count in mistakes[:10]:
        print(f'  {actual} → {pred}：{count} 次')

    mode_suffix = 'calibrated' if CALIBRATED_MODE else 'uncalibrated'
    os.makedirs('charts', exist_ok=True)
    out_path = f'charts/confusion_matrix_{mode_suffix}.png'

    plt.figure(figsize=(7, 6))
    sns.heatmap(cm, annot=True, fmt='d', xticklabels=labels, yticklabels=labels, cmap='Blues')
    plt.xlabel('Predicted')
    plt.ylabel('Actual')
    plt.title(f'Posture Model Confusion Matrix ({mode_suffix})')
    plt.tight_layout()
    plt.savefig(out_path, dpi=150)
    print(f'\n混淆矩陣圖已存至：{out_path}')


if __name__ == '__main__':
    main()
