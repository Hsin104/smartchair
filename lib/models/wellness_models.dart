class WellnessTask {
  const WellnessTask({
    required this.id,
    required this.title,
    required this.description,
    required this.postureCode,
    required this.durationSeconds,
    required this.points,
    this.exerciseId,
    this.group,
  });

  final String id;
  final String title;
  final String description;
  final String postureCode;
  final int durationSeconds;
  final int points;
  final int? exerciseId;
  final String? group;
}

class WellnessRecord {
  const WellnessRecord({
    required this.taskId,
    required this.dateKey,
    required this.completedAt,
    required this.feedback,
    required this.points,
  });

  final String taskId;
  final String dateKey;
  final DateTime completedAt;
  final String feedback;
  final int points;

  Map<String, dynamic> toJson() => {
    'taskId': taskId,
    'dateKey': dateKey,
    'completedAt': completedAt.toIso8601String(),
    'feedback': feedback,
    'points': points,
  };

  factory WellnessRecord.fromJson(Map<String, dynamic> json) {
    return WellnessRecord(
      taskId: json['taskId']?.toString() ?? '',
      dateKey: json['dateKey']?.toString() ?? '',
      completedAt:
          DateTime.tryParse(json['completedAt']?.toString() ?? '') ??
          DateTime.now(),
      feedback: json['feedback']?.toString() ?? '',
      points: int.tryParse(json['points']?.toString() ?? '') ?? 0,
    );
  }
}
