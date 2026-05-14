import 'dart:async';
import 'package:flutter/material.dart';
import '../services/api_service.dart';

class ChairSyncController extends ChangeNotifier {
  String postureLabel = '姿勢正常';
  int postureScore = 92;
  bool isGoodPosture = true;
  String latestInput = '正在同步輸入內容...';
  DateTime updatedAt = DateTime.now();

  Timer? _mockInputTimer;
  int _inputIndex = 0;
  Timer? _syncTimer;

  final List<String> _mockInputs = const [
    '準備開始今日工作',
    '肩膀有點緊，提醒我伸展',
    '30 分鐘後提醒站起來',
    '目前專注模式開啟中',
    '剛完成一段報告輸入',
    '喝水提醒已收到',
  ];

  final List<Map<String, dynamic>> notifications = [];
  final List<Map<String, dynamic>> postureHistory = [];

  void startMockInputStream() {
    _mockInputTimer?.cancel();
    _mockInputTimer = Timer.periodic(const Duration(seconds: 4), (_) {
      _inputIndex = (_inputIndex + 1) % _mockInputs.length;
      latestInput = _mockInputs[_inputIndex];
      updatedAt = DateTime.now();
      notifyListeners();
    });
  }

  void updatePosture({
    required String label,
    required int score,
    required bool isGood,
  }) {
    postureLabel = label;
    postureScore = score;
    isGoodPosture = isGood;
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

  void updateInput(String text) {
    final trimmed = text.trim();
    if (trimmed.isEmpty) return;
    latestInput = trimmed.length > 24
        ? '${trimmed.substring(0, 24)}...'
        : trimmed;
    updatedAt = DateTime.now();
    notifyListeners();
  }

  @override
  void dispose() {
    _mockInputTimer?.cancel();
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

  void stopAutoSync() {
    _syncTimer?.cancel();
    _syncTimer = null;
  }

  Future<void> _pullFromServer() async {
    try {
      // Pull latest posture history and pending notifications
      final history = await ApiService.getPostureHistory(limit: 100);
      final pending = await ApiService.getPendingNotifications();

      // Map server posture entries into controller format
      postureHistory.clear();
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
              DateTime.tryParse(item['time']?.toString() ?? '') ??
              DateTime.now(),
        });
      }

      // Update notifications from pending list
      notifications.clear();
      for (final n in pending) {
        final title = n['title'] as String? ?? '通知';
        final message = n['message'] as String? ?? n['body'] as String? ?? '';
        final time = n['time']?.toString() ?? '';
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
