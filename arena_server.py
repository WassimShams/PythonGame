"""
Πthon Arena - Server
EECE 350 - Computing Networks Project
Two-player online snake battle game server.

Usage: python arena_server.py [port]
Default port: 8000
"""

import socket
import threading
import json
import random
import time
import sys

# ──────────────────────────────────────────────
#  GAME CONSTANTS
# ──────────────────────────────────────────────
GRID_W        = 36          # Grid width  (cells)
GRID_H        = 24          # Grid height (cells)
GAME_DURATION = 120         # Seconds per match
TICK_RATE     = 9           # Server game-loop ticks per second
INITIAL_HP    = 100         # Starting health
MAX_HP        = 200         # Health cap
MAX_PIES      = 7           # Max pies on board at once
MAX_POWERUPS  = 2           # Max power-up items on board at once
POWERUP_DURATION = 50       # Ticks a freeze / double effect lasts (~5 s at 10 TPS)
SHIELD_DURATION  = 30       # Ticks a shield lasts if unused (~3 s)

# Pie definitions: (kind, health_delta, display_color)
PIE_TYPES = [
    {"kind": "normal", "delta": +15, "color": [0, 200,  60]},
    {"kind": "golden", "delta": +30, "color": [255, 215,  0]},
    {"kind": "poison", "delta": -20, "color": [180,  0, 220]},
]

# Power-up definitions
POWERUP_TYPES = [
    {"kind": "shield", "color": [180, 180, 220]},   # silver — absorb next hit
    {"kind": "freeze", "color": [  0, 210, 240]},   # cyan   — freeze opponent
    {"kind": "double", "color": [255, 200,  50]},   # gold   — 2× pie HP
]

# Static obstacle positions (avoid snake spawn zones)
OBSTACLES = [
    (7,  3), (7,  4), (8,  3),
    (22, 3), (22, 4), (21, 3),
    (14, 9), (15, 9), (14,10), (15,10),
    (7, 16), (7, 15), (8, 16),
    (22,16), (22,15), (21,16),
]


# ──────────────────────────────────────────────
#  SNAKE
# ──────────────────────────────────────────────
class Snake:
    OPPOSITES = {"UP":"DOWN","DOWN":"UP","LEFT":"RIGHT","RIGHT":"LEFT"}
    DELTAS    = {"UP":(0,-1),"DOWN":(0,1),"LEFT":(-1,0),"RIGHT":(1,0)}

    def __init__(self, pid, head, direction):
        dx, dy = self.DELTAS[direction]
        self.pid       = pid
        self.body      = [head, (head[0]-dx, head[1]-dy)]   # [head, neck]
        self.direction = direction
        self.next_dir  = direction
        self.health    = INITIAL_HP
        self.alive     = True
        self.grow      = False

    def set_direction(self, d):
        """Queue a direction change (cannot reverse)."""
        if d in self.DELTAS and d != self.OPPOSITES.get(self.direction):
            self.next_dir = d

    def step(self, grid_w, grid_h):
        """Advance one tick with wrap-around. Returns new head position."""
        self.direction = self.next_dir
        dx, dy = self.DELTAS[self.direction]
        hx, hy = self.body[0]
        new_head = ((hx + dx) % grid_w, (hy + dy) % grid_h)
        self.body.insert(0, new_head)
        if self.grow:
            self.grow = False         # keep tail (snake grew)
        else:
            self.body.pop()           # remove tail
        return new_head

    def to_dict(self):
        return {
            "pid":       self.pid,
            "body":      self.body,
            "health":    self.health,
            "alive":     self.alive,
            "direction": self.direction,
        }


# ──────────────────────────────────────────────
#  GAME SESSION
# ──────────────────────────────────────────────
class GameSession:
    """
    Holds all state for one match.
    players = {1: {"username": str, "conn": socket}, 2: {...}}
    """
    def __init__(self, game_id: str, p1, p2):
        self.game_id   = game_id
        self.players   = {1: p1, 2: p2}
        self.snakes    = {
            1: Snake(1, (4,  GRID_H//2), "RIGHT"),
            2: Snake(2, (GRID_W-5, GRID_H//2), "LEFT"),
        }
        self.obstacles  = set(map(tuple, OBSTACLES))
        self.pies       = []
        self.viewers    = []           # list of sockets (spectators)
        self.rlock       = threading.RLock()
        self.running     = False
        self.start_time  = None
        self.ready       = {1: False, 2: False}
        self.colors      = {1: [0, 210, 90], 2: [30, 140, 255]}
        self.start_event = threading.Event()
        self.cancelled   = False
        self.powerups    = []
        self.effects     = {1: {}, 2: {}}   # {effect_kind: ticks_remaining}
        self._spawn_pies()

    # ── Pie management ───────────────────────
    def _spawn_pies(self):
        """Fill board up to MAX_PIES pies."""
        occupied = set()
        for s in self.snakes.values():
            occupied.update(map(tuple, s.body))
        occupied.update(self.obstacles)
        occupied.update(p["pos"] for p in self.pies)

        attempts = 0
        while len(self.pies) < MAX_PIES and attempts < 200:
            attempts += 1
            pos = (random.randint(1, GRID_W-2), random.randint(1, GRID_H-2))
            if pos not in occupied:
                t = random.choice(PIE_TYPES)
                self.pies.append({"pos": pos, "kind": t["kind"],
                                  "delta": t["delta"], "color": t["color"]})
                occupied.add(pos)

    # ── Power-up helpers ─────────────────────
    def _spawn_powerup(self):
        if len(self.powerups) >= MAX_POWERUPS or random.random() > 0.05:
            return
        occupied = set()
        for s in self.snakes.values():
            occupied.update(map(tuple, s.body))
        occupied.update(self.obstacles)
        occupied.update(tuple(p["pos"]) for p in self.pies)
        occupied.update(tuple(p["pos"]) for p in self.powerups)
        for _ in range(50):
            pos = (random.randint(1, GRID_W - 2), random.randint(1, GRID_H - 2))
            if pos not in occupied:
                t = random.choice(POWERUP_TYPES)
                self.powerups.append({"pos": pos, "kind": t["kind"], "color": t["color"]})
                break

    def _apply_damage(self, pid, amount):
        snake = self.snakes[pid]
        if not snake.alive:
            return
        if "shield" in self.effects[pid]:
            del self.effects[pid]["shield"]   # shield consumed, no damage
            return
        snake.health = max(0, snake.health - amount)
        if snake.health <= 0:
            snake.alive = False

    def _collect_powerup(self, pid, kind):
        if kind == "shield":
            self.effects[pid]["shield"] = SHIELD_DURATION
        elif kind == "freeze":
            self.effects[3 - pid]["freeze"] = POWERUP_DURATION
        elif kind == "double":
            self.effects[pid]["double"] = POWERUP_DURATION

    # ── One game tick ─────────────────────────
    def update(self):
        """
        Advance the game state by one tick.
        Called while rlock is held by the game-loop thread.
        Returns (game_over: bool, winner_pid: int|0, time_left: float)
        """
        s1, s2 = self.snakes[1], self.snakes[2]

        # ── Tick down active effects ──────────
        for pid in (1, 2):
            for k in list(self.effects[pid]):
                self.effects[pid][k] -= 1
                if self.effects[pid][k] <= 0:
                    del self.effects[pid][k]

        # ── Freeze: locked snake keeps current direction ──
        for pid, snake in self.snakes.items():
            if snake.alive and "freeze" in self.effects[pid]:
                snake.next_dir = snake.direction

        # Move alive snakes
        for pid, snake in self.snakes.items():
            if snake.alive:
                snake.step(GRID_W, GRID_H)

        # Snapshot all occupied body cells
        all_bodies = {pid: set(map(tuple, s.body)) for pid, s in self.snakes.items()}

        for pid, snake in self.snakes.items():
            if not snake.alive:
                continue
            head = tuple(snake.body[0])

            # ── Obstacle collision ────────────
            if head in self.obstacles:
                self._apply_damage(pid, 25)

            # ── Self collision ────────────────
            if head in set(map(tuple, snake.body[1:])):
                self._apply_damage(pid, 15)

            # ── Other snake collision ─────────
            if head in all_bodies[3 - pid]:
                self._apply_damage(pid, 30)

            # ── Pie collection ────────────────
            for pie in self.pies[:]:
                if head == tuple(pie["pos"]):
                    delta = pie["delta"]
                    if "double" in self.effects[pid] and delta > 0:
                        delta *= 2
                    snake.health = max(0, min(MAX_HP, snake.health + delta))
                    snake.grow = True
                    self.pies.remove(pie)
                    if snake.health <= 0:
                        snake.alive = False

            # ── Power-up collection ───────────
            for pu in self.powerups[:]:
                if head == tuple(pu["pos"]):
                    self._collect_powerup(pid, pu["kind"])
                    self.powerups.remove(pu)

        self._spawn_pies()
        self._spawn_powerup()

        # ── Check end conditions ──────────────
        elapsed    = time.time() - self.start_time
        time_left  = max(0.0, GAME_DURATION - elapsed)

        if not s1.alive or not s2.alive or time_left <= 0:
            if   s1.health > s2.health: winner = 1
            elif s2.health > s1.health: winner = 2
            else:                        winner = 0   # tie
            return True, winner, time_left

        return False, None, time_left

    # ── State snapshot ────────────────────────
    def get_state(self, time_left):
        snakes_data = {}
        for k, v in self.snakes.items():
            d = v.to_dict()
            d["color"] = self.colors.get(k, [200, 200, 200])
            snakes_data[str(k)] = d
        return {
            "type":       "game_state",
            "game_id":    self.game_id,
            "snakes":     snakes_data,
            "pies":       [{"pos": list(p["pos"]), "kind": p["kind"],
                             "color": p["color"]} for p in self.pies],
            "powerups":   [{"pos": list(p["pos"]), "kind": p["kind"],
                             "color": p["color"]} for p in self.powerups],
            "effects":    {str(pid): list(effs.keys())
                           for pid, effs in self.effects.items()},
            "obstacles":  [list(o) for o in self.obstacles],
            "time_left":  round(time_left, 1),
            "usernames":  {str(k): v["username"] for k, v in self.players.items()},
        }

    # ── Broadcast to everyone ─────────────────
    def send_all(self, msg):
        data = (json.dumps(msg) + "\n").encode()
        for pinfo in self.players.values():
            _safe_send_raw(pinfo["conn"], data)
        dead = []
        for viewer in self.viewers:
            try:
                viewer.sendall(data)
            except Exception:
                dead.append(viewer)
        for v in dead:
            self.viewers.remove(v)

    def add_viewer(self, conn):
        self.viewers.append(conn)


# ──────────────────────────────────────────────
#  HELPERS
# ──────────────────────────────────────────────
def _safe_send_raw(conn, data: bytes):
    try:
        conn.sendall(data)
    except Exception:
        pass


def send_msg(conn, msg: dict):
    _safe_send_raw(conn, (json.dumps(msg) + "\n").encode())


# ──────────────────────────────────────────────
#  SERVER
# ──────────────────────────────────────────────
class Server:
    def __init__(self, port: int):
        self.port = port
        # clients[username] = {"conn", "state", "player_id", "game"}
        # state ∈ {"lobby", "playing", "viewing"}
        self.clients      = {}
        self.active_games = {}           # game_id (str) -> GameSession
        self._game_counter = 0
        self.lock         = threading.Lock()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        ip = socket.gethostbyname(socket.gethostname())
        self.sock.bind(("", port))
        self.sock.listen()
        print(f"[SERVER] Πthon Arena running on  {ip}:{port}")
        print(f"[SERVER] Grid {GRID_W}×{GRID_H}  |  {GAME_DURATION}s matches  |  {TICK_RATE} TPS")

    # ── Lobby broadcast ───────────────────────
    def _broadcast_lobby(self):
        """Send updated player list, viewer list, and active games to everyone in the lobby."""
        with self.lock:
            lobby   = [u for u, d in self.clients.items() if d["state"] == "lobby"]
            viewing = [u for u, d in self.clients.items() if d["state"] == "viewing"]
            games   = []
            for g in self.active_games.values():
                n_viewers = sum(1 for d in self.clients.values()
                                if d["state"] == "viewing" and d.get("game") is g)
                games.append({
                    "game_id":  g.game_id,
                    "player1":  g.players[1]["username"],
                    "player2":  g.players[2]["username"],
                    "viewers":  n_viewers,
                })
            msg = {"type": "lobby_update", "players": lobby,
                   "games": games, "viewing": viewing}
            for u, d in self.clients.items():
                if d["state"] == "lobby":
                    send_msg(d["conn"], msg)

    # ── Per-client handler thread ─────────────
    def handle_client(self, conn, addr):
        username = None
        buf      = ""

        def recv():
            """Read one newline-delimited JSON message from the socket."""
            nonlocal buf
            while "\n" not in buf:
                try:
                    chunk = conn.recv(4096).decode("utf-8", errors="ignore")
                    if not chunk:
                        return None
                    buf += chunk
                except Exception:
                    return None
            line, buf = buf.split("\n", 1)
            try:
                return json.loads(line)
            except Exception:
                return None

        try:
            # ─────────────────────────────────
            # PHASE 1 : negotiate username
            # ─────────────────────────────────
            while True:
                msg = recv()
                if not msg:
                    return
                if msg.get("type") != "username":
                    continue
                uname = msg.get("username", "").strip()
                with self.lock:
                    if not uname or uname in self.clients:
                        send_msg(conn, {"type": "username_taken"})
                    else:
                        username = uname
                        self.clients[username] = {
                            "conn": conn, "state": "lobby",
                            "player_id": None, "game": None,
                        }
                        send_msg(conn, {"type": "username_ok", "username": username})
                        break

            self._broadcast_lobby()
            print(f"[+] {username} connected from {addr}")

            # ─────────────────────────────────
            # PHASE 2+ : unified message loop
            # ─────────────────────────────────
            while True:
                msg = recv()
                if not msg:
                    break

                with self.lock:
                    state = self.clients.get(username, {}).get("state", "lobby")

                mtype = msg.get("type")

                # ═══════ LOBBY ═══════════════
                if state == "lobby":

                    if mtype == "challenge":
                        target = msg.get("target", "")
                        with self.lock:
                            tinfo = self.clients.get(target)
                            if tinfo and tinfo["state"] == "lobby":
                                send_msg(tinfo["conn"], {"type": "challenge_request", "from": username})
                                send_msg(conn,          {"type": "challenge_sent",    "target": target})
                            else:
                                send_msg(conn, {"type": "error", "msg": "Player not available"})

                    elif mtype == "challenge_response":
                        accepted   = msg.get("accepted", False)
                        challenger = msg.get("from", "")
                        if accepted:
                            with self.lock:
                                cinfo = self.clients.get(challenger)
                                if cinfo and cinfo["state"] == "lobby":
                                    self._game_counter += 1
                                    gid  = f"game_{self._game_counter}"
                                    p1   = {"username": challenger, "conn": cinfo["conn"]}
                                    p2   = {"username": username,   "conn": conn}
                                    game = GameSession(gid, p1, p2)
                                    self.active_games[gid] = game

                                    # Update client records
                                    self.clients[challenger].update(
                                        state="playing", player_id=1, game=game)
                                    self.clients[username].update(
                                        state="playing", player_id=2, game=game)

                                    # Notify both players
                                    send_msg(cinfo["conn"], {
                                        "type": "game_start", "player_id": 1,
                                        "opponent": username,
                                        "game_id": gid,
                                        "grid_w": GRID_W, "grid_h": GRID_H,
                                    })
                                    send_msg(conn, {
                                        "type": "game_start", "player_id": 2,
                                        "opponent": challenger,
                                        "game_id": gid,
                                        "grid_w": GRID_W, "grid_h": GRID_H,
                                    })

                                    t = threading.Thread(
                                        target=self._run_game, args=(game,), daemon=True)
                                    t.start()
                                else:
                                    send_msg(conn, {"type": "error",
                                                    "msg": "Game could not start"})
                        else:
                            with self.lock:
                                cinfo = self.clients.get(challenger)
                                if cinfo:
                                    send_msg(cinfo["conn"], {
                                        "type": "challenge_declined", "from": username})

                    elif mtype == "watch":
                        gid = msg.get("game_id", "")
                        with self.lock:
                            game = self.active_games.get(gid)
                            if game:
                                game.add_viewer(conn)
                                self.clients[username]["state"] = "viewing"
                                self.clients[username]["game"]  = game
                                un = {str(k): v["username"]
                                      for k, v in game.players.items()}
                                send_msg(conn, {
                                    "type":      "watch_ok",
                                    "game_id":   gid,
                                    "usernames": un,
                                    "grid_w":    GRID_W,
                                    "grid_h":    GRID_H,
                                })
                            else:
                                send_msg(conn, {"type": "error", "msg": "Game not found"})

                    elif mtype == "lobby_chat":
                        # Broadcast text message to all lobby users
                        broadcast_msg = {
                            "type": "lobby_chat",
                            "from": username,
                            "msg":  msg.get("msg", ""),
                        }
                        with self.lock:
                            for _, d in self.clients.items():
                                if d["state"] == "lobby":
                                    send_msg(d["conn"], broadcast_msg)

                # ═══════ PLAYING ═════════════
                elif state == "playing":
                    with self.lock:
                        game = self.clients[username]["game"]
                        pid  = self.clients[username]["player_id"]

                    if mtype == "player_ready" and game and pid:
                        color = msg.get("color")
                        with game.rlock:
                            game.ready[pid] = True
                            if (color and isinstance(color, list) and len(color) == 3
                                    and all(isinstance(c, (int, float)) for c in color)):
                                game.colors[pid] = [max(0, min(255, int(c))) for c in color]
                            if all(game.ready.values()):
                                game.send_all({"type": "game_begin"})
                                game.start_event.set()

                    elif mtype == "move" and game and pid:
                        direction = msg.get("direction", "")
                        if direction in Snake.DELTAS:
                            with game.rlock:
                                if game.snakes[pid].alive:
                                    game.snakes[pid].set_direction(direction)

                    elif mtype == "game_chat" and game:
                        game.send_all({
                            "type": "game_chat",
                            "from": username,
                            "msg":  msg.get("msg", ""),
                        })

                # ═══════ WATCHING ════════════
                elif state == "viewing":
                    if mtype == "game_chat":
                        with self.lock:
                            game = self.clients[username].get("game")
                        if game:
                            game.send_all({
                                "type": "game_chat",
                                "from": f"Spectator {username}",
                                "msg":  msg.get("msg", ""),
                            })

        except Exception as e:
            print(f"[!] Error with {username or addr}: {e}")

        finally:
            if username:
                with self.lock:
                    client_data = self.clients.pop(username, {})

                game = client_data.get("game")
                if game and not game.running:
                    # Disconnected during customization — cancel the pending game
                    game.cancelled = True
                    game.start_event.set()
                    with self.lock:
                        self.active_games.pop(game.game_id, None)
                        for _, d in self.clients.items():
                            if d.get("game") is game:
                                d.update(state="lobby", game=None, player_id=None)
                                send_msg(d["conn"], {
                                    "type": "error",
                                    "msg":  f"{username} disconnected - game cancelled."
                                })

                self._broadcast_lobby()
                print(f"[-] {username} disconnected")
            try:
                conn.close()
            except Exception:
                pass

    # ── Game loop thread ──────────────────────
    def _run_game(self, game: GameSession):
        """Runs in its own daemon thread. Ticks at TICK_RATE Hz."""
        game.start_event.wait()   # block until both players send player_ready
        if game.cancelled:
            return
        game.running    = True
        game.start_time = time.time()
        print(f"[GAME] Started: "
              f"{game.players[1]['username']} vs {game.players[2]['username']}")

        while True:
            time.sleep(1.0 / TICK_RATE)

            with game.rlock:
                game_over, winner_pid, time_left = game.update()
                state_msg = game.get_state(time_left)

            game.send_all(state_msg)

            if game_over:
                # Determine winner name
                if winner_pid == 0:
                    winner_name = "TIE"
                elif winner_pid in game.players:
                    winner_name = game.players[winner_pid]["username"]
                else:
                    winner_name = "TIE"

                final_scores = {
                    game.players[1]["username"]: game.snakes[1].health,
                    game.players[2]["username"]: game.snakes[2].health,
                }

                game.send_all({
                    "type":   "game_over",
                    "winner": winner_name,
                    "scores": final_scores,
                })

                print(f"[GAME] Over — winner: {winner_name}  scores: {final_scores}")

                # Reset player and viewer states back to lobby
                with self.lock:
                    self.active_games.pop(game.game_id, None)
                    for u, d in self.clients.items():
                        if d.get("game") is game:
                            d.update(state="lobby", game=None, player_id=None)

                self._broadcast_lobby()
                break

    # ── Accept loop ───────────────────────────
    def run(self):
        print("[SERVER] Waiting for connections…\n")
        while True:
            conn, addr = self.sock.accept()
            t = threading.Thread(
                target=self.handle_client, args=(conn, addr), daemon=True)
            t.start()
            print(f"[SERVER] Connection from {addr}  |  active threads: "
                  f"{threading.active_count() - 1}")


# ──────────────────────────────────────────────
#  ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    Server(port).run()
