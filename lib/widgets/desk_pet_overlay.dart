import 'package:flutter/material.dart';
import '../state/chair_sync_controller.dart';

class DeskPetOverlay extends StatefulWidget {
  const DeskPetOverlay({super.key, required this.controller});

  final ChairSyncController controller;

  @override
  State<DeskPetOverlay> createState() => _DeskPetOverlayState();
}

class _DeskPetOverlayState extends State<DeskPetOverlay>
    with TickerProviderStateMixin {
  late final AnimationController _breathController;
  late final AnimationController _blinkController;
  late final AnimationController _remindShakeController;

  @override
  void initState() {
    super.initState();
    _breathController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1800),
    )..repeat(reverse: true);

    _blinkController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 2800),
    )..repeat();

    _remindShakeController = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 420),
    );

    widget.controller.addListener(_onSyncChanged);
    _onSyncChanged();
  }

  @override
  void didUpdateWidget(covariant DeskPetOverlay oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.controller != widget.controller) {
      oldWidget.controller.removeListener(_onSyncChanged);
      widget.controller.addListener(_onSyncChanged);
      _onSyncChanged();
    }
  }

  void _onSyncChanged() {
    if (widget.controller.isGoodPosture) {
      _remindShakeController.stop();
      _remindShakeController.value = 0;
    } else if (!_remindShakeController.isAnimating) {
      _remindShakeController.repeat(reverse: true);
    }
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onSyncChanged);
    _breathController.dispose();
    _blinkController.dispose();
    _remindShakeController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: Listenable.merge([
        widget.controller,
        _breathController,
        _blinkController,
        _remindShakeController,
      ]),
      builder: (context, child) {
        final posture = _PostureVisual.fromLabel(widget.controller.postureLabel);
        final Color accent = widget.controller.isGoodPosture
            ? const Color(0xFF16A34A)
            : const Color(0xFFDC2626);
        final double breathOffset = (_breathController.value - 0.5) * 2.8;

        final double blink = _blinkController.value;
        final bool isBlinking = blink > 0.44 && blink < 0.50;
        final double eyeOpenFactor = isBlinking ? 0.22 : 1.0;

        final double shakeOffset = widget.controller.isGoodPosture
          ? 0
          : (_remindShakeController.value - 0.5) * 3.2 * posture.reminderIntensity;

        return Container(
          width: 270,
          padding: const EdgeInsets.fromLTRB(12, 12, 12, 10),
          decoration: BoxDecoration(
            color: const Color(0xFFFEFFFD),
            borderRadius: BorderRadius.circular(20),
            border: Border.all(color: accent.withValues(alpha: 0.30)),
            boxShadow: [
              BoxShadow(
                color: Colors.black.withValues(alpha: 0.12),
                blurRadius: 18,
                offset: const Offset(0, 8),
              ),
            ],
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.fromLTRB(10, 10, 10, 8),
                decoration: BoxDecoration(
                  borderRadius: BorderRadius.circular(16),
                  gradient: LinearGradient(
                    begin: Alignment.topLeft,
                    end: Alignment.bottomRight,
                    colors: [
                      accent.withValues(alpha: 0.17),
                      accent.withValues(alpha: 0.08),
                    ],
                  ),
                ),
                child: Row(
                  children: [
                    Expanded(
                      child: _PetScene(
                        isGoodPosture: widget.controller.isGoodPosture,
                        leanAngle: posture.leanAngle,
                        leanShift: posture.leanShift + shakeOffset,
                        forwardOffset: posture.forwardOffset,
                        chairBackTilt: posture.chairBackTilt,
                        showDeskHint: posture.showDeskHint,
                        gazeX: posture.gazeX,
                        gazeY: posture.gazeY,
                        shoulderLift: posture.shoulderLift,
                        neckReach: posture.neckReach,
                        reminderIntensity: posture.reminderIntensity,
                        breathOffset: breathOffset,
                        eyeOpenFactor: eyeOpenFactor,
                        showReminderMotion: !widget.controller.isGoodPosture,
                      ),
                    ),
                    const SizedBox(width: 8),
                    RotatedBox(
                      quarterTurns: 3,
                      child: Text(
                        widget.controller.isGoodPosture ? 'GOOD POSTURE' : 'FIX POSTURE',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.w800,
                          color: accent,
                          letterSpacing: 0.8,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '坐姿：${widget.controller.postureLabel} (${widget.controller.postureScore} 分)',
                style: const TextStyle(
                  fontSize: 12.5,
                  fontWeight: FontWeight.w700,
                  color: Color(0xFF1E293B),
                ),
              ),
              const SizedBox(height: 8),
              Text(
                widget.controller.isGoodPosture
                    ? '狀態良好，繼續保持'
                    : '偵測到不良姿勢，請微調坐姿',
                style: TextStyle(
                  fontSize: 11.5,
                  color: accent,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        );
      },
    );
  }
}

class _PetScene extends StatelessWidget {
  const _PetScene({
    required this.isGoodPosture,
    required this.leanAngle,
    required this.leanShift,
    required this.forwardOffset,
    required this.chairBackTilt,
    required this.showDeskHint,
    required this.gazeX,
    required this.gazeY,
    required this.shoulderLift,
    required this.neckReach,
    required this.reminderIntensity,
    required this.breathOffset,
    required this.eyeOpenFactor,
    required this.showReminderMotion,
  });

  final bool isGoodPosture;
  final double leanAngle;
  final double leanShift;
  final double forwardOffset;
  final double chairBackTilt;
  final bool showDeskHint;
  final double gazeX;
  final double gazeY;
  final double shoulderLift;
  final double neckReach;
  final double reminderIntensity;
  final double breathOffset;
  final double eyeOpenFactor;
  final bool showReminderMotion;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: 88,
      child: Stack(
        clipBehavior: Clip.none,
        children: [
          Positioned(
            left: 0,
            right: 0,
            bottom: 0,
            child: Container(
              height: 10,
              decoration: BoxDecoration(
                color: const Color(0xFFCBD5E1),
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
          Positioned(
            left: 66,
            bottom: 10,
            child: _ChairShape(backrestTilt: chairBackTilt),
          ),
          Positioned(
            left: 72 + (leanShift * 0.55),
            bottom: 9,
            child: _ChibiHuman(
              isGoodPosture: isGoodPosture,
              bodyTilt: leanAngle,
              forwardOffset: forwardOffset,
              breathOffset: breathOffset,
              eyeOpenFactor: eyeOpenFactor,
              showReminderMotion: showReminderMotion,
              reminderIntensity: reminderIntensity,
              gazeX: gazeX,
              gazeY: gazeY,
              shoulderLift: shoulderLift,
              neckReach: neckReach,
            ),
          ),
          Positioned(
            left: 77,
            bottom: 33,
            child: Container(
              width: 52,
              height: 5,
              decoration: BoxDecoration(
                color: const Color(0xFF1D4ED8).withValues(alpha: 0.45),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ChairShape extends StatelessWidget {
  const _ChairShape({required this.backrestTilt});

  final double backrestTilt;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: 84,
      height: 88,
      child: Stack(
        children: [
          Positioned(
            left: 30,
            top: 0,
            child: Container(
              width: 24,
              height: 10,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Color(0xFFBFDBFE), Color(0xFF60A5FA)],
                ),
                borderRadius: BorderRadius.circular(8),
              ),
            ),
          ),
          Positioned(
            left: 20,
            top: 8,
            child: Transform.rotate(
              angle: backrestTilt,
              alignment: Alignment.bottomCenter,
              child: SizedBox(
                width: 52,
                height: 42,
                child: Stack(
                  children: [
                    Container(
                      width: 52,
                      height: 42,
                      decoration: BoxDecoration(
                        gradient: const LinearGradient(
                          begin: Alignment.topCenter,
                          end: Alignment.bottomCenter,
                          colors: [Color(0xFF93C5FD), Color(0xFF2563EB)],
                        ),
                        borderRadius: BorderRadius.circular(12),
                      ),
                    ),
                    Positioned(
                      left: 9,
                      right: 9,
                      top: 11,
                      child: Container(
                        height: 12,
                        decoration: BoxDecoration(
                          color: Colors.white.withValues(alpha: 0.20),
                          borderRadius: BorderRadius.circular(10),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
          ),
          Positioned(
            left: 22,
            top: 26,
            child: Container(
              width: 30,
              height: 10,
              decoration: BoxDecoration(
                color: const Color(0xFF60A5FA),
                borderRadius: BorderRadius.circular(999),
              ),
            ),
          ),
          Positioned(
            left: 11,
            top: 38,
            child: Container(
              width: 52,
              height: 17,
              decoration: BoxDecoration(
                gradient: const LinearGradient(
                  begin: Alignment.topCenter,
                  end: Alignment.bottomCenter,
                  colors: [Color(0xFF93C5FD), Color(0xFF3B82F6)],
                ),
                borderRadius: BorderRadius.circular(10),
              ),
            ),
          ),
          Positioned(
            left: 6,
            top: 39,
            child: Container(
              width: 8,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF1D4ED8),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            right: 11,
            top: 39,
            child: Container(
              width: 8,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF1D4ED8),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            left: 37,
            top: 54,
            child: Container(
              width: 10,
              height: 16,
              decoration: BoxDecoration(
                color: const Color(0xFF1E3A8A),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            left: 26,
            top: 68,
            child: Container(
              width: 32,
              height: 6,
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            left: 2,
            top: 74,
            child: Container(
              width: 6,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            left: 24,
            top: 74,
            child: Container(
              width: 6,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            left: 47,
            top: 74,
            child: Container(
              width: 6,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
          Positioned(
            right: 2,
            top: 74,
            child: Container(
              width: 6,
              height: 14,
              decoration: BoxDecoration(
                color: const Color(0xFF334155),
                borderRadius: BorderRadius.circular(99),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

class _ChibiHuman extends StatelessWidget {
  const _ChibiHuman({
    required this.isGoodPosture,
    required this.bodyTilt,
    required this.forwardOffset,
    required this.breathOffset,
    required this.eyeOpenFactor,
    required this.showReminderMotion,
    required this.reminderIntensity,
    required this.gazeX,
    required this.gazeY,
    required this.shoulderLift,
    required this.neckReach,
  });

  final bool isGoodPosture;
  final double bodyTilt;
  final double forwardOffset;
  final double breathOffset;
  final double eyeOpenFactor;
  final bool showReminderMotion;
  final double reminderIntensity;
  final double gazeX;
  final double gazeY;
  final double shoulderLift;
  final double neckReach;

  @override
  Widget build(BuildContext context) {
    final Color shirt = isGoodPosture
        ? const Color(0xFF16A34A)
        : const Color(0xFFEF4444);

    final armNudge = showReminderMotion ? 1.5 * reminderIntensity : 0.0;

    return Transform.translate(
      offset: Offset(0, breathOffset + forwardOffset),
      child: Transform.rotate(
        angle: bodyTilt,
        alignment: Alignment.bottomCenter,
        child: SizedBox(
          width: 60,
          height: 80,
          child: Stack(
            clipBehavior: Clip.none,
            children: [
              Positioned(
                left: 15,
                top: 1,
                child: Container(
                  width: 30,
                  height: 30,
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFD9B3),
                    shape: BoxShape.circle,
                    border: Border.all(
                      color: const Color(0xFFF0B78A),
                      width: 1.2,
                    ),
                  ),
                  child: Stack(
                    children: [
                      Positioned(
                        left: 8 + gazeX,
                        top: 12.5 + gazeY,
                        child: Container(
                          width: 3.8,
                          height: 3.8 * eyeOpenFactor,
                          decoration: BoxDecoration(
                            color: const Color(0xFF111827),
                            borderRadius: BorderRadius.circular(99),
                          ),
                        ),
                      ),
                      Positioned(
                        right: 8 - gazeX,
                        top: 12.5 + gazeY,
                        child: Container(
                          width: 3.8,
                          height: 3.8 * eyeOpenFactor,
                          decoration: BoxDecoration(
                            color: const Color(0xFF111827),
                            borderRadius: BorderRadius.circular(99),
                          ),
                        ),
                      ),
                      Positioned(
                        left: 13,
                        bottom: 6,
                        child: Container(
                          width: 6,
                          height: 2.2,
                          decoration: BoxDecoration(
                            color: const Color(0xFF7C2D12),
                            borderRadius: BorderRadius.circular(99),
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Positioned(
                left: 24 + neckReach,
                top: 27 - shoulderLift,
                child: Container(
                  width: 8 + neckReach,
                  height: 6,
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFD9B3),
                    borderRadius: BorderRadius.circular(3),
                  ),
                ),
              ),
              Positioned(
                left: 13,
                top: 30 - shoulderLift,
                child: Container(
                  width: 34,
                  height: 24,
                  decoration: BoxDecoration(
                    gradient: LinearGradient(
                      begin: Alignment.topCenter,
                      end: Alignment.bottomCenter,
                      colors: [
                        shirt.withValues(alpha: 0.95),
                        shirt,
                      ],
                    ),
                    borderRadius: BorderRadius.circular(10),
                  ),
                ),
              ),
              Positioned(
                left: 7 - armNudge,
                top: 34 - (shoulderLift * 0.4),
                child: Container(
                  width: 7,
                  height: 16,
                  decoration: BoxDecoration(
                    color: const Color(0xFFF4C7A1),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              Positioned(
                right: 7 + armNudge,
                top: 34 - (shoulderLift * 0.4),
                child: Container(
                  width: 7,
                  height: 16,
                  decoration: BoxDecoration(
                    color: const Color(0xFFF4C7A1),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              Positioned(
                left: 18,
                top: 52,
                child: Container(
                  width: 9,
                  height: 17,
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              Positioned(
                left: 31,
                top: 52,
                child: Container(
                  width: 9,
                  height: 17,
                  decoration: BoxDecoration(
                    color: const Color(0xFF1E293B),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
              Positioned(
                left: 16,
                bottom: 0,
                child: Container(
                  width: 12,
                  height: 3,
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(99),
                  ),
                ),
              ),
              Positioned(
                left: 30,
                bottom: 0,
                child: Container(
                  width: 12,
                  height: 3,
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(99),
                  ),
                ),
              ),
              Positioned(
                left: 12,
                top: -3,
                child: Container(
                  width: 36,
                  height: 14,
                  decoration: BoxDecoration(
                    color: const Color(0xFF0F172A),
                    borderRadius: BorderRadius.circular(999),
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _PostureVisual {
  const _PostureVisual({
    required this.leanAngle,
    required this.leanShift,
    required this.forwardOffset,
    required this.chairBackTilt,
    required this.showDeskHint,
    required this.gazeX,
    required this.gazeY,
    required this.shoulderLift,
    required this.neckReach,
    required this.reminderIntensity,
  });

  final double leanAngle;
  final double leanShift;
  final double forwardOffset;
  final double chairBackTilt;
  final bool showDeskHint;
  final double gazeX;
  final double gazeY;
  final double shoulderLift;
  final double neckReach;
  final double reminderIntensity;

  factory _PostureVisual.fromLabel(String label) {
    if (label.contains('左')) {
      return const _PostureVisual(
        leanAngle: -0.17,
        leanShift: -5,
        forwardOffset: 0,
        chairBackTilt: -0.05,
        showDeskHint: false,
        gazeX: -1.0,
        gazeY: 0,
        shoulderLift: 0,
        neckReach: 0,
        reminderIntensity: 1.0,
      );
    }
    if (label.contains('右')) {
      return const _PostureVisual(
        leanAngle: 0.17,
        leanShift: 5,
        forwardOffset: 0,
        chairBackTilt: 0.05,
        showDeskHint: false,
        gazeX: 1.0,
        gazeY: 0,
        shoulderLift: 0,
        neckReach: 0,
        reminderIntensity: 1.0,
      );
    }
    if (label.contains('前')) {
      return const _PostureVisual(
        leanAngle: -0.10,
        leanShift: -2,
        forwardOffset: 4,
        chairBackTilt: -0.02,
        showDeskHint: true,
        gazeX: 0,
        gazeY: 1.0,
        shoulderLift: 2.5,
        neckReach: 3.0,
        reminderIntensity: 1.1,
      );
    }
    if (label.contains('後')) {
      return const _PostureVisual(
        leanAngle: 0.10,
        leanShift: 2,
        forwardOffset: -2,
        chairBackTilt: 0.09,
        showDeskHint: false,
        gazeX: 0,
        gazeY: -0.6,
        shoulderLift: -0.8,
        neckReach: 0,
        reminderIntensity: 0.45,
      );
    }
    return const _PostureVisual(
      leanAngle: 0,
      leanShift: 0,
      forwardOffset: 0,
      chairBackTilt: 0,
      showDeskHint: false,
      gazeX: 0,
      gazeY: 0,
      shoulderLift: 0,
      neckReach: 0,
      reminderIntensity: 0,
    );
  }
}
