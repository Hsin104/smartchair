import 'package:flutter/material.dart';
import '../services/api_service.dart';
import '../services/nav_order_storage.dart';
import '../state/chair_sync_controller.dart';
import 'auth_page.dart';
import 'dashboard.dart';
import 'notification.dart';
import 'setting.dart';
import 'ai_advice_page.dart';
import 'health_garden_page.dart';
import '../state/wellness_controller.dart';

class HomePage extends StatefulWidget {
  const HomePage({
    super.key,
    required this.chairSyncController,
    required this.wellnessController,
  });

  final ChairSyncController chairSyncController;
  final WellnessController wellnessController;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  int currentIndex = 0;
  bool _isLoggedIn = false;
  String? _userEmail;
  int _authRefreshVersion = 0;
  List<int> _navOrder = [0, 1, 2, 3];

  final List<Map<String, dynamic>> navItems = const [
    {'icon': Icons.event_seat, 'label': '健康總覽', 'hint': '坐姿與報表'},
    {'icon': Icons.psychology_alt_rounded, 'label': 'AI 建議', 'hint': '治療師建議'},
    {'icon': Icons.local_florist_rounded, 'label': '健康花園', 'hint': '每日養成'},
    {'icon': Icons.notifications_active_rounded, 'label': '通知', 'hint': '提醒中心'},
  ];

  @override
  void initState() {
    super.initState();
    _loadNavOrder();
    _refreshAuthState();
  }

  Future<void> _loadNavOrder() async {
    // 瀏覽器原生 localStorage 不受登入登出或頁面熱重載影響。
    final savedValue = await loadSavedNavOrder();
    if (savedValue == null || !mounted) return;

    final order = savedValue
        .split(',')
        .map(int.tryParse)
        .whereType<int>()
        .where((index) => index >= 0 && index < navItems.length)
        .toSet()
        .toList();
    if (order.length != navItems.length) return;

    setState(() => _navOrder = order);
  }

  Future<void> _saveNavOrder() async {
    // 使用逗號分隔儲存頁面索引，開啟分頁或重新整理後可直接還原。
    await saveNavOrderValue(
      _navOrder.map((index) => index.toString()).join(','),
    );
  }

  Future<void> _refreshAuthState() async {
    final refreshVersion = ++_authRefreshVersion;
    final wasLoggedIn = _isLoggedIn;
    final loggedIn = await ApiService.isLoggedIn();
    final email = await ApiService.getUserEmail();
    if (mounted && refreshVersion == _authRefreshVersion) {
      setState(() {
        _isLoggedIn = loggedIn;
        _userEmail = email;
        if (!loggedIn) {
          currentIndex = 0;
        }
      });

      if (loggedIn && !wasLoggedIn) {
      } else if (!loggedIn && wasLoggedIn) {
        widget.chairSyncController.stopSession();
        widget.chairSyncController.stopAutoSync();
      }
    }
    if (refreshVersion == _authRefreshVersion) {
      await widget.wellnessController.initialize(email);
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
    // 在登出前嘗試 checkout（代表使用者離開椅子）
    try {
      await ApiService.chairCheckout();
    } catch (_) {
      // 忽略 checkout 錯誤，仍然繼續登出流程
    }

    await ApiService.logout();
    if (!mounted) return;
    widget.chairSyncController.stopSession();
    _showMsg('已登出');
    await _refreshAuthState();
  }

  Future<void> _accountDeleted() async {
    await ApiService.logout();
    if (!mounted) return;
    widget.chairSyncController.stopSession();
    widget.chairSyncController.stopAutoSync();
    widget.chairSyncController.clearNotifications();
    widget.chairSyncController.clearPostureHistory();
    _showMsg('帳號已刪除');
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
        wellnessController: widget.wellnessController,
        onOpenAi: () => setState(() => currentIndex = 1),
        onOpenGarden: () => setState(() => currentIndex = 2),
        onOpenSettings: () => setState(() => currentIndex = 0),
      ),
      AiAdvicePage(
        controller: widget.chairSyncController,
        isLoggedIn: _isLoggedIn,
        wellnessController: widget.wellnessController,
      ),
      HealthGardenPage(
        controller: widget.wellnessController,
        postureCode: widget.chairSyncController.postureCode,
      ),
      NotificationPage(
        controller: widget.chairSyncController,
        wellnessController: widget.wellnessController,
      ),
    ];
    final settingsPage = SettingPage(
      isLoggedIn: _isLoggedIn,
      userEmail: _userEmail,
      wellnessController: widget.wellnessController,
      onLogout: _logout,
      onAccountDeleted: _accountDeleted,
      onProfileChanged: _refreshAuthState,
    );

    return Scaffold(
      body: Container(
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
                  padding: const EdgeInsets.fromLTRB(18, 16, 18, 16),
                  decoration: BoxDecoration(
                    color: Colors.white,
                    borderRadius: BorderRadius.circular(24),
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
                            tooltip: '個人設定',
                            icon: const Icon(Icons.settings_outlined),
                            onPressed: () {
                              Navigator.of(context).push(
                                MaterialPageRoute(
                                  builder: (_) => Scaffold(
                                    appBar: AppBar(title: const Text('個人設定')),
                                    body: settingsPage,
                                  ),
                                ),
                              );
                            },
                          ),
                          IconButton(
                            tooltip: '登出帳號',
                            icon: const Icon(Icons.logout_rounded),
                            onPressed: _logout,
                          ),
                        ],
                      ),
                      const SizedBox(height: 10),
                      LayoutBuilder(
                        builder: (context, constraints) {
                          final compact = constraints.maxWidth < 720;
                          final itemWidth =
                              (constraints.maxWidth - 8) / navItems.length;
                          return SizedBox(
                            height: compact ? 68 : 62,
                            child: ReorderableListView.builder(
                              scrollDirection: Axis.horizontal,
                              buildDefaultDragHandles: false,
                              itemCount: navItems.length,
                              onReorder: (oldIndex, newIndex) {
                                setState(() {
                                  if (newIndex > oldIndex) newIndex -= 1;
                                  final pageIndex = _navOrder.removeAt(
                                    oldIndex,
                                  );
                                  _navOrder.insert(newIndex, pageIndex);
                                });
                                _saveNavOrder();
                              },
                              itemBuilder: (context, position) {
                                final pageIndex = _navOrder[position];
                                final item = navItems[pageIndex];
                                final selected = pageIndex == currentIndex;
                                return ReorderableDragStartListener(
                                  key: ValueKey('nav_$pageIndex'),
                                  index: position,
                                  child: SizedBox(
                                    width: itemWidth,
                                    child: Tooltip(
                                      message: '拖曳可調整順序',
                                      child: Padding(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 4,
                                        ),
                                        child: InkWell(
                                          borderRadius: BorderRadius.circular(
                                            18,
                                          ),
                                          onTap: () => setState(
                                            () => currentIndex = pageIndex,
                                          ),
                                          child: AnimatedContainer(
                                            duration: const Duration(
                                              milliseconds: 180,
                                            ),
                                            padding: const EdgeInsets.symmetric(
                                              vertical: 12,
                                              horizontal: 8,
                                            ),
                                            decoration: BoxDecoration(
                                              color: selected
                                                  ? colorScheme.primary
                                                  : const Color(0xFFF1F5F9),
                                              borderRadius:
                                                  BorderRadius.circular(18),
                                            ),
                                            child: Flex(
                                              direction: compact
                                                  ? Axis.vertical
                                                  : Axis.horizontal,
                                              mainAxisAlignment:
                                                  MainAxisAlignment.center,
                                              children: [
                                                Icon(
                                                  item['icon'] as IconData,
                                                  size: selected ? 26 : 24,
                                                  color: selected
                                                      ? Colors.white
                                                      : const Color(0xFF475569),
                                                ),
                                                SizedBox(
                                                  width: compact ? 0 : 8,
                                                  height: compact ? 4 : 0,
                                                ),
                                                Flexible(
                                                  child: Text(
                                                    item['label'] as String,
                                                    textAlign: TextAlign.center,
                                                    style: TextStyle(
                                                      fontSize: compact
                                                          ? (selected ? 14 : 13)
                                                          : (selected
                                                                ? 18
                                                                : 17),
                                                      color: selected
                                                          ? Colors.white
                                                          : const Color(
                                                              0xFF334155,
                                                            ),
                                                      fontWeight:
                                                          FontWeight.w800,
                                                    ),
                                                  ),
                                                ),
                                                if (!compact) ...[
                                                  const SizedBox(width: 4),
                                                  Icon(
                                                    Icons
                                                        .drag_indicator_rounded,
                                                    size: 16,
                                                    color: selected
                                                        ? Colors.white70
                                                        : const Color(
                                                            0xFF94A3B8,
                                                          ),
                                                  ),
                                                ],
                                              ],
                                            ),
                                          ),
                                        ),
                                      ),
                                    ),
                                  ),
                                );
                              },
                            ),
                          );
                        },
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
