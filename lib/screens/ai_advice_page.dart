import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';
import '../services/api_service.dart';
import '../state/chair_sync_controller.dart';
import '../state/wellness_controller.dart';

class AiAdvicePage extends StatefulWidget {
  const AiAdvicePage({
    super.key,
    required this.controller,
    required this.isLoggedIn,
    required this.wellnessController,
  });

  final ChairSyncController controller;
  final bool isLoggedIn;
  final WellnessController wellnessController;

  @override
  State<AiAdvicePage> createState() => _AiAdvicePageState();
}

class _AiAdvicePageState extends State<AiAdvicePage> {
  final TextEditingController _userMessageController = TextEditingController();
  bool _adviceVisible = false;
  bool _isFetchingAdvice = false;
  String _advice = '請先取得 AI 建議，系統將根據你的姿勢與症狀提供治療建議。';
  List<Map<String, dynamic>> _recommendedExercises = const [];

  late final VoidCallback _controllerListener;

  @override
  void initState() {
    super.initState();
    _controllerListener = () {
      if (mounted) setState(() {});
    };
    widget.controller.addListener(_controllerListener);
    _syncFromController();
  }

  @override
  void didUpdateWidget(covariant AiAdvicePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_controllerListener);
      widget.controller.addListener(_controllerListener);
      _syncFromController();
    }
  }

  @override
  void dispose() {
    _userMessageController.dispose();
    widget.controller.removeListener(_controllerListener);
    super.dispose();
  }

  void _syncFromController() {
    final postureCode = widget.controller.postureCode;
    if (postureCode.isEmpty && !_adviceVisible) {
      _advice = '目前尚未取得姿勢資料，請先完成同步後再取得 AI 建議。';
    }
  }

  Future<void> _requestAgentAdvice() async {
    if (_isFetchingAdvice) return;

    if (!widget.isLoggedIn) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('請先登入以取得個人化建議。')));
      return;
    }

    if (widget.controller.postureCode.isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('目前尚未取得姿勢資料，請稍後再試。')));
      return;
    }

    final messenger = ScaffoldMessenger.of(context);
    final safeMessage = _userMessageController.text.trim();

    setState(() {
      _isFetchingAdvice = true;
      _adviceVisible = true;
      _advice = 'AI 建議生成中，請稍候...';
      _recommendedExercises = const [];
    });

    try {
      final result = await ApiService.getAdvice(
        widget.controller.postureCode,
        userMessage: safeMessage,
      );

      if (!mounted) return;

      if (result.success) {
        setState(() {
          _advice = result.advice.isNotEmpty ? result.advice : '目前沒有可用建議。';
          _adviceVisible = true;
          _recommendedExercises = result.recommendedExercises;
        });
        widget.wellnessController.setAiAdviceTasks(result.recommendedExercises);
        await widget.wellnessController.refreshDailyTasks();
      } else {
        messenger.showSnackBar(SnackBar(content: Text(result.message)));
        setState(() {
          _adviceVisible = false;
          _advice = '按下「取得 AI 建議」以查看 AI 建議。';
          _recommendedExercises = const [];
        });
        widget.wellnessController.setAiAdviceTasks(const []);
      }
    } catch (_) {
      if (!mounted) return;
      messenger.showSnackBar(const SnackBar(content: Text('取得 AI 建議時發生錯誤。')));
      setState(() {
        _adviceVisible = false;
        _advice = '按下「取得 AI 建議」以查看 AI 建議。';
        _recommendedExercises = const [];
      });
      widget.wellnessController.setAiAdviceTasks(const []);
    } finally {
      if (mounted) {
        setState(() => _isFetchingAdvice = false);
      }
    }
  }

  Widget _buildAdviceText(String text) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: text.split('\n').map(_buildAdviceLine).toList(),
    );
  }

  Widget _buildAdviceLine(String rawLine) {
    final line = rawLine.trimRight();
    if (line.trim().isEmpty) return const SizedBox(height: 8);
    if (line.trim() == '---') {
      return const Padding(
        padding: EdgeInsets.symmetric(vertical: 8),
        child: Divider(height: 1, color: Color(0xFFCBD5E1)),
      );
    }

    final heading = RegExp(r'^#{1,6}\s+(.+)$').firstMatch(line.trim());
    if (heading != null) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 8),
        child: _buildInlineAdviceText(
          heading.group(1)!,
          const TextStyle(
            fontSize: 17,
            height: 1.45,
            fontWeight: FontWeight.w900,
            color: Color(0xFF1E3A5F),
          ),
        ),
      );
    }

    final bullet = RegExp(r'^[-*]\s+(.+)$').firstMatch(line.trim());
    if (bullet != null) {
      return Padding(
        padding: const EdgeInsets.only(bottom: 5),
        child: Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '• ',
              style: TextStyle(fontSize: 15, color: Color(0xFF0F766E)),
            ),
            Expanded(child: _buildInlineAdviceText(bullet.group(1)!)),
          ],
        ),
      );
    }

    return Padding(
      padding: const EdgeInsets.only(bottom: 5),
      child: _buildInlineAdviceText(line),
    );
  }

  Widget _buildInlineAdviceText(String text, [TextStyle? style]) {
    final baseStyle =
        style ??
        const TextStyle(fontSize: 14, height: 1.6, color: Color(0xFF334155));
    final boldStyle = baseStyle.copyWith(fontWeight: FontWeight.w900);
    final spans = <InlineSpan>[];
    final pattern = RegExp(r'\*\*(.+?)(?:\*\*|$)');
    var currentIndex = 0;

    for (final match in pattern.allMatches(text)) {
      if (match.start > currentIndex) {
        spans.add(TextSpan(text: text.substring(currentIndex, match.start)));
      }
      spans.add(TextSpan(text: match.group(1) ?? '', style: boldStyle));
      currentIndex = match.end;
    }

    if (currentIndex < text.length) {
      spans.add(TextSpan(text: text.substring(currentIndex)));
    }

    return Text.rich(TextSpan(style: baseStyle, children: spans));
  }

  Future<void> _openExercise(Map<String, dynamic> exercise) async {
    final rawUrl = exercise['youtube_url']?.toString().trim() ?? '';
    final uri = Uri.tryParse(rawUrl);
    if (uri == null || !uri.hasScheme || !uri.hasAuthority) {
      if (mounted) {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(const SnackBar(content: Text('影片連結目前無法開啟。')));
      }
      return;
    }
    final opened = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!opened && mounted) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('無法開啟 YouTube 影片。')));
    }
  }

  Widget _buildExerciseCards() {
    if (_recommendedExercises.isEmpty) return const SizedBox.shrink();
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Text(
          '推薦伸展影片',
          style: TextStyle(
            fontSize: 18,
            fontWeight: FontWeight.w900,
            color: Color(0xFF0F172A),
          ),
        ),
        const SizedBox(height: 10),
        ..._recommendedExercises.map(_buildExerciseCard),
      ],
    );
  }

  Widget _buildExerciseCard(Map<String, dynamic> exercise) {
    final name = exercise['name']?.toString() ?? '推薦伸展';
    final target = exercise['target_muscles']?.toString() ?? '';
    final reps = exercise['reps']?.toString() ?? '';
    final description = exercise['description']?.toString() ?? '';
    final duration = exercise['duration_sec']?.toString() ?? '';
    final title = exercise['youtube_title']?.toString().trim() ?? '';
    return Container(
      margin: const EdgeInsets.only(bottom: 10),
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFBAE6FD)),
        boxShadow: [
          BoxShadow(
            color: Colors.black.withValues(alpha: 0.04),
            blurRadius: 12,
            offset: const Offset(0, 5),
          ),
        ],
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Icon(
                Icons.play_circle_fill_rounded,
                color: Color(0xFFDC2626),
                size: 30,
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Text(
                  name,
                  style: const TextStyle(
                    fontSize: 17,
                    fontWeight: FontWeight.w900,
                  ),
                ),
              ),
              if (duration.isNotEmpty)
                Text(
                  '$duration秒',
                  style: const TextStyle(
                    color: Color(0xFF64748B),
                    fontWeight: FontWeight.w700,
                  ),
                ),
            ],
          ),
          if (target.isNotEmpty) ...[
            const SizedBox(height: 6),
            Text(
              '目標肌群：$target',
              style: const TextStyle(color: Color(0xFF475569), fontSize: 13),
            ),
          ],
          if (reps.isNotEmpty) ...[
            const SizedBox(height: 4),
            Text(
              '建議：$reps',
              style: const TextStyle(color: Color(0xFF475569), fontSize: 13),
            ),
          ],
          if (description.isNotEmpty) ...[
            const SizedBox(height: 8),
            Text(
              description,
              style: const TextStyle(color: Color(0xFF334155), height: 1.4),
            ),
          ],
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: () => _openExercise(exercise),
              icon: const Icon(Icons.open_in_new_rounded, size: 18),
              label: Text(
                title.isEmpty ? '在 YouTube 開啟影片' : title,
                overflow: TextOverflow.ellipsis,
              ),
            ),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final postureCode = widget.controller.postureCode;
    final postureLabel = widget.controller.postureLabel.isNotEmpty
        ? widget.controller.postureLabel
        : '尚未同步';
    final risk = postureCode.isNotEmpty
        ? ApiService.toRisk(postureCode)
        : '尚無資料';
    final color = postureCode.isNotEmpty
        ? ApiService.postureColor(postureCode)
        : const Color(0xFF64748B);

    return Scaffold(
      backgroundColor: const Color(0xFFF2F7FA),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(16, 12, 16, 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(18),
                decoration: BoxDecoration(
                  color: Colors.white,
                  borderRadius: BorderRadius.circular(22),
                  border: Border.all(color: const Color(0xFFE2E8F0)),
                  boxShadow: [
                    BoxShadow(
                      color: Colors.black.withValues(alpha: 0.04),
                      blurRadius: 18,
                      offset: const Offset(0, 8),
                    ),
                  ],
                ),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Container(
                          width: 46,
                          height: 46,
                          decoration: BoxDecoration(
                            color: Colors.blue.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(15),
                          ),
                          child: const Icon(
                            Icons.psychology_alt_rounded,
                            color: Colors.blue,
                            size: 26,
                          ),
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Text(
                            'AI 物理治療師建議',
                            style: TextStyle(
                              fontSize: 24,
                              fontWeight: FontWeight.w900,
                              color: Color(0xFF0F172A),
                            ),
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            color: color.withValues(alpha: 0.12),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            risk,
                            style: TextStyle(
                              color: color,
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Text(
                      '目前姿勢：$postureLabel',
                      style: const TextStyle(
                        fontSize: 15,
                        fontWeight: FontWeight.w700,
                        color: Color(0xFF475569),
                      ),
                    ),
                    const SizedBox(height: 12),
                    Wrap(
                      spacing: 8,
                      runSpacing: 8,
                      children: const [
                        _CoachChip(
                          label: '肩膀放鬆',
                          icon: Icons.self_improvement_rounded,
                        ),
                        _CoachChip(
                          label: '骨盆中立',
                          icon: Icons.straighten_rounded,
                        ),
                        _CoachChip(
                          label: '每 45 分鐘起身',
                          icon: Icons.access_time_rounded,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 16),
              Container(
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
                    const Text(
                      '本日診斷摘要',
                      style: TextStyle(
                        fontSize: 17,
                        fontWeight: FontWeight.w800,
                        color: Color(0xFF0F172A),
                      ),
                    ),
                    const SizedBox(height: 12),
                    _adviceVisible
                        ? Container(
                            width: double.infinity,
                            padding: const EdgeInsets.all(14),
                            decoration: BoxDecoration(
                              color: const Color(0xFFF8FAFC),
                              borderRadius: BorderRadius.circular(16),
                              border: Border.all(
                                color: const Color(0xFFE2E8F0),
                              ),
                            ),
                            child: _buildAdviceText(_advice),
                          )
                        : Padding(
                            padding: const EdgeInsets.symmetric(vertical: 4),
                            child: Text(
                              _advice,
                              style: const TextStyle(
                                fontSize: 14,
                                height: 1.6,
                                color: Color(0xFF334155),
                              ),
                            ),
                          ),
                    const SizedBox(height: 16),
                    _buildExerciseCards(),
                    const SizedBox(height: 16),
                    TextField(
                      controller: _userMessageController,
                      maxLength: 500,
                      maxLines: 3,
                      textInputAction: TextInputAction.newline,
                      decoration: InputDecoration(
                        labelText: '附加症狀描述（選填）',
                        hintText: '例如：我肩膀很痠、背部緊繃',
                        filled: true,
                        fillColor: const Color(0xFFF8FAFC),
                        border: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(
                            color: Color(0xFFE2E8F0),
                          ),
                        ),
                        enabledBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(
                            color: Color(0xFFE2E8F0),
                          ),
                        ),
                        focusedBorder: OutlineInputBorder(
                          borderRadius: BorderRadius.circular(14),
                          borderSide: const BorderSide(
                            color: Color(0xFF0F766E),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(height: 12),
                    SizedBox(
                      width: double.infinity,
                      child: FilledButton.icon(
                        onPressed: _isFetchingAdvice
                            ? null
                            : _requestAgentAdvice,
                        icon: _isFetchingAdvice
                            ? const SizedBox(
                                width: 18,
                                height: 18,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                ),
                              )
                            : const Icon(Icons.psychology_alt_rounded),
                        label: Text(
                          _isFetchingAdvice ? '建議生成中...' : '取得 AI 建議',
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _CoachChip extends StatelessWidget {
  const _CoachChip({required this.label, required this.icon});

  final String label;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 7),
      decoration: BoxDecoration(
        color: const Color(0xFFE2E8F0),
        borderRadius: BorderRadius.circular(999),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(icon, size: 14, color: const Color(0xFF0F172A)),
          const SizedBox(width: 6),
          Text(
            label,
            style: const TextStyle(
              fontSize: 12,
              fontWeight: FontWeight.w700,
              color: Color(0xFF0F172A),
            ),
          ),
        ],
      ),
    );
  }
}
