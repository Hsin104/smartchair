import 'package:flutter/material.dart';
import '../state/chair_sync_controller.dart';

class NotificationPage extends StatefulWidget {
  const NotificationPage({super.key, required this.controller});

  final ChairSyncController controller;

  @override
  State<NotificationPage> createState() => _NotificationPageState();
}

class _NotificationPageState extends State<NotificationPage> {
  String _selectedFilter = '全部';

  bool _matchesFilter(Map<String, dynamic> item) {
    if (_selectedFilter == '全部') return true;
    final color = item['color'] as Color;
    final category = _categoryFromColor(color);
    return category == _selectedFilter;
  }

  String _categoryFromColor(Color color) {
    // 大致根據顏色判定警示或提醒：
    // 紅/橘 -> 警示，紫/藍 -> 提醒，其他 -> 其它
    final value = color.value;
    if (value == 0xFFDC2626 || value == 0xFFF85701 || value == 0xFFEA580C) {
      return '警示';
    }
    if (value == 0xFF7C3AED || value == 0xFF2563EB || value == 0xFF0EA5E9) {
      return '提醒';
    }
    return '其它';
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: widget.controller,
      builder: (context, _) {
        final notifications = widget.controller.notifications
            .where(_matchesFilter)
            .toList();

        return RefreshIndicator(
          onRefresh: widget.controller.refreshFromServer,
          child: ListView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(
                  gradient: const LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [Color(0xFF1D4ED8), Color(0xFF0EA5E9)],
                  ),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '通知中心',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 24,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      '優先處理紅色與橘色通知，避免久坐與錯誤姿勢持續。',
                      style: TextStyle(color: Colors.white70, fontSize: 13),
                    ),
                    const SizedBox(height: 12),
                    Align(
                      alignment: Alignment.centerRight,
                      child: OutlinedButton.icon(
                        onPressed: () async {
                          await widget.controller.refreshFromServer();
                          if (context.mounted) {
                            ScaffoldMessenger.of(context).showSnackBar(
                              const SnackBar(content: Text("已從後端重新同步通知")),
                            );
                          }
                        },
                        icon: const Icon(Icons.refresh),
                        label: const Text("重新同步"),
                        style: OutlinedButton.styleFrom(
                          foregroundColor: Colors.white,
                          side: const BorderSide(color: Colors.white),
                        ),
                      ),
                    ),
                  ],
                ),
              ),

              const SizedBox(height: 12),

              const SizedBox(height: 12),

              ...notifications.map((item) {
                final color = item['color'] as Color;

                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(14),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: color.withValues(alpha: 0.22)),
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Container(
                        width: 46,
                        height: 46,
                        decoration: BoxDecoration(
                          color: color.withValues(alpha: 0.12),
                          borderRadius: BorderRadius.circular(12),
                        ),
                        child: Icon(
                          item['icon'] as IconData,
                          color: color,
                          size: 24,
                        ),
                      ),
                      const SizedBox(width: 12),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Row(
                              children: [
                                Expanded(
                                  child: Text(
                                    item['title'] as String,
                                    style: const TextStyle(
                                      fontSize: 16,
                                      color: Color(0xFF0F172A),
                                      fontWeight: FontWeight.w800,
                                    ),
                                  ),
                                ),
                                Text(
                                  item['time'] as String,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    color: Color(0xFF64748B),
                                    fontWeight: FontWeight.w600,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(height: 4),
                            Text(
                              item['message'] as String,
                              style: const TextStyle(
                                fontSize: 14,
                                color: Color(0xFF334155),
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                );
              }),
            ],
          ),
        );
      },
    );
  }
}

class _FilterChip extends StatelessWidget {
  const _FilterChip({required this.label, this.selected = false});

  final String label;
  final bool selected;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 7),
      decoration: BoxDecoration(
        color: selected ? const Color(0xFF0F766E) : Colors.white,
        borderRadius: BorderRadius.circular(999),
      ),
      child: Text(
        label,
        style: TextStyle(
          fontSize: 12,
          fontWeight: FontWeight.w700,
          color: selected ? Colors.white : const Color(0xFF475569),
        ),
      ),
    );
  }
}
