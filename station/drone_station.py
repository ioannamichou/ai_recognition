"""
NB-IoT Drone Ground Station
Combined: pc_db_receiver + pc_command_sender + metrics
"""

import socket
import threading
import queue
import json
import ast
import time
import sys
import os
from datetime import datetime

import pygame
import pygame.freetype

# ============================================================
# ΡΥΘΜΙΣΕΙΣ
# ============================================================
UDP_LISTEN_PORT = 20000

HETZNER_IP   = "178.105.44.165"
HETZNER_PORT = 4001

DB_HOST = "localhost"
DB_PORT = 3306
DB_NAME = "detections"
DB_USER = "admin"
DB_PASS = "admin123"

# Raspberry Pi SSH (Tailscale)
PI_HOST   = "100.69.226.26"
PI_USER   = "dcs-CZQ93wLi"
PI_PASS   = "200304"
PI_SCRIPT = "cd /home/dcs-CZQ93wLi/combined && PYTHONUNBUFFERED=1 python3 pi_combined.py 2>&1"
# ============================================================

CLASSES = {
    0:"person",1:"bicycle",2:"car",3:"motorcycle",4:"airplane",5:"bus",
    6:"train",7:"truck",8:"boat",9:"traffic light",10:"fire hydrant",
    11:"stop sign",12:"parking meter",13:"bench",14:"bird",15:"cat",
    16:"dog",17:"horse",18:"sheep",19:"cow",20:"elephant",21:"bear",
    22:"zebra",23:"giraffe",24:"backpack",25:"umbrella",26:"handbag",
    27:"tie",28:"suitcase",29:"frisbee",30:"skis",31:"snowboard",
    32:"sports ball",33:"kite",34:"baseball bat",35:"baseball glove",
    36:"skateboard",37:"surfboard",38:"tennis racket",39:"bottle",
    40:"wine glass",41:"cup",42:"fork",43:"knife",44:"spoon",45:"bowl",
    46:"banana",47:"apple",48:"sandwich",49:"orange",50:"broccoli",
    51:"carrot",52:"hot dog",53:"pizza",54:"donut",55:"cake",56:"chair",
    57:"couch",58:"potted plant",59:"bed",60:"dining table",61:"toilet",
    62:"tv",63:"laptop",64:"mouse",65:"remote",66:"keyboard",
    67:"cell phone",68:"microwave",69:"oven",70:"toaster",71:"sink",
    72:"refrigerator",73:"book",74:"clock",75:"vase",76:"scissors",
    77:"teddy bear",78:"hair drier",79:"toothbrush",
}

# Reverse lookup: name → id
CLASSES_REV = {v: k for k, v in CLASSES.items()}

# ============================================================
# COLORS
# ============================================================
C_BG        = (10,  14,  18)
C_PANEL     = (16,  22,  28)
C_BORDER    = (30,  55,  40)
C_ACCENT    = (50, 200,  90)
C_ACCENT2   = (20, 140,  60)
C_TEXT      = (180, 220, 190)
C_TEXT_DIM  = (80,  110,  90)
C_WHITE     = (230, 240, 235)
C_RED       = (220,  60,  60)
C_ORANGE    = (220, 150,  40)
C_YELLOW    = (220, 200,  40)
C_INPUT_BG  = (14,  20,  26)
C_INPUT_BD  = (40,  80,  55)
C_INPUT_ACT = (50, 200,  90)
C_SCROLL    = (25,  40,  30)
C_SCROLLTH  = (50, 120,  65)
C_TITLE_BG  = (12,  18,  22)
C_SEP       = (25,  45,  32)
C_ONLINE    = (50, 220, 100)
C_OFFLINE   = (180,  50,  50)
C_CYAN      = (50, 200, 220)

# ============================================================
# Log + Metrics state
# ============================================================
log_queue = queue.Queue()

# Metrics counters
metrics_state = {
    "total_sent":    0,
    "total_recv":    0,
    "latency_last":  0,
    "latency_avg":   0,
    "latency_min":   99999,
    "latency_max":   0,
    "latency_sum":   0,
    "latency_count": 0,
    "last_csq":      0,
    "last_msg_id":   "-",
}
metrics_lock = threading.Lock()

# Pi SSH state
pi_running = False
pi_thread  = None

# Network mode
NETWORK_MODE = None  # "nbiot" ή "5g"

# 5G Flask server state
flask_thread   = None
flask_running  = False

def log(msg, color=None):
    ts = datetime.now().strftime("%H:%M:%S")
    log_queue.put({"ts": ts, "msg": msg, "color": color})

def update_latency(latency_ms):
    with metrics_lock:
        metrics_state["latency_last"]   = latency_ms
        metrics_state["latency_sum"]   += latency_ms
        metrics_state["latency_count"] += 1
        metrics_state["latency_avg"]    = metrics_state["latency_sum"] // metrics_state["latency_count"]
        if latency_ms < metrics_state["latency_min"]:
            metrics_state["latency_min"] = latency_ms
        if latency_ms > metrics_state["latency_max"]:
            metrics_state["latency_max"] = latency_ms
        metrics_state["total_recv"]    += 1

# ============================================================
# DB HELPERS
# ============================================================
def get_conn():
    import mysql.connector
    return mysql.connector.connect(
        host=DB_HOST, port=DB_PORT,
        database=DB_NAME, user=DB_USER, password=DB_PASS
    )

def init_db():
    try:
        conn = get_conn()
        cur  = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS detections (
                id          INT AUTO_INCREMENT PRIMARY KEY,
                detected    BOOLEAN NOT NULL,
                confidence  INT NOT NULL,
                class_id    INT NOT NULL,
                class_name  VARCHAR(50) NOT NULL,
                datetime    DATETIME NOT NULL,
                msg_id      VARCHAR(20),
                csq         INT,
                received_at DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS telemetry (
                id              INT AUTO_INCREMENT PRIMARY KEY,
                mode            VARCHAR(30),
                armed           VARCHAR(10),
                battery_pct     INT,
                battery_voltage FLOAT,
                gps_fix         VARCHAR(20),
                gps_satellites  INT,
                lat             DOUBLE,
                lon             DOUBLE,
                roll            FLOAT,
                pitch           FLOAT,
                yaw             FLOAT,
                altitude        FLOAT,
                speed           FLOAT,
                throttle        INT,
                imu_temp        FLOAT,
                vib_x           FLOAT,
                vib_y           FLOAT,
                vib_z           FLOAT,
                msg_id          VARCHAR(20),
                csq             INT,
                received_at     DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS metrics (
                id                 INT AUTO_INCREMENT PRIMARY KEY,
                msg_id             VARCHAR(20),
                msg_type           VARCHAR(20),
                timestamp_sent_ms  BIGINT,
                timestamp_hetzner_ms BIGINT,
                timestamp_pc_ms    BIGINT,
                latency_total_ms   INT,
                latency_pi_hetzner_ms INT,
                latency_hetzner_pc_ms INT,
                bytes_sent         INT,
                csq                INT,
                received_at        DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS sessions_5g (
                id                  INT AUTO_INCREMENT PRIMARY KEY,
                drone_id            VARCHAR(50),
                network_type        VARCHAR(20),
                fps                 FLOAT,
                avg_inference_ms    FLOAT,
                queue_delay_ms      FLOAT,
                cpu_percent         FLOAT,
                ram_percent         FLOAT,
                payload_bytes       INT,
                detections_count    INT,
                recorded_at         DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        cur.execute("""
            CREATE TABLE IF NOT EXISTS performance_metrics (
                id                  INT AUTO_INCREMENT PRIMARY KEY,
                msg_id              VARCHAR(20),
                drone_id            VARCHAR(50),
                network_type        VARCHAR(20),
                fps                 FLOAT,
                avg_inference_ms    FLOAT,
                queue_delay_ms      FLOAT,
                cpu_percent         FLOAT,
                ram_percent         FLOAT,
                payload_bytes       INT,
                csq                 INT,
                latency_ms          INT,
                timestamp_sent_ms   BIGINT,
                timestamp_pc_ms     BIGINT,
                recorded_at         DATETIME DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # ALTER για παλιες εγκαταστασεις
        for col_sql in [
            "ALTER TABLE performance_metrics ADD COLUMN queue_delay_ms FLOAT",
            "ALTER TABLE performance_metrics ADD COLUMN payload_bytes INT",
        ]:
            try:
                cur.execute(col_sql)
            except:
                pass

        # Προσθηκη στηλων αν δεν υπαρχουν (για παλιες εγκαταστασεις)
        migrations = [
            "ALTER TABLE detections ADD COLUMN msg_id VARCHAR(20)",
            "ALTER TABLE detections ADD COLUMN csq INT",
            "ALTER TABLE telemetry ADD COLUMN msg_id VARCHAR(20)",
            "ALTER TABLE telemetry ADD COLUMN csq INT",
        ]
        for sql in migrations:
            try:
                cur.execute(sql)
            except Exception:
                pass  # Η στηλη υπαρχει ηδη

        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log(f"[DB] ΣΦΑΛΜΑ init: {e}", C_RED)
        return False

def try_save_detection(data):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        dt   = datetime.strptime(data["datetime"], "%Y%m%d%H%M%S")
        cur.execute(
            "INSERT INTO detections (detected,confidence,class_id,class_name,datetime,msg_id,csq)"
            " VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (data["detected"], data["confidence"], data["class_id"],
             data["class_name"], dt, data.get("msg_id"), data.get("csq"))
        )
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        return False

def try_save_telemetry(t):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO telemetry (
                mode,armed,battery_pct,battery_voltage,
                gps_fix,gps_satellites,lat,lon,
                roll,pitch,yaw,altitude,speed,throttle,
                imu_temp,vib_x,vib_y,vib_z,msg_id,csq
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            t.get("mode"), t.get("armed"),
            t.get("battery_pct"), t.get("battery_voltage"),
            t.get("gps_fix"), t.get("gps_satellites"),
            t.get("lat"), t.get("lon"),
            t.get("roll"), t.get("pitch"), t.get("yaw"),
            t.get("altitude"), t.get("speed"), t.get("throttle"),
            t.get("imu_temp"),
            t.get("vib_x"), t.get("vib_y"), t.get("vib_z"),
            t.get("msg_id"), t.get("csq")
        ))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception:
        return False

def try_save_metrics(msg_id, msg_type, ts_sent, ts_hetzner, ts_pc, bytes_sent, csq):
    try:
        conn = get_conn()
        cur  = conn.cursor()

        lat_total   = (ts_pc - ts_sent)      if ts_sent and ts_pc      else None
        lat_pi_htz  = (ts_hetzner - ts_sent) if ts_sent and ts_hetzner else None
        lat_htz_pc  = (ts_pc - ts_hetzner)   if ts_hetzner and ts_pc   else None

        cur.execute("""
            INSERT INTO metrics (
                msg_id, msg_type,
                timestamp_sent_ms, timestamp_hetzner_ms, timestamp_pc_ms,
                latency_total_ms, latency_pi_hetzner_ms, latency_hetzner_pc_ms,
                bytes_sent, csq
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (msg_id, msg_type, ts_sent, ts_hetzner, ts_pc,
              lat_total, lat_pi_htz, lat_htz_pc, bytes_sent, csq))

        conn.commit(); cur.close(); conn.close()

        if lat_total is not None:
            update_latency(lat_total)

        return lat_total
    except Exception as e:
        return None

# ============================================================
# UDP RECEIVER THREAD
# ============================================================
receiver_sock    = None
receiver_running = False

def udp_receiver_thread():
    global receiver_sock, receiver_running
    receiver_running = True
    try:
        receiver_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        receiver_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        receiver_sock.settimeout(1.0)
        receiver_sock.bind(("0.0.0.0", UDP_LISTEN_PORT))
        log(f"[RECEIVER] Ακούω UDP στη πόρτα {UDP_LISTEN_PORT}", C_ACCENT)
    except Exception as e:
        log(f"[RECEIVER] ΣΦΑΛΜΑ bind: {e}", C_RED)
        receiver_running = False
        return

    while receiver_running:
        try:
            data, addr = receiver_sock.recvfrom(4096)
            ts_pc      = int(time.time() * 1000)
            message    = data.decode('utf-8').strip()
            src        = addr[0]

            with metrics_lock:
                metrics_state["total_sent"] += 1

            if message.startswith("{"):
                # JSON message
                try:
                    try:
                        t = json.loads(message)
                    except json.JSONDecodeError:
                        t = ast.literal_eval(message)

                    msg_type = t.get("type", "telemetry")

                    if msg_type == "performance":
                        ts_sent = t.get("timestamp_sent")
                        lat     = (ts_pc - ts_sent) if ts_sent else None
                        saved   = try_save_performance(t, lat, ts_pc)
                        db_tag  = "→DB✓" if saved else "→DB✗"
                        lat_str = f"  Latency:{lat}ms" if lat else ""
                        log(f"[PERF {db_tag}] FPS:{t.get('fps','-')} Inf:{t.get('avg_inference_ms','-')}ms CPU:{t.get('cpu_percent','-')}% RAM:{t.get('ram_percent','-')}%{lat_str}", C_CYAN)
                    else:
                        ts_sent    = t.get("timestamp_sent")
                    ts_hetzner = t.get("timestamp_hetzner")
                    msg_id     = t.get("msg_id", "-")
                    csq        = t.get("csq", 0)

                    with metrics_lock:
                        metrics_state["last_csq"]    = csq
                        metrics_state["last_msg_id"] = msg_id

                    lat = try_save_metrics(msg_id, "telemetry", ts_sent, ts_hetzner, ts_pc, len(data), csq)
                    saved = try_save_telemetry(t)

                    db_tag  = "→DB✓" if saved else "→DB✗"
                    lat_str = f"  Latency: {lat}ms" if lat else ""
                    log(f"[TELEM {db_tag}] ID:{msg_id} CSQ:{csq}{lat_str}", C_YELLOW)
                    log(f"  Mode:{t.get('mode','-')}  Armed:{t.get('armed','-')}  Bat:{t.get('battery_pct','-')}%", C_YELLOW)
                    if t.get('lat'):
                        log(f"  GPS:{t.get('gps_fix','-')} Lat:{t.get('lat','-')} Lon:{t.get('lon','-')}", C_TEXT_DIM)
                    if t.get('roll') is not None:
                        log(f"  Roll:{t.get('roll','-')}° Pitch:{t.get('pitch','-')}° Yaw:{t.get('yaw','-')}°", C_TEXT_DIM)
                    if t.get('altitude') is not None:
                        log(f"  Alt:{t.get('altitude','-')}m Speed:{t.get('speed','-')}m/s Throttle:{t.get('throttle','-')}%", C_TEXT_DIM)
                    if t.get('imu_temp') is not None:
                            log(f"  IMU:{t.get('imu_temp','-')}°C  Vib x:{t.get('vib_x','-')} y:{t.get('vib_y','-')} z:{t.get('vib_z','-')}", C_TEXT_DIM)
                except Exception as e:
                    log(f"[JSON] ΣΦΑΛΜΑ: {e}", C_RED)
            else:
                # Detection CSV: detected,confidence,class_id,datetime,msg_id,csq,timestamp_sent,timestamp_hetzner
                parts = message.strip().split(",")
                if len(parts) >= 4:
                    try:
                        cid    = int(parts[2])
                        msg_id = parts[4] if len(parts) > 4 else "-"
                        csq    = int(parts[5]) if len(parts) > 5 else 0
                        ts_sent    = int(parts[6]) if len(parts) > 6 else None
                        ts_hetzner = int(parts[7]) if len(parts) > 7 else None

                        det = {
                            "detected":   bool(int(parts[0])),
                            "confidence": int(parts[1]),
                            "class_id":   cid,
                            "class_name": CLASSES.get(cid, "unknown"),
                            "datetime":   parts[3],
                            "msg_id":     msg_id,
                            "csq":        csq,
                        }

                        with metrics_lock:
                            metrics_state["last_csq"]    = csq
                            metrics_state["last_msg_id"] = msg_id

                        lat   = try_save_metrics(msg_id, "detection", ts_sent, ts_hetzner, ts_pc, len(data), csq)
                        saved = try_save_detection(det)

                        db_tag     = "→DB✓" if saved else "→DB✗"
                        conf_color = C_RED if det["confidence"] >= 80 else C_ORANGE if det["confidence"] >= 50 else C_TEXT
                        lat_str    = f"  Latency:{lat}ms" if lat else ""
                        log(f"[DET {db_tag}] {det['class_name'].upper()} {det['confidence']}% ID:{msg_id} CSQ:{csq}{lat_str}", conf_color)
                    except Exception as e:
                        log(f"[DET] ΣΦΑΛΜΑ: {e}", C_RED)
                else:
                    log(f"[RAW] {src}: {message[:80]}", C_TEXT_DIM)

        except socket.timeout:
            continue
        except Exception as e:
            if receiver_running:
                log(f"[RECEIVER] ΣΦΑΛΜΑ: {e}", C_RED)

    if receiver_sock:
        receiver_sock.close()
    log("[RECEIVER] Σταμάτησε.", C_TEXT_DIM)

# ============================================================
# COMMAND SENDER
# ============================================================
sender_sock = None

def send_command(cmd):
    global sender_sock
    try:
        if sender_sock is None:
            sender_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sender_sock.sendto(cmd.encode(), (HETZNER_IP, HETZNER_PORT))
        log(f"[SENT →] {cmd}", C_ACCENT)
        return True
    except Exception as e:
        log(f"[SEND ΣΦΑΛΜΑ] {e}", C_RED)
        return False

# ============================================================
# PYGAME UI
# ============================================================
WIN_W, WIN_H = 1280, 800
FPS = 60

QUICK_CMDS = [
    ("telemetry",      "TELEMETRY",  C_CYAN),
    ("arm",            "ARM",        C_RED),
    ("disarm",         "DISARM",     C_ACCENT),
    ("rtl",            "RTL",        C_ORANGE),
    ("land",           "LAND",       C_YELLOW),
    ("mode STABILIZE", "STABILIZE",  C_TEXT_DIM),
    ("mode LOITER",    "LOITER",     C_TEXT_DIM),
    ("mode ALTHOLD",   "ALTHOLD",    C_TEXT_DIM),
]

class TextInput:
    def __init__(self, x, y, w, h, placeholder="Type command..."):
        self.rect = pygame.Rect(x, y, w, h)
        self.text = ""
        self.active = False
        self.placeholder = placeholder
        self.cursor_vis = True
        self.cursor_timer = 0

    def handle_event(self, event):
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if event.type == pygame.KEYDOWN and self.active:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                cmd = self.text.strip()
                self.text = ""
                return cmd
            elif event.key == pygame.K_ESCAPE:
                self.text = ""
            else:
                if len(self.text) < 120:
                    self.text += event.unicode
        return None

    def update(self, dt):
        self.cursor_timer += dt
        if self.cursor_timer > 0.5:
            self.cursor_vis = not self.cursor_vis
            self.cursor_timer = 0

    def draw(self, surf, font):
        border_col = C_INPUT_ACT if self.active else C_INPUT_BD
        pygame.draw.rect(surf, C_INPUT_BG, self.rect, border_radius=4)
        pygame.draw.rect(surf, border_col, self.rect, 1, border_radius=4)
        display = self.text
        if self.active and self.cursor_vis:
            display += "|"
        col = C_WHITE if self.text else C_TEXT_DIM
        txt = self.placeholder if not self.text and not self.active else display
        txt_surf, _ = font.render(txt, col)
        surf.blit(txt_surf, (self.rect.x + 12, self.rect.y + (self.rect.h - txt_surf.get_height()) // 2))


class LogPanel:
    def __init__(self, x, y, w, h):
        self.rect = pygame.Rect(x, y, w, h)
        self.lines = []
        self.scroll = 0
        self.line_h = 19
        self._drag = False
        self._drag_start = 0
        self._scroll_start = 0
        self.max_lines = 2000

    def add(self, ts, msg, color):
        col = color or C_TEXT
        self.lines.append((ts, msg, col))
        if len(self.lines) > self.max_lines:
            self.lines.pop(0)
        visible = (self.rect.h - 4) // self.line_h
        max_scroll = max(0, len(self.lines) - visible)
        self.scroll = max_scroll

    def handle_event(self, event):
        if not self.rect.collidepoint(pygame.mouse.get_pos()):
            return
        if event.type == pygame.MOUSEWHEEL:
            self.scroll = max(0, self.scroll - event.y * 3)
            self._clamp_scroll()
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            sb = self._scrollbar_rect()
            if sb and sb.collidepoint(event.pos):
                self._drag = True
                self._drag_start = event.pos[1]
                self._scroll_start = self.scroll
        if event.type == pygame.MOUSEBUTTONUP:
            self._drag = False
        if event.type == pygame.MOUSEMOTION and self._drag:
            dy = event.pos[1] - self._drag_start
            visible = (self.rect.h - 4) // self.line_h
            max_scroll = max(1, len(self.lines) - visible)
            track_h = self.rect.h - 8
            ratio = dy / track_h
            self.scroll = int(self._scroll_start + ratio * max_scroll)
            self._clamp_scroll()

    def _clamp_scroll(self):
        visible = (self.rect.h - 4) // self.line_h
        max_scroll = max(0, len(self.lines) - visible)
        self.scroll = max(0, min(self.scroll, max_scroll))

    def _scrollbar_rect(self):
        if len(self.lines) == 0:
            return None
        visible = (self.rect.h - 4) // self.line_h
        if len(self.lines) <= visible:
            return None
        track_h = self.rect.h - 8
        thumb_h = max(20, int(track_h * visible / len(self.lines)))
        max_scroll = max(1, len(self.lines) - visible)
        thumb_y = self.rect.y + 4 + int((self.scroll / max_scroll) * (track_h - thumb_h))
        return pygame.Rect(self.rect.right - 10, thumb_y, 7, thumb_h)

    def draw(self, surf, font_small):
        pygame.draw.rect(surf, C_PANEL, self.rect, border_radius=4)
        pygame.draw.rect(surf, C_BORDER, self.rect, 1, border_radius=4)
        clip = pygame.Rect(self.rect.x+2, self.rect.y+2, self.rect.w-16, self.rect.h-4)
        old_clip = surf.get_clip()
        surf.set_clip(clip)
        visible = (self.rect.h - 4) // self.line_h
        start = self.scroll
        end   = start + visible + 1
        for i, (ts, msg, col) in enumerate(self.lines[start:end]):
            y = self.rect.y + 4 + i * self.line_h
            ts_surf, _ = font_small.render(ts, C_TEXT_DIM)
            surf.blit(ts_surf, (self.rect.x + 6, y))
            msg_surf, _ = font_small.render(msg, col)
            surf.blit(msg_surf, (self.rect.x + 70, y))
        surf.set_clip(old_clip)
        sb = self._scrollbar_rect()
        if sb:
            track = pygame.Rect(self.rect.right - 11, self.rect.y+4, 8, self.rect.h-8)
            pygame.draw.rect(surf, C_SCROLL, track, border_radius=3)
            pygame.draw.rect(surf, C_SCROLLTH, sb, border_radius=3)


class Button:
    def __init__(self, x, y, w, h, label, color, cmd=None):
        self.rect  = pygame.Rect(x, y, w, h)
        self.label = label
        self.color = color
        self.cmd   = cmd
        self._hover = False
        self._press = False
        self._anim  = 0.0

    def handle_event(self, event):
        if event.type == pygame.MOUSEMOTION:
            self._hover = self.rect.collidepoint(event.pos)
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            if self.rect.collidepoint(event.pos):
                self._press = True
                self._anim = 1.0
                return self.cmd
        if event.type == pygame.MOUSEBUTTONUP:
            self._press = False
        return None

    def update(self, dt):
        self._anim = max(0.0, self._anim - dt * 4)

    def draw(self, surf, font):
        alpha = 0.15 + 0.25 * self._hover + 0.1 * self._anim
        r, g, b = self.color
        bg = (int(r*alpha), int(g*alpha), int(b*alpha))
        bd = tuple(min(255, int(c * (0.6 + 0.4 * self._hover))) for c in self.color)
        pygame.draw.rect(surf, bg, self.rect, border_radius=4)
        pygame.draw.rect(surf, bd, self.rect, 1, border_radius=4)
        ts, _ = font.render(self.label, self.color)
        surf.blit(ts, (self.rect.centerx - ts.get_width()//2,
                       self.rect.centery - ts.get_height()//2))


def draw_glow_text(surf, font, text, x, y, color, glow=True):
    if glow:
        r, g, b = color
        dim = (r//4, g//4, b//4)
        for dx, dy in [(-1,0),(1,0),(0,-1),(0,1)]:
            s, _ = font.render(text, dim)
            surf.blit(s, (x+dx, y+dy))
    s, _ = font.render(text, color)
    surf.blit(s, (x, y))
    return s.get_width()

def draw_separator(surf, x1, y, x2):
    pygame.draw.line(surf, C_SEP, (x1, y), (x2, y), 1)

def status_dot(surf, x, y, online):
    col = C_ONLINE if online else C_OFFLINE
    pygame.draw.circle(surf, col, (x, y), 5)
    s = pygame.Surface((20, 20), pygame.SRCALPHA)
    r, g, b = col
    pygame.draw.circle(s, (r, g, b, 50), (10, 10), 9)
    surf.blit(s, (x-10, y-10))



# ============================================================
# SSH PI CONTROL
# ============================================================
def ssh_pi_start():
    global pi_running, pi_thread
    if pi_running:
        log("[PI] Ηδη τρεχει!", C_ORANGE)
        return

    def _connect():
        global pi_running
        try:
            import paramiko
        except ImportError:
            log("[PI] ΣΦΑΛΜΑ: pip install paramiko", C_RED)
            return
        log(f"[PI] Συνδεομαι στο {PI_HOST}...", C_CYAN)
        try:
            client = paramiko.SSHClient()
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=10)
            log(f"[PI] Συνδεθηκα! Εκκινω pi_combined.py...", C_CYAN)
            stdin, stdout, stderr = client.exec_command(PI_SCRIPT, get_pty=True)
            pi_running = True
            log("[PI] pi_combined.py τρεχει!", C_ONLINE)
            for line in iter(stdout.readline, ""):
                if not pi_running:
                    break
                line = line.rstrip()
                if line:
                    log(f"[PI] {line}", C_CYAN)
            exit_code = stdout.channel.recv_exit_status()
            pi_running = False
            log(f"[PI] Τερματιστηκε (exit {exit_code})", C_TEXT_DIM)
            client.close()
        except Exception as e:
            pi_running = False
            log(f"[PI] ΣΦΑΛΜΑ SSH: {e}", C_RED)

    pi_thread = threading.Thread(target=_connect, daemon=True)
    pi_thread.start()


def ssh_pi_stop():
    global pi_running, pi_thread
    pi_running = False
    log("[PI] Εντολη διακοπης — στελνω Ctrl+C...", C_ORANGE)
    try:
        import paramiko
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(PI_HOST, username=PI_USER, password=PI_PASS, timeout=5)
        client.exec_command("pkill -f pi_combined.py")
        client.close()
        log("[PI] Σταματησε!", C_ACCENT)
    except Exception as e:
        log(f"[PI] ΣΦΑΛΜΑ stop: {e}", C_RED)

def try_save_performance(p, latency_ms, ts_pc):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        cur.execute("""
            INSERT INTO performance_metrics (
                msg_id, drone_id, network_type,
                fps, avg_inference_ms, queue_delay_ms,
                cpu_percent, ram_percent, payload_bytes,
                csq, latency_ms,
                timestamp_sent_ms, timestamp_pc_ms
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            p.get("msg_id"), p.get("drone_id"), p.get("network_type"),
            p.get("fps"), p.get("avg_inference_ms"), p.get("queue_delay_ms"),
            p.get("cpu_percent"), p.get("ram_percent"), p.get("payload_bytes"),
            p.get("csq"), latency_ms,
            p.get("timestamp_sent"), ts_pc
        ))
        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log(f"[DB PERF ERROR] {e}", C_RED)
        return False


def try_save_5g(data):
    try:
        conn = get_conn()
        cur  = conn.cursor()
        metrics = data.get("metrics", {})
        dets    = data.get("detections", [])

        # Αποθηκευση session
        cur.execute("""
            INSERT INTO sessions_5g (
                drone_id, network_type,
                fps, avg_inference_ms, queue_delay_ms,
                cpu_percent, ram_percent, payload_bytes,
                detections_count
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
        """, (
            data.get("drone_id"), data.get("network_type", "5G"),
            metrics.get("fps"), metrics.get("avg_inference_time_ms"),
            metrics.get("queue_delay_ms"), metrics.get("cpu_percent"),
            metrics.get("ram_percent"), metrics.get("payload_bytes"),
            len(dets)
        ))

        # Αποθηκευση καθε detection ξεχωριστα
        for det in dets:
            try:
                from datetime import datetime as dt_mod
                ts = det.get("timestamp", "")
                try:
                    dt_val = dt_mod.strptime(ts, "%Y-%m-%d %H:%M:%S")
                except:
                    dt_val = dt_mod.now()

                obj_name = det.get("object", "unknown")
                cid = CLASSES_REV.get(obj_name.lower(), 9)
                cur.execute("""
                    INSERT INTO detections (detected, confidence, class_id, class_name, datetime)
                    VALUES (%s, %s, %s, %s, %s)
                """, (True, det.get("confidence", 0), cid, obj_name, dt_val))
            except Exception as de:
                log(f"[DB 5G DET] {de}", C_RED)

        conn.commit(); cur.close(); conn.close()
        return True
    except Exception as e:
        log(f"[DB 5G ERROR] {e}", C_RED)
        return False


def start_flask_server():
    """Flask server για λήψη δεδομένων από το Pi μέσω 5G HTTP POST"""
    global flask_running
    try:
        from flask import Flask, request, jsonify
        app = Flask(__name__)

        @app.route("/upload", methods=["POST"])
        def upload():
            data = request.get_json()
            if data:
                saved = try_save_5g(data)
                dets  = data.get("detections", [])
                m     = data.get("metrics", {})
                log(f"[5G] Εληφθη: {len(dets)} detections FPS:{m.get('fps','-')} CPU:{m.get('cpu_percent','-')}%", C_CYAN)
                if saved:
                    log(f"[5G] →DB✓ Αποθηκευτηκε!", C_ACCENT)
                return jsonify({"status": "ok"}), 200
            return jsonify({"status": "error"}), 400

        flask_running = True
        log("[5G] HTTP Server εκκινησε στο port 5000", C_CYAN)
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except ImportError:
        log("[5G] ΣΦΑΛΜΑ: pip install flask", C_RED)
    except Exception as e:
        log(f"[5G] ΣΦΑΛΜΑ Flask: {e}", C_RED)
    finally:
        flask_running = False


def show_network_selection(screen, clock):
    """Οθονη επιλογης δικτυου με IP input fields"""
    try:
        font_big   = pygame.freetype.SysFont("Courier New", 26, bold=True)
        font_med   = pygame.freetype.SysFont("Courier New", 15)
        font_small = pygame.freetype.SysFont("Courier New", 12)
        font_input = pygame.freetype.SysFont("Courier New", 14)
    except:
        font_big   = pygame.freetype.SysFont(None, 26, bold=True)
        font_med   = pygame.freetype.SysFont(None, 15)
        font_small = pygame.freetype.SysFont(None, 12)
        font_input = pygame.freetype.SysFont(None, 14)

    # Default IPs
    pc_ip_text  = ""
    active_field = None  # "pc" or None

    cursor_vis   = True
    cursor_timer = 0.0
    prev_time    = time.time()

    while True:
        now = time.time()
        dt  = now - prev_time
        prev_time = now
        cursor_timer += dt
        if cursor_timer > 0.5:
            cursor_vis = not cursor_vis
            cursor_timer = 0.0

        W, H = screen.get_size()
        cx   = W // 2
        base_y = 80

        # Rects
        pc_ip_rect = pygame.Rect(cx - 100, base_y + 170, 280, 32)
        btn_nbiot  = pygame.Rect(cx - 220, base_y + 260, 200, 55)
        btn_5g     = pygame.Rect(cx + 20,  base_y + 260, 200, 55)

        mx, my = pygame.mouse.get_pos()

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit()
                import sys; sys.exit(0)

            if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
                if pc_ip_rect.collidepoint(mx, my):
                    active_field = "pc"
                elif btn_nbiot.collidepoint(mx, my):
                    return {"mode": "nbiot", "pc_ip": pc_ip_text.strip()}
                elif btn_5g.collidepoint(mx, my):
                    return {"mode": "5g", "pc_ip": pc_ip_text.strip()}
                else:
                    active_field = None

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_TAB:
                    active_field = "pc"
                elif event.key == pygame.K_BACKSPACE:
                    if active_field == "pc":
                        pc_ip_text = pc_ip_text[:-1]
                elif event.key == pygame.K_RETURN:
                    pass
                else:
                    ch = event.unicode
                    if ch and len(ch) == 1:
                        if active_field == "pc" and len(pc_ip_text) < 40:
                            pc_ip_text += ch

        screen.fill((10, 14, 18))

        # Τιτλος
        t, _ = font_big.render("DRONE GROUND STATION", (50, 200, 90))
        screen.blit(t, (cx - t.get_width()//2, base_y))

        t2, _ = font_med.render("Ρυθμισεις & Επιλογη Δικτυου", (180, 220, 190))
        screen.blit(t2, (cx - t2.get_width()//2, base_y + 50))

        # Γραμμη
        pygame.draw.line(screen, (30, 55, 40), (cx - 250, base_y + 80), (cx + 250, base_y + 80), 1)

        # PC IP field
        t_pc, _ = font_small.render("PC IP (απαιτειται για 5G mode):", (120, 150, 130))
        screen.blit(t_pc, (cx - 200, base_y + 100))

        # PC IP input box
        pc_border = (80, 120, 255) if active_field == "pc" else (40, 80, 55)
        pygame.draw.rect(screen, (14, 20, 26), pc_ip_rect, border_radius=4)
        pygame.draw.rect(screen, pc_border, pc_ip_rect, 1, border_radius=4)
        pc_display = pc_ip_text + ("|" if active_field == "pc" and cursor_vis else "")
        pc_col = (230, 240, 235) if pc_ip_text else (80, 110, 90)
        pc_txt = pc_display if pc_ip_text or active_field == "pc" else "π.χ. 192.168.1.100"
        ts_pc, _ = font_input.render(pc_txt, pc_col)
        screen.blit(ts_pc, (pc_ip_rect.x + 8, pc_ip_rect.y + 7))

        # Γραμμη πριν τα buttons
        pygame.draw.line(screen, (30, 55, 40), (cx - 250, base_y + 225), (cx + 250, base_y + 225), 1)

        t_sel, _ = font_med.render("Επιλεξτε μεθοδο επικοινωνιας:", (180, 220, 190))
        screen.blit(t_sel, (cx - t_sel.get_width()//2, base_y + 232))

        # NB-IoT button
        hover_nbiot = btn_nbiot.collidepoint(mx, my)
        pygame.draw.rect(screen, (20, 60, 30) if hover_nbiot else (14, 40, 20), btn_nbiot, border_radius=8)
        pygame.draw.rect(screen, (50, 200, 90), btn_nbiot, 2, border_radius=8)
        t3, _ = font_med.render("NB-IoT", (50, 200, 90))
        screen.blit(t3, (btn_nbiot.centerx - t3.get_width()//2, btn_nbiot.centery - t3.get_height()//2))

        # 5G button
        hover_5g = btn_5g.collidepoint(mx, my)
        pygame.draw.rect(screen, (30, 30, 80) if hover_5g else (20, 20, 60), btn_5g, border_radius=8)
        pygame.draw.rect(screen, (80, 120, 255), btn_5g, 2, border_radius=8)
        t4, _ = font_med.render("5G", (80, 120, 255))
        screen.blit(t4, (btn_5g.centerx - t4.get_width()//2, btn_5g.centery - t4.get_height()//2))

        # Περιγραφες
        t5, _ = font_small.render("SIM7020 + Hetzner Bridge + UDP", (80, 110, 90))
        screen.blit(t5, (btn_nbiot.x, btn_nbiot.bottom + 6))
        t6, _ = font_small.render("HTTP POST, Flask Server", (60, 80, 160))
        screen.blit(t6, (btn_5g.x, btn_5g.bottom + 6))

        # Footer hint
        t_hint, _ = font_small.render("Click στο πεδιο IP  |  Click NB-IoT η 5G για εκκινηση", (80, 100, 80))
        screen.blit(t_hint, (cx - t_hint.get_width()//2, base_y + 370))

        pygame.display.flip()
        clock.tick(60)


def main():
    global receiver_running, NETWORK_MODE, flask_thread, flask_running

    pygame.init()
    pygame.display.set_caption("Drone Ground Station")
    screen = pygame.display.set_mode((WIN_W, WIN_H), pygame.RESIZABLE)
    clock  = pygame.time.Clock()

    # Οθονη επιλογης δικτυου
    selection    = show_network_selection(screen, clock)
    NETWORK_MODE = selection["mode"]
    
    PC_IP_USER   = selection["pc_ip"]
    pygame.display.set_caption(f"Drone Ground Station  [{NETWORK_MODE.upper()}]")

    # Αυτοματη εκκινηση αναλογα με το mode
    if NETWORK_MODE == "5g":
        flask_thread = threading.Thread(target=start_flask_server, daemon=True)
        flask_thread.start()
        if PC_IP_USER:
            send_command(f"START_5G:{PC_IP_USER}")
        else:
            send_command("START_5G")
    else:
        # NB-IoT — στειλε START αυτοματα
        send_command("START")

    try:
        font_title = pygame.freetype.SysFont("Courier New", 20, bold=True)
        font_hdr   = pygame.freetype.SysFont("Courier New", 13, bold=True)
        font_body  = pygame.freetype.SysFont("Courier New", 12)
        font_small = pygame.freetype.SysFont("Courier New", 11)
        font_btn   = pygame.freetype.SysFont("Courier New", 11, bold=True)
        font_mono  = pygame.freetype.SysFont("Courier New", 11)
    except:
        font_title = pygame.freetype.SysFont(None, 20, bold=True)
        font_hdr   = pygame.freetype.SysFont(None, 13, bold=True)
        font_body  = pygame.freetype.SysFont(None, 12)
        font_small = pygame.freetype.SysFont(None, 11)
        font_btn   = pygame.freetype.SysFont(None, 11, bold=True)
        font_mono  = pygame.freetype.SysFont(None, 11)

    MARGIN   = 12
    HDR_H    = 52
    FOOTER_H = 30
    LEFT_W   = 320
    DIVIDER  = 8
    METRICS_H = 140  # ύψος metrics panel

    def layout(w, h):
        right_x = MARGIN + LEFT_W + DIVIDER
        right_w = w - right_x - MARGIN
        log_y   = HDR_H + MARGIN + METRICS_H + 8
        log_h   = h - log_y - FOOTER_H - MARGIN
        return right_x, right_w, log_y, log_h

    right_x, right_w, log_y, log_h = layout(WIN_W, WIN_H)
    log_panel = LogPanel(right_x, log_y, right_w, log_h)

    INPUT_Y   = HDR_H + MARGIN + 10
    inp       = TextInput(MARGIN, INPUT_Y, LEFT_W - 80, 34, "Γράψε εντολή...")
    btn_send  = Button(MARGIN + LEFT_W - 76, INPUT_Y, 72, 34, "SEND", C_ACCENT)

    BTN_COLS   = 2
    BTN_W      = (LEFT_W - (BTN_COLS-1)*6) // BTN_COLS
    BTN_H      = 30
    qbtns      = []
    btn_start_y = INPUT_Y + 50
    for i, (cmd, label, col) in enumerate(QUICK_CMDS):
        col_i = i % BTN_COLS
        row_i = i // BTN_COLS
        bx = MARGIN + col_i * (BTN_W + 6)
        by = btn_start_y + row_i * (BTN_H + 6)
        qbtns.append(Button(bx, by, BTN_W, BTN_H, label, col, cmd))

    btn_clear    = Button(MARGIN, WIN_H - FOOTER_H - MARGIN - 2, LEFT_W, 24, "CLEAR LOG", C_TEXT_DIM)
    # PI buttons - y θα ανανεωνεται στο draw
    btn_pi_start = Button(MARGIN,                  400, (LEFT_W-6)//2, 28, "START PI", C_ACCENT)
    btn_pi_stop  = Button(MARGIN+(LEFT_W-6)//2+6, 400, (LEFT_W-6)//2, 28, "STOP PI",  C_RED)

    # Init DB
    db_ok = init_db()
    log(f"[DB] {'OK' if db_ok else 'ΣΦΑΛΜΑ — χωρις DB'}", C_ACCENT if db_ok else C_RED)

    # Start receiver
    t = threading.Thread(target=udp_receiver_thread, daemon=True)
    t.start()
    log(f"[STATION] Ground Station αρχίζει...", C_ACCENT)
    log(f"[STATION] Receiver: UDP :{UDP_LISTEN_PORT}", C_TEXT_DIM)
    log(f"[STATION] Sender  : {HETZNER_IP}:{HETZNER_PORT}", C_TEXT_DIM)

    recv_online  = False
    last_recv    = 0
    uptime_start = time.time()
    running      = True
    prev_time    = time.time()

    while running:
        now      = time.time()
        dt       = now - prev_time
        prev_time = now

        while not log_queue.empty():
            item = log_queue.get_nowait()
            log_panel.add(item["ts"], item["msg"], item["color"])
            last_recv   = time.time()
            recv_online = True

        if time.time() - last_recv > 15 and last_recv > 0:
            recv_online = False

        W, H = screen.get_size()
        right_x, right_w, log_y, log_h = layout(W, H)

        log_panel.rect = pygame.Rect(right_x, log_y, right_w, log_h)
        inp.rect       = pygame.Rect(MARGIN, INPUT_Y, LEFT_W - 80, 34)
        btn_send.rect  = pygame.Rect(MARGIN + LEFT_W - 76, INPUT_Y, 72, 34)
        btn_clear.rect = pygame.Rect(MARGIN, H - FOOTER_H - MARGIN - 2, LEFT_W, 24)

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False
            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_F11:
                    pygame.display.toggle_fullscreen()
                if event.key == pygame.K_ESCAPE:
                    running = False
                if event.key == pygame.K_F1:
                    if NETWORK_MODE == "5g":
                        send_command(f"START_5G:{PC_IP_USER}" if PC_IP_USER else "START_5G")
                    else:
                        send_command("START")
                if event.key == pygame.K_F2:
                    send_command("STOP")

            cmd = inp.handle_event(event)
            if cmd:
                send_command(cmd)

            result = btn_send.handle_event(event)
            if result is not None:
                cmd = inp.text.strip()
                if cmd:
                    send_command(cmd)
                    inp.text = ""

            for btn in qbtns:
                c = btn.handle_event(event)
                if c:
                    send_command(c)

            c = btn_clear.handle_event(event)
            if c is not None:
                log_panel.lines.clear()
                log_panel.scroll = 0

            if btn_pi_start.handle_event(event) is not None:
                ssh_pi_start()
            if btn_pi_stop.handle_event(event) is not None:
                ssh_pi_stop()

            log_panel.handle_event(event)

        inp.update(dt)
        btn_send.update(dt)
        for btn in qbtns:
            btn.update(dt)
        btn_pi_start.update(dt)
        btn_pi_stop.update(dt)

        # ---- DRAW ----
        screen.fill(C_BG)

        # Header
        pygame.draw.rect(screen, C_TITLE_BG, (0, 0, W, HDR_H))
        pygame.draw.line(screen, C_BORDER, (0, HDR_H), (W, HDR_H), 1)
        for sy in range(0, HDR_H, 4):
            sl = pygame.Surface((W, 1), pygame.SRCALPHA)
            sl.fill((0, 0, 0, 25))
            screen.blit(sl, (0, sy))
        mode_label = "NB-IoT" if NETWORK_MODE == "nbiot" else "5G"
        draw_glow_text(screen, font_title, f"▶  DRONE GROUND STATION  [{mode_label}]", 18, 16, C_ACCENT)

        sx = W - 260
        status_dot(screen, sx, HDR_H//2, receiver_running)
        ts, _ = font_small.render("RECEIVER", C_TEXT_DIM)
        screen.blit(ts, (sx+12, HDR_H//2 - ts.get_height()//2))
        sx2 = sx + 100
        status_dot(screen, sx2, HDR_H//2, recv_online)
        ts2, _ = font_small.render("DATA FLOW", C_TEXT_DIM)
        screen.blit(ts2, (sx2+12, HDR_H//2 - ts2.get_height()//2))
        up = int(time.time() - uptime_start)
        h_, r = divmod(up, 3600); m_, s_ = divmod(r, 60)
        up_str = f"UP {h_:02d}:{m_:02d}:{s_:02d}"
        ts3, _ = font_small.render(up_str, C_TEXT_DIM)
        screen.blit(ts3, (W - ts3.get_width() - 10, HDR_H//2 - ts3.get_height()//2))

        # LEFT PANEL
        pygame.draw.rect(screen, C_PANEL, (MARGIN-4, HDR_H+4, LEFT_W+8, H-HDR_H-FOOTER_H-2), border_radius=4)
        pygame.draw.rect(screen, C_BORDER, (MARGIN-4, HDR_H+4, LEFT_W+8, H-HDR_H-FOOTER_H-2), 1, border_radius=4)
        draw_glow_text(screen, font_hdr, "COMMAND UPLINK", MARGIN+4, HDR_H+14, C_ACCENT, glow=False)
        draw_separator(screen, MARGIN, HDR_H+30, MARGIN+LEFT_W)
        inp.draw(screen, font_body)
        btn_send.draw(screen, font_btn)
        qlabel_y = btn_start_y - 18
        draw_glow_text(screen, font_hdr, "QUICK COMMANDS", MARGIN+4, qlabel_y, C_ACCENT2, glow=False)
        draw_separator(screen, MARGIN, qlabel_y+14, MARGIN+LEFT_W)
        for btn in qbtns:
            btn.draw(screen, font_btn)
        cfg_y = btn_start_y + (len(QUICK_CMDS)//BTN_COLS + (1 if len(QUICK_CMDS)%BTN_COLS else 0)) * (BTN_H+6) + 14
        draw_glow_text(screen, font_hdr, "CONFIG", MARGIN+4, cfg_y, C_TEXT_DIM, glow=False)
        draw_separator(screen, MARGIN, cfg_y+14, MARGIN+LEFT_W)
        cfg_lines = [
            f"Listen  : :{UDP_LISTEN_PORT}",
            f"Hetzner : {HETZNER_IP}:{HETZNER_PORT}",
            f"DB      : {DB_HOST}/{DB_NAME}",
        ]
        for li, line in enumerate(cfg_lines):
            ts, _ = font_small.render(line, C_TEXT_DIM)
            screen.blit(ts, (MARGIN+6, cfg_y+20 + li*16))
        # RASPBERRY PI section
        pi_y = cfg_y + 20 + 3*16 + 16
        draw_glow_text(screen, font_hdr, "RASPBERRY PI", MARGIN+4, pi_y, C_CYAN, glow=False)
        status_dot(screen, MARGIN + LEFT_W - 10, pi_y + 6, pi_running)
        draw_separator(screen, MARGIN, pi_y+14, MARGIN+LEFT_W)
        pi_lbl_s, _ = font_small.render("RUNNING" if pi_running else "OFFLINE", C_ONLINE if pi_running else C_OFFLINE)
        screen.blit(pi_lbl_s, (MARGIN+6, pi_y+18))
        hint1, _ = font_small.render("F1: Start   F2: Stop", C_TEXT_DIM)
        screen.blit(hint1, (MARGIN+6, pi_y+34))

        btn_clear.rect = pygame.Rect(MARGIN, H - FOOTER_H - MARGIN - 2, LEFT_W, 24)
        btn_clear.draw(screen, font_btn)

        # Divider
        pygame.draw.line(screen, C_BORDER,
                         (MARGIN + LEFT_W + DIVIDER//2, HDR_H+8),
                         (MARGIN + LEFT_W + DIVIDER//2, H-FOOTER_H-4), 1)

        # METRICS PANEL (δεξια, πανω)
        mx = right_x
        my = HDR_H + MARGIN
        mw = right_w
        mh = METRICS_H
        pygame.draw.rect(screen, C_PANEL, (mx, my, mw, mh), border_radius=4)
        pygame.draw.rect(screen, C_BORDER, (mx, my, mw, mh), 1, border_radius=4)
        draw_glow_text(screen, font_hdr, "METRICS", mx+6, my+6, C_CYAN, glow=False)
        draw_separator(screen, mx, my+22, mx+mw)

        with metrics_lock:
            ms = dict(metrics_state)

        packet_loss = 0.0
        if ms["total_sent"] > 0:
            packet_loss = max(0, (ms["total_sent"] - ms["total_recv"]) / ms["total_sent"] * 100)

        col1_x = mx + 8
        col2_x = mx + mw // 3
        col3_x = mx + 2 * mw // 3
        row1_y = my + 28
        row2_y = my + 52
        row3_y = my + 76
        row4_y = my + 100

        def metric_box(x, y, label, value, color):
            lbl, _ = font_small.render(label, C_TEXT_DIM)
            screen.blit(lbl, (x, y))
            val, _ = font_hdr.render(str(value), color)
            screen.blit(val, (x, y + 14))

        metric_box(col1_x, row1_y, "LATENCY LAST",  f"{ms['latency_last']}ms",  C_CYAN)
        metric_box(col2_x, row1_y, "LATENCY AVG",   f"{ms['latency_avg']}ms",   C_ACCENT)
        metric_box(col3_x, row1_y, "LATENCY MIN",   f"{ms['latency_min'] if ms['latency_min'] < 99999 else '-'}ms", C_ACCENT)

        metric_box(col1_x, row2_y, "LATENCY MAX",   f"{ms['latency_max']}ms",   C_ORANGE)
        metric_box(col2_x, row2_y, "PACKET LOSS",   f"{packet_loss:.1f}%",      C_RED if packet_loss > 10 else C_ACCENT)
        metric_box(col3_x, row2_y, "CSQ (RSSI)",    f"{ms['last_csq']}",        C_CYAN)

        metric_box(col1_x, row3_y, "MSGS SENT",     ms["total_sent"],           C_TEXT)
        metric_box(col2_x, row3_y, "MSGS RECV",     ms["total_recv"],           C_TEXT)
        metric_box(col3_x, row3_y, "LAST MSG ID",   ms["last_msg_id"],          C_TEXT_DIM)

        # LOG PANEL
        draw_glow_text(screen, font_hdr, "INCOMING DATA  /  LOG", right_x+4, log_y - 18, C_ACCENT, glow=False)
        draw_separator(screen, right_x, log_y - 4, right_x + right_w)
        log_panel.rect.y      = log_y
        log_panel.rect.height = H - log_y - FOOTER_H - MARGIN
        log_panel.draw(screen, font_mono)

        # Footer
        pygame.draw.line(screen, C_BORDER, (0, H-FOOTER_H), (W, H-FOOTER_H), 1)
        footer_txt = f"Msgs: {len(log_panel.lines)}   |   F1: Start Pi   |   F2: Stop Pi   |   F11: Fullscreen   |   ESC: Quit"
        ts_f, _ = font_small.render(footer_txt, C_TEXT_DIM)
        screen.blit(ts_f, (W//2 - ts_f.get_width()//2, H-FOOTER_H+8))

        pygame.display.flip()
        clock.tick(FPS)

    receiver_running = False
    pygame.quit()
    sys.exit(0)


if __name__ == "__main__":
    main()