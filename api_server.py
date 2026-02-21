"""
Minimal FastAPI server for CCTV AI Module
Endpoints:
  GET /         - HTML interface with live frame and alerts
  GET /frame    - Latest JPEG frame
  GET /alerts   - Last 50 alerts
"""

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from datetime import datetime
import threading
from collections import deque
import io

# ============================================================================
# Pydantic Models (Alert Schema)
# ============================================================================

class Evidence(BaseModel):
    keyframe_path: str
    clip_path: str


class Alert(BaseModel):
    type: str  # INTRUSION|FIRE_SMOKE|VIOLENCE|UNKNOWN_SEVERE_ANOMALY
    severity: str  # HIGH|MED
    confidence: float
    bbox: List[float]  # [x, y, w, h]
    track_id: Optional[str] = None
    evidence: Evidence


class Debug(BaseModel):
    vad_score: float
    detector: str
    fps: float


class AlertEvent(BaseModel):
    camera_id: str
    ts: str  # ISO 8601 timestamp
    alerts: List[Alert]
    debug: Debug


# ============================================================================
# Thread-Safe In-Memory Store
# ============================================================================

class InMemoryStore:
    """Thread-safe storage for frames and alerts"""
    
    def __init__(self, max_alerts: int = 50):
        self._lock = threading.Lock()
        self._latest_frame: Optional[bytes] = None
        self._alerts: deque = deque(maxlen=max_alerts)
    
    def set_frame(self, frame_bytes: bytes):
        """Store latest JPEG frame"""
        with self._lock:
            self._latest_frame = frame_bytes
    
    def get_frame(self) -> Optional[bytes]:
        """Retrieve latest JPEG frame"""
        with self._lock:
            return self._latest_frame
    
    def add_alert(self, alert: AlertEvent):
        """Add a new alert (auto-evicts oldest if > max_alerts)"""
        with self._lock:
            self._alerts.append(alert.model_dump())
    
    def get_alerts(self) -> List[Dict[str, Any]]:
        """Retrieve all stored alerts (up to 50)"""
        with self._lock:
            return list(self._alerts)


# ============================================================================
# FastAPI App
# ============================================================================

app = FastAPI(title="CCTV AI Module API", version="1.0.0")
store = InMemoryStore(max_alerts=50)


@app.get("/", response_class=HTMLResponse)
async def index():
    """Minimal HTML interface with live frame display and alert updates"""
    html_content = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CCTV AI Module</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background: #1a1a1a;
            color: #e0e0e0;
            padding: 20px;
        }
        .container {
            max-width: 1400px;
            margin: 0 auto;
        }
        h1 {
            color: #4CAF50;
            margin-bottom: 20px;
            font-size: 28px;
        }
        .grid {
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }
        .panel {
            background: #2a2a2a;
            border-radius: 8px;
            padding: 20px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        .panel h2 {
            color: #64B5F6;
            margin-bottom: 15px;
            font-size: 20px;
        }
        #frame {
            width: 100%;
            height: auto;
            border-radius: 4px;
            background: #1a1a1a;
            min-height: 300px;
        }
        .no-frame {
            display: flex;
            align-items: center;
            justify-content: center;
            min-height: 300px;
            color: #666;
            font-size: 16px;
        }
        .alert-list {
            max-height: 600px;
            overflow-y: auto;
        }
        .alert-item {
            background: #333;
            border-left: 4px solid #FF5722;
            padding: 12px;
            margin-bottom: 10px;
            border-radius: 4px;
            font-size: 13px;
        }
        .alert-item.HIGH {
            border-left-color: #F44336;
        }
        .alert-item.MED {
            border-left-color: #FF9800;
        }
        .alert-header {
            display: flex;
            justify-content: space-between;
            margin-bottom: 8px;
            font-weight: bold;
        }
        .alert-type {
            color: #FF5722;
            font-size: 14px;
        }
        .alert-time {
            color: #999;
            font-size: 12px;
        }
        .alert-details {
            color: #bbb;
            line-height: 1.6;
        }
        .status {
            display: inline-block;
            padding: 3px 8px;
            border-radius: 3px;
            font-size: 11px;
            font-weight: bold;
            text-transform: uppercase;
        }
        .status.HIGH {
            background: #F44336;
            color: white;
        }
        .status.MED {
            background: #FF9800;
            color: white;
        }
        .no-alerts {
            text-align: center;
            color: #666;
            padding: 40px;
        }
        @media (max-width: 968px) {
            .grid {
                grid-template-columns: 1fr;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>Inference Module</h1>
        <div class="grid">
            <div class="panel">
                <h2> Live Frame</h2>
                <img id="frame" src="/frame" alt="Live Frame" onerror="this.style.display='none'; document.getElementById('no-frame-msg').style.display='flex';">
                <div id="no-frame-msg" class="no-frame" style="display:none;">No frame available</div>
            </div>
            <div class="panel">
                <h2>Recent Alerts (Last 50)</h2>
                <div class="alert-list" id="alerts">
                    <div class="no-alerts">No alerts yet</div>
                </div>
            </div>
        </div>
    </div>

    <script>
        // Update frame every second
        setInterval(() => {
            const img = document.getElementById('frame');
            img.src = '/frame?t=' + new Date().getTime();
        }, 1000);

        // Update alerts every second
        async function updateAlerts() {
            try {
                const response = await fetch('/alerts');
                const alerts = await response.json();
                
                const alertsContainer = document.getElementById('alerts');
                
                if (alerts.length === 0) {
                    alertsContainer.innerHTML = '<div class="no-alerts">No alerts yet</div>';
                    return;
                }
                
                alertsContainer.innerHTML = alerts.reverse().map(event => {
                    const time = new Date(event.ts).toLocaleString();
                    const alertsHtml = event.alerts.map(alert => `
                        <div class="alert-item ${alert.severity}">
                            <div class="alert-header">
                                <span class="alert-type">${alert.type}</span>
                                <span class="status ${alert.severity}">${alert.severity}</span>
                            </div>
                            <div class="alert-details">
                                <div><strong>Camera:</strong> ${event.camera_id}</div>
                                <div><strong>Time:</strong> ${time}</div>
                                <div><strong>Confidence:</strong> ${(alert.confidence * 100).toFixed(1)}%</div>
                                <div><strong>BBox:</strong> [${alert.bbox.map(v => v.toFixed(1)).join(', ')}]</div>
                                ${alert.track_id ? `<div><strong>Track:</strong> ${alert.track_id}</div>` : ''}
                                <div><strong>Detector:</strong> ${event.debug.detector} @ ${event.debug.fps.toFixed(1)} FPS</div>
                            </div>
                        </div>
                    `).join('');
                    return alertsHtml;
                }).join('');
            } catch (error) {
                console.error('Error fetching alerts:', error);
            }
        }
        
        // Initial update and set interval
        updateAlerts();
        setInterval(updateAlerts, 1000);
    </script>
</body>
</html>
    """
    return HTMLResponse(content=html_content)


@app.get("/frame")
async def get_frame():
    """Return the latest JPEG frame"""
    frame_bytes = store.get_frame()
    
    if frame_bytes is None:
        # Return a 1x1 transparent pixel if no frame available
        return Response(
            content=b'\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xdb\x00C\x00\x08\x06\x06\x07\x06\x05\x08\x07\x07\x07\t\t\x08\n\x0c\x14\r\x0c\x0b\x0b\x0c\x19\x12\x13\x0f\x14\x1d\x1a\x1f\x1e\x1d\x1a\x1c\x1c $.\' ",#\x1c\x1c(7),01444\x1f\'9=82<.342\xff\xc0\x00\x0b\x08\x00\x01\x00\x01\x01\x01\x11\x00\xff\xc4\x00\x14\x00\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\t\xff\xc4\x00\x14\x10\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\xff\xda\x00\x08\x01\x01\x00\x00?\x00T\xff\xd9',
            media_type="image/jpeg"
        )
    
    return Response(content=frame_bytes, media_type="image/jpeg")


@app.get("/alerts", response_model=List[AlertEvent])
async def get_alerts():
    """Return the last 50 alerts"""
    return store.get_alerts()


@app.post("/alerts")
async def post_alert(alert: AlertEvent):
    """
    Internal endpoint to add a new alert
    (Used by the AI detection module)
    """
    store.add_alert(alert)
    return {"status": "ok", "message": "Alert added"}


@app.post("/frame")
async def post_frame(frame: bytes):
    """
    Internal endpoint to update the latest frame
    (Used by the frame ingestion module)
    """
    store.set_frame(frame)
    return {"status": "ok", "message": "Frame updated"}


# ============================================================================
# Development/Testing Utilities
# ============================================================================

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "alerts_count": len(store.get_alerts())
    }


if __name__ == "__main__":
    import uvicorn
    print("🚀 Starting CCTV AI Module API Server...")
    print("📍 Dashboard: http://localhost:8000")
    print("📍 Frame endpoint: http://localhost:8000/frame")
    print("📍 Alerts endpoint: http://localhost:8000/alerts")
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="info")
