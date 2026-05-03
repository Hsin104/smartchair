"""
各 API 端點的 JSON Schema 定義，以及統一驗證輔助函式。

使用方式：
    from .schemas import POSTURE_CREATE_SCHEMA, validate_request
    error = validate_request(request.data, POSTURE_CREATE_SCHEMA)
    if error:
        return Response({'schema_error': error}, status=400)
"""

from jsonschema import validate, ValidationError

# ── 子 Schema（可被其他 Schema 引用）───────────────────────────────────────────

SEAT_PRESSURE_SCHEMA = {
    "type": "object",
    "required": [
        "left_back", "left_mid", "left_front",
        "center_back", "center_front",
        "right_back", "right_mid", "right_front",
    ],
    "properties": {
        "left_back":    {"type": "number", "minimum": 0, "maximum": 1023},
        "left_mid":     {"type": "number", "minimum": 0, "maximum": 1023},
        "left_front":   {"type": "number", "minimum": 0, "maximum": 1023},
        "center_back":  {"type": "number", "minimum": 0, "maximum": 1023},
        "center_front": {"type": "number", "minimum": 0, "maximum": 1023},
        "right_back":   {"type": "number", "minimum": 0, "maximum": 1023},
        "right_mid":    {"type": "number", "minimum": 0, "maximum": 1023},
        "right_front":  {"type": "number", "minimum": 0, "maximum": 1023},
    },
    "additionalProperties": False,
}

BACK_PRESSURE_SCHEMA = {
    "type": "object",
    "required": ["spine_upper", "spine_mid", "spine_lower"],
    "properties": {
        "spine_upper": {"type": "number", "minimum": 0, "maximum": 1023},
        "spine_mid":   {"type": "number", "minimum": 0, "maximum": 1023},
        "spine_lower": {"type": "number", "minimum": 0, "maximum": 1023},
    },
    "additionalProperties": False,
}

# ── 端點 Schema ────────────────────────────────────────────────────────────────

REGISTER_SCHEMA = {
    "type": "object",
    "required": ["username", "password"],
    "properties": {
        "username": {"type": "string", "minLength": 1, "maxLength": 150},
        "password": {"type": "string", "minLength": 6},
        "email":    {"type": "string"},
        "height":   {"type": "number", "minimum": 50,  "maximum": 250},
        "weight":   {"type": "number", "minimum": 20,  "maximum": 300},
    },
    "additionalProperties": False,
}

LOGIN_SCHEMA = {
    "type": "object",
    "required": ["username", "password"],
    "properties": {
        "username": {"type": "string", "minLength": 1},
        "password": {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

# posture_create：帶入 posture（已知標籤）或兩組感測器數值（讓模型預測）
POSTURE_CREATE_SCHEMA = {
    "type": "object",
    "properties": {
        "posture": {
            "type": "string",
            "enum": ["normal", "left", "right", "forward", "recline", "sedentary"],
        },
        "seat_pressure_data": SEAT_PRESSURE_SCHEMA,
        "back_pressure_data": BACK_PRESSURE_SCHEMA,
    },
    "additionalProperties": False,
}

AGENT_SCHEMA = {
    "type": "object",
    "required": ["posture"],
    "properties": {
        "posture": {
            "type": "string",
            "enum": ["normal", "left", "right", "forward", "recline", "sedentary"],
        },
        "user_message": {"type": "string", "maxLength": 500},
    },
    "additionalProperties": False,
}

# ── 驗證輔助 ───────────────────────────────────────────────────────────────────

def validate_request(data, schema):
    """
    驗證 data 是否符合 schema。

    合法時回傳 None；不合法時回傳錯誤訊息字串。
    """
    try:
        validate(instance=dict(data), schema=schema)
        return None
    except ValidationError as exc:
        return exc.message
