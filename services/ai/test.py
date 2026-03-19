import cv2

def show_cctv_stream(url):
    # Initialize the video capture object with the stream URL
    cap = cv2.VideoCapture(url)

    # Check if the connection was successful
    if not cap.isOpened():
        print("Error: Could not open the CCTV stream. Please check the URL and network connection.")
        return

    print("Connecting to the stream... Press 'q' to exit.")

    while True:
        # Read a frame from the stream
        ret, frame = cap.read()

        # If the frame was not read successfully, break the loop
        if not ret:
            print("Error: Failed to grab a frame. The stream might have disconnected.")
            break

        # Display the resulting frame in a window
        cv2.imshow('Live CCTV Feed', frame)

        # Wait for 1 millisecond and check if the 'q' key is pressed to quit
        if cv2.waitKey(1) & 0xFF == ord('q'):
            print("Exiting stream...")
            break

    # Release the capture object and close all display windows
    cap.release()
    cv2.destroyAllWindows()

# --- Example Usage ---
# Replace this with your camera's actual RTSP or HTTP URL.
# stream_url = "http://195.196.36.242/mjpg/video.mjpg" 
# stream_url = "http://47.51.131.147/-wvhttp-01-/GetOneShot?image_size=1280x720&frame_count=1000000000" 
stream_url = "http://webcam.rhein-taunus-krematorium.de/mjpg/video.mjpg" 

show_cctv_stream(stream_url)