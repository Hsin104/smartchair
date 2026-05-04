import 'package:flutter/material.dart';

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
  final TextEditingController heightController = TextEditingController(
    text: "165",
  );
  final TextEditingController weightController = TextEditingController(
    text: "55",
  );

  bool postureAlert = true;
  bool sedentaryAlert = true;
  bool vibrationAlert = true;

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
      margin: const EdgeInsets.only(bottom: 14),
      child: TextField(
        controller: controller,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(
          prefixIcon: Icon(icon),
          labelText: label,
          helperText: helper,
          suffixText: unit,
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none,
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
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFE2E8F0)),
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: const Color(0xFF0F766E)),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(subtitle),
        value: value,
        onChanged: onChanged,
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
          const Text(
            '使用者資料',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 12),
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
          const SizedBox(height: 10),
          const Text(
            '提醒設定',
            style: TextStyle(
              fontSize: 20,
              fontWeight: FontWeight.w800,
              color: Color(0xFF0F172A),
            ),
          ),
          const SizedBox(height: 12),
          buildSwitchTile(
            title: '姿勢提醒',
            subtitle: '偵測到不良坐姿時即時通知',
            value: postureAlert,
            icon: Icons.warning_amber_rounded,
            onChanged: (value) {
              setState(() {
                postureAlert = value;
              });
            },
          ),
          buildSwitchTile(
            title: '久坐提醒',
            subtitle: '坐太久時提醒你起身活動',
            value: sedentaryAlert,
            icon: Icons.access_time_rounded,
            onChanged: (value) {
              setState(() {
                sedentaryAlert = value;
              });
            },
          ),
          buildSwitchTile(
            title: '震動回饋',
            subtitle: '透過椅子震動提供快速提醒',
            value: vibrationAlert,
            icon: Icons.vibration_rounded,
            onChanged: (value) {
              setState(() {
                vibrationAlert = value;
              });
            },
          ),
          const SizedBox(height: 24),
          SizedBox(
            width: double.infinity,
            child: FilledButton(
              onPressed: () {
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(const SnackBar(content: Text('校正已開始')));
              },
              style: FilledButton.styleFrom(
                padding: const EdgeInsets.symmetric(vertical: 16),
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(16),
                ),
              ),
              child: const Text(
                '開始初始校正',
                style: TextStyle(fontSize: 16, color: Colors.white),
              ),
            ),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton(
              onPressed: () {
                ScaffoldMessenger.of(
                  context,
                ).showSnackBar(const SnackBar(content: Text('設定已儲存')));
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
