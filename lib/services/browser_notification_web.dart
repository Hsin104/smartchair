// Browser-only implementation; the conditional import keeps this file out of
// native builds.
// ignore_for_file: avoid_web_libraries_in_flutter, deprecated_member_use
import 'dart:html' as html;

Future<void> showBrowserNotification(String title, String body) async {
  if (html.Notification.permission == 'denied') return;
  if (html.Notification.permission != 'granted') {
    final permission = await html.Notification.requestPermission();
    if (permission != 'granted') return;
  }
  html.Notification(title, body: body);
}
