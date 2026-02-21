# FastAPI CCTV AI Module

Minimal FastAPI server with live frame display and alert monitoring.

## Features

- **GET `/`** - HTML dashboard with live frame and real-time alerts
- **GET `/frame`** - Returns latest JPEG frame
- **GET `/alerts`** - Returns last 50 alert JSON objects
- **POST `/frame`** - Internal endpoint to update frame (for AI module)
- **POST `/alerts`** - Internal endpoint to add alert (for AI module)
- **GET `/health`** - Health check endpoint

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements_api.txt
```

Or install manually:
```bash
pip install fastapi uvicorn pydantic
```

### 2. Start the Server

```bash
python api_server.py
```

The server will start on `http://localhost:8000`

### 3. Test with Simulated Data

In a separate terminal:
```bash
pip install opencv-python numpy requests
python test_api.py
```

This will generate simulated frames and alerts to test the interface.

### 4. Open Dashboard

Open your browser to: **http://localhost:8000**

You'll see:
- Live frame updating every second
- Alert list updating every second
- Alert severity badges (HIGH/MED)
- Full alert details with timestamps

## API Endpoints

### `GET /`
Returns HTML dashboard with:
- Live frame display (updates every 1 second)
- Alert list (updates every 1 second)
- Responsive design

### `GET /frame`
Returns the latest JPEG frame as `image/jpeg`

**Response:** Binary JPEG data

### `GET /alerts`
Returns array of last 50 alerts

**Response:**
```json
[
  {
    "camera_id": "cam01",
    "ts": "2026-02-12T10:15:30.123Z",
    "alerts": [
      {
        "type": "INTRUSION",
        "severity": "HIGH",
        "confidence": 0.95,
        "bbox": [100.0, 150.0, 80.0, 120.0],
        "track_id": "track_123",
        "evidence": {
          "keyframe_path": "path/to/frame.jpg",
          "clip_path": "path/to/clip.mp4"
        }
      }
    ],
    "debug": {
      "vad_score": 0.87,
      "detector": "yolov8",
      "fps": 25.5
    }
  }
]
```

### `POST /frame`
Update the latest frame (internal use)

**Body:** Binary JPEG data

### `POST /alerts`
Add a new alert (internal use)

**Body:** AlertEvent JSON matching schema

## Alert Schema

```json
{
  "camera_id": "cam01",
  "ts": "2026-02-12T10:15:30.123Z",
  "alerts": [
    {
      "type": "INTRUSION|FIRE_SMOKE|VIOLENCE|UNKNOWN_SEVERE_ANOMALY",
      "severity": "HIGH|MED",
      "confidence": 0.95,
      "bbox": [x, y, w, h],
      "track_id": "optional",
      "evidence": {
        "keyframe_path": "path/to.jpg",
        "clip_path": "path/to.mp4"
      }
    }
  ],
  "debug": {
    "vad_score": 0.87,
    "detector": "yolov8/rt-detr",
    "fps": 25.5
  }
}
```

## Architecture

- **Thread-safe storage**: Uses `threading.Lock()` for concurrent access
- **In-memory only**: No database required
- **Circular buffer**: Automatically keeps last 50 alerts
- **Real-time updates**: JavaScript polls every second

## Integration with AI Module

Your detection pipeline should:

1. **Send frames** to `POST /frame` with JPEG bytes
2. **Send alerts** to `POST /alerts` with AlertEvent JSON

Example:
```python
import requests
import cv2

# Send frame
_, jpeg = cv2.imencode('.jpg', frame)
requests.post('http://localhost:8000/frame', data=jpeg.tobytes())

# Send alert
alert = {
    "camera_id": "cam01",
    "ts": "2026-02-12T10:15:30.123Z",
    "alerts": [...],
    "debug": {...}
}
requests.post('http://localhost:8000/alerts', json=alert)
```

## Production Considerations

For production use, consider:
- Adding authentication/API keys
- Using a proper database (PostgreSQL, MongoDB)
- Adding WebSocket for real-time push updates
- Implementing rate limiting
- Adding CORS middleware if needed
- Using HTTPS/TLS
- Adding logging and monitoring
- Implementing alert persistence

## License

MIT
