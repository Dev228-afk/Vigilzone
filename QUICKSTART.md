# Quick Start Guide - CCTV AI Module

## Windows 10 - 5 Minute Setup

### Step 1: Install Prerequisites

1. **Python 3.9+**
   - Download: https://www.python.org/downloads/
   - ✅ Check "Add Python to PATH" during installation

2. **FFmpeg** (for video processing)
   - Download: https://ffmpeg.org/download.html
   - Extract and add `bin/` folder to system PATH
   - Verify: Open PowerShell and type `ffmpeg -version`

3. **PyTorch**
   ```powershell
   # CPU version (recommended for testing)
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu
   
   # OR CUDA version (if you have NVIDIA GPU)
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu118
   ```

### Step 2: Install AI Module

```powershell
cd ai_module
pip install -r requirements.txt
```

### Step 3: Configure (Optional - defaults work out of the box)

Edit `configs/cameras.yaml` to add your RTSP cameras or use test video file:

```yaml
cameras:
  - camera_id: test_cam
    rtsp_url: "test_video.mp4"  # Use local video for testing
    ingest_backend: opencv
    sample_hz: 2
    enabled_lanes: [person_zone, fire_smoke]
    cooldown_s: 45
    k_of_n: [3, 5]
```

### Step 4: Run

**Option A - Double-click batch file:**
```
run_ai_module.bat
```

**Option B - Command line:**
```powershell
python -m src.app
```

### Step 5: Open Web UI

Open browser: **http://127.0.0.1:8000**

You should see:
- 📹 Real-time camera status
- 🚨 Alert monitoring dashboard
- 📊 System statistics

---

## Test Without RTSP Cameras

To test the system without real RTSP cameras:

1. Download a test video or use any MP4 file
2. Update `configs/cameras.yaml`:
   ```yaml
   rtsp_url: "C:/path/to/your/video.mp4"
   ```
3. Run the system

The AI will detect persons, motion, and trigger test alerts.

---

## Verify Installation

```powershell
# Check Python
python --version

# Check PyTorch
python -c "import torch; print('PyTorch:', torch.__version__); print('CUDA:', torch.cuda.is_available())"

# Check FFmpeg
ffmpeg -version

# Check dependencies
python -c "import fastapi, ultralytics, cv2; print('All dependencies OK')"
```

---

## Common Issues

**1. "Module not found"**
- Make sure you're in the `ai_module` directory
- Run: `pip install -r requirements.txt`

**2. "FFmpeg not found"**
- Install FFmpeg and add to PATH
- Restart terminal/PowerShell after installation

**3. "Model weights not found"**
- The system will automatically use yolov8n.pt from parent directory
- Make sure yolov8n.pt exists in the parent folder (yolov12-cls/)

**4. Port 8000 in use**
- Edit `src/app.py` line with `AlertServer(port=8080)` to use different port

---

## What Happens When You Run?

1. ✅ System loads configurations
2. ✅ Initializes YOLO models
3. ✅ Starts video ingestion (RTSP/file)
4. ✅ Begins detection on enabled lanes
5. ✅ Launches web server on port 8000
6. 🔴 Prints status every 30 seconds

You'll see:
```
🚀 Starting CCTV AI Module
✅ Started processor for test_cam
✅ System started successfully
🌐 Web UI: http://127.0.0.1:8000
```

---

## Next Steps

1. **Add Real Cameras**: Update `cameras.yaml` with RTSP URLs
2. **Define Zones**: Edit `zones.yaml` with restricted area polygons
3. **Tune Detection**: Adjust confidence thresholds in `models.yaml`
4. **Review Evidence**: Check `evidence/` folder for keyframes and clips
5. **Check Logs**: View `alerts/alerts.jsonl` for all alerts

---

## Need Help?

- Check `README.md` for detailed documentation
- Review configuration files in `configs/`
- Check console output for error messages
- Verify all prerequisites are installed

---

**🎉 You're ready to monitor your CCTV cameras with AI!**
