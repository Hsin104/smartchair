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
  static const _appFont = 'SmartChairTimes';
  static const _fontFallback = [
    'SmartChairKai',
    'serif',
  ];
  static const _appFontStyle = TextStyle(
    fontFamily: _appFont,
    fontFamilyFallback: _fontFallback,
  );

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
    final textTheme = Typography.material2018().black.apply(
      fontFamily: _appFont,
      fontFamilyFallback: _fontFallback,
    );
    final primaryTextTheme = Typography.material2018().white.apply(
      fontFamily: _appFont,
      fontFamilyFallback: _fontFallback,
    );

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '智慧座椅',
      theme: ThemeData(
        useMaterial3: true,
        fontFamily: _appFont,
        fontFamilyFallback: _fontFallback,
        textTheme: textTheme,
        primaryTextTheme: primaryTextTheme,
        colorScheme: colorScheme,
        scaffoldBackgroundColor: const Color(0xFFF2F7FA),
        appBarTheme: const AppBarTheme(
          backgroundColor: Colors.transparent,
          foregroundColor: Color(0xFF0F172A),
          elevation: 0,
          titleTextStyle: TextStyle(
            color: Color(0xFF0F172A),
            fontSize: 22,
            fontWeight: FontWeight.w800,
            fontFamily: _appFont,
            fontFamilyFallback: _fontFallback,
          ),
          toolbarTextStyle: _appFontStyle,
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
          contentTextStyle: _appFontStyle.copyWith(color: Colors.white),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
        inputDecorationTheme: InputDecorationTheme(
          labelStyle: _appFontStyle,
          hintStyle: _appFontStyle.copyWith(color: const Color(0xFF64748B)),
          helperStyle: _appFontStyle,
          errorStyle: _appFontStyle.copyWith(color: Colors.red),
        ),
        textButtonTheme: TextButtonThemeData(
          style: TextButton.styleFrom(textStyle: _appFontStyle),
        ),
        elevatedButtonTheme: ElevatedButtonThemeData(
          style: ElevatedButton.styleFrom(textStyle: _appFontStyle),
        ),
        filledButtonTheme: FilledButtonThemeData(
          style: FilledButton.styleFrom(textStyle: _appFontStyle),
        ),
        outlinedButtonTheme: OutlinedButtonThemeData(
          style: OutlinedButton.styleFrom(textStyle: _appFontStyle),
        ),
        tooltipTheme: const TooltipThemeData(textStyle: _appFontStyle),
      ),
      home: HomePage(chairSyncController: chairSyncController),
    );
  }
}
