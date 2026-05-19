import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../state/chair_sync_controller.dart';
import '../widgets/desk_pet_overlay.dart';
import 'auth_page.dart';
import 'dashboard.dart';
import 'report.dart';
import 'notification.dart';
import 'setting.dart';

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.chairSyncController});

  final ChairSyncController chairSyncController;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int currentIndex = 0;
  bool _isLoggedIn = false;
  String? _userEmail;

  final List<Map<String, dynamic>> navItems = const [
    {'icon': Icons.event_seat, 'label': '儀表板', 'hint': '即時坐姿'},
    {'icon': Icons.bar_chart_rounded, 'label': '報表', 'hint': '今日分析'},
    {'icon': Icons.notifications_active_rounded, 'label': '通知', 'hint': '提醒中心'},
    {'icon': Icons.tune_rounded, 'label': '設定', 'hint': '個人偏好'},
  ];

  @override
  void initState() {
    super.initState();
    _refreshAuthState();
  }

  Future<void> _refreshAuthState() async {
    final loggedIn = await ApiService.isLoggedIn();
    final email = await ApiService.getUserEmail();
    if (mounted) {
      setState(() {
        _isLoggedIn = loggedIn;
        _userEmail = email;
        if (!loggedIn) {
          currentIndex = 0;
        }
      });
      // Start or stop controller auto-sync based on login state
      if (_isLoggedIn) {
        widget.chairSyncController.startAutoSync();
      } else {
        widget.chairSyncController.stopAutoSync();
      }
    }
  }

  void _showMsg(String msg) {
    ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(msg)));
  }

  Future<void> _openAuth(AuthMode mode) async {
    final String? email = await Navigator.of(context).push<String>(
      MaterialPageRoute(builder: (_) => AuthPage(initialMode: mode)),
    );

    if (email != null && mounted) {
      _showMsg(mode == AuthMode.login ? '登入成功' : '註冊成功');
      await _refreshAuthState();
      if (mounted) {
        setState(() => currentIndex = 0);
      }
    }
  }

  Future<void> _logout() async {
    await ApiService.logout();
    if (!mounted) return;
    _showMsg('已登出');
    await _refreshAuthState();
  }

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    if (!_isLoggedIn) {
      return _AuthLandingPage(
        onLogin: () => _openAuth(AuthMode.login),
        onRegister: () => _openAuth(AuthMode.register),
      );
    }

    final pages = [
      DashboardPage(
        controller: widget.chairSyncController,
        isLoggedIn: _isLoggedIn,
        onOpenReport: () => setState(() => currentIndex = 1),
        onStartStretch: () => setState(() => currentIndex = 2),
      ),
      ReportPage(controller: widget.chairSyncController),
      NotificationPage(controller: widget.chairSyncController),
      SettingPage(
        isLoggedIn: _isLoggedIn,
        userEmail: _userEmail,
        onLogout: _logout,
      ),
    ];

    return Scaffold(
      body: Stack(
        children: [
          Container(
            decoration: const BoxDecoration(
              gradient: LinearGradient(
                begin: Alignment.topCenter,
                end: Alignment.bottomCenter,
                colors: [Color(0xFFE9F7FC), Color(0xFFF5F8FA)],
              ),
            ),
            child: SafeArea(
              child: Column(
                children: [
                  Padding(
                    padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                    child: Container(
                      padding: const EdgeInsets.fromLTRB(14, 12, 14, 12),
                      decoration: BoxDecoration(
                        color: Colors.white,
                        borderRadius: BorderRadius.circular(20),
                        boxShadow: [
                          BoxShadow(
                            color: Colors.black.withValues(alpha: 0.06),
                            blurRadius: 18,
                            offset: const Offset(0, 8),
                          ),
                        ],
                      ),
                      child: Column(
                        children: [
                          Row(
                            children: [
                              _BrandBadge(
                                colorScheme: colorScheme,
                                showWebTag: true,
                                compact: false,
                              ),
                              const Spacer(),
                              IconButton(
                                onPressed: _logout,
                                tooltip: '登出',
                                icon: const Icon(Icons.logout_rounded),
                              ),
                            ],
                          ),
                          const SizedBox(height: 10),
                          Row(
                            children: List.generate(navItems.length, (index) {
                              final bool selected = index == currentIndex;
                              return Expanded(
                                child: Padding(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 3,
                                  ),
                                  child: InkWell(
                                    borderRadius: BorderRadius.circular(12),
                                    onTap: () =>
                                        setState(() => currentIndex = index),
                                    child: AnimatedContainer(
                                      duration: const Duration(
                                        milliseconds: 180,
                                      ),
                                      padding: const EdgeInsets.symmetric(
                                        vertical: 8,
                                      ),
                                      decoration: BoxDecoration(
                                        color: selected
                                            ? colorScheme.primary
                                            : const Color(0xFFF1F5F9),
                                        borderRadius: BorderRadius.circular(12),
                                      ),
                                      child: Column(
                                        children: [
                                          Icon(
                                            navItems[index]['icon'] as IconData,
                                            color: selected
                                                ? Colors.white
                                                : const Color(0xFF475569),
                                          ),
                                          const SizedBox(height: 2),
                                          Text(
                                            navItems[index]['label'] as String,
                                            style: TextStyle(
                                              fontSize: 12,
                                              color: selected
                                                  ? Colors.white
                                                  : const Color(0xFF334155),
                                              fontWeight: FontWeight.w700,
                                            ),
                                          ),
                                        ],
                                      ),
                                    ),
                                  ),
                                ),
                              );
                            }),
                          ),
                        ],
                      ),
                    ),
                  ),
                  Expanded(child: pages[currentIndex]),
                ],
              ),
            ),
          ),
          Positioned(
            right: 16,
            bottom: 16,
            child: SafeArea(
              child: DeskPetOverlay(controller: widget.chairSyncController),
            ),
          ),
        ],
      ),
    );
  }
}

class _AuthLandingPage extends StatelessWidget {
  const _AuthLandingPage({required this.onLogin, required this.onRegister});

  final VoidCallback onLogin;
  final VoidCallback onRegister;

  @override
  Widget build(BuildContext context) {
    final colorScheme = Theme.of(context).colorScheme;

    return Scaffold(
      body: Container(
        decoration: const BoxDecoration(
          gradient: LinearGradient(
            begin: Alignment.topLeft,
            end: Alignment.bottomRight,
            colors: [Color(0xFFE6F7FB), Color(0xFFF7FAFC), Color(0xFFF1F8F6)],
          ),
        ),
        child: SafeArea(
          child: Center(
            child: SingleChildScrollView(
              padding: const EdgeInsets.all(20),
              child: ConstrainedBox(
                constraints: const BoxConstraints(maxWidth: 480),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    _BrandBadge(
                      colorScheme: colorScheme,
                      showWebTag: true,
                      compact: false,
                    ),
                    const SizedBox(height: 36),
                    Row(
                      children: [
                        Expanded(
                          child: OutlinedButton(
                            onPressed: onLogin,
                            style: OutlinedButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 20),
                              textStyle: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                              side: BorderSide(color: colorScheme.primary),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(18),
                              ),
                            ),
                            child: const Text(
                              '登入',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                        ),
                        const SizedBox(width: 12),
                        Expanded(
                          child: FilledButton(
                            onPressed: onRegister,
                            style: FilledButton.styleFrom(
                              padding: const EdgeInsets.symmetric(vertical: 20),
                              textStyle: const TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                              shape: RoundedRectangleBorder(
                                borderRadius: BorderRadius.circular(18),
                              ),
                            ),
                            child: const Text(
                              '註冊',
                              style: TextStyle(
                                fontSize: 18,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _BrandBadge extends StatelessWidget {
  const _BrandBadge({
    required this.colorScheme,
    required this.showWebTag,
    required this.compact,
  });

  final ColorScheme colorScheme;
  final bool showWebTag;
  final bool compact;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: compact ? 32 : 40,
          height: compact ? 32 : 40,
          decoration: BoxDecoration(
            color: colorScheme.primary.withValues(alpha: 0.16),
            borderRadius: BorderRadius.circular(12),
          ),
          child: Icon(
            Icons.event_seat_rounded,
            color: colorScheme.primary,
            size: compact ? 20 : 26,
          ),
        ),
        const SizedBox(width: 10),
        const Text(
          '智慧座椅',
          style: TextStyle(
            fontSize: 40,
            fontWeight: FontWeight.w900,
            color: Color(0xFF0F172A),
            letterSpacing: 1.2,
          ),
        ),
        if (showWebTag) ...[
          const SizedBox(width: 10),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
            decoration: BoxDecoration(
              color: const Color(0xFF0F766E).withValues(alpha: 0.12),
              borderRadius: BorderRadius.circular(999),
              border: Border.all(
                color: const Color(0xFF0F766E).withValues(alpha: 0.2),
              ),
            ),
            child: const Text(
              'WEB',
              style: TextStyle(
                fontSize: 20,
                fontWeight: FontWeight.w800,
                color: Color(0xFF0F766E),
                letterSpacing: 1.2,
              ),
            ),
          ),
        ],
      ],
    );
  }
}
