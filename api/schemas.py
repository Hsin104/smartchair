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

UPDATE_ME_SCHEMA = {
    "type": "object",
    "properties": {
        "height":       {"type": "number", "minimum": 50,  "maximum": 250},
        "weight":       {"type": "number", "minimum": 20,  "maximum": 300},
        "email":        {"type": "string"},
        "display_name": {"type": "string", "maxLength": 100},
        "avatar_url":   {"type": "string", "maxLength": 500},
    },
    "additionalProperties": False,
}

CHANGE_PASSWORD_SCHEMA = {
    "type": "object",
    "required": ["current_password", "new_password"],
    "properties": {
        "current_password": {"type": "string", "minLength": 1},
        "new_password":     {"type": "string", "minLength": 6},
    },
    "additionalProperties": False,
}

FORGOT_PASSWORD_REQUEST_SCHEMA = {
    "type": "object",
    "required": ["username", "email"],
    "properties": {
        "username": {"type": "string", "minLength": 1},
        "email":    {"type": "string", "minLength": 1},
    },
    "additionalProperties": False,
}

FORGOT_PASSWORD_VERIFY_SCHEMA = {
    "type": "object",
    "required": ["username", "code", "new_password"],
    "properties": {
        "username":     {"type": "string", "minLength": 1},
        "code":         {"type": "string", "minLength": 6, "maxLength": 6},
        "new_password": {"type": "string", "minLength": 6},
    },
    "additionalProperties": False,
}

AVATAR_SCHEMA = {
    "type": "object",
    "required": ["avatar_url"],
    "properties": {
        "avatar_url": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "additionalProperties": False,
}

AGENT_SCHEMA = {
    "type": "object",
    # posture 必填：一定要結合偵測到的坐姿，不接受純症狀描述、不綁定坐姿的用法。
    # user_message 選填，用來補充症狀描述。
    "required": ["posture"],
    "properties": {
        "posture": {
            "type": "string",
            "enum": ["normal", "left", "right", "forward", "recline", "sedentary"],
        },
        "user_message": {"type": "string", "minLength": 1, "maxLength": 500},
    },
    "additionalProperties": False,
}

MOTOR_TRIGGER_SCHEMA = {
    "type": "object",
    "required": ["posture"],
    "properties": {
        "posture": {
            "type": "string",
            "enum": ["normal", "left", "right", "forward", "recline", "sedentary", "empty"],
        },
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
