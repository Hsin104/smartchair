import 'dart:io';

import 'package:flutter/material.dart';
import 'package:screen_retriever/screen_retriever.dart';
import 'package:window_manager/window_manager.dart';
import 'package:system_tray/system_tray.dart';
import 'services/api_service.dart';
import 'state/chair_sync_controller.dart';
import 'widgets/desk_pet_overlay.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 初始化 window_manager
  await windowManager.ensureInitialized();

  final options = WindowOptions(
    size: const Size(360, 260),
    center: false,
    backgroundColor: Colors.transparent,
    skipTaskbar: true,
    titleBarStyle: TitleBarStyle.hidden,
    alwaysOnTop: true,
  );

  windowManager.waitUntilReadyToShow(options, () async {
    // 設定在螢幕右下角
    final display = await screenRetriever.getPrimaryDisplay();
    final workAreaSize = display.visibleSize ?? display.size;
    final workAreaOffset = display.visiblePosition ?? Offset.zero;
    final width = options.size!.width;
    final height = options.size!.height;
    final dx = workAreaOffset.dx + workAreaSize.width - width - 20;
    final dy = workAreaOffset.dy + workAreaSize.height - height - 40;

    await windowManager.setSize(options.size!);
    await windowManager.setPosition(Offset(dx, dy));
    await windowManager.setAlwaysOnTop(true);
    await windowManager.setSkipTaskbar(true);
    await windowManager.show();
    await windowManager.focus();
  });

  final tray = SystemTray();
  var trayReady = false;

  runApp(
    DesktopPetApp(
      onClose: () async {
        if (trayReady) {
          await tray.destroy();
        }
        exit(0);
      },
    ),
  );

  // 初始化系統托盤
  final iconPath = File('assets/tray_icon.ico').absolute.path;

  final menu = Menu();
  await menu.buildFrom([
    MenuItemLabel(
      label: '顯示/隱藏',
      onClicked: (menuItem) async {
        final isVisible = await windowManager.isVisible();
        if (isVisible) {
          await windowManager.hide();
        } else {
          await windowManager.show();
          await windowManager.focus();
        }
      },
    ),
    MenuItemLabel(
      label: '退出',
      onClicked: (menuItem) async {
        await tray.destroy();
        // 程式退出
        exit(0);
      },
    ),
  ]);

  try {
    if (!File(iconPath).existsSync()) {
      throw FileSystemException('Tray icon not found', iconPath);
    }
    await tray.initSystemTray(iconPath: iconPath, toolTip: 'SmartChair Pet');
    await tray.setContextMenu(menu);
    trayReady = true;
  } catch (error) {
    debugPrint('System tray disabled: $error');
  }
}

class DesktopPetApp extends StatefulWidget {
  const DesktopPetApp({super.key, required this.onClose});

  final Future<void> Function() onClose;

  @override
  State<DesktopPetApp> createState() => _DesktopPetAppState();
}

class _DesktopPetAppState extends State<DesktopPetApp>
    with WidgetsBindingObserver {
  static const _desktopUsername = String.fromEnvironment('DESKTOP_USERNAME');
  static const _desktopPassword = String.fromEnvironment('DESKTOP_PASSWORD');

  late final ChairSyncController chairSyncController;

  @override
  void initState() {
    super.initState();
    chairSyncController = ChairSyncController();
    _startSync();
  }

  Future<void> _startSync() async {
    if (!await ApiService.isLoggedIn() &&
        _desktopUsername.isNotEmpty &&
        _desktopPassword.isNotEmpty) {
      final result = await ApiService.login(_desktopUsername, _desktopPassword);
      if (!result.success) {
        debugPrint('Desktop pet login failed: ${result.message}');
      }
    }

    await ApiService.chairCheckin();
    chairSyncController.startSession();
    chairSyncController.startAutoSync();
  }

  @override
  void dispose() {
    chairSyncController.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        textTheme: Typography.material2018().black.apply(
          bodyColor: const Color(0xFF0F172A),
        ),
      ),
      home: Scaffold(
        backgroundColor: Colors.transparent,
        body: Center(
          child: Padding(
            padding: const EdgeInsets.all(14),
            child: DeskPetOverlay(
              controller: chairSyncController,
              onDragStart: windowManager.startDragging,
              onClose: widget.onClose,
            ),
          ),
        ),
      ),
    );
  }
}
