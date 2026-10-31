import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/browser_notification_stub.dart'
    if (dart.library.html) '../services/browser_notification_web.dart';

class ChairSyncController extends ChangeNotifier {
  ChairSyncController() : sessionOpenedAt = null;

  String postureLabel = '';
  String postureCode = '';
  int postureScore = 0;
  bool isGoodPosture = false;
  String latestAdvice = '等待後端資料同步';
  DateTime? sessionOpenedAt;
  DateTime updatedAt = DateTime.now();
  DateTime lastBackendSyncAt = DateTime.now();
  bool _lastPostureWasSedentary = false;
  final Set<String> _knownNotificationIds = {};
  bool _notificationHistoryLoaded = false;

  Timer? _syncTimer;

  final List<Map<String, dynamic>> notifications = [];
  final List<Map<String, dynamic>> postureHistory = [];

  void updatePosture({
    required String code,
    required String label,
    required int score,
    required String advice,
    required bool isGood,
  }) {
    postureCode = code;
    postureLabel = label;
    postureScore = score;
    isGoodPosture = isGood;
    latestAdvice = _cleanAdviceText(advice);
    updatedAt = DateTime.now();

    addPostureHistory(label: label, score: score, isGood: isGood);
    if (!isGood) addPostureNotification(label);

    notifyListeners();
  }

  void addPostureHistory({
    required String label,
    required int score,
    required bool isGood,
  }) {
    postureHistory.add({
      'label': label,
      'score': score,
      'isGood': isGood,
      'time': DateTime.now(),
    });
    if (postureHistory.length > 100) postureHistory.removeAt(0);
  }

  void addPostureNotification(String posture) {
    final now = TimeOfDay.now();
    final timeText =
        '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';

    notifications.insert(0, {
      'title': posture,
      'time': timeText,
      'message': '坐姿提醒：請調整坐姿。',
      'icon': Icons.warning_amber_rounded,
      'color': ApiService.postureColor(posture),
    });

    if (notifications.length > 20) notifications.removeLast();
  }

  void clearNotifications() {
    notifications.clear();
    notifyListeners();
  }

  void clearPostureHistory() {
    postureHistory.clear();
    notifyListeners();
  }

  void startSession() {
    sessionOpenedAt ??= DateTime.now();
    notifyListeners();
  }

  void stopSession() {
    sessionOpenedAt = null;
    _lastPostureWasSedentary = false;
    notifyListeners();
  }

  @override
  void dispose() {
    _syncTimer?.cancel();
    super.dispose();
  }

  /// Start periodic background sync with backend to keep UI consistent with server
  void startAutoSync({Duration interval = const Duration(seconds: 5)}) {
    _syncTimer?.cancel();
    _syncTimer = Timer.periodic(interval, (_) async {
      await _pullFromServer();
    });
    // do an immediate pull
    _pullFromServer();
  }

  Future<void> refreshFromServer() async {
    await _pullFromServer();
  }

  void stopAutoSync() {
    _syncTimer?.cancel();
    _syncTimer = null;
  }

  Future<void> _pullFromServer() async {
    try {
      // Pull latest posture history and notification history
      final history = await ApiService.getPostureHistory(limit: 100);
      final notificationHistory = await ApiService.getNotificationHistory(
        limit: 50,
      );

      // Map server posture entries into controller format
      if (history.isNotEmpty) {
        postureHistory.clear();
        _applyPosturePayload(history.first);
      } else {
        final chairStatus = await ApiService.getChairStatus();
        if (chairStatus != null) {
          _applyPosturePayload(chairStatus);
        }
      }
      for (final item in history) {
        final label =
            item['posture'] as String? ?? item['label'] as String? ?? '未知';
        final score = ApiService.toScore(label);
        final isGood = label == 'normal' || label == '姿勢正常';
        final parsedTime = DateTime.tryParse(
          item['timestamp']?.toString() ?? '',
        )?.toLocal();
        postureHistory.add({
          'code': label,
          'label':
              item['posture_display']?.toString() ??
              ApiService.toDisplayName(label),
          'score': score,
          'isGood': isGood,
          'time': parsedTime ?? DateTime.now(),
        });
      }

      lastBackendSyncAt = DateTime.now();

      // Update notifications from history list
      notifications.clear();
      for (final n in notificationHistory) {
        final notificationId = n['id']?.toString();
        final isNewAutoCheckout =
            _notificationHistoryLoaded &&
            n['kind']?.toString() == 'auto_checkout' &&
            notificationId != null &&
            !_knownNotificationIds.contains(notificationId);
        final displayPosture = _notificationPostureLabel(n);
        final kind = n['kind']?.toString() ?? 'posture';
        final isWeekly = kind == 'weekly';
        final title = isWeekly ? '週報' : displayPosture;
        final message = _notificationMessage(n, displayPosture);
        final time = _notificationTime(n);
        final color = isWeekly
            ? const Color(0xFF2563EB)
            : ApiService.postureColor(displayPosture);
        notifications.add({
          'title': title,
          'time': time.isNotEmpty ? time : _formatNow(),
          'message': message,
          'kind': kind,
          'icon': Icons.notifications_active_rounded,
          'color': color,
        });
        if (notificationId != null) {
          _knownNotificationIds.add(notificationId);
        }
        if (isNewAutoCheckout) {
          unawaited(
            showBrowserNotification(
              '智慧座椅自动离座',
              n['message']?.toString() ?? '请回到 App 重新入座。',
            ),
          );
        }
      }
      _notificationHistoryLoaded = true;

      notifyListeners();
    } catch (_) {
      // ignore network errors; keep current local state
    }
  }

  String _formatNow() {
    final now = TimeOfDay.now();
    return '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';
  }

  void _applyPosturePayload(Map<String, dynamic> payload) {
    final source = _postureSource(payload);
    final code = _postureCodeFrom(source);
    final backendDisplay = source['posture_display']?.toString().trim();
    final displayName = backendDisplay?.isNotEmpty == true
        ? backendDisplay!
        : code.isEmpty
        ? '等待同步'
        : ApiService.toDisplayName(code);
    final score = ApiService.toScore(code);
    final isSedentary =
        code == 'sedentary' ||
        displayName.contains('久坐') ||
        displayName.contains('sedentary');
    final shouldResetTimer =
        _lastPostureWasSedentary && !isSedentary && code.isNotEmpty;

    postureCode = code;
    postureLabel = displayName;
    postureScore = score;
    isGoodPosture = code == 'normal' || displayName == '姿勢正常';
    latestAdvice = _cleanAdviceText(
      source['physio_advice']?.toString() ??
          source['advice']?.toString() ??
          (isGoodPosture ? '目前姿勢良好，請繼續維持。' : '請依照後端建議調整姿勢。'),
    );

    if (displayName == '無人就坐') {
      sessionOpenedAt = null;
      _lastPostureWasSedentary = false;
    } else if (code.isNotEmpty) {
      if (sessionOpenedAt == null || shouldResetTimer) {
        sessionOpenedAt = DateTime.now();
      }
    }

    _lastPostureWasSedentary = isSedentary;
  }

  String _cleanAdviceText(String text) {
    return text.replaceAll('**', '').trim();
  }

  Map<String, dynamic> _postureSource(Map<String, dynamic> payload) {
    for (final key in ['latest', 'current', 'posture_data', 'data']) {
      final value = payload[key];
      if (value is Map) {
        return value.cast<String, dynamic>();
      }
    }
    return payload;
  }

  String _postureCodeFrom(Map<String, dynamic> payload) {
    final occupied =
        payload['occupied'] ?? payload['is_occupied'] ?? payload['active'];
    if (occupied == false) {
      return 'empty';
    }

    for (final key in [
      'posture',
      'posture_code',
      'current_posture',
      'status',
      'state',
      'label',
    ]) {
      final value = payload[key]?.toString().trim();
      if (value != null && value.isNotEmpty) {
        return _normalizePostureCode(value);
      }
    }

    return occupied == true ? '' : 'empty';
  }

  String _normalizePostureCode(String value) {
    switch (value.toLowerCase()) {
      case 'occupied':
      case 'seated':
      case 'sitting':
        return 'normal';
      case 'unoccupied':
      case 'empty':
      case 'none':
      case 'no_data':
        return 'empty';
      default:
        return value;
    }
  }

  String _notificationPostureLabel(Map<String, dynamic> item) {
    for (final key in ['posture', 'posture_code', 'posture_display', 'label']) {
      final raw = item[key]?.toString().trim();
      if (raw != null && raw.isNotEmpty) {
        final displayName = ApiService.toDisplayName(raw);
        if (displayName != '姿勢正常' &&
            displayName != 'normal' &&
            displayName != 'notification' &&
            displayName != 'alert') {
          return displayName;
        }
      }
    }

    final message =
        item['message']?.toString().trim() ??
        item['content']?.toString().trim() ??
        item['description']?.toString().trim() ??
        '';
    final parsed = RegExp(
      r'坐姿(?:提醒|通知)\s*[:：]\s*([^，。,.]+)',
    ).firstMatch(message);
    if (parsed != null) {
      return parsed.group(1)?.trim() ?? '姿勢提醒';
    }

    final quoted = RegExp(r'目前姿勢為[「"]([^」"]+)[」"]').firstMatch(message);
    if (quoted != null) {
      return quoted.group(1)?.trim() ?? '姿勢提醒';
    }

    return '姿勢提醒';
  }

  String _notificationMessage(Map<String, dynamic> item, String postureLabel) {
    final message =
        item['message']?.toString().trim() ??
        item['content']?.toString().trim() ??
        item['description']?.toString().trim();
    if (message != null && message.isNotEmpty) {
      final cleaned = message
          .replaceAll('通知', '提醒')
          .replaceAll(RegExp(r'^坐姿提醒\s*[:：]\s*'), '');
      return '坐姿提醒：$cleaned';
    }

    return '坐姿提醒：$postureLabel，請調整坐姿。';
  }

  String _notificationTime(Map<String, dynamic> item) {
    final raw = item['timestamp']?.toString() ?? item['time']?.toString() ?? '';
    if (raw.isEmpty) return '';

    final parsed = DateTime.tryParse(raw)?.toLocal();
    if (parsed == null) return raw;

    final now = DateTime.now();
    if (parsed.year == now.year &&
        parsed.month == now.month &&
        parsed.day == now.day) {
      return '${parsed.hour.toString().padLeft(2, '0')}:${parsed.minute.toString().padLeft(2, '0')}';
    }

    return '${parsed.month.toString().padLeft(2, '0')}-${parsed.day.toString().padLeft(2, '0')} ${parsed.hour.toString().padLeft(2, '0')}:${parsed.minute.toString().padLeft(2, '0')}';
  }
}
