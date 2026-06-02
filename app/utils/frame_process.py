from datetime import datetime

import cv2

def process_frame(frame):
    # Resize frame to 640x360 so payload size stays predictable.
    frame = cv2.resize(frame, (640, 360))

    # Draw timestamp text on the processed frame.
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cv2.putText(
        frame,
        timestamp,
        (10, 30),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.7,
        (0, 0, 0),
        2,
        cv2.LINE_AA
    )

    return frame


def compress_frame(frame, quality=45):
    # Encode frame as JPEG with cv2.imencode using `quality`.
    ok, encoded = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), quality])
    # TODO-A4: Return encoded bytes, or None if encoding fails.
    if not ok:
        return None

    return encoded.tobytes()
