// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

const _key = 'smartchair.home_nav_order';

Future<String?> loadSavedNavOrder() async => html.window.localStorage[_key];

Future<void> saveNavOrderValue(String value) async {
  html.window.localStorage[_key] = value;
}
