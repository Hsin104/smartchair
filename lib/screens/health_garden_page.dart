import 'package:flutter/material.dart';

import '../models/wellness_models.dart';
import '../state/wellness_controller.dart';

class HealthGardenPage extends StatefulWidget {
  const HealthGardenPage({
    super.key,
    required this.controller,
    required this.postureCode,
  });

  final WellnessController controller;
  final String postureCode;

  @override
  State<HealthGardenPage> createState() => _HealthGardenPageState();
}

class _HealthGardenPageState extends State<HealthGardenPage>
    with SingleTickerProviderStateMixin {
  late final AnimationController _gardenAnimation;

  @override
  void initState() {
    super.initState();
    _gardenAnimation = AnimationController(
      vsync: this,
      duration: const Duration(seconds: 4),
    )..repeat(reverse: true);
    widget.controller.addListener(_refresh);
  }

  @override
  void dispose() {
    _gardenAnimation.dispose();
    widget.controller.removeListener(_refresh);
    super.dispose();
  }

  void _refresh() {
    if (mounted) setState(() {});
  }

  WellnessTask get _recommendedTask => widget.controller.tasks.first;

  Future<void> _complete(WellnessTask task) async {
    final feedback = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      builder: (context) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 4, 20, 20),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '完成後身體感受如何？',
                style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 8),
              const Text(
                '你的回饋會幫助 AI 下一次調整介入強度。',
                style: TextStyle(color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 12),
              ...['更放鬆', '差不多', '仍然緊繃'].map(
                (label) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: Icon(
                    label == '更放鬆'
                        ? Icons.sentiment_satisfied_alt_rounded
                        : Icons.self_improvement_rounded,
                  ),
                  title: Text(
                    label,
                    style: const TextStyle(fontWeight: FontWeight.w800),
                  ),
                  onTap: () => Navigator.of(context).pop(label),
                ),
              ),
            ],
          ),
        ),
      ),
    );
    if (feedback == null) return;
    final completed = await widget.controller.completeTask(
      task,
      feedback: feedback,
    );
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(completed ? '任務完成，花園獲得成長能量！' : '今天已完成這個任務，明天再來一次。'),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final controller = widget.controller;
    return Scaffold(
      backgroundColor: const Color(0xFFF4F8F3),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 24),
          children: [
            _gardenHeader(controller),
            const SizedBox(height: 14),
            _recommendedCard(_recommendedTask),
            const SizedBox(height: 18),
            const Text(
              '每日任務',
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 10),
            ...controller.tasks.map(_taskCard),
          ],
        ),
      ),
    );
  }

  Widget _gardenHeader(WellnessController controller) {
    final progress = controller.growthProgress;
    final gardenLevel = controller.level.clamp(1, 4);
    final stage = controller.level >= 4
        ? '療癒森林'
        : controller.level >= 3
        ? '茂盛花園'
        : controller.level >= 2
        ? '成長花圃'
        : '初生種子';
    return Container(
      padding: const EdgeInsets.fromLTRB(18, 18, 18, 16),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF14532D), Color(0xFF2F855A)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(24),
      ),
      child: Stack(
        children: [
          Positioned.fill(child: _gardenDecorations(gardenLevel)),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  const Expanded(
                    child: Text(
                      '健康養成花園',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 25,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                  Text(
                    'Lv.${controller.level}',
                    style: const TextStyle(
                      color: Color(0xFFD9F99D),
                      fontSize: 18,
                      fontWeight: FontWeight.w900,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 4),
              Text(
                '$stage · 連續 ${controller.streak} 天',
                style: const TextStyle(
                  color: Color(0xFFDCFCE7),
                  fontWeight: FontWeight.w700,
                ),
              ),
              const SizedBox(height: 18),
              Row(
                crossAxisAlignment: CrossAxisAlignment.end,
                children: [
                  AnimatedBuilder(
                    animation: _gardenAnimation,
                    builder: (context, child) => Transform.rotate(
                      angle: (_gardenAnimation.value - 0.5) * 0.08,
                      alignment: Alignment.bottomCenter,
                      child: child,
                    ),
                    child: TweenAnimationBuilder<double>(
                      tween: Tween(begin: 0, end: progress),
                      duration: const Duration(milliseconds: 700),
                      builder: (context, value, _) => Transform.scale(
                        scale: 0.9 + value * 0.18,
                        child: Text(
                          gardenLevel >= 4
                              ? '🌳'
                              : gardenLevel >= 3
                              ? '🌻'
                              : gardenLevel >= 2
                              ? '🌿'
                              : '🌱',
                          style: const TextStyle(fontSize: 68),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(width: 14),
                  Expanded(
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          '${controller.pointsInLevel}/100 成長能量',
                          style: const TextStyle(
                            color: Colors.white,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(height: 8),
                        ClipRRect(
                          borderRadius: BorderRadius.circular(99),
                          child: LinearProgressIndicator(
                            value: progress,
                            minHeight: 10,
                            backgroundColor: Colors.white24,
                            color: const Color(0xFFA3E635),
                          ),
                        ),
                        const SizedBox(height: 8),
                        Text(
                          '完成有效伸展，讓你的植物和身體一起長大',
                          style: TextStyle(
                            color: Colors.white.withValues(alpha: 0.82),
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  ),
                ],
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _gardenDecorations(int gardenLevel) {
    final decorations = gardenLevel >= 4
        ? ['🌲', '🦋', '🌼', '🍃', '✨']
        : gardenLevel >= 3
        ? ['🌼', '🌷', '🦋', '🍃']
        : gardenLevel >= 2
        ? ['🌱', '🌼', '🍃']
        : ['💧', '🍃'];
    return IgnorePointer(
      child: AnimatedBuilder(
        animation: _gardenAnimation,
        builder: (context, _) => Stack(
          children: [
            for (var index = 0; index < decorations.length; index++)
              Positioned(
                right: 8.0 + (index * 37) % 130,
                top: 8.0 + (index * 23) % 72,
                child: Opacity(
                  opacity: 0.28 + (_gardenAnimation.value * 0.18),
                  child: Transform.translate(
                    offset: Offset(0, (_gardenAnimation.value - 0.5) * 8),
                    child: Text(
                      decorations[index],
                      style: TextStyle(fontSize: index == 1 ? 20 : 17),
                    ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }

  Widget _recommendedCard(WellnessTask task) {
    final accepted = widget.controller.activeTaskId == task.id;
    final completed = widget.controller.isCompletedToday(task.id);
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFBEB),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFFDE68A)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            'AI 今日介入',
            style: TextStyle(
              color: Color(0xFF92400E),
              fontWeight: FontWeight.w900,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            task.title,
            style: const TextStyle(
              fontSize: 19,
              fontWeight: FontWeight.w900,
              color: Color(0xFF451A03),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            task.description,
            style: const TextStyle(color: Color(0xFF78350F), height: 1.45),
          ),
          const SizedBox(height: 14),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.68),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '下一步介入',
                  style: TextStyle(
                    color: Color(0xFF92400E),
                    fontSize: 13,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: _interventionDetail(
                        icon: Icons.timer_outlined,
                        label: '伸展時間',
                        value: '${task.durationSeconds} 秒',
                      ),
                    ),
                    Expanded(
                      child: _interventionDetail(
                        icon: Icons.local_florist_rounded,
                        label: '花園能量',
                        value: '+${task.points}',
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 8),
                const Text(
                  '完成後留下身體感受，能量會加入植物的成長進度。',
                  style: TextStyle(
                    color: Color(0xFF78350F),
                    fontSize: 12,
                    height: 1.4,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 12),
          if (completed)
            Container(
              width: double.infinity,
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
              decoration: BoxDecoration(
                color: const Color(0xFFFEF3C7),
                borderRadius: BorderRadius.circular(12),
              ),
              child: const Row(
                children: [
                  Icon(Icons.check_circle_rounded, color: Color(0xFFB45309)),
                  SizedBox(width: 8),
                  Expanded(
                    child: Text(
                      '今天已完成，明天再來一次就能繼續累積能量。',
                      style: TextStyle(
                        color: Color(0xFF92400E),
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                ],
              ),
            )
          else
            FilledButton.icon(
              onPressed: accepted
                  ? () => _complete(task)
                  : () => widget.controller.acceptTask(task),
              icon: Icon(
                accepted
                    ? Icons.check_circle_rounded
                    : Icons.play_arrow_rounded,
              ),
              label: Text(accepted ? '完成伸展並回饋' : '接受建議，加入今日任務'),
              style: FilledButton.styleFrom(
                backgroundColor: const Color(0xFFB45309),
              ),
            ),
        ],
      ),
    );
  }

  Widget _interventionDetail({
    required IconData icon,
    required String label,
    required String value,
  }) {
    return Row(
      children: [
        Icon(icon, size: 20, color: const Color(0xFFB45309)),
        const SizedBox(width: 6),
        Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(
              label,
              style: const TextStyle(color: Color(0xFF92400E), fontSize: 11),
            ),
            Text(
              value,
              style: const TextStyle(
                color: Color(0xFF451A03),
                fontSize: 15,
                fontWeight: FontWeight.w900,
              ),
            ),
          ],
        ),
      ],
    );
  }

  Widget _taskCard(WellnessTask task) {
    final completed = widget.controller.isCompletedToday(task.id);
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Icon(
            completed ? Icons.check_circle_rounded : Icons.spa_rounded,
            color: completed
                ? const Color(0xFF16A34A)
                : const Color(0xFF65A30D),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  task.title,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w900,
                    color: Color(0xFF0F172A),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  '${task.durationSeconds} 秒 · +${task.points} 能量',
                  style: const TextStyle(
                    color: Color(0xFF64748B),
                    fontSize: 14,
                    fontWeight: FontWeight.w700,
                  ),
                ),
              ],
            ),
          ),
          if (!completed)
            IconButton(
              onPressed: () => _complete(task),
              tooltip: '完成任務',
              icon: const Icon(Icons.arrow_forward_rounded),
            ),
        ],
      ),
    );
  }
}
