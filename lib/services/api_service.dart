import 'dart:async';
import 'dart:convert';
import 'dart:ui';
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:shared_preferences/shared_preferences.dart';

class ApiService {
  static const Duration _aiAdviceTimeout = Duration(seconds: 90);

  // 可透過 --dart-define=API_BASE_URL=... 覆蓋，避免寫死在程式中
  static const String baseUrl = String.fromEnvironment(
    'API_BASE_URL',
    defaultValue: 'https://sandbar-badass-subfloor.ngrok-free.dev',
  );

  static const String apiPrefix = '/api';
  static const String authTokenOverride = String.fromEnvironment('AUTH_TOKEN');

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
    'empty': '無人就坐',
  };

  static const Map<String, int> _scores = {
    'normal': 100,
    'forward': 60,
    'left': 70,
    'right': 68,
    'recline': 72,
    'sedentary': 66,
    'empty': 0,
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

  static Color postureColor(String value) {
    final normalized = value.trim().toLowerCase();
    switch (normalized) {
      case 'normal':
      case '姿勢正常':
        return const Color(0xFF16A34A);
      case 'forward':
      case '頭部前傾':
      case '身體前傾':
      case '頭部前傾（鳥龜頭）':
        return const Color(0xFFDC2626);
      case 'left':
      case '身體左傾':
      case '左側傾斜':
        return const Color(0xFFEA580C);
      case 'right':
      case '身體右傾':
      case '右側傾斜':
        return const Color(0xFFC2410C);
      case 'recline':
      case '過度後仰':
      case '後仰過多':
        return const Color(0xFF2563EB);
      case 'sedentary':
      case '久坐未動':
      case '久坐過久':
        return const Color(0xFF7C3AED);
      default:
        return const Color(0xFF64748B);
    }
  }

  // ── Token 管理 ──────────────────────────────────────────────
  static Future<String?> getToken() async {
    final prefs = await SharedPreferences.getInstance();
    final savedToken = prefs.getString('auth_token');
    if (savedToken != null && savedToken.isNotEmpty) {
      return savedToken;
    }
    return authTokenOverride.isNotEmpty ? authTokenOverride : null;
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

  static String? _extractErrorCode(Map<String, dynamic>? data) {
    if (data == null) return null;
    final candidates = [data['error_code'], data['errorCode'], data['code']];
    for (final value in candidates) {
      final text = value?.toString().trim();
      if (text != null && text.isNotEmpty) {
        return text;
      }
    }
    return null;
  }

  static String _extractMessage(Map<String, dynamic>? data, String fallback) {
    if (data == null) return fallback;
    final candidates = [
      data['message'],
      data['detail'],
      data['error'],
      data['non_field_errors'],
    ];

    for (final value in candidates) {
      if (value is String && value.trim().isNotEmpty) {
        return value.trim();
      }
      if (value is List && value.isNotEmpty) {
        return value.first.toString();
      }
    }

    return fallback;
  }

  static List<Map<String, dynamic>> _decodeNotificationList(String body) {
    try {
      final decoded = jsonDecode(body);
      if (decoded is List) {
        return decoded
            .whereType<Map>()
            .map((item) => item.cast<String, dynamic>())
            .toList();
      }

      if (decoded is Map) {
        for (final key in ['notifications', 'items', 'results', 'data']) {
          final value = decoded[key];
          if (value is List) {
            return value
                .whereType<Map>()
                .map((item) => item.cast<String, dynamic>())
                .toList();
          }
        }
      }
    } catch (_) {
      return [];
    }

    return [];
  }

  static Future<bool> usernameExists(String username) async {
    try {
      final res = await http
          .get(
            _buildApiUri(
              'users/exists',
              queryParameters: {'username': username},
            ),
            headers: await _headers(),
          )
          .timeout(const Duration(seconds: 10));

      final data = _decodeJsonMap(res.body);
      if (res.statusCode == 200 && data != null) {
        final exists = data['exists'];
        if (exists is bool) return exists;
      }
      return false;
    } catch (_) {
      return false;
    }
  }

  // ── 認證 ────────────────────────────────────────────────────
  static Future<
    ({bool success, String message, String? email, String? errorCode})
  >
  login(String username, String password) async {
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
            errorCode: null,
          );
        }
        final token = (data['token'] as String?)?.trim() ?? '';
        if (token.isEmpty) {
          return (
            success: false,
            message: '登入回應缺少 token，請檢查後端 /api/login',
            email: null,
            errorCode: null,
          );
        }
        final email = (data['user']?['email'] as String?) ?? username;
        await _saveAuth(token, email);
        unawaited(chairCheckin());
        return (success: true, message: '登入成功', email: email, errorCode: null);
      }
      final errorCode =
          _extractErrorCode(data) ??
          switch (res.statusCode) {
            404 => 'USER_NOT_FOUND',
            401 => 'INVALID_PASSWORD',
            _ => null,
          };
      final message = switch (errorCode) {
        'USER_NOT_FOUND' => '無此帳戶，請去註冊',
        'INVALID_PASSWORD' => '密碼錯誤',
        _ => _extractMessage(
          data,
          '伺服器回應 ${res.statusCode}，內容：${res.body.isNotEmpty ? res.body.substring(0, res.body.length > 120 ? 120 : res.body.length) : '空'}',
        ),
      };
      return (
        success: false,
        message: message,
        email: null,
        errorCode: errorCode,
      );
    } on TimeoutException {
      return (
        success: false,
        message: '連線逾時，請確認 ngrok 與後端服務是否正常',
        email: null,
        errorCode: null,
      );
    } catch (error) {
      return (
        success: false,
        message: '登入失敗：${error.toString()}',
        email: null,
        errorCode: null,
      );
    }
  }

  static Future<
    ({bool success, String message, String? email, String? errorCode})
  >
  register(
    String username,
    String email,
    String password, {
    double? height,
    double? weight,
  }) async {
    try {
      final body = <String, dynamic>{
        'username': username,
        'password': password,
      };
      if (email.trim().isNotEmpty) body['email'] = email.trim();
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
      if (res.statusCode == 201 || res.statusCode == 200) {
        if (data == null) {
          return (
            success: false,
            message: '伺服器回應格式錯誤，請檢查後端 /api/register',
            email: null,
            errorCode: null,
          );
        }
        final token = (data['token'] as String?)?.trim() ?? '';
        if (token.isEmpty) {
          return (
            success: false,
            message: '註冊回應缺少 token，請檢查後端 /api/register',
            email: null,
            errorCode: null,
          );
        }
        await _saveAuth(token, email);
        unawaited(chairCheckin());
        return (success: true, message: '註冊成功', email: email, errorCode: null);
      }
      final errorCode =
          _extractErrorCode(data) ??
          switch (res.statusCode) {
            409 => 'ACCOUNT_EXISTS',
            _ => null,
          };
      final message = switch (errorCode) {
        'ACCOUNT_EXISTS' => '此帳號已被註冊',
        _ => _extractMessage(
          data,
          '伺服器回應 ${res.statusCode}，內容：${res.body.isNotEmpty ? res.body.substring(0, res.body.length > 120 ? 120 : res.body.length) : '空'}',
        ),
      };
      return (
        success: false,
        message: message,
        email: null,
        errorCode: errorCode,
      );
    } on TimeoutException {
      return (
        success: false,
        message: '連線逾時，請確認 ngrok 與後端服務是否正常',
        email: null,
        errorCode: null,
      );
    } catch (error) {
      return (
        success: false,
        message: '註冊失敗：${error.toString()}',
        email: null,
        errorCode: null,
      );
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
  static Future<
    ({
      bool success,
      String advice,
      String message,
      String? postureDisplay,
      String? posture,
      List<Map<String, dynamic>> recommendedExercises,
    })
  >
  getAdvice(String postureCode, {String userMessage = ''}) async {
    try {
      if (!await isLoggedIn()) {
        return (
          success: false,
          advice: '',
          message: '請先登入後再取得 AI 建議。',
          postureDisplay: null,
          posture: null,
          recommendedExercises: const <Map<String, dynamic>>[],
        );
      }

      final safeMessage = userMessage.trim();
      final submitRes = await http
          .post(
            _buildApiUri('agent/jobs'),
            headers: await _headers(auth: true),
            body: jsonEncode({
              'posture': postureCode.trim(),
              'user_message': safeMessage.length > 500
                  ? safeMessage.substring(0, 500)
                  : safeMessage,
            }),
          )
          .timeout(const Duration(seconds: 10));

      final submitData = _decodeJsonMap(submitRes.body);
      if (submitRes.statusCode != 202) {
        return (
          success: false,
          advice: '',
          message: _extractMessage(
            submitData,
            '送出 AI 建議失敗：${submitRes.statusCode}',
          ),
          postureDisplay: null,
          posture: null,
          recommendedExercises: const <Map<String, dynamic>>[],
        );
      }

      final jobId = submitData?['job_id']?.toString().trim() ?? '';
      if (jobId.isEmpty) {
        return (
          success: false,
          advice: '',
          message: 'AI 回應缺少任務編號。',
          postureDisplay: null,
          posture: null,
          recommendedExercises: const <Map<String, dynamic>>[],
        );
      }

      final deadline = DateTime.now().add(_aiAdviceTimeout);
      while (DateTime.now().isBefore(deadline)) {
        final resultRes = await http
            .get(
              _buildApiUri('agent/jobs/$jobId'),
              headers: await _headers(auth: true),
            )
            .timeout(const Duration(seconds: 10));
        final data = _decodeJsonMap(resultRes.body);
        final status = data?['status']?.toString().toLowerCase();

        if (resultRes.statusCode == 200 && status == 'done') {
          return (
            success: true,
            advice: (data?['advice'] as String?)?.trim() ?? '',
            message: '取得 AI 建議成功',
            postureDisplay: data?['posture_display']?.toString(),
            posture: data?['posture']?.toString(),
            recommendedExercises: _decodeRecommendedExercises(
              data?['recommended_exercises'],
            ),
          );
        }
        if (status == 'failed') {
          return (
            success: false,
            advice: '',
            message: _extractMessage(data, 'AI 建議生成失敗。'),
            postureDisplay: null,
            posture: null,
            recommendedExercises: const <Map<String, dynamic>>[],
          );
        }
        if (resultRes.statusCode != 200) {
          return (
            success: false,
            advice: '',
            message: _extractMessage(
              data,
              '查詢 AI 任務失敗：${resultRes.statusCode}',
            ),
            postureDisplay: null,
            posture: null,
            recommendedExercises: const <Map<String, dynamic>>[],
          );
        }
        await Future<void>.delayed(const Duration(seconds: 2));
      }

      return (
        success: false,
        advice: '',
        message: 'AI 等待超時，請稍後再試。',
        postureDisplay: null,
        posture: null,
        recommendedExercises: const <Map<String, dynamic>>[],
      );
    } on TimeoutException {
      return (
        success: false,
        advice: '',
        message: 'AI 等待超時，請稍後再試。',
        postureDisplay: null,
        posture: null,
        recommendedExercises: const <Map<String, dynamic>>[],
      );
    } catch (_) {
      return (
        success: false,
        advice: '',
        message: '網路錯誤，無法取得 AI 建議。',
        postureDisplay: null,
        posture: null,
        recommendedExercises: const <Map<String, dynamic>>[],
      );
    }
  }

  static List<Map<String, dynamic>> _decodeRecommendedExercises(Object? value) {
    if (value is! List) return [];
    return value
        .whereType<Map>()
        .map((item) => item.cast<String, dynamic>())
        .where((item) => item['name']?.toString().trim().isNotEmpty ?? false)
        .take(3)
        .toList();
  }

  // ── 通知 ────────────────────────────────────────────────────
  static Future<List<Map<String, dynamic>>> getNotificationHistory({
    int limit = 50,
  }) async {
    try {
      if (!await isLoggedIn()) {
        return [];
      }

      Future<List<Map<String, dynamic>>> fetch(String path) async {
        final res = await http
            .get(
              _buildApiUri(path, queryParameters: {'limit': '$limit'}),
              headers: await _headers(auth: true),
            )
            .timeout(const Duration(seconds: 10));

        if (res.statusCode == 200) {
          return _decodeNotificationList(res.body);
        }
        return [];
      }

      return await fetch('notification/history');
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

  static Map<String, String> forgotPasswordRequestPayload({
    required String username,
    required String email,
  }) {
    final safeUsername = username.trim();
    final safeEmail = email.trim();

    if (safeUsername.isEmpty || safeEmail.isEmpty) {
      throw StateError('請同時填寫電子郵件與使用者名稱');
    }

    return {'email': safeEmail, 'username': safeUsername};
  }

  static Map<String, String> forgotPasswordVerifyPayload({
    required String username,
    required String code,
    required String newPassword,
  }) {
    final safeUsername = username.trim();
    final safeCode = code.trim();
    final safeNewPassword = newPassword.trim();

    if (safeUsername.isEmpty || safeCode.length != 6) {
      throw StateError('請輸入帳號與 6 碼驗證碼');
    }
    if (safeNewPassword.length < 6) {
      throw StateError('新密碼至少需要 6 碼');
    }

    return {
      'username': safeUsername,
      'code': safeCode,
      'new_password': safeNewPassword,
    };
  }

  /// 忘記密碼第一步：驗證帳號＋Email 後，請後端寄出 6 碼驗證碼到信箱。
  static Future<({bool success, String message})> requestPasswordResetCode({
    required String username,
    required String email,
  }) async {
    final Map<String, String> payload;
    try {
      payload = forgotPasswordRequestPayload(username: username, email: email);
    } on StateError catch (e) {
      return (success: false, message: e.message);
    }

    try {
      final res = await http
          .post(
            _buildApiUri('auth/forgot-password/request'),
            headers: await _headers(),
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 10));

      final data = _decodeJsonMap(res.body);
      if (res.statusCode == 200) {
        return (success: true, message: _extractMessage(data, '驗證碼已寄出，請查收信箱'));
      }

      return (
        success: false,
        message: _extractMessage(
          data,
          data?['schema_error']?.toString() ?? '請求失敗：${res.statusCode}',
        ),
      );
    } on TimeoutException {
      return (success: false, message: '連線逾時，請稍後再試');
    } catch (error) {
      return (success: false, message: '請求失敗：${error.toString()}');
    }
  }

  /// 忘記密碼第二步：輸入信箱收到的驗證碼與新密碼，完成重設。
  static Future<({bool success, String message})> verifyPasswordReset({
    required String username,
    required String code,
    required String newPassword,
  }) async {
    final Map<String, String> payload;
    try {
      payload = forgotPasswordVerifyPayload(
        username: username,
        code: code,
        newPassword: newPassword,
      );
    } on StateError catch (e) {
      return (success: false, message: e.message);
    }

    try {
      final res = await http
          .post(
            _buildApiUri('auth/forgot-password/verify'),
            headers: await _headers(),
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 10));

      final data = _decodeJsonMap(res.body);
      if (res.statusCode == 200) {
        return (success: true, message: _extractMessage(data, '密碼已重設，請用新密碼登入'));
      }

      return (
        success: false,
        message: _extractMessage(
          data,
          data?['schema_error']?.toString() ?? '重設密碼失敗：${res.statusCode}',
        ),
      );
    } on TimeoutException {
      return (success: false, message: '連線逾時，請稍後再試');
    } catch (error) {
      return (success: false, message: '重設密碼失敗：${error.toString()}');
    }
  }

  static Future<({bool success, String message})> changePassword({
    required String currentPassword,
    required String newPassword,
  }) async {
    final safeCurrent = currentPassword.trim();
    final safeNew = newPassword.trim();
    if (safeCurrent.isEmpty || safeNew.isEmpty) {
      return (success: false, message: '請填寫目前密碼與新密碼');
    }

    final payload = <String, dynamic>{
      'current_password': safeCurrent,
      'new_password': safeNew,
    };

    try {
      final res = await http
          .post(
            _buildApiUri('auth/change-password'),
            headers: await _headers(auth: true),
            body: jsonEncode(payload),
          )
          .timeout(const Duration(seconds: 10));

      if (res.statusCode == 200 ||
          res.statusCode == 201 ||
          res.statusCode == 202 ||
          res.statusCode == 204) {
        return (success: true, message: '密碼已更新');
      }

      final data = _decodeJsonMap(res.body);
      return (
        success: false,
        message: _extractMessage(data, '修改密碼失敗：${res.statusCode}'),
      );
    } on TimeoutException {
      return (success: false, message: '連線逾時，請稍後再試');
    } catch (error) {
      return (success: false, message: '修改密碼失敗：${error.toString()}');
    }
  }

  static Future<({bool success, String message, String? avatarUrl})>
  uploadAvatar({required Uint8List bytes, required String filename}) async {
    try {
      final headers = await _headers(auth: true);
      headers.remove('Content-Type');
      final request =
          http.MultipartRequest('POST', _buildApiUri('me/avatar/upload'))
            ..headers.addAll(headers)
            ..files.add(
              http.MultipartFile.fromBytes('file', bytes, filename: filename),
            );
      final response = await request.send().timeout(
        const Duration(seconds: 30),
      );
      final body = await response.stream.bytesToString();
      final data = _decodeJsonMap(body);
      if (response.statusCode == 200) {
        final avatarUrl = data?['avatar_url']?.toString().trim();
        if (avatarUrl == null || avatarUrl.isEmpty) {
          return (
            success: false,
            message: '头像上传成功，但后端没有返回头像网址。',
            avatarUrl: null,
          );
        }
        return (success: true, message: '头像已更新', avatarUrl: avatarUrl);
      }

      return (
        success: false,
        message: _extractMessage(data, '更新头像失败：${response.statusCode}'),
        avatarUrl: null,
      );
    } on TimeoutException {
      return (success: false, message: '头像上传逾时，请稍后再试。', avatarUrl: null);
    } catch (error) {
      return (success: false, message: '头像上传失败：$error', avatarUrl: null);
    }
  }

  static Future<Uint8List?> loadAvatarBytes(String avatarUrl) async {
    try {
      final response = await http
          .get(Uri.parse(avatarUrl), headers: await _headers(auth: true))
          .timeout(const Duration(seconds: 15));
      if (response.statusCode == 200 &&
          response.bodyBytes.isNotEmpty &&
          (response.headers['content-type']?.startsWith('image/') ?? false)) {
        return response.bodyBytes;
      }
      debugPrint(
        'loadAvatarBytes failed: status=${response.statusCode}, '
        'contentType=${response.headers['content-type']}',
      );
      return null;
    } catch (error) {
      debugPrint('loadAvatarBytes error: $error');
      return null;
    }
  }

  // ── 座椅佔用 ──────────────────────────────────────────────────────────────
  static Future<({bool success, bool calibrated, String message})>
  chairCheckin() async {
    try {
      final res = await http
          .post(
            _buildApiUri('chair/checkin'),
            headers: await _headers(auth: true),
          )
          .timeout(const Duration(seconds: 5));
      final data = _decodeJsonMap(res.body);
      if (res.statusCode >= 200 && res.statusCode < 300) {
        return (
          success: true,
          calibrated: data?['calibrated'] == true,
          message: '入座成功',
        );
      }
      return (
        success: false,
        calibrated: false,
        message: _extractMessage(data, '入座失敗：${res.statusCode}'),
      );
    } on TimeoutException {
      return (success: false, calibrated: false, message: '入座逾時');
    } catch (error) {
      return (success: false, calibrated: false, message: '入座失敗：$error');
    }
  }

  static Future<({bool success, String message, bool calibrated, int? samples})>
  calibrateChairAuto() async {
    try {
      final startRes = await http
          .post(
            _buildApiUri('chair/calibration'),
            headers: await _headers(auth: true),
          )
          .timeout(const Duration(seconds: 10));

      var data = _decodeJsonMap(startRes.body);
      if (startRes.statusCode != 202) {
        return (
          success: false,
          message: _extractMessage(data, '校準失敗：${startRes.statusCode}'),
          calibrated: false,
          samples: null,
        );
      }

      final deadline = DateTime.now().add(const Duration(seconds: 15));
      while (DateTime.now().isBefore(deadline)) {
        await Future<void>.delayed(const Duration(seconds: 1));
        final statusRes = await http
            .get(
              _buildApiUri('chair/calibration'),
              headers: await _headers(auth: true),
            )
            .timeout(const Duration(seconds: 5));
        data = _decodeJsonMap(statusRes.body);
        final status = data?['status']?.toString().toLowerCase();
        if (statusRes.statusCode == 200 && status == 'done') {
          return (
            success: true,
            message: '校準成功',
            calibrated: true,
            samples: null,
          );
        }
        if (status == 'failed') {
          return (
            success: false,
            message: _extractMessage(data, '校準失敗。'),
            calibrated: false,
            samples: null,
          );
        }
      }
      return (
        success: false,
        message: '校準逾時，請稍後再試。',
        calibrated: false,
        samples: null,
      );
    } on TimeoutException {
      return (
        success: false,
        message: '校準逾時，請確認感測器資料是否已進來',
        calibrated: false,
        samples: null,
      );
    } catch (error) {
      return (
        success: false,
        message: '校準失敗：${error.toString()}',
        calibrated: false,
        samples: null,
      );
    }
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
          .get(
            _buildApiUri('chair/status'),
            headers: await _headers(auth: true),
          )
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
