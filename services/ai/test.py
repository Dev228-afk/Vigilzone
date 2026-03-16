import asyncio
import json
import logging
from aiohttp import web
from aiortc import RTCPeerConnection, RTCSessionDescription
from aiortc.contrib.media import MediaPlayer

# --- CONFIGURATION ---
# Change to your RTSP URL when ready (e.g., "rtsp://user:pass@192.168.1.100/stream")
# Leave as 0 to test with your local webcam.
VIDEO_SOURCE = 0 
# ---------------------

# The HTML and JavaScript that will be sent to your web browser
HTML_CONTENT = """
<!DOCTYPE html>
<html>
<head>
    <title>Live CCTV - WebRTC</title>
    <style>
        body { font-family: sans-serif; text-align: center; background: #f4f4f9; padding: 20px; }
        video { background: black; max-width: 800px; width: 100%; border-radius: 8px; box-shadow: 0 4px 8px rgba(0,0,0,0.2); }
    </style>
</head>
<body>
    <h2>Live WebRTC Stream</h2>
    <video id="video" autoplay playsinline controls></video>

    <script>
        const pc = new RTCPeerConnection();

        // When the browser receives the video track, attach it to the <video> element
        pc.addEventListener('track', function(evt) {
            if (evt.track.kind == 'video') {
                document.getElementById('video').srcObject = evt.streams[0];
            }
        });

        // Setup the connection
        async function start() {
            const offer = await pc.createOffer({ offerToReceiveVideo: true });
            await pc.setLocalDescription(offer);

            // Send the offer to our Python server
            const response = await fetch('/offer', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    sdp: pc.localDescription.sdp,
                    type: pc.localDescription.type
                })
            });

            // Get the answer from Python and apply it
            const answer = await response.json();
            await pc.setRemoteDescription(answer);
        }

        start();
    </script>
</body>
</html>
"""

async def index(request):
    """Serves the HTML page to the browser."""
    return web.Response(content_type='text/html', text=HTML_CONTENT)

async def offer(request):
    """Handles the WebRTC signaling."""
    params = await request.json()
    offer = RTCSessionDescription(sdp=params['sdp'], type=params['type'])

    pc = RTCPeerConnection()
    
    # Create a media player that reads from the camera/RTSP stream
    player = MediaPlayer(VIDEO_SOURCE)

    # Add the video track to the WebRTC connection
    if player.video:
        pc.addTrack(player.video)

    # Handle the SDP answer
    await pc.setRemoteDescription(offer)
    answer = await pc.createAnswer()
    await pc.setLocalDescription(answer)

    return web.Response(
        content_type='application/json',
        text=json.dumps({
            'sdp': pc.localDescription.sdp,
            'type': pc.localDescription.type
        })
    )

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    app = web.Application()
    app.router.add_get('/', index)
    app.router.add_post('/offer', offer)

    print("Starting WebRTC Server...")
    print("Open your browser and go to: http://localhost:8080")
    
    web.run_app(app, host='0.0.0.0', port=8085)