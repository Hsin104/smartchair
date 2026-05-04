import 'dart:async';
import 'package:flutter/material.dart';
import '../state/chair_sync_controller.dart';
import '../services/mock_api.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({
    super.key,
    required this.controller,
    required this.onOpenReport,
    required this.onStartStretch,
  });

  final ChairSyncController controller;
  final VoidCallback onOpenReport;
  final VoidCallback onStartStretch;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  bool demoMode = true;
  bool isLoading = false;

  String currentPosture = "姿勢正常";
  int currentScore = 92;
  String currentRisk = "低風險";
  String currentAdvice = "目前姿勢良好，請繼續維持。";
  Color currentColor = const Color(0xFF16A34A);

  Timer? timer;

  @override
  void initState() {
    super.initState();

    fetchMockPosture();

    timer = Timer.periodic(const Duration(seconds: 2), (timer) {
      if (demoMode) {
        fetchMockPosture();
      }
    });
  }

  Future<void> fetchMockPosture() async {
    if (isLoading) return;

    setState(() {
      isLoading = true;
    });

    final data = await MockApi.getPosture();

    if (!mounted) return;

    setState(() {
      currentPosture = data["posture"] as String;
      currentScore = data["score"] as int;
      currentRisk = data["risk"] as String;
      currentAdvice = data["advice"] as String;
      currentColor = getPostureColor(currentPosture);
      isLoading = false;
    });

    widget.controller.updatePosture(
      label: currentPosture,
      score: currentScore,
      isGood: currentPosture == "姿勢正常",
    );
  }

  Color getPostureColor(String posture) {
    switch (posture) {
      case "姿勢正常":
        return const Color(0xFF16A34A);
      case "身體前傾":
        return const Color(0xFFDC2626);
      case "左側傾斜":
        return const Color(0xFFEA580C);
      case "右側傾斜":
        return const Color(0xFFC2410C);
      case "後仰過多":
        return const Color(0xFF2563EB);
      case "久坐過久":
        return const Color(0xFF7C3AED);
      default:
        return Colors.grey;
    }
  }

  @override
  void dispose() {
    timer?.cancel();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final posture = currentPosture;
    final postureColor = currentColor;
    final score = currentScore.toString();
    final risk = currentRisk;
    final advice = currentAdvice;
    final isGood = posture == '姿勢正常';

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 目前姿勢狀態卡片
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  postureColor.withValues(alpha: 0.92),
                  postureColor.withValues(alpha: 0.68),
                ],
              ),
              borderRadius: BorderRadius.circular(22),
              boxShadow: [
                BoxShadow(
                  color: postureColor.withValues(alpha: 0.25),
                  blurRadius: 20,
                  offset: const Offset(0, 10),
                ),
              ],
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 56,
                      height: 56,
                      decoration: BoxDecoration(
                        color: Colors.white.withValues(alpha: 0.22),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: const Icon(
                        Icons.airline_seat_recline_normal_rounded,
                        color: Colors.white,
                        size: 30,
                      ),
                    ),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          const Text(
                            '目前姿勢狀態',
                            style: TextStyle(
                              color: Colors.white70,
                              fontSize: 14,
                            ),
                          ),
                          const SizedBox(height: 4),
                          Text(
                            posture,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 28,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (isLoading)
                      const SizedBox(
                        width: 22,
                        height: 22,
                        child: CircularProgressIndicator(
                          strokeWidth: 2,
                          color: Colors.white,
                        ),
                      ),
                  ],
                ),
                const SizedBox(height: 14),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 7,
                  ),
                  decoration: BoxDecoration(
                    color: Colors.white.withValues(alpha: 0.2),
                    borderRadius: BorderRadius.circular(999),
                  ),
                  child: Text(
                    isGood ? '目前良好，請維持這個姿勢' : '建議立即調整肩頸與背部角度',
                    style: const TextStyle(
                      color: Colors.white,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 14),

          // 資訊卡片
          Row(
            children: [
              Expanded(
                child: _InfoCard(
                  title: '姿勢評分',
                  value: '$score 分',
                  icon: Icons.speed_rounded,
                  accent: postureColor,
                ),
              ),
              const SizedBox(width: 10),
              _InfoCard(
                title: '風險等級',
                value: risk,
                icon: Icons.warning_amber_rounded,
                accent: postureColor,
              ),
            ],
          ),

          const SizedBox(height: 10),

          Row(
            children: [
              Expanded(
                child: _InfoCard(
                  title: '今日提醒',
                  value: isGood ? '2 次' : '5 次',
                  icon: Icons.notifications_active_rounded,
                  accent: const Color(0xFF7C3AED),
                ),
              ),
              const SizedBox(width: 10),
              const Expanded(
                child: _InfoCard(
                  title: '良好坐姿',
                  value: '4 小時 12 分',
                  icon: Icons.check_circle_rounded,
                  accent: Color(0xFF15803D),
                ),
              ),
            ],
          ),

          const SizedBox(height: 16),

          // AI 建議卡片
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Container(
                      width: 38,
                      height: 38,
                      decoration: BoxDecoration(
                        color: Colors.blue.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(12),
                      ),
                      child: const Icon(
                        Icons.psychology_alt_rounded,
                        color: Colors.blue,
                        size: 22,
                      ),
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'AI 物理治療師建議',
                        style: TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.w800,
                          color: Color(0xFF0F172A),
                        ),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(
                        horizontal: 10,
                        vertical: 5,
                      ),
                      decoration: BoxDecoration(
                        color: postureColor.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        risk,
                        style: TextStyle(
                          color: postureColor,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  advice,
                  style: const TextStyle(
                    fontSize: 14,
                    height: 1.6,
                    color: Color(0xFF334155),
                  ),
                ),
              ],
            ),
          ),

          const SizedBox(height: 16),

          // 快速操作
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(18),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '快速操作',
                  style: TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF0F172A),
                  ),
                ),
                const SizedBox(height: 10),

                SwitchListTile(
                  contentPadding: EdgeInsets.zero,
                  title: const Text(
                    "Demo 模式",
                    style: TextStyle(fontWeight: FontWeight.w700),
                  ),
                  subtitle: const Text("自動模擬後端 API 回傳坐姿資料"),
                  value: demoMode,
                  onChanged: (value) {
                    setState(() {
                      demoMode = value;
                    });
                  },
                ),

                const SizedBox(height: 8),

                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: isLoading ? null : fetchMockPosture,
                    icon: isLoading
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh),
                    label: Text(isLoading ? "取得中..." : "手動取得資料"),
                  ),
                ),

                const SizedBox(height: 10),

                Row(
                  children: [
                    Expanded(
                      child: FilledButton.icon(
                        onPressed: widget.onOpenReport,
                        icon: const Icon(Icons.bar_chart_rounded),
                        label: const Text('查看今日報表'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: widget.onStartStretch,
                        icon: const Icon(Icons.accessibility_new_rounded),
                        label: const Text('開始伸展提醒'),
                      ),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _InfoCard extends StatelessWidget {
  const _InfoCard({
    required this.title,
    required this.value,
    required this.icon,
    required this.accent,
  });

  final String title;
  final String value;
  final IconData icon;
  final Color accent;

  @override
  Widget build(BuildContext context) {
    return Expanded(
      child: Container(
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: Colors.white,
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: accent.withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(10),
                  ),
                  child: Icon(icon, size: 18, color: accent),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Text(
                    title,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      color: Color(0xFF64748B),
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
            const SizedBox(height: 10),
            Text(
              value,
              style: const TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: Color(0xFF0F172A),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
