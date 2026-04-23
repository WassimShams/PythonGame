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
import math

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

DIR_SYMBOLS = {"UP": "^", "DOWN": "v", "LEFT": "<", "RIGHT": ">"}
MODE_ORDER = ["base", "sudden_death", "fog_of_war", "best_of_3"]
MODE_LABELS = {
    "base": "Base",
    "sudden_death": "Sudden Death",
    "fog_of_war": "Fog of War",
    "best_of_3": "Best of 3",
}
MODE_BLURBS = {
    "base": "Standard one-round match with power-ups enabled.",
    "sudden_death": "Short round, no power-ups, shrinking safe zone, snake clashes kill instantly.",
    "fog_of_war": "Standard round with limited vision around each snake head.",
    "best_of_3": "First player to win two rounds takes the match.",
}
MAP_ORDER = ["ember", "frost", "vault"]
MAP_LABELS = {
    "ember": "Ember Forge",
    "frost": "Frost Lattice",
    "vault": "Vault Rings",
}
MAP_THEMES = {
    "ember": {
        "board_bg": (33, 22, 18),
        "grid": (74, 44, 34),
        "obstacle": (124, 72, 43),
        "obstacle_x": (78, 38, 18),
        "safe_zone": (255, 120, 80),
        "accent": (255, 170, 90),
    },
    "frost": {
        "board_bg": (19, 29, 41),
        "grid": (54, 82, 112),
        "obstacle": (93, 138, 176),
        "obstacle_x": (50, 81, 108),
        "safe_zone": (160, 225, 255),
        "accent": (150, 220, 255),
    },
    "vault": {
        "board_bg": (24, 23, 35),
        "grid": (58, 55, 84),
        "obstacle": (126, 100, 155),
        "obstacle_x": (77, 53, 100),
        "safe_zone": (220, 175, 255),
        "accent": (205, 160, 255),
    },
}

CELL        = 22           # pixels per grid cell
GRID_W      = 36           # default; updated from server
GRID_H      = 24
PANEL_W     = 320
LOBBY_W, LOBBY_H = 1140, 760
CHAT_LINES  = 7
BASE_GAME_W = GRID_W * CELL + PANEL_W
BASE_GAME_H = GRID_H * CELL
WINDOW_W    = max(LOBBY_W, BASE_GAME_W)
WINDOW_H    = max(LOBBY_H, BASE_GAME_H)
RESERVED_BIND_KEYS = {pygame.K_t, pygame.K_RETURN, pygame.K_ESCAPE}

# ──────────────────────────────────────────────
#  COLOUR PALETTE
# ──────────────────────────────────────────────
C = {
    "bg":          (15,  18,  25),  # Dark navy background
    "panel":       (25,  30,  40),  # Darker panel
    "grid":        (35,  40,  50),  # Subtle grid lines
    "snake1":      (0,   150, 255), # Bright blue
    "snake1h":     (100, 200, 255), # Lighter blue
    "snake2":      (255, 100, 150), # Pink
    "snake2h":     (255, 150, 200), # Lighter pink
    "pie_normal":  (100, 200, 100), # Green
    "pie_golden":  (255, 215,  50), # Gold
    "pie_poison":  (200,  50, 150), # Purple
    "obstacle":    (80,  60,  40),  # Brown
    "obstacle_x":  (60,  40,  20),  # Darker brown
    "text":        (240, 240, 245), # Off-white text
    "dim":         (150, 150, 160), # Dim text
    "accent":      (100, 200, 255), # Cyan accent
    "danger":      (255, 80,  80),  # Red
    "hp1":         (0,   150, 255), # Blue HP
    "hp2":         (255, 100, 150), # Pink HP
    "hp_low":      (255, 80,  80),  # Red low HP
    "input_bg":    (35,  40,  55),  # Input background
    "btn":         (50,  60,  80),  # Button
    "btn_hover":   (80,  100, 130), # Hover
    "btn_green":   (50,  150, 100), # Green button
    "btn_red":     (200, 50,  50),  # Red button
    "card":        (30,  35,  50),  # Card background
    "card_hi":     (50,  60,  80),  # Highlighted card
    "card_border": (70,  80,  100), # Border
    "overlay":     (0,    0,   0, 180), # Overlay
    "white":       (255, 255, 255),
    "black":       (0,    0,   0),
    "win":         (50,  200, 100),
    "lose":        (255, 80,  80),
}


# ──────────────────────────────────────────────
#  UI HELPERS
# ──────────────────────────────────────────────
def filter_plain_text(text):
    return "".join(ch for ch in text if ch.isprintable() and ch not in "\r\n\t")


def filter_ip_text(text):
    return "".join(ch for ch in text if ch.isdigit() or ch == ".")


def filter_digits(text):
    return "".join(ch for ch in text if ch.isdigit())


class TextInput:
    """Single-line text input with placeholder."""
    def __init__(self, rect, placeholder="", font=None, max_len=40, text_filter=None):
        self.rect        = pygame.Rect(rect)
        self.placeholder = placeholder
        self.font        = font
        self.max_len     = max_len
        self.text        = ""
        self.active      = False
        self.cursor      = 0
        self.view_start  = 0
        self.text_filter = text_filter or filter_plain_text

    def activate(self):
        self.active = True

    def set_text(self, text):
        self.text = self.text_filter(text)[:self.max_len]
        self.cursor = len(self.text)
        self._ensure_cursor_visible()

    def _text_width(self, text):
        if not self.font or not text:
            return 0
        return self.font.size(text)[0]

    def _inner_width(self):
        return max(0, self.rect.w - 20)

    def _ensure_cursor_visible(self):
        self.view_start = min(self.view_start, self.cursor)
        while self._text_width(self.text[self.view_start:self.cursor]) > self._inner_width():
            self.view_start += 1

    def _visible_text(self):
        self._ensure_cursor_visible()
        end = self.view_start
        while end < len(self.text):
            if self._text_width(self.text[self.view_start:end + 1]) > self._inner_width():
                break
            end += 1
        return self.text[self.view_start:end]

    def _insert_text(self, raw_text):
        filtered = self.text_filter(raw_text)
        if not filtered:
            return
        room = self.max_len - len(self.text)
        if room <= 0:
            return
        filtered = filtered[:room]
        self.text = self.text[:self.cursor] + filtered + self.text[self.cursor:]
        self.cursor += len(filtered)
        self._ensure_cursor_visible()

    def _delete_back(self):
        if self.cursor <= 0:
            return
        self.text = self.text[:self.cursor - 1] + self.text[self.cursor:]
        self.cursor -= 1
        self._ensure_cursor_visible()

    def _delete_forward(self):
        if self.cursor >= len(self.text):
            return
        self.text = self.text[:self.cursor] + self.text[self.cursor + 1:]
        self._ensure_cursor_visible()

    def _clipboard_text(self):
        try:
            clip = pygame.scrap.get(pygame.SCRAP_TEXT)
        except pygame.error:
            clip = None
        if not clip:
            return ""
        if isinstance(clip, bytes):
            clip = clip.decode("utf-8", errors="ignore")
        return clip.replace("\x00", "")

    def _cursor_from_mouse(self, mouse_x):
        if not self.text:
            return 0
        rel_x = mouse_x - (self.rect.x + 10)
        visible = self._visible_text()
        best_index = self.view_start
        best_dist = abs(rel_x)
        for i in range(len(visible) + 1):
            cursor_x = self._text_width(visible[:i])
            dist = abs(rel_x - cursor_x)
            if dist <= best_dist:
                best_dist = dist
                best_index = self.view_start + i
        return best_index

    def handle(self, event):
        """Handle one event. Returns True if Enter was pressed while active."""
        if event.type == pygame.MOUSEBUTTONDOWN:
            self.active = self.rect.collidepoint(event.pos)
            if self.active:
                self.cursor = self._cursor_from_mouse(event.pos[0])
                self._ensure_cursor_visible()
        if self.active and event.type == pygame.KEYDOWN:
            mods = getattr(event, "mod", pygame.key.get_mods())
            if ((mods & pygame.KMOD_CTRL) and event.key == pygame.K_v
                    or ((mods & pygame.KMOD_SHIFT) and event.key == pygame.K_INSERT)):
                self._insert_text(self._clipboard_text())
            elif event.key == pygame.K_LEFT:
                self.cursor = max(0, self.cursor - 1)
                self._ensure_cursor_visible()
            elif event.key == pygame.K_RIGHT:
                self.cursor = min(len(self.text), self.cursor + 1)
                self._ensure_cursor_visible()
            elif event.key == pygame.K_HOME:
                self.cursor = 0
                self._ensure_cursor_visible()
            elif event.key == pygame.K_END:
                self.cursor = len(self.text)
                self._ensure_cursor_visible()
            elif event.key == pygame.K_BACKSPACE:
                self._delete_back()
            elif event.key == pygame.K_DELETE:
                self._delete_forward()
            elif event.key == pygame.K_RETURN:
                return True
            elif event.key == pygame.K_ESCAPE:
                self.active = False
            elif event.unicode and not (mods & pygame.KMOD_CTRL):
                self._insert_text(event.unicode)
        return False

    def draw(self, surf):
        bg_color = C["btn_hover"] if self.active else C["input_bg"]
        pygame.draw.rect(surf, bg_color, self.rect, border_radius=4)
        if not self.font:
            return

        clip_rect = self.rect.inflate(-12, -8)
        prev_clip = surf.get_clip()
        surf.set_clip(clip_rect)

        if self.text:
            display = self._visible_text()
            color = C["text"]
        else:
            display = self.placeholder
            color = C["dim"]

        ts = self.font.render(display, True, color)
        text_x = self.rect.x + 10
        text_y = self.rect.y + (self.rect.h - ts.get_height()) // 2
        surf.blit(ts, (text_x, text_y))

        if self.active and (pygame.time.get_ticks() // 500) % 2 == 0:
            visible = self._visible_text()
            cursor_offset = self._text_width(
                visible[:max(0, self.cursor - self.view_start)]
            )
            cursor_x = text_x + cursor_offset
            pygame.draw.line(
                surf,
                C["white"],
                (cursor_x, self.rect.y + 8),
                (cursor_x, self.rect.bottom - 8),
                2,
            )

        surf.set_clip(prev_clip)


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
        color = self.hover if hov else self.color
        pygame.draw.rect(surf, color, self.rect, border_radius=4)
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
        try:
            pygame.scrap.init()
        except pygame.error:
            pass
        self.screen = pygame.display.set_mode((WINDOW_W, WINDOW_H))
        pygame.display.set_caption("Python Arena")
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
        self.pending_challenge = None     # incoming challenge details
        self.challenge_setup   = None     # outgoing challenge draft
        self.game_state       = None      # latest game_state dict from server
        self.prev_game_state  = None
        self.game_over_data   = None
        self.chat_log         = []        # list of strings
        self.error_msg        = ""
        self.error_timer      = 0
        self.board_animations = []
        self.selected_mode    = "base"
        self.map_vote         = "ember"
        self.map_votes        = {}
        self.selected_map     = None
        self.customize_info   = {}
        self.ready_state      = {}
        self.round_number     = 1
        self.round_wins       = {}
        self.target_wins      = 1
        self.countdown_end_ms = 0

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

    def _target_window_size(self):
        game_w = self.gw * CELL + PANEL_W
        game_h = self.gh * CELL
        return max(WINDOW_W, game_w), max(WINDOW_H, game_h)

    def _apply_window_size(self):
        self.screen = pygame.display.set_mode(self._target_window_size())

    def _draw_poison_skull(self, center, radius):
        pulse = 1.0 + 0.08 * math.sin(pygame.time.get_ticks() / 180.0)
        skull_r = max(6, int(radius * pulse))
        jaw_h = max(4, skull_r // 2)
        jaw_w = max(8, skull_r + 4)

        glow = pygame.Surface((skull_r * 4, skull_r * 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (220, 70, 150, 55), (glow.get_width() // 2, glow.get_height() // 2),
                           skull_r + 6)
        self.screen.blit(glow, glow.get_rect(center=center))

        pygame.draw.circle(self.screen, (245, 245, 245), center, skull_r)
        jaw = pygame.Rect(0, 0, jaw_w, jaw_h)
        jaw.midtop = (center[0], center[1] + skull_r - jaw_h // 3)
        pygame.draw.rect(self.screen, (245, 245, 245), jaw, border_radius=3)

        eye_dx = max(3, skull_r // 2 - 1)
        eye_y = center[1] - max(1, skull_r // 4)
        pygame.draw.circle(self.screen, C["black"], (center[0] - eye_dx, eye_y), max(2, skull_r // 4))
        pygame.draw.circle(self.screen, C["black"], (center[0] + eye_dx, eye_y), max(2, skull_r // 4))
        nose = [(center[0], center[1] + 1),
                (center[0] - 3, center[1] + 6),
                (center[0] + 3, center[1] + 6)]
        pygame.draw.polygon(self.screen, C["black"], nose)

        tooth_w = max(2, jaw_w // 5)
        tooth_h = max(3, jaw_h - 1)
        for idx in range(4):
            tooth = pygame.Rect(jaw.x + 2 + idx * tooth_w, jaw.y + 1, max(1, tooth_w - 1), tooth_h)
            pygame.draw.rect(self.screen, C["black"], tooth, 1)

        pygame.draw.circle(self.screen, (120, 0, 40), center, skull_r, 1)

    def _draw_shield_pickup(self, center, radius, color):
        bob = math.sin(pygame.time.get_ticks() / 240.0)
        cy = center[1] + int(bob * 2)
        outline = [
            (center[0], cy - radius),
            (center[0] + radius - 2, cy - radius // 2),
            (center[0] + radius - 4, cy + radius // 3),
            (center[0], cy + radius),
            (center[0] - radius + 4, cy + radius // 3),
            (center[0] - radius + 2, cy - radius // 2),
        ]
        glow = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
        pygame.draw.circle(glow, (*color, 60), (glow.get_width() // 2, glow.get_height() // 2), radius + 8)
        self.screen.blit(glow, glow.get_rect(center=(center[0], cy)))
        pygame.draw.polygon(self.screen, color, outline)
        pygame.draw.polygon(self.screen, C["white"], outline, 2)
        inner = [
            (center[0], cy - radius + 4),
            (center[0] + radius - 6, cy - radius // 2),
            (center[0] + radius - 8, cy + radius // 4),
            (center[0], cy + radius - 5),
            (center[0] - radius + 8, cy + radius // 4),
            (center[0] - radius + 6, cy - radius // 2),
        ]
        pygame.draw.polygon(self.screen, (235, 240, 255), inner)
        pygame.draw.line(self.screen, color, (center[0], cy - radius + 5), (center[0], cy + radius - 6), 2)

    def _draw_freeze_pickup(self, center, radius, color):
        angle = pygame.time.get_ticks() / 500.0
        for axis in range(3):
            rot = angle + axis * (math.pi / 3)
            dx = math.cos(rot) * radius
            dy = math.sin(rot) * radius
            pygame.draw.line(self.screen, color,
                             (center[0] - dx, center[1] - dy),
                             (center[0] + dx, center[1] + dy), 2)
            tip_x = center[0] + dx
            tip_y = center[1] + dy
            branch_dx = math.cos(rot + math.pi / 6) * (radius * 0.35)
            branch_dy = math.sin(rot + math.pi / 6) * (radius * 0.35)
            pygame.draw.line(self.screen, color, (tip_x, tip_y),
                             (tip_x - branch_dx, tip_y - branch_dy), 2)
            pygame.draw.line(self.screen, color, (tip_x, tip_y),
                             (tip_x - branch_dy, tip_y + branch_dx), 2)
        pygame.draw.circle(self.screen, C["white"], center, max(2, radius // 4))

    def _draw_shield_ring(self, snake):
        if not snake.get("body"):
            return
        hx, hy = snake["body"][0]
        center = (hx * CELL + CELL // 2, hy * CELL + CELL // 2)
        center = (self._board_x + center[0], self._board_y + center[1])
        phase = pygame.time.get_ticks() / 170.0
        base_r = CELL // 2 + 5
        for idx, alpha in enumerate((120, 55)):
            ring = pygame.Surface((base_r * 4, base_r * 4), pygame.SRCALPHA)
            radius = base_r + idx * 4 + int(2 * math.sin(phase + idx))
            pygame.draw.circle(ring, (190, 210, 255, alpha),
                               (ring.get_width() // 2, ring.get_height() // 2), radius, 3)
            self.screen.blit(ring, ring.get_rect(center=center))

    def _draw_freeze_overlay(self, snake):
        shimmer = pygame.time.get_ticks() / 140.0
        for idx, (bx, by) in enumerate(snake.get("body", [])):
            rect = pygame.Rect(self._board_x + bx * CELL + 1, self._board_y + by * CELL + 1,
                               CELL - 2, CELL - 2)
            frost = pygame.Surface(rect.size, pygame.SRCALPHA)
            alpha = 55 if idx else 85
            frost.fill((170, 235, 255, alpha))
            self.screen.blit(frost, rect.topleft)
            if idx == 0:
                center = rect.center
                for branch in range(4):
                    rot = shimmer + branch * (math.pi / 2)
                    dx = math.cos(rot) * (CELL // 2 + 2)
                    dy = math.sin(rot) * (CELL // 2 + 2)
                    pygame.draw.line(self.screen, (210, 250, 255),
                                     (center[0] - dx, center[1] - dy),
                                     (center[0] + dx, center[1] + dy), 2)
                pygame.draw.circle(self.screen, (235, 250, 255), center, CELL // 2 + 3, 1)

    def _grid_to_screen(self, cell_pos):
        return (
            self._board_x + cell_pos[0] * CELL + CELL // 2,
            self._board_y + cell_pos[1] * CELL + CELL // 2,
        )

    def _spawn_board_animation(self, kind, cell_pos, color=None, duration=420):
        self.board_animations.append({
            "kind": kind,
            "cell": tuple(cell_pos),
            "color": color,
            "start": pygame.time.get_ticks(),
            "duration": duration,
        })

    def _maybe_trigger_board_animations(self, new_state):
        prev_state = self.prev_game_state
        self.prev_game_state = new_state
        if not prev_state:
            return

        prev_snakes = prev_state.get("snakes", {})
        new_snakes = new_state.get("snakes", {})
        prev_effects = prev_state.get("effects", {})
        new_effects = new_state.get("effects", {})
        prev_pies = {
            tuple(pie["pos"]): pie.get("kind")
            for pie in prev_state.get("pies", [])
        }
        new_pies = {tuple(pie["pos"]) for pie in new_state.get("pies", [])}

        for pid_s, snake in new_snakes.items():
            body = snake.get("body", [])
            if not body:
                continue
            head = tuple(body[0])
            prev_snake = prev_snakes.get(pid_s, {})
            prev_color = tuple(prev_snake.get("color", snake.get("color", [200, 200, 200])))
            prev_head = tuple(prev_snake.get("body", [head])[0]) if prev_snake.get("body") else head

            if prev_pies.get(head) == "poison" and head not in new_pies:
                self._spawn_board_animation("poison_flash", head, C["pie_poison"], 360)

            old_fx = set(prev_effects.get(pid_s, []))
            new_fx = set(new_effects.get(pid_s, []))

            if "shield" in old_fx and "shield" not in new_fx:
                self._spawn_board_animation("shield_break", prev_head, prev_color, 420)
            if "freeze" in old_fx and "freeze" not in new_fx:
                self._spawn_board_animation("freeze_shatter", head, (180, 235, 255), 460)

    def _draw_board_animations(self):
        now = pygame.time.get_ticks()
        active = []
        for anim in self.board_animations:
            elapsed = now - anim["start"]
            if elapsed >= anim["duration"]:
                continue
            active.append(anim)

            progress = elapsed / anim["duration"]
            cx, cy = self._grid_to_screen(anim["cell"])
            color = anim["color"] or C["white"]

            if anim["kind"] == "poison_flash":
                radius = int(CELL * (0.55 + progress * 0.9))
                alpha = max(0, int(150 * (1.0 - progress)))
                burst = pygame.Surface((radius * 4, radius * 4), pygame.SRCALPHA)
                pygame.draw.circle(burst, (*C["pie_poison"], alpha),
                                   (burst.get_width() // 2, burst.get_height() // 2), radius)
                pygame.draw.circle(burst, (255, 255, 255, max(0, alpha - 40)),
                                   (burst.get_width() // 2, burst.get_height() // 2), max(4, radius // 2), 2)
                self.screen.blit(burst, burst.get_rect(center=(cx, cy)))
            elif anim["kind"] == "shield_break":
                shards = 6
                for shard in range(shards):
                    angle = progress * 2.0 + shard * (math.tau / shards)
                    dist = CELL * (0.15 + progress * 0.7)
                    sx = cx + math.cos(angle) * dist
                    sy = cy + math.sin(angle) * dist
                    ex = sx + math.cos(angle) * 8
                    ey = sy + math.sin(angle) * 8
                    pygame.draw.line(self.screen, color, (sx, sy), (ex, ey), 2)
                ring_alpha = max(0, int(180 * (1.0 - progress)))
                ring = pygame.Surface((CELL * 5, CELL * 5), pygame.SRCALPHA)
                pygame.draw.circle(ring, (*color, ring_alpha),
                                   (ring.get_width() // 2, ring.get_height() // 2),
                                   int(CELL * (0.65 + progress * 0.5)), 3)
                self.screen.blit(ring, ring.get_rect(center=(cx, cy)))
            elif anim["kind"] == "freeze_shatter":
                shards = 8
                for shard in range(shards):
                    angle = shard * (math.tau / shards) + progress * 0.35
                    dist = CELL * progress * 0.9
                    sx = cx + math.cos(angle) * dist
                    sy = cy + math.sin(angle) * dist
                    ex = sx + math.cos(angle) * (6 + shard % 3)
                    ey = sy + math.sin(angle) * (6 + shard % 3)
                    pygame.draw.line(self.screen, color, (sx, sy), (ex, ey), 2)
                crack_alpha = max(0, int(170 * (1.0 - progress)))
                aura = pygame.Surface((CELL * 5, CELL * 5), pygame.SRCALPHA)
                pygame.draw.circle(aura, (*color, crack_alpha // 2),
                                   (aura.get_width() // 2, aura.get_height() // 2),
                                   int(CELL * (0.5 + progress * 0.55)), 2)
                self.screen.blit(aura, aura.get_rect(center=(cx, cy)))

        self.board_animations = active

    # ── Build UI elements ─────────────────────
    def _build_connect_ui(self):
        cx = LOBBY_W // 2
        self.ip_input   = TextInput((cx-180, 280, 360, 48), "Server IP address", self.f_md,
                                    text_filter=filter_ip_text)
        self.port_input = TextInput((cx-180, 348, 360, 48), "Port (default 8000)", self.f_md,
                                    text_filter=filter_digits)
        self.port_input.set_text("8000")
        self.conn_btn   = Button  ((cx-100, 420,  200, 52), "Connect", self.f_md)
        self.ip_input.activate()

    def _build_username_ui(self):
        cx = LOBBY_W // 2
        self.name_input = TextInput((cx-200, 320, 400, 52), "Enter your username", self.f_md)
        self.join_btn   = Button  ((cx-110, 392, 220, 52), "Enter the Arena", self.f_md)
        self.name_input.activate()

    def _drop_widget(self, name):
        self.__dict__.pop(name, None)

    def _close_connection(self):
        conn = self.conn
        self.conn = None
        if conn:
            try:
                conn.close()
            except Exception:
                pass

    def _clear_game_context(self):
        self.player_id = None
        self.game_id = None
        self.watching_game_id = None
        self.opponent = ""
        self.prev_game_state = None
        self.game_state = None
        self.game_over_data = None
        self.chat_log = []
        self.pending_challenge = None
        self.challenge_setup = None
        self.customize_ready = False
        self.binding_slot = None
        self.custom_color = [0, 210, 90]
        self.selected_mode = "base"
        self.map_vote = "ember"
        self.map_votes = {}
        self.selected_map = None
        self.customize_info = {}
        self.ready_state = {}
        self.round_number = 1
        self.round_wins = {}
        self.target_wins = 1
        self.countdown_end_ms = 0
        self.gw = GRID_W
        self.gh = GRID_H
        self.board_animations = []
        self._drop_widget("_game_chat_input")

    def _enter_lobby(self, msg=""):
        self._clear_game_context()
        self.state = "LOBBY"
        self._apply_window_size()
        if msg:
            self._set_error(msg)

    def _reset_to_connect(self, msg="Disconnected from server."):
        ip_text = self.ip_input.text if hasattr(self, "ip_input") else ""
        port_text = self.port_input.text if hasattr(self, "port_input") else "8000"
        self._close_connection()
        self.mq = queue.Queue()
        self.state = "CONNECT"
        self.username = ""
        self.lobby_players = []
        self.lobby_games = []
        self.lobby_viewing = []
        self._clear_game_context()
        self._drop_widget("_lobby_chat_input")
        self._build_connect_ui()
        self.ip_input.set_text(ip_text)
        self.port_input.set_text(port_text or "8000")
        self._apply_window_size()
        if msg:
            self._set_error(msg)

    # Networking
    def _send(self, msg: dict):
        if not self.conn:
            return False
        try:
            with self.send_lock:
                self.conn.sendall((json.dumps(msg) + "\n").encode())
            return True
        except Exception:
            self.mq.put({"type": "_disconnected"})
            return False

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
                        self.mq.put({"type": "error", "msg": "Received malformed data from server."})
            except Exception:
                self.mq.put({"type": "_disconnected"})
                break

    def _process_queue(self):
        while not self.mq.empty():
            msg = self.mq.get()
            t = msg.get("type")

            if t == "_disconnected":
                self._reset_to_connect("Disconnected from server.")

            elif t == "username_ok":
                self.username = msg["username"]
                self.state = "LOBBY"
                self.pending_challenge = None
                self.challenge_setup = None
                self.error_msg = ""
                self.error_timer = 0
                self._apply_window_size()

            elif t == "username_taken":
                self._set_error("Username already taken - try another.")

            elif t == "lobby_update":
                self.lobby_players = [p for p in msg.get("players", []) if p != self.username]
                self.lobby_games = msg.get("games", [])
                self.lobby_viewing = [v for v in msg.get("viewing", []) if v != self.username]
                if (self.pending_challenge
                        and self.pending_challenge.get("from") not in self.lobby_players):
                    self.pending_challenge = None

            elif t == "challenge_request":
                if self.state == "LOBBY":
                    self.pending_challenge = {
                        "from": msg.get("from", ""),
                        "mode": msg.get("mode", "base"),
                        "map_preference": msg.get("map_preference", "ember"),
                    }

            elif t == "challenge_sent":
                self.challenge_setup = None
                mode = MODE_LABELS.get(msg.get("mode"), msg.get("mode", ""))
                map_name = MAP_LABELS.get(msg.get("map_preference"), msg.get("map_preference", ""))
                self._set_error(f"Challenge sent to {msg.get('target')} - {mode}, {map_name}.")

            elif t == "challenge_declined":
                self._set_error(f"{msg.get('from')} declined your challenge.")

            elif t == "challenge_cancelled":
                if self.pending_challenge and self.pending_challenge.get("from") == msg.get("from"):
                    self.pending_challenge = None
                self._set_error(msg.get("msg", "Challenge cancelled."))

            elif t == "game_start":
                self._clear_game_context()
                self.player_id = msg["player_id"]
                self.game_id = msg.get("game_id", "")
                self.opponent = msg.get("opponent", "")
                self.gw = msg.get("grid_w", GRID_W)
                self.gh = msg.get("grid_h", GRID_H)
                self.selected_mode = msg.get("mode", "base")
                self.selected_map = msg.get("selected_map")
                self.map_votes = msg.get("map_votes", {})
                self.map_vote = self.selected_map or self.map_votes.get(self.username, "ember")
                self.round_number = msg.get("round_number", 1)
                self.round_wins = msg.get("round_wins", {})
                self.target_wins = msg.get("target_wins", 1)
                self.ready_state = {}
                self.state = "CUSTOMIZE"
                self.error_msg = ""
                self.error_timer = 0
                self.customize_ready = False
                self.binding_slot = None
                self.custom_color = ([0, 210, 90] if self.player_id == 1 else [30, 140, 255])
                self._apply_window_size()

            elif t == "round_prepare":
                if self.state == "WATCHING" and "player_id" not in msg:
                    self.game_state = None
                    self.prev_game_state = None
                    self.selected_mode = msg.get("mode", self.selected_mode)
                    self.selected_map = msg.get("selected_map", self.selected_map)
                    self.map_votes = msg.get("map_votes", self.map_votes)
                    self.round_number = msg.get("round_number", self.round_number)
                    self.round_wins = msg.get("round_wins", self.round_wins)
                    self.target_wins = msg.get("target_wins", self.target_wins)
                    self.countdown_end_ms = 0
                    continue
                self.game_state = None
                self.prev_game_state = None
                self.player_id = msg["player_id"]
                self.game_id = msg.get("game_id", self.game_id or "")
                self.opponent = msg.get("opponent", self.opponent)
                self.gw = msg.get("grid_w", self.gw)
                self.gh = msg.get("grid_h", self.gh)
                self.selected_mode = msg.get("mode", self.selected_mode)
                self.selected_map = msg.get("selected_map")
                self.map_votes = msg.get("map_votes", self.map_votes)
                self.map_vote = self.selected_map or self.map_votes.get(self.username, self.map_vote)
                self.round_number = msg.get("round_number", self.round_number)
                self.round_wins = msg.get("round_wins", self.round_wins)
                self.target_wins = msg.get("target_wins", self.target_wins)
                self.ready_state = {}
                self.customize_ready = False
                self.binding_slot = None
                self.countdown_end_ms = 0
                self.state = "CUSTOMIZE"
                self._apply_window_size()

            elif t == "customize_update":
                self.selected_mode = msg.get("mode", self.selected_mode)
                self.selected_map = msg.get("selected_map", self.selected_map)
                self.round_number = msg.get("round_number", self.round_number)
                self.round_wins = msg.get("round_wins", self.round_wins)
                self.target_wins = msg.get("target_wins", self.target_wins)
                self.map_votes = msg.get("map_votes", {})
                if self.map_votes.get(self.username):
                    self.map_vote = self.map_votes[self.username]
                self.ready_state = msg.get("ready", {})
                self.customize_info = msg.get("players", {})
                self.customize_ready = bool(self.ready_state.get(self.username, False))

            elif t == "game_begin":
                if self.state in ("CUSTOMIZE", "GAME"):
                    self.state = "GAME"
                self.countdown_end_ms = 0
                self._apply_window_size()

            elif t == "countdown_start":
                self.selected_map = msg.get("selected_map", self.selected_map)
                seconds = max(1, int(msg.get("seconds", 3)))
                self.countdown_end_ms = pygame.time.get_ticks() + seconds * 1000

            elif t == "watch_ok":
                self._clear_game_context()
                self.watching_game_id = msg.get("game_id", "")
                self.gw = msg.get("grid_w", GRID_W)
                self.gh = msg.get("grid_h", GRID_H)
                self.selected_mode = msg.get("mode", "base")
                self.selected_map = msg.get("selected_map")
                self.map_votes = msg.get("map_votes", {})
                self.round_number = msg.get("round_number", 1)
                self.round_wins = msg.get("round_wins", {})
                self.target_wins = msg.get("target_wins", 1)
                self.opponent = f"{msg.get('player1', '')} vs {msg.get('player2', '')}"
                self.state = "WATCHING"
                self._apply_window_size()

            elif t == "game_state":
                if self.state in ("GAME", "WATCHING", "GAME_OVER"):
                    self._maybe_trigger_board_animations(msg)
                    self.game_state = msg
                    self.selected_mode = msg.get("mode", self.selected_mode)
                    self.selected_map = msg.get("map_id", self.selected_map)
                    self.round_number = msg.get("round_number", self.round_number)
                    self.round_wins = msg.get("round_wins", self.round_wins)
                    self.target_wins = msg.get("target_wins", self.target_wins)

            elif t == "game_over":
                if self.state == "WATCHING":
                    winner = msg.get("winner", "Unknown")
                    self._enter_lobby(f"Game ended. Winner: {winner}.")
                elif self.state in ("CUSTOMIZE", "GAME", "GAME_OVER"):
                    self.game_over_data = msg
                    self.state = "GAME_OVER"
                    self.countdown_end_ms = 0

            elif t == "round_over":
                self.round_wins = msg.get("round_wins", self.round_wins)
                self.target_wins = msg.get("target_wins", self.target_wins)
                winner = msg.get("winner", "TIE")
                if winner == "TIE":
                    self._set_error("Round tied - next round preparing.")
                elif winner == self.username:
                    self._set_error("You won the round.")
                else:
                    self._set_error(f"{winner} won the round.")

            elif t in ("game_chat", "lobby_chat"):
                line = f"{msg.get('from', '?')}: {msg.get('msg', '')}"
                self.chat_log.append(line)
                if len(self.chat_log) > 80:
                    self.chat_log.pop(0)

            elif t == "match_cancelled":
                self._enter_lobby(msg.get("msg", "Match cancelled."))

            elif t == "error":
                self._set_error(msg.get("msg", "Unknown error"))

    def _set_error(self, msg):
        self.error_msg = msg
        self.error_timer = 240 if msg else 0

    def _theme(self):
        theme = MAP_THEMES.get(self.selected_map or self.map_vote or "ember", {})
        merged = dict(C)
        merged.update(theme)
        return merged

    def _countdown_value(self):
        if self.countdown_end_ms <= 0:
            return 0
        remaining = max(0, self.countdown_end_ms - pygame.time.get_ticks())
        if remaining <= 0:
            self.countdown_end_ms = 0
            return 0
        return max(1, int(math.ceil(remaining / 1000.0)))

    def _send_customize_choice(self):
        self._send({
            "type": "customize_choice",
            "color": self.custom_color,
        })

    # ── Try to connect to server ──────────────
    def _try_connect(self):
        ip = self.ip_input.text.strip()
        if not ip:
            ip = socket.gethostbyname(socket.gethostname())
        elif ip == "0.0.0.0":
            ip = "127.0.0.1"
        try:
            port = int(self.port_input.text.strip() or "8000")
        except ValueError:
            self._set_error("Invalid port number.")
            return
        try:
            self._close_connection()
            self.conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.conn.settimeout(5)
            self.conn.connect((ip, port))
            self.conn.settimeout(None)
            threading.Thread(target=self._net_thread, daemon=True).start()
            self.state     = "USERNAME"
            self.error_msg = ""
            self.error_timer = 0
            self._build_username_ui()
        except Exception as e:
            self._set_error(f"Connection failed: {e}")

    # ──────────────────────────────────────────
    # DRAW SCREENS
    def _draw_fog_of_war(self, gs, board_x, board_y):
        if self.selected_mode != "fog_of_war" or self.state != "GAME" or not self.player_id:
            return
        snake = gs.get("snakes", {}).get(str(self.player_id))
        if not snake or not snake.get("body"):
            return
        length = len(snake.get("body", []))
        hx, hy = snake["body"][0]
        radius_cells = 4.5 + min(6.0, length * 0.28)
        radius_px = int(radius_cells * CELL)
        fog = pygame.Surface((self.gw * CELL, self.gh * CELL), pygame.SRCALPHA)
        fog.fill((0, 0, 0, 215))
        center = (hx * CELL + CELL // 2, hy * CELL + CELL // 2)
        pygame.draw.circle(fog, (0, 0, 0, 0), center, radius_px)
        pygame.draw.circle(fog, (255, 255, 255, 40), center, radius_px, 2)
        self.screen.blit(fog, (board_x, board_y))

    def _draw_connect(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        # Title
        draw_text(self.screen, "Python Arena", self.f_xl, C["accent"],
                  (sw//2, 130), "center")
        draw_text(self.screen, "Online Two-Player Snake Battle - EECE 350",
                  self.f_sm, C["dim"], (sw//2, 195), "center")

        self.ip_input.rect.centerx   = sw // 2
        self.port_input.rect.centerx = sw // 2
        self.conn_btn.rect.centerx   = sw // 2

        self.ip_input.draw(self.screen)
        self.port_input.draw(self.screen)
        self.conn_btn.draw(self.screen)
        draw_text(self.screen,
                  "Tip: 0.0.0.0 is for hosting; friends should use the server computer's LAN IP.",
                  self.f_xs, C["dim"], (sw // 2, 486), "center")

        if self.error_msg:
            draw_text(self.screen, self.error_msg, self.f_sm, C["danger"],
                      (sw//2, 520), "center")

    def _draw_username(self):
        sw, sh = self.screen.get_size()
        self.screen.fill(C["bg"])

        draw_text(self.screen, "Python Arena", self.f_xl, C["accent"],
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
        pygame.draw.rect(self.screen, C["panel"], (0, 0, sw, 72))
        pygame.draw.line(self.screen, C["card_border"], (0, 71), (sw, 71))
        draw_text(self.screen, "Python Arena", self.f_lg, C["accent"], (24, 18))
        draw_text(self.screen, f"Logged in as  {self.username}", self.f_sm,
                  C["dim"], (sw - 20, 25), "topright")
        draw_text(self.screen, "Online Players", self.f_md, C["text"], (24, 90))
        draw_text(self.screen, "Choose mode and map before sending a challenge.",
                  self.f_xs, C["dim"], (24, 118))

        btn_rects = {}
        all_rows = ([(p, "lobby") for p in self.lobby_players] +
                    [(v, "viewing") for v in self.lobby_viewing])
        if not all_rows:
            draw_text(self.screen, "No other players online - waiting for opponents...",
                      self.f_sm, C["dim"], (24, 152))
        else:
            for i, (name, role) in enumerate(all_rows[:8]):
                y = 146 + i * 62
                row = pygame.Rect(24, y, sw - 300, 52)
                if row.collidepoint(pygame.mouse.get_pos()):
                    pygame.draw.rect(self.screen, C["card_hi"], row, border_radius=8)
                label = ("Player  " if role == "lobby" else "Viewer  ") + name
                if role == "viewing":
                    label += "  - watching"
                draw_text(self.screen, label, self.f_sm,
                          C["text"] if role == "lobby" else C["dim"],
                          (row.x + 18, row.y + 15))
                pygame.draw.line(self.screen, C["card_border"],
                                 (row.x, row.bottom), (row.right, row.bottom), 1)
                if role == "lobby":
                    ch_r = pygame.Rect(row.right - 140, y + 8, 130, 36)
                    pygame.draw.rect(self.screen,
                                     C["btn_hover"] if ch_r.collidepoint(pygame.mouse.get_pos()) else C["btn"],
                                     ch_r, border_radius=7)
                    draw_text(self.screen, "Challenge", self.f_xs, C["text"], ch_r.center, "center")
                    btn_rects[name] = ch_r

        lg_x = sw - 258
        draw_text(self.screen, "Live Games", self.f_sm, C["text"], (lg_x, 90))
        watch_btns = {}
        if not self.lobby_games:
            draw_text(self.screen, "No games in progress", self.f_xs, C["dim"], (lg_x, 120))
        else:
            for i, ginfo in enumerate(self.lobby_games[:6]):
                gid = ginfo["game_id"]
                gy = 118 + i * 60
                draw_text(self.screen, f"{ginfo['player1']} vs {ginfo['player2']}"[:22],
                          self.f_xs, C["text"], (lg_x, gy))
                draw_text(self.screen,
                          f"{MODE_LABELS.get(ginfo.get('mode'), 'Base')} - "
                          f"{MAP_LABELS.get(ginfo.get('map_id'), 'TBD')}",
                          self.f_xs, C["dim"], (lg_x, gy + 16))
                if ginfo.get("viewers", 0):
                    draw_text(self.screen, f"Viewers {ginfo.get('viewers', 0)}", self.f_xs,
                              C["dim"], (lg_x, gy + 32))
                wrect = pygame.Rect(lg_x + 152, gy - 2, 74, 26)
                pygame.draw.rect(self.screen,
                                 (70, 50, 140) if wrect.collidepoint(pygame.mouse.get_pos()) else (50, 35, 110),
                                 wrect, border_radius=6)
                draw_text(self.screen, "Watch", self.f_xs, C["text"], wrect.center, "center")
                watch_btns[gid] = wrect

        chat_panel = pygame.Rect(24, sh - 200, sw - 48, 180)
        shadow = chat_panel.copy(); shadow.x += 3; shadow.y += 3
        pygame.draw.rect(self.screen, (0, 0, 0, 60), shadow, border_radius=10)
        pygame.draw.rect(self.screen, C["panel"], chat_panel, border_radius=10)
        pygame.draw.rect(self.screen, C["card_border"], chat_panel, 1, border_radius=10)
        draw_text(self.screen, "Lobby Chat", self.f_xs, C["dim"], (chat_panel.x + 12, chat_panel.y + 8))
        for j, line in enumerate(self.chat_log[-6:]):
            draw_text(self.screen, line[:80], self.f_xs, C["text"],
                      (chat_panel.x + 12, chat_panel.y + 28 + j * 18))
        ci_rect = pygame.Rect(chat_panel.x + 4, chat_panel.bottom - 38, chat_panel.w - 8, 32)
        if not hasattr(self, "_lobby_chat_input"):
            self._lobby_chat_input = TextInput(ci_rect, "Press Enter to chat...", self.f_xs, max_len=80)
        self._lobby_chat_input.rect = ci_rect
        self._lobby_chat_input.draw(self.screen)

        acc_btn = dec_btn = None
        modal = {"mode": {}, "map": {}, "send": None, "cancel": None}
        if self.pending_challenge:
            challenger = self.pending_challenge.get("from", "")
            mode = MODE_LABELS.get(self.pending_challenge.get("mode"), "Base")
            map_name = MAP_LABELS.get(self.pending_challenge.get("map_preference"), "Unknown")
            ox, oy, ow, oh = sw // 2 - 230, sh // 2 - 108, 460, 216
            popup = pygame.Rect(ox, oy, ow, oh)
            pygame.draw.rect(self.screen, C["panel"], popup, border_radius=14)
            pygame.draw.rect(self.screen, C["accent"], popup, 2, border_radius=14)
            draw_text(self.screen, f"{challenger} challenged you", self.f_md, C["accent"],
                      (sw // 2, oy + 32), "center")
            draw_text(self.screen, f"Mode: {mode}", self.f_sm, C["text"], (sw // 2, oy + 78), "center")
            draw_text(self.screen, f"Preferred map: {map_name}", self.f_sm, C["dim"],
                      (sw // 2, oy + 106), "center")
            acc_btn = Button((sw // 2 - 130, oy + 146, 115, 42), "Accept", self.f_sm,
                             C["btn_green"], (50, 180, 70))
            dec_btn = Button((sw // 2 + 15, oy + 146, 115, 42), "Decline", self.f_sm,
                             C["btn_red"], (200, 50, 50))
            acc_btn.draw(self.screen); dec_btn.draw(self.screen)

        if self.challenge_setup:
            setup = self.challenge_setup
            ox, oy, ow, oh = sw // 2 - 270, sh // 2 - 215, 540, 430
            popup = pygame.Rect(ox, oy, ow, oh)
            pygame.draw.rect(self.screen, C["panel"], popup, border_radius=16)
            pygame.draw.rect(self.screen, C["accent"], popup, 2, border_radius=16)
            draw_text(self.screen, "Prepare Challenge", self.f_lg, C["accent"], (sw // 2, oy + 28), "center")
            draw_text(self.screen, f"Opponent: {setup['target']}", self.f_sm, C["text"], (ox + 30, oy + 82))
            draw_text(self.screen, "Mode", self.f_sm, C["dim"], (ox + 30, oy + 120))
            for idx, mode in enumerate(MODE_ORDER):
                rect = pygame.Rect(ox + 30, oy + 152 + idx * 42, 224, 34)
                modal["mode"][mode] = rect
                chosen = setup["mode"] == mode
                pygame.draw.rect(self.screen, C["card_hi"] if chosen else C["card"], rect, border_radius=8)
                pygame.draw.rect(self.screen, C["accent"] if chosen else C["card_border"],
                                 rect, 2 if chosen else 1, border_radius=8)
                draw_text(self.screen, MODE_LABELS[mode], self.f_xs,
                          C["white"] if chosen else C["text"], (rect.x + 10, rect.y + 9))
            draw_text(self.screen, MODE_BLURBS.get(setup["mode"], ""), self.f_xs, C["dim"],
                      (ox + 30, oy + 342))
            draw_text(self.screen, "Map preference", self.f_sm, C["dim"], (ox + 290, oy + 120))
            for idx, map_id in enumerate(MAP_ORDER):
                rect = pygame.Rect(ox + 290, oy + 152 + idx * 62, 220, 50)
                modal["map"][map_id] = rect
                chosen = setup["map_preference"] == map_id
                theme = MAP_THEMES[map_id]
                pygame.draw.rect(self.screen, theme["board_bg"], rect, border_radius=10)
                pygame.draw.rect(self.screen, theme["accent"] if chosen else C["card_border"],
                                 rect, 2 if chosen else 1, border_radius=10)
                draw_text(self.screen, MAP_LABELS[map_id], self.f_sm, C["text"], (rect.x + 16, rect.y + 8))
                draw_text(self.screen, "Distinct obstacle layout", self.f_xs, C["dim"], (rect.x + 16, rect.y + 28))
            modal["send"] = Button((sw // 2 - 128, oy + 372, 118, 42), "Send", self.f_sm,
                                    C["btn_green"], (50, 180, 70))
            modal["cancel"] = Button((sw // 2 + 12, oy + 372, 118, 42), "Cancel", self.f_sm,
                                      C["btn_red"], (200, 50, 50))
            modal["send"].draw(self.screen); modal["cancel"].draw(self.screen)

        if self.error_msg:
            draw_text(self.screen, self.error_msg, self.f_xs, C["danger"], (24, sh - 215))
        return btn_rects, watch_btns, acc_btn, dec_btn, modal

    def _draw_customize(self):
        sw, sh = self.screen.get_size()
        theme = self._theme()
        self.screen.fill(theme["board_bg"])
        draw_text(self.screen,
                  "Customize Your Snake" if self.round_number <= 1 else f"Round {self.round_number} Ready Up",
                  self.f_lg, theme.get("accent", C["accent"]), (sw // 2, 42), "center")
        draw_text(self.screen, f"vs  {self.opponent}", self.f_sm, C["dim"], (sw // 2, 92), "center")
        draw_text(self.screen,
                  f"Mode: {MODE_LABELS.get(self.selected_mode, 'Base')} | First to {self.target_wins}",
                  self.f_xs, C["text"], (sw // 2, 122), "center")
        if self.round_wins:
            draw_text(self.screen,
                      f"Score {self.username} {self.round_wins.get(self.username, 0)} - "
                      f"{self.round_wins.get(self.opponent, 0)} {self.opponent}",
                      self.f_sm, C["text"], (sw // 2, 146), "center")

        map_rects = {}
        draw_text(self.screen, "Selected Map", self.f_sm, C["dim"], (sw // 2, 178), "center")
        total_w = 3 * 176 + 2 * 18
        start_x = sw // 2 - total_w // 2
        for idx, map_id in enumerate(MAP_ORDER):
            rect = pygame.Rect(start_x + idx * 194, 196, 176, 70)
            theme2 = MAP_THEMES[map_id]
            chosen = (self.selected_map or self.map_vote) == map_id
            pygame.draw.rect(self.screen, theme2["board_bg"], rect, border_radius=12)
            pygame.draw.rect(self.screen, theme2["accent"] if chosen else C["card_border"],
                             rect, 2 if chosen else 1, border_radius=12)
            draw_text(self.screen, MAP_LABELS[map_id], self.f_sm, C["text"], (rect.x + 16, rect.y + 10))
            label = "Challenger choice" if chosen else "Unavailable"
            draw_text(self.screen, label, self.f_xs, theme2["accent"] if chosen else C["dim"],
                      (rect.x + 16, rect.y + 38))
        draw_text(self.screen,
                  f"Map was selected by challenger: {MAP_LABELS.get(self.selected_map or self.map_vote, 'Ember Forge')}",
                  self.f_xs, theme.get("accent", C["accent"]), (sw // 2, 278), "center")

        pygame.draw.line(self.screen, C["card_border"], (30, 308), (sw - 30, 308), 1)
        pygame.draw.line(self.screen, C["card_border"], (sw // 2, 308), (sw // 2, sh - 90), 1)

        lx = 50
        draw_text(self.screen, "Snake Color", self.f_md, C["text"], (lx, 326))
        prev_color = tuple(self.custom_color)
        prev_head = tuple(min(255, v + 60) for v in self.custom_color)
        for i in range(5):
            r = pygame.Rect(lx + i * 34, 372, 30, 30)
            pygame.draw.rect(self.screen, prev_head if i == 0 else prev_color, r, border_radius=5 if i == 0 else 3)
            if i == 0:
                pygame.draw.circle(self.screen, C["black"], (r.x + 9, r.y + 9), 3)
                pygame.draw.circle(self.screen, C["black"], (r.x + 20, r.y + 9), 3)
        swatch_rects = {}
        for idx, color in enumerate(SNAKE_COLORS):
            row, col_i = divmod(idx, 6)
            rect = pygame.Rect(lx + col_i * 58, 424 + row * 62, 50, 50)
            swatch_rects[idx] = rect
            pygame.draw.rect(self.screen, tuple(color), rect, border_radius=8)
            pygame.draw.rect(self.screen, C["white"] if list(color) == self.custom_color else C["card_border"],
                             rect, 3 if list(color) == self.custom_color else 1, border_radius=8)

        rx = sw // 2 + 24
        draw_text(self.screen, "Movement Keys", self.f_md, C["text"], (rx, 326))
        dir_to_key = {v: k for k, v in self.key_map.items()}
        key_slot_rects = {}
        for i, (direction, symbol) in enumerate(DIR_SYMBOLS.items()):
            ry = 362 + i * 72
            row_r = pygame.Rect(rx, ry, 366, 58)
            pygame.draw.rect(self.screen, C["card"], row_r, border_radius=8)
            draw_text(self.screen, symbol, self.f_lg, C["text"], (rx + 18, ry + 10))
            draw_text(self.screen, direction, self.f_sm, C["dim"], (rx + 52, ry + 17))
            kcode = dir_to_key.get(direction)
            kname = pygame.key.name(kcode).upper() if kcode else "-"
            is_binding = self.binding_slot == direction
            kbox = pygame.Rect(rx + 238, ry + 11, 110, 36)
            key_slot_rects[direction] = kbox
            pygame.draw.rect(self.screen, C["btn_hover"] if is_binding else C["input_bg"], kbox, border_radius=6)
            pygame.draw.rect(self.screen, C["accent"] if is_binding else C["card_border"], kbox, 2, border_radius=6)
            draw_text(self.screen, "Press key..." if is_binding else kname, self.f_sm,
                      C["accent"] if is_binding else C["text"], kbox.center, "center")

        ready_names = [name for name, ready in self.ready_state.items() if ready]
        draw_text(self.screen, "Ready: " + (", ".join(ready_names) if ready_names else "nobody yet"),
                  self.f_xs, C["dim"], (sw // 2, sh - 118), "center")
        ready_r = pygame.Rect(sw // 2 - 120, sh - 76, 240, 50)
        if self.customize_ready:
            draw_text(self.screen, "Waiting for opponent...", self.f_sm, C["dim"],
                      (sw // 2, sh - 50), "center")
        else:
            pygame.draw.rect(self.screen, C["btn_green"], ready_r, border_radius=10)
            draw_text(self.screen, "Ready", self.f_md, C["text"], ready_r.center, "center")
        countdown = self._countdown_value()
        if countdown:
            overlay = pygame.Surface((sw, sh), pygame.SRCALPHA); overlay.fill((0, 0, 0, 110))
            self.screen.blit(overlay, (0, 0))
            draw_text(self.screen, str(countdown), self.f_xl, C["white"], (sw // 2, sh // 2 - 10), "center")
            draw_text(self.screen, "Match starting", self.f_sm, C["accent"], (sw // 2, sh // 2 + 42), "center")
        return swatch_rects, key_slot_rects, ready_r, map_rects

    def _draw_game(self):
        gw, gh = self.gw, self.gh
        game_w, game_h = gw * CELL, gh * CELL
        full_w = game_w + PANEL_W
        screen_w, screen_h = self.screen.get_size()
        board_x = (screen_w - full_w) // 2
        board_y = (screen_h - game_h) // 2
        self._board_x = board_x
        self._board_y = board_y
        theme = self._theme()
        self.screen.fill(C["bg"])
        pygame.draw.rect(self.screen, theme["board_bg"], (board_x, board_y, game_w, game_h))
        for x in range(0, game_w + 1, CELL):
            pygame.draw.line(self.screen, theme["grid"], (board_x + x, board_y), (board_x + x, board_y + game_h))
        for y in range(0, game_h + 1, CELL):
            pygame.draw.line(self.screen, theme["grid"], (board_x, board_y + y), (board_x + game_w, board_y + y))
        if not self.game_state:
            draw_text(self.screen, "Waiting for first game state...", self.f_md, C["dim"],
                      (board_x + game_w // 2, board_y + game_h // 2), "center")
            self._draw_panel(board_x + game_w, board_y, game_h)
            return

        gs = self.game_state
        effects = gs.get("effects", {})
        if gs.get("map_id"):
            self.selected_map = gs.get("map_id")
            theme = self._theme()
        safe_zone = gs.get("safe_zone")
        if safe_zone:
            sx, sy, zw, zh = safe_zone
            pygame.draw.rect(self.screen, theme["safe_zone"],
                             (board_x + sx * CELL, board_y + sy * CELL, zw * CELL, zh * CELL), 3, border_radius=4)
        for ox, oy in gs.get("obstacles", []):
            r = pygame.Rect(board_x + ox * CELL + 1, board_y + oy * CELL + 1, CELL - 2, CELL - 2)
            pygame.draw.rect(self.screen, theme["obstacle"], r, border_radius=2)
            pygame.draw.line(self.screen, theme["obstacle_x"], r.topleft, r.bottomright, 1)
            pygame.draw.line(self.screen, theme["obstacle_x"], r.topright, r.bottomleft, 1)
        for pie in gs.get("pies", []):
            px, py = pie["pos"]
            center = (board_x + px * CELL + CELL // 2, board_y + py * CELL + CELL // 2)
            r = CELL // 2 - 2
            if pie.get("kind") == "poison":
                self._draw_poison_skull(center, r)
            else:
                color = tuple(pie.get("color", C["pie_normal"]))
                pygame.draw.circle(self.screen, color, center, r + (1 if pie.get("kind") == "golden" else 0))
                pygame.draw.circle(self.screen, C["white"], center, r, 1)
        for pu in gs.get("powerups", []):
            px, py = pu["pos"]
            center = (board_x + px * CELL + CELL // 2, board_y + py * CELL + CELL // 2)
            color = tuple(pu.get("color", C["card_border"]))
            r = CELL // 2 - 2
            if pu.get("kind") == "shield":
                self._draw_shield_pickup(center, r, color)
            elif pu.get("kind") == "freeze":
                self._draw_freeze_pickup(center, r, color)
            else:
                pts = [(center[0], center[1] - r), (center[0] + r, center[1]),
                       (center[0], center[1] + r), (center[0] - r, center[1])]
                pygame.draw.polygon(self.screen, color, pts)
                pygame.draw.polygon(self.screen, C["white"], pts, 1)
        for pid_s, snake in gs.get("snakes", {}).items():
            raw = snake.get("color", [200, 200, 200])
            body_c = tuple(raw)
            head_c = tuple(min(255, v + 40) for v in raw)
            if not snake.get("alive", True):
                body_c = head_c = tuple(max(0, v - 100) for v in raw)
            for i, (bx, by) in enumerate(snake.get("body", [])):
                rect = pygame.Rect(board_x + bx * CELL + 1, board_y + by * CELL + 1, CELL - 2, CELL - 2)
                if i == 0 and snake.get("alive", True):
                    pygame.draw.rect(self.screen, head_c, rect, border_radius=3)
                    pygame.draw.circle(self.screen, C["black"], (rect.centerx - 2, rect.centery - 2), 2)
                    pygame.draw.circle(self.screen, C["black"], (rect.centerx + 2, rect.centery - 2), 2)
                else:
                    pygame.draw.rect(self.screen, body_c, rect, border_radius=2)
            snake_effects = effects.get(pid_s, [])
            if "shield" in snake_effects:
                self._draw_shield_ring(snake)
            if "freeze" in snake_effects:
                self._draw_freeze_overlay(snake)
        self._draw_board_animations()
        self._draw_fog_of_war(gs, board_x, board_y)
        self._draw_panel(board_x + game_w, board_y, game_h)
        countdown = self._countdown_value()
        if countdown:
            sw, sh = self.screen.get_size()
            overlay = pygame.Surface((sw, sh), pygame.SRCALPHA); overlay.fill((0, 0, 0, 120))
            self.screen.blit(overlay, (0, 0))
            draw_text(self.screen, str(countdown), self.f_xl, C["white"],
                      (board_x + game_w // 2, board_y + game_h // 2 - 10), "center")
            draw_text(self.screen, "Round starting", self.f_sm, C["accent"],
                      (board_x + game_w // 2, board_y + game_h // 2 + 42), "center")

    def _draw_panel(self, panel_x, panel_y, game_h):
        px = panel_x
        pygame.draw.rect(self.screen, C["panel"], (px, panel_y, PANEL_W, game_h))
        pygame.draw.line(self.screen, C["card_border"], (px, panel_y), (px, panel_y + game_h), 2)
        gs = self.game_state or {}
        snakes = gs.get("snakes", {})
        usernames = gs.get("usernames", {})
        time_left = gs.get("time_left", 0)
        theme = self._theme()
        effects = gs.get("effects", {})
        eff_color = {"shield": (180, 180, 220), "freeze": (0, 210, 240), "double": (255, 200, 50)}
        eff_label = {"shield": "Shield", "freeze": "Frozen!", "double": "2x Pies"}

        y = panel_y + 14
        draw_text(self.screen,
                  f"{MODE_LABELS.get(self.selected_mode, 'Base')} - {MAP_LABELS.get(self.selected_map, 'Map voting')}",
                  self.f_xs, theme.get("accent", C["accent"]), (px + 10, y))
        y += 18
        if self.target_wins > 1:
            p1 = usernames.get("1", "P1")
            p2 = usernames.get("2", "P2")
            draw_text(self.screen,
                      f"Round {self.round_number} | {p1} {self.round_wins.get(p1, 0)} - {self.round_wins.get(p2, 0)} {p2}",
                      self.f_xs, C["dim"], (px + 10, y))
            y += 18

        for pid_s in ("1", "2"):
            snake = snakes.get(pid_s, {})
            raw = snake.get("color", [200, 200, 200])
            body_c = tuple(raw)
            uname = usernames.get(pid_s, f"Player {pid_s}")
            hp = snake.get("health", 0)
            alive = snake.get("alive", True)
            me = (self.player_id is not None and int(pid_s) == self.player_id)
            label = f"{'> ' if me else ''}{uname}{'  (you)' if me else ''}"
            draw_text(self.screen, label, self.f_sm, body_c if alive else C["dim"], (px + 10, y))
            y += 24
            bar = pygame.Rect(px + 10, y, PANEL_W - 22, 16)
            pygame.draw.rect(self.screen, C["input_bg"], bar, border_radius=5)
            w = int(bar.w * max(0, hp) / 200)
            if w > 0:
                pygame.draw.rect(self.screen, body_c if hp > 40 else C["hp_low"],
                                 pygame.Rect(bar.x, bar.y, w, bar.h), border_radius=5)
            pygame.draw.rect(self.screen, C["card_border"], bar, 1, border_radius=5)
            draw_text(self.screen, f"HP {hp}", self.f_xs, C["text"], (bar.x + 5, bar.y + 2))
            y += 20
            for eff in effects.get(pid_s, []):
                draw_text(self.screen, eff_label.get(eff, eff), self.f_xs,
                          eff_color.get(eff, C["dim"]), (px + 12, y))
                y += 13
            y += 8

        y += 4
        tc = C["danger"] if time_left < 20 else C["accent"]
        pygame.draw.rect(self.screen, C["card"], (px + 10, y, PANEL_W - 22, 34), border_radius=7)
        draw_text(self.screen, f"Time: {int(time_left)} s remaining", self.f_sm, tc,
                  (px + PANEL_W // 2, y + 10), "center")
        y += 46

        draw_text(self.screen, "Legend", self.f_xs, C["dim"], (px + 10, y))
        y += 18
        legend = [
            (C["pie_normal"], "Normal Pie   +15 HP"),
            (C["pie_golden"], "Golden Pie   +30 HP"),
            (C["pie_poison"], "Poison Pie   -20 HP"),
            (theme["obstacle"], "Obstacle     -25 HP"),
        ]
        if self.selected_mode == "sudden_death":
            legend.append((theme["safe_zone"], "Safe Zone    shrinking"))
        else:
            legend.extend([
                ((180, 180, 220), "Shield       next hit"),
                ((0, 210, 240), "Freeze       opp. 5s"),
                ((255, 200, 50), "2x Pies      5s buff"),
            ])
        for color, label in legend:
            pygame.draw.rect(self.screen, color, (px + 10, y + 2, 13, 13), border_radius=3)
            draw_text(self.screen, label, self.f_xs, C["dim"], (px + 28, y))
            y += 18

        y += 8
        hint_lines = ["Arrow keys / WASD: move", "T + Enter: chat"] if self.state == "GAME" else ["Watching...", "T + Enter: cheer"]
        for line in hint_lines:
            draw_text(self.screen, line, self.f_xs, C["dim"], (px + 10, y))
            y += 16

        chat_top = max(y + 10, panel_y + game_h - 185)
        draw_text(self.screen, "Chat", self.f_xs, C["dim"], (px + 10, chat_top))
        for j, line in enumerate(self.chat_log[-4:]):
            draw_text(self.screen, line[:34], self.f_xs, C["text"], (px + 6, chat_top + 18 + j * 17))
        event_top = chat_top + 92
        draw_text(self.screen, "Event Log", self.f_xs, C["dim"], (px + 10, event_top))
        for j, line in enumerate(gs.get("event_log", [])[-3:]):
            draw_text(self.screen, line[:36], self.f_xs, C["accent"], (px + 6, event_top + 18 + j * 16))

        ci = pygame.Rect(px + 5, panel_y + game_h - 34, PANEL_W - 10, 28)
        if not hasattr(self, "_game_chat_input"):
            self._game_chat_input = TextInput(ci, "T to chat...", self.f_xs, max_len=60)
        self._game_chat_input.rect = ci
        self._game_chat_input.draw(self.screen)

    def _draw_game_over(self):
        self._draw_game()
        sw, sh = self.screen.get_size()
        overlay = pygame.Surface((sw, sh), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 170))
        self.screen.blit(overlay, (0, 0))
        pd = self.game_over_data or {}
        winner = pd.get("winner", "?")
        scores = pd.get("scores", {})
        round_wins = pd.get("round_wins", {})
        target_wins = pd.get("target_wins", self.target_wins)
        pw, ph = 500, 310
        pr = pygame.Rect(sw // 2 - pw // 2, sh // 2 - ph // 2, pw, ph)
        pygame.draw.rect(self.screen, C["panel"], pr, border_radius=16)
        pygame.draw.rect(self.screen, C["accent"], pr, 3, border_radius=16)
        draw_text(self.screen, "GAME OVER", self.f_xl, C["accent"], (sw // 2, pr.y + 30), "center")
        if winner == "TIE":
            result, color = "It's a Tie!", C["text"]
        elif winner == self.username:
            result, color = "You Win!", C["win"]
        else:
            result, color = f"{winner} Wins!", C["lose"]
        draw_text(self.screen, result, self.f_lg, color, (sw // 2, pr.y + 100), "center")
        y = pr.y + 150
        if round_wins and target_wins > 1:
            for uname, wins in round_wins.items():
                draw_text(self.screen, f"{uname}: {wins} round wins", self.f_md, C["text"], (sw // 2, y), "center")
                y += 34
        else:
            for uname, hp in scores.items():
                draw_text(self.screen, f"{uname}: {hp} HP", self.f_md, C["text"], (sw // 2, y), "center")
                y += 34
        back_btn = Button((sw // 2 - 115, pr.bottom - 62, 230, 46), "Back to Lobby", self.f_md)
        back_btn.draw(self.screen)
        return back_btn

    def run(self):
        lobby_btn_rects = {}
        watch_btns = {}
        challenge_modal = {"mode": {}, "map": {}, "send": None, "cancel": None}
        acc_btn = dec_btn = None
        back_btn = None
        cust_swatch_rects = {}
        cust_key_rects = {}
        cust_ready_r = None
        cust_map_rects = {}

        while True:
            self.clock.tick(60)
            self._process_queue()
            if self.error_timer > 0:
                self.error_timer -= 1
                if self.error_timer == 0:
                    self.error_msg = ""

            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._close_connection()
                    pygame.quit()
                    sys.exit()

                if self.state == "CONNECT":
                    ip_entered = self.ip_input.handle(event)
                    port_entered = self.port_input.handle(event)
                    if self.conn_btn.clicked(event) or ip_entered or port_entered:
                        self._try_connect()

                elif self.state == "USERNAME":
                    entered = self.name_input.handle(event)
                    if self.join_btn.clicked(event) or entered:
                        uname = self.name_input.text.strip()
                        if uname:
                            self._send({"type": "username", "username": uname})

                elif self.state == "LOBBY":
                    if not hasattr(self, "_lobby_chat_input"):
                        self._lobby_chat_input = TextInput((0, 0, 100, 30), "", self.f_xs, 80)
                    if self._lobby_chat_input.handle(event) and self._lobby_chat_input.text.strip():
                        self._send({"type": "lobby_chat", "msg": self._lobby_chat_input.text.strip()})
                        self._lobby_chat_input.set_text("")

                    if self.challenge_setup:
                        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                            self.challenge_setup = None
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            send_btn = challenge_modal.get("send")
                            cancel_btn = challenge_modal.get("cancel")
                            if send_btn and send_btn.clicked(event):
                                self.map_vote = self.challenge_setup["map_preference"]
                                self._send({"type": "challenge", "target": self.challenge_setup["target"],
                                            "mode": self.challenge_setup["mode"],
                                            "map_preference": self.challenge_setup["map_preference"]})
                            elif cancel_btn and cancel_btn.clicked(event):
                                self.challenge_setup = None
                            else:
                                for mode, rect in challenge_modal.get("mode", {}).items():
                                    if rect.collidepoint(event.pos):
                                        self.challenge_setup["mode"] = mode
                                for map_id, rect in challenge_modal.get("map", {}).items():
                                    if rect.collidepoint(event.pos):
                                        self.challenge_setup["map_preference"] = map_id
                    elif self.pending_challenge:
                        if acc_btn and acc_btn.clicked(event):
                            self._send({"type": "challenge_response",
                                        "from": self.pending_challenge.get("from"), "accepted": True})
                            self.pending_challenge = None
                        elif dec_btn and dec_btn.clicked(event):
                            self._send({"type": "challenge_response",
                                        "from": self.pending_challenge.get("from"), "accepted": False})
                            self.pending_challenge = None
                    else:
                        if event.type == pygame.MOUSEBUTTONDOWN:
                            for player, rect in lobby_btn_rects.items():
                                if rect.collidepoint(event.pos):
                                    self.challenge_setup = {"target": player, "mode": "base",
                                                            "map_preference": self.map_vote or "ember"}
                            for gid, rect in watch_btns.items():
                                if rect.collidepoint(event.pos):
                                    self._send({"type": "watch", "game_id": gid})
                                    break

                elif self.state == "CUSTOMIZE":
                    if event.type == pygame.MOUSEBUTTONDOWN:
                        for idx, rect in cust_swatch_rects.items():
                            if not self.customize_ready and rect.collidepoint(event.pos):
                                self.custom_color = list(SNAKE_COLORS[idx])
                                self.binding_slot = None
                                self._send_customize_choice()
                        if not self.customize_ready:
                            for direction, rect in cust_key_rects.items():
                                if rect.collidepoint(event.pos):
                                    self.binding_slot = direction
                        if not self.customize_ready and cust_ready_r and cust_ready_r.collidepoint(event.pos):
                            self._send({"type": "player_ready", "color": self.custom_color})
                            self.customize_ready = True
                            self.binding_slot = None
                    elif event.type == pygame.KEYDOWN:
                        if self.binding_slot:
                            if event.key in RESERVED_BIND_KEYS:
                                self._set_error("That key is reserved.")
                                self.binding_slot = None
                                continue
                            direction = self.binding_slot
                            self.key_map = {k: v for k, v in self.key_map.items() if k != event.key and v != direction}
                            self.key_map[event.key] = direction
                            self.binding_slot = None
                        elif event.key == pygame.K_ESCAPE:
                            self.binding_slot = None

                elif self.state in ("GAME", "WATCHING"):
                    if not hasattr(self, "_game_chat_input"):
                        self._game_chat_input = TextInput((0, 0, 100, 30), "", self.f_xs, 60)
                    if self._game_chat_input.handle(event) and self._game_chat_input.text.strip():
                        self._send({"type": "game_chat", "msg": self._game_chat_input.text.strip()})
                        self._game_chat_input.set_text("")
                    if self.state == "GAME" and event.type == pygame.KEYDOWN and not self._game_chat_input.active:
                        direction = self.key_map.get(event.key)
                        if direction:
                            self._send({"type": "move", "direction": direction})
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_t and not self._game_chat_input.active:
                        self._game_chat_input.activate()

                elif self.state == "GAME_OVER":
                    if back_btn and back_btn.clicked(event):
                        self._enter_lobby()

            if self.state == "CONNECT":
                self._draw_connect()
            elif self.state == "USERNAME":
                self._draw_username()
            elif self.state == "LOBBY":
                lobby_btn_rects, watch_btns, acc_btn, dec_btn, challenge_modal = self._draw_lobby()
            elif self.state == "CUSTOMIZE":
                cust_swatch_rects, cust_key_rects, cust_ready_r, cust_map_rects = self._draw_customize()
            elif self.state in ("GAME", "WATCHING"):
                self._draw_game()
            elif self.state == "GAME_OVER":
                back_btn = self._draw_game_over()
            pygame.display.flip()


if __name__ == "__main__":
    ArenaClient().run()
