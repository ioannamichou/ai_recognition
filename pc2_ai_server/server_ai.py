import socket
import os
import time
import mysql.connector
from ultralytics import YOLO
import cv2
from datetime import datetime

# --- ΡΥΘΜΙΣΕΙΣ ΔΙΚΤΥΟΥ & ΑΠΟΘΗΚΕΥΣΗΣ ---
HOST = '0.0.0.0'
PORT = 5006
SAVE_DIR = '/app/ai_videos'
MODEL_PATH = 'yolov8n.pt'  # Θα κατεβεί αυτόματα την πρώτη φορά

# --- ΡΥΘΜΙΣΕΙΣ ΒΑΣΗΣ ΔΕΔΟΜΕΝΩΝ (MySQL) ---
DB_CONFIG = {
    'host': 'db',            # Το όνομα του MySQL container στο docker-compose
    'user': 'root',
    'password': 'root_password',
    'database': 'drone_ai_db'
}

# Δημιουργία φακέλου αν δεν υπάρχει
if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

# --- 1. ΣΥΝΔΕΣΗ ΚΑΙ ΑΡΧΙΚΟΠΟΙΗΣΗ ΒΑΣΗΣ ---
def init_db():
    print("🤖 AI Server: Προσπάθεια σύνδεσης στη βάση δεδομένων...", flush=True)
    attempt = 0
    while attempt < 5:
        try:
            conn = mysql.connector.connect(**DB_CONFIG)
            cursor = conn.cursor()
            
            # Δημιουργία πίνακα αν δεν υπάρχει
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS detections (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    video_name VARCHAR(255) NOT NULL,
                    object_class VARCHAR(100) NOT NULL,
                    confidence FLOAT NOT NULL,
                    timestamp DATETIME NOT NULL
                )
            """)
            conn.commit()
            print("✅ AI Server: Η βάση δεδομένων είναι έτοιμη.", flush=True)
            return conn, cursor
        except mysql.connector.Error as err:
            attempt += 1
            print(f"⚠️ Αποτυχία σύνδεσης στη βάση (Προσπάθεια {attempt}/5): {err}", flush=True)
            time.sleep(5) # Περιμένουμε να σηκωθεί η MySQL
    
    print("❌ Σφάλμα: Δεν ήταν δυνατή η σύνδεση στη βάση δεδομένων.", flush=True)
    exit(1)

# --- 2. ΣΥΝΑΡΤΗΣΗ ΑΝΑΛΥΣΗΣ YOLO ---
def run_yolo_on_video(video_path, db_conn, db_cursor):
    filename = os.path.basename(video_path)
    print(f"🧠 AI: Έναρξη ανάλυσης YOLO στο βίντεο: {filename}...", flush=True)
    
    try:
        # Φόρτωση μοντέλου (nano για ταχύτητα)
        model = YOLO(MODEL_PATH)
        
        # Άνοιγμα του βίντεο με OpenCV
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"❌ Σφάλμα: Αδυναμία ανοίγματος του βίντεο {filename}", flush=True)
            return

        frame_count = 0
        detections_found = 0
        
        # Ανάλυση frame-προς-frame
        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break
            
            frame_count += 1
            
            # Τρέχουμε το YOLO μόνο κάθε 5 frames για εξοικονόμηση πόρων (4 FPS AI)
            if frame_count % 5 != 0:
                continue

            # Εκτέλεση ανίχνευσης (conf=0.5 -> confidence > 50%)
            results = model(frame, conf=0.5, verbose=False)
            
            # Επεξεργασία αποτελεσμάτων
            current_time = datetime.now()
            
            for result in results:
                boxes = result.boxes
                for box in boxes:
                    # Παίρνουμε τα δεδομένα: Κλάση (όνομα) και Confidence
                    cls_id = int(box.cls[0])
                    cls_name = model.names[cls_id]
                    conf = float(box.conf[0])
                    
                    # INSERT στη βάση δεδομένων
                    try:
                        sql = "INSERT INTO detections (video_name, object_class, confidence, timestamp) VALUES (%s, %s, %s, %s)"
                        val = (filename, cls_name, conf, current_time)
                        db_cursor.execute(sql, val)
                        db_conn.commit()
                        detections_found += 1
                        print(f"🔍 [DETECTED] {cls_name} ({conf:.2f}) στο {filename}", flush=True)
                    except mysql.connector.Error as err:
                        print(f"❌ Σφάλμα MySQL Insert: {err}", flush=True)

        cap.release()
        print(f"✅ AI: Ολοκληρώθηκε η ανάλυση του {filename}. Βρέθηκαν {detections_found} αντικείμενα.", flush=True)
        
    except Exception as e:
        print(f"❌ Γενικό Σφάλμα κατά την ανάλυση AI: {e}", flush=True)

# --- 3. ΚΥΡΙΟΣ SERVER (ΔΕΚΤΗΣ ΑΡΧΕΙΩΝ) ---
def start_server():
    # Αρχικοποίηση βάσης
    db_conn, db_cursor = init_db()
    
    # Δημιουργία Socket
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen(5)
    print(f"📡 AI Server (PC 2): Έτοιμος! Περιμένω MP4 στη θύρα {PORT}...", flush=True)

    while True:
        try:
            conn, addr = server.accept()
            print(f"\n[+] Σύνδεση από {addr[0]}", flush=True)
            
            # 1. Λήψη ονόματος αρχείου
            filename_raw = conn.recv(1024).decode('utf-8').strip()
            if not filename_raw:
                conn.close()
                continue
            
            print(f"📩 Λήψη αρχείου: {filename_raw}...", flush=True)

            # 2. Αποστολή "OK"
            conn.sendall(b"OK")
            
            # 3. Λήψη δεδομένων και αποθήκευση
            filepath = os.path.join(SAVE_DIR, filename_raw)
            with open(filepath, 'wb') as f:
                while True:
                    packet = conn.recv(8192)
                    if not packet:
                        break
                    f.write(packet)
            
            print(f"✅ Το βίντεο αποθηκεύτηκε: {filename_raw}", flush=True)
            conn.close()
            
            # --- 4. ΑΥΤΟΜΑΤΗ ΕΚΚΙΝΗΣΗ YOLO ---
            run_yolo_on_video(filepath, db_conn, db_cursor)
            
        except ConnectionResetError:
            print("⚠️ Η σύνδεση κόπηκε απότομα.", flush=True)
        except Exception as e:
            print(f"❌ Σφάλμα Server: {e}", flush=True)

if __name__ == "__main__":
    start_server()