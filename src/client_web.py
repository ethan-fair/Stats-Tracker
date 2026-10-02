"""Browser moderator console for the quiz bowl stats tracker.

Run it with `python client_web.py` (`python3` on macOS/Linux). It is a drop-in
replacement for client.py: every packet to server.py is the same UDP datagram
client.py sends. The page is served on 127.0.0.1 only and talks to this
process, never to the game server.
"""
import os
import sys
import re
import json
import time
import socket
import configparser
import datetime
import atexit
import signal
import threading
import csv
import zlib
import queue
import shutil
import secrets
import webbrowser
import statistics as stats
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

os.chdir(os.path.dirname(os.path.abspath(__file__)))

changes_to_send = []
tentative_changes = []
change_id_counter = 0
pending_players = []
current_question = 0
game_id_num = None

changes_lock = threading.RLock()
send_io_lock = threading.Lock()

ACK_POLL_INTERVAL = 1.0
ACK_DRAIN_TIMEOUT = 10.0
ACK_SILENT_POLLS = 6
ACK_BATCH_SIZE = 8
ACK_SEND_INTERVAL = 0.005
ACK_RESEND_INTERVAL = 5.0

IP = "127.0.0.1"
PORT = 9999
last_reply = 0.0

CATEGORIES = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]


def say(text):
    try:
        print(text, flush=True)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Ported from client.py. Keep these byte-compatible with the text client.
# ---------------------------------------------------------------------------

def queue_change(data):
    tentative_changes.append(data)


def change_is_acked(change_id, ranges):
    for span in ranges:
        if span[0] <= change_id <= span[1]:
            return True
    return False


def poll_server():
    global last_reply
    while True:
        sock = None
        try:
            if game_id_num is not None and changes_to_send:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(0.5)
                sock.sendto(("PLACK" + str(game_id_num)).encode(), (IP, PORT))
                data, addr = sock.recvfrom(65535)
                last_reply = time.time()
                msg = data.decode("utf-8")
                if msg.startswith("ACKS|"):
                    acks = json.loads(msg.split("|", 1)[1])
                    with changes_lock:
                        before = len(changes_to_send)
                        changes_to_send[:] = [c for c in changes_to_send if not change_is_acked(int(c["id"]), acks.get(c["data"][3], []))]
                        if before and not changes_to_send and os.path.exists("changes.json"):
                            os.remove("changes.json")
        except socket.timeout:
            pass
        except Exception:
            pass
        finally:
            if sock is not None:
                sock.close()
        time.sleep(ACK_POLL_INTERVAL)


def sendMessage(message: str, repeat=3, timeout=2.0, address=None):
    global last_reply
    if message.startswith("STSCR"):
        message = message.replace("|", ":" + str(time.monotonic_ns()) + "|", 1)
    for i in range(repeat):
        client_socket = None
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_socket.settimeout(timeout)
            client_socket.sendto(message.encode(), address or (IP, PORT))
            data, addr = client_socket.recvfrom(4096)
            data = data.decode("utf-8")
            client_socket.close()
            last_reply = time.time()
            return data
        except socket.timeout:
            pass
        except ConnectionResetError:
            return "SVRCLS"
        except OSError:
            return "TIMEOUT"
        finally:
            if client_socket:
                client_socket.close()
    return "TIMEOUT"


def flush_pending_players():
    """Re-send player registrations the server never confirmed."""
    if not pending_players:
        return
    for player in list(pending_players):
        reply = sendMessage("ADPLR" + json.dumps(player), repeat=2)
        if reply.startswith("exists|"):
            notify("The username " + player[0] + " already belongs to " + reply[7:] + ", so the stats entered for " + player[1] + " " + player[2] + " are recorded under that player.", "warn")
        elif reply != "pass":
            continue
        with changes_lock:
            if player in pending_players:
                pending_players.remove(player)
        touch()


def ensure_player(username, first_name, last_name):
    """Returns (True | False | "exists", message) like client.py's ensure_player."""
    player = [username, first_name, last_name]
    if username == "pass":
        return "exists", "That username is reserved. Enter a different username."
    reply = sendMessage("ADPLR" + json.dumps(player), repeat=3)
    if reply == "pass":
        return True, ""
    if reply.startswith("exists|"):
        return "exists", "The username " + username + " already belongs to " + reply[7:] + ". Enter a different username, or restart the client to select that player."
    with changes_lock:
        pending_players.append(player)
    return False, "The server did not confirm that " + first_name + " " + last_name + " was added. This will keep retrying."


def remove_change(change_id):
    with changes_lock:
        for i in range(len(changes_to_send)):
            if changes_to_send[i]["id"] == change_id:
                del changes_to_send[i]
                return


def send_changes_synchronously():
    with changes_lock:
        pending = list(changes_to_send)[:ACK_BATCH_SIZE]
    for change in pending:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.sendto(("WRROW" + json.dumps({"id": change["id"], "data": change["data"], "game_id": game_id_num, "hash": zlib.crc32(json.dumps([change["id"], change["data"], game_id_num]).encode())})).encode(), (IP, PORT))
        except OSError:
            pass
        sock.close()
        time.sleep(ACK_SEND_INTERVAL)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(("COMIT" + str(game_id_num)).encode(), (IP, PORT))
    except OSError:
        pass
    sock.close()
    for _ in range(ACK_SILENT_POLLS):
        with changes_lock:
            if not changes_to_send:
                break
        time.sleep(ACK_POLL_INTERVAL)
    with changes_lock:
        return not changes_to_send


def flush_changes(timeout=ACK_DRAIN_TIMEOUT):
    deadline = time.time() + timeout
    remaining = None
    stalled = 0
    while time.time() < deadline:
        writeToDatabase()
        with changes_lock:
            if not changes_to_send:
                return True
            current = len(changes_to_send)
        stalled = stalled + 1 if current == remaining else 0
        remaining = current
        if stalled >= ACK_SILENT_POLLS:
            break
        time.sleep(ACK_POLL_INTERVAL)
    return send_changes_synchronously()


def writeToDatabase():
    flush_pending_players()
    now = time.time()
    with changes_lock:
        batch = []
        for change in changes_to_send:
            if now - change.get("sent", 0) < ACK_RESEND_INTERVAL:
                continue
            change["sent"] = now
            batch.append(("WRROW" + json.dumps({"id": change["id"], "data": change["data"], "game_id": game_id_num, "hash": zlib.crc32(json.dumps([change["id"], change["data"], game_id_num]).encode())})).encode())
            if len(batch) >= ACK_BATCH_SIZE:
                break
        try:
            if changes_to_send:
                with open("changes.json.tmp", "w") as f:
                    json.dump([{"id": c["id"], "data": c["data"]} for c in changes_to_send], f)
                os.replace("changes.json.tmp", "changes.json")
            elif os.path.exists("changes.json"):
                os.remove("changes.json")
        except OSError:
            pass
    if not batch and not changes_to_send:
        return
    with send_io_lock:
        sock = None
        for packet in batch:
            sock = None
            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.setblocking(False)
                sock.sendto(packet, (IP, PORT))
                sock.close()
            except BlockingIOError:
                if sock is not None:
                    sock.close()
                break
            except OSError:
                if sock is not None:
                    sock.close()
                break
            time.sleep(ACK_SEND_INTERVAL)
        while sock is not None:
            try:
                sock.recvfrom(4096)
            except (BlockingIOError, socket.timeout):
                break
            except OSError:
                break
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.settimeout(2)
            sock.sendto(("COMIT" + str(game_id_num)).encode(), (IP, PORT))
            sock.recvfrom(4096)
            sock.close()
        except OSError:
            pass


def write_database_in_background():
    threading.Thread(target=writeToDatabase, daemon=True).start()


def promote(keep=None):
    """Move tentative changes to the send queue, as client.py does after a question."""
    global change_id_counter
    with changes_lock:
        for change in tentative_changes.copy():
            if keep is None or keep(change):
                change_id_counter += 1
                changes_to_send.append({"id": change_id_counter, "data": change})
                tentative_changes.remove(change)


close_lock = threading.Lock()
close_started = False
close_finished = threading.Event()


def close():
    global change_id_counter, close_started
    with close_lock:
        first = not close_started
        close_started = True
    if not first:
        close_finished.wait(60)
        return
    try:
        deadline = time.time() + 5
        while board_queue.unfinished_tasks and time.time() < deadline:
            time.sleep(0.05)
        with changes_lock:
            for change in tentative_changes:
                if change[4] != current_question and not any(c["data"] is change for c in changes_to_send):
                    change_id_counter += 1
                    changes_to_send.append({"id": change_id_counter, "data": change})
            del tentative_changes[:]
            pending = bool(changes_to_send)
        if pending:
            flush_changes()
        with changes_lock:
            if changes_to_send:
                with open("changes.json.tmp", "w") as f:
                    json.dump([{"id": c["id"], "data": c["data"]} for c in changes_to_send], f)
                os.replace("changes.json.tmp", "changes.json")
                changes_to_send[:] = []
                say("Some stats could not be sent to the server. They have been saved and will be sent the next time this client starts.")
            elif pending and os.path.exists("changes.json"):
                os.remove("changes.json")
        if pending_players:
            saved_players = json.load(open("players.json")) if os.path.exists("players.json") else []
            with open("players.json.tmp", "w") as f:
                json.dump(saved_players + [p for p in pending_players if p not in saved_players], f)
            os.replace("players.json.tmp", "players.json")
        try:
            if game_id_num is not None:
                sendMessage("CLOSE" + str(game_id_num), repeat=1)
        except OSError:
            pass
    finally:
        close_finished.set()


def recover_backlog():
    """client.py's startup recovery block. Returns a short status line."""
    global change_id_counter
    notes = []
    if os.path.exists("players.json"):
        with open("players.json") as f:
            loaded_players = json.load(f)
        with changes_lock:
            pending_players[:] = loaded_players
        flush_pending_players()
        if not pending_players:
            os.remove("players.json")
            notes.append("Registered %d saved player%s." % (len(loaded_players), "" if len(loaded_players) == 1 else "s"))
        else:
            notes.append("%d saved player%s still waiting for the server." % (len(pending_players), "" if len(pending_players) == 1 else "s"))
    if os.path.exists("changes.json"):
        with open("changes.json") as f:
            loaded = json.load(f)
        migrated = []
        for item in loaded:
            if isinstance(item, dict) and "id" in item and "data" in item:
                migrated.append(item)
            else:
                change_id_counter += 1
                migrated.append({"id": change_id_counter, "data": item})
        for item in migrated:
            if isinstance(item.get("id"), int) and item["id"] > change_id_counter:
                change_id_counter = item["id"]
        with changes_lock:
            changes_to_send[:] = [c for c in migrated if isinstance(c["data"], list) and len(c["data"]) == 6 and isinstance(c["data"][3], str)]
            count = len(changes_to_send)
        if send_changes_synchronously():
            os.remove("changes.json")
            notes.append("Sent %d older stat%s from a previous session." % (count, "" if count == 1 else "s"))
        else:
            notes.append("Sending %d older stats from a previous session; they keep retrying until the server confirms them." % count)
    return " ".join(notes)


# ---------------------------------------------------------------------------
# Ordered scoreboard sender: one FIFO, one worker, so the scoreboard sees
# messages in the order the moderator produced them.
# ---------------------------------------------------------------------------

board_queue = queue.Queue()


def board_worker():
    failures = 0
    while True:
        with board_queue.not_empty:
            if not board_queue.queue:
                board_queue.not_empty.wait(3.0)
            item = board_queue.queue[0] if board_queue.queue else None
        if item is None:
            game = G
            try:
                if game_id_num is not None:
                    snap = sendMessage("UPDTE" + str(game_id_num) + "|-1", repeat=1)
                    snap = json.loads(snap[5:]) if snap.startswith("SNAP|") else None
                    with state_lock:
                        if snap and game is not None and game.phase != "registering" and G is game and not board_queue.queue:
                            if [snap["score"].get("a"), snap["score"].get("b")] != [game.score["a"], game.score["b"]]:
                                game.send_score()
                            for team in ("a", "b"):
                                if snap["messages"][team] != game.messages[team]:
                                    game.send_messages(team)
                            seats = {team: game.seats[team] for team in ("a", "b") if snap["seats"][team] != game.seats[team]}
                            if seats:
                                game.stscr(["NEW_PLAYERS", seats])
                            question = [game.lq["i"], "lightning"] if game.lq else [game.tossup, "tossup"]
                            if snap["question"] != question:
                                game.stscr(["QUESTION"] + question)
                            if snap["names"] != {"a": game.teamAName, "b": game.teamBName}:
                                post("STGME" + json.dumps([game.date, {"packet": game.packet, "player_data": [], "name": game.name, "a_name": game.teamAName, "b_name": game.teamBName}, game_id_num]))
            except Exception:
                pass
            continue
        try:
            reply = sendMessage(item[1], repeat=1, timeout=0.5 * 2 ** min(failures, 2))
        except Exception:
            reply = "error"
        failures = failures + 1 if reply in ("TIMEOUT", "SVRCLS") else 0
        with board_queue.mutex:
            if not failures and board_queue.queue and board_queue.queue[0] is item:
                board_queue.queue.popleft()
                board_queue.unfinished_tasks -= 1
        if failures:
            time.sleep(0.25)


def post(message):
    code, _, body = message.partition("|")
    kind = json.loads(body)[0] if code[:5] in ("STSCR", "STMSG") else None
    slot = code[:5] + str(kind) + ("".join(sorted(json.loads(body)[1])) if kind == "NEW_PLAYERS" else "")
    with board_queue.mutex:
        for old in list(board_queue.queue):
            if (code[:5] == "RESCR" or (old[0] == slot and kind not in ("SET_HIGHLIGHT", "HIGHLIGHT"))
                    or (kind == "NEW_PLAYERS" and old[0].startswith("STSCRNEW_PLAYERS") and set(old[0][16:]) <= set(slot[16:]))
                    or (kind == "SET_HIGHLIGHT" and old[0] in ("STSCRSET_HIGHLIGHT", "STSCRHIGHLIGHT"))):
                board_queue.queue.remove(old)
                board_queue.unfinished_tasks -= 1
    board_queue.put((slot, message))


def keepalive_loop():
    ticks = 0
    while True:
        time.sleep(1)
        ticks += 1
        try:
            if game_id_num is not None and ticks % 300 == 0:
                sendMessage("KPALV" + str(game_id_num), repeat=1)
            if game_id_num is not None and changes_to_send:
                writeToDatabase()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Application state. The page only renders what lives here.
# ---------------------------------------------------------------------------

state_lock = threading.RLock()
rev = 0
players_rev = 0
toasts = []
toast_seq = 0
name_rows = []
RUN_TOKEN = os.urandom(8).hex()
PAGE_TOKEN = secrets.token_urlsafe(24)
G = None
httpd = None

MAX_USERNAME = 32
MAX_NAME = 64

app = {
    "screen": "connect",
    "host": "",
    "port": "",
    "connect": {"phase": "connecting", "error": ""},
    "session_name": "",
    "recovery": "",
    "setup": None,
    "setup_seq": 0,
    "setup_check": None,
    "setup_error": "",
    "lookup": None,
    "settings": {"busy": False, "error": "", "ok": ""},
    "save": {"running": False, "result": ""},
    "test": None,
    "reconnecting": False,
    "lists": False,
}


def touch():
    global rev
    with state_lock:
        rev += 1


def players_changed():
    global players_rev
    with state_lock:
        players_rev += 1
        touch()


def notify(text, kind="info"):
    global toast_seq
    with state_lock:
        toast_seq += 1
        toasts.append({"id": toast_seq, "kind": kind, "text": text})
        del toasts[:-12]
        touch()


class UserError(Exception):
    """A message for the moderator, shown next to whatever caused it."""


def short_name(row):
    return row["first_name"] + " " + row["last_name"][:1] + "."


def clean_label(value, what="This"):
    value = str(value or "").strip()
    if not value:
        return None, what + " cannot be empty."
    if "|" in value:
        return None, what + " cannot contain the \"|\" character."
    if len(value) > MAX_NAME:
        return None, what + " must be %d characters or fewer." % MAX_NAME
    return value, ""


def today_str():
    return datetime.date.today().strftime("%m/%d/%Y")


# ---------------------------------------------------------------------------
# config.ini
# ---------------------------------------------------------------------------

def read_config():
    """Returns (host, port, error)."""
    config = configparser.ConfigParser()
    try:
        config.read("../config.ini")
    except configparser.Error:
        return "", "", "config.ini is incorrectly formatted."
    if not (config.has_section("CONNECTION") and config.has_section("FORMAT")):
        return "", "", "config.ini does not exist. Enter the server address to create it."
    try:
        host = config["CONNECTION"]["ip"]
        port = int(config["CONNECTION"]["port"])
        config["FORMAT"]["use_rich_text"]
    except (KeyError, ValueError):
        return config["CONNECTION"].get("ip", ""), config["CONNECTION"].get("port", ""), "config.ini is incorrectly formatted."
    return host, port, ""


def validate_address(host, port):
    host = str(host or "").strip()
    if not host:
        raise UserError("Enter the server's host name or IP address.")
    if not re.fullmatch(r"[A-Za-z0-9._-]+", host):
        raise UserError("The host can only contain letters, digits, dots, hyphens and underscores.")
    try:
        port = int(str(port).strip())
    except ValueError:
        raise UserError("The port must be a whole number from 1 to 65535.")
    if not 1 <= port <= 65535:
        raise UserError("The port must be a whole number from 1 to 65535.")
    return host, port


def write_config(host, port):
    """Write ip and port into ../config.ini atomically, keeping everything else."""
    path = "../config.ini"
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", newline="") as f:
            text = f.read()
        nl = "\r\n" if "\r\n" in text else "\n"
        lines = text.splitlines()
        out = []
        section = None
        seen_sections = set()
        done = {"ip": False, "port": False}

        def finish_connection():
            for key, value in (("ip", host), ("port", str(port))):
                if not done[key]:
                    out.append(key + " = " + value)
                    done[key] = True

        for line in lines:
            header = re.match(r"^\s*\[([^\]]+)\]\s*$", line)
            if header:
                if section == "CONNECTION":
                    finish_connection()
                section = header.group(1)
                seen_sections.add(section)
                out.append(line)
                continue
            if section == "CONNECTION":
                key = re.match(r"^\s*(ip|port)\s*[=:]", line, re.IGNORECASE)
                if key and not line.lstrip().startswith((";", "#")):
                    name = key.group(1).lower()
                    if not done[name]:
                        out.append(name + " = " + (host if name == "ip" else str(port)))
                        done[name] = True
                    continue
            out.append(line)
        if section == "CONNECTION":
            finish_connection()
        if "CONNECTION" not in seen_sections:
            out += ["[CONNECTION]", "ip = " + host, "port = " + str(port)]
        if "FORMAT" not in seen_sections:
            out += ["[FORMAT]", "use_rich_text = True"]
        text = nl.join(out) + nl
    else:
        nl = "\r\n" if os.name == "nt" else "\n"
        text = nl.join(["[CONNECTION]", "ip = " + host, "port = " + str(port), "[FORMAT]", "use_rich_text = True"]) + nl
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8", newline="") as f:
        f.write(text)
    if os.path.exists(path):
        try:
            shutil.copymode(path, tmp)
        except OSError:
            pass
    os.replace(tmp, path)
    check_host, check_port, error = read_config()
    if error or check_host != host or check_port != port:
        raise UserError("config.ini was written but could not be read back. Check the file by hand.")


def resolve(host):
    try:
        return socket.gethostbyname(host)
    except OSError:
        return host


def load_players(address):
    """client.py's PLNME paging. Returns (rows, error)."""
    rows = []
    while True:
        data = sendMessage("PLNME" + str(len(rows)), address=address)
        if data == "SVRCLS" or data == "TIMEOUT":
            return None, "The server is not responding. Launch the server and try again, or change the IP."
        try:
            data = json.loads(data)
        except (json.JSONDecodeError, TypeError):
            return None, "The server could not read the player list. Try again in a moment."
        if not isinstance(data, list):
            return None, "The server could not read the player list. Try again in a moment."
        if not data or data[0] in rows:
            return rows, ""
        rows += data


background_started = False


def connect_flow():
    """Startup: read config.ini, resolve, load players. Then ask for a session name."""
    global IP, PORT
    with state_lock:
        app["screen"] = "connect"
        app["connect"] = {"phase": "connecting", "error": ""}
        touch()
    host, port, error = read_config()
    with state_lock:
        app["host"], app["port"] = host, port
        if error:
            app["connect"] = {"phase": "failed", "error": error}
            touch()
            return
    ip = resolve(host)
    rows, error = load_players((ip, port))
    app["lists"] = not error and sendMessage("PROBELISTS", address=(ip, port)) == "lists"
    with state_lock:
        if error:
            app["connect"] = {"phase": "failed", "error": error}
        else:
            IP, PORT = ip, port
            name_rows[:] = rows
            app["connect"] = {"phase": "session", "error": ""}
            players_changed()
        touch()


def request_game_id(session_name):
    global game_id_num, background_started
    session_name = "".join(ch for ch in str(session_name or "") if ch.isalnum() or ch in " _-").strip()[:32]
    with state_lock:
        app["connect"] = {"phase": "requesting", "error": ""}
        app["session_name"] = session_name
        touch()
    data = sendMessage("PLNUM" + RUN_TOKEN + "|" + session_name)
    if data == "SVRCLS" or data == "TIMEOUT" or not data.isdigit():
        with state_lock:
            app["connect"] = {"phase": "failed", "error": "The server did not issue a game ID. Launch the server and try again, or change the IP."}
            touch()
        return
    with state_lock:
        game_id_num = int(data)
        app["connect"] = {"phase": "recovering", "error": ""}
        touch()
    if not background_started:
        background_started = True
        threading.Thread(target=keepalive_loop, daemon=True).start()
        threading.Thread(target=poll_server, daemon=True).start()
    try:
        note = recover_backlog()
    except (OSError, ValueError) as e:
        note = "Could not read the saved backlog: " + str(e)
    with state_lock:
        app["recovery"] = note
        app["connect"] = {"phase": "done", "error": ""}
        app["screen"] = "home"
        players_changed()


def reconnect(host, port):
    """Settings saved from Home: move this session to a new server address."""
    global IP, PORT, game_id_num
    old_address = (IP, PORT)
    old_gid = game_id_num
    ip = resolve(host)
    try:
        probe = sendMessage("PROBELISTS", address=(ip, port))
        if probe not in ("pass", "lists"):
            raise UserError("Saved to config.ini, but %s:%d did not answer. Still using the previous server." % (host, port))
        rows, error = load_players((ip, port))
        if error:
            raise UserError("Saved to config.ini, but " + error[0].lower() + error[1:] + " Still using the previous server.")
        data = sendMessage("PLNUM" + RUN_TOKEN + "|" + app["session_name"], address=(ip, port))
        if not data.isdigit():
            raise UserError("Saved to config.ini, but %s:%d did not issue a game ID. Still using the previous server." % (host, port))
        new_gid = int(data)
        with state_lock:
            IP, PORT = ip, port
            name_rows[:] = rows
            game_id_num = new_gid
            app["lists"] = probe == "lists"
            app["host"], app["port"] = host, port
            if new_gid == old_gid:
                app["settings"] = {"busy": False, "error": "", "ok": "Connected to %s:%d. Same server, so the game ID is unchanged." % (host, port)}
            else:
                app["settings"] = {"busy": False, "error": "", "ok": "Connected to %s:%d. The game ID is now %d; give it to the scoreboard operator." % (host, port, new_gid)}
            players_changed()
        if new_gid != old_gid:
            notify("New game ID %d. Scoreboards must switch to it." % new_gid, "warn")
            if old_gid is not None:
                try:
                    sendMessage("CLOSE" + str(old_gid), repeat=1, address=old_address)
                except OSError:
                    pass
        write_database_in_background()
    except UserError as e:
        with state_lock:
            app["host"], app["port"] = host, port
            app["settings"] = {"busy": False, "error": str(e), "ok": ""}
            touch()
    finally:
        with state_lock:
            app["reconnecting"] = False
            app["settings"]["busy"] = False
            touch()


# ---------------------------------------------------------------------------
# Live report, computed with pdf.py's maths so it agrees with the printout.
# ---------------------------------------------------------------------------

def _seat_count(log, team, phase):
    per_q = {}
    for e in log:
        if e[5] != team:
            continue
        if phase == "tossup":
            heard = e[1] in CATEGORIES and e[2] == [0, 0, 0, 1]
        else:
            heard = e[1] == "lightning" and e[2] == [0, 0, 1]
        if heard:
            per_q[e[4]] = per_q.get(e[4], 0) + 1
    return max(per_q.values(), default=1)


def _conv_band(pct):
    if pct >= 67:
        return "hi"
    if pct >= 34:
        return "mid"
    return "lo"


def live_report(log, rows):
    full = {}
    for row in rows:
        full[row["username"]] = row["first_name"] + " " + row["last_name"]
    log = sorted(log, key=lambda e: e[4])
    seats = {t: _seat_count(log, t, "tossup") for t in ("a", "b")}
    lseats = {t: _seat_count(log, t, "lightning") for t in ("a", "b")}
    round_data = {0: {"a": 0, "b": 0}}
    bonus = {"a": [0, 0], "b": [0, 0]}
    lteam = {"a": [0, 0, 0], "b": [0, 0, 0]}
    has_tossup = False
    for e in log:
        q, team, field, value = e[4], e[5], e[1], e[2]
        if q not in round_data and field != "lightning":
            round_data[q] = dict(round_data[max(k for k in round_data if k < q)])
        if field != "lightning":
            has_tossup = True
        if field in CATEGORIES:
            round_data[q][team] += 15 * value[0]
            round_data[q][team] += 10 * value[1]
            round_data[q][team] -= 5 * value[2]
        if field == "bonus_ans":
            round_data[q][team] += 10 / seats[team]
            bonus[team][0] += 1
        if field == "bonus_heard":
            bonus[team][1] += 1
    for q in round_data:
        round_data[q]["a"] = round(round_data[q]["a"])
        round_data[q]["b"] = round(round_data[q]["b"])
    for t in ("a", "b"):
        bonus[t][0] = round(bonus[t][0] / seats[t])
        bonus[t][1] = round(bonus[t][1] / seats[t])
    max_index = max(round_data.keys())
    lightning_data = {0: {"a": round_data[max_index]["a"], "b": round_data[max_index]["b"]}}
    has_lightning = False
    for e in log:
        if e[1] != "lightning":
            continue
        q, team, value = e[4], e[5], e[2]
        if q not in lightning_data:
            lightning_data[q] = dict(lightning_data[max(k for k in lightning_data if k < q)])
        lightning_data[q][team] += 10 * value[0]
        lightning_data[q][team] -= 10 * value[1]
        lteam[team][0] += value[0]
        lteam[team][1] += value[1]
        lteam[team][2] += value[2]
        has_lightning = True
    for t in ("a", "b"):
        lteam[t][2] = round(lteam[t][2] / lseats[t])
    full_chart = [[k, round_data[k]["a"], round_data[k]["b"]] for k in sorted(round_data)]
    lightning_keys = sorted(k for k in lightning_data if k != 0)
    for offset, k in enumerate(lightning_keys, start=1):
        full_chart.append([max_index + offset, lightning_data[k]["a"], lightning_data[k]["b"]])

    def tossup_table(team):
        players = {}
        for e in log:
            if e[5] == team:
                players.setdefault(e[0], []).append((e[1], e[2]))
        players = {p: evs for p, evs in players.items() if any(f in CATEGORIES for f, _ in evs)}
        out = []
        for p, evs in players.items():
            tuh = sum(v[3] for f, v in evs if f in CATEGORIES)
            if not p.isalpha():
                tuh = round(tuh / seats[team])
            powers = sum(v[0] for f, v in evs if f in CATEGORIES)
            tens = sum(v[1] for f, v in evs if f in CATEGORIES)
            negs = sum(v[2] for f, v in evs if f in CATEGORIES)
            pts = powers * 15 + tens * 10 + negs * -5
            out.append({"name": full.get(p, p) if p.isalpha() else "Combined Score", "pts": pts,
                        "rate": f"{(pts / tuh) * 20 if tuh > 0 else 0:.1f}",
                        "segs": [powers, tens, negs, max(0, tuh - (powers + tens + negs))]})
        out.sort(key=lambda r: r["pts"], reverse=True)
        return out

    def lightning_table(team):
        players = {}
        for e in log:
            if e[5] == team:
                players.setdefault(e[0], []).append((e[1], e[2]))
        players = {p: evs for p, evs in players.items() if any(f == "lightning" for f, _ in evs)}
        out = []
        for p, evs in players.items():
            tuh = sum(v[2] for f, v in evs if f == "lightning")
            if not p.isalpha():
                tuh = round(tuh / lseats[team])
            tens = sum(v[0] for f, v in evs if f == "lightning")
            negs = sum(v[1] for f, v in evs if f == "lightning")
            out.append({"name": full.get(p, p) if p.isalpha() else "Combined Score", "pts": tens * 10 + negs * -10,
                        "segs": [0, tens, negs, max(0, tuh - (tens + negs))]})
        out.sort(key=lambda r: r["pts"], reverse=True)
        return out

    bonus_rows = {}
    light_rows = {}
    for t in ("a", "b"):
        ans, heard = bonus[t]
        conv = ans / heard * 100 if heard > 0 else 0
        bonus_rows[t] = {"ans": ans, "heard": heard, "conv": f"{conv:.1f}%", "ppb": f"{ans / heard * 30 if heard > 0 else 0:.1f}", "pct": max(0, min(100, conv)), "band": _conv_band(conv)}
        correct, incorrect, lheard = lteam[t]
        lconv = correct / lheard * 100 if lheard > 0 else 0
        light_rows[t] = {"correct": correct, "incorrect": incorrect, "heard": lheard, "conv": f"{lconv:.1f}%", "pct": max(0, min(100, lconv)), "band": _conv_band(lconv)}
    return {
        "has_tossup": has_tossup,
        "has_lightning": has_lightning,
        "tossup": {"a": tossup_table("a"), "b": tossup_table("b")} if has_tossup else None,
        "lightning": {"a": lightning_table("a"), "b": lightning_table("b")} if has_lightning else None,
        "bonus": bonus_rows,
        "light": light_rows,
        "chart": full_chart,
        "split": max_index if has_tossup and has_lightning else None,
    }


# ---------------------------------------------------------------------------
# The game: a port of client.py's questionTracker as a state machine.
# Every method runs with state_lock held.
# ---------------------------------------------------------------------------

class Game:
    def __init__(self, cfg):
        self.rows = name_rows
        self.tossups = cfg["tossups"]
        self.lightnings = cfg["lightnings"]
        self.n = cfg["players"]
        self.teamA = cfg["teamA"]
        self.teamB = cfg["teamB"]
        self.a_ind = cfg["a_ind"]
        self.b_ind = cfg["b_ind"]
        self.teamAName = cfg["a_name"]
        self.teamBName = cfg["b_name"]
        self.name = cfg["name"]
        self.packet = cfg["packet"]
        self.packet_known = cfg["packet_known"]
        self.packet_name = cfg["packet_name"]
        self.score = {"a": 0, "b": 0, "points": {}, "roster": {"a": self.teamA, "b": self.teamB}}
        self.tossup = 0
        self.messages = {"a": [], "b": []}
        self.message_seq = 0
        self.seats = {"a": [], "b": []}
        self.snap_messages = {}
        self.snap_seats = {}
        self.snap_scores = {}
        self.snap_rosters = {}
        self.do_revert = False
        self.date = None
        self.phase = "registering"
        self.register = {"status": "Saving stats…", "cancel": False}
        self.tu = None
        self.lq = None
        self.sel = None
        self.log = []
        self.log_ver = 0
        self.report_cache = (None, None)
        self.warning = ""
        self.final = None

    # -- scoreboard messages, all through the ordered sender --
    def stscr(self, payload):
        post("STSCR" + str(game_id_num) + "|" + json.dumps(payload))

    def send_score(self):
        post("HLSCR" + str(game_id_num) + "|" + json.dumps(self.score))

    def send_messages(self, team):
        post("STMSG" + str(game_id_num) + "|" + json.dumps([team, self.messages[team]]))

    def add_message(self, team, text):
        self.message_seq += 1
        self.messages[team].append([self.message_seq, text])
        del self.messages[team][:-5]
        self.send_messages(team)

    def names(self, team_names=False):
        out = {}
        for row in self.rows:
            u = row["username"]
            if team_names and u.startswith("!"):
                out[u] = self.teamAName if u == "!playerA" else self.teamBName
            else:
                out[u] = short_name(row)
        return out

    def team_list(self, team):
        return self.teamA if team == "a" else self.teamB

    def board_seats(self, team):
        name_list = self.names()
        return ["" if i.startswith("!") else name_list[i] for i in self.team_list(team)]

    def queue(self, change):
        users = change[0] if isinstance(change[0], list) else [change[0]]
        self.log.extend([user] + change[1:] for user in users)
        self.log_ver += 1
        if not (app["lists"] and isinstance(change[0], list)):
            for user in users:
                queue_change([user] + change[1:])
            return
        chunk = []
        for user in users:
            if chunk and len(("WRROW" + json.dumps({"id": 999999, "data": [chunk + [user]] + change[1:], "game_id": 999999, "hash": 4294967295})).encode()) > 548:
                queue_change([chunk] + change[1:])
                chunk = []
            chunk.append(user)
        queue_change([chunk] + change[1:])

    def heard_markers(self, field, value, question):
        users = {"a": [], "b": []}
        for row in self.rows:
            u = row["username"]
            if u in self.teamA or u in self.teamB:
                users["a" if u in self.teamA else "b"].append(u)
        for team in ("a", "b"):
            if users[team]:
                self.queue([users[team], field, value, self.date, question, team])

    def seat_arg(self, team, seat):
        if team not in ("a", "b"):
            raise UserError("Pick a seat.")
        try:
            seat = int(seat)
        except (TypeError, ValueError):
            raise UserError("Pick a seat.")
        if not 1 <= seat <= self.n:
            raise UserError("Pick a seat.")
        return team, seat

    # -- tossups --
    def start_tossup(self):
        global current_question
        self.stscr(["SET_HIGHLIGHT", []])
        self.seats = {"a": self.board_seats("a"), "b": self.board_seats("b")}
        self.stscr(["NEW_PLAYERS", self.seats])
        self.tossup += 1
        current_question = self.tossup
        t = self.tossup
        if t not in self.snap_messages:
            self.snap_messages[t] = {"a": [entry[:] for entry in self.messages["a"]], "b": [entry[:] for entry in self.messages["b"]]}
        if t not in self.snap_seats:
            self.snap_seats[t] = {"a": self.seats["a"][:], "b": self.seats["b"][:]}
        if t not in self.snap_scores:
            self.snap_scores[t] = {**self.score, "points": self.score["points"].copy()}
        if t not in self.snap_rosters:
            self.snap_rosters[t] = {"a": self.teamA[:], "b": self.teamB[:]}
        self.stscr(["QUESTION", t, "tossup"])
        self.phase = "tossup"
        self.tu = {"category": "", "locked": {"a": False, "b": False}, "answered": None, "ended": False,
                   "dead": False, "bonus": [False, False, False], "committed": False, "subs": False, "log": []}
        self.sel = None

    def can_correct_prev(self):
        tu = self.tu
        if self.phase == "review":
            return self.do_revert and self.tossup > 0
        return (self.phase == "tossup" and self.tossup > 1 and self.do_revert and tu is not None
                and not tu["committed"] and not tu["ended"] and not tu["subs"])

    def restore(self, previous_tossup):
        self.stscr(["QUESTION", previous_tossup, "tossup"])
        self.seats = {"a": self.snap_seats[previous_tossup]["a"][:], "b": self.snap_seats[previous_tossup]["b"][:]}
        undone = self.teamA != self.snap_rosters[previous_tossup]["a"] or self.teamB != self.snap_rosters[previous_tossup]["b"]
        self.teamA[:] = self.snap_rosters[previous_tossup]["a"]
        self.teamB[:] = self.snap_rosters[previous_tossup]["b"]
        self.stscr(["NEW_PLAYERS", self.seats])
        self.score = {**self.snap_scores[previous_tossup], "points": self.snap_scores[previous_tossup]["points"].copy()}
        self.send_score()
        self.messages = {"a": [entry[:] for entry in self.snap_messages[previous_tossup]["a"]], "b": [entry[:] for entry in self.snap_messages[previous_tossup]["b"]]}
        self.send_messages("a")
        self.send_messages("b")
        self.stscr(["SET_HIGHLIGHT", []])
        for stale in [key for key in self.snap_messages if key > previous_tossup]:
            self.snap_messages.pop(stale, None)
            self.snap_seats.pop(stale, None)
            self.snap_scores.pop(stale, None)
            self.snap_rosters.pop(stale, None)
        with changes_lock:
            tentative_changes[:] = [i for i in tentative_changes if i[4] < previous_tossup]
        self.log = [c for c in self.log if c[4] < previous_tossup]
        self.log_ver += 1
        self.do_revert = False
        self.warning = ("Substitutions made at or after Tossup %d were undone. Make them again if needed." % previous_tossup) if undone else ""
        if undone:
            notify(self.warning, "warn")

    def correct_prev(self):
        if not self.can_correct_prev():
            raise UserError("Tossup %d can't be corrected right now." % (self.tossup - 1))
        previous_tossup = self.tossup - 1
        self.restore(previous_tossup)
        self.tossup = previous_tossup - 1
        self.start_tossup()

    def correct_last(self):
        if self.phase != "review" or not self.can_correct_prev():
            raise UserError("There is no finished tossup to correct.")
        previous_tossup = self.tossup
        self.restore(previous_tossup)
        self.tossup = previous_tossup - 1
        self.start_tossup()

    def select(self, team, seat):
        if self.phase == "tossup":
            tu = self.tu
            if tu["ended"] or tu["subs"]:
                raise UserError("This tossup is over.")
            if team is not None and tu["locked"].get(team):
                raise UserError("A player on team " + team.upper() + " has already answered.")
        elif self.phase == "lightning":
            if self.lq["done"]:
                raise UserError("This lightning question is over.")
        else:
            raise UserError("Nothing to select right now.")
        if team is None:
            if self.sel is not None:
                self.sel = None
                self.stscr(["SET_HIGHLIGHT", []])
            return
        team, seat = self.seat_arg(team, seat)
        if self.sel == {"team": team, "seat": seat}:
            return
        self.sel = {"team": team, "seat": seat}
        self.stscr(["SET_HIGHLIGHT", []])
        self.stscr(["HIGHLIGHT", team, [seat, 10**8]])

    def commit(self, category, team, seat, value):
        tu = self.tu
        if self.phase != "tossup" or tu["ended"] or tu["subs"]:
            raise UserError("This tossup is over.")
        team, seat = self.seat_arg(team, seat)
        if tu["locked"][team]:
            raise UserError("A player on team " + team.upper() + " has already answered.")
        if value not in (1, 2, 3, 4):
            raise UserError("Pick a point value.")
        if not tu["committed"]:
            if category not in CATEGORIES:
                raise UserError("Pick a category first.")
            tu["category"] = category
            self.heard_markers(category, [0, 0, 0, 1], self.tossup)
        category = tu["category"]
        playerId = self.team_list(team)[seat - 1]
        name_list = self.names(True)
        on = "a" if playerId in self.teamA else "b"
        if value == 1:
            self.queue([playerId, category, [1, 0, 0, 0], self.date, self.tossup, on])
            self.score[team] += 15
            self.score["points"][playerId] = self.score["points"].get(playerId, 0) + 15
            self.send_score()
            self.add_message(team, name_list[playerId] + ": 15")
            self.stscr(["HIGHLIGHT", team, [seat, 10**8]])
        elif value == 2:
            self.queue([playerId, category, [0, 1, 0, 0], self.date, self.tossup, on])
            self.score[team] += 10
            self.score["points"][playerId] = self.score["points"].get(playerId, 0) + 10
            self.send_score()
            self.add_message(team, name_list[playerId] + ": 10")
            self.stscr(["HIGHLIGHT", team, [seat, 10**8]])
        elif value == 3:
            self.queue([playerId, category, [0, 0, 1, 0], self.date, self.tossup, on])
            self.score[team] -= 5
            self.score["points"][playerId] = self.score["points"].get(playerId, 0) - 5
            self.send_score()
            self.add_message(team, name_list[playerId] + ": -5")
            self.stscr(["SET_HIGHLIGHT", []])
            self.stscr(["HIGHLIGHT", team, [seat, 200]])
            tu["locked"][team] = True
        else:
            tu["locked"][team] = True
            self.add_message(team, name_list[playerId] + ": 0")
            self.stscr(["SET_HIGHLIGHT", []])
            self.stscr(["HIGHLIGHT", team, [seat, 200]])
        tu["committed"] = True
        tu["log"].append({"team": team, "seat": seat, "value": value, "name": name_list[playerId]})
        self.sel = None
        if value in (1, 2):
            tu["answered"] = team
            tu["ended"] = True
        elif tu["locked"]["a"] and tu["locked"]["b"]:
            tu["ended"] = True

    def no_answer(self, category):
        tu = self.tu
        if self.phase != "tossup" or tu["ended"] or tu["subs"]:
            raise UserError("This tossup is over.")
        if not tu["committed"]:
            if category not in CATEGORIES:
                raise UserError("Pick a category first; the tossup is still recorded as heard.")
            tu["category"] = category
            self.heard_markers(category, [0, 0, 0, 1], self.tossup)
        tu["ended"] = True
        tu["dead"] = True
        if self.sel is not None:
            self.sel = None
            self.stscr(["SET_HIGHLIGHT", []])

    def toggle_bonus(self, part):
        tu = self.tu
        if self.phase != "tossup" or not tu["answered"]:
            raise UserError("The bonus unlocks after a power or a ten.")
        if part not in (0, 1, 2):
            raise UserError("Pick a bonus part.")
        tu["bonus"][part] = not tu["bonus"][part]
        self.score[tu["answered"]] += 10 if tu["bonus"][part] else -10
        self.send_score()

    def next_tossup(self, end=False):
        global current_question
        tu = self.tu
        if self.phase != "tossup" or tu["subs"] or not (tu["ended"] or (end and not tu["committed"])):
            raise UserError("Finish the tossup first.")
        tossup = self.tossup
        if not tu["ended"]:
            self.stscr(["SET_HIGHLIGHT", []])
            self.stscr(["QUESTION", tossup - 1, "tossup"])
            for snapshots in (self.snap_messages, self.snap_seats, self.snap_scores, self.snap_rosters):
                snapshots.pop(tossup, None)
            self.tossup -= 1
            current_question = 0
            self.phase = "review"
            self.tu = None
            self.sel = None
            return
        team = tu["answered"]
        if team:
            if tu["bonus"].count(True):
                self.queue([self.team_list(team) * tu["bonus"].count(True), "bonus_ans", 1, self.date, tossup, team])
            self.queue([self.team_list(team) * 3, "bonus_heard", 1, self.date, tossup, team])
        promote(lambda change: change[4] <= tossup - 1)
        write_database_in_background()
        self.stscr(["SET_HIGHLIGHT", []])
        current_question = 0
        self.do_revert = True
        self.warning = ""
        self.sel = None
        if not end:
            self.start_tossup()
        else:
            self.phase = "review"
            self.tu = None

    def end_tossups(self):
        promote()
        write_database_in_background()
        if self.lightnings > 0 and self.tossups > 0:
            self.phase = "lsubs"
            self.tu = None
            self.warning = ""
        elif self.lightnings > 0:
            self.start_lightning(1)
        else:
            self.to_final()

    # -- substitutions --
    def open_subs(self):
        tu = self.tu
        if self.phase != "tossup" or tu["committed"] or tu["ended"]:
            raise UserError("Substitutions are made before the first buzz of a tossup.")
        tu["subs"] = True
        if self.sel is not None:
            self.sel = None
            self.stscr(["SET_HIGHLIGHT", []])

    def close_subs(self):
        if self.phase != "tossup" or not self.tu["subs"]:
            return
        self.tu["subs"] = False
        self.stscr(["SET_HIGHLIGHT", []])
        self.seats = {"a": self.board_seats("a"), "b": self.board_seats("b")}
        self.stscr(["NEW_PLAYERS", self.seats])
        self.stscr(["QUESTION", self.tossup, "tossup"])

    def substitute(self, team, seat, username):
        if not ((self.phase == "tossup" and self.tu["subs"]) or self.phase == "lsubs"):
            raise UserError("Open substitutions first.")
        team, seat = self.seat_arg(team, seat)
        lst = self.team_list(team)
        out = lst[seat - 1]
        if not out.isalpha():
            raise UserError("Combined-score seats can't be substituted.")
        new = str(username or "").lower().strip()
        if not new.isalpha():
            raise UserError("Usernames can only contain letters.")
        if new in self.teamA or new in self.teamB:
            raise UserError("That player is already in play.")
        if new not in [row["username"] for row in self.rows]:
            if new == "pass":
                raise UserError("That username is reserved. Enter a different username.")
            if len(new) >= 3:
                raise UserError("That player isn't in the list yet. Add them first.")
            raise UserError("Usernames must be 3 characters or longer.")
        lst[seat - 1] = new
        name_list = self.names()
        self.seats[team] = ["" if i.startswith("!") else name_list[i] for i in lst]
        self.stscr(["NEW_PLAYERS", {team: self.seats[team]}])
        self.add_message(team, name_list[out] + " -> " + name_list[new])
        self.send_score()
        self.stscr(["HIGHLIGHT", team, [seat, 400]])
        return name_list[out] + " has been replaced by " + name_list[new]

    # -- lightning --
    def start_lightning(self, i):
        global current_question
        current_question = i
        self.stscr(["SET_HIGHLIGHT", []])
        self.seats = {"a": self.board_seats("a"), "b": self.board_seats("b")}
        self.stscr(["NEW_PLAYERS", self.seats])
        self.stscr(["QUESTION", i, "lightning"])
        self.phase = "lightning"
        self.tu = None
        self.warning = ""
        self.lq = {"i": i, "done": False, "result": None}
        self.sel = None

    def lightning_answer(self, team, seat, value):
        if self.phase != "lightning" or self.lq["done"]:
            raise UserError("This lightning question is over.")
        i = self.lq["i"]
        if value is not None:
            team, seat = self.seat_arg(team, seat)
            if value not in (1, 2):
                raise UserError("Pick correct or incorrect.")
            playerId = self.team_list(team)[seat - 1]
        self.heard_markers("lightning", [0, 0, 1], i)
        if value is None:
            self.lq["result"] = {"text": "No answer"}
        else:
            name_list = self.names(True)
            delta = 10 if value == 1 else -10
            self.score[team] += delta
            self.score["points"][playerId] = self.score["points"].get(playerId, 0) + delta
            self.send_score()
            self.add_message(team, name_list[playerId] + (": +10" if value == 1 else ": -10"))
            self.stscr(["HIGHLIGHT", team, [seat, 400]])
            self.queue([playerId, "lightning", [1, 0, 0] if value == 1 else [0, 1, 0], self.date, i, "a" if playerId in self.teamA else "b"])
            self.lq["result"] = {"text": name_list[playerId] + (" +10" if value == 1 else " −10"), "team": team, "seat": seat, "value": value}
        self.lq["done"] = True
        self.sel = None
        promote()
        write_database_in_background()

    def next_lightning(self, end=False):
        if self.phase != "lightning" or not (self.lq["done"] or end):
            raise UserError("Answer the question first.")
        self.stscr(["SET_HIGHLIGHT", []])
        self.sel = None
        if not self.lq["done"]:
            self.lq["i"] -= 1
            self.stscr(["QUESTION", self.lq["i"], "lightning"])
        if not end:
            self.start_lightning(self.lq["i"] + 1)
        else:
            self.to_final()

    # -- end of game --
    def to_final(self):
        promote()
        self.phase = "final"
        self.tu = None
        self.final = {"flushing": True, "ok": None, "left": 0}
        threading.Thread(target=self.final_flush, daemon=True).start()

    def final_flush(self):
        ok = flush_changes()
        with state_lock:
            with changes_lock:
                left = len(changes_to_send)
            self.final = {"flushing": False, "ok": ok, "left": left}
            touch()

    # -- view --
    def held_tossup(self):
        if self.phase not in ("tossup", "review"):
            return None
        with changes_lock:
            held = [c[4] for c in tentative_changes if c[4] != current_question]
        return max(held) if held else None

    def report(self):
        if self.report_cache[0] != self.log_ver:
            self.report_cache = (self.log_ver, live_report(self.log, self.rows))
        return self.report_cache[1]

    def view(self):
        full = {}
        for row in self.rows:
            full[row["username"]] = row["first_name"] + " " + row["last_name"]
        short = self.names()

        def seat_list(team):
            return [{"u": u, "label": ("Seat %d" % (i + 1)) if u.startswith("!") else short.get(u, u),
                     "full": "" if u.startswith("!") else full.get(u, u)} for i, u in enumerate(self.team_list(team))]
        return {
            "phase": self.phase,
            "register": self.register,
            "tossups": self.tossups,
            "lightnings": self.lightnings,
            "n": self.n,
            "a_name": self.teamAName,
            "b_name": self.teamBName,
            "a_ind": self.a_ind,
            "b_ind": self.b_ind,
            "name": self.name,
            "packet": self.packet,
            "seats": {"a": seat_list("a"), "b": seat_list("b")},
            "score": {"a": self.score["a"], "b": self.score["b"]},
            "tossup": self.tossup,
            "tu": self.tu,
            "lq": self.lq,
            "sel": self.sel,
            "can_correct": self.can_correct_prev(),
            "messages": self.messages,
            "warning": self.warning,
            "final": self.final,
            "held": self.held_tossup(),
            "report": self.report(),
        }

# ---------------------------------------------------------------------------
# Game setup: every question client.py asks before Tossup 1, on one form.
# Validation lives here so Python's isalpha() decides what a username is.
# ---------------------------------------------------------------------------

def default_setup():
    return {"tossups": True, "lightnings": False, "players": "4", "a_ind": True, "b_ind": True,
            "use_names": False, "a_name": "", "b_name": "", "seats_a": [""] * 4, "seats_b": [""] * 4,
            "packet_none": False, "packet": "", "packet_confirm": False, "packet_name": "",
            "name_override": False, "game_name": ""}


def check_setup(f):
    """Returns (check, cfg). cfg is None unless the form is ready to start."""
    errors = {}

    def as_int(key):
        try:
            return int(str(f.get(key, "")).strip())
        except ValueError:
            return None
    tossups = bool(f.get("tossups"))
    lightnings = bool(f.get("lightnings"))
    if not tossups and not lightnings:
        errors["lightnings"] = "A game needs tossups, a lightning round, or both."
    players = as_int("players")
    if players is None:
        errors["players"] = "That is not a valid input."
    elif players <= 0:
        errors["players"] = "That is not a valid number of players."
    elif players > 9:
        errors["players"] = "A maximum of 9 players may be selected."
    n = players if "players" not in errors else 0
    a_ind = bool(f.get("a_ind"))
    b_ind = bool(f.get("b_ind"))
    names_needed = not (a_ind and b_ind) or bool(f.get("use_names"))
    a_name = b_name = None
    if names_needed:
        a_name, e = clean_label(f.get("a_name"), "Team A's name")
        if e:
            errors["a_name"] = e
        b_name, e = clean_label(f.get("b_name"), "Team B's name")
        if e:
            errors["b_name"] = e
    users = {}
    for row in name_rows:
        users[row["username"]] = row
    with changes_lock:
        pending = {p[0] for p in pending_players}
    seats = {"a": [], "b": []}
    taken = set()
    for team, ind in (("a", a_ind), ("b", b_ind)):
        raw = f.get("seats_" + team) or []
        for i in range(n):
            if not ind:
                seats[team].append({"status": "combined"})
                continue
            value = str(raw[i] if i < len(raw) else "").lower().strip()
            s = {"status": "error", "msg": "", "value": value}
            if not value:
                s["status"] = "empty"
            elif len(value) > MAX_USERNAME:
                s["msg"] = "Usernames must be %d letters or fewer." % MAX_USERNAME
            elif not value.isalpha():
                s["msg"] = "That is not a valid username."
            elif value in taken:
                s["msg"] = "That player is already in the game."
            elif value in users:
                s.update(status="ok", label=short_name(users[value]), full=users[value]["first_name"] + " " + users[value]["last_name"], pending=value in pending)
            elif value == "pass":
                s["msg"] = "That username is reserved. Enter a different username."
            elif len(value) >= 3:
                s.update(status="new", msg="Not in the player list yet.")
            else:
                s["msg"] = "Usernames must be 3 characters or longer."
            if s["status"] in ("ok", "new"):
                taken.add(value)
            seats[team].append(s)
    if any(s["status"] not in ("ok", "combined") for team in ("a", "b") for s in seats[team]):
        errors["seats"] = ""
    packet = "pass"
    packet_known = False
    packet_name = ""
    pk = {"status": "none"}
    if tossups:
        if f.get("packet_none"):
            pk = {"status": "skip"}
        else:
            pid = str(f.get("packet", "")).lower().strip()
            if not pid:
                errors["packet"] = "Enter the packet id, or choose No packet."
            elif len(pid) > MAX_NAME:
                errors["packet"] = "Packet ids must be %d characters or fewer." % MAX_NAME
            elif pid == "pass":
                pk = {"status": "skip"}
            else:
                lookup = app["lookup"]
                if not lookup or lookup["id"] != pid:
                    pk = {"status": "looking"}
                    errors["packet"] = ""
                elif lookup["status"] == "error":
                    pk = lookup
                    errors["packet"] = lookup["msg"]
                elif lookup["status"] == "found":
                    pk = lookup
                    packet = pid
                    packet_known = True
                    if not f.get("packet_confirm"):
                        errors["packet"] = "Confirm that this is the packet."
                else:
                    pk = lookup
                    packet = pid
                    packet_name = str(f.get("packet_name", "")).strip()
                    if not packet_name or packet_name.lower() == "pass":
                        errors["packet_name"] = "Name the new packet."
                    elif len(packet_name) > 100:
                        errors["packet_name"] = "Packet names must be 100 characters or fewer."
    default_name = a_name + " vs. " + b_name if names_needed and a_name and b_name else ""
    if names_needed and not f.get("name_override"):
        name = default_name
    else:
        name, e = clean_label(f.get("game_name"), "The game name")
        if e:
            errors["game_name"] = e
    check = {"ok": not errors, "errors": errors, "seats": seats, "packet": pk, "names_needed": names_needed,
             "default_name": default_name, "n": n, "tossups": tossups}
    if errors:
        return check, None
    cfg = {"tossups": tossups, "lightnings": lightnings, "players": n, "a_ind": a_ind, "b_ind": b_ind,
           "teamA": [s["value"] for s in seats["a"]] if a_ind else ["!playerA"] * n,
           "teamB": [s["value"] for s in seats["b"]] if b_ind else ["!playerB"] * n,
           "a_name": a_name or "Team A", "b_name": b_name or "Team B", "name": name,
           "packet": packet, "packet_known": packet_known, "packet_name": packet_name}
    return check, cfg


def recheck_setup():
    if app["setup"] is not None:
        app["setup_check"] = check_setup(app["setup"])[0]


SETUP_KEYS = {"tossups": bool, "lightnings": bool, "players": str, "a_ind": bool, "b_ind": bool, "use_names": bool,
              "a_name": str, "b_name": str, "packet_none": bool, "packet": str, "packet_confirm": bool,
              "packet_name": str, "name_override": bool, "game_name": str}


def clean_form(raw):
    form = default_setup()
    if not isinstance(raw, dict):
        return form
    for key, kind in SETUP_KEYS.items():
        if key in raw:
            form[key] = bool(raw[key]) if kind is bool else str(raw[key])[:200]
    for key in ("seats_a", "seats_b"):
        if isinstance(raw.get(key), list):
            form[key] = [str(v)[:200] for v in raw[key][:9]]
    return form


def register_game(game):
    global G
    try:
        run_registration(game)
    except Exception as e:
        say("Error starting the game: %s: %s" % (type(e).__name__, e))
        with state_lock:
            if G is game:
                G = None
            app["screen"] = "setup"
            app["setup_error"] = "Something went wrong starting the game (%s). Try again." % type(e).__name__
            touch()


def run_registration(game):
    """Start sequence from client.py: save, seats, game key, packet, STGME."""
    global G

    def back_to_setup(message):
        global G
        with state_lock:
            if G is game:
                G = None
            app["screen"] = "setup"
            app["setup_error"] = message
            touch()
    writeToDatabase()
    with state_lock:
        if game.register["cancel"]:
            return back_to_setup("")
        game.stscr(["NEW_PLAYERS", {"a": game.board_seats("a"), "b": game.board_seats("b")}])
        game.register["status"] = "Getting the game key…"
        touch()
    game_date_time = sendMessage("PLTME")
    if not game_date_time.endswith(("AM", "PM")):
        game_date_time = datetime.datetime.now().strftime("%b %d, %Y, %I:%M:%S.%f %p")
    game.date = game_date_time
    if game.tossups > 0 and game.packet != "pass":
        with state_lock:
            game.register["status"] = "Saving the packet…"
            touch()
        if game.packet_known:
            reply = sendMessage("WRPAC" + json.dumps({"date": today_str(), "id": game.packet}))
        else:
            reply = sendMessage("ADPAC" + json.dumps([game.packet, game.packet_name, today_str()]))
        if reply != "pass":
            return back_to_setup("The server did not confirm the packet. Try again.")
    with state_lock:
        game.register["status"] = "Registering game…"
        touch()
    while True:
        if game.register["cancel"]:
            return back_to_setup("")
        if sendMessage("STGME" + json.dumps([game.date, {"packet": game.packet, "player_data": [], "name": game.name, "a_name": game.teamAName, "b_name": game.teamBName}, game_id_num]), repeat=3) == "pass":
            break
        with state_lock:
            game.register["status"] = "The server did not confirm that the game was registered. Retrying, check the connection."
            touch()
        for _ in range(10):
            if game.register["cancel"]:
                break
            time.sleep(0.1)
    with state_lock:
        if G is not game:
            return
        app["screen"] = "game"
        app["setup_error"] = ""
        if game.tossups > 0:
            game.start_tossup()
        else:
            game.end_tossups()
        touch()


# ---------------------------------------------------------------------------
# Rename, connection test, save button
# ---------------------------------------------------------------------------

def rename_player(p):
    target = str(p.get("target", "")).lower().strip()
    with state_lock:
        all_users = [row["username"] for row in name_rows if not row["username"].startswith("!")]
        if target not in all_users:
            raise UserError("That username is not in the database.")
        current = next(row for row in name_rows if row["username"] == target)
        new_username = str(p.get("new", "")).lower().strip() or target
        if new_username != target and new_username in all_users:
            raise UserError("That username already exists. Choose a different one.")
        if new_username == "pass":
            raise UserError("That username is reserved. Choose a different one.")
        if not new_username.isalpha():
            raise UserError("Usernames can only contain letters.")
        if len(new_username) < 3:
            raise UserError("Usernames must be 3 characters or longer.")
        if len(new_username) > MAX_USERNAME:
            raise UserError("Usernames must be %d letters or fewer." % MAX_USERNAME)
        first_name = str(p.get("first", "")).strip() or current["first_name"]
        last_name = str(p.get("last", "")).strip() or current["last_name"]
        if len(first_name) > MAX_NAME or len(last_name) > MAX_NAME:
            raise UserError("Names must be %d characters or fewer." % MAX_NAME)
    response = sendMessage("CHNME" + json.dumps({
        "old_username": target,
        "new_username": new_username,
        "first_name": first_name,
        "last_name": last_name,
    }))
    if response == "pass":
        with state_lock:
            current["username"] = new_username
            current["first_name"] = first_name
            current["last_name"] = last_name
            with changes_lock:
                for change in changes_to_send:
                    if change["data"][0] == target:
                        change["data"][0] = new_username
                    elif isinstance(change["data"][0], list):
                        change["data"][0] = [new_username if u == target else u for u in change["data"][0]]
            players_changed()
        return {"message": first_name + " " + last_name + " has been updated."}
    if response == "exists":
        raise UserError("That username already exists on the server. No changes were made.")
    if response == "notfound":
        raise UserError("That player no longer exists on the server. No changes were made.")
    raise UserError("Could not reach the server or an error occurred. Try again.")


def run_test():
    t = app["test"]

    def update(**kw):
        with state_lock:
            t.update(kw)
            touch()
    total_time = 0
    num_times = 0
    for i in range(5):
        time_start = datetime.datetime.now().timestamp()
        time_mid = sendMessage("PLTME", repeat=1, timeout=5)
        time_end = datetime.datetime.now().timestamp()
        update(pre=i + 1)
        if time_mid == "SVRCLS" or time_mid == "TIMEOUT":
            continue
        total_time += time_end - time_start
        num_times += 1
    if num_times == 0:
        return update(phase="failed", error="All five pretest packets failed, indicating a disconnection from the server.")
    total_time /= num_times
    times_round_trip = []
    dropped_packets = 0
    update(phase="running", started=time.time())
    current_time = datetime.datetime.now().timestamp()
    last_update = 0
    while datetime.datetime.now().timestamp() - current_time < 10:
        time_start = datetime.datetime.now().timestamp()
        time_mid = sendMessage("PLTME", repeat=1, timeout=total_time + 1)
        time_end = datetime.datetime.now().timestamp()
        if time_mid == "SVRCLS" or time_mid == "TIMEOUT":
            dropped_packets += 1
            time.sleep(0.1)
        else:
            times_round_trip.append((time_end - time_start) * 1000)
        if time_end - last_update > 0.2:
            last_update = time_end
            update(ok=len(times_round_trip), drops=dropped_packets, elapsed=min(10, time_end - current_time))
    if not times_round_trip:
        return update(phase="failed", error="Every packet in the test was lost, indicating a disconnection from the server.", drops=dropped_packets)
    percent_packets_dropped = dropped_packets / (len(times_round_trip) + dropped_packets) * 100
    median_latency = stats.median(times_round_trip)
    max_latency = max(times_round_trip)
    warnings = []
    if percent_packets_dropped > 1:
        warnings.append("Your average packet loss is high, which can indicate an unstable connection. The program may not work as intended with this connection.")
    if median_latency > 2000:
        warnings.append("Your median latency is high, which can cause delay during the game.")
    if max_latency > 5000:
        warnings.append("Your max latency is greater than 5 seconds, which exceeds the cap for the program.")
    step = max(1, len(times_round_trip) // 240)
    series = [max(times_round_trip[i:i + step]) for i in range(0, len(times_round_trip), step)]
    with state_lock:
        t["rtts"] = times_round_trip
        t.update(phase="done", ok=len(times_round_trip), drops=dropped_packets, elapsed=10,
                 loss="%.2f%%" % percent_packets_dropped, median="%.2f" % median_latency, max="%.2f" % max_latency,
                 warnings=warnings, series=series)
        touch()


def test_view():
    t = app["test"]
    if t is None:
        return None
    return {k: v for k, v in t.items() if k != "rtts"}


def run_flush():
    ok = flush_changes()
    with changes_lock:
        left = len(changes_to_send)
    with state_lock:
        if ok:
            result = "Every stat has been acknowledged."
        else:
            result = "%d stat%s not acknowledged yet. Saved to changes.json and still retrying." % (left, "" if left == 1 else "s")
        app["save"] = {"running": False, "result": result, "ok": ok}
        touch()


def do_quit():
    with state_lock:
        app["screen"] = "closing"
        touch()
    close()
    with state_lock:
        app["screen"] = "closed"
        touch()
    time.sleep(1.5)
    if httpd is not None:
        httpd.shutdown()


# ---------------------------------------------------------------------------
# Actions posted by the page
# ---------------------------------------------------------------------------

def spawn(target, *args):
    threading.Thread(target=target, args=args, daemon=True).start()


def need_game(*phases):
    if G is None or (phases and G.phase not in phases):
        raise UserError("That isn't available right now.")
    return G


def handle_action(p):
    global G
    kind = p.get("type")
    if kind == "add_player":
        username = str(p.get("username", "")).lower().strip()
        if not username.isalpha():
            raise UserError("Usernames can only contain letters.")
        if len(username) < 3:
            raise UserError("Usernames must be 3 characters or longer.")
        if len(username) > MAX_USERNAME:
            raise UserError("Usernames must be %d letters or fewer." % MAX_USERNAME)
        first, e = clean_label(p.get("first"), "The first name")
        if e:
            raise UserError(e)
        last, e = clean_label(p.get("last"), "The last name")
        if e:
            raise UserError(e)
        with state_lock:
            if username in [row["username"] for row in name_rows]:
                recheck_setup()
                return {"message": "That player is already in the list."}
        result, message = ensure_player(username, first, last)
        if result == "exists":
            raise UserError(message)
        with state_lock:
            name_rows.append({"username": username, "first_name": first, "last_name": last})
            recheck_setup()
            players_changed()
        return {"message": message or (first + " " + last + " was added."), "pending": result is False}
    if kind == "packet_lookup":
        pid = str(p.get("id", "")).lower().strip()
        if not pid or pid == "pass" or len(pid) > MAX_NAME:
            return {}
        response = sendMessage("PACKS" + pid)
        lookup = {"id": pid, "status": "error", "msg": ""}
        if response in ("TIMEOUT", "SVRCLS", "error"):
            lookup["msg"] = "Could not reach the server to look up packets. Try again."
        else:
            try:
                previous_packets = json.loads(response)
                match = next((row for row in previous_packets if row["id"] == pid), None)
                if match is None:
                    lookup = {"id": pid, "status": "notfound"}
                else:
                    try:
                        last_played = str(abs((datetime.datetime.now().date() - datetime.datetime.strptime(match["date"], "%m/%d/%Y").date()).days)) + " days ago"
                    except (ValueError, TypeError):
                        last_played = "on an unknown date"
                    lookup = {"id": pid, "status": "found", "name": str(match["name"]), "last_played": last_played}
            except (json.JSONDecodeError, TypeError, KeyError):
                lookup["msg"] = "Received an unexpected response from the server. Try again."
        with state_lock:
            if app["setup"] is not None and str(app["setup"].get("packet", "")).lower().strip() == pid:
                app["lookup"] = lookup
                recheck_setup()
                touch()
        return {}
    if kind == "rename":
        with state_lock:
            if app["screen"] != "rename":
                raise UserError("Open Rename player from Home first.")
        return rename_player(p)

    with state_lock:
        screen = app["screen"]
        if kind == "session":
            if app["connect"]["phase"] != "session":
                raise UserError("Not ready for a session name.")
            app["connect"]["phase"] = "requesting"
            spawn(request_game_id, p.get("name", ""))
        elif kind == "retry":
            if screen != "connect" or app["connect"]["phase"] not in ("failed",):
                raise UserError("Already connecting.")
            app["connect"]["phase"] = "connecting"
            spawn(connect_flow)
        elif kind == "goto":
            target = p.get("screen")
            if target not in ("home", "rename", "test", "settings", "setup"):
                raise UserError("Unknown screen.")
            if G is not None and G.phase != "final":
                raise UserError("Finish the game first.")
            if screen == "connect":
                if target != "settings":
                    raise UserError("Connect to the server first.")
            if target == "home" and game_id_num is None:
                target = "connect"
            if target == "setup":
                if game_id_num is None:
                    raise UserError("Connect to the server first.")
                if app["reconnecting"]:
                    raise UserError("Wait for the server settings to finish.")
                post("RESCR" + str(game_id_num))
                if app["setup"] is None:
                    app["setup"] = default_setup()
                else:
                    app["setup"].update(packet="", packet_confirm=False, packet_name="", packet_none=False, name_override=False, game_name="")
                app["lookup"] = None
                app["setup_error"] = ""
                app["setup_seq"] += 1
                recheck_setup()
            if target == "settings" and not app["settings"]["busy"]:
                app["settings"] = {"busy": False, "error": "", "ok": ""}
            if target == "test" and (app["test"] is None or app["test"].get("phase") in ("done", "failed")):
                app["test"] = None
            G = None
            app["screen"] = target
        elif kind == "setup_form":
            if screen != "setup":
                raise UserError("Setup isn't open.")
            app["setup"] = clean_form(p.get("form"))
            app["setup_seq"] = int(p.get("seq") or 0)
            recheck_setup()
        elif kind == "start":
            if screen != "setup" or G is not None:
                raise UserError("A game is already starting.")
            check, cfg = check_setup(app["setup"] or {})
            app["setup_check"] = check
            if cfg is None:
                raise UserError("Some details still need attention.")
            for team, tag, letter in (("a", "!playerA", "A"), ("b", "!playerB", "B")):
                if not cfg[team + "_ind"]:
                    name_rows[:] = [row for row in name_rows if row["username"] != tag]
                    name_rows.extend({"username": i, "first_name": "Team", "last_name": letter} for i in cfg["team" + letter])
            G = Game(cfg)
            app["setup_error"] = ""
            spawn(register_game, G)
        elif kind == "cancel_register":
            game = need_game("registering")
            game.register["cancel"] = True
            game.register["status"] = "Cancelling…"
        elif kind == "select":
            game = need_game("tossup", "lightning")
            if p.get("team") is None:
                game.select(None, None)
            else:
                game.select(p.get("team"), p.get("seat"))
        elif kind == "commit":
            need_game("tossup").commit(p.get("category"), p.get("team"), p.get("seat"), p.get("value"))
        elif kind == "no_answer":
            need_game("tossup").no_answer(p.get("category"))
        elif kind == "bonus":
            need_game("tossup").toggle_bonus(p.get("part"))
        elif kind == "next":
            need_game("tossup").next_tossup(bool(p.get("end")))
        elif kind == "resume":
            need_game("review").start_tossup()
        elif kind == "subs_open":
            need_game("tossup").open_subs()
        elif kind == "subs_close":
            need_game("tossup").close_subs()
        elif kind == "sub":
            message = need_game("tossup", "lsubs").substitute(p.get("team"), p.get("seat"), p.get("username"))
            touch()
            return {"message": message}
        elif kind == "correct_prev":
            need_game("tossup").correct_prev()
        elif kind == "correct_last":
            need_game("review").correct_last()
        elif kind == "continue":
            need_game("review").end_tossups()
        elif kind == "start_lightning":
            need_game("lsubs").start_lightning(1)
        elif kind == "lcommit":
            need_game("lightning").lightning_answer(p.get("team"), p.get("seat"), p.get("value"))
        elif kind == "lno_answer":
            need_game("lightning").lightning_answer(None, None, None)
        elif kind == "lnext":
            need_game("lightning").next_lightning(bool(p.get("end")))
        elif kind == "flush":
            if app["save"]["running"]:
                raise UserError("Already saving.")
            app["save"] = {"running": True, "result": "", "ok": None}
            spawn(run_flush)
        elif kind == "test_start":
            if screen != "test" or (app["test"] and app["test"].get("phase") in ("pretest", "running")):
                raise UserError("A test is already running.")
            app["test"] = {"phase": "pretest", "pre": 0, "ok": 0, "drops": 0, "elapsed": 0}
            spawn(run_test)
        elif kind == "test_export":
            t = app["test"]
            if not t or t.get("phase") != "done":
                raise UserError("Run the test first.")
            try:
                with open("latency.csv", "w", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(t["rtts"])
            except OSError as e:
                raise UserError("Could not write latency.csv: " + str(e))
            touch()
            return {"message": "Saved latency.csv next to client_web.py."}
        elif kind == "settings_save":
            if G is not None and G.phase != "final":
                raise UserError("Server settings can't be changed during a game.")
            if app["reconnecting"] or app["settings"]["busy"]:
                raise UserError("Still checking the last address.")
            host, port = validate_address(p.get("host"), p.get("port"))
            try:
                write_config(host, port)
            except OSError as e:
                raise UserError("Could not write config.ini: " + str(e))
            app["host"], app["port"] = host, port
            if game_id_num is None:
                app["settings"] = {"busy": False, "error": "", "ok": "Saved to config.ini."}
                app["screen"] = "connect"
                app["connect"] = {"phase": "connecting", "error": ""}
                spawn(connect_flow)
            else:
                app["reconnecting"] = True
                app["settings"] = {"busy": True, "error": "", "ok": "Saved to config.ini. Checking %s:%d…" % (host, port)}
                spawn(reconnect, host, port)
        elif kind == "quit":
            if screen in ("closing", "closed"):
                return {}
            spawn(do_quit)
        else:
            raise UserError("Unknown action.")
        touch()
    return {}


# ---------------------------------------------------------------------------
# Page server: loopback only, every API call carries the launch token.
# ---------------------------------------------------------------------------

def build_view():
    view = {
        "screen": app["screen"],
        "gid": game_id_num,
        "host": app["host"],
        "port": app["port"],
        "session": app["session_name"],
        "connect": app["connect"],
        "recovery": app["recovery"],
        "settings": app["settings"],
        "reconnecting": app["reconnecting"],
        "today": datetime.date.today().strftime("%B %d, %Y"),
        "test": test_view(),
        "game": G.view() if G is not None else None,
    }
    if app["screen"] == "setup":
        view["setup"] = {"form": app["setup"], "seq": app["setup_seq"], "check": app["setup_check"], "error": app["setup_error"]}
    return view


def state_payload(known_rev=-1, known_players=-1):
    with state_lock:
        with changes_lock:
            unsent = len(changes_to_send)
            tentative = len(tentative_changes)
            waiting_players = len(pending_players)
        out = {"status": {
            "rev": rev,
            "unsent": unsent,
            "tentative": tentative,
            "board": board_queue.unfinished_tasks,
            "pending_players": waiting_players,
            "conn": "none" if game_id_num is None else ("ok" if time.time() - last_reply < 10 else "lost"),
            "save": app["save"],
            "toasts": toasts[-12:],
        }}
        if known_rev != rev:
            out["view"] = build_view()
        if known_players != players_rev:
            out["players_rev"] = players_rev
            out["players"] = [[row["username"], row["first_name"], row["last_name"]] for row in name_rows if not row["username"].startswith("!")]
    return out


class Handler(BaseHTTPRequestHandler):
    server_version = "MatchConsole"
    sys_version = ""

    def log_message(self, format, *args):
        pass

    def reply(self, code, body, ctype="application/json"):
        data = body.encode("utf-8") if isinstance(body, str) else body
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src data:; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def allowed(self, token):
        port = self.server.server_address[1]
        if self.headers.get("Host", "") not in ("127.0.0.1:%d" % port, "localhost:%d" % port):
            return False
        return secrets.compare_digest(str(token or ""), PAGE_TOKEN)

    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        if url.path == "/":
            if not self.allowed(query.get("t", [""])[0]):
                return self.reply(403, LOCKED_PAGE, "text/html; charset=utf-8")
            return self.reply(200, PAGE, "text/html; charset=utf-8")
        if url.path == "/api/state":
            if not self.allowed(self.headers.get("X-Token")):
                return self.reply(403, '{"error": "forbidden"}')
            try:
                known_rev = int(query.get("rev", ["-1"])[0])
                known_players = int(query.get("p", ["-1"])[0])
            except ValueError:
                known_rev = known_players = -1
            return self.reply(200, json.dumps(state_payload(known_rev, known_players)))
        if url.path == "/favicon.ico":
            return self.reply(204, b"", "image/x-icon")
        return self.reply(404, '{"error": "not found"}')

    def do_POST(self):
        if urlparse(self.path).path != "/api/action" or not self.allowed(self.headers.get("X-Token")):
            return self.reply(403, '{"error": "forbidden"}')
        if not self.headers.get("Content-Type", "").startswith("application/json"):
            return self.reply(415, '{"error": "json only"}')
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            length = 0
        if not 0 < length <= 65536:
            return self.reply(413, '{"error": "too large"}')
        try:
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValueError
        except (ValueError, UnicodeDecodeError):
            return self.reply(400, '{"error": "bad json"}')
        try:
            result = {"ok": True, **handle_action(payload)}
        except UserError as e:
            result = {"ok": False, "error": str(e)}
        except Exception as e:
            say("Error handling %s: %s: %s" % (payload.get("type"), type(e).__name__, e))
            result = {"ok": False, "error": "Something went wrong (%s). The game state is unchanged; try again." % type(e).__name__}
        result.update(state_payload())
        return self.reply(200, json.dumps(result))


class PageServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = os.name != "nt"


def make_server():
    try:
        return PageServer(("127.0.0.1", 8765), Handler)
    except OSError:
        return PageServer(("127.0.0.1", 0), Handler)


def handle_exit_signals(signum, frame):
    for name in ("SIGHUP", "SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            try:
                signal.signal(getattr(signal, name), signal.SIG_IGN)
            except (OSError, ValueError):
                pass
    sys.exit(0)


def main():
    global httpd
    atexit.register(close)
    for name in ("SIGHUP", "SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), handle_exit_signals)
    httpd = make_server()
    url = "http://127.0.0.1:%d/?t=%s" % (httpd.server_address[1], PAGE_TOKEN)
    say("Match console: " + url)
    say("Keep this window open during the game. Quit from the page, or press Ctrl+C here.")
    threading.Thread(target=board_worker, daemon=True).start()
    threading.Thread(target=connect_flow, daemon=True).start()
    threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever(poll_interval=0.25)
    finally:
        with state_lock:
            if app["screen"] not in ("closing", "closed"):
                app["screen"] = "closing"
                touch()
        close()
        with state_lock:
            app["screen"] = "closed"
            touch()
        httpd.server_close()
        say("Client closed.")

# ---------------------------------------------------------------------------
# The page. Plain HTML, CSS and JavaScript; nothing is loaded from the network.
# ---------------------------------------------------------------------------

LOCKED_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Match Console</title>
<style>body{font-family:"DejaVu Sans","Helvetica Neue",Helvetica,Arial,sans-serif;color:#111;background:#fff;margin:48px}
p{color:#6B6B6B;max-width:36em;line-height:1.5}</style></head><body><h1>Match Console</h1>
<p>This page needs the link printed in the terminal window where client_web.py is running.
Open that link (it ends in <code>?t=…</code>) to use the console.</p></body></html>"""

PAGE_CSS = r"""
:root{
  --ink:#111111; --muted:#6B6B6B; --rule:#D9D9D9; --paper:#FAFAF7; --track:#EFEFEA; --white:#FFFFFF;
  --power:#257D2F; --ten:#23BE2B; --neg:#C62828; --none:#9E9E9E;
  --team-a:#1F6FEB; --team-b:#C62828; --hi:#2E7D32; --mid:#9E9E9E; --lo:#C62828; --lightning:#FFE020;
  --a-tint:#EEF4FE; --b-tint:#FCEEEE; --ok-tint:#EAF6EB; --warn-tint:#FFF6D6;
  --font:"DejaVu Sans","Helvetica Neue",Helvetica,Arial,sans-serif;
  --fast:160ms; --mid-t:260ms; --slow:380ms; --ease:cubic-bezier(.215,.61,.355,1);
}
*{box-sizing:border-box}
html,body{margin:0;background:var(--white);color:var(--ink)}
body{font-family:var(--font);font-size:14px;line-height:1.4;-webkit-font-smoothing:antialiased;min-width:1000px}
button,input,select{font:inherit;color:inherit}
.num,.tile .v,.score,.wheel,table td.n{font-variant-numeric:tabular-nums}
.wrap{max-width:1360px;margin:0 auto;padding:0 24px}
.eyebrow{font-size:10px;font-weight:700;letter-spacing:.24em;text-transform:uppercase;color:var(--muted)}
.muted{color:var(--muted)}
.small{font-size:12px}
[hidden]{display:none!important}

/* masthead */
header.mast{padding-top:18px}
.mast-row{display:flex;align-items:flex-end;justify-content:space-between;gap:24px}
.mast h1{font-size:29px;line-height:1.1;margin:4px 0 0;font-weight:700;letter-spacing:-.01em}
body.ingame .mast h1{font-size:20px}
body.ingame header.mast{padding-top:10px}
.rule{height:0;border-top:1.2px solid var(--ink);margin-top:10px}
.mast-tools{display:flex;align-items:center;gap:10px;flex-wrap:wrap;justify-content:flex-end}
.gid{display:flex;align-items:baseline;gap:8px;padding:6px 10px;border:1px solid var(--rule);background:var(--paper)}
.gid b{font-size:18px;letter-spacing:.06em;font-variant-numeric:tabular-nums}
.dot{width:8px;height:8px;border-radius:50%;background:var(--none);display:inline-block;transition:background var(--mid-t)}
.dot.ok{background:var(--ten)} .dot.lost{background:var(--neg)}

/* buttons */
.btn{appearance:none;border:1px solid var(--rule);background:var(--white);padding:8px 14px;cursor:pointer;
  transition:background var(--fast),border-color var(--fast),color var(--fast),opacity var(--fast);line-height:1.2;white-space:nowrap}
.btn:hover:not(:disabled){border-color:var(--ink)}
.btn:focus-visible,.seat:focus-visible,.opt:focus-visible,input:focus-visible,select:focus-visible{outline:2px solid var(--team-a);outline-offset:1px}
.btn.primary{background:var(--ink);border-color:var(--ink);color:var(--white)}
.btn.primary:hover:not(:disabled){background:#333}
.btn.quiet{border-color:transparent;background:transparent;color:var(--muted)}
.btn.quiet:hover:not(:disabled){color:var(--ink);border-color:var(--rule)}
.btn.small{padding:4px 9px;font-size:12px}
.btn.big{padding:12px 20px;font-size:15px}
.btn:disabled{opacity:.4;cursor:not-allowed}
.btn .k{font-size:10px;color:inherit;opacity:.6;margin-left:6px;letter-spacing:.08em}
.savebtn{display:flex;gap:8px;align-items:center}
.savebtn .count{font-weight:700;font-variant-numeric:tabular-nums}

/* banner + toasts */
.banner{background:var(--neg);color:var(--white);font-size:13px;padding:6px 24px;text-align:center;transform-origin:top;
  animation:drop var(--mid-t) var(--ease)}
@keyframes drop{from{transform:scaleY(0);opacity:0}to{transform:none;opacity:1}}
#toasts{position:fixed;right:18px;bottom:84px;display:flex;flex-direction:column;gap:8px;z-index:50;max-width:380px}
.toast{background:var(--white);border:1px solid var(--rule);border-left:4px solid var(--ink);padding:10px 14px;font-size:13px;
  box-shadow:0 2px 6px rgba(0,0,0,.06);transform:translateX(0);opacity:1;transition:transform var(--mid-t) var(--ease),opacity var(--mid-t)}
.toast.enter{transform:translateX(110%);opacity:0}
.toast.warn{border-left-color:var(--neg)} .toast.ok{border-left-color:var(--ten)}

/* screens */
main#app{padding-top:18px;padding-bottom:60px}
.screen{transition:opacity var(--mid-t) var(--ease)}
.screen.fade{opacity:0}
h2.sec{font-size:15px;font-weight:700;margin:26px 0 10px}
h2.sec .sn{color:var(--muted);margin-right:10px}
.lede{color:var(--muted);max-width:44em}
.panel{border-top:1px solid var(--rule);padding-top:14px;margin-top:14px}
.row{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.stack{display:flex;flex-direction:column;gap:10px}
.err{color:var(--neg);font-size:12px;min-height:0}
.ok-msg{color:var(--hi);font-size:13px}
.warn-msg{background:var(--warn-tint);border-left:3px solid #C9A400;padding:8px 12px;font-size:13px}
.status-line{color:var(--muted);font-size:13px;margin-top:16px}

/* forms */
label.f{display:flex;flex-direction:column;gap:4px;font-size:12px;color:var(--muted)}
label.f > span{font-weight:700;letter-spacing:.14em;text-transform:uppercase;font-size:10px}
input[type=text],input[type=number],select{border:1px solid var(--rule);background:var(--white);padding:8px 10px;min-width:0;
  transition:border-color var(--fast),background var(--fast);border-radius:0}
input[type=text]:focus,input[type=number]:focus,select:focus{border-color:var(--ink);outline:none}
input.bad{border-color:var(--neg);background:#FFF8F8}
input.good{border-color:var(--hi)}
.w-num{width:96px}.w-mid{width:220px}.w-wide{width:320px}
.toggle{display:inline-flex;align-items:center;gap:8px;cursor:pointer;user-select:none;font-size:13px}
.toggle input{position:absolute;opacity:0;width:1px;height:1px}
.toggle .sw{width:34px;height:20px;border-radius:10px;background:var(--track);border:1px solid var(--rule);position:relative;transition:background var(--fast)}
.toggle .sw::after{content:"";position:absolute;top:2px;left:2px;width:14px;height:14px;border-radius:50%;background:var(--white);
  border:1px solid var(--rule);transition:transform var(--fast) var(--ease)}
.toggle input:checked + .sw{background:var(--ink);border-color:var(--ink)}
.toggle input:checked + .sw::after{transform:translateX(14px)}
.toggle input:focus-visible + .sw{outline:2px solid var(--team-a);outline-offset:1px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.seatrow{display:grid;grid-template-columns:34px 1fr;gap:8px;align-items:start;margin-bottom:8px}
.seatno{width:34px;height:34px;display:flex;align-items:center;justify-content:center;background:var(--paper);border:1px solid var(--rule);font-weight:700;font-size:12px}
.seatinfo{font-size:12px;margin-top:3px;min-height:16px}
.addform{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px;padding:8px;background:var(--paper);border:1px solid var(--rule)}
.addform input{width:130px}
.lookup{margin-top:8px;padding:10px 12px;background:var(--paper);border:1px solid var(--rule);font-size:13px}
.startbar{position:sticky;bottom:0;background:var(--white);border-top:1.2px solid var(--ink);padding:12px 0;margin-top:28px;display:flex;align-items:center;gap:16px;justify-content:space-between}
.overlay{position:fixed;inset:0;background:rgba(255,255,255,.86);display:flex;align-items:center;justify-content:center;z-index:40;animation:fadein var(--mid-t) var(--ease)}
@keyframes fadein{from{opacity:0}to{opacity:1}}
.card{background:var(--white);border:1px solid var(--rule);border-top:1.2px solid var(--ink);padding:22px 26px;max-width:720px;width:calc(100% - 48px);max-height:calc(100vh - 60px);overflow:auto}
.spinner{width:14px;height:14px;border:2px solid var(--rule);border-top-color:var(--ink);border-radius:50%;display:inline-block;animation:spin .8s linear infinite;vertical-align:-2px}
@keyframes spin{to{transform:rotate(360deg)}}

/* home */
.home-grid{display:grid;grid-template-columns:minmax(280px,380px) 1fr;gap:40px;align-items:start}
.bigid{font-size:64px;font-weight:700;letter-spacing:.06em;line-height:1;font-variant-numeric:tabular-nums;margin:6px 0 12px}
.menu{display:flex;flex-direction:column;gap:10px;max-width:340px}
.menu .btn{text-align:left;padding:14px 16px;font-size:15px}

/* tiles */
.tile{background:var(--paper);border:1px solid var(--rule);padding:10px 14px}
.tile .v{font-size:24px;font-weight:700;line-height:1.15}
.tiles{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px}

/* score bar */
.scorebar{position:sticky;top:0;z-index:20;background:var(--white);border-bottom:1px solid var(--rule)}
.scorebar-in{display:grid;grid-template-columns:1fr auto 1fr;gap:16px;align-items:stretch;padding:8px 0}
.st{display:flex;align-items:center;gap:14px;padding:6px 14px;background:var(--paper);border:1px solid var(--rule)}
.st.b{justify-content:flex-end;text-align:right}
.st .tn{font-size:13px;font-weight:700;max-width:260px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.st.a .tn{color:var(--team-a)} .st.b .tn{color:var(--team-b)}
.score{font-size:40px;font-weight:700;line-height:1;display:inline-flex;min-width:1.2em}
.st.a{border-left:3px solid var(--team-a)} .st.b{border-right:3px solid var(--team-b)}
.qbox{display:flex;flex-direction:column;align-items:center;justify-content:center;padding:4px 18px;min-width:170px}
.qline{display:flex;align-items:baseline;gap:6px}
.wheel{font-size:30px;font-weight:700;line-height:1;display:inline-flex;padding:2px 8px;transition:background var(--mid-t)}
.wheel.lightning{background:var(--lightning)}

/* rolling digits */
.roll{display:inline-flex;overflow:hidden;height:1em;line-height:1}
.dg{display:inline-block;position:relative;height:1em;overflow:hidden;vertical-align:top}
.dg > span:not(.col),.dg .col > span{display:block;height:1em;line-height:1;flex:none}
.dg .col{display:flex;flex-direction:column;transition:transform var(--slow) var(--ease)}

/* game layout */
.game{display:grid;grid-template-columns:minmax(170px,230px) minmax(0,1fr) minmax(170px,230px);gap:22px;align-items:start}
.teamcol h3{margin:0 0 8px;font-size:10px;letter-spacing:.24em;text-transform:uppercase;padding-bottom:6px;border-bottom:1px solid var(--rule);
  white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.teamcol.a h3{color:var(--team-a)} .teamcol.b h3{color:var(--team-b);text-align:right}
.seat{display:flex;align-items:center;gap:10px;width:100%;padding:7px 8px;margin-bottom:6px;background:var(--white);border:1px solid var(--rule);
  cursor:pointer;text-align:left;transition:background var(--fast),border-color var(--fast),opacity var(--mid-t),box-shadow var(--fast)}
.teamcol.b .seat{flex-direction:row-reverse;text-align:right}
.seat .no{width:26px;height:26px;flex:none;display:flex;align-items:center;justify-content:center;background:var(--paper);border:1px solid var(--rule);
  font-size:11px;font-weight:700;transition:background var(--fast),color var(--fast)}
.seat .nm{flex:1;min-width:0;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;font-size:13px}
.seat .key{font-size:10px;color:var(--muted);letter-spacing:.08em}
.seat:hover:not(:disabled){border-color:var(--ink)}
.teamcol.a .seat.sel{border-color:var(--team-a);background:var(--a-tint);box-shadow:inset 3px 0 0 var(--team-a)}
.teamcol.b .seat.sel{border-color:var(--team-b);background:var(--b-tint);box-shadow:inset -3px 0 0 var(--team-b)}
.teamcol.a .seat.sel .no{background:var(--team-a);color:#fff} .teamcol.b .seat.sel .no{background:var(--team-b);color:#fff}
.seat.got{background:var(--ok-tint);border-color:var(--power)} .seat.got .no{background:var(--power);color:#fff}
.seat.negged{background:#FCEEEE;border-color:var(--neg)} .seat.negged .no{background:var(--neg);color:#fff}
.seat.zeroed .no{background:var(--none);color:#fff}
.seat:disabled{cursor:not-allowed;opacity:.42}
.seat.got:disabled,.seat.negged:disabled,.seat.zeroed:disabled{opacity:.8}
.game.idle .seat:disabled{opacity:1;cursor:default}
.center{min-width:0}
.qhead{display:flex;align-items:center;justify-content:space-between;gap:12px;margin-bottom:10px}
.qhead .title{font-size:18px;font-weight:700}
.chip-l{background:var(--lightning);padding:2px 8px;font-weight:700}
.ctl{display:grid;grid-template-columns:auto 1fr;gap:10px 14px;align-items:center}
.ctl > .lab{font-size:10px;font-weight:700;letter-spacing:.2em;text-transform:uppercase;color:var(--muted)}
.opts{display:flex;gap:6px;flex-wrap:wrap}
.opt{appearance:none;border:1px solid var(--rule);background:var(--white);padding:8px 12px;cursor:pointer;display:inline-flex;align-items:center;gap:8px;
  transition:background var(--fast),color var(--fast),border-color var(--fast)}
.opt .c{width:10px;height:10px;display:inline-block;background:var(--oc)}
.opt .k{font-size:10px;color:var(--muted)}
.opt:hover{border-color:var(--oc)}
.opt.on{background:var(--oc);border-color:var(--oc);color:#fff}
.opt.on .c{background:#fff}.opt.on .k{color:rgba(255,255,255,.8)}
.opt.power{--oc:var(--power)}.opt.ten{--oc:var(--ten)}.opt.neg{--oc:var(--neg)}.opt.zero{--oc:var(--none)}
.selline{font-size:13px;min-height:20px}
.actions{display:flex;gap:8px;flex-wrap:wrap;align-items:center;margin-top:12px}
.tools{display:flex;gap:8px;flex-wrap:wrap;margin-top:10px}
.legend{display:flex;gap:14px;flex-wrap:wrap;font-size:11px;color:var(--muted);margin-top:12px}
.legend i{display:inline-block;width:10px;height:10px;margin-right:5px;vertical-align:-1px}
.bonus{margin-top:16px;border:1px dashed var(--rule);padding:12px 14px;transition:border-color var(--mid-t),background var(--mid-t)}
.bonus.open{border-style:solid;border-color:var(--rule);background:var(--paper)}
.bonus .body{display:grid;grid-template-rows:0fr;transition:grid-template-rows var(--slow) var(--ease),opacity var(--slow);opacity:0}
.bonus.open .body{grid-template-rows:1fr;opacity:1}
.bonus .body > div{overflow:hidden}
.bparts{display:flex;gap:8px;margin-top:10px}
.bpart{flex:1;appearance:none;border:1px solid var(--rule);background:var(--white);padding:12px;cursor:pointer;font-weight:700;
  transition:background var(--fast),color var(--fast),border-color var(--fast)}
.bpart.on{background:var(--ten);border-color:var(--ten);color:#fff}
.bpart .k{font-size:10px;font-weight:400;opacity:.7;margin-left:6px}
.log{margin-top:14px;font-size:13px}
.log div{padding:4px 0;border-bottom:1px solid var(--rule);display:flex;justify-content:space-between;gap:8px}
.log .v1{color:var(--power);font-weight:700}.log .v2{color:var(--ten);font-weight:700}.log .v3{color:var(--neg);font-weight:700}.log .v4{color:var(--none);font-weight:700}
.nextbar{margin-top:16px;padding-top:14px;border-top:1.2px solid var(--ink);display:flex;justify-content:space-between;align-items:center;gap:12px}

/* report */
.report{margin-top:34px;border-top:1.2px solid var(--ink)}
.report h2.sec{margin-top:18px}
table.rt{width:100%;border-collapse:collapse;font-size:13px}
table.rt th{font-size:10px;font-weight:700;color:var(--muted);letter-spacing:.14em;text-transform:uppercase;text-align:left;padding:6px 8px;border-bottom:1px solid var(--ink)}
table.rt td{padding:7px 8px;border-bottom:1px solid var(--rule);vertical-align:middle}
table.rt tr:last-child td{border-bottom:none}
table.rt th.n,table.rt td.n{text-align:right}
table.rt td.n{font-weight:700;font-size:15px}
table.rt td.c{text-align:center;font-weight:700}
table.rt.alt tbody tr:nth-child(even) td{background:var(--paper)}
.two{display:grid;grid-template-columns:1fr 1fr;gap:28px}
.bar{position:relative;display:flex;height:10px;background:var(--white);min-width:120px}
.bar .s{height:100%;transition:flex-grow var(--slow) var(--ease)}
.bar .dv{position:absolute;top:0;bottom:0;width:0;border-left:0.8px solid var(--paper)}
.slider{height:10px;border-radius:5px;background:var(--track);border:0.5px solid var(--rule);position:relative;overflow:hidden;min-width:120px}
.slider .fill{position:absolute;left:0;top:0;bottom:0;border-radius:5px;transition:width var(--slow) var(--ease),background var(--slow)}
.chart{max-width:940px}
.chart svg{width:100%;height:auto;display:block}
.chart .ax{stroke:var(--rule);stroke-width:1}
.chart .grid{stroke:#E5E5E5;stroke-width:.6}
.chart text{font-size:10px;fill:var(--muted);font-family:var(--font)}
.chart .la{stroke:var(--team-a);stroke-width:2;fill:none}
.chart .lb{stroke:var(--team-b);stroke-width:2;fill:none}
.chart .split{stroke:var(--muted);stroke-width:.9;stroke-dasharray:4 3}
.empty{color:var(--muted);font-size:13px;padding:10px 0}

@media (max-width:1180px){
  .game{grid-template-columns:minmax(150px,190px) minmax(0,1fr) minmax(150px,190px);gap:14px}
  .score{font-size:34px}
  .st .tn{max-width:180px}
  .two{gap:18px}
}
@media (prefers-reduced-motion:reduce){
  *,*::before,*::after{transition-duration:1ms!important;animation-duration:1ms!important;animation-iteration-count:1!important}
}
"""

PAGE_HTML = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="referrer" content="no-referrer">
<title>Match Console</title>
<link rel="icon" href="data:,">
<style>/*CSS*/</style>
</head>
<body>
<div id="banner" class="banner" hidden></div>
<header class="mast wrap">
  <div class="mast-row">
    <div>
      <div class="eyebrow">Match Console</div>
      <h1 id="today"></h1>
    </div>
    <div class="mast-tools">
      <div class="gid" id="gidbox" hidden><span class="eyebrow">Game ID</span><b id="gid"></b>
        <button class="btn quiet small" id="copygid" type="button">Copy</button></div>
      <span class="dot" id="dot" title="Connection"></span>
      <button class="btn small savebtn" id="savebtn" type="button" hidden><span>Save</span><span class="count" id="savecount">0</span></button>
      <button class="btn small quiet" id="quitbtn" type="button">Quit</button>
    </div>
  </div>
  <div class="rule"></div>
</header>
<div class="scorebar" id="scorebar" hidden>
  <div class="wrap scorebar-in">
    <div class="st a"><span class="score roll" id="scoreA"></span><div><div class="eyebrow">Team A</div><div class="tn" id="nameA"></div></div></div>
    <div class="qbox">
      <div class="eyebrow" id="qlabel">Tossup</div>
      <div class="qline"><span class="wheel roll" id="wheel"></span></div>
      <div class="small muted" id="savestatus"></div>
    </div>
    <div class="st b"><div><div class="eyebrow">Team B</div><div class="tn" id="nameB"></div></div><span class="score roll" id="scoreB"></span></div>
  </div>
</div>
<main class="wrap" id="app" style="position:relative"></main>
<div id="toasts" aria-live="polite"></div>
<datalist id="players"></datalist>
<script>/*JS*/</script>
</body>
</html>
"""

PAGE_JS_CORE = r"""
"use strict";
const TOKEN = new URLSearchParams(location.search).get("t") || "";
const RM = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : {matches: false};
const $ = (id) => document.getElementById(id);
let V = null, ST = null, REV = -1, PREV = -1;
let PLAYERS = [], PMAP = new Map();
let current = null, polling = true, seenToast = -1, backendDown = false;
const inflight = new Set();
const SCREENS = {};
const CATS = [["lit", "Literature"], ["history", "History"], ["science", "Science"], ["fine_arts", "Fine Arts"],
  ["geography", "Geography"], ["current_events", "Current Events"], ["rmpss", "RMPSS"], ["trash", "Trash / Pop Culture"]];
const CATNAME = Object.fromEntries(CATS);

function h(tag, props, ...kids) {
  const el = document.createElement(tag);
  if (props) {
    for (const [k, v] of Object.entries(props)) {
      if (v === null || v === undefined || v === false) continue;
      if (k === "class") el.className = v;
      else if (k === "text") el.textContent = v;
      else if (k.startsWith("on")) el.addEventListener(k.slice(2), v);
      else if (k === "value" || k === "checked" || k === "disabled") el[k] = v;
      else el.setAttribute(k, v === true ? "" : String(v));
    }
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid === null || kid === undefined || kid === false) continue;
    el.append(kid.nodeType ? kid : document.createTextNode(String(kid)));
  }
  return el;
}
function setText(el, text) { text = text == null ? "" : String(text); if (el.textContent !== text) el.textContent = text; }
function show(el, on) { el.hidden = !on; }
function store(key, value) { try { if (value === null) sessionStorage.removeItem(key); else sessionStorage.setItem(key, value); } catch (e) {} }
function recall(key) { try { return sessionStorage.getItem(key); } catch (e) { return null; } }
function nextFrame(fn) { requestAnimationFrame(() => requestAnimationFrame(fn)); }

async function call(path, body) {
  const opts = {method: body ? "POST" : "GET", headers: {"X-Token": TOKEN}, cache: "no-store"};
  if (body) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
  const r = await fetch(path, opts);
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function absorb(d) {
  if (d.players) {
    PREV = d.players_rev;
    if (JSON.stringify(d.players) !== JSON.stringify(PLAYERS)) {
      PLAYERS = d.players;
      PMAP = new Map(PLAYERS.map((p) => [p[0], p]));
      const list = $("players");
      list.replaceChildren(...PLAYERS.map((p) => h("option", {value: p[0], label: p[1] + " " + (p[2] || "").slice(0, 1) + ". (" + p[0] + ")"})));
    }
  }
  if (d.status) ST = d.status;
  if (d.view) { V = d.view; REV = d.status.rev; render(); }
  if (d.status) statusUpdate();
}

async function poll() {
  if (!polling) return;
  try {
    const d = await call("/api/state?rev=" + REV + "&p=" + PREV);
    backendDown = false;
    absorb(d);
  } catch (e) {
    if (V && (V.screen === "closing" || V.screen === "closed")) { closedPage(); return; }
    backendDown = true;
    statusUpdate();
  }
  if (V && V.screen === "closed") { closedPage(); return; }
  setTimeout(poll, 500);
}

/* Actions run one at a time, in the order the moderator made them, except the
   slow lookups that wait on the game server. Repeats of a pending one-shot
   action (commit, next, ...) are dropped so a double press can't double-score. */
const REPEATABLE = new Set(["setup_form", "select", "packet_lookup"]);
const PARALLEL = new Set(["packet_lookup", "add_player", "rename"]);
let chain = Promise.resolve();
function act(type, data) {
  if (!REPEATABLE.has(type)) {
    if (inflight.has(type)) return Promise.resolve({ok: false, busy: true});
    inflight.add(type);
  }
  const run = async () => {
    try {
      const d = await call("/api/action", Object.assign({type: type}, data || {}));
      backendDown = false;
      absorb(d);
      return d;
    } catch (e) {
      backendDown = true;
      statusUpdate();
      return {ok: false, error: "The console backend isn't answering. Is client_web.py still running?"};
    } finally {
      inflight.delete(type);
    }
  };
  if (PARALLEL.has(type)) return run();
  const p = chain.then(run, run);
  chain = p.catch(() => {});
  return p;
}

async function actOrToast(type, data) {
  const r = await act(type, data);
  if (r && !r.ok && !r.busy && r.error) toast(r.error, "warn");
  return r;
}

function closedPage() {
  polling = false;
  document.body.classList.remove("ingame");
  show($("scorebar"), false);
  show($("banner"), false);
  $("app").replaceChildren(h("div", {class: "screen"},
    h("h2", {class: "sec"}, "Client closed, you can close this tab."),
    h("p", {class: "lede"}, "Every stat was either acknowledged by the server or saved to changes.json for the next launch.")));
}

/* ---- toasts ---- */
function toast(text, kind) {
  const el = h("div", {class: "toast enter " + (kind || ""), text: text, role: "status"});
  $("toasts").append(el);
  nextFrame(() => el.classList.remove("enter"));
  setTimeout(() => { el.classList.add("enter"); setTimeout(() => el.remove(), 400); }, kind === "warn" ? 8000 : 4500);
}

/* ---- rolling numbers, after gui.py's Counter and QuestionWheel ---- */
class Roller {
  constructor(el) { this.el = el; this.val = null; }
  set(value, wholeNumber) {
    const s = String(value);
    if (this.val === s) return;
    const prev = this.val;
    this.val = s;
    const signFlip = prev !== null && (prev.startsWith("-") !== s.startsWith("-"));
    if (prev === null || RM.matches || signFlip) { this.el.replaceChildren(h("span", {text: s})); return; }
    const down = Number(s) < Number(prev);
    if (wholeNumber) { this.el.replaceChildren(this.cell(prev, s, down)); return; }
    const n = Math.max(prev.length, s.length);
    const a = prev.padStart(n, " "), b = s.padStart(n, " ");
    const cells = [];
    for (let i = 0; i < n; i++) {
      if (a[i] === b[i]) { if (b[i] !== " ") cells.push(h("span", {class: "dg"}, h("span", {text: b[i]}))); }
      else cells.push(this.cell(a[i] === " " ? "" : a[i], b[i] === " " ? "" : b[i], false));
    }
    this.el.replaceChildren(...cells);
  }
  cell(from, to, down) {
    const first = down ? to : from, second = down ? from : to;
    const col = h("span", {class: "col"}, h("span", {text: first}), h("span", {text: second}));
    if (down) col.style.transform = "translateY(-1em)";
    const cell = h("span", {class: "dg"}, col);
    nextFrame(() => { col.style.transform = down ? "translateY(0)" : "translateY(-1em)"; });
    return cell;
  }
}
const scoreA = new Roller($("scoreA")), scoreB = new Roller($("scoreB")), wheel = new Roller($("wheel"));

/* ---- header, score bar, status ---- */
function header() {
  setText($("today"), V.today);
  show($("gidbox"), V.gid !== null);
  setText($("gid"), V.gid === null ? "" : V.gid);
  const g = V.game;
  const playing = !!(g && g.phase !== "registering" && V.screen === "game");
  show($("scorebar"), playing);
  show($("savebtn"), playing);
  if (!playing) return;
  scoreA.set(g.score.a);
  scoreB.set(g.score.b);
  setText($("nameA"), g.a_name);
  setText($("nameB"), g.b_name);
  const light = g.phase === "lightning" || (g.phase === "final" && g.lightnings > 0 && g.lq);
  const q = light ? (g.lq ? g.lq.i : 0) : g.tossup;
  setText($("qlabel"), light ? "Lightning" : "Tossup");
  $("wheel").classList.toggle("lightning", !!light);
  wheel.set(q, true);
}

function statusUpdate() {
  if (!ST) return;
  const dot = $("dot");
  dot.className = "dot " + (backendDown ? "lost" : ST.conn === "ok" ? "ok" : ST.conn === "lost" ? "lost" : "");
  dot.title = backendDown ? "The console backend isn't answering" : ST.conn === "ok" ? "Server answering" : ST.conn === "lost" ? "Connection lost" : "Not connected yet";
  const banner = $("banner");
  const lost = backendDown || ST.conn === "lost";
  if (lost) setText(banner, backendDown ? "The console backend isn't answering. Check the terminal where client_web.py runs." :
    "Connection lost. The server hasn't replied for 10 seconds; everything queued keeps retrying.");
  if (banner.hidden === lost) {
    show(banner, lost);
    if (lost) toast(backendDown ? "Lost contact with the console backend." : "Connection lost. Queued stats and scoreboard updates keep retrying.", "warn");
    else if (ST.conn === "ok") toast("Connection restored.", "ok");
  }
  setText($("savecount"), ST.unsent);
  const sb = $("savebtn");
  sb.disabled = ST.save.running;
  const g = V && V.game;
  let line = ST.save.running ? "Saving…" : ST.unsent ? ST.unsent + " waiting for the server" : "All sent stats acknowledged";
  if (g && g.held) line += " · Tossup " + g.held + " held for correction";
  if (ST.save.result && !ST.save.running) sb.title = ST.save.result;
  if (awaitingSave && !ST.save.running && ST.save.result) { awaitingSave = false; toast(ST.save.result, ST.save.ok ? "ok" : "warn"); }
  setText($("savestatus"), line);
  if (seenToast < 0) seenToast = ST.toasts.length ? ST.toasts[ST.toasts.length - 1].id : 0;
  for (const t of ST.toasts) if (t.id > seenToast) { seenToast = t.id; toast(t.text, t.kind); }
}

let awaitingSave = false;
$("savebtn").addEventListener("click", async () => {
  const r = await actOrToast("flush");
  if (r && r.ok) { awaitingSave = true; toast("Sending stats to the server…"); }
});
$("quitbtn").addEventListener("click", () => {
  const g = V && V.game;
  const midGame = g && g.phase !== "final";
  confirmBox(midGame ? "Quit in the middle of the game?" : "Quit the console?",
    midGame ? "The question in progress is discarded. Every completed question is sent to the server, or saved to changes.json if it can't be reached. Then the client closes."
            : "Unsent stats are sent to the server, or saved to changes.json. Then the client closes.",
    "Quit", () => act("quit"));
});
$("copygid").addEventListener("click", () => copyText(String(V.gid)));

function copyText(text) {
  const done = () => toast("Game ID " + text + " copied.", "ok");
  if (navigator.clipboard && window.isSecureContext) navigator.clipboard.writeText(text).then(done, () => fallbackCopy(text, done));
  else fallbackCopy(text, done);
}
function fallbackCopy(text, done) {
  const t = h("textarea", {style: "position:fixed;opacity:0"});
  t.value = text;
  document.body.append(t);
  t.select();
  try { document.execCommand("copy"); done(); } catch (e) { toast("Copy failed; the game ID is " + text + ".", "warn"); }
  t.remove();
}

function confirmBox(title, body, okLabel, onOk) {
  const close = () => { ov.remove(); document.removeEventListener("keydown", onKey, true); };
  const ok = h("button", {class: "btn primary", type: "button", text: okLabel, onclick: () => { close(); onOk(); }});
  const ov = h("div", {class: "overlay", role: "dialog", "aria-modal": "true"},
    h("div", {class: "card"}, h("h2", {class: "sec", style: "margin-top:0"}, title), h("p", {class: "lede"}, body),
      h("div", {class: "row", style: "justify-content:flex-end;margin-top:18px"},
        h("button", {class: "btn", type: "button", text: "Cancel", onclick: close}), ok)));
  const onKey = (e) => { if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); close(); } };
  document.addEventListener("keydown", onKey, true);
  document.body.append(ov);
  ok.focus();
}

/* ---- screen switching with a cross-fade ---- */
function render() {
  document.body.classList.toggle("ingame", V.screen === "game");
  header();
  const name = SCREENS[V.screen] ? V.screen : "closing";
  if (!current || current.name !== name) {
    const main = $("app");
    const el = h("div", {class: "screen fade"});
    const inst = SCREENS[name].mount(el);
    if (current) {
      const old = current.el;
      old.style.position = "absolute"; old.style.left = "24px"; old.style.right = "24px"; old.style.top = "18px";
      old.style.pointerEvents = "none";
      old.classList.add("fade");
      setTimeout(() => old.remove(), 300);
    }
    main.append(el);
    nextFrame(() => el.classList.remove("fade"));
    current = {name: name, el: el, inst: inst};
    window.scrollTo(0, 0);
  }
  current.inst.update(V);
}

document.addEventListener("keydown", (e) => {
  if (e.defaultPrevented || e.metaKey || e.ctrlKey || e.altKey) return;
  const t = e.target;
  if (t && (t.tagName === "INPUT" || t.tagName === "SELECT" || t.tagName === "TEXTAREA" || t.isContentEditable)) return;
  if (document.querySelector(".overlay:not([hidden])")) return;
  if (current && current.inst.key) current.inst.key(e);
});

SCREENS.closing = {mount(el) {
  el.append(h("h2", {class: "sec"}, h("span", {class: "spinner"}), " Closing"),
    h("p", {class: "lede"}, "Sending the last stats and closing the game on the server…"));
  return {update() {}};
}};
"""

PAGE_JS_SCREENS = r"""
/* ---- server settings form, used on Connect and Settings ---- */
function settingsForm() {
  const host = h("input", {type: "text", class: "w-wide", autocomplete: "off", spellcheck: "false"});
  const port = h("input", {type: "text", class: "w-num", inputmode: "numeric", autocomplete: "off"});
  const err = h("div", {class: "err"});
  const ok = h("div", {class: "ok-msg"});
  const save = h("button", {class: "btn primary", type: "button", text: "Save and connect"});
  let filled = false;
  const submit = async () => {
    setText(err, ""); setText(ok, "");
    const r = await act("settings_save", {host: host.value, port: port.value});
    if (r && !r.ok && !r.busy) setText(err, r.error);
  };
  save.addEventListener("click", submit);
  for (const i of [host, port]) i.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const el = h("div", {class: "stack"},
    h("div", {class: "row", style: "align-items:flex-end"},
      h("label", {class: "f"}, h("span", null, "Host or IP"), host),
      h("label", {class: "f"}, h("span", null, "Port"), port), save),
    err, ok);
  return {el: el, update(v) {
    if (!filled) { host.value = v.host || ""; port.value = v.port || ""; filled = true; }
    save.disabled = !!v.settings.busy || !!v.reconnecting;
    setText(save, v.settings.busy ? "Checking…" : "Save and connect");
    if (v.settings.error) setText(err, v.settings.error);
    setText(ok, v.settings.ok || "");
  }};
}

/* ---- 1. Connect ---- */
SCREENS.connect = {mount(el) {
  const title = h("h2", {class: "sec"});
  const msg = h("p", {class: "lede"});
  const err = h("p", {class: "err", style: "font-size:14px"});
  const retry = h("button", {class: "btn primary", type: "button", text: "Retry", onclick: () => actOrToast("retry")});
  const sessName = h("input", {type: "text", class: "w-wide", maxlength: "64", placeholder: "Optional, e.g. Round 3 Room 2", autocomplete: "off"});
  const go = h("button", {class: "btn primary", type: "button", text: "Continue"});
  const submit = () => actOrToast("session", {name: sessName.value});
  go.addEventListener("click", submit);
  sessName.addEventListener("keydown", (e) => { if (e.key === "Enter") submit(); });
  const sess = h("div", {class: "stack"},
    h("label", {class: "f"}, h("span", null, "Session name"), sessName),
    h("div", {class: "small muted"}, "Letters, digits, spaces, _ and - only; up to 32 characters. Leave blank to skip."),
    h("div", null, go));
  const settings = settingsForm();
  const settingsBox = h("div", {class: "panel"}, h("div", {class: "eyebrow", style: "margin-bottom:8px"}, "Server settings"), settings.el);
  el.append(title, msg, err, h("div", {class: "row"}, retry), sess, settingsBox);
  let focused = false;
  return {update(v) {
    const c = v.connect, addr = (v.host || "?") + ":" + (v.port || "?");
    const phase = c.phase;
    setText(title, {connecting: "Connecting", failed: "Can't reach the server", session: "Connected",
      requesting: "Requesting a game ID", recovering: "Sending older stats", done: "Connected"}[phase] || "Connecting");
    setText(msg, {connecting: "Loading the player list from " + addr + "…", failed: "Server address: " + addr,
      session: "Loaded " + PLAYERS.length + " players from " + addr + ". Name this session if you like, then continue.",
      requesting: "Asking " + addr + " for a game ID…", recovering: "Sending stats and players saved by an earlier session…",
      done: ""}[phase] || "");
    if (phase === "connecting" || phase === "requesting" || phase === "recovering") title.prepend(h("span", {class: "spinner"}), " ");
    setText(err, phase === "failed" ? c.error : "");
    show(retry.parentNode, phase === "failed");
    show(sess, phase === "session");
    show(settingsBox, phase === "failed");
    settings.update(v);
    if (phase === "session" && !focused) { focused = true; sessName.focus(); }
  }};
}};

/* ---- 2. Home ---- */
SCREENS.home = {mount(el) {
  const id = h("div", {class: "bigid"});
  const addr = h("div", {class: "small muted"});
  const rec = h("div", {class: "status-line"});
  const backlog = h("div", {class: "status-line"});
  const start = h("button", {class: "btn primary big", type: "button", text: "Start game", onclick: () => actOrToast("goto", {screen: "setup"})});
  el.append(h("div", {class: "home-grid"},
    h("div", null,
      h("div", {class: "eyebrow"}, "Game ID"), id,
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", text: "Copy game ID", onclick: () => copyText(String(V.gid))})),
      h("p", {class: "lede small", style: "margin-top:12px"}, "The scoreboard operator types this ID into gui.py."),
      addr, rec, backlog),
    h("div", {class: "menu"},
      start,
      h("button", {class: "btn", type: "button", text: "Rename player", onclick: () => actOrToast("goto", {screen: "rename"})}),
      h("button", {class: "btn", type: "button", text: "Test connection", onclick: () => actOrToast("goto", {screen: "test"})}),
      h("button", {class: "btn", type: "button", text: "Server settings", onclick: () => actOrToast("goto", {screen: "settings"})}),
      h("button", {class: "btn quiet", type: "button", text: "Quit", onclick: () => $("quitbtn").click()}))));
  return {update(v) {
    setText(id, v.gid);
    setText(addr, "Server " + v.host + ":" + v.port + (v.session ? " · Session “" + v.session + "”" : "") + " · " + PLAYERS.length + " players");
    setText(rec, v.recovery);
    const n = ST ? ST.unsent : 0;
    setText(backlog, n ? n + " stat" + (n === 1 ? "" : "s") + " still waiting for the server; they keep retrying." : "");
    start.disabled = !!v.reconnecting;
  }};
}};

/* ---- 13. Server settings ---- */
SCREENS.settings = {mount(el) {
  const settings = settingsForm();
  el.append(h("h2", {class: "sec"}, "Server settings"),
    h("p", {class: "lede"}, "Saved to config.ini one folder up, which client.py, gui.py and this console all read. Other settings in the file are kept."),
    settings.el,
    h("div", {class: "panel"}, h("button", {class: "btn", type: "button", text: "Back to home", onclick: () => actOrToast("goto", {screen: "home"})})));
  return {update(v) { settings.update(v); }};
}};

/* ---- 11. Rename player ---- */
SCREENS.rename = {mount(el) {
  const target = h("input", {type: "text", class: "w-mid", list: "players", autocomplete: "off", spellcheck: "false"});
  const who = h("div", {class: "seatinfo muted"});
  const nu = h("input", {type: "text", class: "w-mid", autocomplete: "off", spellcheck: "false", maxlength: "32"});
  const first = h("input", {type: "text", class: "w-mid", autocomplete: "off", maxlength: "64"});
  const last = h("input", {type: "text", class: "w-mid", autocomplete: "off", maxlength: "64"});
  const err = h("div", {class: "err", style: "font-size:13px"});
  const ok = h("div", {class: "ok-msg"});
  const save = h("button", {class: "btn primary", type: "button", text: "Rename"});
  const sync = () => {
    const p = PMAP.get(target.value.toLowerCase().trim());
    setText(who, p ? p[1] + " " + p[2] : target.value.trim() ? "That username is not in the database." : "");
    who.className = "seatinfo " + (p || !target.value.trim() ? "muted" : "err");
    nu.placeholder = p ? p[0] : "";
    first.placeholder = p ? p[1] : "";
    last.placeholder = p ? p[2] : "";
    save.disabled = !p;
  };
  target.addEventListener("input", sync);
  save.addEventListener("click", async () => {
    setText(err, ""); setText(ok, "");
    save.disabled = true;
    const r = await act("rename", {target: target.value, new: nu.value, first: first.value, last: last.value});
    if (r && r.ok) { setText(ok, r.message); target.value = ""; nu.value = ""; first.value = ""; last.value = ""; }
    else if (r && !r.busy) setText(err, r.error);
    sync();
  });
  el.append(h("h2", {class: "sec"}, "Rename player"),
    h("p", {class: "lede"}, "Leave a field blank to keep it. New usernames must be letters only, at least 3 long, and not already taken."),
    h("div", {class: "stack", style: "max-width:560px"},
      h("label", {class: "f"}, h("span", null, "Player (username)"), target), who,
      h("label", {class: "f"}, h("span", null, "New username"), nu),
      h("div", {class: "row"}, h("label", {class: "f"}, h("span", null, "First name"), first), h("label", {class: "f"}, h("span", null, "Last name"), last)),
      h("div", {class: "row"}, save, h("button", {class: "btn", type: "button", text: "Back to home", onclick: () => actOrToast("goto", {screen: "home"})})),
      err, ok));
  sync();
  target.focus();
  return {update() { sync(); }};
}};

/* ---- 12. Test connection ---- */
SCREENS.test = {mount(el) {
  const run = h("button", {class: "btn primary", type: "button", text: "Start test", onclick: () => actOrToast("test_start")});
  const exp = h("button", {class: "btn", type: "button", text: "Export CSV", onclick: async () => {
    const r = await actOrToast("test_export");
    if (r && r.ok) toast(r.message, "ok");
  }});
  const prog = h("div", {class: "slider", style: "max-width:520px"}, h("div", {class: "fill", style: "width:0;background:var(--ink)"}));
  const line = h("div", {class: "status-line"});
  const tiles = h("div", {class: "tiles", style: "max-width:720px;margin-top:14px"});
  const warns = h("div", {class: "stack", style: "margin-top:12px;max-width:720px"});
  const chart = h("div", {class: "chart", style: "max-width:720px;margin-top:14px"});
  el.append(h("h2", {class: "sec"}, "Test connection"),
    h("p", {class: "lede"}, "Sends five pretest packets, then exchanges packets with the server for 10 seconds and reports loss and latency, like client.py's test."),
    h("div", {class: "row"}, run, exp, h("button", {class: "btn", type: "button", text: "Back to home", onclick: () => actOrToast("goto", {screen: "home"})})),
    h("div", {style: "margin-top:16px"}, prog), line, tiles, warns, chart);
  const tile = (label, value) => h("div", {class: "tile"}, h("div", {class: "v"}, value), h("div", {class: "eyebrow"}, label));
  let drawn = null;
  return {update(v) {
    const t = v.test;
    const busy = !!(t && (t.phase === "pretest" || t.phase === "running"));
    run.disabled = busy;
    exp.disabled = !(t && t.phase === "done");
    const pct = !t ? 0 : t.phase === "pretest" ? (t.pre / 5) * 8 : t.phase === "running" ? 8 + (t.elapsed / 10) * 92 : 100;
    prog.firstChild.style.width = pct + "%";
    if (!t) setText(line, "Takes at least 10 seconds.");
    else if (t.phase === "pretest") setText(line, "Pretest packet " + t.pre + " of 5…");
    else if (t.phase === "running") setText(line, (t.elapsed || 0).toFixed(1) + " s · " + t.ok + " exchanged · " + t.drops + " lost");
    else if (t.phase === "failed") setText(line, t.error);
    else setText(line, "Done.");
    line.className = "status-line" + (t && t.phase === "failed" ? " err" : "");
    const key = t && t.phase === "done" ? JSON.stringify([t.ok, t.drops, t.median]) : null;
    if (key === drawn) return;
    drawn = key;
    tiles.replaceChildren(); warns.replaceChildren(); chart.replaceChildren();
    if (!key) return;
    tiles.append(tile("Exchanged", t.ok), tile("Lost", t.drops + (t.drops ? " (" + t.loss + ")" : "")),
      tile("Median ms", t.median), tile("Max ms", t.max));
    for (const w of t.warnings) warns.append(h("div", {class: "warn-msg"}, h("b", null, "Warning: "), w));
    chart.append(h("div", {class: "eyebrow", style: "margin-bottom:4px"}, "Round-trip time (ms)"), latencyChart(t.series));
  }};
}};

function svg(tag, attrs, ...kids) {
  const el = document.createElementNS("http://www.w3.org/2000/svg", tag);
  for (const [k, v] of Object.entries(attrs || {})) el.setAttribute(k, String(v));
  for (const k of kids.flat()) if (k !== null && k !== undefined && k !== false) el.append(k.nodeType ? k : document.createTextNode(String(k)));
  return el;
}

function latencyChart(series) {
  const W = 720, H = 180, L = 44, R = 10, T = 10, B = 22;
  const max = Math.max(1, ...series), n = series.length;
  const x = (i) => L + (n <= 1 ? 0 : (i / (n - 1)) * (W - L - R));
  const y = (v) => T + (1 - v / max) * (H - T - B);
  const g = svg("svg", {viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Latency chart"});
  for (let i = 0; i <= 4; i++) {
    const v = (max * i) / 4;
    g.append(svg("line", {class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v)}),
      svg("text", {x: L - 6, y: y(v) + 3, "text-anchor": "end"}, v < 10 ? v.toFixed(1) : Math.round(v)));
  }
  g.append(svg("line", {class: "ax", x1: L, x2: W - R, y1: H - B, y2: H - B}));
  g.append(svg("path", {class: "la", d: series.map((v, i) => (i ? "L" : "M") + x(i).toFixed(1) + " " + y(v).toFixed(1)).join(" ")}));
  g.append(svg("text", {x: W - R, y: H - 6, "text-anchor": "end"}, "packets over 10 s"));
  return g;
}
"""

PAGE_JS_SETUP = r"""
/* ---- 3. Game setup, all on one page ---- */
SCREENS.setup = {mount(el) {
  let F = null, seq = 0, timer = null, lookupTimer = null, check = null, lastLookup = "", lookupKey = null;
  const bool = (k) => !!F[k];
  const post = (delay) => {
    clearTimeout(timer);
    timer = setTimeout(() => { seq += 1; act("setup_form", {form: F, seq: seq}); }, delay === undefined ? 120 : delay);
  };
  const numIn = (key) => {
    const i = h("input", {type: "text", class: "w-num", inputmode: "numeric", autocomplete: "off"});
    i.addEventListener("input", () => { F[key] = i.value; if (key === "players") resizeSeats(); post(); });
    return i;
  };
  const tog = (key, label) => {
    const i = h("input", {type: "checkbox"});
    i.addEventListener("change", () => { F[key] = i.checked; if (key === "packet_none" || key === "packet_confirm") post(0); else post(); layout(); });
    return {input: i, el: h("label", {class: "toggle"}, i, h("span", {class: "sw"}), h("span", null, label))};
  };
  const txt = (key, cls, extra) => {
    const i = h("input", Object.assign({type: "text", class: cls || "w-mid", autocomplete: "off", maxlength: "64"}, extra || {}));
    i.addEventListener("input", () => { F[key] = i.value; post(); layout(); });
    return i;
  };
  const errFor = () => h("div", {class: "err"});

  const tossups = tog("tossups", "Tossups"), lightnings = tog("lightnings", "Lightning round"), players = numIn("players");
  const eL = errFor(), eP = errFor();
  const aInd = tog("a_ind", "Individual stats for team A"), bInd = tog("b_ind", "Individual stats for team B");
  const useNames = tog("use_names", "Use team names");
  const aName = txt("a_name"), bName = txt("b_name");
  const eA = errFor(), eB = errFor();
  const namesBox = h("div", {class: "row", style: "align-items:flex-start;margin-top:12px"},
    h("label", {class: "f"}, h("span", null, "Team A name"), aName, eA), h("label", {class: "f"}, h("span", null, "Team B name"), bName, eB));
  const seatCols = {a: h("div"), b: h("div")};
  const seatHeads = {a: h("div", {class: "eyebrow", style: "color:var(--team-a);margin-bottom:8px"}), b: h("div", {class: "eyebrow", style: "color:var(--team-b);margin-bottom:8px"})};
  const seatRows = {a: [], b: []};

  const packetNone = tog("packet_none", "No packet");
  const packetId = txt("packet", "w-mid", {placeholder: "e.g. is #226a p1", spellcheck: "false"});
  packetId.addEventListener("input", () => {
    F.packet_confirm = false; F.packet_name = "";
    packetConfirm.input.checked = false; packetName.value = "";
    scheduleLookup();
  });
  const packetConfirm = tog("packet_confirm", "Yes, this is the packet");
  const packetName = txt("packet_name", "w-wide", {maxlength: "100", placeholder: "e.g. Inv. Series #226A Packet 1"});
  const lookupBox = h("div", {class: "lookup"});
  const ePk = errFor(), ePn = errFor();
  const packetSec = h("section", null, h("h2", {class: "sec"}, h("span", {class: "sn"}, "§ 04"), "Packet"),
    h("div", {class: "row"}, packetNone.el),
    h("div", {class: "row", style: "margin-top:10px;align-items:flex-start"}, h("label", {class: "f"}, h("span", null, "Packet id"), packetId, ePk)),
    lookupBox);

  const override = tog("name_override", "Use a different game name");
  const gameName = txt("game_name", "w-wide");
  const eG = errFor();
  const defaultName = h("div", {class: "small"});

  const startErr = h("div", {class: "err", style: "font-size:13px"});
  const start = h("button", {class: "btn primary big", type: "button", text: "Start game"});
  const overlay = h("div", {class: "overlay", hidden: true});
  const regStatus = h("p", {class: "lede"});
  overlay.append(h("div", {class: "card"}, h("h2", {class: "sec", style: "margin-top:0"}, h("span", {class: "spinner"}), " Registering game"),
    regStatus, h("div", {class: "row", style: "justify-content:flex-end"},
      h("button", {class: "btn", type: "button", text: "Cancel", onclick: () => act("cancel_register")}))));

  start.addEventListener("click", async () => {
    clearTimeout(timer);
    seq += 1;
    await act("setup_form", {form: F, seq: seq});
    const r = await act("start");
    if (r && !r.ok && !r.busy) setText(startErr, r.error);
  });

  function scheduleLookup() {
    clearTimeout(lookupTimer);
    const id = packetId.value.toLowerCase().trim();
    if (!id || id === "pass" || F.packet_none) return;
    lookupTimer = setTimeout(async () => {
      clearTimeout(timer); seq += 1;
      await act("setup_form", {form: F, seq: seq});
      lastLookup = id;
      act("packet_lookup", {id: id});
    }, 380);
  }

  function resizeSeats() {
    const n = parseInt(F.players, 10);
    if (!(n >= 1 && n <= 9)) return;
    for (const t of ["a", "b"]) {
      const key = "seats_" + t;
      while (F[key].length < n) F[key].push("");
      F[key].length = n;
    }
    buildSeats();
  }

  function buildSeats() {
    for (const t of ["a", "b"]) {
      const n = Math.max(0, Math.min(9, parseInt(F.players, 10) || 0));
      seatRows[t] = [];
      const col = seatCols[t];
      col.replaceChildren();
      for (let i = 0; i < n; i++) {
        const input = h("input", {type: "text", class: "w-mid", list: "players", autocomplete: "off", spellcheck: "false", maxlength: "32",
          "aria-label": "Team " + t.toUpperCase() + " seat " + (i + 1)});
        input.value = F["seats_" + t][i] || "";
        input.addEventListener("input", () => { F["seats_" + t][i] = input.value; post(); });
        const info = h("div", {class: "seatinfo"});
        const first = h("input", {type: "text", placeholder: "First name", maxlength: "64", autocomplete: "off"});
        const last = h("input", {type: "text", placeholder: "Last name", maxlength: "64", autocomplete: "off"});
        const addErr = h("div", {class: "err", style: "width:100%"});
        const add = h("button", {class: "btn small primary", type: "button", text: "Add player"});
        const addForm = h("div", {class: "addform", hidden: true}, first, last, add, addErr);
        add.addEventListener("click", async () => {
          setText(addErr, "");
          add.disabled = true;
          const r = await act("add_player", {username: input.value, first: first.value, last: last.value});
          add.disabled = false;
          if (r && r.ok) { toast(r.message, r.pending ? "warn" : "ok"); first.value = ""; last.value = ""; post(0); }
          else if (r && !r.busy) {
            setText(addErr, r.error);
            if (/already belongs|reserved/.test(r.error)) { input.value = ""; F["seats_" + t][i] = ""; post(0); }
          }
        });
        const combined = h("div", {class: "small muted", style: "padding-top:9px"});
        seatRows[t].push({input, info, addForm, combined});
        col.append(h("div", {class: "seatrow"}, h("div", {class: "seatno"}, t.toUpperCase() + (i + 1)),
          h("div", null, input, combined, info, addForm)));
      }
    }
    paintSeats();
  }

  function paintSeats() {
    for (const t of ["a", "b"]) {
      const ind = bool(t + "_ind");
      const name = check && check.names_needed ? (F[t + "_name"] || "").trim() : "";
      setText(seatHeads[t], (name || "Team " + t.toUpperCase()) + (ind ? "" : " · combined score"));
      seatRows[t].forEach((row, i) => {
        show(row.input, ind);
        show(row.combined, !ind);
        setText(row.combined, "Plays as " + (name || "Team " + t.toUpperCase()) + "; the scoreboard shows this seat blank.");
        const s = check && check.seats[t] && check.seats[t][i];
        let text = "", cls = "seatinfo muted";
        if (ind && s) {
          if (s.status === "ok") { text = s.full + (s.pending ? " · not yet confirmed by the server, will keep retrying" : ""); cls = s.pending ? "seatinfo warn-msg" : "seatinfo ok-msg"; }
          else if (s.status === "new") { text = "Not in the player list. Add them:"; cls = "seatinfo muted"; }
          else if (s.status === "error") { text = s.msg; cls = "seatinfo err"; }
        }
        setText(row.info, text);
        row.info.className = cls;
        row.input.classList.toggle("bad", !!(ind && s && s.status === "error"));
        row.input.classList.toggle("good", !!(ind && s && s.status === "ok"));
        show(row.addForm, !!(ind && s && s.status === "new"));
      });
    }
  }

  function layout() {
    const both = bool("a_ind") && bool("b_ind");
    show(useNames.el, both);
    const needNames = !both || bool("use_names");
    show(namesBox, needNames);
    show(packetSec, bool("tossups"));
    show(override.el, needNames);
    show(gameName.parentNode, !needNames || bool("name_override"));
    show(defaultName, needNames && !bool("name_override"));
    const a = (F.a_name || "").trim(), b = (F.b_name || "").trim();
    setText(defaultName, a && b ? "Game name: " + a + " vs. " + b : "Game name: the two team names, “A vs. B”.");
    packetId.disabled = bool("packet_none");
    paintSeats();
  }

  function paintCheck() {
    if (!check) return;
    const e = check.errors || {};
    setText(eL, e.lightnings || ""); setText(eP, e.players || "");
    setText(eA, e.a_name || ""); setText(eB, e.b_name || ""); setText(eG, e.game_name || "");
    setText(ePk, e.packet || ""); setText(ePn, e.packet_name || "");
    const pk = check.packet || {status: "none"};
    show(lookupBox, ["looking", "found", "notfound", "error"].includes(pk.status) && !F.packet_none);
    const pkKey = JSON.stringify(pk);
    if (pkKey !== lookupKey) {
      lookupKey = pkKey;
      lookupBox.replaceChildren();
      if (pk.status === "looking") lookupBox.append(h("span", {class: "spinner"}), " Looking up the packet…");
      else if (pk.status === "found") lookupBox.append(h("div", null, "Packet is ", h("b", null, pk.name), " and was last played " + pk.last_played + "."),
        h("div", {style: "margin-top:8px"}, packetConfirm.el));
      else if (pk.status === "notfound") lookupBox.append(h("div", null, "This packet isn't in the database yet. Name it:"),
        h("div", {style: "margin-top:8px"}, packetName, ePn));
      else if (pk.status === "error") lookupBox.append(h("div", {class: "err"}, pk.msg), h("div", {style: "margin-top:8px"},
        h("button", {class: "btn small", type: "button", text: "Look up again", onclick: () => { lastLookup = ""; scheduleLookup(); }})));
    }
    packetConfirm.input.checked = !!F.packet_confirm;
    start.disabled = !check.ok;
    const missing = [];
    if (e.lightnings !== undefined || e.players !== undefined) missing.push("format");
    if (e.a_name !== undefined || e.b_name !== undefined) missing.push("team names");
    if (e.seats !== undefined) missing.push("seats");
    if (e.packet !== undefined || e.packet_name !== undefined) missing.push("packet");
    if (e.game_name !== undefined) missing.push("game name");
    return missing;
  }

  const summary = h("div", {class: "small muted"});
  el.append(
    h("h2", {class: "sec"}, "Game setup"),
    h("p", {class: "lede"}, "Everything client.py asks before the first tossup. Start unlocks when every section is complete."),
    h("section", null, h("h2", {class: "sec"}, h("span", {class: "sn"}, "§ 01"), "Format"),
      h("div", {class: "row", style: "gap:24px"}, tossups.el, lightnings.el), eL,
      h("div", {class: "row", style: "align-items:flex-start;margin-top:12px"},
        h("label", {class: "f"}, h("span", null, "Players per team"), players, eP))),
    h("section", null, h("h2", {class: "sec"}, h("span", {class: "sn"}, "§ 02"), "Teams"),
      h("div", {class: "row", style: "gap:24px"}, aInd.el, bInd.el, useNames.el), namesBox),
    h("section", null, h("h2", {class: "sec"}, h("span", {class: "sn"}, "§ 03"), "Seats"),
      h("div", {class: "grid2"}, h("div", null, seatHeads.a, seatCols.a), h("div", null, seatHeads.b, seatCols.b))),
    packetSec,
    h("section", null, h("h2", {class: "sec"}, h("span", {class: "sn"}, "§ 05"), "Game name"),
      h("div", {class: "row"}, override.el), defaultName,
      h("label", {class: "f", style: "margin-top:10px"}, h("span", null, "Game name"), gameName, eG)),
    h("div", {class: "startbar"}, h("div", null, startErr, summary),
      h("div", {class: "row"}, h("button", {class: "btn", type: "button", text: "Back to home", onclick: () => actOrToast("goto", {screen: "home"})}), start)),
    overlay);

  function load(v) {
    F = JSON.parse(JSON.stringify(v.setup.form));
    seq = v.setup.seq;
    tossups.input.checked = F.tossups; lightnings.input.checked = F.lightnings; players.value = F.players;
    aInd.input.checked = F.a_ind; bInd.input.checked = F.b_ind; useNames.input.checked = F.use_names;
    aName.value = F.a_name; bName.value = F.b_name; packetNone.input.checked = F.packet_none; packetId.value = F.packet;
    packetConfirm.input.checked = F.packet_confirm; packetName.value = F.packet_name;
    override.input.checked = F.name_override; gameName.value = F.game_name;
    buildSeats();
  }

  let loadedFor = null;
  return {update(v) {
    if (!v.setup) return;
    if (loadedFor === null) { load(v); loadedFor = v.setup.seq; players.focus(); }
    if (v.setup.seq === seq) check = v.setup.check;
    layout();
    const missing = paintCheck() || [];
    setText(summary, check && check.ok ? "Ready. Start registers the game and opens the first question." : missing.length ? "Still needed: " + missing.join(", ") + "." : "");
    setText(startErr, v.setup.error || "");
    const reg = v.game && v.game.phase === "registering";
    show(overlay, reg);
    if (reg) setText(regStatus, v.game.register.status);
  }};
}};
"""

PAGE_JS_GAME = r"""
/* ---- 4-9. The game screen ---- */
const OUTCOMES = {1: ["power", "Power", "+15"], 2: ["ten", "Ten", "+10"], 3: ["neg", "Neg", "−5"], 4: ["zero", "Zero", "0"]};
const teamName = (g, t) => t === "a" ? g.a_name : g.b_name;

function legendEl() {
  const item = (c, label) => h("span", null, h("i", {style: "background:" + c}), label);
  return h("div", {class: "legend"}, item("var(--power)", "Power · +15"), item("var(--ten)", "Get · +10"),
    item("var(--none)", "No buzz · 0"), item("var(--neg)", "Neg · −5"));
}

/* Typing a1, 1a, b2 or a username picks a seat, as client.py's prompt does. */
function seatTyper(opts) {
  let buf = "", timer = null, digitPrev;
  const reset = () => { buf = ""; digitPrev = undefined; clearTimeout(timer); };
  const expire = () => {
    if (buf === "p") opts.pass();
    else { const m = opts.users().find((u) => u[0] === buf); if (m) opts.select(m[1], m[2]); }
    reset();
  };
  const arm = () => { clearTimeout(timer); timer = setTimeout(expire, 900); };
  return (key) => {
    if (key.length !== 1) return false;
    const k = key.toLowerCase();
    if (/^[1-9]$/.test(k)) {
      if (buf === "a" || buf === "b") { opts.select(buf, Number(k)); reset(); return true; }
      reset();
      digitPrev = opts.digit(Number(k));
      buf = k;
      arm();
      return true;
    }
    if (k === k.toUpperCase()) return false;
    if (/^[1-9]$/.test(buf) && (k === "a" || k === "b")) { opts.restore(digitPrev); opts.select(k, Number(buf)); reset(); return true; }
    if (/^[1-9]$/.test(buf)) reset();
    const users = opts.users();
    if (buf === "" && k === "p" && !users.some((u) => u[0].startsWith("p"))) { opts.pass(); reset(); return true; }
    buf += k;
    const m = users.find((u) => u[0] === buf);
    if (m && !users.some((u) => u[0] !== buf && u[0].startsWith(buf))) { opts.select(m[1], m[2]); reset(); return true; }
    if (buf === "pass") { opts.pass(); reset(); return true; }
    arm();
    return true;
  };
}

function inPlay(g) {
  const out = [];
  for (const t of ["a", "b"]) g.seats[t].forEach((s, i) => { if (!s.u.startsWith("!")) out.push([s.u, t, i + 1]); });
  return out;
}

function valueOpts(defs, onPick) {
  const btns = defs.map(([v, cls, label, pts]) => {
    const b = h("button", {class: "opt " + cls, type: "button", onclick: () => onPick(v)}, h("span", {class: "c"}), label + " " + pts, h("span", {class: "k"}, String(v)));
    b.dataset.v = v;
    return b;
  });
  return {el: h("div", {class: "opts", role: "radiogroup"}, btns), paint(val) {
    for (const b of btns) { const on = Number(b.dataset.v) === val; b.classList.toggle("on", on); b.setAttribute("aria-checked", on ? "true" : "false"); b.setAttribute("role", "radio"); }
  }};
}

function selDescription(g) {
  if (!g.sel) return null;
  const s = g.seats[g.sel.team][g.sel.seat - 1];
  return g.sel.team.toUpperCase() + g.sel.seat + " · " + (s.u.startsWith("!") ? teamName(g, g.sel.team) + ", seat " + g.sel.seat : s.label);
}

function confirmCorrection(n, extra, onOk) {
  confirmBox("Correct Tossup " + n + "?",
    "The score, seats and scoreboard messages go back to how they were before Tossup " + n + ", its stats are discarded, and it is replayed." + (extra || ""),
    "Correct Tossup " + n, () => {
      store("tu:" + V.gid + ":" + n + ":cat", null);
      store("tu:" + V.gid + ":" + n + ":val", null);
      onOk();
    });
}

/* Substitutions, as an overlay during a tossup or inline before lightning. */
function subsPanel(inline) {
  let out = null;
  const list = h("div", {class: "stack", style: "gap:6px"});
  const input = h("input", {type: "text", class: "w-mid", list: "players", autocomplete: "off", spellcheck: "false", maxlength: "32", placeholder: "Username to sub in"});
  const info = h("div", {class: "seatinfo"});
  const first = h("input", {type: "text", placeholder: "First name", maxlength: "64"});
  const last = h("input", {type: "text", placeholder: "Last name", maxlength: "64"});
  const add = h("button", {class: "btn small primary", type: "button", text: "Add player"});
  const addForm = h("div", {class: "addform", hidden: true}, first, last, add);
  const err = h("div", {class: "err", style: "font-size:13px"});
  const go = h("button", {class: "btn primary", type: "button", text: "Sub in"});
  let g = null;
  const sync = () => {
    const u = input.value.toLowerCase().trim();
    const p = PMAP.get(u);
    const inGame = g && inPlay(g).some((x) => x[0] === u);
    let text = "", cls = "seatinfo muted", needAdd = false;
    if (!u) text = "";
    else if (inGame) { text = "That player is already in play."; cls = "seatinfo err"; }
    else if (p) text = p[1] + " " + p[2];
    else if (u.length >= 3 && u !== "pass") { text = "Not in the player list. Add them:"; needAdd = true; }
    setText(info, text); info.className = cls;
    show(addForm, needAdd);
    go.disabled = !out || !p || inGame;
  };
  input.addEventListener("input", () => { setText(err, ""); sync(); });
  add.addEventListener("click", async () => {
    setText(err, "");
    const r = await act("add_player", {username: input.value, first: first.value, last: last.value});
    if (r && r.ok) { toast(r.message, r.pending ? "warn" : "ok"); first.value = ""; last.value = ""; }
    else if (r && !r.busy) { setText(err, r.error); if (/already belongs|reserved/.test(r.error)) input.value = ""; }
    sync();
  });
  const submit = async () => {
    if (go.disabled) return;
    setText(err, "");
    const r = await act("sub", {team: out.team, seat: out.seat, username: input.value});
    if (r && r.ok) { toast(r.message, "ok"); input.value = ""; out = null; }
    else if (r && !r.busy) setText(err, r.error);
    sync();
  };
  go.addEventListener("click", submit);
  input.addEventListener("keydown", (e) => { if (e.key === "Enter") { e.preventDefault(); submit(); } });
  const done = h("button", {class: "btn", type: "button", text: "Done", onclick: () => act("subs_close")});
  const body = h("div", null,
    h("div", {class: "eyebrow", style: "margin-bottom:6px"}, "1 · Player to sub out"), list,
    h("div", {class: "eyebrow", style: "margin:14px 0 6px"}, "2 · Player to sub in"),
    h("div", {class: "row", style: "align-items:flex-start"}, h("div", null, input, info, addForm), go), err);
  const el = inline ? h("div", {class: "panel"}, body)
    : h("div", {class: "overlay"}, h("div", {class: "card"}, h("h2", {class: "sec", style: "margin-top:0"}, "Substitutions"),
        h("p", {class: "lede small"}, "Make as many as you need, then press Done to return to the tossup."), body,
        h("div", {class: "row", style: "justify-content:flex-end;margin-top:16px"}, done)));
  const onKey = (e) => { if (e.key === "Escape" && !inline && el.isConnected) { e.preventDefault(); act("subs_close"); } };
  document.addEventListener("keydown", onKey);
  const api = {el: el, update(game) {
    g = game;
    const key = JSON.stringify([g.seats, out]);
    if (key !== list.dataset.key) {
      list.dataset.key = key;
      list.replaceChildren();
      let any = false;
      for (const t of ["a", "b"]) {
        if (!(t === "a" ? g.a_ind : g.b_ind)) {
          list.append(h("div", {class: "small muted"}, teamName(g, t) + " plays as a combined team, so its seats can't be substituted."));
          continue;
        }
        const row = h("div", {class: "opts"});
        g.seats[t].forEach((s, i) => {
          any = true;
          const on = out && out.team === t && out.seat === i + 1;
          row.append(h("button", {class: "opt " + (t === "a" ? "ten" : "neg") + (on ? " on" : ""), type: "button",
            style: "--oc:var(--team-" + t + ")", onclick: () => { out = {team: t, seat: i + 1}; list.dataset.key = ""; api.update(g); input.focus(); }},
            t.toUpperCase() + (i + 1) + " · " + s.label));
        });
        list.append(h("div", null, h("div", {class: "small", style: "margin-bottom:4px;color:var(--team-" + t + ")"}, teamName(g, t)), row));
      }
      if (!any) input.disabled = true;
    }
    sync();
  }, destroy() { document.removeEventListener("keydown", onKey); }};
  return api;
}

function tossupPanel(g0, ctx) {
  const t = g0.tossup, base = "tu:" + V.gid + ":" + g0.tossup;
  let cat = recall(base + ":cat") || "", val = Number(recall(base + ":val")) || 0, g = g0, subs = null;
  const catSel = h("select", {"aria-label": "Category"}, h("option", {value: ""}, "Choose a category…"), CATS.map(([k, n]) => h("option", {value: k}, n)));
  catSel.value = cat;
  catSel.addEventListener("change", () => { cat = catSel.value; store(base + ":cat", cat); paint(); catSel.blur(); });
  const setVal = (v) => { val = v; store(base + ":val", String(v)); paint(); };
  const opts = valueOpts([1, 2, 3, 4].map((v) => [v].concat(OUTCOMES[v])), setVal);
  const selLine = h("div", {class: "selline"});
  const commit = h("button", {class: "btn primary", type: "button"}, "Commit", h("span", {class: "k"}, "ENTER"));
  const noAns = h("button", {class: "btn", type: "button"}, "No answer", h("span", {class: "k"}, "P"));
  const subsBtn = h("button", {class: "btn small", type: "button", text: "Substitutions", onclick: () => actOrToast("subs_open")});
  const corrBtn = h("button", {class: "btn small", type: "button", text: "Correct Tossup " + (t - 1),
    onclick: () => confirmCorrection(t - 1, "", () => actOrToast("correct_prev"))});
  const tools = h("div", {class: "tools"}, subsBtn, corrBtn,
    h("button", {class: "btn small", type: "button", text: "End tossups", title: "End the tossup round without playing Tossup " + t, onclick: () => actOrToast("next", {end: true})}));
  const bHint = h("div", {class: "small muted"});
  const bparts = [0, 1, 2].map((i) => h("button", {class: "bpart", type: "button", onclick: () => actOrToast("bonus", {part: i})}, "Part " + (i + 1)));
  const bonus = h("div", {class: "bonus"}, h("div", {class: "row", style: "justify-content:space-between"}, h("span", {class: "eyebrow"}, "Bonus"), bHint),
    h("div", {class: "body"}, h("div", null, h("div", {class: "bparts"}, bparts))));
  const result = h("div");
  const next = h("button", {class: "btn primary big", type: "button", onclick: () => actOrToast("next")},
    "Next tossup", h("span", {class: "k"}, "ENTER"));
  const nextBar = h("div", {class: "nextbar"}, result, h("div", {class: "row"},
    h("button", {class: "btn", type: "button", text: "End tossups", onclick: () => actOrToast("next", {end: true})}), next));
  const log = h("div", {class: "log"});
  const warn = h("div", {class: "warn-msg", style: "margin-top:12px"});
  const catLabel = h("span", {class: "muted"});
  const el = h("div", null,
    h("div", {class: "qhead"}, h("div", {class: "title"}, "Tossup " + t), catLabel),
    h("div", {class: "ctl"}, h("div", {class: "lab"}, "Category"), catSel, h("div", {class: "lab"}, "Value"), opts.el, h("div", {class: "lab"}, "Player"), selLine),
    h("div", {class: "actions"}, commit, noAns), tools, bonus, nextBar, warn, log, legendEl());

  const canCommit = () => {
    const tu = g.tu;
    return !tu.ended && !tu.subs && !!(tu.committed || cat) && !!g.sel && !!val && !tu.locked[g.sel.team];
  };
  const doCommit = async () => {
    if (!canCommit()) return;
    const r = await actOrToast("commit", {category: cat, team: g.sel.team, seat: g.sel.seat, value: val});
    if (r && r.ok) { val = 0; store(base + ":val", null); paint(); }
  };
  const doNoAnswer = () => {
    if (g.tu.ended) return;
    if (!g.tu.committed && !cat) { toast("Pick the category first; a dead tossup is still recorded as heard.", "warn"); catSel.focus(); return; }
    actOrToast("no_answer", {category: cat});
  };
  commit.addEventListener("click", doCommit);
  noAns.addEventListener("click", doNoAnswer);
  const typer = seatTyper({
    users: () => inPlay(g),
    select: (team, seat) => ctx.pick(team, seat),
    digit: (d) => { const prev = val; if (d >= 1 && d <= 4) setVal(d); return prev; },
    restore: (prev) => setVal(prev || 0),
    pass: doNoAnswer,
  });

  function paint() {
    const tu = g.tu;
    if (tu.committed) { catSel.value = tu.category; cat = tu.category; }
    catSel.disabled = tu.committed || tu.ended;
    setText(catLabel, tu.committed || tu.ended ? CATNAME[tu.category] || "" : "");
    opts.paint(val);
    for (const b of opts.el.children) b.disabled = tu.ended;
    const d = selDescription(g);
    setText(selLine, tu.ended ? "—" : d || "Click a seat, or type a1, 1a or a username.");
    selLine.className = "selline" + (d ? "" : " muted");
    commit.disabled = !canCommit();
    noAns.disabled = tu.ended || tu.subs;
    show(tools, !tu.committed && !tu.ended);
    subsBtn.disabled = tu.subs;
    show(corrBtn, g.can_correct);
    const open = !!tu.answered;
    bonus.classList.toggle("open", open);
    const got = tu.bonus.filter(Boolean).length;
    setText(bHint, open ? "For " + teamName(g, tu.answered) + " · " + got + " of 3 · +" + got * 10 : "Unlocks after a power or a ten.");
    bparts.forEach((b, i) => { b.classList.toggle("on", !!tu.bonus[i]); b.disabled = !open; b.setAttribute("aria-pressed", tu.bonus[i] ? "true" : "false"); });
    show(nextBar, tu.ended);
    if (tu.ended) {
      const last = tu.log[tu.log.length - 1];
      const who = !last ? "" : g.seats[last.team][last.seat - 1].u.startsWith("!") ? "seat " + last.seat : last.name;
      setText(result, tu.answered ? teamName(g, tu.answered) + " answered (" + who + ", +" + (last.value === 1 ? 15 : 10) + ")." + (open ? " Mark the bonus, then continue." : "")
        : tu.dead ? "Dead tossup. No bonus." : "Both teams are locked out. No bonus.");
    }
    setText(warn, g.warning);
    show(warn, !!g.warning);
    log.replaceChildren(...tu.log.map((e) => h("div", null, h("span", null, e.team.toUpperCase() + e.seat + " · " + e.name),
      h("span", {class: "v" + e.value}, OUTCOMES[e.value][1] + " " + OUTCOMES[e.value][2]))));
    if (tu.subs && !subs) { subs = subsPanel(false); document.body.append(subs.el); subs.update(g); }
    else if (!tu.subs && subs) { subs.destroy(); subs.el.remove(); subs = null; }
    else if (subs) subs.update(g);
  }
  return {el: el, update(game) { g = game; paint(); },
    destroy() { if (subs) { subs.destroy(); subs.el.remove(); subs = null; } },
    clickable: (team) => !g.tu.ended && !g.tu.subs && !g.tu.locked[team],
    key(e) {
      if (g.tu.subs) return;
      if (e.key === "Enter") { e.preventDefault(); if (g.tu.ended) actOrToast("next"); else doCommit(); return; }
      if (e.key === "Escape") { e.preventDefault(); ctx.pick(null); return; }
      if (!g.tu.ended && typer(e.key)) e.preventDefault();
    }};
}

function reviewPanel(g) {
  const n = g.tossup;
  const cont = h("button", {class: "btn primary big", type: "button", text: g.lightnings > 0 ? "Continue to lightning" : "Finish game", onclick: () => actOrToast("continue")});
  const warn = h("div", {class: "warn-msg", style: "margin-top:12px"});
  const el = h("div", null, h("div", {class: "qhead"}, h("div", {class: "title"}, "Tossups complete")),
    h("p", {class: "lede"}, (n ? n + " tossup" + (n === 1 ? "" : "s") + " played." : "No tossups were played.") +
      (g.can_correct ? " Tossup " + n + " is held until you continue, so it can still be corrected." : "")),
    h("div", {class: "row", style: "margin-top:14px"},
      g.can_correct && h("button", {class: "btn", type: "button", text: "Correct Tossup " + n, onclick: () => confirmCorrection(n, "", () => actOrToast("correct_last"))}),
      h("button", {class: "btn", type: "button", text: "Resume tossups", onclick: () => actOrToast("resume")}), cont),
    warn, legendEl());
  return {el: el, update(game) { setText(warn, game.warning); show(warn, !!game.warning); }, clickable: () => false};
}

function lsubsPanel(g) {
  const subs = subsPanel(true);
  const start = h("button", {class: "btn primary big", type: "button", text: "Start lightning round", onclick: () => actOrToast("start_lightning")});
  const el = h("div", null, h("div", {class: "qhead"}, h("div", {class: "title"}, "Before the lightning round"), h("span", {class: "chip-l"}, "LIGHTNING")),
    h("p", {class: "lede"}, "Make any substitutions, then start the lightning round."), subs.el,
    h("div", {class: "nextbar"}, h("span", {class: "muted"}, "Lightning questions continue until you end the round."), start));
  return {el: el, update(game) { subs.update(game); }, destroy() { subs.destroy(); }, clickable: () => false};
}

function lightningPanel(g0, ctx) {
  const i = g0.lq.i, base = "lq:" + V.gid + ":" + i;
  let val = Number(recall(base + ":val")) || 0, g = g0;
  const setVal = (v) => { val = v; store(base + ":val", String(v)); paint(); };
  const opts = valueOpts([[1, "ten", "Correct", "+10"], [2, "neg", "Incorrect", "−10"]], setVal);
  const selLine = h("div", {class: "selline"});
  const commit = h("button", {class: "btn primary", type: "button"}, "Commit", h("span", {class: "k"}, "ENTER"));
  const noAns = h("button", {class: "btn", type: "button"}, "No answer", h("span", {class: "k"}, "P"));
  const result = h("div");
  const next = h("button", {class: "btn primary big", type: "button", onclick: () => actOrToast("lnext")},
    "Next lightning", h("span", {class: "k"}, "ENTER"));
  const end = () => confirmBox("End the lightning round?",
    (g.lq.done ? "Lightning " + i + " counts." : "Lightning " + i + " hasn't been answered, so it is dropped.") + " The game then finishes and the final stats are sent.",
    "End lightning", () => actOrToast("lnext", {end: true}));
  const nextBar = h("div", {class: "nextbar"}, result, h("div", {class: "row"}, h("button", {class: "btn", type: "button", text: "End lightning", onclick: end}), next));
  const tools = h("div", {class: "tools"}, h("button", {class: "btn small", type: "button", text: "End lightning", onclick: end}));
  const el = h("div", null,
    h("div", {class: "qhead"}, h("div", {class: "title"}, h("span", {class: "chip-l"}, "LIGHTNING " + i))),
    h("div", {class: "ctl"}, h("div", {class: "lab"}, "Answer"), opts.el, h("div", {class: "lab"}, "Player"), selLine),
    h("div", {class: "actions"}, commit, noAns), tools, nextBar);
  const canCommit = () => !g.lq.done && !!g.sel && !!val;
  const doCommit = async () => {
    if (!canCommit()) return;
    const r = await actOrToast("lcommit", {team: g.sel.team, seat: g.sel.seat, value: val});
    if (r && r.ok) { val = 0; store(base + ":val", null); paint(); }
  };
  const doNoAnswer = () => { if (!g.lq.done) actOrToast("lno_answer"); };
  commit.addEventListener("click", doCommit);
  noAns.addEventListener("click", doNoAnswer);
  const typer = seatTyper({
    users: () => inPlay(g), select: (team, seat) => ctx.pick(team, seat),
    digit: (d) => { const prev = val; if (d === 1 || d === 2) setVal(d); return prev; },
    restore: (prev) => setVal(prev || 0), pass: doNoAnswer,
  });
  function paint() {
    const done = g.lq.done;
    opts.paint(val);
    for (const b of opts.el.children) b.disabled = done;
    const d = selDescription(g);
    setText(selLine, done ? "—" : d || "Click a seat, or type a1, 1a or a username.");
    selLine.className = "selline" + (d ? "" : " muted");
    commit.disabled = !canCommit();
    noAns.disabled = done;
    show(tools, !done);
    show(nextBar, done);
    if (done) setText(result, g.lq.result.text);
  }
  return {el: el, update(game) { g = game; paint(); }, clickable: () => !g.lq.done,
    key(e) {
      if (e.key === "Enter") { e.preventDefault(); if (g.lq.done) actOrToast("lnext"); else doCommit(); return; }
      if (e.key === "Escape") { e.preventDefault(); ctx.pick(null); return; }
      if (!g.lq.done && typer(e.key)) e.preventDefault();
    }};
}

function finalPanel(g) {
  const tA = h("div", {class: "v"}), tB = h("div", {class: "v"});
  const status = h("div", {class: "status-line"});
  const el = h("div", null, h("div", {class: "qhead"}, h("div", {class: "title"}, "Final score")),
    h("div", {class: "tiles"}, h("div", {class: "tile"}, tA, h("div", {class: "eyebrow"}, g.a_name)), h("div", {class: "tile"}, tB, h("div", {class: "eyebrow"}, g.b_name))),
    status,
    h("div", {class: "row", style: "margin-top:16px"}, h("button", {class: "btn primary", type: "button", text: "Back to home", onclick: () => actOrToast("goto", {screen: "home"})})));
  return {el: el, clickable: () => false, update(game) {
    setText(tA, game.score.a); setText(tB, game.score.b);
    const f = game.final || {};
    status.replaceChildren();
    if (f.flushing) status.append(h("span", {class: "spinner"}), " Sending the last stats to the server…");
    else if (f.ok) status.append(h("span", {class: "ok-msg"}, "Every stat was acknowledged by the server."));
    else status.append(h("span", {class: "err", style: "font-size:13px"}, f.left + " stat" + (f.left === 1 ? " was" : "s were") +
      " not acknowledged. They are saved in changes.json, keep retrying while the console is open, and are sent on the next launch."));
  }};
}

SCREENS.game = {mount(el) {
  const cols = {a: h("section", {class: "teamcol a"}), b: h("section", {class: "teamcol b"})};
  const heads = {a: h("h3"), b: h("h3")};
  const boxes = {a: h("div"), b: h("div")};
  cols.a.append(heads.a, boxes.a);
  cols.b.append(heads.b, boxes.b);
  const center = h("section", {class: "center"});
  const report = new Report();
  const grid = h("div", {class: "game"}, cols.a, center, cols.b);
  el.append(grid, report.el);
  let g = null, seatEls = {a: [], b: []}, seatKey = "", panel = null, panelKey = "";
  const ctx = {pick(team, seat) {
    if (!panel || !panel.clickable || (team && !panel.clickable(team))) return;
    g.sel = team ? {team: team, seat: seat} : null;
    paintSeats();
    if (panel.update) panel.update(g);
    act("select", team ? {team: team, seat: seat} : {team: null});
  }};
  function buildSeats() {
    for (const t of ["a", "b"]) {
      seatEls[t] = g.seats[t].map((s, i) => {
        const b = h("button", {class: "seat", type: "button", onclick: () => {
          if (g.sel && g.sel.team === t && g.sel.seat === i + 1) ctx.pick(null); else ctx.pick(t, i + 1);
        }}, h("span", {class: "no"}, String(i + 1)), h("span", {class: "nm", text: s.label}), h("span", {class: "key", text: t.toUpperCase() + (i + 1)}));
        b.title = s.full || s.label;
        return b;
      });
      boxes[t].replaceChildren(...seatEls[t]);
    }
  }
  function paintSeats() {
    const tu = g.phase === "tossup" ? g.tu : null;
    const marks = {};
    if (tu) for (const e of tu.log) marks[e.team + e.seat] = e.value;
    if (g.phase === "lightning" && g.lq.result && g.lq.result.team) marks[g.lq.result.team + g.lq.result.seat] = g.lq.result.value === 1 ? 2 : 3;
    for (const t of ["a", "b"]) seatEls[t].forEach((b, i) => {
      const m = marks[t + (i + 1)];
      b.classList.toggle("sel", !!(g.sel && g.sel.team === t && g.sel.seat === i + 1));
      b.classList.toggle("got", m === 1 || m === 2);
      b.classList.toggle("negged", m === 3);
      b.classList.toggle("zeroed", m === 4);
      b.disabled = !(panel && panel.clickable && panel.clickable(t));
    });
    grid.classList.toggle("idle", !["tossup", "lightning"].includes(g.phase));
  }
  return {
    update(v) {
      g = v.game;
      if (!g) return;
      setText(heads.a, g.a_name + (g.a_ind ? "" : " · combined"));
      setText(heads.b, g.b_name + (g.b_ind ? "" : " · combined"));
      const key = JSON.stringify([g.seats.a, g.seats.b]);
      if (key !== seatKey) { seatKey = key; buildSeats(); }
      const pk = g.phase + ":" + (g.phase === "tossup" ? g.tossup : g.phase === "lightning" ? g.lq.i : g.phase === "review" ? g.tossup : "");
      if (pk !== panelKey) {
        if (panel && panel.destroy) panel.destroy();
        panelKey = pk;
        const make = {tossup: tossupPanel, review: reviewPanel, lsubs: lsubsPanel, lightning: lightningPanel, final: finalPanel}[g.phase];
        panel = make ? make(g, ctx) : {el: h("div"), update() {}, clickable: () => false};
        panel.el.classList.add("screen", "fade");
        center.replaceChildren(panel.el);
        nextFrame(() => panel.el.classList.remove("fade"));
      }
      panel.update(g);
      paintSeats();
      report.update(g);
    },
    key(e) { if (panel && panel.key) panel.key(e); },
  };
}};
"""

PAGE_JS_REPORT = r"""
/* ---- live report, laid out like pdf.py's match report ---- */
const SEG_COLORS = ["var(--power)", "var(--ten)", "var(--neg)", "var(--none)"];
const BAND = {hi: "var(--hi)", mid: "var(--mid)", lo: "var(--lo)"};

class Bar {
  constructor() {
    this.segs = SEG_COLORS.map((c) => h("div", {class: "s", style: "background:" + c + ";flex-grow:0;flex-basis:0"}));
    this.lines = h("div");
    this.el = h("div", {class: "bar"}, this.segs, this.lines);
  }
  set(counts) {
    counts.forEach((c, i) => { this.segs[i].style.flexGrow = String(c); });
    const total = counts.reduce((a, b) => a + b, 0);
    const units = Math.round(total);
    const key = String(units);
    if (this.lines.dataset.k === key) return;
    this.lines.dataset.k = key;
    this.lines.replaceChildren();
    if (units < 2 || Math.abs(total - units) > 1e-6 || units > 80) return;
    for (let i = 1; i < units; i++) this.lines.append(h("div", {class: "dv", style: "left:" + (i / units) * 100 + "%"}));
  }
}

class PlayerTable {
  constructor(lightning) {
    this.lightning = lightning;
    this.rows = new Map();
    this.tbody = h("tbody");
    this.empty = h("tr", null, h("td", {class: "empty", colspan: lightning ? 3 : 4}, "No buzzes yet."));
    const head = lightning ? ["PLAYER", "PTS", "LIGHTNING OUTCOME DISTRIBUTION"] : ["PLAYER", "PTS", "PP20TUH", "TOSSUP OUTCOME DISTRIBUTION"];
    this.el = h("table", {class: "rt"}, h("thead", null, h("tr", null, head.map((t, i) => h("th", {class: i === 1 || (i === 2 && !lightning) ? "n" : ""}, t)))), this.tbody);
  }
  set(list) {
    const seen = new Set();
    for (const r of list) {
      let row = this.rows.get(r.name);
      if (!row) {
        row = {name: h("td", {style: "font-weight:700"}), pts: h("td", {class: "n"}), rate: this.lightning ? null : h("td", {class: "n"}), bar: new Bar()};
        row.tr = h("tr", null, row.name, row.pts, row.rate, h("td", {style: "width:45%"}, row.bar.el));
        this.rows.set(r.name, row);
      }
      seen.add(r.name);
      setText(row.name, r.name);
      setText(row.pts, r.pts);
      if (row.rate) setText(row.rate, r.rate);
      row.bar.set(r.segs);
      this.tbody.append(row.tr);
    }
    for (const [k, row] of this.rows) if (!seen.has(k)) { row.tr.remove(); this.rows.delete(k); }
    if (!list.length) this.tbody.append(this.empty); else this.empty.remove();
  }
}

class ConvTable {
  constructor(heads) {
    this.tbody = h("tbody");
    this.rows = {};
    this.el = h("table", {class: "rt alt"}, h("thead", null, h("tr", null, heads.map((t, i) => h("th", {style: i === 0 || i === heads.length - 1 ? "" : "text-align:center"}, t)))), this.tbody);
    for (const t of ["a", "b"]) {
      const cells = heads.slice(0, -1).map((_, i) => h("td", {class: i === 0 ? "" : "c", style: i === 0 ? "font-weight:700" : ""}));
      const fill = h("div", {class: "fill", style: "width:0"});
      const tr = h("tr", null, cells, h("td", {style: "width:25%"}, h("div", {class: "slider"}, fill)));
      this.rows[t] = {cells: cells, fill: fill};
      this.tbody.append(tr);
    }
  }
  set(t, values, pct, band) {
    const r = this.rows[t];
    values.forEach((v, i) => setText(r.cells[i], v));
    r.fill.style.width = pct > 0 ? "max(10px, " + pct + "%)" : "0";
    r.fill.style.background = BAND[band];
  }
}

function niceStep(range) {
  const raw = range / 5;
  const mag = Math.pow(10, Math.floor(Math.log10(Math.max(raw, 1))));
  for (const m of [1, 2, 2.5, 5, 10]) if (m * mag >= raw) return Math.max(1, m * mag);
  return 10 * mag;
}

class Chart {
  constructor() { this.el = h("div", {class: "chart"}); this.pts = null; this.raf = 0; this.meta = {}; }
  set(pts, split, na, nb) {
    const from = this.pts;
    this.meta = {split: split, na: na, nb: nb};
    this.pts = pts.map((p) => p.slice());
    cancelAnimationFrame(this.raf);
    if (!from || RM.matches || from.length > pts.length || !from.length) { this.draw(this.pts); return; }
    const last = from[from.length - 1];
    const start = this.pts.map((p, i) => i < from.length ? from[i] : [p[0], last[1], last[2]]);
    const target = this.pts, t0 = performance.now(), dur = 360;
    const step = (now) => {
      const k = Math.min(1, (now - t0) / dur), e = 1 - Math.pow(1 - k, 3);
      this.draw(target.map((p, i) => [p[0], start[i][1] + (p[1] - start[i][1]) * e, start[i][2] + (p[2] - start[i][2]) * e]));
      if (k < 1) this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  }
  draw(pts) {
    const W = 760, H = 250, L = 42, R = 14, T = 22, B = 30, split = this.meta.split;
    const maxX = Math.max(1, pts[pts.length - 1][0]);
    const as = pts.map((p) => p[1]), bs = pts.map((p) => p[2]);
    let low = Math.min(0, ...as, ...bs), high = Math.max(...as, ...bs);
    if (high - low < 1) high = low + 1;
    const pad = (high - low) * 0.08;
    const y0 = low - (low < 0 ? pad : 0), y1 = high + pad;
    const x = (v) => L + (v / maxX) * (W - L - R);
    const y = (v) => T + (1 - (v - y0) / (y1 - y0)) * (H - T - B);
    const g = svg("svg", {viewBox: "0 0 " + W + " " + H, role: "img", "aria-label": "Running score chart"});
    const step = niceStep(y1 - y0);
    for (let v = Math.ceil(y0 / step) * step; v <= y1 + 1e-9; v += step) {
      g.append(svg("line", {class: "grid", x1: L, x2: W - R, y1: y(v), y2: y(v)}), svg("text", {x: L - 6, y: y(v) + 3, "text-anchor": "end"}, Math.round(v)));
    }
    g.append(svg("line", {class: "ax", x1: L, x2: L, y1: T, y2: H - B}), svg("line", {class: "ax", x1: L, x2: W - R, y1: H - B, y2: H - B}));
    const every = maxX <= 25 ? 1 : maxX <= 50 ? 2 : 5;
    for (let t = 0; t <= maxX; t += every) {
      g.append(svg("text", {x: x(t), y: H - B + 14, "text-anchor": "middle"}, split !== null && split !== undefined && t > split ? t - split : t));
    }
    g.append(svg("text", {x: (L + W - R) / 2, y: H - 2, "text-anchor": "middle"}, "Question"));
    for (let i = 0; i + 1 < pts.length; i++) {
      const [xa, a0, b0] = pts[i], [xb, a1, b1] = pts[i + 1];
      const d0 = a0 - b0, d1 = a1 - b1;
      const quad = (P, color) => g.append(svg("path", {d: "M" + P.map((p) => x(p[0]).toFixed(1) + " " + y(p[1]).toFixed(1)).join(" L") + " Z",
        fill: color, "fill-opacity": 0.06, stroke: "none"}));
      if (d0 * d1 >= 0) quad([[xa, a0], [xb, a1], [xb, b1], [xa, b0]], d0 + d1 >= 0 ? "#1F6FEB" : "#C62828");
      else {
        const k = d0 / (d0 - d1), xc = xa + k * (xb - xa), yc = a0 + k * (a1 - a0);
        quad([[xa, a0], [xc, yc], [xa, b0]], d0 >= 0 ? "#1F6FEB" : "#C62828");
        quad([[xc, yc], [xb, a1], [xb, b1]], d1 >= 0 ? "#1F6FEB" : "#C62828");
      }
    }
    for (const [px, a, b] of pts) if (a !== b) g.append(svg("line", {x1: x(px), x2: x(px), y1: y(Math.min(a, b)), y2: y(Math.max(a, b)), stroke: "#9E9E9E", "stroke-width": 0.6, "stroke-opacity": 0.6}));
    const line = (i) => pts.map((p, j) => (j ? "L" : "M") + x(p[0]).toFixed(1) + " " + y(p[i]).toFixed(1)).join(" ");
    g.append(svg("path", {class: "la", d: line(1)}), svg("path", {class: "lb", d: line(2)}));
    if (split !== null && split !== undefined) {
      g.append(svg("line", {class: "split", x1: x(split), x2: x(split), y1: T - 8, y2: H - B}),
        svg("text", {x: x(split) - 4, y: T - 10, "text-anchor": "end"}, "Tossups"),
        svg("text", {x: x(split) + 4, y: T - 10, "text-anchor": "start"}, "Lightning"));
    }
    const bx = Math.max(130, 22 + String(this.meta.na).length * 6.4 + 22);
    const lg = svg("g", {transform: "translate(" + (L + 8) + "," + (T - 12) + ")"},
      svg("line", {x1: 0, x2: 16, y1: 0, y2: 0, class: "la"}), svg("text", {x: 22, y: 3}, this.meta.na),
      svg("line", {x1: bx, x2: bx + 16, y1: 0, y2: 0, class: "lb"}), svg("text", {x: bx + 22, y: 3}, this.meta.nb));
    g.append(lg);
    this.el.replaceChildren(g);
  }
}

class Report {
  constructor() {
    this.el = h("section", {class: "report"});
    this.tossup = {a: new PlayerTable(false), b: new PlayerTable(false)};
    this.light = {a: new PlayerTable(true), b: new PlayerTable(true)};
    this.bonus = new ConvTable(["TEAM", "ANSWERED", "HEARD", "CONVERSION", "PPB", "RATE"]);
    this.lconv = new ConvTable(["TEAM", "CORRECT", "INCORRECT", "HEARD", "CONVERSION", "RATE"]);
    this.chart = new Chart();
    this.eyes = {ta: h("div", {class: "eyebrow", style: "margin:8px 0 4px;color:var(--team-a)"}), tb: h("div", {class: "eyebrow", style: "margin:8px 0 4px;color:var(--team-b)"}),
      la: h("div", {class: "eyebrow", style: "margin:8px 0 4px;color:var(--team-a)"}), lb: h("div", {class: "eyebrow", style: "margin:8px 0 4px;color:var(--team-b)"})};
    this.n1 = h("span", {class: "sn"}); this.n2 = h("span", {class: "sn"}); this.n3 = h("span", {class: "sn"});
    this.secT = h("div", null, h("h2", {class: "sec"}, this.n1, "Tossup data"),
      h("div", {class: "two"}, h("div", null, this.eyes.ta, this.tossup.a.el), h("div", null, this.eyes.tb, this.tossup.b.el)), legendEl(),
      h("div", {class: "eyebrow", style: "margin:18px 0 4px"}, "Bonus conversion"), this.bonus.el);
    this.secL = h("div", null, h("h2", {class: "sec"}, this.n2, "Lightning data"),
      h("div", {class: "two"}, h("div", null, this.eyes.la, this.light.a.el), h("div", null, this.eyes.lb, this.light.b.el)),
      h("div", {class: "eyebrow", style: "margin:18px 0 4px"}, "Lightning conversion"), this.lconv.el);
    this.secC = h("div", null, h("h2", {class: "sec"}, this.n3, "Running score"), this.chart.el);
    this.none = h("p", {class: "empty"}, "The live report fills in as buzzes are committed.");
    this.el.append(this.none, this.secT, this.secL, this.secC);
    this.key = null;
  }
  update(g) {
    const r = g.report;
    const key = JSON.stringify([r, g.a_name, g.b_name]);
    if (key === this.key) return;
    this.key = key;
    show(this.none, !r.has_tossup && !r.has_lightning);
    show(this.secT, r.has_tossup);
    show(this.secL, r.has_lightning);
    show(this.secC, r.has_tossup || r.has_lightning);
    let n = 0;
    if (r.has_tossup) setText(this.n1, "§ " + String(++n).padStart(2, "0"));
    if (r.has_lightning) setText(this.n2, "§ " + String(++n).padStart(2, "0"));
    setText(this.n3, "§ " + String(++n).padStart(2, "0"));
    for (const e of ["ta", "la"]) setText(this.eyes[e], g.a_name);
    for (const e of ["tb", "lb"]) setText(this.eyes[e], g.b_name);
    if (r.has_tossup) {
      this.tossup.a.set(r.tossup.a); this.tossup.b.set(r.tossup.b);
      for (const t of ["a", "b"]) { const b = r.bonus[t]; this.bonus.set(t, [teamName(g, t), b.ans, b.heard, b.conv, b.ppb], b.pct, b.band); }
    }
    if (r.has_lightning) {
      this.light.a.set(r.lightning.a); this.light.b.set(r.lightning.b);
      for (const t of ["a", "b"]) { const l = r.light[t]; this.lconv.set(t, [teamName(g, t), l.correct, l.incorrect, l.heard, l.conv], l.pct, l.band); }
    }
    if (r.has_tossup || r.has_lightning) this.chart.set(r.chart, r.split, g.a_name, g.b_name);
  }
}

poll();
"""

PAGE = PAGE_HTML.replace("/*CSS*/", PAGE_CSS).replace("/*JS*/", PAGE_JS_CORE + PAGE_JS_SCREENS + PAGE_JS_SETUP + PAGE_JS_GAME + PAGE_JS_REPORT)


if __name__ == "__main__":
    main()
