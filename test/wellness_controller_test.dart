import 'package:flutter_test/flutter_test.dart';

import 'package:smart_chair_app/models/wellness_models.dart';
import 'package:smart_chair_app/state/wellness_controller.dart';

void main() {
  test('posture maps to a concrete intervention task', () {
    final controller = WellnessController();

    expect(controller.taskForPosture('forward').id, 'neck-reset');
    expect(controller.taskForPosture('sedentary').id, 'stand-reset');
    expect(controller.taskForPosture('unknown').id, 'posture-check');
  });

  test('wellness records preserve the intervention contract', () {
    final record = WellnessRecord(
      taskId: 'neck-reset',
      dateKey: '2026-10-16',
      completedAt: DateTime.parse('2026-10-16T08:30:00Z'),
      feedback: '肩頸比較放鬆',
      points: 15,
    );

    final restored = WellnessRecord.fromJson(record.toJson());

    expect(restored.taskId, record.taskId);
    expect(restored.dateKey, record.dateKey);
    expect(restored.feedback, record.feedback);
    expect(restored.points, record.points);
  });
}
