"""
Πthon Arena - Client
EECE 350 - Computing Networks Project

Usage: python arena_client.py
"""

import pygame
import socket
import threading
import json
import queue
import sys

# ──────────────────────────────────────────────
#  DISPLAY CONSTANTS  (override if server sends different grid)
# ──────────────────────────────────────────────
SNAKE_COLORS = [
    [  0, 210,  90],  # green
    [ 30, 140, 255],  # blue
    [255,  70,  70],  # red
    [255, 165,   0],  # orange
    [180,   0, 220],  # purple
    [  0, 200, 220],  # cyan
    [255, 220,   0],  # yellow
    [255, 105, 180],  # pink
    [ 80, 200,  80],  # lime
    [200, 200, 200],  # silver
    [255, 140,  60],  # coral
    [  0, 180, 180],  # teal
]

DIR_SYMBOLS = {"UP": "▲", "DOWN": "▼", "LEFT": "◄", "RIGHT": "►"}

CELL        = 22           # pixels per grid cell
GRID_W      = 30           # default; updated from server
GRID_H      = 20
PANEL_W     = 300
LOBBY_W, LOBBY_H = 860, 620
CHAT_LINES  = 7

# ──────────────────────────────────────────────
#  COLOUR PALETTE
# ──────────────────────────────────────────────
C = {
    "bg":          (10,  12,  22),
    "panel":       (18,  22,  40),
    "grid":        (22,  26,  45),
    "snake1":      (0,  210,  90),
    "snake1h":     (80, 255, 150),
    "snake2":      (30, 140, 255),
    "snake2h":     (100,200, 255),
    "pie_normal":  (0,  210,  60),
    "pie_golden":  (255,215,   0),
    "pie_poison":  (190,  0, 230),
    "obstacle":    (120, 80,  35),
    "obstacle_x":  (80,  50,  20),
    "text":        (220,220, 230),
    "dim":         (120,120, 150),
    "accent":      (255,200,   0),
    "danger":      (255, 55,  55),
    "hp1":         (0,  210,  90),
    "hp2":         (30, 140, 255),
    "hp_low":      (255, 55,  55),
    "input_bg":    (28,  32,  55),
    "btn":         (40,  90, 180),
    "btn_hover":   (60, 120, 220),
    "btn_green":   (30, 130,  50),
    "btn_red":     (150, 30,  30),
    "card":        (22,  32,  60),
    "card_hi":     (35,  55, 110),
    "card_border": (50,  75, 140),
    "overlay":     (0,    0,   0, 180),
    "white":       (255,255, 255),
    "black":       (0,    0,   0),
    "win":         (0,  230,  80),
    "lose":        (255, 70,  70),
}


# ──────────────────────────────────────────────
#  UI HELPERS
# ──────────────────────────────────────────────
class TextInput:
    """Single-line text input with placeholder."""
    def __init__(self, rect, placeholder="", font=None, max_len=40):
        self.rect        = pygame.Rect(rect)
        self.placeholder = placeholder
        self.font        = font
        self.max_len     = max_len
        self.text        = ""
        self.active      = False

    def activate(self):
        self.active = True

    def handle(self, event):
        """Handle one event. Returns True if Enter was pressed while active."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
        if self.active and event.type == pygame.KEYDOWN:
            if event.key == pygame.K_BACKSPACE:
                self.text = self.text[:-1]
            elif event.key == pygame.K_RETURN:
                return True
            elif event.key == pygame.K_ESCAPE:
                self.active = False
            elif event.unicode and len(self.text) < self.max_len:
                self.text += event.unicode
        return False

    def draw(self, surf):
        border = C["btn_hover"] if self.active else C["card_border"]
        pygame.draw.rect(surf, C["input_bg"], self.rect, border_radius=7)
        pygame.draw.rect(surf, border,        self.rect, 2, border_radius=7)
        display = self.text if self.text else self.placeholder
        color   = C["text"] if self.text else C["dim"]
        if self.font:
            ts = self.font.render(display, True, color)
            surf.blit(ts, (self.rect.x + 10,
                           self.rect.y + (self.rect.h - ts.get_height()) // 2))


class Button:
    """Simple clickable button."""
    def __init__(self, rect, label, font=None, color=None, hover=None):
        self.rect  = pygame.Rect(rect)
        self.label = label
        self.font  = font
        self.color = color or C["btn"]
        self.hover = hover or C["btn_hover"]

    def draw(self, surf):
        hov = self.rect.collidepoint(pygame.mouse.get_pos())
        pygame.draw.rect(surf, self.hover if hov else self.color,
                         self.rect, border_radius=8)
        if self.font:
            ts = self.font.render(self.label, True, C["text"])
            surf.blit(ts, ts.get_rect(center=self.rect.center))

    def clicked(self, event):
        return (event.type == pygame.MOUSEBUTTONDOWN
                and event.button == 1
                and self.rect.collidepoint(event.pos))


def draw_text(surf, text, font, color, pos, anchor="topleft"):
    ts = font.render(text, True, color)
    r  = ts.get_rect(**{anchor: pos})
    surf.blit(ts, r)
    return r


# ──────────────────────────────────────────────
#  CLIENT APPLICATION
# ──────────────────────────────────────────────
class ArenaClient:
    STATES = ("CONNECT", "USERNAME", "LOBBY", "CUSTOMIZE", "GAME", "GAME_OVER", "WATCHING")

    def __init__(self):
        pygame.init()
        self.screen = pygame.display.set_mode((LOBBY_W, LOBBY_H))
        pygame.display.set_caption("Πthon Arena")
        self.clock  = pygame.time.Clock()

        # Fonts
        self.f_xl  = pygame.font.SysFont("arial", 54, bold=True)
        self.f_lg  = pygame.font.SysFont("arial", 36, bold=True)
        self.f_md  = pygame.font.SysFont("arial", 26)
        self.f_sm  = pygame.font.SysFont("arial", 20)
        self.f_xs  = pygame.font.SysFont("arial", 16)

        # App state
        self.state            = "CONNECT"
        self.username         = ""
        self.player_id        = None      # 1 or 2 once in game
        self.game_id          = None      # id of the game being played
        self.watching_game_id = None      # id of the game being watched
        self.opponent         = ""
        self.lobby_players    = []
        self.lobby_games      = []        # list of {"game_id", "player1", "player2", "viewers"}
        self.lobby_viewing    = []        # usernames currently spectating any game
        self.pending_from     = None      # challenger username
        self.game_state       = None      # latest game_state dict from server
        self.game_over_data   = None
        self.chat_log         = []        # list of strings
        self.error_msg        = ""
        self.error_timer      = 0

        # Customization
        self.custom_color    = [0, 210, 90]   # chosen snake color (RGB list)
        self.key_map         = {              # key_code -> direction string
            pygame.K_UP:    "UP",
            pygame.K_DOWN:  "DOWN",
            pygame.K_LEFT:  "LEFT",
            pygame.K_RIGHT: "RIGHT",
        }
        self.customize_ready = False
        self.binding_slot    = None           # direction being rebound, or None

        # Network
        self.conn       = None
        self.mq         = queue.Queue()
        self.send_lock  = threading.Lock()

        # Game grid (may be updated by server)
        self.gw = GRID_W
        self.gh = GRID_H

        self._build_connect_ui()

    # ── Build UI elements ─────────────────────
    def _build_connect_ui(self):
        cx = LOBBY_W // 2
        self.ip_input   = TextInput((cx-180, 280, 360, 48), "Server IP address", self.f_md)
        self.port_input = TextInput((cx-180, 348, 360, 48), "Port  (default 8000)", self.f_md)
        self.port_input.text = "8000"
        self.conn_btn   = Button  ((cx-100, 420,  200, 52), "Connect", self.f_md)
        self.ip_input.activate()

    def _build_username_ui(self):
        cx = LOBBY_W // 2
        self.name_input = TextInput((cx-200, 320, 400, 52), "Enter your username", self.f_md)
        self.join_btn   = Button  ((cx-110, 392, 220, 52), "Enter the Arena", self.f_md)
        self.name_input.activate()

    # ── Networking ────────────────────────────
    def _send(self, msg: dict):
        if self.conn:
            try:
                with self.send_lock:
                    self.conn.sendall((json.dumps(msg) + "\n").encode())
            except Exception:
                pass

    def _net_thread(self):
        buf = ""
        while True:
            try:
                chunk = self.conn.recv(4096).decode("utf-8", errors="ignore")
                if not chunk:
                    self.mq.put({"type": "_disconnected"})
                    break
                buf += chunk
                while "\n" in buf:
                    line, buf = buf.split("\n", 1)
                    try:
                        self.mq.put(json.loads(line))
                    except Exception:
                        pass
            except Exception:
                self.mq.put({"type": "_disconnected"})
                break

    def _process_queue(self):
        while not self.mq.empty():
            msg = self.mq.get()
            t   = msg.get("type")

            if t == "_disconnected":
                self.state     = "CONNECT"
                self.error_msg = "Disconnected from server."

            elif t == "username_ok":
                self.username = msg["username"]
                self.state    = "LOBBY"
                self.error_msg = ""

            elif t == "username_taken":
                self.error_msg = "Username already taken — try another."

            elif t == "lobby_update":
                self.lobby_players = [p for p in msg.get("players", [])
                                      if p != self.username]
                self.lobby_games   = msg.get("games", [])
                self.lobby_viewing = [v for v in msg.get("viewing", [])
                                      if v != self.username]

            elif t == "challenge_request":
                self.pending_from = msg.get("from")

            elif t == "challenge_sent":
                self.error_msg = f"Challenge sent to {msg.get('target')} — waiting…"

            elif t == "challenge_declined":
                self.error_msg = f"{msg.get('from')} declined your challenge."

            elif t == "game_start":
                self.player_id       = msg["player_id"]
                self.game_id         = msg.get("game_id", "")
                self.opponent        = msg.get("opponent", "")
                self.gw              = msg.get("grid_w", GRID_W)
                self.gh              = msg.get("grid_h", GRID_H)
                self.state           = "CUSTOMIZE"
                self.game_state      = None
                self.game_over_data  = None
                self.chat_log        = []
                self.error_msg       = ""
                self.customize_ready = False
                self.binding_slot    = None
                self.custom_color    = ([0, 210, 90] if self.player_id == 1
                                        else [30, 140, 255])
                self.screen = pygame.display.set_mode((LOBBY_W, LOBBY_H))

            elif t == "game_begin":
                self.state = "GAME"
                sw = self.gw * CELL + PANEL_W
                sh = self.gh * CELL
                self.screen = pygame.display.set_mode((sw, sh))

            elif t == "watch_ok":
                self.watching_game_id = msg.get("game_id", "")
                self.gw    = msg.get("grid_w", GRID_W)
                self.gh    = msg.get("grid_h", GRID_H)
                self.state = "WATCHING"
                self.chat_log = []
                sw = self.gw * CELL + PANEL_W
                sh = self.gh * CELL
                self.screen = pygame.display.set_mode((sw, sh))

            elif t == "game_state":
                self.game_state = msg

            elif t == "game_over":
                self.game_over_data = msg
                self.state          = "GAME_OVER"

            elif t in ("game_chat", "lobby_chat"):
                line = f"{msg.get('from','?')}: {msg.get('msg','')}"
                self.chat_log.append(line)
                if len(self.chat_log) > 80:
                    self.chat_log.pop(0)

            elif t == "error":
                self.error_msg = msg.get("msg", "Unknown error")

    def _set_error(self, msg):
        self.error_msg   = msg
        self.error_timer = 240   # frames

    # ── Try to connect to server ──────────────
    def _try_connect(self):
        ip   = self.ip_input.text.strip() or socket.gethostbyname(socket.gethostname())
        try:
            port = int(self.port_input.text.strip() or "8000")
        except ValueError:
            self._set_error("Invalid port number.")
            return
        try:
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.settimeout(5)
            self.conn.connect((ip, port))
            self.conn.settimeout(None)
            threading.Thread(target=self._net_thread, daemon=True).start()
            self.state     = "USERNAME"
            self.error_msg = ""
            self._build_username_ui()
        except Exception as e:
            self._set_error(f"Connection failed: {e}")

    # ──────────────────────────────────────────
    #  DRAW SCREENS
    # ──────────────────────────────────────────
    def _draw_connect(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        # Decorative grid lines
        for x in range(0, sw, 40):
            pygame.draw.line(self.screen, C["grid"], (x, 0), (x, sh))
        for y in range(0, sh, 40):
            pygame.draw.line(self.screen, C["grid"], (0, y), (sw, y))

        # Title
        draw_text(self.screen, "Πthon Arena", self.f_xl, C["accent"],
                  (sw//2, 130), "center")
        draw_text(self.screen, "Online Two-Player Snake Battle — EECE 350",
                  self.f_sm, C["dim"], (sw//2, 195), "center")

        self.ip_input.rect.centerx   = sw // 2
        self.port_input.rect.centerx = sw // 2
        self.conn_btn.rect.centerx   = sw // 2

        self.ip_input.draw(self.screen)
        self.port_input.draw(self.screen)
        self.conn_btn.draw(self.screen)

        if self.error_msg:
            draw_text(self.screen, self.error_msg, self.f_sm, C["danger"],
                      (sw//2, 495), "center")

    def _draw_username(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        draw_text(self.screen, "Πthon Arena", self.f_xl, C["accent"],
                  (sw//2, 140), "center")
        draw_text(self.screen, "Choose your arena name", self.f_md, C["dim"],
                  (sw//2, 220), "center")

        self.name_input.rect.centerx = sw // 2
        self.join_btn.rect.centerx   = sw // 2
        self.name_input.draw(self.screen)
        self.join_btn.draw(self.screen)

        if self.error_msg:
            draw_text(self.screen, self.error_msg, self.f_sm, C["danger"],
                      (sw//2, 460), "center")

    def _draw_lobby(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        # Header bar
        pygame.draw.rect(self.screen, C["panel"], (0, 0, sw, 72))
        draw_text(self.screen, "Πthon Arena", self.f_lg, C["accent"], (24, 18))
        draw_text(self.screen, f"Logged in as  {self.username}", self.f_sm,
                  C["dim"], (sw - 20, 25), "topright")

        # Section title
        draw_text(self.screen, "Online Players", self.f_md, C["text"], (24, 90))

        # Player cards (challengeable) + viewer rows
        btn_rects  = {}   # player → challenge button rect
        all_rows   = ([(p, "lobby")   for p in self.lobby_players] +
                      [(v, "viewing") for v in self.lobby_viewing])
        if not all_rows:
            draw_text(self.screen, "No other players online — waiting for opponents…",
                      self.f_sm, C["dim"], (24, 130))
        else:
            for i, (name, role) in enumerate(all_rows[:8]):
                y    = 122 + i * 62
                card = pygame.Rect(24, y, sw - 280, 52)
                hi   = card.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(self.screen, C["card_hi"] if hi else C["card"],
                                 card, border_radius=9)
                pygame.draw.rect(self.screen, C["card_border"], card, 1, border_radius=9)

                if role == "lobby":
                    draw_text(self.screen, f"🐍  {name}", self.f_sm, C["text"],
                              (card.x + 18, card.y + 15))
                    ch_r   = pygame.Rect(card.right + 12, y + 8, 130, 36)
                    hov_ch = ch_r.collidepoint(pygame.mouse.get_pos())
                    pygame.draw.rect(self.screen, C["btn_hover"] if hov_ch else C["btn"],
                                     ch_r, border_radius=7)
                    draw_text(self.screen, "Challenge", self.f_xs, C["text"],
                              ch_r.center, "center")
                    btn_rects[name] = ch_r
                else:
                    draw_text(self.screen, f"👁  {name}  — watching",
                              self.f_sm, C["dim"], (card.x + 18, card.y + 15))

        # Live Games panel (right column)
        lg_x = sw - 258
        draw_text(self.screen, "Live Games", self.f_sm, C["text"], (lg_x, 90))
        watch_btns = {}   # game_id -> Rect
        if not self.lobby_games:
            draw_text(self.screen, "No games in progress",
                      self.f_xs, C["dim"], (lg_x, 120))
        else:
            for i, ginfo in enumerate(self.lobby_games[:6]):
                gid      = ginfo["game_id"]
                label    = f"{ginfo['player1']} vs {ginfo['player2']}"
                n_view   = ginfo.get("viewers", 0)
                gy       = 118 + i * 52
                gcard    = pygame.Rect(lg_x - 4, gy - 4, 240, 44)
                pygame.draw.rect(self.screen, C["card"], gcard, border_radius=7)
                pygame.draw.rect(self.screen, C["card_border"], gcard, 1, border_radius=7)
                draw_text(self.screen, label[:22], self.f_xs, C["text"], (lg_x + 4, gy + 4))
                if n_view:
                    draw_text(self.screen, f"👁 {n_view}", self.f_xs, C["dim"],
                              (lg_x + 4, gy + 20))
                wrect = pygame.Rect(lg_x + 152, gy + 8, 74, 26)
                hov_w = wrect.collidepoint(pygame.mouse.get_pos())
                pygame.draw.rect(self.screen,
                                 (70, 50, 140) if hov_w else (50, 35, 110),
                                 wrect, border_radius=6)
                draw_text(self.screen, "👁 Watch", self.f_xs, C["text"],
                          wrect.center, "center")
                watch_btns[gid] = wrect

        # Lobby chat panel
        chat_panel = pygame.Rect(24, sh - 200, sw - 48, 180)
        pygame.draw.rect(self.screen, C["panel"], chat_panel, border_radius=10)
        pygame.draw.rect(self.screen, C["card_border"], chat_panel, 1, border_radius=10)
        draw_text(self.screen, "Lobby Chat", self.f_xs, C["dim"],
                  (chat_panel.x + 12, chat_panel.y + 8))

        visible = self.chat_log[-6:]
        for j, line in enumerate(visible):
            draw_text(self.screen, line[:80], self.f_xs, C["text"],
                      (chat_panel.x + 12, chat_panel.y + 28 + j * 18))

        # Chat input
        ci_rect = pygame.Rect(chat_panel.x + 4, chat_panel.bottom - 38,
                              chat_panel.w - 8, 32)
        if not hasattr(self, "_lobby_chat_input"):
            self._lobby_chat_input = TextInput(ci_rect, "Press Enter to chat…",
                                               self.f_xs, max_len=80)
        self._lobby_chat_input.rect = ci_rect
        self._lobby_chat_input.draw(self.screen)

        # Challenge notification popup
        acc_btn = dec_btn = None
        if self.pending_from:
            ox, oy, ow, oh = sw//2-220, sh//2-90, 440, 180
            pygame.draw.rect(self.screen, C["panel"],
                             (ox, oy, ow, oh), border_radius=14)
            pygame.draw.rect(self.screen, C["accent"],
                             (ox, oy, ow, oh), 2, border_radius=14)
            draw_text(self.screen,
                      f"{self.pending_from}  challenged you!",
                      self.f_md, C["accent"], (sw//2, oy + 35), "center")
            acc_btn = Button((sw//2 - 130, oy + 90, 115, 42), "✓  Accept",
                             self.f_sm, C["btn_green"], (50, 180, 70))
            dec_btn = Button((sw//2 + 15,  oy + 90, 115, 42), "✗  Decline",
                             self.f_sm, C["btn_red"],   (200, 50, 50))
            acc_btn.draw(self.screen)
            dec_btn.draw(self.screen)

        # Error / info bar
        if self.error_msg:
            draw_text(self.screen, self.error_msg, self.f_xs, C["danger"],
                      (24, sh - 215))

        return btn_rects, watch_btns, acc_btn, dec_btn

    # ── Customization screen ──────────────────
    def _draw_customize(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        for x in range(0, sw, 40):
            pygame.draw.line(self.screen, C["grid"], (x, 0), (x, sh))
        for y in range(0, sh, 40):
            pygame.draw.line(self.screen, C["grid"], (0, y), (sw, y))

        draw_text(self.screen, "Customize Your Snake", self.f_lg, C["accent"],
                  (sw // 2, 45), "center")
        draw_text(self.screen, f"vs  {self.opponent}", self.f_sm, C["dim"],
                  (sw // 2, 100), "center")

        pygame.draw.line(self.screen, C["card_border"], (30, 128), (sw - 30, 128), 1)
        pygame.draw.line(self.screen, C["card_border"], (sw // 2, 128), (sw // 2, sh - 85), 1)

        # ── Left panel: color picker ─────────────────
        lx = 50
        draw_text(self.screen, "Snake Color", self.f_md, C["text"], (lx, 145))

        # Mini snake preview
        prev_color = tuple(self.custom_color)
        prev_head  = tuple(min(255, v + 60) for v in self.custom_color)
        for i in range(5):
            r = pygame.Rect(lx + i * 34, 190, 30, 30)
            c = prev_head if i == 0 else prev_color
            pygame.draw.rect(self.screen, c, r, border_radius=5 if i == 0 else 3)
            if i == 0:
                pygame.draw.circle(self.screen, C["black"], (r.x + 9,  r.y + 9),  3)
                pygame.draw.circle(self.screen, C["black"], (r.x + 20, r.y + 9),  3)
                pygame.draw.circle(self.screen, C["white"], (r.x + 10, r.y + 8),  1)
                pygame.draw.circle(self.screen, C["white"], (r.x + 21, r.y + 8),  1)

        # Color swatches — 2 rows of 6
        swatch_rects = {}
        for idx, color in enumerate(SNAKE_COLORS):
            row, col_i = divmod(idx, 6)
            sx = lx + col_i * 58
            sy = 242 + row * 62
            rect = pygame.Rect(sx, sy, 50, 50)
            swatch_rects[idx] = rect
            pygame.draw.rect(self.screen, tuple(color), rect, border_radius=8)
            border = C["white"] if list(color) == self.custom_color else C["card_border"]
            bw     = 3         if list(color) == self.custom_color else 1
            pygame.draw.rect(self.screen, border, rect, bw, border_radius=8)

        # ── Right panel: key bindings ─────────────────
        rx = sw // 2 + 24
        draw_text(self.screen, "Movement Keys", self.f_md, C["text"], (rx, 145))

        dir_to_key   = {v: k for k, v in self.key_map.items()}
        key_slot_rects = {}
        for i, (direction, symbol) in enumerate(DIR_SYMBOLS.items()):
            ry = 182 + i * 72
            row_r = pygame.Rect(rx, ry, 366, 58)
            pygame.draw.rect(self.screen, C["card"], row_r, border_radius=8)

            draw_text(self.screen, symbol,    self.f_lg, C["text"],   (rx + 18, ry + 10))
            draw_text(self.screen, direction, self.f_sm, C["dim"],    (rx + 52, ry + 17))

            kcode = dir_to_key.get(direction)
            kname = pygame.key.name(kcode).upper() if kcode else "—"
            is_binding = (self.binding_slot == direction)

            kbox = pygame.Rect(rx + 238, ry + 11, 110, 36)
            key_slot_rects[direction] = kbox
            kbg  = C["btn_hover"] if is_binding else (
                   C["btn"] if kbox.collidepoint(pygame.mouse.get_pos()) else C["input_bg"])
            pygame.draw.rect(self.screen, kbg, kbox, border_radius=6)
            pygame.draw.rect(self.screen,
                             C["accent"] if is_binding else C["card_border"],
                             kbox, 2, border_radius=6)
            draw_text(self.screen,
                      "Press key…" if is_binding else kname,
                      self.f_sm,
                      C["accent"] if is_binding else C["text"],
                      kbox.center, "center")

        # ── Ready / waiting ───────────────────────────
        ready_r = pygame.Rect(sw // 2 - 120, sh - 78, 240, 52)
        if self.customize_ready:
            draw_text(self.screen, "Waiting for opponent…", self.f_sm, C["dim"],
                      (sw // 2, sh - 52), "center")
        else:
            hov = ready_r.collidepoint(pygame.mouse.get_pos())
            pygame.draw.rect(self.screen,
                             C["btn_hover"] if hov else C["btn_green"],
                             ready_r, border_radius=10)
            draw_text(self.screen, "✓  Ready", self.f_md, C["text"],
                      ready_r.center, "center")

        return swatch_rects, key_slot_rects, ready_r

    # ── Game / Watching screen ────────────────
    def _draw_game(self):
        gw, gh = self.gw, self.gh
        sw, sh = gw * CELL, gh * CELL
        full_w = sw + PANEL_W
        self.screen.fill(C["bg"])

        # Grid lines
        for x in range(0, sw + 1, CELL):
            pygame.draw.line(self.screen, C["grid"], (x, 0), (x, sh))
        for y in range(0, sh + 1, CELL):
            pygame.draw.line(self.screen, C["grid"], (0, y), (sw, y))

        if not self.game_state:
            draw_text(self.screen, "Waiting for first game state…",
                      self.f_md, C["dim"], (sw//2, sh//2), "center")
            self._draw_panel(sw, sh, full_w)
            return

        gs = self.game_state

        # Obstacles
        for ox, oy in gs.get("obstacles", []):
            r = pygame.Rect(ox*CELL+1, oy*CELL+1, CELL-2, CELL-2)
            pygame.draw.rect(self.screen, C["obstacle"], r, border_radius=3)
            pygame.draw.line(self.screen, C["obstacle_x"],
                             r.topleft, r.bottomright, 2)
            pygame.draw.line(self.screen, C["obstacle_x"],
                             r.topright, r.bottomleft, 2)

        # Pies
        for pie in gs.get("pies", []):
            px, py = pie["pos"]
            color  = tuple(pie.get("color", [0, 200, 60]))
            cx_    = px * CELL + CELL // 2
            cy_    = py * CELL + CELL // 2
            r      = CELL // 2 - 1
            pygame.draw.circle(self.screen, color, (cx_, cy_), r)
            pygame.draw.circle(self.screen, C["white"], (cx_, cy_), r, 1)
            # Shine dot
            pygame.draw.circle(self.screen, C["white"],
                               (cx_ - r//3, cy_ - r//3), max(1, r//4))

        # Power-ups (diamonds)
        for pu in gs.get("powerups", []):
            px_, py_ = pu["pos"]
            color    = tuple(pu.get("color", [200, 200, 200]))
            cx_      = px_ * CELL + CELL // 2
            cy_      = py_ * CELL + CELL // 2
            r        = CELL // 2 - 1
            pts      = [(cx_, cy_ - r), (cx_ + r, cy_),
                        (cx_, cy_ + r), (cx_ - r, cy_)]
            pygame.draw.polygon(self.screen, color, pts)
            pygame.draw.polygon(self.screen, C["white"], pts, 1)
            pygame.draw.circle(self.screen, C["white"],
                               (cx_ - r // 3, cy_ - r // 3), max(1, r // 4))

        # Snakes — colors come from the game state (set during customization)
        for pid_s, snake in gs.get("snakes", {}).items():
            raw    = snake.get("color", [200, 200, 200])
            body_c = tuple(raw)
            head_c = tuple(min(255, v + 60) for v in raw)
            if not snake.get("alive", True):
                body_c = head_c = tuple(max(0, v - 120) for v in raw)

            for i, (bx, by) in enumerate(snake.get("body", [])):
                rect = pygame.Rect(bx*CELL+1, by*CELL+1, CELL-2, CELL-2)
                if not snake.get("alive", True):
                    pygame.draw.rect(self.screen, body_c, rect, border_radius=2)
                elif i == 0:
                    pygame.draw.rect(self.screen, head_c, rect, border_radius=5)
                    # Eyes
                    ex, ey = rect.centerx, rect.centery
                    pygame.draw.circle(self.screen, C["black"], (ex-3, ey-3), 3)
                    pygame.draw.circle(self.screen, C["black"], (ex+3, ey-3), 3)
                    pygame.draw.circle(self.screen, C["white"], (ex-2, ey-4), 1)
                    pygame.draw.circle(self.screen, C["white"], (ex+4, ey-4), 1)
                else:
                    pygame.draw.rect(self.screen, body_c, rect, border_radius=3)

        self._draw_panel(sw, sh, full_w)

    def _draw_panel(self, game_w, game_h, full_w):
        px = game_w
        pygame.draw.rect(self.screen, C["panel"],
                         (px, 0, PANEL_W, game_h))
        pygame.draw.line(self.screen, C["card_border"],
                         (px, 0), (px, game_h), 2)

        gs        = self.game_state or {}
        snakes    = gs.get("snakes", {})
        usernames = gs.get("usernames", {})
        time_left = gs.get("time_left", 0)

        EFF_COLOR = {"shield": (180, 180, 220), "freeze": (0, 210, 240),
                     "double": (255, 200, 50)}
        EFF_LABEL = {"shield": "🛡 Shield", "freeze": "❄ Frozen!",
                     "double": "⭐ 2× Pies"}

        y = 14
        # Player health panels
        effects = gs.get("effects", {})
        for pid_s in ("1", "2"):
            snake  = snakes.get(pid_s, {})
            raw    = snake.get("color", [200, 200, 200])
            body_c = tuple(raw)
            uname  = usernames.get(pid_s, f"Player {pid_s}")
            hp     = snake.get("health", 0)
            alive  = snake.get("alive", True)
            me     = (int(pid_s) == self.player_id)

            label = f"{'▶ ' if me else ''}{uname}{'  (you)' if me else ''}"
            col   = body_c if alive else C["dim"]
            draw_text(self.screen, label, self.f_sm, col, (px + 10, y))
            y += 24

            # HP bar
            bar = pygame.Rect(px + 10, y, PANEL_W - 22, 16)
            pygame.draw.rect(self.screen, C["input_bg"], bar, border_radius=5)
            w = int(bar.w * max(0, hp) / 200)
            if w > 0:
                bc = body_c if hp > 40 else C["hp_low"]
                pygame.draw.rect(self.screen, bc,
                                 pygame.Rect(bar.x, bar.y, w, bar.h),
                                 border_radius=5)
            pygame.draw.rect(self.screen, C["card_border"], bar, 1, border_radius=5)
            draw_text(self.screen, f"HP {hp}", self.f_xs, C["text"],
                      (bar.x + 5, bar.y + 2))
            y += 20

            # Active effects badges
            for eff in effects.get(pid_s, []):
                draw_text(self.screen, EFF_LABEL.get(eff, eff),
                          self.f_xs, EFF_COLOR.get(eff, C["dim"]), (px + 12, y))
                y += 13
            y += 8

        y += 4
        # Timer
        tc = C["danger"] if time_left < 20 else C["accent"]
        pygame.draw.rect(self.screen, C["card"],
                         (px + 10, y, PANEL_W - 22, 34), border_radius=7)
        draw_text(self.screen, f"⏱  {int(time_left)} s remaining",
                  self.f_sm, tc, (px + PANEL_W//2, y + 10), "center")
        y += 46

        # Legend
        draw_text(self.screen, "Legend", self.f_xs, C["dim"], (px + 10, y))
        y += 18
        legend = [
            (C["pie_normal"],  "Normal Pie   +15 HP"),
            (C["pie_golden"],  "Golden Pie   +30 HP"),
            (C["pie_poison"],  "Poison Pie   −20 HP"),
            (C["obstacle"],    "Obstacle     −25 HP"),
            (C["danger"],      "Wall hit     −30 HP"),
            ((180, 180, 220),  "◆ Shield     next hit"),
            ((  0, 210, 240),  "◆ Freeze     opp. 5s"),
            ((255, 200,  50),  "◆ 2× Pies   5s buff"),
        ]
        for color, label in legend:
            pygame.draw.rect(self.screen, color,
                             (px + 10, y + 2, 13, 13), border_radius=3)
            draw_text(self.screen, label, self.f_xs, C["dim"], (px + 28, y))
            y += 18

        y += 8
        # Controls hint (only if playing, not watching)
        if self.state == "GAME":
            hint_lines = ["Arrow keys / WASD: move", "T + Enter: chat"]
        else:
            hint_lines = ["Watching…", "T + Enter: cheer"]
        for hl in hint_lines:
            draw_text(self.screen, hl, self.f_xs, C["dim"], (px + 10, y))
            y += 16

        # Chat area
        chat_top = max(y + 10, game_h - CHAT_LINES * 17 - 50)
        draw_text(self.screen, "Chat", self.f_xs, C["dim"], (px + 10, chat_top))
        for j, line in enumerate(self.chat_log[-CHAT_LINES:]):
            draw_text(self.screen, line[:34], self.f_xs, C["text"],
                      (px + 6, chat_top + 18 + j * 17))

        # Chat input box at bottom of panel
        ci = pygame.Rect(px + 5, game_h - 34, PANEL_W - 10, 28)
        if not hasattr(self, "_game_chat_input"):
            self._game_chat_input = TextInput(ci, "T → chat…", self.f_xs, max_len=60)
        self._game_chat_input.rect = ci
        self._game_chat_input.draw(self.screen)

    def _draw_game_over(self):
        self._draw_game()   # render last game state behind

        sw, sh = self.screen.get_size()
        ov = pygame.Surface((sw, sh), pygame.SRCALPHA)
        ov.fill((0, 0, 0, 160))
        self.screen.blit(ov, (0, 0))

        pd = self.game_over_data or {}
        winner = pd.get("winner", "?")
        scores = pd.get("scores", {})

        pw, ph = 480, 300
        pr = pygame.Rect(sw//2 - pw//2, sh//2 - ph//2, pw, ph)
        pygame.draw.rect(self.screen, C["panel"], pr, border_radius=16)
        pygame.draw.rect(self.screen, C["accent"], pr, 3,  border_radius=16)

        draw_text(self.screen, "GAME OVER", self.f_xl, C["accent"],
                  (sw//2, pr.y + 30), "center")

        if winner == "TIE":
            rtxt, rcol = "It's a Tie!", C["text"]
        elif winner == self.username:
            rtxt, rcol = "🏆  You Win!", C["win"]
        else:
            rtxt, rcol = f"{winner} Wins!", C["lose"]

        draw_text(self.screen, rtxt, self.f_lg, rcol,
                  (sw//2, pr.y + 100), "center")

        y = pr.y + 150
        for uname, hp in scores.items():
            draw_text(self.screen, f"{uname}:  {hp} HP", self.f_md, C["text"],
                      (sw//2, y), "center")
            y += 36

        back_btn = Button((sw//2 - 115, pr.bottom - 62, 230, 46),
                          "Back to Lobby", self.f_md)
        back_btn.draw(self.screen)
        return back_btn

    # ──────────────────────────────────────────
    #  MAIN LOOP
    # ──────────────────────────────────────────
    def run(self):
        # Per-screen persistent state
        lobby_btn_rects  = {}
        watch_btns       = {}    # game_id -> Rect
        acc_btn = dec_btn = None
        back_btn          = None

        # Customize screen rects (refreshed each frame)
        cust_swatch_rects  = {}   # idx -> Rect
        cust_key_rects     = {}   # direction -> Rect
        cust_ready_r       = None

        chat_active = False   # in-game chat input focus

        while True:
            self.clock.tick(60)
            self._process_queue()

            events = pygame.event.get()
            for event in events:
                if event.type == pygame.QUIT:
                    pygame.quit()
                    sys.exit()

                # ── CONNECT ───────────────────
                if self.state == "CONNECT":
                    self.ip_input.handle(event)
                    entered = self.port_input.handle(event)
                    if self.conn_btn.clicked(event) or entered:
                        self._try_connect()

                # ── USERNAME ──────────────────
                elif self.state == "USERNAME":
                    entered = self.name_input.handle(event)
                    if self.join_btn.clicked(event) or entered:
                        uname = self.name_input.text.strip()
                        if uname:
                            self._send({"type": "username", "username": uname})

                # ── LOBBY ─────────────────────
                elif self.state == "LOBBY":
                    if not hasattr(self, "_lobby_chat_input"):
                        from types import SimpleNamespace
                        self._lobby_chat_input = TextInput(
                            (0, 0, 100, 30), "", self.f_xs, 80)

                    lci_entered = self._lobby_chat_input.handle(event)
                    if lci_entered and self._lobby_chat_input.text.strip():
                        self._send({"type": "lobby_chat",
                                    "msg": self._lobby_chat_input.text.strip()})
                        self._lobby_chat_input.text = ""

                    if self.pending_from:
                        if acc_btn and acc_btn.clicked(event):
                            self._send({"type": "challenge_response",
                                        "from": self.pending_from, "accepted": True})
                            self.pending_from = None
                        elif dec_btn and dec_btn.clicked(event):
                            self._send({"type": "challenge_response",
                                        "from": self.pending_from, "accepted": False})
                            self.pending_from = None
                    else:
                        # Challenge buttons
                        for player, rect in lobby_btn_rects.items():
                            if event.type == pygame.MOUSEBUTTONDOWN and rect.collidepoint(event.pos):
                                self._send({"type": "challenge", "target": player})
                        # Per-game watch buttons
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            for gid, wrect in watch_btns.items():
                                if wrect.collidepoint(event.pos):
                                    self._send({"type": "watch", "game_id": gid})
                                    break

                # ── CUSTOMIZE ─────────────────
                elif self.state == "CUSTOMIZE":
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        # Color swatch
                        for idx, rect in cust_swatch_rects.items():
                            if rect.collidepoint(event.pos):
                                self.custom_color = list(SNAKE_COLORS[idx])
                                self.binding_slot = None
                        # Key slot (only if not already ready)
                        if not self.customize_ready:
                            for direction, rect in cust_key_rects.items():
                                if rect.collidepoint(event.pos):
                                    self.binding_slot = direction
                        # Ready button
                        if (not self.customize_ready and cust_ready_r
                                and cust_ready_r.collidepoint(event.pos)):
                            self._send({"type": "player_ready",
                                        "color": self.custom_color})
                            self.customize_ready = True
                            self.binding_slot    = None
                    elif event.type == pygame.KEYDOWN:
                        if self.binding_slot:
                            direction = self.binding_slot
                            # Remove any existing mapping for this key or direction
                            self.key_map = {k: v for k, v in self.key_map.items()
                                            if k != event.key and v != direction}
                            self.key_map[event.key] = direction
                            self.binding_slot = None
                        elif event.key == pygame.K_ESCAPE:
                            self.binding_slot = None

                # ── GAME / WATCHING ───────────
                elif self.state in ("GAME", "WATCHING"):
                    if not hasattr(self, "_game_chat_input"):
                        from types import SimpleNamespace
                        self._game_chat_input = TextInput(
                            (0, 0, 100, 30), "", self.f_xs, 60)

                    gci_entered = self._game_chat_input.handle(event)
                    if gci_entered and self._game_chat_input.text.strip():
                        self._send({"type": "game_chat",
                                    "msg": self._game_chat_input.text.strip()})
                        self._game_chat_input.text = ""
                        chat_active = False

                    # Keyboard movement (only when chat input not focused)
                    if (self.state == "GAME" and event.type == pygame.KEYDOWN
                            and not self._game_chat_input.active):
                        direction = self.key_map.get(event.key)
                        if direction:
                            self._send({"type": "move", "direction": direction})

                    # 'T' key activates chat
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                        if not self._game_chat_input.active:
                            self._game_chat_input.activate()

                # ── GAME OVER ─────────────────
                elif self.state == "GAME_OVER":
                    if back_btn and back_btn.clicked(event):
                        self.state = "LOBBY"
                        self.screen = pygame.display.set_mode((LOBBY_W, LOBBY_H))
                        self.__dict__.pop("_game_chat_input", None)

            # ── DRAW ──────────────────────────
            if self.state == "CONNECT":
                self._draw_connect()
            elif self.state == "USERNAME":
                self._draw_username()
            elif self.state == "LOBBY":
                lobby_btn_rects, watch_btns, acc_btn, dec_btn = self._draw_lobby()
            elif self.state == "CUSTOMIZE":
                cust_swatch_rects, cust_key_rects, cust_ready_r = self._draw_customize()
            elif self.state in ("GAME", "WATCHING"):
                self._draw_game()
            elif self.state == "GAME_OVER":
                back_btn = self._draw_game_over()

            pygame.display.flip()


# ──────────────────────────────────────────────
if __name__ == "__main__":
    ArenaClient().run()
