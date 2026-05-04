import 'dart:math';

class MockApi {
  static final List<Map<String, dynamic>> _mockPostures = [
    {
      "posture": "姿勢正常",
      "score": 92,
      "risk": "低風險",
      "advice": "目前姿勢良好，請繼續維持。建議每 50 分鐘起身活動 5 分鐘。",
    },
    {
      "posture": "身體前傾",
      "score": 63,
      "risk": "高風險",
      "advice": "偵測到身體前傾，建議將背部貼近椅背，並進行收下巴運動。",
    },
    {
      "posture": "左側傾斜",
      "score": 70,
      "risk": "中風險",
      "advice": "偵測到重心偏左，建議調整骨盆位置，讓左右坐骨平均受力。",
    },
    {
      "posture": "右側傾斜",
      "score": 68,
      "risk": "中風險",
      "advice": "偵測到重心偏右，請重新坐正並放鬆肩膀。",
    },
    {
      "posture": "後仰過多",
      "score": 72,
      "risk": "中風險",
      "advice": "後仰角度過大，建議回到正常坐姿，讓腰部維持適當支撐。",
    },
    {
      "posture": "久坐過久",
      "score": 66,
      "risk": "高風險",
      "advice": "久坐過久，建議起身伸展 3 到 5 分鐘。",
    },
  ];

  static Future<Map<String, dynamic>> getPosture() async {
    await Future.delayed(const Duration(milliseconds: 600));

    final random = Random();
    return _mockPostures[random.nextInt(_mockPostures.length)];
  }
}
