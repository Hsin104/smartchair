import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';
import 'package:flutter/foundation.dart';
import 'firebase_options.dart';
import 'screens/home_page.dart';
import 'state/chair_sync_controller.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  bool firebaseReady = false;
  String? firebaseError;

  try {
    if (kIsWeb) {
      await Firebase.initializeApp(options: DefaultFirebaseOptions.web);
    } else {
      await Firebase.initializeApp();
    }
    firebaseReady = true;
  } catch (e) {
    firebaseError = e.toString();
  }

  runApp(
    SmartChairApp(firebaseReady: firebaseReady, firebaseError: firebaseError),
  );
}

class SmartChairApp extends StatefulWidget {
  const SmartChairApp({
    super.key,
    required this.firebaseReady,
    this.firebaseError,
  });

  final bool firebaseReady;
  final String? firebaseError;

  @override
  State<SmartChairApp> createState() => _SmartChairAppState();
}

class _SmartChairAppState extends State<SmartChairApp> {
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
    final colorScheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF0E7490),
      brightness: Brightness.light,
    );

    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: '智慧座椅',
      theme: ThemeData(
        useMaterial3: true,
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
          contentTextStyle: const TextStyle(color: Colors.white),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(12),
          ),
        ),
      ),
      home: HomePage(
        firebaseReady: widget.firebaseReady,
        firebaseError: widget.firebaseError,
        chairSyncController: chairSyncController,
      ),
    );
  }
}
