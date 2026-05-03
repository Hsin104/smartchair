"""
深度學習坐姿分類模型訓練腳本

架構：多層感知器（MLP）
  Input(11) → Dense(64, ReLU) → BN → Dropout(0.3)
            → Dense(128, ReLU) → BN → Dropout(0.3)
            → Dense(64, ReLU)  → Dropout(0.2)
            → Dense(32, ReLU)  → Dense(num_classes, Softmax)

此架構適合以特徵向量（單筆樣本）作為輸入。
待感測器累積足夠時序資料後，可將此架構替換為 1D-CNN 或 LSTM。

安裝依賴：
    pip install tensorflow

執行方式：
    python train_model_dl.py
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

DL_MODEL_PATH  = 'posture_model_dl.keras'
DL_LABEL_PATH  = 'label_encoder_dl.pkl'
DL_SCALER_PATH = 'feature_scaler_dl.pkl'

FEATURES = [
    # 椅墊 8 個 FSR（3-2-3）
    'left_back', 'left_mid', 'left_front',
    'center_back', 'center_front',
    'right_back', 'right_mid', 'right_front',
    # 椅背脊椎 3 個 FSR
    'spine_upper', 'spine_mid', 'spine_lower',
    # 衍生特徵
    'seat_total', 'left_ratio', 'front_ratio', 'spine_total', 'spine_ratio',
]


def load_data():
    print('[1/4] 從資料庫讀取數據...')
    records = PostureRecord.objects.filter(
        seat_pressure_data__isnull=False,
        back_pressure_data__isnull=False,
    ).exclude(posture='sedentary').values('posture', 'seat_pressure_data', 'back_pressure_data')
    rows = []
    for r in records:
        seat = r['seat_pressure_data'] or {}
        back = r['back_pressure_data'] or {}
        rows.append({
            'posture':      r['posture'],
            'left_back':    seat.get('left_back',    0),
            'left_mid':     seat.get('left_mid',     0),
            'left_front':   seat.get('left_front',   0),
            'center_back':  seat.get('center_back',  0),
            'center_front': seat.get('center_front', 0),
            'right_back':   seat.get('right_back',   0),
            'right_mid':    seat.get('right_mid',    0),
            'right_front':  seat.get('right_front',  0),
            'spine_upper':  back.get('spine_upper',  0),
            'spine_mid':    back.get('spine_mid',    0),
            'spine_lower':  back.get('spine_lower',  0),
        })
    df = pd.DataFrame(rows)
    print(f'   讀取完成：{len(df)} 筆，{df["posture"].nunique()} 種坐姿')
    if len(df) < 100:
        print(f'   [Warning] 資料量不足，建議先執行 python generate_fake_data.py 補充假資料')
    return df


def preprocess(df):
    print('[2/4] 特徵工程與標準化準備...')
    df = df.dropna()
    df['seat_total']  = df['left_back'] + df['left_mid'] + df['left_front'] + df['center_back'] + df['center_front'] + df['right_back'] + df['right_mid'] + df['right_front']
    df['left_ratio']  = (df['left_back'] + df['left_mid'] + df['left_front']) / (df['seat_total'] + 1e-6)
    df['front_ratio'] = (df['left_front'] + df['center_front'] + df['right_front']) / (df['seat_total'] + 1e-6)
    df['spine_total'] = df['spine_upper'] + df['spine_mid'] + df['spine_lower']
    df['spine_ratio'] = df['spine_total'] / (df['seat_total'] + df['spine_total'] + 1e-6)
    print(f'   特徵數量：{len(FEATURES)} 個，樣本數：{len(df)} 筆')
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

    print('\n完成！執行 python manage.py runserver 啟動伺服器（DL 模型優先載入）')


if __name__ == '__main__':
    main()
