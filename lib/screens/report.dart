import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../state/chair_sync_controller.dart';

class ReportPage extends StatelessWidget {
  const ReportPage({super.key, required this.controller});

  final ChairSyncController controller;

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: controller,
      builder: (context, _) {
        final history = controller.postureHistory;
        final total = history.length;

        final goodCount = history
            .where((item) => item["isGood"] == true)
            .length;
        final badCount = total - goodCount;

        final goodPercent = total == 0
            ? 0
            : ((goodCount / total) * 100).round();

        final avgScore = total == 0
            ? 0
            : (history
                          .map((item) => item["score"] as int)
                          .reduce((a, b) => a + b) /
                      total)
                  .round();

        final Map<String, int> postureCounts = {};
        for (final item in history) {
          final label = item["label"] as String;
          postureCounts[label] = (postureCounts[label] ?? 0) + 1;
        }

        return SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              // 清除資料按鈕
              Row(
                mainAxisAlignment: MainAxisAlignment.spaceBetween,
                children: [
                  const Text(
                    "報表總覽",
                    style: TextStyle(
                      fontSize: 22,
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF0F172A),
                    ),
                  ),
                  ElevatedButton.icon(
                    onPressed: () {
                      controller.clearPostureHistory();
                      controller.clearNotifications();

                      ScaffoldMessenger.of(context).showSnackBar(
                        const SnackBar(content: Text("報表與通知資料已清除")),
                      );
                    },
                    icon: const Icon(Icons.delete_outline, color: Colors.white),
                    label: const Text(
                      "清除資料",
                      style: TextStyle(color: Colors.white),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: Colors.red,
                      padding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 10,
                      ),
                    ),
                  ),
                ],
              ),

              const SizedBox(height: 12),

              _buildSummaryCard(total, avgScore),
              const SizedBox(height: 12),
              _buildQuickKpiRow(goodPercent, badCount),
              const SizedBox(height: 18),
              _buildDistributionAndStatsSection(
                postureCounts: postureCounts,
                total: total,
                goodCount: goodCount,
                badCount: badCount,
              ),
            ],
          ),
        );
      },
    );
  }

  Widget _buildQuickKpiRow(int goodPercent, int badCount) {
    return Row(
      children: [
        Expanded(
          child: _MiniKpiCard(
            title: '坐姿穩定度',
            value: '$goodPercent%',
            icon: Icons.insights_rounded,
            color: const Color(0xFF2563EB),
          ),
        ),
        const SizedBox(width: 10),
        Expanded(
          child: _MiniKpiCard(
            title: '提醒次數',
            value: '$badCount 次',
            icon: Icons.notifications_active_rounded,
            color: const Color(0xFF15803D),
          ),
        ),
      ],
    );
  }

  Widget _buildDistributionAndStatsSection({
    required Map<String, int> postureCounts,
    required int total,
    required int goodCount,
    required int badCount,
  }) {
    return LayoutBuilder(
      builder: (context, constraints) {
        final isCompact = constraints.maxWidth < 760;

        if (isCompact) {
          return Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              _buildSectionTitle("今日姿勢分布"),
              const SizedBox(height: 12),
              _buildPieChartCard(postureCounts: postureCounts, total: total),
              const SizedBox(height: 20),
              _buildSectionTitle("每日統計"),
              const SizedBox(height: 12),
              _buildStatsGrid(
                postureCounts: postureCounts,
                total: total,
                badCount: badCount,
              ),
            ],
          );
        }

        return Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildSectionTitle("今日姿勢分布"),
                  const SizedBox(height: 12),
                  _buildPieChartCard(
                    postureCounts: postureCounts,
                    total: total,
                  ),
                ],
              ),
            ),
            const SizedBox(width: 16),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  _buildSectionTitle("每日統計"),
                  const SizedBox(height: 12),
                  _buildStatsGrid(
                    postureCounts: postureCounts,
                    total: total,
                    badCount: badCount,
                  ),
                ],
              ),
            ),
          ],
        );
      },
    );
  }

  Widget _buildSummaryCard(int total, int avgScore) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
          colors: [Color(0xFF0F766E), Color(0xFF155E75)],
        ),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '今日健康摘要',
            style: TextStyle(color: Colors.white70, fontSize: 15),
          ),
          const SizedBox(height: 10),
          Text(
            total == 0 ? '尚無坐姿資料' : '平均姿勢分數 $avgScore 分',
            style: const TextStyle(
              color: Colors.white,
              fontSize: 28,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 8),
          Text(
            '目前已累積 $total 筆姿勢紀錄',
            style: const TextStyle(color: Colors.white, fontSize: 15),
          ),
        ],
      ),
    );
  }

  Widget _buildSectionTitle(String title) {
    return Text(
      title,
      style: const TextStyle(
        fontSize: 19,
        fontWeight: FontWeight.w800,
        color: Color(0xFF0F172A),
      ),
    );
  }

  Widget _buildPieChartCard({
    required Map<String, int> postureCounts,
    required int total,
  }) {
    final labels = ["姿勢正常", "身體前傾", "左側傾斜", "右側傾斜", "後仰過多", "久坐過久"];

    final colors = {
      "姿勢正常": Colors.green,
      "身體前傾": Colors.red,
      "左側傾斜": Colors.orange,
      "右側傾斜": Colors.deepOrange,
      "後仰過多": Colors.blue,
      "久坐過久": Colors.purple,
    };

    return Container(
      height: 280,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
      ),
      child: total == 0
          ? const Center(
              child: Text('尚無統計資料', style: TextStyle(color: Colors.black54)),
            )
          : Column(
              children: [
                Expanded(
                  child: PieChart(
                    PieChartData(
                      sectionsSpace: 3,
                      centerSpaceRadius: 40,
                      sections: labels.map((label) {
                        final count = postureCounts[label] ?? 0;
                        final percent = total == 0
                            ? 0
                            : ((count / total) * 100).round();

                        return PieChartSectionData(
                          value: count.toDouble(),
                          title: count == 0 ? '' : '$percent%',
                          radius: 55,
                          color: colors[label],
                          titleStyle: const TextStyle(
                            fontSize: 14,
                            fontWeight: FontWeight.bold,
                            color: Colors.white,
                          ),
                        );
                      }).toList(),
                    ),
                  ),
                ),
                const SizedBox(height: 12),
                const Wrap(
                  spacing: 12,
                  runSpacing: 8,
                  children: [
                    _LegendItem(color: Colors.green, text: "姿勢正常"),
                    _LegendItem(color: Colors.red, text: "身體前傾"),
                    _LegendItem(color: Colors.orange, text: "左側傾斜"),
                    _LegendItem(color: Colors.deepOrange, text: "右側傾斜"),
                    _LegendItem(color: Colors.blue, text: "後仰過多"),
                    _LegendItem(color: Colors.purple, text: "久坐過久"),
                  ],
                ),
              ],
            ),
    );
  }

  Widget _buildStatsGrid({
    required Map<String, int> postureCounts,
    required int total,
    required int badCount,
  }) {
    final stats = [
      (title: "姿勢正常", value: _percentText(postureCounts["姿勢正常"] ?? 0, total)),
      (title: "身體前傾", value: _percentText(postureCounts["身體前傾"] ?? 0, total)),
      (title: "左側傾斜", value: _percentText(postureCounts["左側傾斜"] ?? 0, total)),
      (title: "右側傾斜", value: _percentText(postureCounts["右側傾斜"] ?? 0, total)),
      (title: "後仰過多", value: _percentText(postureCounts["後仰過多"] ?? 0, total)),
      (title: "提醒次數", value: "$badCount 次"),
    ];

    return LayoutBuilder(
      builder: (context, constraints) {
        final columns = constraints.maxWidth < 500 ? 2 : 3;

        return GridView.builder(
          shrinkWrap: true,
          physics: const NeverScrollableScrollPhysics(),
          itemCount: stats.length,
          gridDelegate: SliverGridDelegateWithFixedCrossAxisCount(
            crossAxisCount: columns,
            crossAxisSpacing: 10,
            mainAxisSpacing: 10,
            mainAxisExtent: 100,
          ),
          itemBuilder: (context, index) {
            final stat = stats[index];
            return _StatCard(title: stat.title, value: stat.value);
          },
        );
      },
    );
  }

  String _percentText(int count, int total) {
    if (total == 0) return "0%";
    return "${((count / total) * 100).round()}%";
  }
}

class _StatCard extends StatelessWidget {
  const _StatCard({required this.title, required this.value});

  final String title;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        mainAxisAlignment: MainAxisAlignment.center,
        children: [
          Text(
            value,
            style: const TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: Color(0xFF0F766E),
            ),
          ),
          const SizedBox(height: 4),
          Text(
            title,
            textAlign: TextAlign.center,
            style: const TextStyle(fontSize: 13, color: Colors.black54),
          ),
        ],
      ),
    );
  }
}

class _LegendItem extends StatelessWidget {
  const _LegendItem({required this.color, required this.text});

  final Color color;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(width: 12, height: 12, color: color),
        const SizedBox(width: 6),
        Text(text),
      ],
    );
  }
}

class _MiniKpiCard extends StatelessWidget {
  const _MiniKpiCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.color,
  });

  final String title;
  final String value;
  final IconData icon;
  final Color color;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(title),
                Text(
                  value,
                  style: const TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w800,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
