"""
坐姿辨識成效分析（回應教授 11/16 第 7 點）：雲端 AI 坐姿模型（未校準／校準兩個 MLP）＋ ESP32 重心規則

資料：資料庫中 source='real' 的人工標註資料，與 train_model_dl.py 相同的讀取與篩選。
     兩種格式分開評估：未校準＝絕對值（無負值），校準＝相對中立點的 delta 值（有負值）。

為什麼要切時間：兩個模型都在 10/09 17:14 重新訓練（commit 5157ad2）。train_model_dl.py 依時間排序後
用 test_size=0.2、random_state=42、stratify 切分，所以「只用 10/09 17:14 以前的資料」才能重現當時的測試集；
之後才收進資料庫的真實資料，模型完全沒看過，另外當成第二個測試集。
     1. 重現的測試集（訓練時保留的 20%）
     2. 訓練後新收的資料（若有）
     3. 全部資料（含訓練看過的，只供參考，數字會偏樂觀）

ESP32 重心規則依 demo/MQTT資料說明.md 第 4.2 節在電腦上重現（只適用未校準的絕對值資料）：
    1. 用 S1–S8 的 norm 以座標加權算重心 (center_x, center_y)
    2. 中立點 = 8 顆感測器座標平均 (0.500, 0.4425)
    3. 與中立點距離 < normal_radius (0.07) → normal
    4. 否則比較左右、前後偏移，偏比較多的方向即為結果（x 大 = 右傾、y 大 = 前傾、y 小 = 後仰）

執行：python compare_esp32_rule.py   （只讀資料庫，不連 MQTT、不呼叫 OpenAI）
      在已部署的容器內執行（不需重建）：docker compose exec -T django python - < compare_esp32_rule.py
      嚴格驗證（重新訓練暫時模型、不覆蓋正式模型，CPU 約數分鐘）：
          docker compose exec -T django python - --strict < compare_esp32_rule.py
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone

import django
import numpy as np
import pandas as pd

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'smartchair_backend.settings')
django.setup()

import joblib
import tensorflow as tf
from sklearn.metrics import accuracy_score, classification_report, confusion_matrix
from sklearn.model_selection import train_test_split

from api.models import PostureRecord

LABELS = ['normal', 'left', 'right', 'forward', 'recline']
# 兩個模型最後一次重新訓練的時間（git commit 5157ad2 的時間，訓練在這之前完成）
TRAINED_AT = datetime(2026, 10, 9, 17, 14, 16, tzinfo=timezone(timedelta(hours=8)))
MODELS = {
    'uncalibrated': ('未校準模型', 'posture_model_dl.keras', 'label_encoder_dl.pkl', 'feature_scaler_dl.pkl'),
    'calibrated':   ('校準模型', 'posture_model_calibrated.keras', 'label_encoder_calibrated.pkl',
                     'feature_scaler_calibrated.pkl'),
}

# 座標（MQTT資料說明.md 第 3 節），key 對應後端 seat_pressure_data 的欄位名
POS = {
    'right_back':   (0.82, 0.18),  # S1
    'right_mid':    (0.82, 0.42),  # S2
    'right_front':  (0.82, 0.72),  # S3
    'center_back':  (0.50, 0.18),  # S4
    'center_front': (0.50, 0.72),  # S5
    'left_front':   (0.18, 0.72),  # S6
    'left_mid':     (0.18, 0.42),  # S7
    'left_back':    (0.18, 0.18),  # S8
}
NEUTRAL = (np.mean([p[0] for p in POS.values()]), np.mean([p[1] for p in POS.values()]))
NORMAL_RADIUS = 0.07

FEATURES = [
    'left_back', 'left_mid', 'left_front', 'center_back', 'center_front',
    'right_back', 'right_mid', 'right_front',
    'left_delta', 'right_delta', 'front_delta', 'back_delta',
    'spine_upper', 'spine_mid', 'spine_lower',
    'spine_total', 'spine_ratio', 'spine_upper_ratio', 'spine_lower_ratio', 'spine_upper_lower_delta',
]


def esp32_rule(row):
    w = {k: max(float(row[k]), 0.0) for k in POS}
    total = sum(w.values())
    if total <= 0:
        return 'normal'
    cx = sum(w[k] * POS[k][0] for k in POS) / total
    cy = sum(w[k] * POS[k][1] for k in POS) / total
    dx, dy = cx - NEUTRAL[0], cy - NEUTRAL[1]
    if (dx * dx + dy * dy) ** 0.5 < NORMAL_RADIUS:
        return 'normal'
    if abs(dx) >= abs(dy):
        return 'right' if dx > 0 else 'left'
    return 'forward' if dy > 0 else 'recline'


def load_df(calibrated):
    """與 train_model_dl.py load_data()＋preprocess() 相同的查詢、排序（-timestamp）、篩選與特徵；只取真實資料。"""
    qs = PostureRecord.objects.filter(
        seat_pressure_data__isnull=False, back_pressure_data__isnull=False,
    ).exclude(posture__in=['sedentary', 'empty'])
    qs = [r for r in qs if r.back_pressure_data and r.source == 'real']
    qs = [r for r in qs if any(v < 0 for v in r.seat_pressure_data.values()) == calibrated]
    rows = []
    for r in qs:
        s, b = r.seat_pressure_data, r.back_pressure_data
        rows.append({'posture': r.posture, 'timestamp': r.timestamp, 'user_id': r.user_id or 0,
                     'device_posture': r.device_posture or '', **{k: s.get(k, 0) for k in POS},
                     'spine_upper': b.get('spine_upper', 0), 'spine_mid': b.get('spine_mid', 0),
                     'spine_lower': b.get('spine_lower', 0)})
    df = pd.DataFrame(rows)
    df = df.dropna(subset=[c for c in df.columns if c != 'device_posture'])
    if df.empty:
        return df
    seat = sum(df[k] for k in POS)
    div = 1 if calibrated else seat + 1e-6     # 校準＝delta 總和；未校準＝比例（消除體重影響）
    df['left_delta'] = (df['left_back'] + df['left_mid'] + df['left_front']) / div
    df['right_delta'] = (df['right_back'] + df['right_mid'] + df['right_front']) / div
    df['front_delta'] = (df['left_front'] + df['center_front'] + df['right_front']) / div
    df['back_delta'] = (df['left_back'] + df['center_back'] + df['right_back']) / div
    df['spine_total'] = df['spine_upper'] + df['spine_mid'] + df['spine_lower']
    st = df['spine_total'].where(df['spine_total'].abs() > 1e-6, 1e-6)
    ta = seat + df['spine_total']
    ta = ta.where(ta.abs() > 1e-6, 1e-6)
    df['spine_ratio'] = df['spine_total'] / ta
    df['spine_upper_ratio'] = df['spine_upper'] / st
    df['spine_lower_ratio'] = df['spine_lower'] / st
    df['spine_upper_lower_delta'] = df['spine_upper'] - df['spine_lower']
    return df.reset_index(drop=True)


def report(name, y_true, y_pred, conf=None):
    acc = accuracy_score(y_true, y_pred)
    rep = classification_report(y_true, y_pred, labels=LABELS, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=LABELS)
    print(f'\n=== {name}（n={len(y_true)}）準確率 {acc * 100:.1f}% ===')
    print('  類別        precision  recall  f1    樣本數')
    for l in LABELS:
        r = rep[l]
        print(f'  {l:10}  {r["precision"]:.3f}     {r["recall"]:.3f}   {r["f1-score"]:.3f}  {int(r["support"])}')
    print('  混淆矩陣（列＝實際，欄＝預測）：', LABELS)
    for l, row in zip(LABELS, cm):
        print(f'    {l:8}', ' '.join(f'{v:5d}' for v in row))
    confusions = sorted(((int(cm[i][j]), LABELS[i], LABELS[j]) for i in range(len(LABELS))
                         for j in range(len(LABELS)) if i != j and cm[i][j]), reverse=True)[:5]
    print('  最常見誤判（實際 → 誤判為，次數）：', [f'{a}→{b} {n}' for n, a, b in confusions])
    out = {'n': int(len(y_true)), 'accuracy': round(acc * 100, 1),
           'per_class': {l: {'precision': round(rep[l]['precision'], 3), 'recall': round(rep[l]['recall'], 3),
                             'f1': round(rep[l]['f1-score'], 3), 'support': int(rep[l]['support'])} for l in LABELS},
           'confusion_matrix': {'labels': LABELS, 'rows': cm.tolist()},
           'top_confusions': [{'actual': a, 'predicted': b, 'count': n} for n, a, b in confusions]}
    if conf is not None:
        low = conf < 0.5
        correct = np.asarray(y_true) == np.asarray(y_pred)
        out['confidence'] = {
            'mean': round(float(conf.mean()), 3), 'low_count': int(low.sum()),
            'accuracy_when_low': round(float(correct[low].mean()) * 100, 1) if low.any() else None,
            'accuracy_when_high': round(float(correct[~low].mean()) * 100, 1) if (~low).any() else None,
        }
        print(f'  信心分數：平均 {out["confidence"]["mean"]}；低於 0.5 有 {out["confidence"]["low_count"]} 筆；'
              f'低信心準確率 {out["confidence"]["accuracy_when_low"]}%、高信心 {out["confidence"]["accuracy_when_high"]}%')
    return out


def predict(files, df):
    model = tf.keras.models.load_model(files[1])
    le = joblib.load(files[2])
    scaler = joblib.load(files[3])
    probs = model.predict(scaler.transform(df[FEATURES].values.astype(np.float32)), verbose=0)
    return le, le.inverse_transform(probs.argmax(axis=1)), probs.max(axis=1)


def evaluate(key):
    files = MODELS[key]
    df = load_df(key == 'calibrated')
    print(f'\n################ {files[0]}（{"delta 值" if key == "calibrated" else "絕對值"}格式的真實資料）')
    if df.empty:
        print('  沒有這種格式的真實標註資料，略過')
        return {'available': False}
    before = df[df['timestamp'] <= TRAINED_AT].reset_index(drop=True)
    after = df[df['timestamp'] > TRAINED_AT].reset_index(drop=True)
    print(f'  全部 {len(df)} 筆：訓練前 {len(before)} 筆、訓練後新收 {len(after)} 筆；'
          f'各類別 {df["posture"].value_counts().to_dict()}')
    mtimes = {f: datetime.fromtimestamp(os.path.getmtime(f)).strftime('%Y-%m-%d %H:%M') for f in files[1:]}
    print(f'  模型檔修改時間：{mtimes}（若 scaler 與模型日期不同，表示兩者可能不是同一次訓練產生）')
    result = {'available': True, 'trained_at': TRAINED_AT.isoformat(), 'file_mtimes': mtimes,
              'limitation': '重現切分的前提是訓練後沒有刪改 10/09 以前的資料；無法百分之百保證與當時測試集相同',
              'total': len(df),
              'before_training': len(before), 'after_training': len(after),
              'class_counts': df['posture'].value_counts().to_dict()}
    if len(before) < 50:
        # train_model_dl.py 的 auto 模式在真實資料不足 50 筆時會混入假資料訓練，這時無法重現測試集
        print('  訓練前的真實資料不足 50 筆，訓練時混用了假資料，無法重現測試集')
    else:
        le = joblib.load(files[2])
        y = le.transform(before['posture'].values)
        _, idx_test = train_test_split(np.arange(len(before)), test_size=0.2, random_state=42, stratify=y)
        test = before.iloc[idx_test]
        _, pred, conf = predict(files, test)
        result['split'] = '訓練前資料依 -timestamp 排序，test_size=0.2、random_state=42、stratify，與訓練時相同'
        result['model_test'] = report(f'{files[0]} — 重現的測試集（訓練時保留的 20%）', test['posture'].values, pred, conf)
        if key == 'uncalibrated':
            result['esp32_rule_test'] = report('ESP32 重心規則 — 同一份測試集', test['posture'].values,
                                               test.apply(esp32_rule, axis=1).values)
    if len(after):
        _, pred, conf = predict(files, after)
        result['model_after'] = report(f'{files[0]} — 訓練後新收的資料（完全沒看過）', after['posture'].values, pred, conf)
    _, pred, conf = predict(files, df)
    result['model_all'] = report(f'{files[0]} — 全部資料（含訓練看過的，僅供參考）', df['posture'].values, pred, conf)
    if key == 'uncalibrated':
        result['esp32_rule_all'] = report('ESP32 重心規則 — 全部真實資料', df['posture'].values,
                                          df.apply(esp32_rule, axis=1).values)
    return result


# ── 更嚴格的驗證：重新訓練暫時模型（不覆蓋正式模型檔）──────────────────────────────
# 原本的測試集是把連續收集的感測資料「隨機」切 20%，相鄰幾秒幾乎相同的資料會分到訓練與測試兩邊，
# 準確率可能偏樂觀。這裡用和 train_model_dl.py 相同的架構與參數重新訓練，換兩種切法：
#   時間切分：每個類別各自依時間排序，前 80% 訓練、後 20% 測試（測的是「之後收集的資料」）
#   留一人：用其他人的資料訓練，測這個人（測的是「沒看過的新使用者」）

def build_mlp(input_dim, num_classes):
    """與 train_model_dl.build_model 相同的架構（複製一份，避免容器內 import 訓練腳本的路徑問題）。"""
    k = tf.keras
    model = k.Sequential([
        k.layers.Input(shape=(input_dim,)),
        k.layers.Dense(64, activation='relu'), k.layers.BatchNormalization(), k.layers.Dropout(0.3),
        k.layers.Dense(128, activation='relu'), k.layers.BatchNormalization(), k.layers.Dropout(0.3),
        k.layers.Dense(64, activation='relu'), k.layers.Dropout(0.2),
        k.layers.Dense(32, activation='relu'),
        k.layers.Dense(num_classes, activation='softmax'),
    ])
    model.compile(optimizer=k.optimizers.Adam(learning_rate=1e-3),
                  loss='sparse_categorical_crossentropy', metrics=['accuracy'])
    return model


def train_and_predict(train_df, test_df):
    from sklearn.preprocessing import LabelEncoder, StandardScaler
    tf.keras.utils.set_random_seed(42)
    le = LabelEncoder().fit(train_df['posture'].values)
    scaler = StandardScaler().fit(train_df[FEATURES].values.astype(np.float32))
    model = build_mlp(len(FEATURES), len(le.classes_))
    cb = [tf.keras.callbacks.EarlyStopping(monitor='val_accuracy', patience=15, restore_best_weights=True),
          tf.keras.callbacks.ReduceLROnPlateau(monitor='val_loss', factor=0.5, patience=7, min_lr=1e-6)]
    # 訓練資料打亂後再切驗證集，避免 validation_split 只拿到最後一個類別
    tr = train_df.sample(frac=1, random_state=42)
    model.fit(scaler.transform(tr[FEATURES].values.astype(np.float32)), le.transform(tr['posture'].values),
              validation_split=0.2, epochs=100, batch_size=32, callbacks=cb, verbose=0)
    probs = model.predict(scaler.transform(test_df[FEATURES].values.astype(np.float32)), verbose=0)
    return le.inverse_transform(probs.argmax(axis=1)), probs.max(axis=1)


def sessions(df, gap_minutes=10):
    """同一類別相鄰兩筆超過 gap_minutes 分鐘視為不同次收集，回傳各類別收集次數。"""
    out = {}
    for label, g in df.sort_values('timestamp').groupby('posture'):
        gaps = g['timestamp'].diff() > pd.Timedelta(minutes=gap_minutes)
        out[label] = int(gaps.sum()) + 1
    return out


def strict_validation(key):
    files = MODELS[key]
    df = load_df(key == 'calibrated')
    print(f'\n################ 嚴格驗證：{files[0]}')
    if df.empty:
        return {'available': False}
    result = {'available': True, 'collection_sessions': sessions(df),
              'users': {str(u): int(n) for u, n in df['user_id'].value_counts().items()}}
    print(f'  各類別收集次數（相隔 10 分鐘以上算不同次）：{result["collection_sessions"]}')
    print(f'  各使用者筆數：{result["users"]}')

    df = df.sort_values('timestamp')
    test_idx = []
    for _, g in df.groupby('posture'):
        test_idx += list(g.index[int(len(g) * 0.8):])
    test, train = df.loc[test_idx], df.drop(index=test_idx)
    result['time_split_range'] = {'train_until': str(train['timestamp'].max()), 'test_from': str(test['timestamp'].min())}
    pred, conf = train_and_predict(train, test)
    result['time_split_model'] = report(f'{files[0]}架構 — 時間切分（各類別前 80% 訓練、後 20% 測試）',
                                        test['posture'].values, pred, conf)
    if key == 'uncalibrated':
        result['time_split_esp32_rule'] = report('ESP32 重心規則（重現）— 同一份時間切分測試集',
                                                 test['posture'].values, test.apply(esp32_rule, axis=1).values)

    loso = {}
    for uid, n in df['user_id'].value_counts().items():
        other = df[df['user_id'] != uid]
        if n < 50 or other['posture'].nunique() < len(LABELS) or len(other) < 200:
            continue
        mine = df[df['user_id'] == uid]
        pred, conf = train_and_predict(other, mine)
        loso[str(uid)] = report(f'{files[0]}架構 — 留一人：測使用者 {uid}（用其他人訓練）', mine['posture'].values, pred, conf)
    result['leave_one_user_out'] = loso or '只有一位使用者有足夠資料，無法做留一人驗證'
    if not loso:
        print('  只有一位使用者有足夠資料，無法做留一人驗證')

    dev = df[df['device_posture'].isin(LABELS)]
    if len(dev):
        result['device_firmware'] = report('椅子韌體實際判斷（device_posture 有紀錄的資料）',
                                           dev['posture'].values, dev['device_posture'].values)
    else:
        result['device_firmware'] = '這批資料沒有記錄椅子韌體的判斷'
        print('  這批資料沒有記錄椅子韌體的判斷（device_posture）')
    return result


def main():
    if '--strict' in sys.argv:
        results = {key: strict_validation(key) for key in MODELS}
        print('\nSTRICT_JSON ' + json.dumps(results, ensure_ascii=False, default=str))
        return
    results = {key: evaluate(key) for key in MODELS}
    # 在容器內執行時沒有 demo/ 資料夾（.dockerignore 排除），改成只印出 JSON
    print('\nRESULT_JSON ' + json.dumps(results, ensure_ascii=False, default=str))
    if os.path.isdir('demo'):
        out = 'demo/posture_model_evaluation.json'
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(results, f, ensure_ascii=False, indent=2, default=str)
        print(f'結果已存到 {out}')


if __name__ == '__main__':
    main()
