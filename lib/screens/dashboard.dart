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
  bool _isLoading = false;
  late final VoidCallback _controllerListener;

  String _postureDisplay = '等待後端資料';
  String _postureCode = '';
  int _score = 0;
  String _risk = '尚無資料';
  String _advice = '登入後並完成同步，這裡會顯示後端回傳的最新建議。';
  Color _color = const Color(0xFF64748B);

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

  @override
  void initState() {
    super.initState();
    _controllerListener = () {
      if (mounted) _syncFromController();
    };
    widget.controller.addListener(_controllerListener);
    _syncFromController();
    _fetch();
  }

  @override
  void didUpdateWidget(DashboardPage old) {
    super.didUpdateWidget(old);
    if (old.controller != widget.controller) {
      old.controller.removeListener(_controllerListener);
      widget.controller.addListener(_controllerListener);
      _syncFromController();
    }
    // 登入狀態改變時立即重新拉資料
    if (old.isLoggedIn != widget.isLoggedIn) _fetch();
  }

  @override
  void dispose() {
    widget.controller.removeListener(_controllerListener);
    super.dispose();
  }

  void _syncFromController() {
    setState(() {
      _postureDisplay = widget.controller.postureLabel.isNotEmpty
          ? widget.controller.postureLabel
          : '等待後端資料';
      _postureCode = widget.controller.postureCode;
      _score = widget.controller.postureScore;
      _risk = widget.controller.postureCode.isNotEmpty
          ? ApiService.toRisk(widget.controller.postureCode)
          : '尚無資料';
      _advice = widget.controller.latestAdvice;
      _color = widget.controller.postureCode.isNotEmpty
          ? _postureColor(widget.controller.postureCode)
          : const Color(0xFF64748B);
    });
  }

  Future<void> _fetch() async {
    if (_isLoading) return;
    setState(() => _isLoading = true);

    // 由控制器依後端輪詢同步資料，畫面跟著控制器狀態更新
    await widget.controller.refreshFromServer();
    // Diagnostic: directly query backend to help debug missing data
    try {
      final history = await ApiService.getPostureHistory(limit: 1);
      final notificationHistory = await ApiService.getNotificationHistory(
        limit: 10,
      );
      final adviceFromApi = history.isNotEmpty
          ? (history.first['physio_advice'] as String?) ??
                (history.first['advice'] as String?) ??
                ''
          : '';
      final loggedIn = await ApiService.isLoggedIn();
      final me = await ApiService.getMe();
      final token = await ApiService.getToken();
      final tokenFlag = (token != null && token.isNotEmpty) ? 'yes' : 'no';
      if (mounted) {
        final msg =
            'backend: history=${history.length}, notifications=${notificationHistory.length}, advice=${adviceFromApi.isNotEmpty ? 'yes' : 'no'}; auth: loggedIn=$loggedIn, me=${me != null ? 'yes' : 'no'}, token=$tokenFlag';
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(msg)));

        // 診斷對話框已移除：若需要，請使用畫面上的 SnackBar 或 BACKEND_DIAGNOSIS.md 傳給後端。
      }
    } catch (_) {}
    if (!widget.isLoggedIn && mounted) {
      setState(() {
        _advice = '目前未登入，登入後可取得個人化即時姿勢資料。';
      });
    }

    if (mounted) setState(() => _isLoading = false);
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
  Widget build(BuildContext context) {
    final hasData = _postureCode.isNotEmpty;
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
                value: hasData ? '$_score 分' : '尚無資料',
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
