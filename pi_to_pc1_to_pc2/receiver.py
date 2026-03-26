import socket
import cv2
import struct
import os
import numpy as np
from datetime import datetime

IP_LOCAL = '0.0.0.0'  
PORT_LOCAL = 5005     
SAVE_PATH = "/app"    

def start_receiver():
    if not os.path.exists(SAVE_PATH):
        os.makedirs(SAVE_PATH)

    server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server_socket.bind((IP_LOCAL, PORT_LOCAL))
    server_socket.listen(1)
    
    print(f"PC 1: Ο Σταθμός Βάσης είναι ενεργός (Θύρα {PORT_LOCAL}). Περιμένω το Drone...")

    #while True: 
    try:
        conn, addr = server_socket.accept()
        print(f"\n[+] Νέα σύνδεση από {addr}. Έναρξη καταγραφής 3x10s...")
            
        data = b""
        payload_size = struct.calcsize(">L")
        fps = 20.0  
        frames_per_clip = 200 

        for video_count in range(1, 4):
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f'drone_record_{timestamp}_part{video_count}.mp4'
            full_path = os.path.join(SAVE_PATH, filename)
                
            # Χρήση mp4v για εγγυημένη συμβατότητα σε Docker/Windows
            fourcc = cv2.VideoWriter_fourcc(*'mp4v') 
            out = cv2.VideoWriter(full_path, fourcc, fps, (640, 480))
                
            print(f"Καταγραφή στο αρχείο: {filename}...")
                
            frame_counter = 0
            try:
                while frame_counter < frames_per_clip:
                    # Λήψη μεγέθους πακέτου
                    while len(data) < payload_size:
                        packet = conn.recv(8192)
                        if not packet: break
                        data += packet
                    if len(data) < payload_size: break
                        
                    packed_size = data[:payload_size]
                    data = data[payload_size:]
                    msg_size = struct.unpack(">L", packed_size)[0]

                    # Λήψη δεδομένων εικόνας
                    while len(data) < msg_size:
                        packet = conn.recv(8192)
                        if not packet: break
                        data += packet
                    if len(data) < msg_size: break
                        
                    frame_data = data[:msg_size]
                    data = data[msg_size:]
                        
                    # Αποκωδικοποίηση και εγγραφή
                    frame_array = np.frombuffer(frame_data, dtype=np.uint8)
                    frame = cv2.imdecode(frame_array, cv2.IMREAD_COLOR)
                        
                    if frame is not None:
                        out.write(frame)
                        frame_counter += 1
            finally:
                # ΚΡΙΣΙΜΟ: Το αρχείο ΠΡΕΠΕΙ να κλείσει για να είναι έγκυρο το MP4
                out.release()
                print(f"✅ Part {video_count} ολοκληρώθηκε και 'κλείδωσε' στο δίσκο.")

        conn.close()
        print("--- Όλα τα βίντεο ελήφθησαν. Έτοιμα για αποστολή στο PC 2 ---")

        server_socket.close() # Κλείνουμε το socket
        return # Επιστρέφουμε από τη συνάρτηση για να τερματίσει το script

    except Exception as e:
        print(f"Σφάλμα επικοινωνίας: {e}")
        server_socket.close()

if __name__ == "__main__":
    start_receiver()