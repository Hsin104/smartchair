import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../models/wellness_models.dart';
import '../services/api_service.dart';

class WellnessController extends ChangeNotifier {
  static const _baseTasks = <WellnessTask>[
    WellnessTask(
      id: 'neck-reset',
      title: '頸部回正呼吸',
      description: '下巴微收，肩膀放鬆，配合 3 次慢呼吸。',
      postureCode: 'forward',
      durationSeconds: 45,
      points: 10,
    ),
    WellnessTask(
      id: 'side-open',
      title: '側身開展',
      description: '身體向相反側延展，讓腰側慢慢恢復活動度。',
      postureCode: 'left',
      durationSeconds: 40,
      points: 10,
    ),
    WellnessTask(
      id: 'side-balance',
      title: '左右平衡伸展',
      description: '雙腳踩穩，軀幹回到中央，左右各停留一次。',
      postureCode: 'right',
      durationSeconds: 40,
      points: 10,
    ),
    WellnessTask(
      id: 'chest-open',
      title: '胸口開展',
      description: '雙手向後延伸，打開胸腔並維持自然呼吸。',
      postureCode: 'recline',
      durationSeconds: 45,
      points: 10,
    ),
    WellnessTask(
      id: 'stand-reset',
      title: '起身重置',
      description: '離開座位走動一下，讓久坐狀態重新開始。',
      postureCode: 'sedentary',
      durationSeconds: 60,
      points: 15,
    ),
    WellnessTask(
      id: 'posture-check',
      title: '姿勢覺察練習',
      description: '確認腳掌、骨盆、肩膀與頭部位於同一條穩定軸線。',
      postureCode: 'normal',
      durationSeconds: 30,
      points: 8,
    ),
  ];

  String _scope = 'guest';
  int points = 0;
  int streak = 0;
  String? activeTaskId;
  String? latestFeedback;
  final List<WellnessRecord> records = [];
  List<WellnessTask> _dailyTasks = const [];
  final Set<String> _aiAdviceTaskKeys = {};

  List<WellnessTask> get tasks {
    final source = _dailyTasks.isEmpty ? _baseTasks : _dailyTasks;
    final selected = <WellnessTask>[];
    for (final task in source) {
      if (!_conflictsWithAiAdvice(task)) selected.add(task);
      if (selected.length == 3) return List.unmodifiable(selected);
    }

    for (final task in _baseTasks) {
      if (!_conflictsWithAiAdvice(task) &&
          !selected.any((item) => item.id == task.id)) {
        selected.add(task);
      }
      if (selected.length == 3) break;
    }
    return List.unmodifiable(selected);
  }

  int get level => (points ~/ 100) + 1;

  int get pointsInLevel => points % 100;

  double get growthProgress => pointsInLevel / 100;

  WellnessTask taskForPosture(String postureCode) {
    if (_dailyTasks.isNotEmpty && postureCode == 'ai') {
      return _dailyTasks.first;
    }
    return _baseTasks.firstWhere(
      (task) => task.postureCode == postureCode,
      orElse: () => _baseTasks.last,
    );
  }

  void setAiAdviceTasks(List<Map<String, dynamic>> exercises) {
    _aiAdviceTaskKeys
      ..clear()
      ..addAll(
        exercises
            .expand(
              (exercise) => [
                exercise['id']?.toString(),
                exercise['group']?.toString(),
                exercise['name']?.toString(),
                exercise['title']?.toString(),
              ],
            )
            .whereType<String>()
            .map(_taskKey)
            .where((key) => key.isNotEmpty),
      );
    notifyListeners();
  }

  bool _conflictsWithAiAdvice(WellnessTask task) {
    if (_aiAdviceTaskKeys.isEmpty) return false;
    final titleKey = _taskKey(task.title);
    final idKey = _taskKey(task.id);
    return _aiAdviceTaskKeys.contains(titleKey) ||
        _aiAdviceTaskKeys.contains(idKey);
  }

  String _taskKey(String value) =>
      value.toLowerCase().replaceAll(RegExp(r'[^a-z0-9\u4e00-\u9fff]'), '');

  bool isCompletedToday(String taskId) {
    final today = _dateKey(DateTime.now());
    return records.any(
      (record) => record.taskId == taskId && record.dateKey == today,
    );
  }

  Future<void> initialize(String? userScope) async {
    final nextScope = userScope?.trim().toLowerCase();
    _scope = nextScope == null || nextScope.isEmpty ? 'guest' : nextScope;
    notifyListeners();

    final prefs = await SharedPreferences.getInstance();
    points = prefs.getInt(_key('points')) ?? 0;
    streak = prefs.getInt(_key('streak')) ?? 0;
    final savedTaskId = prefs.getString(_key('activeTaskId'));
    activeTaskId = savedTaskId == null || savedTaskId.isEmpty
        ? null
        : savedTaskId;
    latestFeedback = prefs.getString(_key('latestFeedback'));
    records
      ..clear()
      ..addAll(_decodeRecords(prefs.getString(_key('records'))));
    _recalculateStreak();
    await _loadDailyTasks();
    await _loadWellnessHistory();
    notifyListeners();
  }

  Future<void> refreshDailyTasks() async {
    await _loadDailyTasks(force: true);
    notifyListeners();
  }

  Future<void> _loadDailyTasks({bool force = false}) async {
    final prefs = await SharedPreferences.getInstance();
    final today = _dateKey(DateTime.now());
    if (!force && prefs.getString(_key('dailyTasksDate')) == today) {
      final cached = prefs.getString(_key('dailyTasks'));
      if (cached != null && cached.isNotEmpty) {
        try {
          final decoded = jsonDecode(cached);
          if (decoded is List) {
            _dailyTasks = decoded
                .whereType<Map>()
                .map((item) => _taskFromExercise(item.cast<String, dynamic>()))
                .take(3)
                .toList();
            if (_dailyTasks.isNotEmpty) return;
          }
        } on FormatException {
          // Fetch a fresh plan when the cached value is invalid.
        }
      }
    }

    final exercises = await ApiService.getStretchPlan();
    if (exercises.isEmpty) {
      _dailyTasks = _baseTasks.take(3).toList();
      return;
    }

    _dailyTasks = exercises.take(3).map(_taskFromExercise).toList();
    await prefs.setString(_key('dailyTasksDate'), today);
    await prefs.setString(_key('dailyTasks'), jsonEncode(exercises.take(3)));
  }

  WellnessTask _taskFromExercise(Map<String, dynamic> exercise) {
    final name =
        exercise['name']?.toString().trim() ??
        exercise['title']?.toString().trim();
    final title = name == null || name.isEmpty ? 'AI 伸展任務' : name;
    final description =
        exercise['description']?.toString().trim() ??
        exercise['reps']?.toString().trim() ??
        '依照 AI 建議完成伸展動作。';
    final rawDuration =
        exercise['duration_sec'] ?? exercise['duration_seconds'];
    final duration = rawDuration is num
        ? rawDuration.toInt()
        : int.tryParse(rawDuration?.toString() ?? '') ?? 45;
    final id = exercise['id']?.toString().trim();
    return WellnessTask(
      id: id == null || id.isEmpty ? 'ai-${title.hashCode}' : id,
      title: title,
      description: description,
      postureCode: 'ai',
      durationSeconds: duration.clamp(15, 300).toInt(),
      points: 10,
      exerciseId: int.tryParse(id ?? ''),
      group: exercise['group']?.toString(),
    );
  }

  Future<void> _loadWellnessHistory() async {
    if (!await ApiService.isLoggedIn()) return;
    final history = await ApiService.getWellnessHistory();
    for (final item in history) {
      final exerciseId = item['exercise_id']?.toString();
      final date = item['date']?.toString();
      if (exerciseId == null || date == null) continue;
      if (records.any(
        (record) => record.taskId == exerciseId && record.dateKey == date,
      )) {
        continue;
      }
      records.add(
        WellnessRecord(
          taskId: exerciseId,
          dateKey: date,
          completedAt:
              DateTime.tryParse(item['completed_at']?.toString() ?? '') ??
              DateTime.now(),
          feedback: item['feedback']?.toString() ?? '',
          points: 0,
        ),
      );
    }
    _recalculateStreak();
  }

  Future<void> acceptTask(WellnessTask task) async {
    activeTaskId = task.id;
    await _persist();
    notifyListeners();
  }

  Future<bool> completeTask(WellnessTask task, {String feedback = '完成'}) async {
    if (isCompletedToday(task.id)) return false;
    if (task.exerciseId != null) {
      final synced = await ApiService.completeWellnessTask(
        exerciseId: task.exerciseId!,
        source: 'daily',
        feedback: feedback,
      );
      if (!synced) return false;
    }

    final today = _dateKey(DateTime.now());
    final isFirstTaskToday = !records.any((record) => record.dateKey == today);
    final earnedPoints = task.points + (isFirstTaskToday ? 5 : 0);
    records.insert(
      0,
      WellnessRecord(
        taskId: task.id,
        dateKey: today,
        completedAt: DateTime.now(),
        feedback: feedback,
        points: earnedPoints,
      ),
    );
    points += earnedPoints;
    activeTaskId = null;
    latestFeedback = feedback;
    _recalculateStreak();
    await _persist();
    notifyListeners();
    return true;
  }

  String _key(String field) => 'wellness_${_scope}_$field';

  List<WellnessRecord> _decodeRecords(String? encoded) {
    if (encoded == null || encoded.isEmpty) return [];
    try {
      final decoded = jsonDecode(encoded);
      if (decoded is! List) return [];
      return decoded
          .whereType<Map>()
          .map((item) => WellnessRecord.fromJson(item.cast<String, dynamic>()))
          .toList();
    } on FormatException {
      return [];
    }
  }

  String _dateKey(DateTime date) =>
      '${date.year}-${date.month.toString().padLeft(2, '0')}-${date.day.toString().padLeft(2, '0')}';

  void _recalculateStreak() {
    final completedDays = records.map((record) => record.dateKey).toSet();
    var cursor = DateTime.now();
    var count = 0;
    while (completedDays.contains(_dateKey(cursor))) {
      count++;
      cursor = cursor.subtract(const Duration(days: 1));
    }
    streak = count;
  }

  Future<void> _persist() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setInt(_key('points'), points);
    await prefs.setInt(_key('streak'), streak);
    await prefs.setString(_key('activeTaskId'), activeTaskId ?? '');
    await prefs.setString(_key('latestFeedback'), latestFeedback ?? '');
    await prefs.setString(
      _key('records'),
      jsonEncode(records.map((record) => record.toJson()).toList()),
    );
  }
}
