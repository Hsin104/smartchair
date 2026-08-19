import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../services/api_service.dart';

class SettingPage extends StatefulWidget {
  const SettingPage({
    super.key,
    this.isLoggedIn = false,
    this.userEmail,
    this.onLogout,
    this.onProfileChanged,
  });

  final bool isLoggedIn;
  final String? userEmail;
  final Future<void> Function()? onLogout;
  final Future<void> Function()? onProfileChanged;

  @override
  State<SettingPage> createState() => _SettingPageState();
}

class _SettingPageState extends State<SettingPage> {
  static const List<IconData> _avatarIcons = [
    Icons.person_rounded,
    Icons.fitness_center_rounded,
    Icons.self_improvement_rounded,
    Icons.sports_esports_rounded,
    Icons.psychology_rounded,
    Icons.waves_rounded,
  ];

  static const List<Color> _avatarColors = [
    Color(0xFF0F766E),
    Color(0xFF2563EB),
    Color(0xFF7C3AED),
    Color(0xFFDB2777),
    Color(0xFFEA580C),
    Color(0xFF0EA5A7),
  ];

  static const List<String> _avatarLabels = [
    '預設',
    '運動',
    '專注',
    '活力',
    '思考',
    '波紋',
  ];

  final TextEditingController heightController = TextEditingController();
  final TextEditingController weightController = TextEditingController();
  final TextEditingController displayNameController = TextEditingController();
  final TextEditingController currentPasswordController =
      TextEditingController();
  final TextEditingController newPasswordController = TextEditingController();
  final TextEditingController confirmPasswordController =
      TextEditingController();

  bool _obscureCurrentPassword = true;
  bool _obscureNewPassword = true;
  bool _obscureConfirmPassword = true;
  int _avatarIndex = 0;

  String get _userScope {
    final email = widget.userEmail?.trim().toLowerCase();
    if (widget.isLoggedIn && email != null && email.isNotEmpty) {
      return email;
    }
    return 'guest';
  }

  String _key(String field) => 'settings_${_userScope}_$field';

  int get _defaultAvatarIndex =>
      (_userScope.hashCode & 0x7fffffff) % _avatarIcons.length;

  Color get _avatarColor => _avatarColors[_avatarIndex % _avatarColors.length];

  IconData get _avatarIcon => _avatarIcons[_avatarIndex % _avatarIcons.length];

  String get _avatarLabel => _avatarLabels[_avatarIndex % _avatarLabels.length];

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
    final savedDisplayName = prefs.getString(_key('displayName'));
    final savedAvatarIndex = prefs.getInt(_key('avatarIndex'));

    String? heightText;
    String? weightText;
    String? displayNameText;

    if (widget.isLoggedIn) {
      final profile = await ApiService.getMe();
      if (profile != null) {
        final height = profile['height']?.toString();
        final weight = profile['weight']?.toString();
        final email = profile['email']?.toString();
        final username = profile['username']?.toString();
        final name =
            profile['display_name']?.toString() ??
            profile['displayName']?.toString() ??
            profile['name']?.toString() ??
            profile['nickname']?.toString();
        if (height != null && height != 'null' && height.isNotEmpty) {
          heightText = height;
        }
        if (weight != null && weight != 'null' && weight.isNotEmpty) {
          weightText = weight;
        }
        if (name != null && name.isNotEmpty && name != 'null') {
          displayNameText = name;
        } else if (username != null &&
            username.isNotEmpty &&
            username != 'null') {
          displayNameText = username;
        } else if (email != null && email.isNotEmpty && email != 'null') {
          displayNameText = email.split('@').first;
        }
        debugPrint(
          '[Setting] Loaded backend profile: height=$heightText, weight=$weightText, displayName=$displayNameText',
        );
      }
    }

    heightText ??= prefs.getString(_key('height'));
    weightText ??= prefs.getString(_key('weight'));
    displayNameText ??= savedDisplayName;
    final avatarIndex = savedAvatarIndex ?? _defaultAvatarIndex;

    if (!mounted) return;
    setState(() {
      heightController.text = heightText ?? '';
      weightController.text = weightText ?? '';
      displayNameController.text = displayNameText ?? '';
      _avatarIndex = avatarIndex;
    });
  }

  Future<bool> _saveSettings() async {
    final prefs = await SharedPreferences.getInstance();
    final heightStr = heightController.text.trim();
    final weightStr = weightController.text.trim();
    final displayNameStr = displayNameController.text.trim();

    await prefs.setString(_key('height'), heightStr);
    await prefs.setString(_key('weight'), weightStr);
    await prefs.setString(_key('displayName'), displayNameStr);
    await prefs.setInt(_key('avatarIndex'), _avatarIndex);
    debugPrint(
      '[Setting] Saved locally for scope=$_userScope: displayName=$displayNameStr, avatarIndex=$_avatarIndex, height=$heightStr, weight=$weightStr',
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

  Future<void> _pickAvatar() async {
    final selected = await showModalBottomSheet<int>(
      context: context,
      showDragHandle: true,
      backgroundColor: Colors.white,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(24)),
      ),
      builder: (sheetContext) {
        return Padding(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text(
                '選擇頭像',
                style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
              ),
              const SizedBox(height: 6),
              const Text(
                '這個頭像會保存在目前帳號的本地設定中。',
                style: TextStyle(color: Color(0xFF64748B)),
              ),
              const SizedBox(height: 16),
              GridView.builder(
                shrinkWrap: true,
                itemCount: _avatarIcons.length,
                physics: const NeverScrollableScrollPhysics(),
                gridDelegate: const SliverGridDelegateWithFixedCrossAxisCount(
                  crossAxisCount: 3,
                  crossAxisSpacing: 12,
                  mainAxisSpacing: 12,
                  childAspectRatio: 0.92,
                ),
                itemBuilder: (context, index) {
                  final selectedAvatar = index == _avatarIndex;
                  return InkWell(
                    borderRadius: BorderRadius.circular(20),
                    onTap: () => Navigator.of(sheetContext).pop(index),
                    child: Container(
                      decoration: BoxDecoration(
                        color: selectedAvatar
                            ? _avatarColors[index].withValues(alpha: 0.16)
                            : const Color(0xFFF8FAFC),
                        borderRadius: BorderRadius.circular(20),
                        border: Border.all(
                          color: selectedAvatar
                              ? _avatarColors[index]
                              : const Color(0xFFE2E8F0),
                          width: selectedAvatar ? 2 : 1,
                        ),
                      ),
                      child: Column(
                        mainAxisAlignment: MainAxisAlignment.center,
                        children: [
                          CircleAvatar(
                            radius: 28,
                            backgroundColor: _avatarColors[index],
                            child: Icon(
                              _avatarIcons[index],
                              color: Colors.white,
                              size: 30,
                            ),
                          ),
                          const SizedBox(height: 10),
                          Text(
                            _avatarLabels[index],
                            style: const TextStyle(fontWeight: FontWeight.w800),
                          ),
                        ],
                      ),
                    ),
                  );
                },
              ),
            ],
          ),
        );
      },
    );

    if (selected != null && mounted) {
      setState(() => _avatarIndex = selected);
    }
  }

  Future<void> _changePassword() async {
    final currentPassword = currentPasswordController.text;
    final newPassword = newPasswordController.text;
    final confirmPassword = confirmPasswordController.text;

    if (currentPassword.trim().isEmpty || newPassword.trim().isEmpty) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('請填寫目前密碼與新密碼')));
      return;
    }

    if (newPassword.length < 6) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('新密碼至少需要 6 碼')));
      return;
    }

    if (newPassword != confirmPassword) {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('兩次輸入的新密碼不一致')));
      return;
    }

    final result = await ApiService.changePassword(
      currentPassword: currentPassword,
      newPassword: newPassword,
    );

    if (!mounted) return;

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(result.message)));

    if (result.success) {
      currentPasswordController.clear();
      newPasswordController.clear();
      confirmPasswordController.clear();
    }
  }

  Widget _buildAvatarPreview() {
    return Container(
      width: 86,
      height: 86,
      decoration: BoxDecoration(
        gradient: LinearGradient(
          colors: [_avatarColor, _avatarColor.withValues(alpha: 0.76)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(28),
        boxShadow: [
          BoxShadow(
            color: _avatarColor.withValues(alpha: 0.25),
            blurRadius: 18,
            offset: const Offset(0, 8),
          ),
        ],
      ),
      child: Icon(_avatarIcon, color: Colors.white, size: 44),
    );
  }

  Widget _buildPasswordField({
    required String label,
    required TextEditingController controller,
    required bool obscureText,
    required VoidCallback onToggle,
  }) {
    return TextField(
      controller: controller,
      obscureText: obscureText,
      decoration: InputDecoration(
        labelText: label,
        filled: true,
        fillColor: const Color(0xFFF8FAFC),
        suffixIcon: IconButton(
          onPressed: onToggle,
          icon: Icon(obscureText ? Icons.visibility_off : Icons.visibility),
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
    );
  }

  @override
  void dispose() {
    heightController.dispose();
    weightController.dispose();
    displayNameController.dispose();
    currentPasswordController.dispose();
    newPasswordController.dispose();
    confirmPasswordController.dispose();
    super.dispose();
  }

  Widget buildTextField({
    required String label,
    required String unit,
    required TextEditingController controller,
    required IconData icon,
    String? helper,
    TextInputType keyboardType = TextInputType.number,
    bool readOnly = false,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      child: TextField(
        controller: controller,
        keyboardType: keyboardType,
        readOnly: readOnly,
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
                      ? _avatarColor.withValues(alpha: 0.15)
                      : const Color(0xFF94A3B8).withValues(alpha: 0.18),
                  child: widget.isLoggedIn
                      ? Icon(_avatarIcon, color: _avatarColor)
                      : const Icon(
                          Icons.person_rounded,
                          color: Color(0xFF64748B),
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
                      if (displayNameController.text.trim().isNotEmpty) ...[
                        const SizedBox(height: 2),
                        Text(
                          displayNameController.text.trim(),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                          style: const TextStyle(color: Color(0xFF0F766E)),
                        ),
                      ],
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
                  Row(
                    children: [
                      _buildAvatarPreview(),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            Text(
                              '個人頭像',
                              style: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                                color: Color(0xFF0F172A),
                              ),
                            ),
                            const SizedBox(height: 4),
                            Text(
                              _avatarLabel,
                              style: const TextStyle(color: Color(0xFF64748B)),
                            ),
                            const SizedBox(height: 8),
                            OutlinedButton(
                              onPressed: _pickAvatar,
                              child: const Text('更換頭像'),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const SizedBox(height: 14),
                  buildTextField(
                    label: '顯示名稱',
                    unit: '',
                    controller: displayNameController,
                    icon: Icons.badge_outlined,
                    keyboardType: TextInputType.name,
                    helper: '這個名稱只會儲存在目前帳號的本地設定',
                  ),
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
                  Container(
                    width: double.infinity,
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: const Color(0xFFF8FAFC),
                      borderRadius: BorderRadius.circular(18),
                      border: Border.all(color: const Color(0xFFE2E8F0)),
                    ),
                    child: Row(
                      children: [
                        const Icon(
                          Icons.alternate_email_rounded,
                          color: Color(0xFF0F766E),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: Text(
                            widget.userEmail ?? '尚未登入',
                            style: const TextStyle(
                              fontSize: 16,
                              fontWeight: FontWeight.w700,
                              color: Color(0xFF0F172A),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        const Text(
                          '登入帳號',
                          style: TextStyle(color: Color(0xFF64748B)),
                        ),
                      ],
                    ),
                  ),
                ],
              );

              if (constraints.maxWidth < 820) {
                return Column(children: [profilePanel]);
              }

              return Row(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [Expanded(child: profilePanel)],
              );
            },
          ),

          const SizedBox(height: 16),
          _sectionPanel(
            title: '修改密碼',
            icon: Icons.lock_rounded,
            accent: const Color(0xFFEA580C),
            children: [
              _buildPasswordField(
                label: '目前密碼',
                controller: currentPasswordController,
                obscureText: _obscureCurrentPassword,
                onToggle: () => setState(() {
                  _obscureCurrentPassword = !_obscureCurrentPassword;
                }),
              ),
              const SizedBox(height: 12),
              _buildPasswordField(
                label: '新密碼',
                controller: newPasswordController,
                obscureText: _obscureNewPassword,
                onToggle: () => setState(() {
                  _obscureNewPassword = !_obscureNewPassword;
                }),
              ),
              const SizedBox(height: 12),
              _buildPasswordField(
                label: '確認新密碼',
                controller: confirmPasswordController,
                obscureText: _obscureConfirmPassword,
                onToggle: () => setState(() {
                  _obscureConfirmPassword = !_obscureConfirmPassword;
                }),
              ),
              const SizedBox(height: 14),
              SizedBox(
                width: double.infinity,
                child: FilledButton.icon(
                  onPressed: widget.isLoggedIn ? _changePassword : null,
                  icon: const Icon(Icons.password_rounded),
                  label: const Text('更新密碼'),
                ),
              ),
            ],
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
                if (syncedOk) {
                  await widget.onProfileChanged?.call();
                }
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
