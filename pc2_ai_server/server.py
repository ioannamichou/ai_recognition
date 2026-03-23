import socket
import os
from datetime import datetime

HOST = '0.0.0.0'
PORT = 5006
SAVE_DIR = '/app/ai_videos'

if not os.path.exists(SAVE_DIR):
    os.makedirs(SAVE_DIR)

def start_server():
    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.bind((HOST, PORT))
    server.listen(5)
    # Χρησιμοποιούμε flush=True για να βλέπουμε τα prints αμέσως στα logs
    print(f"AI Server (PC 2): Είμαι έτοιμος! Περιμένω αρχεία στη θύρα {PORT}...", flush=True)

    while True:
        conn, addr = server.accept()
        print(f"\n[+] Σύνδεση από το Laptop ({addr[0]}).", flush=True)
        
        try:
            # 1. ΠΡΩΤΑ διαβάζουμε το όνομα του αρχείου που στέλνει το Laptop
            filename_raw = conn.recv(1024).decode('utf-8').strip()
            if not filename_raw:
                conn.close()
                continue
            
            print(f"Λήψη αρχείου: {filename_raw}", flush=True)

            # 2. ΣΤΕΛΝΟΥΜΕ ΤΟ "OK" στο Laptop για να ξεκινήσει η ροή των δεδομένων
            conn.sendall(b"OK")
            
            # 3. ΛΑΜΒΑΝΟΥΜΕ τα δεδομένα του βίντεο και τα σώζουμε με το ΑΥΘΕΝΤΙΚΟ όνομα
            filepath = os.path.join(SAVE_DIR, filename_raw)
            
            with open(filepath, 'wb') as f:
                while True:
                    packet = conn.recv(8192)
                    if not packet:
                        break
                    f.write(packet)
            
            print(f"✅ Το βίντεο αποθηκεύτηκε ως: {filename_raw}", flush=True)
            print("🤖 Αναμονή για επεξεργασία AI...", flush=True)
            
        except Exception as e:
            print(f"❌ Σφάλμα κατά τη λήψη: {e}", flush=True)
        finally:
            conn.close()

if __name__ == "__main__":
    start_server()