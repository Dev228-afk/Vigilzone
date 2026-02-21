"""
Test script to simulate alerts and frames for the FastAPI server
Run this alongside the API server to see the interface in action
"""

import requests
import time
import random
from datetime import datetime, timezone
import numpy as np
import cv2

API_BASE = "http://localhost:8000"

# Alert types and severities
ALERT_TYPES = ["INTRUSION", "FIRE_SMOKE", "VIOLENCE", "UNKNOWN_SEVERE_ANOMALY"]
SEVERITIES = ["HIGH", "MED"]
DETECTORS = ["yolov8", "rt-detr", "yolov12"]


def generate_test_frame():
    """Generate a test JPEG frame with timestamp"""
    # Create a 640x480 frame with random color and timestamp
    frame = np.random.randint(30, 60, (480, 640, 3), dtype=np.uint8)
    
    # Add timestamp text
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(frame, f"CCTV Cam01 - {timestamp}", (10, 30), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
    
    # Add a moving rectangle to simulate activity
    x = int((time.time() % 10) / 10 * 540) + 50
    y = int((time.time() % 7) / 7 * 380) + 50
    cv2.rectangle(frame, (x, y), (x + 100, y + 100), (0, 0, 255), 2)
    cv2.putText(frame, "DETECTED", (x, y - 10), 
                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)
    
    # Encode to JPEG
    _, jpeg = cv2.imencode('.jpg', frame)
    return jpeg.tobytes()


def generate_test_alert():
    """Generate a test alert matching the schema"""
    alert_type = random.choice(ALERT_TYPES)
    severity = "HIGH" if alert_type in ["FIRE_SMOKE", "VIOLENCE"] else random.choice(SEVERITIES)
    
    alert = {
        "camera_id": "cam01",
        "ts": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "alerts": [
            {
                "type": alert_type,
                "severity": severity,
                "confidence": round(random.uniform(0.75, 0.98), 3),
                "bbox": [
                    round(random.uniform(50, 300), 1),
                    round(random.uniform(50, 200), 1),
                    round(random.uniform(50, 150), 1),
                    round(random.uniform(50, 150), 1)
                ],
                "track_id": f"track_{random.randint(100, 999)}" if random.random() > 0.3 else None,
                "evidence": {
                    "keyframe_path": f"local_db/evidence/{alert_type.lower()}_{int(time.time())}.jpg",
                    "clip_path": f"local_db/evidence/{alert_type.lower()}_{int(time.time())}.mp4"
                }
            }
        ],
        "debug": {
            "vad_score": round(random.uniform(0.5, 0.95), 3),
            "detector": random.choice(DETECTORS),
            "fps": round(random.uniform(15.0, 30.0), 1)
        }
    }
    return alert


def main():
    """Main test loop"""
    print("🧪 Starting API Test Client...")
    print(f"📍 Sending test data to: {API_BASE}")
    print("🌐 Open http://localhost:8000 in your browser")
    print("-" * 60)
    
    frame_count = 0
    alert_count = 0
    
    try:
        while True:
            # Send a frame every iteration (1 second)
            try:
                frame_bytes = generate_test_frame()
                response = requests.post(f"{API_BASE}/frame", data=frame_bytes)
                if response.status_code == 200:
                    frame_count += 1
                    print(f"✅ Frame {frame_count} sent")
            except Exception as e:
                print(f"❌ Error sending frame: {e}")
            
            # Send an alert randomly (about every 5-10 seconds)
            if random.random() < 0.15:
                try:
                    alert = generate_test_alert()
                    response = requests.post(f"{API_BASE}/alerts", json=alert)
                    if response.status_code == 200:
                        alert_count += 1
                        alert_type = alert["alerts"][0]["type"]
                        severity = alert["alerts"][0]["severity"]
                        print(f"🚨 Alert {alert_count} sent: {alert_type} [{severity}]")
                except Exception as e:
                    print(f"❌ Error sending alert: {e}")
            
            time.sleep(1)
            
    except KeyboardInterrupt:
        print(f"\n\n📊 Test Summary:")
        print(f"   Frames sent: {frame_count}")
        print(f"   Alerts sent: {alert_count}")
        print("👋 Test client stopped.")


if __name__ == "__main__":
    main()
