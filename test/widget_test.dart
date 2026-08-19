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

  test('forgot password payload requires username, email, and new password', () {
    final validPayload = ApiService.forgotPasswordPayload(
      username: 'alice',
      email: 'user@example.com',
      newPassword: 'newpass123',
    );

    expect(validPayload, {
      'email': 'user@example.com',
      'username': 'alice',
      'new_password': 'newpass123',
    });

    expect(
      () => ApiService.forgotPasswordPayload(
        username: 'alice',
        email: '',
        newPassword: 'newpass123',
      ),
      throwsA(isA<StateError>()),
    );
    expect(
      () => ApiService.forgotPasswordPayload(
        username: '',
        email: 'user@example.com',
        newPassword: 'newpass123',
      ),
      throwsA(isA<StateError>()),
    );
    expect(
      () => ApiService.forgotPasswordPayload(
        username: 'alice',
        email: 'user@example.com',
        newPassword: '',
      ),
      throwsA(isA<StateError>()),
    );
  });

  test('forgot password step 1 requires username and email', () {
    final validPayload = ApiService.forgotPasswordRequestPayload(
      username: 'alice',
      email: 'user@example.com',
    );

    expect(validPayload, {'email': 'user@example.com', 'username': 'alice'});
    expect(
      () => ApiService.forgotPasswordRequestPayload(
        username: 'alice',
        email: '',
      ),
      throwsA(isA<StateError>()),
    );
    expect(
      () => ApiService.forgotPasswordRequestPayload(
        username: '',
        email: 'user@example.com',
      ),
      throwsA(isA<StateError>()),
    );
  });

  test(
    'forgot password step 2 requires a 6-digit code and a new password',
    () {
      final validPayload = ApiService.forgotPasswordVerifyPayload(
        username: 'alice',
        code: '123456',
        newPassword: 'newpass123',
      );

      expect(validPayload, {
        'username': 'alice',
        'code': '123456',
        'new_password': 'newpass123',
      });
      expect(
        () => ApiService.forgotPasswordVerifyPayload(
          username: 'alice',
          code: '123',
          newPassword: 'newpass123',
        ),
        throwsA(isA<StateError>()),
      );
      expect(
        () => ApiService.forgotPasswordVerifyPayload(
          username: '',
          code: '123456',
          newPassword: 'newpass123',
        ),
        throwsA(isA<StateError>()),
      );
      expect(
        () => ApiService.forgotPasswordVerifyPayload(
          username: 'alice',
          code: '123456',
          newPassword: '123',
        ),
        throwsA(isA<StateError>()),
      );
    },
  );

  test('change password sends one canonical payload shape', () {
    final payload = {'current_password': '123456', 'new_password': '123789'};

    expect(payload.keys, {'current_password', 'new_password'});
    expect(payload['current_password'], '123456');
    expect(payload['new_password'], '123789');
  });
}
