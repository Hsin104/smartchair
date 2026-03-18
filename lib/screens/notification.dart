import 'package:flutter/material.dart';

class NotificationPage extends StatelessWidget {
  const NotificationPage({super.key});

  final List<Map<String, dynamic>> notifications = const [
    {
      "title": "Poor posture detected",
      "time": "09:20 AM",
      "message": "You have been leaning forward for 10 minutes.",
      "icon": Icons.warning_amber_rounded,
      "color": Colors.red,
    },
    {
      "title": "Sitting too long",
      "time": "10:05 AM",
      "message": "You have been sitting continuously for 1 hour.",
      "icon": Icons.access_time,
      "color": Colors.orange,
    },
    {
      "title": "Posture corrected",
      "time": "10:15 AM",
      "message": "Your posture returned to normal.",
      "icon": Icons.check_circle,
      "color": Colors.green,
    },
    {
      "title": "Right lean detected",
      "time": "11:40 AM",
      "message": "Your body weight is leaning to the right side.",
      "icon": Icons.airline_seat_recline_normal,
      "color": Colors.deepOrange,
    },
    {
      "title": "Stretch reminder",
      "time": "01:30 PM",
      "message": "Please stand up and stretch your shoulders and neck.",
      "icon": Icons.self_improvement,
      "color": Colors.blue,
    },
  ];

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.grey[50],
      appBar: AppBar(
        title: const Text(
          "Notifications",
          style: TextStyle(fontWeight: FontWeight.bold),
        ),
        backgroundColor: Colors.white,
        foregroundColor: Colors.black,
        elevation: 0,
        centerTitle: true,
      ),
      body: ListView.builder(
        padding: const EdgeInsets.all(16),
        itemCount: notifications.length,
        itemBuilder: (context, index) {
          final item = notifications[index];

          return Container(
            margin: const EdgeInsets.only(bottom: 14),
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(18),
              boxShadow: [
                BoxShadow(
                  color: Colors.grey.withValues(alpha: 0.10),
                  blurRadius: 8,
                  offset: const Offset(0, 3),
                ),
              ],
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 48,
                  height: 48,
                  decoration: BoxDecoration(
                    color: (item["color"] as Color).withValues(alpha: 0.12),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Icon(
                    item["icon"] as IconData,
                    color: item["color"] as Color,
                    size: 26,
                  ),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        item["title"] as String,
                        style: const TextStyle(
                          fontSize: 17,
                          fontWeight: FontWeight.bold,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        item["message"] as String,
                        style: const TextStyle(
                          fontSize: 14,
                          color: Colors.black54,
                        ),
                      ),
                      const SizedBox(height: 8),
                      Text(
                        item["time"] as String,
                        style: const TextStyle(
                          fontSize: 13,
                          color: Colors.grey,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          );
        },
      ),
    );
  }
}
