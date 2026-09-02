"""
深度學習坐姿分類模型訓練腳本

架構：多層感知器（MLP），20 個特徵輸入（椅墊 12 個 + 椅背 8 個）

執行方式：
    python train_model_dl.py                            # 未校準模型
    python train_model_dl.py --calibrated               # 校準模型（自動優先使用真實資料）
    python train_model_dl.py --calibrated --real-only   # 校準模型（強制僅用真實資料）
"""

import os
import sys
import django
import numpy as np
import pandas as pd
import joblib
from sklearn.model_selection import train_test_split
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.metrics import classification_report, accuracy_score

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

try:
    import tensorflow as tf
    from tensorflow import keras
except ImportError:
    print('[Error] 請先安裝 TensorFlow：pip install tensorflow')
    sys.exit(1)

from api.models import PostureRecord

CALIBRATED_MODE = '--calibrated' in sys.argv
REAL_ONLY_MODE  = '--real-only'  in sys.argv

DL_MODEL_PATH  = 'posture_model_calibrated.keras' if CALIBRATED_MODE else 'posture_model_dl.keras'
DL_LABEL_PATH  = 'label_encoder_calibrated.pkl'   if CALIBRATED_MODE else 'label_encoder_dl.pkl'
DL_SCALER_PATH = 'feature_scaler_calibrated.pkl'  if CALIBRATED_MODE else 'feature_scaler_dl.pkl'

# 20 個特徵：椅墊原始值 8 個 + 椅墊區域統計 4 個 + 椅背原始值 3 個 + 椅背衍生 5 個
# 校準模式：椅墊/椅背原始值皆為 delta 值，統計/衍生特徵為 delta 的加總或比例
FEATURES = [
    'left_back', 'left_mid', 'left_front',
    'center_back', 'center_front',
    'right_back', 'right_mid', 'right_front',
    'left_delta', 'right_delta', 'front_delta', 'back_delta',
    'spine_upper', 'spine_mid', 'spine_lower',
    'spine_total', 'spine_ratio', 'spine_upper_ratio', 'spine_lower_ratio', 'spine_upper_lower_delta',
]


def _is_delta_style(record):
    """
    real 資料依採集方式分兩種格式，不能混用：
      - 校準模式（collect_data.py 預設）存 delta 值，相對基準值，可正可負
      - 未校準模式（collect_data.py --raw）存原始絕對讀值，FSR 讀數理論上不會是負的
    用「有沒有負值」判斷是哪一種格式。
    """
    return any(v < 0 for v in (record.seat_pressure_data or {}).values())


def load_data():
    print('[1/4] 從資料庫讀取數據...')
    qs = PostureRecord.objects.filter(
        seat_pressure_data__isnull=False,
        back_pressure_data__isnull=False,
    ).exclude(posture__in=['sedentary', 'empty'])

    # 排除椅背資料為空字典（尚未接上椅背感測器時期的舊資料，20 特徵模型無法使用）
    qs = [r for r in qs if r.back_pressure_data]

    # 排除格式跟目前訓練模式不符的 real 資料（delta 資料訓練未校準模式、
    # 或原始值資料訓練校準模式，preprocess() 會誤解讀，必須先排除）
    mismatched = sum(1 for r in qs if r.source == 'real' and _is_delta_style(r) != CALIBRATED_MODE)
    qs = [r for r in qs if not (r.source == 'real' and _is_delta_style(r) != CALIBRATED_MODE)]
    if mismatched:
        print(f'   [略過] {mismatched} 筆真實資料格式跟目前訓練模式（'
              f'{"校準" if CALIBRATED_MODE else "未校準"}）不符，已排除')

    real_count = sum(1 for r in qs if r.source == 'real')
    fake_count = sum(1 for r in qs if r.source == 'fake')
    auto_count = len(qs) - real_count - fake_count
    print(f'   資料庫（含椅背資料）：真實 {real_count} 筆 / 假資料 {fake_count} 筆 / 自動 {auto_count} 筆')

    if REAL_ONLY_MODE:
        if real_count < 50:
            print(f'   [Error] --real-only 需要至少 50 筆真實資料，目前只有 {real_count} 筆')
            print(f'   請先執行 python collect_data.py{"" if CALIBRATED_MODE else " --raw"} 採集真實資料')
            sys.exit(1)
        qs = [r for r in qs if r.source == 'real']
        print(f'   [real-only] 僅使用真實資料 {real_count} 筆')
    elif real_count >= 50:
        qs = [r for r in qs if r.source == 'real']
        print(f'   [auto] 真實資料已足夠，僅使用真實資料 {real_count} 筆（略過假資料）')
    else:
        print(f'   [auto] 真實資料不足，使用全部資料（真實 + 假資料）')

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
    df = pd.DataFrame(rows)
    print(f'   訓練用資料：{len(df)} 筆，{df["posture"].nunique() if len(df) else 0} 種坐姿')
    if len(df) < 50:
        print(f'   [Warning] 資料量不足，請先執行 python collect_data.py 採集真實資料')
    return df


def preprocess(df):
    print('[2/4] 特徵工程與標準化準備...')
    df = df.dropna()
    seat_total = (df['left_back'] + df['left_mid'] + df['left_front'] +
                  df['center_back'] + df['center_front'] +
                  df['right_back'] + df['right_mid'] + df['right_front'])

    if CALIBRATED_MODE:
        # 校準模式：輸入已是 delta 值，計算區域 delta 總和
        df['left_delta']  = df['left_back'] + df['left_mid'] + df['left_front']
        df['right_delta'] = df['right_back'] + df['right_mid'] + df['right_front']
        df['front_delta'] = df['left_front'] + df['center_front'] + df['right_front']
        df['back_delta']  = df['left_back'] + df['center_back'] + df['right_back']
    else:
        # 未校準模式：計算比例（消除體重影響）
        seat_total_safe = seat_total + 1e-6
        df['left_delta']  = (df['left_back'] + df['left_mid'] + df['left_front']) / seat_total_safe
        df['right_delta'] = (df['right_back'] + df['right_mid'] + df['right_front']) / seat_total_safe
        df['front_delta'] = (df['left_front'] + df['center_front'] + df['right_front']) / seat_total_safe
        df['back_delta']  = (df['left_back'] + df['center_back'] + df['right_back']) / seat_total_safe

    # ── 椅背衍生特徵（5 個，delta／絕對值模式共用同一組公式）───────────────────
    df['spine_total'] = df['spine_upper'] + df['spine_mid'] + df['spine_lower']
    spine_total_safe  = df['spine_total'].where(df['spine_total'].abs() > 1e-6, 1e-6)
    total_all         = seat_total + df['spine_total']
    total_all_safe    = total_all.where(total_all.abs() > 1e-6, 1e-6)

    df['spine_ratio']             = df['spine_total'] / total_all_safe
    df['spine_upper_ratio']       = df['spine_upper'] / spine_total_safe
    df['spine_lower_ratio']       = df['spine_lower'] / spine_total_safe
    df['spine_upper_lower_delta'] = df['spine_upper'] - df['spine_lower']

    print(f'   特徵數量：{len(FEATURES)} 個，樣本數：{len(df)} 筆')
    print(f'   模式：{"校準（delta）" if CALIBRATED_MODE else "未校準（絕對值）"}')
    return df


def build_model(input_dim, num_classes):
    """
    MLP 架構，適合特徵向量輸入。
    若改用時序資料，可在此替換為 1D-CNN 或 LSTM。
    """
    model = keras.Sequential([
        keras.layers.Input(shape=(input_dim,)),

        keras.layers.Dense(64, activation='relu'),
        keras.layers.BatchNormalization(),
        keras.layers.Dropout(0.3),

        keras.layers.Dense(128, activation='relu'),
        keras.layers.BatchNormalization(),
        keras.layers.Dropout(0.3),

        keras.layers.Dense(64, activation='relu'),
        keras.layers.Dropout(0.2),

        keras.layers.Dense(32, activation='relu'),

        keras.layers.Dense(num_classes, activation='softmax'),
    ], name='posture_mlp')

    model.compile(
        optimizer=keras.optimizers.Adam(learning_rate=1e-3),
        loss='sparse_categorical_crossentropy',
        metrics=['accuracy'],
    )
    return model


def train(df):
    print('[3/4] 訓練深度學習模型（MLP）...')

    X = df[FEATURES].values.astype(np.float32)
    y = df['posture'].values

    le = LabelEncoder()
    y_encoded = le.fit_transform(y)
    num_classes = len(le.classes_)

    X_train, X_test, y_train, y_test = train_test_split(
        X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
    )

    scaler = StandardScaler()
    X_train_norm = scaler.fit_transform(X_train)
    X_test_norm  = scaler.transform(X_test)

    model = build_model(len(FEATURES), num_classes)
    model.summary()

    callbacks = [
        keras.callbacks.EarlyStopping(
            monitor='val_accuracy', patience=15, restore_best_weights=True
        ),
        keras.callbacks.ReduceLROnPlateau(
            monitor='val_loss', factor=0.5, patience=7, min_lr=1e-6
        ),
    ]

    print(f'\n   訓練集：{len(X_train)} 筆，測試集：{len(X_test)} 筆')
    model.fit(
        X_train_norm, y_train,
        validation_split=0.2,
        epochs=100,
        batch_size=32,
        callbacks=callbacks,
        verbose=1,
    )

    y_pred = np.argmax(model.predict(X_test_norm, verbose=0), axis=1)
    acc = accuracy_score(y_test, y_pred)
    print(f'\n   測試準確率：{acc:.4f} ({acc * 100:.2f}%)')

    print('\n   各類別準確率：')
    report = classification_report(y_test, y_pred, target_names=le.classes_, zero_division=0)
    for line in report.split('\n'):
        if line.strip():
            print(f'   {line}')

    return model, le, scaler


def save(model, le, scaler):
    print('[4/4] 儲存模型...')
    model.save(DL_MODEL_PATH)
    joblib.dump(le, DL_LABEL_PATH)
    joblib.dump(scaler, DL_SCALER_PATH)
    print(f'   模型  ：{DL_MODEL_PATH}')
    print(f'   標籤  ：{DL_LABEL_PATH}')
    print(f'   縮放器：{DL_SCALER_PATH}')


def main():
    print('=' * 50)
    print('  坐姿分類深度學習模型訓練（MLP）')
    print('=' * 50 + '\n')

    df = load_data()
    df = preprocess(df)
    model, le, scaler = train(df)
    save(model, le, scaler)

    mode_label = '校準（--calibrated）' if CALIBRATED_MODE else '未校準'
    data_label = '（僅真實資料）' if REAL_ONLY_MODE else ''
    print(f'\n完成！{mode_label}{data_label} 模型已儲存 → {DL_MODEL_PATH}')
    print('執行 python manage.py runserver 啟動伺服器')


if __name__ == '__main__':
    main()
