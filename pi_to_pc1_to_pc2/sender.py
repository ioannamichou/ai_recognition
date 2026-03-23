import cv2
import socket
import struct
import time

# Ρυθμίσεις - Βάλε την IP του Laptop (PC 1)
PC1_IP = '192.168.10.104' 
PORT = 5005

client_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
client_socket.connect((PC1_IP, PORT))

cap = cv2.VideoCapture(0)
cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)

target_fps = 20 
frame_delay = 1.0 / target_fps
total_frames_to_send = 650  # 600 θέλει το PC + 50 για αέρα ασφαλείας
frames_sent = 0

print(f"Drone: Έναρξη αποστολής {total_frames_to_send} frames (Ελαφριά έκδοση)...")

try:
    while frames_sent < total_frames_to_send:
        t1 = time.time()
        ret, frame = cap.read()
        if not ret: break

        # Συμπίεση JPEG και μετατροπή σε bytes (Χωρίς pickle)
        result, encoded_frame = cv2.imencode('.jpg', frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
        data = encoded_frame.tobytes()
        size = len(data)

        # Αποστολή
        client_socket.sendall(struct.pack(">L", size) + data)
        frames_sent += 1

        # Έλεγχος ταχύτητας
        elapsed = time.time() - t1
        if elapsed < frame_delay:
            time.sleep(frame_delay - elapsed)

except Exception as e:
    print(f"Σφάλμα: {e}")
finally:
    time.sleep(2) 
    cap.release()
    client_socket.close()
    print("Μετάδοση ολοκληρώθηκε με επιτυχία.")