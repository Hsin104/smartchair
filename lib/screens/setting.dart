import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';

class SettingPage extends StatefulWidget {
  const SettingPage({
    super.key,
    this.isLoggedIn = false,
    this.userEmail,
    this.onLogout,
  });

  final bool isLoggedIn;
  final String? userEmail;
  final Future<void> Function()? onLogout;

  @override
  State<SettingPage> createState() => _SettingPageState();
}

class _SettingPageState extends State<SettingPage> {
  final TextEditingController heightController = TextEditingController();
  final TextEditingController weightController = TextEditingController();

  bool postureAlert = true;
  bool sedentaryAlert = true;
  bool vibrationAlert = true;

  String get _userScope {
    final email = widget.userEmail?.trim().toLowerCase();
    if (widget.isLoggedIn && email != null && email.isNotEmpty) {
      return email;
    }
    return 'guest';
  }

  String _key(String field) => 'settings_${_userScope}_$field';

  @override
  void initState() {
    super.initState();
    _loadSettings();
  }

  @override
  void didUpdateWidget(covariant SettingPage oldWidget) {
    super.didUpdateWidget(oldWidget);
    final oldScope =
        (oldWidget.isLoggedIn &&
            (oldWidget.userEmail?.trim().isNotEmpty ?? false))
        ? oldWidget.userEmail!.trim().toLowerCase()
        : 'guest';
    if (oldScope != _userScope) {
      _loadSettings();
    }
  }

  Future<void> _loadSettings() async {
    final prefs = await SharedPreferences.getInstance();
    debugPrint('[Setting] Loading settings for scope=$_userScope');
    final savedPostureAlert = prefs.getBool(_key('postureAlert'));
    final savedSedentaryAlert = prefs.getBool(_key('sedentaryAlert'));
    final savedVibrationAlert = prefs.getBool(_key('vibrationAlert'));

    String? heightText;
    String? weightText;

    if (widget.isLoggedIn) {
      final profile = await ApiService.getMe();
      if (profile != null) {
        final height = profile['height']?.toString();
        final weight = profile['weight']?.toString();
        if (height != null && height != 'null' && height.isNotEmpty) {
          heightText = height;
        }
        if (weight != null && weight != 'null' && weight.isNotEmpty) {
          weightText = weight;
        }
        debugPrint(
          '[Setting] Loaded backend profile: height=$heightText, weight=$weightText',
        );
      }
    }

    heightText ??= prefs.getString(_key('height'));
    weightText ??= prefs.getString(_key('weight'));

    if (!mounted) return;
    setState(() {
      heightController.text = heightText ?? '';
      weightController.text = weightText ?? '';
      postureAlert = savedPostureAlert ?? true;
      sedentaryAlert = savedSedentaryAlert ?? true;
      vibrationAlert = savedVibrationAlert ?? true;
    });
  }

  Future<bool> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final heightStr = heightController.text.trim();
    final weightStr = weightController.text.trim();

    await prefs.setString(_key('height'), heightStr);
    await prefs.setString(_key('weight'), weightStr);
    await prefs.setBool(_key('postureAlert'), postureAlert);
    await prefs.setBool(_key('sedentaryAlert'), sedentaryAlert);
    await prefs.setBool(_key('vibrationAlert'), vibrationAlert);
    debugPrint(
      '[Setting] Saved locally for scope=$_userScope: height=$heightStr, weight=$weightStr, postureAlert=$postureAlert, sedentaryAlert=$sedentaryAlert, vibrationAlert=$vibrationAlert',
    );

    if (widget.isLoggedIn) {
      try {
        final height = double.tryParse(heightStr);
        final weight = double.tryParse(weightStr);
        final updates = <String, dynamic>{};
        if (height != null) updates['height'] = height;
        if (weight != null) updates['weight'] = weight;

        if (updates.isNotEmpty) {
          final ok = await ApiService.updateMe(updates);
          debugPrint('[Setting] updateMe ok=$ok, updates=$updates');
          return ok;
        }
      } catch (e) {
        debugPrint('[Setting] updateMe error: $e');
        return false;
      }
    }

    return true;
  }

  @override
  void dispose() {
    heightController.dispose();
    weightController.dispose();
    super.dispose();
  }

  Widget buildTextField({
    required String label,
    required String unit,
    required TextEditingController controller,
    required IconData icon,
    String? helper,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        keyboardType: TextInputType.number,
        style: const TextStyle(
          fontSize: 18,
          fontWeight: FontWeight.w700,
          color: Color(0xFF0F172A),
        ),
        decoration: InputDecoration(
          prefixIcon: Icon(icon, color: const Color(0xFF0F766E), size: 24),
          labelText: label,
          helperText: helper,
          helperMaxLines: 2,
          suffixText: unit,
          suffixStyle: const TextStyle(
            fontSize: 16,
            fontWeight: FontWeight.w700,
            color: Color(0xFF475569),
          ),
          filled: true,
          fillColor: const Color(0xFFF8FAFC),
          contentPadding: const EdgeInsets.symmetric(
            horizontal: 18,
            vertical: 18,
          ),
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
          enabledBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0xFFE2E8F0)),
          ),
          focusedBorder: OutlineInputBorder(
            borderRadius: BorderRadius.circular(18),
            borderSide: const BorderSide(color: Color(0xFF0F766E), width: 1.5),
          ),
        ),
      ),
    );
  }

  Widget buildSwitchTile({
    required String title,
    required String subtitle,
    required bool value,
    required Function(bool) onChanged,
    required IconData icon,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 16),
      decoration: BoxDecoration(
        color: const Color(0xFFF8FAFC),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: Row(
        children: [
          Container(
            width: 44,
            height: 44,
            decoration: BoxDecoration(
              color: const Color(0xFF0F766E).withValues(alpha: 0.10),
              borderRadius: BorderRadius.circular(14),
            ),
            child: Icon(icon, color: const Color(0xFF0F766E), size: 24),
          ),
          const SizedBox(width: 14),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 18,
                    fontWeight: FontWeight.w800,
                    color: Color(0xFF0F172A),
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 14,
                    color: Color(0xFF475569),
                    height: 1.25,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 12),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: Colors.white,
            activeTrackColor: const Color(0xFF0F766E),
          ),
        ],
      ),
    );
  }

  Widget _sectionPanel({
    required String title,
    required IconData icon,
    required Color accent,
    required List<Widget> children,
  }) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(20),
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
                width: 42,
                height: 42,
                decoration: BoxDecoration(
                  color: accent.withValues(alpha: 0.12),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(icon, color: accent, size: 24),
              ),
              const SizedBox(width: 12),
              Expanded(
                child: Text(
                  title,
                  style: const TextStyle(
                    fontSize: 21,
                    fontWeight: FontWeight.w900,
                    color: Color(0xFF0F172A),
                  ),
                ),
              ),
            ],
          ),
          const SizedBox(height: 18),
          ...children,
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(16, 4, 16, 16),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: double.infinity,
            margin: const EdgeInsets.only(bottom: 16),
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(16),
            ),
            child: Row(
              children: [
                CircleAvatar(
                  backgroundColor: widget.isLoggedIn
                      ? const Color(0xFF16A34A).withValues(alpha: 0.15)
                      : const Color(0xFF94A3B8).withValues(alpha: 0.18),
                  child: Icon(
                    widget.isLoggedIn
                        ? Icons.verified_user_rounded
                        : Icons.person_rounded,
                    color: widget.isLoggedIn
                        ? const Color(0xFF15803D)
                        : const Color(0xFF64748B),
                  ),
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.isLoggedIn ? '帳號已連線' : '尚未登入',
                        style: const TextStyle(
                          fontSize: 16,
                          color: Color(0xFF0F172A),
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 2),
                      Text(
                        widget.userEmail ?? '登入後可自動同步你的偏好設定',
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: const TextStyle(color: Color(0xFF64748B)),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),

          LayoutBuilder(
            builder: (context, constraints) {
              final profilePanel = _sectionPanel(
                title: '使用者資料',
                icon: Icons.badge_rounded,
                accent: const Color(0xFF0F766E),
                children: [
                  buildTextField(
                    label: '身高',
                    unit: 'cm',
                    controller: heightController,
                    icon: Icons.height_rounded,
                    helper: '建議填寫實際身高，讓姿勢判斷更準確',
                  ),
                  buildTextField(
                    label: '體重',
                    unit: 'kg',
                    controller: weightController,
                    icon: Icons.monitor_weight_rounded,
                  ),
                ],
              );

              final reminderPanel = _sectionPanel(
                title: '提醒設定',
                icon: Icons.notifications_active_rounded,
                accent: const Color(0xFF7C3AED),
                children: [
                  buildSwitchTile(
                    title: '姿勢提醒',
                    subtitle: '偵測到不良坐姿時即時通知',
                    value: postureAlert,
                    icon: Icons.warning_amber_rounded,
                    onChanged: (value) => setState(() => postureAlert = value),
                  ),
                  buildSwitchTile(
                    title: '久坐提醒',
                    subtitle: '坐太久時提醒你起身活動',
                    value: sedentaryAlert,
                    icon: Icons.access_time_rounded,
                    onChanged: (value) =>
                        setState(() => sedentaryAlert = value),
                  ),
                  buildSwitchTile(
                    title: '震動回饋',
                    subtitle: '透過椅子震動提供快速提醒',
                    value: vibrationAlert,
                    icon: Icons.vibration_rounded,
                    onChanged: (value) =>
                        setState(() => vibrationAlert = value),
                  ),
                ],
              );

              if (constraints.maxWidth < 820) {
                return Column(
                  children: [
                    profilePanel,
                    const SizedBox(height: 14),
                    reminderPanel,
                  ],
                );
              }

              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Expanded(child: profilePanel),
                  const SizedBox(width: 18),
                  Expanded(child: reminderPanel),
                ],
              );
            },
          ),

          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () async {
                final syncedOk = await _saveSettings();
                if (!context.mounted) return;
                ScaffoldMessenger.of(context).showSnackBar(
                  SnackBar(
                    content: Text(syncedOk ? '設定已儲存' : '設定已儲存本地，但同步到伺服器失敗'),
                  ),
                );
              },
              style: OutlinedButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              child: const Text('儲存設定', style: TextStyle(fontSize: 16)),
            ),
          ),
          if (widget.isLoggedIn) ...[
            const SizedBox(height: 12),
            SizedBox(
              width: double.infinity,
              child: TextButton.icon(
                onPressed: widget.onLogout,
                icon: const Icon(Icons.logout_rounded, color: Colors.red),
                label: const Text(
                  '登出帳號',
                  style: TextStyle(color: Colors.red, fontSize: 16),
                ),
                style: TextButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 14),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(12),
                  ),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
