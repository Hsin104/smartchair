import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ChairSyncController extends ChangeNotifier {
  String postureLabel = '';
  String postureCode = '';
  int postureScore = 0;
  bool isGoodPosture = false;
  String latestAdvice = '等待後端資料同步';
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
      'title': '偵測到不良坐姿',
      'time': timeText,
      'message': '目前姿勢為「$posture」，請調整坐姿。',
      'icon': Icons.warning_amber_rounded,
      'color': _postureColor(posture),
    });

    if (notifications.length > 20) notifications.removeLast();
  }

  Color _postureColor(String label) {
    switch (label) {
      // 中文顯示名稱（dashboard 傳入的是中文）
      case '頭部前傾':
        return const Color(0xFFDC2626);
      case '身體左傾':
        return const Color(0xFFEA580C);
      case '身體右傾':
        return const Color(0xFFC2410C);
      case '過度後仰':
        return const Color(0xFF2563EB);
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
        return Colors.red;
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
        postureCode = code;
        postureLabel = ApiService.toDisplayName(code);
        postureScore = (latest['score'] as int?) ?? ApiService.toScore(code);
        isGoodPosture = code == 'normal';
        latestAdvice =
            latest['physio_advice'] as String? ??
            latest['advice'] as String? ??
            (isGoodPosture ? '目前姿勢良好，請繼續維持。' : '請依照後端建議調整姿勢。');
      }
      for (final item in history) {
        final label =
            item['posture'] as String? ?? item['label'] as String? ?? '未知';
        final score = (item['score'] as int?) ?? ApiService.toScore(label);
        final isGood = label == 'normal' || label == '姿勢正常';
        postureHistory.add({
          'label': ApiService.toDisplayName(label),
          'score': score,
          'isGood': isGood,
          'time':
              DateTime.tryParse(item['timestamp']?.toString() ?? '') ??
              DateTime.now(),
        });
      }

      lastBackendSyncAt = DateTime.now();

      // Update notifications from history list
      notifications.clear();
      for (final n in notificationHistory) {
        final title = n['title'] as String? ?? '通知';
        final message = n['message'] as String? ?? '';
        final time = n['timestamp']?.toString() ?? '';
        final color = _postureColor(n['posture'] as String? ?? 'normal');
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
}
