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
                    padding: const EdgeInsets.fromLTRB(14, 14, 14, 10),
                    child: Container(
                      padding: const EdgeInsets.all(14),
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
                          // 登入/登出按鈕列
                          Row(
                            children: [
                              const Spacer(),
                              if (!_isLoggedIn) ...[
                                OutlinedButton(
                                  onPressed: () => _openAuth(AuthMode.login),
                                  child: const Text('登入'),
                                ),
                                const SizedBox(width: 6),
                                FilledButton(
                                  onPressed: () => _openAuth(AuthMode.register),
                                  child: const Text('註冊'),
                                ),
                              ] else
                                IconButton(
                                  onPressed: _logout,
                                  tooltip: '登出',
                                  icon: const Icon(Icons.logout_rounded),
                                ),
                            ],
                          ),
                          const SizedBox(height: 8),

                          // App 標題
                          Center(
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 14,
                                vertical: 10,
                              ),
                              decoration: BoxDecoration(
                                gradient: LinearGradient(
                                  begin: Alignment.topLeft,
                                  end: Alignment.bottomRight,
                                  colors: [
                                    colorScheme.primary.withValues(alpha: 0.16),
                                    colorScheme.primary.withValues(alpha: 0.08),
                                  ],
                                ),
                                borderRadius: BorderRadius.circular(16),
                                border: Border.all(
                                  color: colorScheme.primary.withValues(
                                    alpha: 0.26,
                                  ),
                                ),
                              ),
                              child: Column(
                                children: [
                                  Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Container(
                                        width: 34,
                                        height: 34,
                                        decoration: BoxDecoration(
                                          color: colorScheme.primary.withValues(
                                            alpha: 0.18,
                                          ),
                                          borderRadius: BorderRadius.circular(
                                            10,
                                          ),
                                        ),
                                        child: Icon(
                                          Icons.event_seat_rounded,
                                          color: colorScheme.primary,
                                          size: 22,
                                        ),
                                      ),
                                      const SizedBox(width: 8),
                                      const Text(
                                        '智慧座椅',
                                        style: TextStyle(
                                          fontSize: 30,
                                          fontWeight: FontWeight.w900,
                                          color: Color(0xFF0F172A),
                                          letterSpacing: 1.0,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 2),
                                  Text(
                                    navItems[currentIndex]['hint'] as String,
                                    style: const TextStyle(
                                      fontSize: 14,
                                      color: Color(0xFF64748B),
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                ],
                              ),
                            ),
                          ),
                          const SizedBox(height: 12),

                          // 登入狀態列
                          Container(
                            width: double.infinity,
                            padding: const EdgeInsets.symmetric(
                              horizontal: 12,
                              vertical: 10,
                            ),
                            decoration: BoxDecoration(
                              color: _isLoggedIn
                                  ? const Color(0xFFECFDF3)
                                  : const Color(0xFFFFF7ED),
                              borderRadius: BorderRadius.circular(12),
                            ),
                            child: Row(
                              children: [
                                Icon(
                                  _isLoggedIn
                                      ? Icons.verified_user_rounded
                                      : Icons.info_outline_rounded,
                                  size: 18,
                                  color: _isLoggedIn
                                      ? const Color(0xFF15803D)
                                      : const Color(0xFFB45309),
                                ),
                                const SizedBox(width: 8),
                                Expanded(
                                  child: Text(
                                    _isLoggedIn
                                        ? (_userEmail ?? '已登入')
                                        : '尚未登入，登入後可同步坐姿資料',
                                    maxLines: 1,
                                    overflow: TextOverflow.ellipsis,
                                    style: TextStyle(
                                      fontSize: 13,
                                      color: _isLoggedIn
                                          ? const Color(0xFF166534)
                                          : const Color(0xFF9A3412),
                                    ),
                                  ),
                                ),
                              ],
                            ),
                          ),
                          const SizedBox(height: 12),

                          // 底部導覽列
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
