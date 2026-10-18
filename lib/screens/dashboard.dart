import 'dart:async';

import 'package:flutter/material.dart';
import 'package:fl_chart/fl_chart.dart';
import '../state/chair_sync_controller.dart';
import '../services/api_service.dart';
import '../state/wellness_controller.dart';

class DashboardPage extends StatefulWidget {
  const DashboardPage({
    super.key,
    required this.controller,
    required this.isLoggedIn,
    required this.wellnessController,
    required this.onOpenAi,
    required this.onOpenGarden,
    required this.onOpenSettings,
  });

  final ChairSyncController controller;
  final bool isLoggedIn;
  final WellnessController wellnessController;
  final VoidCallback onOpenAi;
  final VoidCallback onOpenGarden;
  final VoidCallback onOpenSettings;

  @override
  State<DashboardPage> createState() => _DashboardPageState();
}

class _DashboardPageState extends State<DashboardPage> {
  bool _isLoading = false;
  bool _isCalibrating = false;
  late final VoidCallback _controllerListener;
  Timer? _pageTimer;
  final ScrollController _scrollController = ScrollController();
  final GlobalKey _historyKey = GlobalKey();

  String _postureDisplay = '無人就坐';
  String _postureCode = '';
  int _score = 0;
  String _risk = '尚無資料';
  Color _color = const Color(0xFF64748B);

  int get _todayReminderCount => widget.controller.notifications.length;

  String get _pageElapsedText {
    final sessionOpenedAt = widget.controller.sessionOpenedAt;
    if (sessionOpenedAt == null) return '0秒';

    final elapsed = DateTime.now().difference(sessionOpenedAt);
    final hours = elapsed.inHours;
    final minutes = elapsed.inMinutes.remainder(60);
    final seconds = elapsed.inSeconds.remainder(60);
    if (hours > 0) {
      return '$hours時${minutes.toString().padLeft(2, '0')}分${seconds.toString().padLeft(2, '0')}秒';
    }
    if (minutes > 0) {
      return '$minutes分${seconds.toString().padLeft(2, '0')}秒';
    }
    return '$seconds秒';
  }

  @override
  void initState() {
    super.initState();
    _controllerListener = () {
      if (mounted) _syncFromController();
    };
    widget.controller.addListener(_controllerListener);
    widget.wellnessController.addListener(_controllerListener);
    _pageTimer = Timer.periodic(const Duration(seconds: 1), (_) {
      if (mounted) setState(() {});
    });
    _syncFromController();
    _enterPage();
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
    _pageTimer?.cancel();
    _scrollController.dispose();
    widget.controller.removeListener(_controllerListener);
    widget.wellnessController.removeListener(_controllerListener);
    super.dispose();
  }

  Future<void> _enterPage() async {
    if (!widget.isLoggedIn) return;

    try {
      await ApiService.chairCheckin();
      widget.controller.startSession();
      widget.controller.startAutoSync();
      await _fetch();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('進入坐姿監測頁失敗，請稍後再試。')));
    }
  }

  void _syncFromController() {
    setState(() {
      _postureDisplay = widget.controller.postureLabel.isNotEmpty
          ? widget.controller.postureLabel
          : '無人就坐';
      _postureCode = widget.controller.postureCode;
      _score = widget.controller.postureScore;
      _risk = widget.controller.postureCode.isNotEmpty
          ? ApiService.toRisk(widget.controller.postureCode)
          : '尚無資料';
      // 不在同步時自動顯示 AI 建議；改為按鈕按下時才載入/顯示
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
    if (mounted) {
      final message = widget.controller.postureCode.isNotEmpty
          ? '已同步最新姿勢資料'
          : '目前沒有後端資料，顯示無人就坐';
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(message)));
    }
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _calibrateAuto() async {
    if (_isCalibrating) return;

    final messenger = ScaffoldMessenger.of(context);
    setState(() => _isCalibrating = true);

    try {
      await ApiService.chairCheckin();
      final result = await ApiService.calibrateChairAuto();

      if (!mounted) return;

      if (result.success) {
        await widget.controller.refreshFromServer();
        final samplesText = result.samples != null
            ? '，樣本數 ${result.samples}'
            : '';
        messenger.showSnackBar(SnackBar(content: Text('校準成功$samplesText')));
      } else {
        messenger.showSnackBar(SnackBar(content: Text(result.message)));
      }
    } catch (_) {
      if (!mounted) return;
      messenger.showSnackBar(
        const SnackBar(content: Text('校準失敗，請檢查連線與感測器資料。')),
      );
    } finally {
      if (mounted) {
        setState(() => _isCalibrating = false);
      }
    }
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
      controller: _scrollController,
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
                          AnimatedSwitcher(
                            duration: const Duration(milliseconds: 350),
                            transitionBuilder: (child, animation) =>
                                FadeTransition(
                                  opacity: animation,
                                  child: SlideTransition(
                                    position: Tween<Offset>(
                                      begin: const Offset(0, 0.2),
                                      end: Offset.zero,
                                    ).animate(animation),
                                    child: child,
                                  ),
                                ),
                            child: Text(
                              _postureDisplay,
                              key: ValueKey(_postureDisplay),
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 28,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(width: 12),
                    Column(
                      crossAxisAlignment: CrossAxisAlignment.end,
                      children: [
                        if (_isLoading)
                          const SizedBox(
                            width: 22,
                            height: 22,
                            child: CircularProgressIndicator(
                              strokeWidth: 2,
                              color: Colors.white,
                            ),
                          ),
                        if (_isLoading) const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: Colors.white.withValues(alpha: 0.18),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(
                              color: Colors.white.withValues(alpha: 0.18),
                            ),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              const Text(
                                '你已就座時長',
                                style: TextStyle(
                                  color: Colors.white,
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _pageElapsedText,
                                style: const TextStyle(
                                  color: Colors.white,

                                  fontSize: 22,
                                  fontWeight: FontWeight.w800,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                _postureDisplay == '無人就坐'
                    ? const SizedBox.shrink()
                    : Container(
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

          // 資訊卡片列（同一橫排顯示三張卡）
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
              const SizedBox(width: 10),
              _InfoCard(
                title: '今日提醒',
                value: '$_todayReminderCount 次',
                icon: Icons.notifications_active_rounded,
                accent: const Color(0xFF7C3AED),
              ),
            ],
          ),

          const SizedBox(height: 16),

          _buildReportSnapshot(),

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
                const SizedBox(height: 10),
                SizedBox(
                  width: double.infinity,
                  child: ElevatedButton.icon(
                    onPressed: _isCalibrating ? null : _calibrateAuto,
                    icon: _isCalibrating
                        ? const SizedBox(
                            width: 16,
                            height: 16,
                            child: CircularProgressIndicator(strokeWidth: 2),
                          )
                        : const Icon(Icons.tune_rounded),
                    label: Text(_isCalibrating ? '校準中...' : '自動校準'),
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildReportSnapshot() {
    final history = widget.controller.postureHistory;
    final total = history.length;
    final postureCounts = <String, int>{};
    for (final item in history) {
      final label = item['label'] as String;
      postureCounts[label] = (postureCounts[label] ?? 0) + 1;
    }

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '今日坐姿分布',
            style: TextStyle(
              fontSize: 16,
              fontWeight: FontWeight.w900,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 8),
          _buildPosturePieChart(postureCounts, total),
        ],
      ),
    );
  }

  Widget _buildPosturePieChart(Map<String, int> postureCounts, int total) {
    const colors = <String, Color>{
      '姿勢正常': Color(0xFF16A34A),
      '頭部前傾': Color(0xFFDC2626),
      '身體左傾': Color(0xFFEA580C),
      '身體右傾': Color(0xFFC2410C),
      '過度後仰': Color(0xFF2563EB),
      '久坐未動': Color(0xFF7C3AED),
    };

    if (total == 0) {
      return Container(
        height: 180,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          color: const Color(0xFFF8FAFC),
          borderRadius: BorderRadius.circular(16),
        ),
        child: const Text(
          '目前尚無今日坐姿資料',
          style: TextStyle(color: Color(0xFF64748B)),
        ),
      );
    }

    return SizedBox(
      height: 220,
      child: Row(
        children: [
          Expanded(
            flex: 5,
            child: PieChart(
              PieChartData(
                centerSpaceRadius: 38,
                sectionsSpace: 2,
                sections: postureCounts.entries
                    .where((entry) => entry.value > 0)
                    .map(
                      (entry) => PieChartSectionData(
                        value: entry.value.toDouble(),
                        title: '${((entry.value / total) * 100).round()}%',
                        color: colors[entry.key] ?? const Color(0xFF64748B),
                        radius: 54,
                        titleStyle: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    )
                    .toList(),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            flex: 6,
            child: ListView(
              physics: const NeverScrollableScrollPhysics(),
              children: postureCounts.entries
                  .where((entry) => entry.value > 0)
                  .map(
                    (entry) => Padding(
                      padding: const EdgeInsets.only(bottom: 8),
                      child: Row(
                        children: [
                          Container(
                            width: 10,
                            height: 10,
                            decoration: BoxDecoration(
                              color:
                                  colors[entry.key] ?? const Color(0xFF64748B),
                              shape: BoxShape.circle,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Expanded(
                            child: Text(
                              entry.key,
                              overflow: TextOverflow.ellipsis,
                              style: const TextStyle(
                                fontSize: 12,
                                fontWeight: FontWeight.w700,
                                color: Color(0xFF334155),
                              ),
                            ),
                          ),
                          Text(
                            '${entry.value} 次',
                            style: const TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.w900,
                              color: Color(0xFF0F172A),
                            ),
                          ),
                        ],
                      ),
                    ),
                  )
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }

  // ignore: unused_element
  Widget _buildHealthOverview() {
    final advice = widget.controller.latestAdvice.trim();
    final wellness = widget.wellnessController;
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Text(
            '今日健康總覽',
            style: TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w900,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 12),
          Row(
            children: [
              Expanded(
                child: _OverviewTile(
                  icon: Icons.psychology_alt_rounded,
                  title: 'AI 建議',
                  value: advice.isEmpty ? '等待同步' : advice,
                  color: const Color(0xFF2563EB),
                  onTap: widget.onOpenAi,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _OverviewTile(
                  icon: Icons.local_florist_rounded,
                  title: '健康花園',
                  value: 'Lv.${wellness.level} · ${wellness.points} 能量',
                  color: const Color(0xFF16A34A),
                  onTap: widget.onOpenGarden,
                ),
              ),
            ],
          ),
          const SizedBox(height: 10),
          Row(
            children: [
              Expanded(
                child: _OverviewTile(
                  icon: Icons.history_rounded,
                  title: '歷史報表',
                  value: '${widget.controller.postureHistory.length} 筆姿勢紀錄',
                  color: const Color(0xFF7C3AED),
                  onTap: _scrollToHistory,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: _OverviewTile(
                  icon: Icons.tune_rounded,
                  title: '個人設定',
                  value: '調整身體資料與偏好',
                  color: const Color(0xFF0F766E),
                  onTap: widget.onOpenSettings,
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  void _scrollToHistory() {
    final context = _historyKey.currentContext;
    if (context != null) {
      Scrollable.ensureVisible(
        context,
        duration: const Duration(milliseconds: 450),
        curve: Curves.easeOutCubic,
      );
    }
  }

  // ignore: unused_element
  Widget _buildHistoryReport() {
    final history = widget.controller.postureHistory.reversed.take(12).toList();
    if (history.isEmpty) {
      return _reportSection(
        title: '歷史報表',
        child: const Padding(
          padding: EdgeInsets.symmetric(vertical: 20),
          child: Center(
            child: Text(
              '目前尚無姿勢歷史紀錄',
              style: TextStyle(color: Color(0xFF64748B)),
            ),
          ),
        ),
      );
    }

    return _reportSection(
      title: '歷史報表',
      child: Column(
        children: history.map((item) {
          final score = item['score'] as int? ?? 0;
          final label = item['label']?.toString() ?? '未知姿勢';
          final time = item['time'] is DateTime
              ? _formatHistoryTime(item['time'] as DateTime)
              : '';
          final good = item['isGood'] == true;
          return Container(
            margin: const EdgeInsets.only(bottom: 8),
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(
              color: const Color(0xFFF8FAFC),
              borderRadius: BorderRadius.circular(12),
            ),
            child: Row(
              children: [
                Icon(
                  good
                      ? Icons.check_circle_rounded
                      : Icons.warning_amber_rounded,
                  color: good
                      ? const Color(0xFF16A34A)
                      : const Color(0xFFEA580C),
                  size: 20,
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Text(
                    label,
                    style: const TextStyle(
                      fontWeight: FontWeight.w800,
                      color: Color(0xFF334155),
                    ),
                  ),
                ),
                Text(
                  '$score 分',
                  style: TextStyle(
                    color: good
                        ? const Color(0xFF16A34A)
                        : const Color(0xFFEA580C),
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const SizedBox(width: 10),
                Text(
                  time,
                  style: const TextStyle(
                    color: Color(0xFF94A3B8),
                    fontSize: 12,
                  ),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  Widget _reportSection({required String title, required Widget child}) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(20),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: const TextStyle(
              fontSize: 18,
              fontWeight: FontWeight.w900,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 12),
          child,
        ],
      ),
    );
  }

  String _formatHistoryTime(DateTime time) {
    return '${time.month}/${time.day} ${time.hour.toString().padLeft(2, '0')}:${time.minute.toString().padLeft(2, '0')}';
  }
}

class _OverviewTile extends StatelessWidget {
  const _OverviewTile({
    required this.icon,
    required this.title,
    required this.value,
    required this.color,
    required this.onTap,
  });

  final IconData icon;
  final String title;
  final String value;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      borderRadius: BorderRadius.circular(16),
      child: Container(
        constraints: const BoxConstraints(minHeight: 104),
        padding: const EdgeInsets.all(12),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.08),
          borderRadius: BorderRadius.circular(16),
        ),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(icon, color: color, size: 24),
            const SizedBox(height: 7),
            Text(
              title,
              style: TextStyle(color: color, fontWeight: FontWeight.w900),
            ),
            const SizedBox(height: 4),
            Text(
              value,
              maxLines: 2,
              overflow: TextOverflow.ellipsis,
              style: const TextStyle(
                color: Color(0xFF334155),
                fontSize: 12,
                height: 1.35,
              ),
            ),
          ],
        ),
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
                      fontSize: 16,
                      color: Color(0xFF64748B),
                      fontWeight: FontWeight.w700,
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
