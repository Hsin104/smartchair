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
  final Set<String> _promptedAutoCheckoutIds = {};
  late final VoidCallback _controllerListener;
  Timer? _pageTimer;
  final ScrollController _scrollController = ScrollController();

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
      final chairId = await ApiService.getSavedChairId();
      if (chairId == null || chairId.isEmpty) {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(const SnackBar(content: Text('請先登出並重新登入以選擇椅子。')));
        }
        return;
      }
      final checkin = await ApiService.chairCheckin(deviceId: chairId);
      if (!mounted || !checkin.success) {
        if (mounted) {
          ScaffoldMessenger.of(
            context,
          ).showSnackBar(SnackBar(content: Text(checkin.message)));
        }
        return;
      }
      widget.controller.startSession();
      widget.controller.startAutoSync();
      await _fetch();
      if (!mounted || checkin.calibrated) return;
      final shouldCalibrate = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('需要校準坐姿'),
          content: const Text('請坐正並保持不動約 5 秒，現在要開始校準嗎？'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('稍後'),
            ),
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('開始校準'),
            ),
          ],
        ),
      );
      if (shouldCalibrate == true && mounted) await _calibrateAuto();
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
          ? ApiService.postureColor(widget.controller.postureCode)
          : const Color(0xFF64748B);
    });
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!mounted) return;
      for (final item in widget.controller.notifications.reversed) {
        if (item['kind']?.toString() != 'auto_checkout') continue;
        final id = item['id']?.toString();
        if (id == null || id.isEmpty) continue;
        if (_promptedAutoCheckoutIds.add(id)) {
          _promptRecheckIn();
          break;
        }
      }
    });
  }

  Future<void> _promptRecheckIn() async {
    if (!mounted) return;
    final shouldCheckin = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('椅子已自動離座'),
        content: const Text('椅子已自動離座，要重新入座嗎？'),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('稍後'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('重新入座'),
          ),
        ],
      ),
    );
    if (shouldCheckin != true || !mounted) return;
    final chairId = await ApiService.getSavedChairId();
    if (chairId == null || chairId.isEmpty) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('請先重新登入並選擇椅子。')));
      }
      return;
    }
    final result = await ApiService.chairCheckin(deviceId: chairId);
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(content: Text(result.success ? '已重新入座' : result.message)),
    );
    if (result.success) {
      widget.controller.startSession();
      await widget.controller.refreshFromServer();
    }
  }

  Future<void> _fetch() async {
    if (_isLoading) return;
    setState(() => _isLoading = true);

    // 由控制器依後端輪詢同步資料，畫面跟著控制器狀態更新
    await widget.controller.refreshFromServer();
    if (mounted) setState(() => _isLoading = false);
  }

  Future<void> _calibrateAuto() async {
    if (_isCalibrating) return;

    final messenger = ScaffoldMessenger.of(context);
    setState(() => _isCalibrating = true);

    try {
      final chairId = await ApiService.getSavedChairId();
      if (chairId == null || chairId.isEmpty) {
        throw StateError('請先選擇椅子');
      }
      final checkin = await ApiService.chairCheckin(deviceId: chairId);
      if (!checkin.success) {
        throw StateError(checkin.message);
      }
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
              color: Colors.white,
              borderRadius: BorderRadius.circular(22),
              border: Border.all(color: _color.withValues(alpha: 0.3)),
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
                        color: _color.withValues(alpha: 0.12),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: const Icon(
                        Icons.airline_seat_recline_normal_rounded,
                        color: Color(0xFF0F172A),
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
                              color: Color(0xFF64748B),
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
                                color: Color(0xFF0F172A),
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
                              color: Color(0xFF64748B),
                            ),
                          ),
                        if (_isLoading) const SizedBox(height: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 12,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: const Color(0xFFF1F5F9),
                            borderRadius: BorderRadius.circular(14),
                            border: Border.all(color: const Color(0xFFE2E8F0)),
                          ),
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.end,
                            children: [
                              const Text(
                                '你已就座時長',
                                style: TextStyle(
                                  color: Color(0xFF64748B),
                                  fontSize: 15,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              const SizedBox(height: 4),
                              Text(
                                _pageElapsedText,
                                style: const TextStyle(
                                  color: Color(0xFF0F172A),

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
                          color: _color.withValues(alpha: 0.1),
                          borderRadius: BorderRadius.circular(999),
                        ),
                        child: Text(
                          isGood ? '目前良好，請維持這個姿勢' : '建議立即調整肩頸與背部角度',
                          style: const TextStyle(
                            color: Color(0xFF334155),
                            fontSize: 13,
                            fontWeight: FontWeight.w600,
                          ),
                        ),
                      ),
              ],
            ),
          ),

          const SizedBox(height: 14),

          LayoutBuilder(
            builder: (context, constraints) {
              final cards = [
                _InfoCard(
                  title: '姿勢評分',
                  value: hasData ? '$_score 分' : '尚無資料',
                  icon: Icons.speed_rounded,
                  accent: _color,
                ),
                _InfoCard(
                  title: '風險等級',
                  value: _risk,
                  icon: Icons.warning_amber_rounded,
                  accent: _color,
                ),
                _InfoCard(
                  title: '今日提醒',
                  value: '$_todayReminderCount 次',
                  icon: Icons.notifications_active_rounded,
                  accent: const Color(0xFF7C3AED),
                ),
                _InfoCard(
                  title: '椅子電量',
                  value:
                      widget.controller.chairBattery?.label(
                        online: widget.controller.chairOnline,
                      ) ??
                      '電量未知',
                  icon: Icons.battery_std_rounded,
                  accent: !widget.controller.chairOnline
                      ? const Color(0xFF94A3B8)
                      : (widget.controller.chairBattery?.isLow ?? false)
                      ? const Color(0xFFDC2626)
                      : const Color(0xFF16A34A),
                  valueColor: !widget.controller.chairOnline
                      ? const Color(0xFF94A3B8)
                      : (widget.controller.chairBattery?.isLow ?? false)
                      ? const Color(0xFFDC2626)
                      : null,
                ),
              ];

              if (constraints.maxWidth >= 560) {
                return Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    for (var i = 0; i < cards.length; i++) ...[
                      if (i > 0) const SizedBox(width: 10),
                      Expanded(child: cards[i]),
                    ],
                  ],
                );
              }

              return Wrap(
                spacing: 10,
                runSpacing: 10,
                children: cards
                    .map(
                      (card) => SizedBox(
                        width: (constraints.maxWidth - 10) / 2,
                        child: card,
                      ),
                    )
                    .toList(),
              );
            },
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
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton.icon(
                        onPressed: _isLoading ? null : _fetch,
                        icon: const Icon(Icons.refresh),
                        label: const Text('更新'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: ElevatedButton.icon(
                        onPressed: _isCalibrating ? null : _calibrateAuto,
                        icon: const Icon(Icons.tune_rounded),
                        label: Text(_isCalibrating ? '校準中...' : '校準'),
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

  Widget _buildReportSnapshot() {
    final postures = widget.controller.todayPostures
        .where((item) => item['posture']?.toString() != 'empty')
        .toList();

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
          Text(
            '今日總坐著時間 ${widget.controller.sittingMinutes.round()} 分鐘',
            style: const TextStyle(
              fontSize: 13,
              fontWeight: FontWeight.w700,
              color: Color(0xFF64748B),
            ),
          ),
          const SizedBox(height: 8),
          _buildPosturePieChart(postures),
        ],
      ),
    );
  }

  Widget _buildPosturePieChart(List<Map<String, dynamic>> postures) {
    if (postures.isEmpty) {
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
                centerSpaceColor: Colors.white,
                sections: postures
                    .where((item) {
                      final ratio = (item['ratio'] as num?)?.toDouble() ?? 0;
                      return ratio > 0;
                    })
                    .map((item) {
                      final code = item['posture']?.toString() ?? '';
                      final ratio = (item['ratio'] as num?)?.toDouble() ?? 0;
                      return PieChartSectionData(
                        value: ratio,
                        title: '${(ratio * 100).round()}%',
                        color: ApiService.postureColor(code),
                        radius: 54,
                        titleStyle: const TextStyle(
                          color: Colors.white,
                          fontSize: 11,
                          fontWeight: FontWeight.w900,
                        ),
                      );
                    })
                    .toList(),
              ),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            flex: 6,
            child: ListView(
              physics: const NeverScrollableScrollPhysics(),
              children: postures
                  .where((item) {
                    final ratio = (item['ratio'] as num?)?.toDouble() ?? 0;
                    return ratio > 0;
                  })
                  .map((item) {
                    final code = item['posture']?.toString() ?? '';
                    final display =
                        item['display']?.toString() ??
                        ApiService.toDisplayName(code);
                    final minutes = (item['minutes'] as num?)?.toInt() ?? 0;
                    final episodes = (item['episodes'] as num?)?.toInt() ?? 0;
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 7),
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 9,
                          vertical: 7,
                        ),
                        decoration: BoxDecoration(
                          color: ApiService.postureColor(
                            code,
                          ).withValues(alpha: 0.08),
                          borderRadius: BorderRadius.circular(10),
                          border: Border.all(
                            color: ApiService.postureColor(
                              code,
                            ).withValues(alpha: 0.22),
                          ),
                        ),
                        child: Row(
                          children: [
                            Icon(
                              _postureIcon(code),
                              color: ApiService.postureColor(code),
                              size: 19,
                            ),
                            const SizedBox(width: 7),
                            Expanded(
                              child: Text(
                                display,
                                overflow: TextOverflow.ellipsis,
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w900,
                                  color: Color(0xFF1E293B),
                                ),
                              ),
                            ),
                            Column(
                              crossAxisAlignment: CrossAxisAlignment.end,
                              children: [
                                Text(
                                  '$minutes 分鐘・$episodes 次',
                                  style: const TextStyle(
                                    fontSize: 13,
                                    fontWeight: FontWeight.w900,
                                    color: Color(0xFF0F172A),
                                  ),
                                ),
                                Text(
                                  _postureStatus(code),
                                  style: TextStyle(
                                    fontSize: 10,
                                    fontWeight: FontWeight.w800,
                                    color: ApiService.postureColor(code),
                                  ),
                                ),
                              ],
                            ),
                          ],
                        ),
                      ),
                    );
                  })
                  .toList(),
            ),
          ),
        ],
      ),
    );
  }

  IconData _postureIcon(String code) {
    switch (code) {
      case 'normal':
        return Icons.check_circle_rounded;
      case 'forward':
        return Icons.accessibility_new_rounded;
      case 'left':
      case 'right':
        return Icons.swap_horiz_rounded;
      case 'recline':
        return Icons.airline_seat_recline_extra_rounded;
      case 'sedentary':
        return Icons.hourglass_bottom_rounded;
      default:
        return Icons.info_outline_rounded;
    }
  }

  String _postureStatus(String code) {
    return code == 'normal' ? '正常' : '需要调整';
  }
}

class HealthReportPage extends StatelessWidget {
  const HealthReportPage({super.key, required this.controller});

  final ChairSyncController controller;

  @override
  Widget build(BuildContext context) {
    final postures = controller.todayPostures
        .where((item) => item['posture']?.toString() != 'empty')
        .where((item) => (item['ratio'] as num?)?.toDouble() != null)
        .toList();
    final normalRatio =
        postures
            .where((item) => item['posture']?.toString() == 'normal')
            .fold<double>(
              0,
              (sum, item) => sum + ((item['ratio'] as num?)?.toDouble() ?? 0),
            ) *
        100;

    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '今日健康摘要',
                  style: TextStyle(
                    fontSize: 20,
                    fontWeight: FontWeight.w900,
                    color: Color(0xFF0F172A),
                  ),
                ),
                const SizedBox(height: 14),
                Wrap(
                  spacing: 10,
                  runSpacing: 10,
                  children: [
                    _ReportMetric(
                      title: '就坐時間',
                      value: '${controller.sittingMinutes.round()} 分',
                      icon: Icons.schedule_rounded,
                      color: const Color(0xFF2563EB),
                    ),
                    _ReportMetric(
                      title: '正常坐姿',
                      value: '${normalRatio.round()}%',
                      icon: Icons.check_circle_rounded,
                      color: const Color(0xFF16A34A),
                    ),
                    _ReportMetric(
                      title: '今日提醒',
                      value: '${controller.notifications.length} 次',
                      icon: Icons.notifications_active_rounded,
                      color: const Color(0xFF7C3AED),
                    ),
                  ],
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: const Color(0xFFE2E8F0)),
            ),
            child: postures.isEmpty
                ? const SizedBox(
                    height: 180,
                    child: Center(
                      child: Text(
                        '目前尚無今日坐姿資料',
                        style: TextStyle(color: Color(0xFF64748B)),
                      ),
                    ),
                  )
                : LayoutBuilder(
                    builder: (context, constraints) {
                      final compact = constraints.maxWidth < 620;
                      final chart = SizedBox(
                        height: 220,
                        width: compact ? double.infinity : 280,
                        child: PieChart(
                          PieChartData(
                            centerSpaceRadius: 42,
                            sectionsSpace: 2,
                            sections: postures.map((item) {
                              final code = item['posture']?.toString() ?? '';
                              final ratio =
                                  (item['ratio'] as num?)?.toDouble() ?? 0;
                              return PieChartSectionData(
                                value: ratio,
                                title: '${(ratio * 100).round()}%',
                                color: ApiService.postureColor(code),
                                radius: 58,
                                titleStyle: const TextStyle(
                                  color: Colors.white,
                                  fontSize: 12,
                                  fontWeight: FontWeight.w900,
                                ),
                              );
                            }).toList(),
                          ),
                        ),
                      );
                      final legend = Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        mainAxisSize: MainAxisSize.min,
                        children: postures.map((item) {
                          final code = item['posture']?.toString() ?? '';
                          final display =
                              item['display']?.toString() ??
                              ApiService.toDisplayName(code);
                          final minutes =
                              (item['minutes'] as num?)?.toInt() ?? 0;
                          final ratio =
                              (item['ratio'] as num?)?.toDouble() ?? 0;
                          final color = ApiService.postureColor(code);
                          return Padding(
                            padding: const EdgeInsets.only(bottom: 8),
                            child: Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Container(
                                  width: 10,
                                  height: 10,
                                  decoration: BoxDecoration(
                                    color: color,
                                    shape: BoxShape.circle,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                Text(
                                  '$display  $minutes 分  ${(ratio * 100).round()}%',
                                  style: const TextStyle(
                                    color: Color(0xFF334155),
                                    fontWeight: FontWeight.w700,
                                  ),
                                ),
                              ],
                            ),
                          );
                        }).toList(),
                      );
                      if (compact) {
                        return Column(
                          children: [chart, const SizedBox(height: 12), legend],
                        );
                      }
                      return Row(
                        children: [
                          chart,
                          const SizedBox(width: 24),
                          Expanded(child: legend),
                        ],
                      );
                    },
                  ),
          ),
        ],
      ),
    );
  }
}

class _ReportMetric extends StatelessWidget {
  const _ReportMetric({
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
      width: 180,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.08),
        borderRadius: BorderRadius.circular(14),
      ),
      child: Row(
        children: [
          Icon(icon, color: color),
          const SizedBox(width: 10),
          Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                title,
                style: const TextStyle(
                  color: Color(0xFF64748B),
                  fontWeight: FontWeight.w700,
                ),
              ),
              Text(
                value,
                style: const TextStyle(
                  color: Color(0xFF0F172A),
                  fontSize: 18,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ],
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
    this.valueColor,
  });

  final String title;
  final String value;
  final IconData icon;
  final Color accent;
  final Color? valueColor;

  @override
  Widget build(BuildContext context) {
    return Container(
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
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: valueColor ?? const Color(0xFF0F172A),
            ),
          ),
        ],
      ),
    );
  }
}
