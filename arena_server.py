"""
Python Arena - Server
EECE 350 - Computing Networks Project
Two-player online snake battle game server.

Usage: python arena_server.py [port]
Default port: 8000
"""

import json
import random
import socket
import sys
import threading
import time


GRID_W = 36
GRID_H = 24
GAME_DURATION = 120
TICK_RATE = 9
INITIAL_HP = 100
MAX_HP = 200
MAX_PIES = 7
MAX_POWERUPS = 2
POWERUP_DURATION = 50
SHIELD_DURATION = 30
READY_TIMEOUT = 30
MAX_MESSAGE_BYTES = 8192
MAX_USERNAME_LEN = 20
MAX_CHAT_LEN = 80

PIE_TYPES = [
    {"kind": "normal", "delta": +15, "color": [0, 200, 60]},
    {"kind": "golden", "delta": +30, "color": [255, 215, 0]},
    {"kind": "poison", "delta": -20, "color": [180, 0, 220]},
]

POWERUP_TYPES = [
    {"kind": "shield", "color": [180, 180, 220]},
    {"kind": "freeze", "color": [0, 210, 240]},
    {"kind": "double", "color": [255, 200, 50]},
]

OBSTACLES = [
    (7, 3), (7, 4), (8, 3),
    (22, 3), (22, 4), (21, 3),
    (14, 9), (15, 9), (14, 10), (15, 10),
    (7, 16), (7, 15), (8, 16),
    (22, 16), (22, 15), (21, 16),
]


def _encode_msg(msg):
    return (json.dumps(msg) + "\n").encode("utf-8")


def _send_raw(conn, data):
    try:
        conn.sendall(data)
        return True
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        return False


def send_msg(conn, msg):
    return _send_raw(conn, _encode_msg(msg))


def sanitize_username(username):
    if not isinstance(username, str):
        return None
    username = username.strip()
    if not username or len(username) > MAX_USERNAME_LEN:
        return None
    if any((not ch.isprintable()) or ch in ":\r\n\t" for ch in username):
        return None
    return username


def sanitize_chat(text):
    if not isinstance(text, str):
        return None
    text = text.replace("\r", " ").replace("\n", " ").replace("\t", " ").strip()
    if not text:
        return None
    text = "".join(ch for ch in text if ch.isprintable())
    return text[:MAX_CHAT_LEN] if text else None


def normalize_color(color):
    if not isinstance(color, (list, tuple)) or len(color) != 3:
        return None
    normalized = []
    for channel in color:
        if not isinstance(channel, (int, float)):
            return None
        normalized.append(max(0, min(255, int(channel))))
    return normalized


class Snake:
    OPPOSITES = {"UP": "DOWN", "DOWN": "UP", "LEFT": "RIGHT", "RIGHT": "LEFT"}
    DELTAS = {"UP": (0, -1), "DOWN": (0, 1), "LEFT": (-1, 0), "RIGHT": (1, 0)}

    def __init__(self, pid, head, direction):
        dx, dy = self.DELTAS[direction]
        self.pid = pid
        self.body = [head, (head[0] - dx, head[1] - dy)]
        self.direction = direction
        self.next_dir = direction
        self.health = INITIAL_HP
        self.alive = True
        self.grow = False

    def set_direction(self, direction):
        if direction in self.DELTAS and direction != self.OPPOSITES.get(self.direction):
            self.next_dir = direction

    def step(self, grid_w, grid_h):
        self.direction = self.next_dir
        dx, dy = self.DELTAS[self.direction]
        hx, hy = self.body[0]
        new_head = ((hx + dx) % grid_w, (hy + dy) % grid_h)
        self.body.insert(0, new_head)
        if self.grow:
            self.grow = False
        else:
            self.body.pop()
        return new_head

    def to_dict(self):
        return {
            "pid": self.pid,
            "body": self.body,
            "health": self.health,
            "alive": self.alive,
            "direction": self.direction,
        }


class GameSession:
    def __init__(self, game_id, p1, p2):
        self.game_id = game_id
        self.players = {1: p1, 2: p2}
        self.snakes = {
            1: Snake(1, (4, GRID_H // 2), "RIGHT"),
            2: Snake(2, (GRID_W - 5, GRID_H // 2), "LEFT"),
        }
        self.obstacles = set(OBSTACLES)
        self.pies = []
        self.powerups = []
        self.viewers = set()
        self.colors = {1: [0, 210, 90], 2: [30, 140, 255]}
        self.effects = {1: {}, 2: {}}
        self.ready = {1: False, 2: False}
        self.rlock = threading.RLock()
        self.start_event = threading.Event()
        self.running = False
        self.start_time = None
        self.ended = False
        self.cancelled = False
        self._spawn_pies()

    def add_viewer(self, username):
        if username not in (self.players[1]["username"], self.players[2]["username"]):
            self.viewers.add(username)

    def remove_viewer(self, username):
        self.viewers.discard(username)

    def _spawn_pies(self):
        occupied = set(self.obstacles)
        for snake in self.snakes.values():
            occupied.update(map(tuple, snake.body))
        occupied.update(tuple(pie["pos"]) for pie in self.pies)

        attempts = 0
        while len(self.pies) < MAX_PIES and attempts < 200:
            attempts += 1
            pos = (random.randint(1, GRID_W - 2), random.randint(1, GRID_H - 2))
            if pos in occupied:
                continue
            pie_type = random.choice(PIE_TYPES)
            self.pies.append({
                "pos": pos,
                "kind": pie_type["kind"],
                "delta": pie_type["delta"],
                "color": pie_type["color"],
            })
            occupied.add(pos)

    def _spawn_powerup(self):
        if len(self.powerups) >= MAX_POWERUPS or random.random() > 0.05:
            return

        occupied = set(self.obstacles)
        for snake in self.snakes.values():
            occupied.update(map(tuple, snake.body))
        occupied.update(tuple(pie["pos"]) for pie in self.pies)
        occupied.update(tuple(powerup["pos"]) for powerup in self.powerups)

        for _ in range(50):
            pos = (random.randint(1, GRID_W - 2), random.randint(1, GRID_H - 2))
            if pos in occupied:
                continue
            powerup_type = random.choice(POWERUP_TYPES)
            self.powerups.append({
                "pos": pos,
                "kind": powerup_type["kind"],
                "color": powerup_type["color"],
            })
            break

    def _apply_damage(self, pid, amount):
        snake = self.snakes[pid]
        if not snake.alive:
            return
        if "shield" in self.effects[pid]:
            del self.effects[pid]["shield"]
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

    def _tick_effects(self):
        for pid in (1, 2):
            for kind in list(self.effects[pid]):
                self.effects[pid][kind] -= 1
                if self.effects[pid][kind] <= 0:
                    del self.effects[pid][kind]

    def _apply_hits_in_order(self, pid, hits):
        for _, amount in hits:
            self._apply_damage(pid, amount)
            if not self.snakes[pid].alive:
                break

    def update(self):
        """
        Advance the game state by one tick.
        Called while game.rlock is held.
        Returns (game_over: bool, winner_pid: int|0, time_left: float)
        """
        self._tick_effects()

        old_heads = {}
        planned_heads = {}
        for pid, snake in self.snakes.items():
            if not snake.alive:
                continue
            if "freeze" in self.effects[pid]:
                snake.next_dir = snake.direction
            dx, dy = Snake.DELTAS[snake.next_dir]
            hx, hy = snake.body[0]
            old_heads[pid] = tuple(snake.body[0])
            planned_heads[pid] = ((hx + dx) % GRID_W, (hy + dy) % GRID_H)

        for pid, snake in self.snakes.items():
            if snake.alive:
                snake.step(GRID_W, GRID_H)

        hits = {1: [], 2: []}
        alive_now = {pid for pid, snake in self.snakes.items() if snake.alive}

        for pid in alive_now:
            head = tuple(self.snakes[pid].body[0])
            if head in self.obstacles:
                hits[pid].append(("obstacle", 25))
            if head in set(map(tuple, self.snakes[pid].body[1:])):
                hits[pid].append(("self", 15))

        if 1 in alive_now and 2 in alive_now:
            same_head = planned_heads[1] == planned_heads[2]
            head_swap = (
                planned_heads[1] == old_heads[2]
                and planned_heads[2] == old_heads[1]
            )
            if same_head or head_swap:
                hits[1].append(("head", 30))
                hits[2].append(("head", 30))
            else:
                body_1 = set(map(tuple, self.snakes[1].body[1:]))
                body_2 = set(map(tuple, self.snakes[2].body[1:]))
                if planned_heads[1] in body_2:
                    hits[1].append(("other", 30))
                if planned_heads[2] in body_1:
                    hits[2].append(("other", 30))

        for pid in (1, 2):
            self._apply_hits_in_order(pid, hits[pid])

        for pid in (1, 2):
            snake = self.snakes[pid]
            if not snake.alive:
                continue

            head = tuple(snake.body[0])
            for pie in self.pies[:]:
                if head != tuple(pie["pos"]):
                    continue
                delta = pie["delta"]
                if "double" in self.effects[pid] and delta > 0:
                    delta *= 2
                snake.health = max(0, min(MAX_HP, snake.health + delta))
                snake.grow = True
                self.pies.remove(pie)
                if snake.health <= 0:
                    snake.alive = False
                break

            if not snake.alive:
                continue

            for powerup in self.powerups[:]:
                if head != tuple(powerup["pos"]):
                    continue
                self._collect_powerup(pid, powerup["kind"])
                self.powerups.remove(powerup)
                break

        self._spawn_pies()
        self._spawn_powerup()

        elapsed = time.time() - self.start_time if self.start_time else 0.0
        time_left = max(0.0, GAME_DURATION - elapsed)

        s1, s2 = self.snakes[1], self.snakes[2]
        if not s1.alive or not s2.alive or time_left <= 0:
            if s1.health > s2.health:
                winner = 1
            elif s2.health > s1.health:
                winner = 2
            else:
                winner = 0
            return True, winner, time_left

        return False, None, time_left

    def get_state(self, time_left):
        snakes_data = {}
        for pid, snake in self.snakes.items():
            snake_dict = snake.to_dict()
            snake_dict["color"] = self.colors.get(pid, [200, 200, 200])
            snakes_data[str(pid)] = snake_dict

        return {
            "type": "game_state",
            "game_id": self.game_id,
            "snakes": snakes_data,
            "pies": [
                {"pos": list(pie["pos"]), "kind": pie["kind"], "color": pie["color"]}
                for pie in self.pies
            ],
            "powerups": [
                {
                    "pos": list(powerup["pos"]),
                    "kind": powerup["kind"],
                    "color": powerup["color"],
                }
                for powerup in self.powerups
            ],
            "effects": {
                str(pid): list(effects.keys())
                for pid, effects in self.effects.items()
            },
            "obstacles": [list(obstacle) for obstacle in self.obstacles],
            "time_left": round(time_left, 1),
            "usernames": {
                str(pid): player["username"] for pid, player in self.players.items()
            },
        }


class Server:
    def __init__(self, port):
        self.port = port
        self.clients = {}
        self.active_games = {}
        self.pending_from = {}
        self.pending_to = {}
        self._game_counter = 0
        self.lock = threading.Lock()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("", port))
        self.sock.listen()

        ip = socket.gethostbyname(socket.gethostname())
        print(f"[SERVER] Python Arena running on {ip}:{port}")
        print(
            f"[SERVER] Grid {GRID_W}x{GRID_H} | "
            f"{GAME_DURATION}s matches | {TICK_RATE} TPS"
        )

    def _next_game_id_locked(self):
        self._game_counter += 1
        return f"game_{self._game_counter}"

    def _player_pid(self, game, username):
        for pid, player in game.players.items():
            if player["username"] == username:
                return pid
        return None

    def _broadcast_lobby(self):
        with self.lock:
            client_snapshot = [
                (username, data["conn"], data["state"])
                for username, data in self.clients.items()
            ]
            games_snapshot = list(self.active_games.values())

        lobby = [username for username, _, state in client_snapshot if state == "lobby"]
        viewing = [username for username, _, state in client_snapshot if state == "viewing"]
        recipients = [conn for _, conn, state in client_snapshot if state == "lobby"]
        games = []
        for game in games_snapshot:
            with game.rlock:
                if game.ended or not game.running:
                    continue
                games.append({
                    "game_id": game.game_id,
                    "player1": game.players[1]["username"],
                    "player2": game.players[2]["username"],
                    "viewers": len(game.viewers),
                })

        msg = {"type": "lobby_update", "players": lobby, "games": games, "viewing": viewing}
        for conn in recipients:
            send_msg(conn, msg)

    def _clear_challenges_for_locked(self, username, notify=True):
        notifications = []

        target = self.pending_to.pop(username, None)
        if target and self.pending_from.get(target) == username:
            del self.pending_from[target]
            target_info = self.clients.get(target)
            if notify and target_info and target_info["state"] == "lobby":
                notifications.append((
                    target_info["conn"],
                    {
                        "type": "challenge_cancelled",
                        "from": username,
                        "msg": f"{username} cancelled the challenge.",
                    },
                ))

        challenger = self.pending_from.pop(username, None)
        if challenger and self.pending_to.get(challenger) == username:
            del self.pending_to[challenger]
            challenger_info = self.clients.get(challenger)
            if notify and challenger_info and challenger_info["state"] == "lobby":
                notifications.append((
                    challenger_info["conn"],
                    {
                        "type": "challenge_cancelled",
                        "from": username,
                        "msg": f"{username} is no longer available.",
                    },
                ))

        return notifications

    def _collect_game_recipients(self, game):
        with game.rlock:
            viewer_names = list(game.viewers)
            player_names = [game.players[1]["username"], game.players[2]["username"]]

        recipients = []
        stale_viewers = []
        with self.lock:
            for username in player_names:
                data = self.clients.get(username)
                if not data or data.get("game") is not game:
                    continue
                recipients.append((username, data["conn"], "player"))
            for username in viewer_names:
                data = self.clients.get(username)
                if not data or data["state"] != "viewing" or data.get("game") is not game:
                    stale_viewers.append(username)
                    continue
                recipients.append((username, data["conn"], "viewer"))

        if stale_viewers:
            with game.rlock:
                for username in stale_viewers:
                    game.remove_viewer(username)
        return recipients

    def _send_to_game(self, game, msg):
        data = _encode_msg(msg)
        stale_viewers = []
        for username, conn, role in self._collect_game_recipients(game):
            if not _send_raw(conn, data) and role == "viewer":
                stale_viewers.append(username)
        if stale_viewers:
            with game.rlock:
                for username in stale_viewers:
                    game.remove_viewer(username)

    def _finish_game(self, game, winner_pid=None, cancel_reason=None, system_text=None):
        with game.rlock:
            if game.ended:
                return False
            game.ended = True
            game.running = False
            if cancel_reason:
                game.cancelled = True
            game.start_event.set()
            players = {pid: player["username"] for pid, player in game.players.items()}
            scores = {players[pid]: game.snakes[pid].health for pid in (1, 2)}
            game.viewers.clear()

        recipients = []
        with self.lock:
            self.active_games.pop(game.game_id, None)
            for username, data in self.clients.items():
                if data.get("game") is not game:
                    continue
                recipients.append((username, data["conn"], data["state"]))
                data.update(state="lobby", game=None, player_id=None)

        if system_text:
            chat_msg = {"type": "game_chat", "from": "SERVER", "msg": system_text}
            payload = _encode_msg(chat_msg)
            for _, conn, _ in recipients:
                _send_raw(conn, payload)

        if cancel_reason:
            cancel_msg = {"type": "match_cancelled", "msg": cancel_reason}
            payload = _encode_msg(cancel_msg)
            for _, conn, _ in recipients:
                _send_raw(conn, payload)
        else:
            winner_name = "TIE" if winner_pid == 0 else players.get(winner_pid, "TIE")
            game_over_msg = {"type": "game_over", "winner": winner_name, "scores": scores}
            payload = _encode_msg(game_over_msg)
            for _, conn, _ in recipients:
                _send_raw(conn, payload)

        self._broadcast_lobby()
        return True

    def _recv_message(self, conn, buffer):
        while "\n" not in buffer:
            try:
                chunk = conn.recv(4096)
            except Exception:
                return None, buffer, "disconnect"
            if not chunk:
                return None, buffer, "disconnect"
            buffer += chunk.decode("utf-8", errors="ignore")
            if len(buffer) > MAX_MESSAGE_BYTES:
                return None, "", "too_large"

        line, buffer = buffer.split("\n", 1)
        if len(line) > MAX_MESSAGE_BYTES:
            return None, buffer, "too_large"
        if not line.strip():
            return None, buffer, "malformed"
        try:
            msg = json.loads(line)
        except Exception:
            return None, buffer, "malformed"
        if not isinstance(msg, dict):
            return None, buffer, "malformed"
        return msg, buffer, None

    def _handle_lobby_challenge(self, username, msg):
        target = msg.get("target")
        notifications = []

        with self.lock:
            requester = self.clients.get(username)
            requester_conn = requester["conn"] if requester else None

            if not isinstance(target, str) or target == username:
                return [(requester_conn, {"type": "error", "msg": "Invalid challenge target."})]

            target_info = self.clients.get(target)
            if not requester or requester["state"] != "lobby":
                return [(requester_conn, {"type": "error", "msg": "You are not in the lobby."})]
            if not target_info or target_info["state"] != "lobby":
                return [(requester_conn, {"type": "error", "msg": "Player not available."})]
            if (
                username in self.pending_to
                or username in self.pending_from
                or target in self.pending_to
                or target in self.pending_from
            ):
                return [(
                    requester_conn,
                    {"type": "error", "msg": "One of the players already has a pending challenge."},
                )]

            self.pending_to[username] = target
            self.pending_from[target] = username
            notifications.append((target_info["conn"], {
                "type": "challenge_request",
                "from": username,
            }))

        if requester_conn:
            notifications.append((requester_conn, {
                "type": "challenge_sent",
                "target": target,
            }))
        return notifications

    def _handle_challenge_response(self, username, msg):
        accepted = bool(msg.get("accepted"))
        challenger = msg.get("from")
        notifications = []
        game_to_start = None

        with self.lock:
            responder = self.clients.get(username)
            responder_conn = responder["conn"] if responder else None
            if not responder or responder["state"] != "lobby":
                return [(responder_conn, {"type": "error", "msg": "You are not in the lobby."})], None

            if self.pending_from.get(username) != challenger or self.pending_to.get(challenger) != username:
                return [(responder_conn, {"type": "error", "msg": "That challenge is no longer valid."})], None

            challenger_info = self.clients.get(challenger)
            if not challenger_info or challenger_info["state"] != "lobby":
                del self.pending_from[username]
                del self.pending_to[challenger]
                return [(responder_conn, {"type": "error", "msg": "The challenger is no longer available."})], None

            del self.pending_from[username]
            del self.pending_to[challenger]

            if not accepted:
                notifications.append((challenger_info["conn"], {
                    "type": "challenge_declined",
                    "from": username,
                }))
                return notifications, None

            self._clear_challenges_for_locked(username, notify=False)
            self._clear_challenges_for_locked(challenger, notify=False)

            gid = self._next_game_id_locked()
            game = GameSession(
                gid,
                {"username": challenger, "conn": challenger_info["conn"]},
                {"username": username, "conn": responder_conn},
            )
            self.active_games[gid] = game
            challenger_info.update(state="customizing", player_id=1, game=game)
            responder.update(state="customizing", player_id=2, game=game)
            notifications.extend([
                (challenger_info["conn"], {
                    "type": "game_start",
                    "player_id": 1,
                    "opponent": username,
                    "game_id": gid,
                    "grid_w": GRID_W,
                    "grid_h": GRID_H,
                }),
                (responder_conn, {
                    "type": "game_start",
                    "player_id": 2,
                    "opponent": challenger,
                    "game_id": gid,
                    "grid_w": GRID_W,
                    "grid_h": GRID_H,
                }),
            ])
            game_to_start = game

        return notifications, game_to_start

    def _handle_watch_request(self, username, msg):
        gid = msg.get("game_id")
        with self.lock:
            watcher = self.clients.get(username)
            watcher_conn = watcher["conn"] if watcher else None
            if not watcher or watcher["state"] != "lobby":
                return [(watcher_conn, {"type": "error", "msg": "You can only spectate from the lobby."})]
            game = self.active_games.get(gid)
            if not game:
                return [(watcher_conn, {"type": "error", "msg": "Game not found."})]

        with game.rlock:
            if game.ended or not game.running:
                return [(watcher_conn, {"type": "error", "msg": "That game is not available to watch yet."})]
            game.add_viewer(username)
            usernames = {str(pid): player["username"] for pid, player in game.players.items()}

        notifications = []
        with self.lock:
            watcher = self.clients.get(username)
            if not watcher or watcher["state"] != "lobby":
                with game.rlock:
                    game.remove_viewer(username)
                return [(watcher_conn, {"type": "error", "msg": "You are no longer in the lobby."})]
            notifications.extend(self._clear_challenges_for_locked(username, notify=True))
            watcher["state"] = "viewing"
            watcher["game"] = game

        notifications.append((
            watcher_conn,
            {
                "type": "watch_ok",
                "game_id": gid,
                "usernames": usernames,
                "grid_w": GRID_W,
                "grid_h": GRID_H,
            },
        ))
        return notifications

    def _handle_lobby_chat(self, username, msg):
        text = sanitize_chat(msg.get("msg"))
        if not text:
            with self.lock:
                client = self.clients.get(username)
                conn = client["conn"] if client else None
            return [(conn, {"type": "error", "msg": "Chat message cannot be empty."})]

        with self.lock:
            recipients = [
                data["conn"] for data in self.clients.values() if data["state"] == "lobby"
            ]

        payload = {"type": "lobby_chat", "from": username, "msg": text}
        return [(conn, payload) for conn in recipients]

    def _disconnect_client(self, username, conn):
        state = None
        game = None
        player_id = None
        notifications = []

        with self.lock:
            client = self.clients.get(username)
            if not client or client["conn"] is not conn:
                return
            state = client["state"]
            game = client.get("game")
            player_id = client.get("player_id")
            notifications = self._clear_challenges_for_locked(username, notify=True)
            del self.clients[username]

        for target_conn, msg in notifications:
            if target_conn:
                send_msg(target_conn, msg)

        if game:
            if state == "viewing":
                with game.rlock:
                    game.remove_viewer(username)
                self._broadcast_lobby()
            elif state == "customizing":
                self._finish_game(
                    game,
                    cancel_reason=f"{username} disconnected before the match started.",
                )
            elif state == "playing":
                winner_pid = 1 if player_id == 2 else 2
                winner_name = game.players[winner_pid]["username"]
                self._finish_game(
                    game,
                    winner_pid=winner_pid,
                    system_text=f"{username} disconnected. {winner_name} wins by forfeit.",
                )
            else:
                self._broadcast_lobby()
        else:
            self._broadcast_lobby()

        print(f"[-] {username} disconnected")

    def handle_client(self, conn, addr):
        username = None
        buffer = ""

        try:
            while True:
                msg, buffer, error = self._recv_message(conn, buffer)
                if error == "disconnect":
                    return
                if error == "too_large":
                    send_msg(conn, {"type": "error", "msg": "Message too large."})
                    return
                if error == "malformed":
                    send_msg(conn, {"type": "error", "msg": "Malformed JSON payload."})
                    continue

                if msg.get("type") != "username":
                    send_msg(conn, {"type": "error", "msg": "Send a username first."})
                    continue

                requested = sanitize_username(msg.get("username"))
                if not requested:
                    send_msg(conn, {
                        "type": "error",
                        "msg": "Username must be 1-20 printable characters.",
                    })
                    continue

                with self.lock:
                    if requested in self.clients:
                        send_msg(conn, {"type": "username_taken"})
                        continue
                    self.clients[requested] = {
                        "conn": conn,
                        "state": "lobby",
                        "player_id": None,
                        "game": None,
                    }
                    username = requested

                send_msg(conn, {"type": "username_ok", "username": username})
                self._broadcast_lobby()
                print(f"[+] {username} connected from {addr}")
                break

            while True:
                msg, buffer, error = self._recv_message(conn, buffer)
                if error == "disconnect":
                    break
                if error == "too_large":
                    send_msg(conn, {"type": "error", "msg": "Message too large."})
                    break
                if error == "malformed":
                    send_msg(conn, {"type": "error", "msg": "Malformed JSON payload."})
                    continue

                mtype = msg.get("type")
                if not isinstance(mtype, str):
                    send_msg(conn, {"type": "error", "msg": "Missing message type."})
                    continue

                with self.lock:
                    client = self.clients.get(username)
                    if not client:
                        break
                    state = client["state"]
                    game = client.get("game")
                    player_id = client.get("player_id")

                if state == "lobby":
                    if mtype == "challenge":
                        notifications = self._handle_lobby_challenge(username, msg)
                        for target_conn, out_msg in notifications:
                            if target_conn:
                                send_msg(target_conn, out_msg)
                    elif mtype == "challenge_response":
                        notifications, game_to_start = self._handle_challenge_response(username, msg)
                        for target_conn, out_msg in notifications:
                            if target_conn:
                                send_msg(target_conn, out_msg)
                        if game_to_start:
                            thread = threading.Thread(
                                target=self._run_game,
                                args=(game_to_start,),
                                daemon=True,
                            )
                            thread.start()
                            self._broadcast_lobby()
                    elif mtype == "watch":
                        notifications = self._handle_watch_request(username, msg)
                        for target_conn, out_msg in notifications:
                            if target_conn:
                                send_msg(target_conn, out_msg)
                        self._broadcast_lobby()
                    elif mtype == "lobby_chat":
                        notifications = self._handle_lobby_chat(username, msg)
                        for target_conn, out_msg in notifications:
                            if target_conn:
                                send_msg(target_conn, out_msg)
                    else:
                        send_msg(conn, {"type": "error", "msg": "Invalid action in the lobby."})

                elif state == "customizing":
                    if mtype != "player_ready" or not game or not player_id:
                        send_msg(conn, {"type": "error", "msg": "Invalid action during customization."})
                        continue

                    color = normalize_color(msg.get("color"))
                    begin_match = False
                    with game.rlock:
                        if game.ended:
                            continue
                        game.ready[player_id] = True
                        if color:
                            game.colors[player_id] = color
                        begin_match = all(game.ready.values())

                    if begin_match:
                        with self.lock:
                            valid = True
                            for pid in (1, 2):
                                player_name = game.players[pid]["username"]
                                pdata = self.clients.get(player_name)
                                if not pdata or pdata["state"] != "customizing" or pdata.get("game") is not game:
                                    valid = False
                                    break
                            if valid:
                                for pid in (1, 2):
                                    player_name = game.players[pid]["username"]
                                    self.clients[player_name]["state"] = "playing"
                        if begin_match and valid:
                            self._send_to_game(game, {"type": "game_begin"})
                            game.start_event.set()

                elif state == "playing":
                    if not game or not player_id:
                        send_msg(conn, {"type": "error", "msg": "You are not attached to a game."})
                        continue

                    if mtype == "move":
                        direction = msg.get("direction")
                        if direction not in Snake.DELTAS:
                            send_msg(conn, {"type": "error", "msg": "Invalid move direction."})
                            continue
                        with game.rlock:
                            if not game.ended and game.snakes[player_id].alive:
                                game.snakes[player_id].set_direction(direction)
                    elif mtype == "game_chat":
                        text = sanitize_chat(msg.get("msg"))
                        if not text:
                            send_msg(conn, {"type": "error", "msg": "Chat message cannot be empty."})
                            continue
                        self._send_to_game(game, {"type": "game_chat", "from": username, "msg": text})
                    else:
                        send_msg(conn, {"type": "error", "msg": "Invalid action during a match."})

                elif state == "viewing":
                    if mtype != "game_chat" or not game:
                        send_msg(conn, {"type": "error", "msg": "Invalid spectator action."})
                        continue
                    text = sanitize_chat(msg.get("msg"))
                    if not text:
                        send_msg(conn, {"type": "error", "msg": "Chat message cannot be empty."})
                        continue
                    self._send_to_game(
                        game,
                        {"type": "game_chat", "from": f"Spectator {username}", "msg": text},
                    )

        except Exception as exc:
            print(f"[!] Error with {username or addr}: {exc}")
        finally:
            if username:
                self._disconnect_client(username, conn)
            try:
                conn.close()
            except Exception:
                pass

    def _run_game(self, game):
        if not game.start_event.wait(READY_TIMEOUT):
            self._finish_game(game, cancel_reason="Match cancelled: ready-up timed out.")
            return

        with game.rlock:
            if game.ended:
                return
            game.running = True
            game.start_time = time.time()

        print(
            f"[GAME] Started: {game.players[1]['username']} vs "
            f"{game.players[2]['username']}"
        )
        self._broadcast_lobby()

        while True:
            time.sleep(1.0 / TICK_RATE)
            with game.rlock:
                if game.ended:
                    break
                game_over, winner_pid, time_left = game.update()
                state_msg = game.get_state(time_left)

            self._send_to_game(game, state_msg)

            if game_over:
                winner_name = "TIE"
                if winner_pid in game.players:
                    winner_name = game.players[winner_pid]["username"]
                print(f"[GAME] Over - winner: {winner_name}")
                self._finish_game(game, winner_pid=winner_pid)
                break

    def run(self):
        print("[SERVER] Waiting for connections...\n")
        while True:
            conn, addr = self.sock.accept()
            thread = threading.Thread(
                target=self.handle_client,
                args=(conn, addr),
                daemon=True,
            )
            thread.start()
            print(
                f"[SERVER] Connection from {addr} | active threads: "
                f"{threading.active_count() - 1}"
            )


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    Server(port).run()
