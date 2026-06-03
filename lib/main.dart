import 'package:flutter/material.dart';
import 'screens/home_page.dart';
import 'state/chair_sync_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  runApp(const SmartChairApp());
}

class SmartChairApp extends StatefulWidget {
  const SmartChairApp({super.key});

  @override
  State<SmartChairApp> createState() => _SmartChairAppState();
}

class _SmartChairAppState extends State<SmartChairApp> {
  late final ChairSyncController chairSyncController;
  static const _latinFont = 'Times New Roman';
  static const _chineseFontFallback = [
    '標楷體',
    'DFKai-SB',
    'BiauKai',
    'KaiTi',
    'serif',
  ];

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
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF0E7490),
      brightness: Brightness.light,
    );

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '智慧座椅',
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: _latinFont,
        fontFamilyFallback: _chineseFontFallback,
        colorScheme: colorScheme,
        scaffoldBackgroundColor: const Color(0xFFF2F7FA),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          foregroundColor: Color(0xFF0F172A),
          elevation: 0,
        ),
        cardTheme: CardThemeData(
          elevation: 0,
          color: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(18),
          ),
        ),
        snackBarTheme: SnackBarThemeData(
          behavior: SnackBarBehavior.floating,
          backgroundColor: const Color(0xFF0F172A),
          contentTextStyle: const TextStyle(
            color: Colors.white,
            fontFamily: _latinFont,
            fontFamilyFallback: _chineseFontFallback,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      home: HomePage(chairSyncController: chairSyncController),
    );
  }
}
