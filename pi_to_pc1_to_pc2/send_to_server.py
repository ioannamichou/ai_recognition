import socket
import os
import time

# --- ΡΥΘΜΙΣΕΙΣ ---
SERVER_IP = "192.168.10.205"  # <-- ΠΡΟΣΟΧΗ: Βάλε εδώ τη σωστή IP του PC 2!
TCP_PORT = 5006

def upload_files():
    # Βρίσκει όλα τα αρχεία στον φάκελο του Docker
    files = [f for f in os.listdir('.') if f.endswith('.mp4')]
    
    if not files:
        print("Δεν βρέθηκαν αρχεία βίντεο για αποστολή.")
        return

    print(f"Βρέθηκαν {len(files)} αρχεία. Ξεκινάει η αποστολή...")

    for video_file in files:
        try:
            print(f"\nΣύνδεση για το αρχείο: {video_file}")
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            
            # 5 δευτερόλεπτα όριο ΜΟΝΟ για τη σύνδεση
            sock.settimeout(20) 
            sock.connect((SERVER_IP, TCP_PORT))
            
            # ΑΠΕΡΙΟΡΙΣΤΟΣ χρόνος για να προλάβει να στείλει το τεράστιο βίντεο!
            sock.settimeout(None) 
            
            # Στέλνουμε το όνομα
            sock.send(video_file.encode())
            
            # Στέλνουμε τα δεδομένα
            with open(video_file, 'rb') as f:
                while True:
                    data = f.read(4096)
                    if not data: break
                    sock.sendall(data)
            
            print(f"✅ Επιτυχής αποστολή: {video_file}")
            sock.close()
            
            # Μικρή παύση ανάμεσα στα αρχεία
            time.sleep(2) 
            
        except Exception as e:
            print(f"❌ Σφάλμα στο {video_file}: {e}")

if __name__ == "__main__":
    upload_files()