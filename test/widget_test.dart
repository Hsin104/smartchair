// This is a basic Flutter widget test.
//
// To perform an interaction with a widget in your test, use the WidgetTester
// utility in the flutter_test package. For example, you can send tap and scroll
// gestures. You can also use WidgetTester to find child widgets in the widget
// tree, read text, and verify that the values of widget properties are correct.

import 'package:flutter_test/flutter_test.dart';

import 'package:smart_chair_app/main.dart';
import 'package:smart_chair_app/screens/auth_page.dart';
import 'package:smart_chair_app/services/api_service.dart';

void main() {
  testWidgets('App shell renders', (WidgetTester tester) async {
    await tester.pumpWidget(const SmartChairApp());

    expect(find.text('智慧座椅'), findsOneWidget);
  });

  test('register duplicate username message is reported clearly', () {
    expect(
      AuthPage.usernameValidationMessage(
        isRegisterMode: true,
        usernameExists: true,
      ),
      '此帳號已存在',
    );
  });

  test('forgot password requires both email and username together', () {
    final validPayload = ApiService.forgotPasswordPayload(
      username: 'alice',
      email: 'user@example.com',
    );

    expect(validPayload, {'email': 'user@example.com', 'username': 'alice'});
    expect(
      () => ApiService.forgotPasswordPayload(username: 'alice', email: ''),
      throwsA(isA<StateError>()),
    );
    expect(
      () => ApiService.forgotPasswordPayload(
        username: '',
        email: 'user@example.com',
      ),
      throwsA(isA<StateError>()),
    );
  });
}
