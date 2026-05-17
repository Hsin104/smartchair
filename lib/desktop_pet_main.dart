import 'dart:io';

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';
import 'package:system_tray/system_tray.dart';
import 'screens/home_page.dart';
import 'state/chair_sync_controller.dart';
import 'widgets/desk_pet_overlay.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  // 初始化 window_manager
  await windowManager.ensureInitialized();

  final options = WindowOptions(
    size: const Size(300, 140),
    center: false,
    backgroundColor: Colors.transparent,
    skipTaskbar: true,
    titleBarStyle: TitleBarStyle.hidden,
    alwaysOnTop: true,
  );

  windowManager.waitUntilReadyToShow(options, () async {
    // 設定在螢幕右下角
    final display = await windowManager.getPrimaryDisplay();
    final workArea = display.workArea;
    final width = options.size!.width;
    final height = options.size!.height;
    final dx = workArea.right - width - 20;
    final dy = workArea.bottom - height - 40;

    await windowManager.setSize(options.size!);
    await windowManager.setPosition(Offset(dx, dy));
    await windowManager.setAlwaysOnTop(true);
    await windowManager.setSkipTaskbar(true);
    await windowManager.show();
    await windowManager.focus();
  });

  // 初始化系統托盤
  final tray = SystemTray();
  String iconPath = 'assets/tray_icon.ico';
  if (!File(iconPath).existsSync()) {
    // 若沒有 icon，使用空白（system_tray 需要 icon，提醒使用者自行放置）
    print(
      'Warning: $iconPath not found. Please add an ICO file at that path for the tray icon.',
    );
  }

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
        // 程序退出
        exit(0);
      },
    ),
  ]);

  await tray.initSystemTray(iconPath: iconPath, toolTip: 'SmartChair Pet');
  await tray.setContextMenu(menu);

  runApp(const DesktopPetApp());
}

class DesktopPetApp extends StatefulWidget {
  const DesktopPetApp({super.key});

  @override
  State<DesktopPetApp> createState() => _DesktopPetAppState();
}

class _DesktopPetAppState extends State<DesktopPetApp>
    with WidgetsBindingObserver {
  late final ChairSyncController chairSyncController;

  @override
  void initState() {
    super.initState();
    chairSyncController = ChairSyncController();
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
      home: Scaffold(
        backgroundColor: Colors.transparent,
        body: Align(
          alignment: Alignment.bottomRight,
          child: Padding(
            padding: const EdgeInsets.all(8.0),
            child: DeskPetOverlay(controller: chairSyncController),
          ),
        ),
      ),
    );
  }
}
