import 'package:flutter/material.dart';
import 'screens/home_page.dart';

void main() {
  runApp(const SmartChairApp());
}

class SmartChairApp extends StatelessWidget {
  const SmartChairApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      debugShowCheckedModeBanner: false,
      title: 'Smart Chair',
      theme: ThemeData(primarySwatch: Colors.blue),
      home: const HomePage(),
    );
  }
}
