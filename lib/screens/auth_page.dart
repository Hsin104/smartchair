import 'package:flutter/material.dart';
import '../services/api_service.dart';

enum AuthMode { login, register }

class AuthPage extends StatefulWidget {
  const AuthPage({super.key, required this.initialMode});

  final AuthMode initialMode;

  @override
  State<AuthPage> createState() => _AuthPageState();
}

class _AuthPageState extends State<AuthPage> {
  final _formKey = GlobalKey<FormState>();
  final _usernameController = TextEditingController();
  final _emailController = TextEditingController();
  final _passwordController = TextEditingController();
  final _confirmPasswordController = TextEditingController();

  late AuthMode _mode;
  bool _isSubmitting = false;
  bool _obscurePassword = true;
  bool _obscureConfirmPassword = true;

  @override
  void initState() {
    super.initState();
    _mode = widget.initialMode;
  }

  @override
  void dispose() {
    _usernameController.dispose();
    _emailController.dispose();
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

    setState(() => _isSubmitting = true);

    final result = _mode == AuthMode.login
        ? await ApiService.login(
            _usernameController.text.trim(),
            _passwordController.text,
          )
        : await ApiService.register(
            _usernameController.text.trim(),
            _emailController.text.trim(),
            _passwordController.text,
          );

    if (!mounted) return;

    setState(() => _isSubmitting = false);

    if (result.success) {
      Navigator.of(context).pop(result.email);
    } else {
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(SnackBar(content: Text(result.message)));
    }
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
                        decoration: const InputDecoration(
                          labelText: '帳號',
                          border: OutlineInputBorder(),
                        ),
                        validator: (v) =>
                            (v ?? '').trim().isEmpty ? '請輸入帳號' : null,
                      ),
                      const SizedBox(height: 12),

                      // Email（只有註冊需要）
                      if (_mode == AuthMode.register) ...[
                        TextFormField(
                          controller: _emailController,
                          keyboardType: TextInputType.emailAddress,
                          decoration: const InputDecoration(
                            labelText: 'Email',
                            border: OutlineInputBorder(),
                          ),
                          validator: (v) {
                            final text = (v ?? '').trim();
                            if (text.isEmpty) return '請輸入 Email';
                            if (!text.contains('@')) return '請輸入有效 Email';
                            return null;
                          },
                        ),
                        const SizedBox(height: 12),
                      ],

                      // 密碼
                      TextFormField(
                        controller: _passwordController,
                        obscureText: _obscurePassword,
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
