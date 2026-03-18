import 'package:flutter/material.dart';

class SettingPage extends StatefulWidget {
  const SettingPage({super.key});

  @override
  State<SettingPage> createState() => _SettingPageState();
}

class _SettingPageState extends State<SettingPage> {
  final TextEditingController heightController = TextEditingController(
    text: "165",
  );
  final TextEditingController weightController = TextEditingController(
    text: "55",
  );
  final TextEditingController chairHeightController = TextEditingController(
    text: "45",
  );

  bool postureAlert = true;
  bool sedentaryAlert = true;
  bool vibrationAlert = true;

  @override
  void dispose() {
    heightController.dispose();
    weightController.dispose();
    chairHeightController.dispose();
    super.dispose();
  }

  Widget buildTextField({
    required String label,
    required String unit,
    required TextEditingController controller,
    required IconData icon,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 14),
      child: TextField(
        controller: controller,
        keyboardType: TextInputType.number,
        decoration: InputDecoration(
          prefixIcon: Icon(icon),
          labelText: label,
          suffixText: unit,
          filled: true,
          fillColor: Colors.white,
          border: OutlineInputBorder(
            borderRadius: BorderRadius.circular(16),
            borderSide: BorderSide.none,
          ),
        ),
      ),
    );
  }

  Widget buildSwitchTile({
    required String title,
    required String subtitle,
    required bool value,
    required Function(bool) onChanged,
    required IconData icon,
  }) {
    return Container(
      margin: const EdgeInsets.only(bottom: 12),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(18),
      ),
      child: SwitchListTile(
        secondary: Icon(icon, color: Colors.blue),
        title: Text(title, style: const TextStyle(fontWeight: FontWeight.bold)),
        subtitle: Text(subtitle),
        value: value,
        onChanged: onChanged,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[50],
      appBar: AppBar(
        title: const Text(
          "Settings",
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black,
        elevation: 0,
        centerTitle: true,
      ),
      body: SingleChildScrollView(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              "User Profile",
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),

            buildTextField(
              label: "Height",
              unit: "cm",
              controller: heightController,
              icon: Icons.height,
            ),
            buildTextField(
              label: "Weight",
              unit: "kg",
              controller: weightController,
              icon: Icons.monitor_weight,
            ),
            buildTextField(
              label: "Chair Height",
              unit: "cm",
              controller: chairHeightController,
              icon: Icons.chair_alt,
            ),

            const SizedBox(height: 20),
            const Text(
              "Alert Settings",
              style: TextStyle(fontSize: 20, fontWeight: FontWeight.bold),
            ),
            const SizedBox(height: 12),

            buildSwitchTile(
              title: "Posture Alert",
              subtitle: "Notify when poor posture is detected",
              value: postureAlert,
              icon: Icons.warning_amber_rounded,
              onChanged: (value) {
                setState(() {
                  postureAlert = value;
                });
              },
            ),
            buildSwitchTile(
              title: "Sedentary Alert",
              subtitle: "Notify when sitting too long",
              value: sedentaryAlert,
              icon: Icons.access_time,
              onChanged: (value) {
                setState(() {
                  sedentaryAlert = value;
                });
              },
            ),
            buildSwitchTile(
              title: "Vibration Feedback",
              subtitle: "Enable chair vibration reminder",
              value: vibrationAlert,
              icon: Icons.vibration,
              onChanged: (value) {
                setState(() {
                  vibrationAlert = value;
                });
              },
            ),

            const SizedBox(height: 24),

            SizedBox(
              width: double.infinity,
              child: ElevatedButton(
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text("Calibration started")),
                  );
                },
                style: ElevatedButton.styleFrom(
                  backgroundColor: Colors.blue,
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                ),
                child: const Text(
                  "Start Initial Calibration",
                  style: TextStyle(fontSize: 16, color: Colors.white),
                ),
              ),
            ),

            const SizedBox(height: 12),

            SizedBox(
              width: double.infinity,
              child: OutlinedButton(
                onPressed: () {
                  ScaffoldMessenger.of(context).showSnackBar(
                    const SnackBar(content: Text("Settings saved")),
                  );
                },
                style: OutlinedButton.styleFrom(
                  padding: const EdgeInsets.symmetric(vertical: 16),
                  shape: RoundedRectangleBorder(
                    borderRadius: BorderRadius.circular(16),
                  ),
                ),
                child: const Text(
                  "Save Settings",
                  style: TextStyle(fontSize: 16),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
