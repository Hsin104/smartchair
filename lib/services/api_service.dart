import 'dart:async';
import 'dart:convert';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  // 可透過 --dart-define=API_BASE_URL=... 覆蓋，避免寫死在程式中
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://sandbar-badass-subfloor.ngrok-free.dev',
  );

  static const String apiPrefix = '/api';

  static String _apiBaseUrl() {
    final trimmed = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    if (trimmed.endsWith(apiPrefix)) {
      return trimmed.substring(0, trimmed.length - apiPrefix.length);
    }
    return trimmed;
  }

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
    'normal': 92,
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

  static Future<Map<String, String>> _headers({bool auth = false}) async {
    final token = await getToken();
    final headers = <String, String>{
      'Content-Type': 'application/json',
      'ngrok-skip-browser-warning': 'true',
    };
    if (auth && token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Token $token';
    }
    debugPrint(
      'ApiService._headers -> tokenPresent=${token != null && token.isNotEmpty}, auth=$auth',
    );
    debugPrint('ApiService._headers -> headers=$headers');
    return headers;
  }

  static Uri _buildApiUri(String path, {Map<String, String>? queryParameters}) {
    final normalizedPath = path.startsWith('/') ? path.substring(1) : path;
    final uri = Uri.parse('${_apiBaseUrl()}$apiPrefix/$normalizedPath');
    final mergedQuery = <String, String>{
      ...uri.queryParameters,
      ...?queryParameters,
    };
    return uri.replace(queryParameters: mergedQuery);
  }

  static Map<String, dynamic>? _decodeJsonMap(String body) {
    try {
      final decoded = jsonDecode(body);
      return decoded is Map<String, dynamic> ? decoded : null;
    } catch (_) {
      return null;
    }
  }

  // ── 認證 ────────────────────────────────────────────────────
  static Future<({bool success, String message, String? email})> login(
    String username,
    String password,
  ) async {
    try {
      final res = await http
          .post(
            _buildApiUri('login'),
            headers: await _headers(),
            body: jsonEncode({'username': username, 'password': password}),
          )
          .timeout(const Duration(seconds: 10));

      final data = _decodeJsonMap(res.body);
      if (res.statusCode == 200) {
        if (data == null) {
          return (
            success: false,
            message: '伺服器回應格式錯誤，請檢查後端 /api/login',
            email: null,
          );
        }
        final token = (data['token'] as String?)?.trim() ?? '';
        if (token.isEmpty) {
          return (
            success: false,
            message: '登入回應缺少 token，請檢查後端 /api/login',
            email: null,
          );
        }
        final email = (data['user']?['email'] as String?) ?? username;
        await _saveAuth(token, email);
        unawaited(chairCheckin());
        return (success: true, message: '登入成功', email: email);
      }
      final msg = data == null
          ? '伺服器回應 ${res.statusCode}，內容：${res.body.isNotEmpty ? res.body.substring(0, res.body.length > 120 ? 120 : res.body.length) : '空'}'
          : (data['non_field_errors'] as List?)?.first?.toString() ??
                data.values.first?.toString() ??
                '帳號或密碼錯誤';
      return (success: false, message: msg, email: null);
    } on TimeoutException {
      return (success: false, message: '連線逾時，請確認 ngrok 與後端服務是否正常', email: null);
    } catch (error) {
      return (success: false, message: '登入失敗：${error.toString()}', email: null);
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
            _buildApiUri('register'),
            headers: await _headers(),
            body: jsonEncode(body),
          )
          .timeout(const Duration(seconds: 10));

      final data = _decodeJsonMap(res.body);
      if (res.statusCode == 201) {
        if (data == null) {
          return (
            success: false,
            message: '伺服器回應格式錯誤，請檢查後端 /api/register',
            email: null,
          );
        }
        final token = (data['token'] as String?)?.trim() ?? '';
        if (token.isEmpty) {
          return (
            success: false,
            message: '註冊回應缺少 token，請檢查後端 /api/register',
            email: null,
          );
        }
        await _saveAuth(token, email);
        unawaited(chairCheckin());
        return (success: true, message: '註冊成功', email: email);
      }
      final errors = data == null
          ? '伺服器回應 ${res.statusCode}，內容：${res.body.isNotEmpty ? res.body.substring(0, res.body.length > 120 ? 120 : res.body.length) : '空'}'
          : data.values.expand((v) => v is List ? v : [v]).join('、');
      return (success: false, message: errors, email: null);
    } on TimeoutException {
      return (success: false, message: '連線逾時，請確認 ngrok 與後端服務是否正常', email: null);
    } catch (error) {
      return (success: false, message: '註冊失敗：${error.toString()}', email: null);
    }
  }

  static Future<Map<String, dynamic>?> getMe() async {
    try {
      final res = await http
          .get(_buildApiUri('me'), headers: await _headers(auth: true))
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        return _decodeJsonMap(res.body);
      }
      return null;
    } catch (_) {
      return null;
    }
  }

  // ── 坐姿 ────────────────────────────────────────────────────
  static Future<Map<String, dynamic>?> getLatestPosture() async {
    try {
      if (!await isLoggedIn()) {
        return null;
      }

      final res = await http
          .get(
            _buildApiUri('posture/history', queryParameters: {'limit': '1'}),
            headers: await _headers(auth: true),
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
      if (!await isLoggedIn()) {
        return [];
      }

      final res = await http
          .get(
            _buildApiUri(
              'posture/history',
              queryParameters: {'limit': '$limit'},
            ),
            headers: await _headers(auth: true),
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
      if (!await isLoggedIn()) {
        return '';
      }

      final res = await http
          .post(
            _buildApiUri('agent'),
            headers: await _headers(auth: true),
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
  static Future<List<Map<String, dynamic>>> getNotificationHistory({
    int limit = 50,
  }) async {
    try {
      if (!await isLoggedIn()) {
        return [];
      }

      final res = await http
          .get(
            _buildApiUri(
              'notification/pending',
              queryParameters: {'limit': '$limit'},
            ),
            headers: await _headers(auth: true),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200) {
        final data = jsonDecode(res.body);

        if (data is List) {
          return data.cast<Map<String, dynamic>>();
        }

        if (data is Map && data['notifications'] is List) {
          return (data['notifications'] as List).cast<Map<String, dynamic>>();
        }
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
            _buildApiUri('me/update'),
            headers: await _headers(auth: true),
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
            _buildApiUri('chair/checkin'),
            headers: await _headers(auth: true),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  static Future<void> chairCheckout() async {
    try {
      await http
          .post(
            _buildApiUri('chair/checkout'),
            headers: await _headers(auth: true),
          )
          .timeout(const Duration(seconds: 5));
    } catch (_) {}
  }

  static Future<Map<String, dynamic>?> getChairStatus() async {
    try {
      final res = await http
          .get(_buildApiUri('chair/status'), headers: await _headers())
          .timeout(const Duration(seconds: 5));

      if (res.statusCode == 200) {
        return jsonDecode(res.body) as Map<String, dynamic>;
      }
      return null;
    } catch (error) {
      debugPrint('getChairStatus error: $error');
      return null;
    }
  }
}
