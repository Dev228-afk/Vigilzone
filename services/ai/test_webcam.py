import cv2
import os
import time

def test_webcam(index=0):
    print(f"Testing webcam index {index}...")
    if os.name == 'nt':
        print("Detected Windows, using CAP_DSHOW...")
        cap = cv2.VideoCapture(index, cv2.CAP_DSHOW)
    else:
        cap = cv2.VideoCapture(index)
    
    if not cap.isOpened():
        print(f"Failed to open webcam index {index}")
        return False
    
    print("Webcam opened. Reading 5 frames...")
    for i in range(5):
        ret, frame = cap.read()
        if ret:
            print(f"Frame {i} read successfully: {frame.shape}")
        else:
            print(f"Frame {i} read failed.")
        time.sleep(0.5)
    
    cap.release()
    print("Testing complete.")
    return True

if __name__ == "__main__":
    test_webcam(0)
    test_webcam(1)
