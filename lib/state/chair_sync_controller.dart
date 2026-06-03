import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

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
    latestAdvice = advice;
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
      'color': _postureColor(posture),
    });

    if (notifications.length > 20) notifications.removeLast();
  }

  Color _postureColor(String label) {
    if (label.contains('前傾')) {
      return const Color(0xFFDC2626);
    }
    if (label.contains('左傾') || label.contains('左側傾斜')) {
      return const Color(0xFFEA580C);
    }
    if (label.contains('右傾') || label.contains('右側傾斜')) {
      return const Color(0xFFC2410C);
    }
    if (label.contains('後仰')) {
      return const Color(0xFF2563EB);
    }
    if (label.contains('久坐')) {
      return const Color(0xFF7C3AED);
    }

    switch (label) {
      case 'normal':
      case '姿勢正常':
        return const Color(0xFF16A34A);
      case 'forward':
      // 中文顯示名稱（dashboard 傳入的是中文）
      case '頭部前傾':
        return const Color(0xFFDC2626);
      case 'left':
      case '身體左傾':
        return const Color(0xFFEA580C);
      case 'right':
      case '身體右傾':
        return const Color(0xFFC2410C);
      case 'recline':
      case '過度後仰':
        return const Color(0xFF2563EB);
      case 'sedentary':
      case '久坐未動':
        return const Color(0xFF7C3AED);
      // 相容舊版中文
      case '身體前傾':
        return const Color(0xFFDC2626);
      case '左側傾斜':
        return const Color(0xFFEA580C);
      case '右側傾斜':
        return const Color(0xFFC2410C);
      case '後仰過多':
        return const Color(0xFF2563EB);
      case '久坐過久':
        return const Color(0xFF7C3AED);
      default:
        return const Color(0xFF64748B);
    }
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
    sessionOpenedAt = DateTime.now();
    notifyListeners();
  }

  void stopSession() {
    sessionOpenedAt = null;
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
      postureHistory.clear();
      if (history.isNotEmpty) {
        final latest = history.first;
        final code = latest['posture'] as String? ?? 'normal';
        final displayName = ApiService.toDisplayName(code);
        postureCode = code;
        postureLabel = displayName;
        postureScore = (latest['score'] as int?) ?? ApiService.toScore(code);
        isGoodPosture = code == 'normal';
        latestAdvice =
            latest['physio_advice'] as String? ??
            latest['advice'] as String? ??
            (isGoodPosture ? '目前姿勢良好，請繼續維持。' : '請依照後端建議調整姿勢。');

        // 如果最新狀態為「無人就坐」，則暫停計時（不計時）
        // 否則：若目前沒有在計時（sessionOpenedAt 為 null），則開始計時
        if (displayName == '無人就坐') {
          sessionOpenedAt = null;
        } else {
          sessionOpenedAt ??= DateTime.now();
        }
      } else {
        postureCode = '';
        postureLabel = '無人就坐';
        postureScore = 0;
        isGoodPosture = false;
        latestAdvice = '等待後端資料同步';

        // 空的歷史視為無人就坐，暫停計時
        sessionOpenedAt = null;
      }
      for (final item in history) {
        final label =
            item['posture'] as String? ?? item['label'] as String? ?? '未知';
        final score = (item['score'] as int?) ?? ApiService.toScore(label);
        final isGood = label == 'normal' || label == '姿勢正常';
        final parsedTime = DateTime.tryParse(
          item['timestamp']?.toString() ?? '',
        )?.toLocal();
        postureHistory.add({
          'label': ApiService.toDisplayName(label),
          'score': score,
          'isGood': isGood,
          'time': parsedTime ?? DateTime.now(),
        });
      }

      lastBackendSyncAt = DateTime.now();

      // Update notifications from history list
      notifications.clear();
      for (final n in notificationHistory) {
        final displayPosture = _notificationPostureLabel(n);
        final title = displayPosture;
        final message = _notificationMessage(n, displayPosture);
        final time = _notificationTime(n);
        final color = _postureColor(displayPosture);
        notifications.add({
          'title': title,
          'time': time.isNotEmpty ? time : _formatNow(),
          'message': message,
          'icon': Icons.notifications_active_rounded,
          'color': color,
        });
      }

      notifyListeners();
    } catch (_) {
      // ignore network errors; keep current local state
    }
  }

  String _formatNow() {
    final now = TimeOfDay.now();
    return '${now.hour.toString().padLeft(2, '0')}:${now.minute.toString().padLeft(2, '0')}';
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
    final raw =
        item['timestamp']?.toString() ??
        item['created_at']?.toString() ??
        item['createdAt']?.toString() ??
        item['time']?.toString() ??
        '';
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
