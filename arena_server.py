"""
Python Arena - Server
EECE 350 - Computing Networks Project

Usage: py -3 arena_server.py
"""

import json
import random
import socket
import threading
import time
import uuid


HOST = "0.0.0.0"
PORT = 8000

GRID_W = 36
GRID_H = 24
TICK_RATE = 8
CUSTOMIZE_TIMEOUT = 45.0
ROUND_TRANSITION = 2.2

VALID_MODES = ("base", "sudden_death", "fog_of_war", "best_of_3")
VALID_MAPS = ("ember", "frost", "vault")

PIE_COLORS = {
    "normal": [100, 200, 100],
    "golden": [255, 215, 50],
    "poison": [200, 50, 150],
}

POWERUP_COLORS = {
    "shield": [180, 180, 220],
    "freeze": [0, 210, 240],
    "double": [255, 200, 50],
}

DIRS = {
    "UP": (0, -1),
    "DOWN": (0, 1),
    "LEFT": (-1, 0),
    "RIGHT": (1, 0),
}

OPPOSITE = {
    "UP": "DOWN",
    "DOWN": "UP",
    "LEFT": "RIGHT",
    "RIGHT": "LEFT",
}

MAPS = {
    "ember": {
        "name": "Ember Forge",
        "obstacles": [
            (12, 5), (13, 5), (22, 5), (23, 5),
            (12, 6), (23, 6),
            (6, 8), (7, 8), (28, 8), (29, 8),
            (6, 15), (7, 15), (28, 15), (29, 15),
            (12, 18), (13, 18), (22, 18), (23, 18),
            (12, 17), (23, 17),
            (17, 10), (18, 10), (17, 13), (18, 13),
        ],
    },
    "frost": {
        "name": "Frost Lattice",
        "obstacles": [
            (9, 4), (9, 5), (9, 6), (9, 17), (9, 18), (9, 19),
            (26, 4), (26, 5), (26, 6), (26, 17), (26, 18), (26, 19),
            (15, 9), (16, 9), (19, 9), (20, 9),
            (15, 14), (16, 14), (19, 14), (20, 14),
            (17, 7), (18, 7), (17, 16), (18, 16),
        ],
    },
    "vault": {
        "name": "Vault Rings",
        "obstacles": [
            (6, 5), (7, 5), (8, 5), (27, 5), (28, 5), (29, 5),
            (6, 18), (7, 18), (8, 18), (27, 18), (28, 18), (29, 18),
            (15, 4), (16, 4), (19, 4), (20, 4),
            (15, 19), (16, 19), (19, 19), (20, 19),
            (4, 10), (4, 11), (4, 12), (31, 10), (31, 11), (31, 12),
            (17, 10), (18, 10), (17, 13), (18, 13),
        ],
    },
}


def now():
    return time.time()


def clamp(value, low, high):
    return max(low, min(high, value))


def clean_text(value, limit=80):
    text = str(value or "").replace("\r", " ").replace("\n", " ").strip()
    return "".join(ch for ch in text if ch.isprintable())[:limit]


def valid_username(value):
    text = clean_text(value, 20)
    if not (2 <= len(text) <= 20):
        return None
    if not all(ch.isalnum() or ch in "_-" for ch in text):
        return None
    return text


class ClientConn:
    def __init__(self, conn, addr):
        self.conn = conn
        self.addr = addr
        self.username = None
        self.state = "CONNECTED"
        self.game_id = None
        self.watching_game_id = None
        self.closed = False
        self.send_lock = threading.Lock()

    def send(self, payload):
        if self.closed:
            return False
        raw = (json.dumps(payload) + "\n").encode("utf-8")
        try:
            with self.send_lock:
                self.conn.sendall(raw)
            return True
        except Exception:
            self.closed = True
            return False

    def close(self):
        if self.closed:
            return
        self.closed = True
        try:
            self.conn.close()
        except Exception:
            pass


class PendingChallenge:
    def __init__(self, challenger, target, mode, map_preference):
        self.id = uuid.uuid4().hex[:12]
        self.challenger = challenger
        self.target = target
        self.mode = mode
        self.map_preference = map_preference
        self.created_at = now()


class GameSession:
    def __init__(self, server, player1, player2, mode, challenger_map):
        self.server = server
        self.id = uuid.uuid4().hex[:10]
        self.rlock = threading.RLock()
        self.players = {1: player1, 2: player2}
        self.user_to_pid = {player1: 1, player2: 2}
        self.mode = mode
        self.target_wins = 2 if mode == "best_of_3" else 1
        self.round_number = 1
        self.round_wins = {player1: 0, player2: 0}
        self.phase = "PREPARING"
        self.created_at = now()
        self.ready = {player1: False, player2: False}
        self.colors = {
            player1: [0, 210, 90],
            player2: [30, 140, 255],
        }
        self.selected_map = challenger_map if challenger_map in VALID_MAPS else "ember"
        self.map_votes = {player1: self.selected_map, player2: self.selected_map}
        self.obstacles = []
        self.viewers = set()
        self.chat_log = []
        self.event_log = []
        self.countdown_deadline = None
        self.round_deadline = None
        self.stop_event = threading.Event()
        self.forfeit = None
        self.final_winner = None
        self.final_reason = ""
        self.last_snapshot = None
        self.snakes = {}
        self.pies = []
        self.powerups = []
        self.safe_zone = None
        self.next_powerup_time = 0.0
        self.next_pie_time = 0.0
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def time_limit(self):
        if self.mode == "sudden_death":
            return 55
        return 90

    def add_event(self, text):
        text = clean_text(text, 70)
        if not text:
            return
        with self.rlock:
            self.event_log.append(text)s
            self.event_log = self.event_log[-7:]

    def mark_forfeit(self, username, reason):
        with self.rlock:
            if self.phase in ("FINISHED", "CANCELLED"):
                return
            if username in self.user_to_pid:
                self.forfeit = (username, reason)

    def remove_viewer(self, username):
        with self.rlock:
            self.viewers.discard(username)

    def add_viewer(self, username):
        with self.rlock:
            self.viewers.add(username)

    def player_client(self, username):
        return self.server.get_client(username)

    def participants(self):
        with self.rlock:
            usernames = [self.players[1], self.players[2], *self.viewers]
        recipients = []
        for uname in usernames:
            client = self.server.get_client(uname)
            if client is not None:
                recipients.append(client)
        return recipients

    def player_recipients(self):
        recipients = []
        for pid in (1, 2):
            client = self.server.get_client(self.players[pid])
            if client is not None:
                recipients.append(client)
        return recipients

    def broadcast(self, payload, players_only=False):
        recipients = self.player_recipients() if players_only else self.participants()
        failed = []
        for client in recipients:
            if not client.send(payload):
                failed.append(client.username)
        for username in failed:
            self.server.handle_disconnect(username)

    def set_customize(self, username, color=None, map_vote=None, ready=None):
        changed = False
        with self.rlock:
            if self.phase not in ("PREPARING", "ROUND_OVER"):
                return False
            if username not in self.user_to_pid:
                return False
            if color:
                self.colors[username] = [int(clamp(v, 0, 255)) for v in color[:3]]
                changed = True
            if ready is not None:
                self.ready[username] = bool(ready)
                changed = True
        if changed:
            self.broadcast_customize_update()
        return changed

    def broadcast_customize_update(self):
        with self.rlock:
            payload = {
                "type": "customize_update",
                "game_id": self.id,
                "mode": self.mode,
                "round_number": self.round_number,
                "target_wins": self.target_wins,
                "round_wins": dict(self.round_wins),
                "map_votes": dict(self.map_votes),
                "selected_map": self.selected_map,
                "ready": dict(self.ready),
                "players": {
                    name: {"color": list(color)}
                    for name, color in self.colors.items()
                },
            }
        self.broadcast(payload)

    def resolve_map(self):
        with self.rlock:
            if self.selected_map not in VALID_MAPS:
                self.selected_map = "ember"
            return self.selected_map

    def reset_round_state(self):
        chosen_map = self.resolve_map()
        start_1 = [(5, GRID_H // 2), (4, GRID_H // 2), (3, GRID_H // 2)]
        start_2 = [(GRID_W - 6, GRID_H // 2), (GRID_W - 5, GRID_H // 2), (GRID_W - 4, GRID_H // 2)]
        with self.rlock:
            self.phase = "PREPARING"
            self.obstacles = list(MAPS[chosen_map]["obstacles"])
            self.pies = []
            self.powerups = []
            self.event_log = []
            self.safe_zone = [0, 0, GRID_W, GRID_H]
            self.next_powerup_time = now() + 8.0
            self.next_pie_time = now()
            self.round_deadline = None
            self.countdown_deadline = None
            self.snakes = {
                "1": {
                    "body": list(start_1),
                    "dir": "RIGHT",
                    "next_dir": "RIGHT",
                    "health": 100,
                    "alive": True,
                    "color": list(self.colors[self.players[1]]),
                    "effects": {},
                    "grow": 0,
                },
                "2": {
                    "body": list(start_2),
                    "dir": "LEFT",
                    "next_dir": "LEFT",
                    "health": 100,
                    "alive": True,
                    "color": list(self.colors[self.players[2]]),
                    "effects": {},
                    "grow": 0,
                },
            }
        while len(self.pies) < 5:
            self.spawn_pie()
        if self.mode != "sudden_death":
            self.spawn_powerup()
        self.add_event(f"Round {self.round_number} on {MAPS[chosen_map]['name']}.")

    def spawn_pie(self):
        with self.rlock:
            occupied = set(self.obstacles)
            for snake in self.snakes.values():
                occupied.update(tuple(cell) for cell in snake["body"])
            occupied.update(tuple(pie["pos"]) for pie in self.pies)
            occupied.update(tuple(pu["pos"]) for pu in self.powerups)
        free = [
            (x, y)
            for x in range(GRID_W)
            for y in range(GRID_H)
            if (x, y) not in occupied
        ]
        if not free:
            return
        pos = random.choice(free)
        roll = random.random()
        kind = "normal"
        if roll < 0.14:
            kind = "golden"
        elif roll < 0.24:
            kind = "poison"
        with self.rlock:
            self.pies.append({"pos": list(pos), "kind": kind, "color": PIE_COLORS[kind]})

    def spawn_powerup(self):
        if self.mode == "sudden_death":
            return
        with self.rlock:
            occupied = set(self.obstacles)
            for snake in self.snakes.values():
                occupied.update(tuple(cell) for cell in snake["body"])
            occupied.update(tuple(pie["pos"]) for pie in self.pies)
            occupied.update(tuple(pu["pos"]) for pu in self.powerups)
        free = [
            (x, y)
            for x in range(GRID_W)
            for y in range(GRID_H)
            if (x, y) not in occupied
        ]
        if not free:
            return
        kind = random.choice(("shield", "freeze", "double"))
        pos = random.choice(free)
        with self.rlock:
            self.powerups = [{"pos": list(pos), "kind": kind, "color": POWERUP_COLORS[kind]}]

    def queue_move(self, username, direction):
        if direction not in DIRS:
            return
        with self.rlock:
            if self.phase != "ACTIVE":
                return
            pid = str(self.user_to_pid.get(username, ""))
            snake = self.snakes.get(pid)
            if not snake or not snake["alive"]:
                return
            if OPPOSITE[direction] == snake["dir"]:
                return
            snake["next_dir"] = direction

    def remaining_time(self):
        with self.rlock:
            if not self.round_deadline:
                return self.time_limit()
            return max(0.0, self.round_deadline - now())

    def serialize_state(self):
        with self.rlock:
            snapshot = {
                "type": "game_state",
                "game_id": self.id,
                "mode": self.mode,
                "map_id": self.selected_map,
                "map_name": MAPS[self.selected_map]["name"] if self.selected_map else "",
                "grid_w": GRID_W,
                "grid_h": GRID_H,
                "phase": self.phase,
                "round_number": self.round_number,
                "target_wins": self.target_wins,
                "round_wins": dict(self.round_wins),
                "time_left": round(self.remaining_time(), 1),
                "usernames": {"1": self.players[1], "2": self.players[2]},
                "snakes": {
                    pid: {
                        "body": [list(cell) for cell in snake["body"]],
                        "dir": snake["dir"],
                        "health": int(clamp(snake["health"], 0, 200)),
                        "alive": snake["alive"],
                        "color": list(snake["color"]),
                    }
                    for pid, snake in self.snakes.items()
                },
                "effects": {
                    pid: sorted(list(snake["effects"].keys()))
                    for pid, snake in self.snakes.items()
                },
                "pies": list(self.pies),
                "powerups": list(self.powerups),
                "obstacles": [list(cell) for cell in self.obstacles],
                "event_log": list(self.event_log),
                "safe_zone": list(self.safe_zone) if self.safe_zone else None,
            }
            self.last_snapshot = snapshot
            return snapshot

    def player_summary(self):
        with self.rlock:
            return {
                self.players[int(pid)]: snake["health"]
                for pid, snake in self.snakes.items()
            }

    def apply_damage(self, pid, amount, reason):
        snake = self.snakes[pid]
        if not snake["alive"] or amount <= 0:
            return False
        if "shield" in snake["effects"]:
            del snake["effects"]["shield"]
            self.add_event(f"{self.players[int(pid)]} blocked {reason.lower()} with a shield.")
            return False
        snake["health"] = clamp(snake["health"] - amount, 0, 200)
        self.add_event(f"{self.players[int(pid)]} took {amount} from {reason.lower()}.")
        if snake["health"] <= 0:
            snake["alive"] = False
            self.add_event(f"{self.players[int(pid)]} was eliminated.")
        return True

    def consume_pie(self, pid, pie):
        snake = self.snakes[pid]
        mult = 2 if "double" in snake["effects"] else 1
        if pie["kind"] == "normal":
            snake["health"] = clamp(snake["health"] + 15 * mult, 0, 200)
            snake["grow"] += 1
            self.add_event(f"{self.players[int(pid)]} ate a pie.")
        elif pie["kind"] == "golden":
            snake["health"] = clamp(snake["health"] + 30 * mult, 0, 200)
            snake["grow"] += 2
            self.add_event(f"{self.players[int(pid)]} ate a golden pie.")
        else:
            self.apply_damage(pid, 20 * mult, "Poison Pie")

    def consume_powerup(self, pid, powerup):
        snake = self.snakes[pid]
        owner = self.players[int(pid)]
        if powerup["kind"] == "shield":
            snake["effects"]["shield"] = now() + 9999.0
            self.add_event(f"{owner} picked up a shield.")
        elif powerup["kind"] == "double":
            snake["effects"]["double"] = now() + 5.0
            self.add_event(f"{owner} activated double pies.")
        elif powerup["kind"] == "freeze":
            opp = "2" if pid == "1" else "1"
            self.snakes[opp]["effects"]["freeze"] = now() + 4.5
            self.add_event(f"{owner} froze {self.players[int(opp)]}.")

    def expire_effects(self):
        t = now()
        with self.rlock:
            for snake in self.snakes.values():
                expired = [name for name, deadline in snake["effects"].items() if deadline <= t]
                for name in expired:
                    del snake["effects"][name]

    def update_safe_zone(self):
        if self.mode != "sudden_death" or not self.round_deadline:
            return
        elapsed = self.time_limit() - self.remaining_time()
        shrink_steps = max(0, int((elapsed - 15) // 8))
        max_steps = min(GRID_W // 4, GRID_H // 4) - 2
        shrink = clamp(shrink_steps, 0, max_steps)
        zone = [shrink, shrink, GRID_W - shrink * 2, GRID_H - shrink * 2]
        with self.rlock:
            if zone != self.safe_zone:
                self.safe_zone = zone
                self.add_event("The safe zone shrank.")

    def inside_safe_zone(self, cell):
        if not self.safe_zone:
            return True
        x0, y0, w, h = self.safe_zone
        return x0 <= cell[0] < x0 + w and y0 <= cell[1] < y0 + h

    def tick_round(self):
        self.expire_effects()
        self.update_safe_zone()

        with self.rlock:
            old_heads = {pid: tuple(snake["body"][0]) for pid, snake in self.snakes.items()}
            old_tails = {pid: tuple(snake["body"][-1]) for pid, snake in self.snakes.items()}
            moves = {}
            frozen_pids = set()
            for pid, snake in self.snakes.items():
                if not snake["alive"]:
                    moves[pid] = old_heads[pid]
                    continue
                if "freeze" in snake["effects"]:
                    frozen_pids.add(pid)
                    moves[pid] = old_heads[pid]
                    continue
                direction = snake["next_dir"]
                if OPPOSITE[direction] != snake["dir"]:
                    snake["dir"] = direction
                dx, dy = DIRS[snake["dir"]]
                hx, hy = old_heads[pid]
                moves[pid] = ((hx + dx) % GRID_W, (hy + dy) % GRID_H)

            for pid, snake in self.snakes.items():
                if not snake["alive"]:
                    continue
                if pid in frozen_pids:
                    continue
                new_head = moves[pid]
                body = [new_head] + list(snake["body"])
                if snake["grow"] > 0:
                    snake["grow"] -= 1
                else:
                    body.pop()
                snake["body"] = body

            pie_hits = {}
            for pid, snake in self.snakes.items():
                if not snake["alive"]:
                    continue
                head = tuple(snake["body"][0])
                for pie in list(self.pies):
                    if tuple(pie["pos"]) == head:
                        pie_hits[pid] = pie
                        self.pies.remove(pie)
                        break

            power_hits = {}
            for pid, snake in self.snakes.items():
                if not snake["alive"]:
                    continue
                head = tuple(snake["body"][0])
                for powerup in list(self.powerups):
                    if tuple(powerup["pos"]) == head:
                        power_hits[pid] = powerup
                        self.powerups.remove(powerup)
                        break

            damage_events = {"1": [], "2": []}
            p1_head = tuple(self.snakes["1"]["body"][0])
            p2_head = tuple(self.snakes["2"]["body"][0])
            p1_old = old_heads["1"]
            p2_old = old_heads["2"]
            p1_swap = p1_head == p2_old and p2_head == p1_old
            head_same = p1_head == p2_head

            if head_same or p1_swap:
                if self.mode == "sudden_death":
                    damage_events["1"].append((999, "Snake Clash"))
                    damage_events["2"].append((999, "Snake Clash"))
                else:
                    damage_events["1"].append((40, "Snake Clash"))
                    damage_events["2"].append((40, "Snake Clash"))
            else:
                if p1_head in [tuple(cell) for cell in self.snakes["2"]["body"][1:]]:
                    damage_events["1"].append((999 if self.mode == "sudden_death" else 35, "Enemy Body"))
                if p2_head in [tuple(cell) for cell in self.snakes["1"]["body"][1:]]:
                    damage_events["2"].append((999 if self.mode == "sudden_death" else 35, "Enemy Body"))

            for pid, snake in self.snakes.items():
                if not snake["alive"]:
                    continue
                head = tuple(snake["body"][0])
                if head in self.obstacles:
                    damage_events[pid].append((25, "Obstacle"))
                if head in [tuple(cell) for cell in snake["body"][1:]]:
                    damage_events[pid].append((30, "Own Body"))
                if self.mode == "sudden_death" and not self.inside_safe_zone(head):
                    damage_events[pid].append((40, "Safe Zone"))

            for pid in ("1", "2"):
                if pie_hits.get(pid):
                    pie = pie_hits[pid]
                    if pie["kind"] == "poison":
                        snake = self.snakes[pid]
                        mult = 2 if "double" in snake["effects"] else 1
                        damage_events[pid].append((20 * mult, "Poison Pie"))

            for pid in ("1", "2"):
                if not self.snakes[pid]["alive"]:
                    continue
                if damage_events[pid]:
                    amount, reason = sorted(damage_events[pid], key=lambda item: (-item[0], item[1]))[0]
                    if amount >= 999:
                        self.snakes[pid]["health"] = 0
                        self.snakes[pid]["alive"] = False
                        self.add_event(f"{self.players[int(pid)]} was eliminated by {reason.lower()}.")
                    else:
                        self.apply_damage(pid, amount, reason)

            for pid in ("1", "2"):
                snake = self.snakes[pid]
                if not snake["alive"]:
                    continue
                pie = pie_hits.get(pid)
                if pie and pie["kind"] != "poison":
                    self.consume_pie(pid, pie)
                powerup = power_hits.get(pid)
                if powerup:
                    self.consume_powerup(pid, powerup)

            for pid in ("1", "2"):
                snake = self.snakes[pid]
                if snake["alive"] and snake["health"] <= 0:
                    snake["alive"] = False

            if now() >= self.next_pie_time and len(self.pies) < 5:
                self.next_pie_time = now() + 4.0
                self.spawn_pie()
            if self.mode != "sudden_death" and now() >= self.next_powerup_time and not self.powerups:
                self.next_powerup_time = now() + random.uniform(9.0, 12.0)
                self.spawn_powerup()

            alive = [pid for pid, snake in self.snakes.items() if snake["alive"]]
            if len(alive) == 2 and self.remaining_time() > 0:
                return None

            if self.remaining_time() <= 0 and len(alive) == 2:
                hp1 = self.snakes["1"]["health"]
                hp2 = self.snakes["2"]["health"]
                if hp1 > hp2:
                    return self.players[1], "Time"
                if hp2 > hp1:
                    return self.players[2], "Time"
                return "TIE", "Time"
            if len(alive) == 1:
                return self.players[int(alive[0])], "Elimination"
            if len(alive) == 0:
                return "TIE", "Double KO"
            return None

    def wait_for_ready(self):
        deadline = now() + CUSTOMIZE_TIMEOUT
        while not self.stop_event.is_set():
            with self.rlock:
                p1_ready = self.ready[self.players[1]]
                p2_ready = self.ready[self.players[2]]
                winner = self.forfeit
            if winner:
                username, reason = winner
                self.cancel_match(f"{username} left before the round started - match cancelled.")
                return False
            if p1_ready and p2_ready:
                return True
            if now() >= deadline:
                self.cancel_match("Ready timeout - match cancelled.")
                return False
            time.sleep(0.1)
        return False

    def send_round_prepare(self):
        with self.server.lock:
            for pid in (1, 2):
                client = self.server.clients.get(self.players[pid])
                if client:
                    client.state = "CUSTOMIZE"
        with self.rlock:
            payload = {
                "type": "round_prepare" if self.round_number > 1 else "game_start",
                "game_id": self.id,
                "mode": self.mode,
                "grid_w": GRID_W,
                "grid_h": GRID_H,
                "selected_map": self.selected_map,
                "map_votes": dict(self.map_votes),
                "round_number": self.round_number,
                "target_wins": self.target_wins,
                "round_wins": dict(self.round_wins),
                "opponent_names": {
                    self.players[1]: self.players[2],
                    self.players[2]: self.players[1],
                },
            }
            viewer_payload = {
                "type": "watch_ok" if self.round_number == 1 else "round_prepare",
                "game_id": self.id,
                "mode": self.mode,
                "grid_w": GRID_W,
                "grid_h": GRID_H,
                "selected_map": self.selected_map,
                "map_votes": dict(self.map_votes),
                "round_number": self.round_number,
                "target_wins": self.target_wins,
                "round_wins": dict(self.round_wins),
                "player1": self.players[1],
                "player2": self.players[2],
            }
            viewers = list(self.viewers)
        for pid in (1, 2):
            client = self.server.get_client(self.players[pid])
            if client is None:
                continue
            data = dict(payload)
            data["player_id"] = pid
            data["opponent"] = self.players[2 if pid == 1 else 1]
            client.send(data)
        for uname in viewers:
            client = self.server.get_client(uname)
            if client:
                client.send(viewer_payload)

    def start_countdown(self):
        with self.rlock:
            self.phase = "COUNTDOWN"
            self.countdown_deadline = now() + 3.0
        self.broadcast({
            "type": "countdown_start",
            "game_id": self.id,
            "seconds": 3,
            "round_number": self.round_number,
            "mode": self.mode,
            "selected_map": self.selected_map,
        })
        while not self.stop_event.is_set() and now() < self.countdown_deadline:
            with self.rlock:
                if self.forfeit:
                    username, reason = self.forfeit
                    self.cancel_match(f"{username} left before the round started - match cancelled.")
                    return False
            time.sleep(0.05)
        return not self.stop_event.is_set()

    def run_round(self):
        with self.rlock:
            self.phase = "ACTIVE"
            self.round_deadline = now() + self.time_limit()
        with self.server.lock:
            for pid in (1, 2):
                client = self.server.clients.get(self.players[pid])
                if client:
                    client.state = "GAME"
        self.broadcast({"type": "game_begin", "game_id": self.id, "round_number": self.round_number})
        frame = 1.0 / TICK_RATE
        while not self.stop_event.is_set():
            with self.rlock:
                if self.forfeit:
                    loser, reason = self.forfeit
                    winner = self.players[1] if loser == self.players[2] else self.players[2]
                    return winner, reason
            result = self.tick_round()
            self.broadcast(self.serialize_state())
            if result:
                return result
            time.sleep(frame)
        return None

    def finish_match(self, winner, reason):
        with self.rlock:
            self.phase = "FINISHED"
            self.final_winner = winner
            self.final_reason = reason
            self.stop_event.set()

    def cancel_match(self, message):
        with self.rlock:
            self.phase = "CANCELLED"
            self.final_reason = message
            self.stop_event.set()
        self.broadcast({"type": "match_cancelled", "msg": message})

    def handle_round_result(self, result):
        if not result:
            return False
        winner, reason = result
        if winner != "TIE":
            with self.rlock:
                self.round_wins[winner] += 1
        self.broadcast({
            "type": "round_over",
            "winner": winner,
            "reason": reason,
            "round_number": self.round_number,
            "round_wins": dict(self.round_wins),
            "target_wins": self.target_wins,
        })
        if reason == "Disconnect":
            self.finish_match(winner, reason)
            return False
        if self.mode != "best_of_3":
            self.finish_match(winner, reason)
            return False
        with self.rlock:
            if winner != "TIE" and self.round_wins[winner] >= self.target_wins:
                self.finish_match(winner, "Match")
                return False
            self.round_number += 1
            self.ready = {self.players[1]: False, self.players[2]: False}
            self.map_votes = {self.players[1]: self.selected_map, self.players[2]: self.selected_map}
            self.phase = "ROUND_OVER"
        time.sleep(ROUND_TRANSITION)
        return True

    def send_final_messages(self):
        payload = {
            "type": "game_over",
            "game_id": self.id,
            "winner": self.final_winner or "TIE",
            "reason": self.final_reason,
            "scores": self.player_summary(),
            "mode": self.mode,
            "round_wins": dict(self.round_wins),
            "target_wins": self.target_wins,
            "round_number": self.round_number,
        }
        self.broadcast(payload)

    def run(self):
        keep_running = True
        while keep_running and not self.stop_event.is_set():
            self.reset_round_state()
            self.send_round_prepare()
            self.broadcast_customize_update()
            if not self.wait_for_ready():
                break
            self.resolve_map()
            self.broadcast_customize_update()
            if not self.start_countdown():
                break
            result = self.run_round()
            keep_running = self.handle_round_result(result)
        if self.phase not in ("CANCELLED",):
            if self.final_winner is None and self.final_reason and self.phase != "CANCELLED":
                self.final_winner = "TIE"
            if self.phase != "CANCELLED":
                self.send_final_messages()
        self.server.finish_game(self)


class ArenaServer:
    def __init__(self, host=HOST, port=PORT):
        self.host = host
        self.port = port
        self.lock = threading.RLock()
        self.sock = None
        self.clients = {}
        self.active_games = {}
        self.pending_by_target = {}
        self.pending_by_challenger = {}
        self.cleanup_thread = threading.Thread(target=self._cleanup_loop, daemon=True)
        self.cleanup_thread.start()

    def _cleanup_loop(self):
        while True:
            time.sleep(1)
            self.cleanup_expired_challenges()

    def get_client(self, username):
        with self.lock:
            return self.clients.get(username)

    def send_to(self, username, payload):
        client = self.get_client(username)
        if not client:
            return False
        if not client.send(payload):
            self.handle_disconnect(username)
            return False
        return True

    def lobby_snapshot(self):
        with self.lock:
            players = [name for name, client in self.clients.items() if client.state == "LOBBY"]
            viewing = [name for name, client in self.clients.items() if client.state == "WATCHING"]
            games = []
            for game in self.active_games.values():
                with game.rlock:
                    if game.phase in ("FINISHED", "CANCELLED"):
                        continue
                    games.append({
                        "game_id": game.id,
                        "player1": game.players[1],
                        "player2": game.players[2],
                        "viewers": len(game.viewers),
                        "mode": game.mode,
                        "map_id": game.selected_map or game.map_votes.get(game.players[1]),
                    })
            recipients = [client for client in self.clients.values() if client.state == "LOBBY"]
        payload = {"type": "lobby_update", "players": players, "viewing": viewing, "games": games}
        failures = []
        for client in recipients:
            if not client.send(payload):
                failures.append(client.username)
        for username in failures:
            self.handle_disconnect(username)

    def cleanup_pending_for(self, username, send_notice=True, reason="Challenge cancelled."):
        notices = []
        with self.lock:
            outgoing = self.pending_by_challenger.pop(username, None)
            if outgoing:
                self.pending_by_target.pop(outgoing.target, None)
                notices.append((outgoing.challenger, {
                    "type": "challenge_cancelled",
                    "from": outgoing.challenger,
                    "msg": reason,
                }))
                notices.append((outgoing.target, {
                    "type": "challenge_cancelled",
                    "from": outgoing.challenger,
                    "msg": reason,
                }))
            incoming = self.pending_by_target.pop(username, None)
            if incoming:
                self.pending_by_challenger.pop(incoming.challenger, None)
                notices.append((incoming.target, {
                    "type": "challenge_cancelled",
                    "from": incoming.challenger,
                    "msg": reason,
                }))
                notices.append((incoming.challenger, {
                    "type": "challenge_cancelled",
                    "from": incoming.challenger,
                    "msg": reason,
                }))
        if send_notice:
            for target, payload in notices:
                self.send_to(target, payload)

    def cleanup_expired_challenges(self):
        expired = []
        with self.lock:
            for challenger, challenge in self.pending_by_challenger.items():
                if now() - challenge.created_at > 10:
                    expired.append(challenger)
        for challenger in expired:
            self.cleanup_pending_for(challenger, reason="Challenge timed out.")

    def register_username(self, client, username):
        username = valid_username(username)
        if not username:
            client.send({"type": "error", "msg": "Username must be 2-20 chars using letters, numbers, _ or -."})
            return
        reply = None
        with self.lock:
            if username in self.clients:
                reply = {"type": "username_taken"}
            else:
                client.username = username
                client.state = "LOBBY"
                self.clients[username] = client
                reply = {"type": "username_ok", "username": username}
        client.send(reply)
        if reply["type"] == "username_ok":
            self.lobby_snapshot()

    def create_challenge(self, client, target, mode, map_preference):
        target = clean_text(target, 20)
        mode = mode if mode in VALID_MODES else None
        map_preference = map_preference if map_preference in VALID_MAPS else None
        if not mode or not map_preference:
            client.send({"type": "error", "msg": "Invalid mode or map selection."})
            return
        error = None
        challenge = None
        with self.lock:
            if client.state != "LOBBY":
                error = "You can only challenge from the lobby."
            else:
                target_client = self.clients.get(target)
                if not target_client or target_client.state != "LOBBY":
                    error = "That player is no longer available."
                elif target == client.username:
                    error = "You cannot challenge yourself."
                elif client.username in self.pending_by_challenger or client.username in self.pending_by_target:
                    error = "Resolve your existing challenge first."
                elif target in self.pending_by_challenger or target in self.pending_by_target:
                    error = "That player already has a pending challenge."
                else:
                    challenge = PendingChallenge(client.username, target, mode, map_preference)
                    self.pending_by_challenger[client.username] = challenge
                    self.pending_by_target[target] = challenge
        if error:
            client.send({"type": "error", "msg": error})
            return
        delivered = self.send_to(target, {
            "type": "challenge_request",
            "from": client.username,
            "mode": mode,
            "map_preference": map_preference,
        })
        if delivered:
            client.send({"type": "challenge_sent", "target": target, "mode": mode, "map_preference": map_preference})
        else:
            self.cleanup_pending_for(client.username, send_notice=False)
            client.send({"type": "error", "msg": "Challenge could not be delivered."})

    def answer_challenge(self, client, challenger, accepted):
        challenger = clean_text(challenger, 20)
        error = None
        cancel_payload = None
        with self.lock:
            if client.state != "LOBBY":
                error = "Only lobby players can accept challenges."
                challenge = None
            else:
                challenge = self.pending_by_target.get(client.username)
                if not challenge or challenge.challenger != challenger:
                    error = "That challenge is no longer valid."
                else:
                    challenger_client = self.clients.get(challenger)
                    if not challenger_client or challenger_client.state != "LOBBY":
                        self.pending_by_target.pop(client.username, None)
                        self.pending_by_challenger.pop(challenger, None)
                        cancel_payload = {
                            "type": "challenge_cancelled",
                            "from": challenger,
                            "msg": "Challenger is no longer available.",
                        }
                    else:
                        self.pending_by_target.pop(client.username, None)
                        self.pending_by_challenger.pop(challenger, None)
        if error:
            client.send({"type": "error", "msg": error})
            return
        if cancel_payload:
            client.send(cancel_payload)
            return

        if not accepted:
            self.send_to(challenger, {"type": "challenge_declined", "from": client.username})
            return

        self.start_game(challenge.challenger, challenge.target, challenge.mode, challenge.map_preference)

    def start_game(self, username1, username2, mode, challenger_map):
        with self.lock:
            player1 = self.clients.get(username1)
            player2 = self.clients.get(username2)
            if not player1 or not player2 or player1.state != "LOBBY" or player2.state != "LOBBY":
                return
            game = GameSession(self, username1, username2, mode, challenger_map)
            self.active_games[game.id] = game
            player1.state = "CUSTOMIZE"
            player2.state = "CUSTOMIZE"
            player1.game_id = game.id
            player2.game_id = game.id
        game.start()
        self.lobby_snapshot()

    def watch_game(self, client, game_id):
        error = None
        with self.lock:
            if client.state != "LOBBY":
                error = "You can only spectate from the lobby."
                game = None
            else:
                game = self.active_games.get(game_id)
        if error:
            client.send({"type": "error", "msg": error})
            return
        if not game:
            client.send({"type": "error", "msg": "That game is no longer running."})
            return
        game.add_viewer(client.username)
        with self.lock:
            client.state = "WATCHING"
            client.watching_game_id = game_id
        with game.rlock:
            selected_map = game.selected_map
            round_number = game.round_number
            round_wins = dict(game.round_wins)
            target_wins = game.target_wins
            mode = game.mode
            player1 = game.players[1]
            player2 = game.players[2]
        client.send({
            "type": "watch_ok",
            "game_id": game_id,
            "grid_w": GRID_W,
            "grid_h": GRID_H,
            "mode": mode,
            "selected_map": selected_map,
            "round_number": round_number,
            "round_wins": round_wins,
            "target_wins": target_wins,
            "player1": player1,
            "player2": player2,
        })
        snapshot = game.serialize_state()
        client.send(snapshot)
        self.lobby_snapshot()

    def finish_game(self, game):
        players_to_reset = []
        viewers_to_reset = []
        with self.lock:
            self.active_games.pop(game.id, None)
            for pid in (1, 2):
                username = game.players[pid]
                client = self.clients.get(username)
                if client and client.game_id == game.id:
                    client.game_id = None
                    client.state = "LOBBY"
                    players_to_reset.append(client)
            for username in list(game.viewers):
                client = self.clients.get(username)
                if client and client.watching_game_id == game.id:
                    client.watching_game_id = None
                    client.state = "LOBBY"
                    viewers_to_reset.append(client)
        self.lobby_snapshot()

    def game_for_user(self, client):
        with self.lock:
            game_id = client.game_id or client.watching_game_id
            if not game_id:
                return None
            return self.active_games.get(game_id)

    def send_lobby_chat(self, client, text):
        if client.state != "LOBBY":
            client.send({"type": "error", "msg": "Lobby chat is only available in the lobby."})
            return
        msg = clean_text(text, 80)
        if not msg:
            return
        with self.lock:
            recipients = [c for c in self.clients.values() if c.state == "LOBBY"]
        failures = []
        payload = {"type": "lobby_chat", "from": client.username, "msg": msg}
        for recipient in recipients:
            if not recipient.send(payload):
                failures.append(recipient.username)
        for username in failures:
            self.handle_disconnect(username)

    def send_game_chat(self, client, text):
        msg = clean_text(text, 80)
        if not msg:
            return
        game = self.game_for_user(client)
        if not game:
            client.send({"type": "error", "msg": "No active game chat available."})
            return
        game.broadcast({"type": "game_chat", "from": client.username, "msg": msg})

    def handle_disconnect(self, username):
        if not username:
            return
        with self.lock:
            client = self.clients.pop(username, None)
            if not client:
                return
            game = self.active_games.get(client.game_id) if client.game_id else None
            watch_game = self.active_games.get(client.watching_game_id) if client.watching_game_id else None
        self.cleanup_pending_for(username, send_notice=True, reason="Challenge cancelled - player disconnected.")
        if game:
            game.mark_forfeit(username, "Disconnect")
        if watch_game:
            watch_game.remove_viewer(username)
        client.close()
        self.lobby_snapshot()

    def handle_message(self, client, payload):
        if not isinstance(payload, dict):
            client.send({"type": "error", "msg": "Malformed message."})
            return
        msg_type = payload.get("type")
        if msg_type == "username":
            if client.username:
                client.send({"type": "error", "msg": "Username already set."})
                return
            self.register_username(client, payload.get("username", ""))
            return

        if not client.username:
            client.send({"type": "error", "msg": "Set a username first."})
            return

        if msg_type == "challenge":
            self.create_challenge(client, payload.get("target", ""), payload.get("mode"), payload.get("map_preference"))
        elif msg_type == "challenge_response":
            self.answer_challenge(client, payload.get("from", ""), bool(payload.get("accepted")))
        elif msg_type == "watch":
            self.watch_game(client, payload.get("game_id", ""))
        elif msg_type == "lobby_chat":
            self.send_lobby_chat(client, payload.get("msg", ""))
        elif msg_type == "game_chat":
            self.send_game_chat(client, payload.get("msg", ""))
        elif msg_type == "move":
            game = self.game_for_user(client)
            if not game or client.state != "GAME":
                return
            game.queue_move(client.username, payload.get("direction"))
        elif msg_type == "customize_choice":
            game = self.game_for_user(client)
            if not game:
                return
            color = payload.get("color")
            if not (isinstance(color, list) and len(color) >= 3):
                color = None
            map_vote = payload.get("map_vote")
            if map_vote not in VALID_MAPS:
                map_vote = None
            game.set_customize(client.username, color=color, map_vote=map_vote)
        elif msg_type == "player_ready":
            game = self.game_for_user(client)
            if not game:
                return
            color = payload.get("color")
            if not (isinstance(color, list) and len(color) >= 3):
                color = None
            map_vote = payload.get("map_vote")
            if map_vote not in VALID_MAPS:
                map_vote = None
            if client.state in ("CUSTOMIZE", "GAME"):
                game.set_customize(client.username, color=color, map_vote=map_vote, ready=True)
        elif msg_type == "leave_watch":
            game = self.game_for_user(client)
            if game and client.watching_game_id:
                game.remove_viewer(client.username)
                with self.lock:
                    client.watching_game_id = None
                    client.state = "LOBBY"
                self.lobby_snapshot()
        else:
            client.send({"type": "error", "msg": "Unknown message type."})

    def client_thread(self, conn, addr):
        client = ClientConn(conn, addr)
        buffer = ""
        try:
            while not client.closed:
                chunk = conn.recv(4096)
                if not chunk:
                    break
                buffer += chunk.decode("utf-8", errors="ignore")
                while "\n" in buffer:
                    raw, buffer = buffer.split("\n", 1)
                    raw = raw.strip()
                    if not raw:
                        continue
                    try:
                        payload = json.loads(raw)
                    except json.JSONDecodeError:
                        client.send({"type": "error", "msg": "Malformed JSON."})
                        continue
                    self.handle_message(client, payload)
        except Exception:
            pass
        finally:
            username = client.username
            if username:
                self.handle_disconnect(username)
            else:
                client.close()

    def serve_forever(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind((self.host, self.port))
        self.sock.listen()
        print(f"Python Arena server listening on {self.host}:{self.port}")
        try:
            lan_ip = socket.gethostbyname(socket.gethostname())
            print(f"Players on your network should connect to {lan_ip}:{self.port}")
        except Exception:
            pass
        while True:
            conn, addr = self.sock.accept()
            threading.Thread(target=self.client_thread, args=(conn, addr), daemon=True).start()


if __name__ == "__main__":
    ArenaServer().serve_forever()
