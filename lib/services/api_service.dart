import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  // 可透過 --dart-define=API_BASE_URL=... 覆蓋，避免寫死在程式中
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://sandbar-badass-subfloor.ngrok-free.dev/api',
  );

  // ── 坐姿顯示名稱對照表 ──────────────────────────────────────────
  static const Map<String, String> _displayNames = {
    'normal': '姿勢正常',
    'forward': '頭部前傾',
    'left': '身體左傾',
    'right': '身體右傾',
    'recline': '過度後仰',
    'sedentary': '久坐未動',
  };

  static const Map<String, int> _scores = {
    'normal': 100,
    'forward': 60,
    'left': 70,
    'right': 68,
    'recline': 72,
    'sedentary': 66,
  };

  static const Map<String, String> _risks = {
    'normal': '低風險',
    'forward': '高風險',
    'left': '中風險',
    'right': '中風險',
    'recline': '中風險',
    'sedentary': '高風險',
  };

  static String toDisplayName(String code) => _displayNames[code] ?? code;
  static int toScore(String code) => _scores[code] ?? 70;
  static String toRisk(String code) => _risks[code] ?? '未知';

  // ── Token 管理 ──────────────────────────────────────────────
  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('auth_token');
  }

  static Future<String?> getUserEmail() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString('user_email');
  }

  static Future<bool> isLoggedIn() async {
    final token = await getToken();
    return token != null && token.isNotEmpty;
  }

  static Future<void> _saveAuth(String token, String email) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('auth_token', token);
    await prefs.setString('user_email', email);
  }

  static Future<void> logout() async {
    await chairCheckout();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('auth_token');
    await prefs.remove('user_email');
  }

  static Future<Map<String, String>> _authHeaders() async {
    final token = await getToken();
    return {
      'Content-Type': 'application/json',
      if (token != null) 'Authorization': 'Token $token',
    };
  }

  // ── 認證 ────────────────────────────────────────────────────
  static Future<({bool success, String message, String? email})> login(
    String username,
    String password,
  ) async {
    try {
      final res = await http
          .post(
            Uri.parse('$baseUrl/login'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode({'username': username, 'password': password}),
          )
          .timeout(const Duration(seconds: 10));

      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (res.statusCode == 200) {
        final email = (data['user']?['email'] as String?) ?? username;
        await _saveAuth(data['token'] as String, email);
        unawaited(chairCheckin());
        return (success: true, message: '登入成功', email: email);
      }
      final msg =
          (data['non_field_errors'] as List?)?.first?.toString() ??
          data.values.first?.toString() ??
          '帳號或密碼錯誤';
      return (success: false, message: msg, email: null);
    } catch (_) {
      return (success: false, message: '無法連線到伺服器，請確認後端已啟動', email: null);
    }
  }

  static Future<({bool success, String message, String? email})> register(
    String username,
    String email,
    String password, {
    double? height,
    double? weight,
  }) async {
    try {
      final body = <String, dynamic>{
        'username': username,
        'email': email,
        'password': password,
      };
      if (height != null) body['height'] = height;
      if (weight != null) body['weight'] = weight;

      final res = await http
          .post(
            Uri.parse('$baseUrl/register'),
            headers: {'Content-Type': 'application/json'},
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 10));

      final data = jsonDecode(res.body) as Map<String, dynamic>;
      if (res.statusCode == 201) {
        await _saveAuth(data['token'] as String, email);
        unawaited(chairCheckin());
        return (success: true, message: '註冊成功', email: email);
      }
      final errors = data.values.expand((v) => v is List ? v : [v]).join('、');
      return (success: false, message: errors, email: null);
    } catch (_) {
      return (success: false, message: '無法連線到伺服器，請確認後端已啟動', email: null);
    }
  }

  // ── 坐姿 ────────────────────────────────────────────────────
  static Future<Map<String, dynamic>?> getLatestPosture() async {
    try {
      final res = await http
          .get(
            Uri.parse('$baseUrl/posture/history?limit=1'),
            headers: await _authHeaders(),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        final list = jsonDecode(res.body) as List;
        return list.isNotEmpty ? list.first as Map<String, dynamic> : null;
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  static Future<List<Map<String, dynamic>>> getPostureHistory({
    int limit = 50,
  }) async {
    try {
      final res = await http
          .get(
            Uri.parse('$baseUrl/posture/history?limit=$limit'),
            headers: await _authHeaders(),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        return (jsonDecode(res.body) as List).cast<Map<String, dynamic>>();
      }
      return [];
    } catch (_) {
      return [];
    }
  }

  // ── AI 建議 ──────────────────────────────────────────────────
  static Future<String> getAdvice(
    String postureCode, {
    String userMessage = '',
  }) async {
    try {
      final res = await http
          .post(
            Uri.parse('$baseUrl/agent'),
            headers: await _authHeaders(),
            body: jsonEncode({
              'posture': postureCode,
              'user_message': userMessage,
            }),
          )
          .timeout(const Duration(seconds: 30));

      if (res.statusCode == 200) {
        return jsonDecode(res.body)['advice'] as String? ?? '';
      }
      return '';
    } catch (_) {
      return '';
    }
  }

  // ── 通知 ────────────────────────────────────────────────────
  static Future<List<Map<String, dynamic>>> getPendingNotifications() async {
    try {
      final res = await http
          .get(
            Uri.parse('$baseUrl/notification/pending'),
            headers: await _authHeaders(),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        return (jsonDecode(res.body)['notifications'] as List)
            .cast<Map<String, dynamic>>();
      }
      return [];
    } catch (_) {
      return [];
    }
  }

  // ── 使用者設定 ──────────────────────────────────────────────────────
  /// 更新使用者資料（身高、體重、Email）到後端。
  static Future<bool> updateMe(Map<String, dynamic> updates) async {
    try {
      final res = await http
          .patch(
            Uri.parse('$baseUrl/me/update'),
            headers: await _authHeaders(),
            body: jsonEncode(updates),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        final data = jsonDecode(res.body) as Map<String, dynamic>;
        // 可選：更新本地存儲的 userEmail（若後端回傳了更新後的 email）
        if (data['email'] != null) {
          await _saveAuth(await getToken() ?? '', data['email'] as String);
        }
      }
      return res.statusCode == 200;
    } catch (_) {
      return false;
    }
  }

  /// 將本地設定同步到後端（舊名稱，現在轉向 updateMe）。
  static Future<bool> saveUserSettings(Map<String, dynamic> settings) async {
    return updateMe(settings);
  }

  // ── 座椅佔用 ──────────────────────────────────────────────────────────────
  static Future<void> chairCheckin() async {
    try {
      await http
          .post(
            Uri.parse('$baseUrl/chair/checkin'),
            headers: await _authHeaders(),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  static Future<void> chairCheckout() async {
    try {
      await http
          .post(
            Uri.parse('$baseUrl/chair/checkout'),
            headers: await _authHeaders(),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }
}
