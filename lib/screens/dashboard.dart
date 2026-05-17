import 'dart:math';
import 'package:flutter/material.dart';
import '../state/chair_sync_controller.dart';
import '../services/api_service.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({
    super.key,
    required this.controller,
    required this.isLoggedIn,
    required this.onOpenReport,
    required this.onStartStretch,
  });

  final ChairSyncController controller;
  final bool isLoggedIn;
  final VoidCallback onOpenReport;
  final VoidCallback onStartStretch;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  bool _demoMode = false; // true = 示範模式（假資料），false = 即時模式（後端 API）
  bool _isLoading = false;

  String _postureDisplay = '姿勢正常';
  String _postureCode = 'normal';
  int _score = 92;
  String _risk = '低風險';
  String _advice = '目前姿勢良好，請繼續維持。';
  Color _color = const Color(0xFF16A34A);

  // 不使用計時器：僅以手動更新資料

  int get _todayReminderCount => widget.controller.notifications.length;

  String get _goodPostureDurationText {
    final goodCount = widget.controller.postureHistory
        .where((item) => item['isGood'] == true)
        .length;
    final goodSeconds = goodCount * 5;
    final hours = goodSeconds ~/ 3600;
    final minutes = (goodSeconds % 3600) ~/ 60;
    if (hours > 0) return '$hours 小時 $minutes 分';
    return '$minutes 分鐘';
  }

  // 示範用假資料（保留作為離線展示）
  static final List<Map<String, dynamic>> _demoPostures = [
    {'code': 'normal', 'advice': '目前姿勢良好，請繼續維持。建議每 30 分鐘起身活動 5 分鐘。'},
    {'code': 'forward', 'advice': '偵測到頭部前傾，建議收下巴並將螢幕提高至眼睛等高。'},
    {'code': 'left', 'advice': '偵測到身體左傾，建議調整骨盆讓左右坐骨均等受力。'},
    {'code': 'right', 'advice': '偵測到身體右傾，請將滑鼠移近身體並坐正。'},
    {'code': 'recline', 'advice': '後仰角度過大，建議回到正常坐姿並使用腰枕支撐。'},
    {'code': 'sedentary', 'advice': '久坐過久，建議立刻起身伸展 3–5 分鐘。'},
  ];

  @override
  void initState() {
    super.initState();
    // 不自動抓取資料，僅透過「手動更新資料」按鈕觸發 _fetch()
  }

  @override
  void didUpdateWidget(DashboardPage old) {
    super.didUpdateWidget(old);
    // 登入狀態改變時立即重新拉資料
    if (old.isLoggedIn != widget.isLoggedIn) _fetch();
  }

  Future<void> _fetch() async {
    if (_isLoading) return;
    setState(() => _isLoading = true);

    if (_demoMode) {
      // ── 示範模式：隨機假資料 ──
      await Future.delayed(const Duration(milliseconds: 400));
      final demo = _demoPostures[Random().nextInt(_demoPostures.length)];
      _applyPosture(
        code: demo['code'] as String,
        advice: demo['advice'] as String,
      );
    } else {
      // ── 即時模式：呼叫後端 API；若無資料則顯示目前狀態 ──
      final data = await ApiService.getLatestPosture();
      if (data != null) {
        _applyPosture(
          code: data['posture'] as String,
          advice: (data['physio_advice'] as String?) ?? '',
        );
      } else {
        if (!mounted) return;
        setState(() {
          _advice = widget.isLoggedIn
              ? '尚未取得即時姿勢資料，請確認後端服務與 API_BASE_URL 設定。'
              : '目前未登入，登入後可取得個人化即時姿勢資料。';
        });
      }
    }

    if (mounted) setState(() => _isLoading = false);
  }

  void _applyPosture({required String code, required String advice}) {
    final display = ApiService.toDisplayName(code);
    final score = ApiService.toScore(code);
    final risk = ApiService.toRisk(code);

    if (!mounted) return;
    setState(() {
      _postureCode = code;
      _postureDisplay = display;
      _score = score;
      _risk = risk;
      _advice = advice.isNotEmpty ? advice : '目前姿勢良好，請繼續維持。';
      _color = _postureColor(code);
    });

    widget.controller.updatePosture(
      label: display,
      score: score,
      isGood: code == 'normal',
    );
  }

  Color _postureColor(String code) {
    switch (code) {
      case 'normal':
        return const Color(0xFF16A34A);
      case 'forward':
        return const Color(0xFFDC2626);
      case 'left':
        return const Color(0xFFEA580C);
      case 'right':
        return const Color(0xFFC2410C);
      case 'recline':
        return const Color(0xFF2563EB);
      case 'sedentary':
        return const Color(0xFF7C3AED);
      default:
        return Colors.grey;
    }
  }

  @override
  void dispose() {
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    final isGood = _postureCode == 'normal';

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          // 姿勢狀態主卡片
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
                colors: [
                  _color.withValues(alpha: 0.92),
                  _color.withValues(alpha: 0.68),
                ],
              ),
              borderRadius: BorderRadius.circular(22),
              boxShadow: [
                BoxShadow(
                  color: _color.withValues(alpha: 0.25),
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
                            _postureDisplay,
                            style: const TextStyle(
                              color: Colors.white,
                              fontSize: 28,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ],
                      ),
                    ),
                    if (_isLoading)
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

          // 資訊卡片列
          Row(
            children: [
              _InfoCard(
                title: '姿勢評分',
                value: '$_score 分',
                icon: Icons.speed_rounded,
                accent: _color,
              ),
              const SizedBox(width: 10),
              _InfoCard(
                title: '風險等級',
                value: _risk,
                icon: Icons.warning_amber_rounded,
                accent: _color,
              ),
            ],
          ),

          const SizedBox(height: 10),

          Row(
            children: [
              _InfoCard(
                title: '今日提醒',
                value: '$_todayReminderCount 次',
                icon: Icons.notifications_active_rounded,
                accent: const Color(0xFF7C3AED),
              ),
              const SizedBox(width: 10),
              _InfoCard(
                title: '良好坐姿',
                value: _goodPostureDurationText,
                icon: Icons.check_circle_rounded,
                accent: const Color(0xFF15803D),
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
                        color: _color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(999),
                      ),
                      child: Text(
                        _risk,
                        style: TextStyle(
                          color: _color,
                          fontSize: 12,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  _advice,
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
                const SizedBox(height: 10),

                const SizedBox(height: 8),

                SizedBox(
                  width: double.infinity,
                  child: OutlinedButton.icon(
                    onPressed: _isLoading ? null : _fetch,
                    icon: _isLoading
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.refresh),
                    label: Text(_isLoading ? '取得中...' : '手動更新資料'),
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
