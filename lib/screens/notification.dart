import 'package:flutter/material.dart';
import '../state/chair_sync_controller.dart';
import '../state/wellness_controller.dart';

class NotificationPage extends StatefulWidget {
  const NotificationPage({
    super.key,
    required this.controller,
    required this.wellnessController,
  });

  final ChairSyncController controller;
  final WellnessController wellnessController;

  @override
  State<NotificationPage> createState() => _NotificationPageState();
}

class _NotificationPageState extends State<NotificationPage> {
  String _selectedFilter = '提醒';
  static const _filterOptions = ['提醒', '周報'];

  bool _matchesFilter(Map<String, dynamic> item) {
    final kind = item['kind']?.toString();
    if (_selectedFilter == '周報') {
      return kind == 'weekly';
    }
    if (kind == 'weekly') return false;
    if (kind == 'posture' || kind == 'auto_checkout') return true;

    final color = item['color'] as Color;
    final category = _categoryFromColor(color);
    if (_selectedFilter == '提醒') {
      return category == '警示' || category == '提醒';
    }
    return false;
  }

  String _categoryFromColor(Color color) {
    // 大致根據顏色判定警示或提醒：
    // 紅/橘 -> 警示，紫/藍 -> 提醒，其他 -> 其它
    final value = color.toARGB32();
    if (value == 0xFFDC2626 || value == 0xFFEA580C || value == 0xFFC2410C) {
      return '警示';
    }
    if (value == 0xFF7C3AED || value == 0xFF2563EB || value == 0xFF0EA5E9) {
      return '提醒';
    }
    return '其它';
  }

  IconData _postureIcon(String title) {
    switch (title) {
      case '頭部前傾':
      case '身體前傾':
        return Icons.accessibility_new_rounded;
      case '身體左傾':
      case '身體右傾':
      case '左側傾斜':
      case '右側傾斜':
        return Icons.swap_horiz_rounded;
      case '過度後仰':
      case '後仰過多':
        return Icons.airline_seat_recline_extra_rounded;
      case '久坐未動':
      case '久坐過久':
        return Icons.hourglass_bottom_rounded;
      default:
        return Icons.airline_seat_recline_normal_rounded;
    }
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([
        widget.controller,
        widget.wellnessController,
      ]),
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
                      '姿勢提醒紀錄',
                      style: TextStyle(
                        color: Colors.white,
                        fontSize: 24,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '今日已完成 ${widget.wellnessController.records.where((record) => record.dateKey == _todayKey()).length} 個健康介入任務',
                      style: const TextStyle(
                        color: Colors.white70,
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 4),
                    const Text(
                      '此處列出已記錄的坐姿狀態，方便快速回看異常類型。',
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

              SingleChildScrollView(
                scrollDirection: Axis.horizontal,
                child: Row(
                  children: _filterOptions.map((filter) {
                    final selected = filter == _selectedFilter;
                    return Padding(
                      padding: const EdgeInsets.only(right: 8),
                      child: ChoiceChip(
                        label: Text(filter),
                        selected: selected,
                        onSelected: (_) => setState(() {
                          _selectedFilter = filter;
                        }),
                        avatar: Icon(
                          filter == '提醒'
                              ? Icons.notifications_active_rounded
                              : Icons.auto_awesome_rounded,
                          size: 17,
                        ),
                        selectedColor: const Color(0xFFDBEAFE),
                        labelStyle: TextStyle(
                          color: selected
                              ? const Color(0xFF1D4ED8)
                              : const Color(0xFF475569),
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                    );
                  }).toList(),
                ),
              ),

              const SizedBox(height: 12),

              ...notifications.map((item) {
                final color = item['color'] as Color;
                final title = item['title'] as String;

                return Container(
                  margin: const EdgeInsets.only(bottom: 12),
                  padding: const EdgeInsets.all(16),
                  decoration: BoxDecoration(
                    color: color.withValues(alpha: 0.07),
                    borderRadius: BorderRadius.circular(16),
                    border: Border.all(color: color.withValues(alpha: 0.35)),
                    boxShadow: [
                      BoxShadow(
                        color: color.withValues(alpha: 0.08),
                        blurRadius: 16,
                        offset: const Offset(0, 8),
                      ),
                    ],
                  ),
                  child: Row(
                    crossAxisAlignment: CrossAxisAlignment.center,
                    children: [
                      Container(
                        width: 52,
                        height: 52,
                        decoration: BoxDecoration(
                          color: color.withValues(alpha: 0.16),
                          borderRadius: BorderRadius.circular(14),
                        ),
                        child: Icon(
                          _postureIcon(title),
                          color: color,
                          size: 28,
                        ),
                      ),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              title,
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                              style: TextStyle(
                                fontSize: 24,
                                color: color,
                                fontWeight: FontWeight.w900,
                              ),
                            ),
                            const SizedBox(height: 6),
                            _buildMessage(
                              item['message'] as String,
                              isWeeklyReport: item['kind'] == 'weekly',
                            ),
                          ],
                        ),
                      ),
                      const SizedBox(width: 12),
                      Column(
                        mainAxisSize: MainAxisSize.min,
                        crossAxisAlignment: CrossAxisAlignment.end,
                        children: [
                          Text(
                            item['time'] as String,
                            style: TextStyle(
                              fontSize: 13,
                              color: color,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          // status dot removed per request
                        ],
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

  String _todayKey() {
    final now = DateTime.now();
    return '${now.year}-${now.month.toString().padLeft(2, '0')}-${now.day.toString().padLeft(2, '0')}';
  }

  Widget _buildMessage(String message, {required bool isWeeklyReport}) {
    if (!isWeeklyReport) {
      return Text(
        message,
        style: const TextStyle(
          fontSize: 15,
          color: Color(0xFF334155),
          fontWeight: FontWeight.w700,
        ),
      );
    }

    final lines = message.split('\n');
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: lines.map(_buildWeeklyLine).toList(),
    );
  }

  Widget _buildWeeklyLine(String rawLine) {
    final trimmedLine = rawLine.trim();
    if (trimmedLine.isEmpty) return const SizedBox(height: 8);
    if (trimmedLine == '---') {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 6),
        child: Divider(height: 1, color: Color(0xFFCBD5E1)),
      );
    }

    final isHeading = RegExp(r'^#{1,6}\s*').hasMatch(trimmedLine);
    final withoutHeading = trimmedLine.replaceFirst(RegExp(r'^#{1,6}\s*'), '');
    final isBullet = RegExp(r'^[-*]\s+').hasMatch(withoutHeading);
    final content = withoutHeading.replaceFirst(RegExp(r'^[-*]\s+'), '');
    final displayText = isBullet ? '• $content' : content;
    final textStyle = TextStyle(
      fontSize: isHeading ? 16 : 14,
      height: 1.55,
      color: const Color(0xFF334155),
      fontWeight: isHeading ? FontWeight.w900 : FontWeight.w600,
    );

    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: _buildBoldText(displayText, textStyle),
    );
  }

  Widget _buildBoldText(String text, TextStyle style) {
    final spans = <InlineSpan>[];
    final pattern = RegExp(r'\*\*(.+?)(?:\*\*|$)');
    var currentIndex = 0;

    for (final match in pattern.allMatches(text)) {
      if (match.start > currentIndex) {
        spans.add(TextSpan(text: text.substring(currentIndex, match.start)));
      }
      spans.add(
        TextSpan(
          text: match.group(1) ?? '',
          style: style.copyWith(fontWeight: FontWeight.w900),
        ),
      );
      currentIndex = match.end;
    }

    if (currentIndex < text.length) {
      spans.add(TextSpan(text: text.substring(currentIndex)));
    }

    return Text.rich(TextSpan(style: style, children: spans));
  }
}
