import 'package:flutter/material.dart';
import '../services/api_service.dart';

enum AuthMode { login, register }

enum _LoginErrorKind { unknown, username, password }

class AuthPage extends StatefulWidget {
  const AuthPage({super.key, required this.initialMode});

  final AuthMode initialMode;

  static String usernameValidationMessage({
    required bool isRegisterMode,
    required bool usernameExists,
  }) {
    if (isRegisterMode && usernameExists) {
      return '此帳號已存在';
    }
    return '';
  }

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _emailController = TextEditingController();
  final _forgotPasswordEmailController = TextEditingController();
  final _forgotPasswordUsernameController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  late AuthMode _mode;
  bool _isSubmitting = false;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;
  String _usernameServerError = '';
  String _passwordServerError = '';

  @override
  void initState() {
    super.initState();
    _mode = widget.initialMode;
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _emailController.dispose();
    _forgotPasswordEmailController.dispose();
    _forgotPasswordUsernameController.dispose();
    _passwordController.dispose();
    _confirmPasswordController.dispose();
    super.dispose();
  }

  String get _title => _mode == AuthMode.login ? '登入' : '註冊';
  String get _headline => _mode == AuthMode.login ? '歡迎回來' : '建立帳號';
  String get _subtitle =>
      _mode == AuthMode.login ? '登入後即可查看你的智慧座椅資料' : '註冊後即可開始使用完整功能';

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;

    final username = _usernameController.text.trim();

    if (_mode == AuthMode.login) {
      final usernameExists = await ApiService.usernameExists(username);
      if (!usernameExists) {
        if (!mounted) return;
        setState(() {
          _usernameServerError = '無此帳戶，請去註冊';
          _passwordServerError = '';
          _isSubmitting = false;
        });
        return;
      }
    } else {
      final usernameExists = await ApiService.usernameExists(username);
      if (usernameExists) {
        if (!mounted) return;
        setState(() {
          _usernameServerError = AuthPage.usernameValidationMessage(
            isRegisterMode: true,
            usernameExists: true,
          );
          _passwordServerError = '';
          _isSubmitting = false;
        });
        return;
      }
    }

    setState(() {
      _isSubmitting = true;
      _usernameServerError = '';
      _passwordServerError = '';
    });

    final result = _mode == AuthMode.login
        ? await ApiService.login(username, _passwordController.text)
        : await ApiService.register(
            username,
            _emailController.text.trim(),
            _passwordController.text,
          );

    if (!mounted) return;

    setState(() => _isSubmitting = false);

    if (result.success) {
      Navigator.of(context).pop(result.email);
    } else {
      if (_mode == AuthMode.login) {
        final errorCode = result.errorCode?.toUpperCase();
        final authError = errorCode == 'USER_NOT_FOUND'
            ? _LoginErrorKind.username
            : errorCode == 'INVALID_PASSWORD'
            ? _LoginErrorKind.password
            : _classifyLoginError(result.message);
        setState(() {
          _usernameServerError = authError == _LoginErrorKind.username
              ? '無此帳戶，請去註冊'
              : '';
          _passwordServerError = authError == _LoginErrorKind.password
              ? '密碼錯誤'
              : '';
        });
      } else if ((result.errorCode?.toUpperCase() ?? '') == 'ACCOUNT_EXISTS') {
        setState(() {
          _usernameServerError = AuthPage.usernameValidationMessage(
            isRegisterMode: true,
            usernameExists: true,
          );
          _passwordServerError = '';
        });
      } else {
        ScaffoldMessenger.of(
          context,
        ).showSnackBar(SnackBar(content: Text(result.message)));
      }
    }
  }

  Future<void> _showForgotPasswordDialog() async {
    _forgotPasswordEmailController.text = _emailController.text.trim();
    _forgotPasswordUsernameController.text = _usernameController.text.trim();

    final submitted = await showDialog<bool>(
      context: context,
      builder: (dialogContext) {
        return AlertDialog(
          title: const Text('忘記密碼'),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const Text('請同時輸入註冊時使用的電子郵件與使用者名稱，兩者都正確才可送出重設密碼請求。'),
              const SizedBox(height: 16),
              TextField(
                controller: _forgotPasswordEmailController,
                keyboardType: TextInputType.emailAddress,
                decoration: const InputDecoration(
                  labelText: '電子郵件',
                  border: OutlineInputBorder(),
                ),
              ),
              const SizedBox(height: 12),
              TextField(
                controller: _forgotPasswordUsernameController,
                decoration: const InputDecoration(
                  labelText: '使用者名稱',
                  border: OutlineInputBorder(),
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () => Navigator.of(dialogContext).pop(false),
              child: const Text('取消'),
            ),
            FilledButton(
              onPressed: () => Navigator.of(dialogContext).pop(true),
              child: const Text('送出請求'),
            ),
          ],
        );
      },
    );

    if (submitted != true || !mounted) {
      return;
    }

    final result = await ApiService.requestPasswordReset(
      _forgotPasswordUsernameController.text,
      _forgotPasswordEmailController.text,
    );

    if (!mounted) return;

    ScaffoldMessenger.of(
      context,
    ).showSnackBar(SnackBar(content: Text(result.message)));
  }

  _LoginErrorKind _classifyLoginError(String message) {
    final normalized = message.toLowerCase();
    if (normalized.contains('無此帳戶') ||
        normalized.contains('無此帳號') ||
        normalized.contains('不存在') ||
        normalized.contains('not found') ||
        normalized.contains('no such user') ||
        normalized.contains('user does not exist') ||
        normalized.contains('unknown account')) {
      return _LoginErrorKind.username;
    }

    if (normalized.contains('密碼') ||
        normalized.contains('password') ||
        normalized.contains('帳號或密碼錯誤') ||
        normalized.contains('invalid credentials') ||
        normalized.contains('authentication failed') ||
        normalized.contains('wrong password') ||
        normalized.contains('incorrect password') ||
        normalized.contains('帳號錯誤')) {
      return _LoginErrorKind.password;
    }

    return _LoginErrorKind.unknown;
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(
        title: Text(
          _title,
          style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w700),
        ),
        centerTitle: true,
      ),
      body: Center(
        child: SingleChildScrollView(
          padding: const EdgeInsets.all(20),
          child: ConstrainedBox(
            constraints: const BoxConstraints(maxWidth: 460),
            child: Card(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Form(
                  key: _formKey,
                  child: Column(
                    mainAxisSize: MainAxisSize.min,
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      // 標題列
                      Row(
                        children: [
                          Container(
                            width: 8,
                            height: 44,
                            decoration: BoxDecoration(
                              color: Theme.of(context).primaryColor,
                              borderRadius: BorderRadius.circular(6),
                            ),
                          ),
                          const SizedBox(width: 12),
                          Expanded(
                            child: Text(
                              _title,
                              style: const TextStyle(
                                fontSize: 30,
                                fontWeight: FontWeight.w800,
                                height: 1.1,
                              ),
                            ),
                          ),
                        ],
                      ),
                      const SizedBox(height: 12),
                      Text(
                        _headline,
                        style: const TextStyle(
                          fontSize: 21,
                          fontWeight: FontWeight.w700,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        _subtitle,
                        style: const TextStyle(
                          fontSize: 14,
                          color: Colors.black54,
                        ),
                      ),
                      const SizedBox(height: 16),

                      // 帳號（登入 & 註冊都需要）
                      TextFormField(
                        controller: _usernameController,
                        onChanged: (_) {
                          if (_usernameServerError.isNotEmpty) {
                            setState(() => _usernameServerError = '');
                          }
                        },
                        decoration: const InputDecoration(
                          labelText: '帳號',
                          border: OutlineInputBorder(),
                        ),
                        validator: (v) =>
                            (v ?? '').trim().isEmpty ? '請輸入帳號' : null,
                      ),
                      if (_usernameServerError.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        Padding(
                          padding: const EdgeInsets.only(left: 4),
                          child: Text(
                            _usernameServerError,
                            style: const TextStyle(
                              color: Colors.red,
                              fontSize: 16,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                      ],
                      const SizedBox(height: 12),

                      // Email（只有註冊需要）
                      if (_mode == AuthMode.register) ...[
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          decoration: const InputDecoration(
                            labelText: '電子郵件',
                            border: OutlineInputBorder(),
                          ),
                          validator: (v) {
                            final text = (v ?? '').trim();
                            if (text.isEmpty) return '請輸入電子郵件';
                            if (!text.contains('@')) return '請輸入有效電子郵件';
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                      ],

                      // 密碼
                      TextFormField(
                        controller: _passwordController,
                        obscureText: _obscurePassword,
                        onChanged: (_) {
                          if (_passwordServerError.isNotEmpty) {
                            setState(() => _passwordServerError = '');
                          }
                        },
                        decoration: InputDecoration(
                          labelText: '密碼',
                          border: const OutlineInputBorder(),
                          suffixIcon: IconButton(
                            icon: Icon(
                              _obscurePassword
                                  ? Icons.visibility_off
                                  : Icons.visibility,
                            ),
                            onPressed: () => setState(() {
                              _obscurePassword = !_obscurePassword;
                            }),
                          ),
                        ),
                        validator: (v) {
                          final text = v ?? '';
                          if (text.isEmpty) return '請輸入密碼';
                          if (_mode == AuthMode.register && text.length < 6) {
                            return '密碼至少需要 6 碼';
                          }
                          return null;
                        },
                      ),
                      if (_passwordServerError.isNotEmpty) ...[
                        const SizedBox(height: 6),
                        const Padding(
                          padding: EdgeInsets.only(left: 4),
                          child: Text(
                            '密碼錯誤',
                            style: TextStyle(
                              color: Colors.red,
                              fontSize: 14,
                              fontWeight: FontWeight.w700,
                            ),
                          ),
                        ),
                      ],
                      if (_mode == AuthMode.login) ...[
                        const SizedBox(height: 4),
                        Align(
                          alignment: Alignment.centerRight,
                          child: TextButton(
                            onPressed: _isSubmitting
                                ? null
                                : _showForgotPasswordDialog,
                            child: const Text('忘記密碼？'),
                          ),
                        ),
                      ],
                      const SizedBox(height: 12),

                      // 密碼確認（只有註冊需要）
                      if (_mode == AuthMode.register) ...[
                        TextFormField(
                          controller: _confirmPasswordController,
                          obscureText: _obscureConfirmPassword,
                          decoration: InputDecoration(
                            labelText: '確認密碼',
                            border: const OutlineInputBorder(),
                            suffixIcon: IconButton(
                              icon: Icon(
                                _obscureConfirmPassword
                                    ? Icons.visibility_off
                                    : Icons.visibility,
                              ),
                              onPressed: () => setState(() {
                                _obscureConfirmPassword =
                                    !_obscureConfirmPassword;
                              }),
                            ),
                          ),
                          validator: (v) {
                            final text = v ?? '';
                            if (text.isEmpty) return '請再次輸入密碼';
                            if (text != _passwordController.text) {
                              return '密碼不相符';
                            }
                            return null;
                          },
                        ),
                        const SizedBox(height: 16),
                      ] else
                        const SizedBox(height: 16),

                      SizedBox(
                        width: double.infinity,
                        child: ElevatedButton(
                          onPressed: _isSubmitting ? null : _submit,
                          child: Text(_isSubmitting ? '處理中...' : _title),
                        ),
                      ),
                      const SizedBox(height: 8),
                      Align(
                        alignment: Alignment.center,
                        child: TextButton(
                          onPressed: _isSubmitting
                              ? null
                              : () => setState(() {
                                  _mode = _mode == AuthMode.login
                                      ? AuthMode.register
                                      : AuthMode.login;
                                  _usernameController.clear();
                                  _emailController.clear();
                                  _passwordController.clear();
                                  _confirmPasswordController.clear();
                                  // height/weight removed from registration
                                  _obscurePassword = true;
                                  _obscureConfirmPassword = true;
                                  _usernameServerError = '';
                                  _passwordServerError = '';
                                }),
                          child: Text(
                            _mode == AuthMode.login ? '沒有帳號？前往註冊' : '已有帳號？前往登入',
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
