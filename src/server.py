import socket
import sqlite3
import json
import random
import os
import time
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

IP = "localhost" #"127.0.0.1"
PORT = 9999
server_socket.bind((IP, PORT))
server_socket.settimeout(1)

print("Server open on \033[32m" + IP + ":" + str(PORT) + "\033[0m")

DB_TIMEOUT = 1.0

game_list = {}

last_cleared_date = None

SCOREBOARD_FPS = 40

def record_ack(game_id, req_id):
    """Remember that a row is committed, so PLACK can tell the client to retire it.

    Keyed by the client's game id rather than by the database row the stat landed
    in: one client run numbers its changes in a single ascending sequence but can
    write into several game rows -- a second game, or rows recovered from a
    previous run -- and the client needs one answer that covers all of them.
    """
    item = game_list.get(str(game_id))
    if item is None:
        return
    item["last_active"] = time.time()
    item["acks"].add(req_id)


def empty_scoreboard_state():
    return {
        "score": {"a": 0, "b": 0},
        "messages": {"a": [], "b": []},
        "seats": {"a": [], "b": []},
        "highlights": {"a": [], "b": []},
        "question": [0, 0, 0, "tossup"],   # [number, tossups, lightnings, phase]
        "names": {"a": "Team A", "b": "Team B"},
        "version": 0,
        "msg_seq": 0,
    }

ACTIVE_GAMES_FLUSH_INTERVAL = 0.5
ACTIVE_GAMES_RECONCILE_INTERVAL = 30.0

active_games_dirty = set()
active_games_last_flush = 0.0
active_games_last_reconcile = 0.0


def open_active_games_db():
    conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS active_games (
            game_id TEXT PRIMARY KEY,
            session_name TEXT NOT NULL,
            scoreboard_state TEXT NOT NULL,
            stats TEXT NOT NULL
        )
    """)
    return conn


def clear_active_games():
    conn = None
    try:
        conn = open_active_games_db()
        removed = conn.execute("DELETE FROM active_games").rowcount
        conn.commit()
        if removed > 0:
            print(f"Cleared {removed} stale game(s) left by a previous run")
    except Exception as e:
        print(f"Error clearing active games: {type(e).__name__}: {e}")
    finally:
        if conn is not None:
            conn.close()


def write_active_game(c, gid):
    item = game_list.get(gid)
    if item is None:
        c.execute("DELETE FROM active_games WHERE game_id = ?", (gid,))
        return
    c.execute("""
        INSERT INTO active_games (game_id, session_name, scoreboard_state, stats)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(game_id) DO UPDATE SET
            session_name=excluded.session_name,
            scoreboard_state=excluded.scoreboard_state,
            stats=excluded.stats
    """, (
        gid,
        item["session_name"],
        json.dumps(item["scoreboard_state"]),
        json.dumps(item["session_stats"])
    ))


def mark_active_game(game_id):
    active_games_dirty.add(str(game_id))


def flush_active_games(force=False):
    global active_games_last_flush, active_games_last_reconcile
    now = time.time()
    reconcile = now - active_games_last_reconcile >= ACTIVE_GAMES_RECONCILE_INTERVAL
    if not reconcile:
        if not active_games_dirty:
            return
        if not force and now - active_games_last_flush < ACTIVE_GAMES_FLUSH_INTERVAL:
            return
    pending = list(active_games_dirty)
    conn = None
    try:
        conn = open_active_games_db()
        c = conn.cursor()
        if reconcile:
            c.execute("SELECT game_id FROM active_games")
            for row in c.fetchall():
                if row[0] not in game_list:
                    c.execute("DELETE FROM active_games WHERE game_id = ?", (row[0],))
            for gid in game_list:
                write_active_game(c, gid)
            active_games_last_reconcile = now
        else:
            for gid in pending:
                write_active_game(c, gid)
        conn.commit()
        active_games_dirty.difference_update(pending)
        active_games_last_flush = now
    except Exception as e:
        print(f"Error writing active games: {type(e).__name__}: {e}")
    finally:
        if conn is not None:
            conn.close()


def bump_version(item):
    item["last_active"] = time.time()
    item["scoreboard_state"]["version"] += 1
    mark_active_game(item["game_id"])


def state_snapshot(st):
    now = time.time()
    highlights = {}
    for team in ("a", "b"):
        st["highlights"][team] = [h for h in st["highlights"][team] if h[1] > now]
        highlights[team] = [[h[0], int((h[1] - now) * SCOREBOARD_FPS)] for h in st["highlights"][team]]
    return {
        "version": st["version"],
        "score": st["score"],
        "seats": st["seats"],
        "question": st["question"],
        "names": st["names"],
        "messages": st["messages"],
        "highlights": highlights,
    }


clear_active_games()

while True:
    try:
        current_time = time.time()
        to_remove = []

        for key, item in game_list.items():
            if current_time - item["last_active"] > 1800:
                to_remove.append(key)

        for key in to_remove:
            print(f"Removing inactive game: {key}")
            del game_list[key]
            mark_active_game(key)
    except Exception as e:
        print(f"Error expiring inactive games: {type(e).__name__}: {e}")

    flush_active_games()

    try:
        data, addr = server_socket.recvfrom(4096)
    except socket.timeout:
        continue
    except:
        continue
    try:
        data = data.decode()
    except UnicodeDecodeError:
        continue
    code = data[:5]
    try:
        data = data[5:]
    except:
        pass
    # A failure inside any one handler must never take the server down for
    # every connected client, so the whole dispatch is guarded.
    try:
        if code == "PROBE":
            server_socket.sendto(b"pass", addr)
        elif code == "KPALV": #Keep a game alive while the client idles at a menu
            item = game_list.get(data)
            if item is not None:
                item["last_active"] = time.time()
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "PLTME":
            server_socket.sendto(datetime.datetime.now().strftime("%b %d, %Y, %I:%M:%S.%f %p").encode(), addr)
        elif code == "PLNME":
            conn = None
            try:
                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row

                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT * FROM players")
                    result = cursor.fetchall()
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e).lower():
                        raise
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS players (
                            username TEXT PRIMARY KEY,
                            first_name TEXT NOT NULL,
                            last_name TEXT NOT NULL
                        )
                    """)
                    conn.commit()

                    cursor.execute("SELECT * FROM players")
                    result = cursor.fetchall()

                rows = [dict(row) for row in result]
                name_rows = []
                for i in rows:
                    name_rows.append({"username": i["username"], "first_name": i["first_name"], "last_name": i["last_name"]})
                server_socket.sendto(json.dumps(name_rows).encode(), addr)
            except Exception:
                server_socket.sendto(b"error", addr)
            finally:
                if conn is not None:
                    conn.close()

        elif code == "ADSCR": #add scoreboard
            if data in game_list:
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"invalid", addr)
        elif code == "UPDTE":
            parts = data.split("|")
            item = game_list.get(parts[0])
            if item is None:
                server_socket.sendto(b"CLOSED", addr)
                continue
            item["last_active"] = time.time()
            st = item["scoreboard_state"]
            try:
                known = int(parts[1])
            except (IndexError, ValueError):
                known = -1
            if known == st["version"]:
                server_socket.sendto(b"nochange", addr)
            else:
                server_socket.sendto(("SNAP|" + json.dumps(state_snapshot(st))).encode(), addr)
        elif code == "CLOSE": #Close client link
            game_list.pop(data, None)
            mark_active_game(data)
            server_socket.sendto(b"pass", addr)
        elif code == "HLSCR": #Send score data to scoreboards
            parts = data.split("|", 1)
            item = game_list.get(parts[0]) if len(parts) >= 2 else None
            if item is not None:
                try:
                    item["scoreboard_state"]["score"] = json.loads(parts[1])
                except Exception:
                    pass
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "STSCR": #Send seat data to scoreboards
            parts = data.split("|", 1)
            item = game_list.get(parts[0]) if len(parts) >= 2 else None
            if item is not None:
                try:
                    payload = json.loads(parts[1])
                    state = item["scoreboard_state"]
                    if payload[0] == "NEW_PLAYERS":
                        for key, names in payload[1].items():
                            if key in ("a", "b"):
                                state["seats"][key] = names
                    elif payload[0] == "HIGHLIGHT":
                        team, h = payload[1], payload[2]
                        if (team in ("a", "b") and isinstance(h, list) and len(h) == 2
                                and isinstance(h[0], int) and not isinstance(h[0], bool)
                                and isinstance(h[1], (int, float)) and not isinstance(h[1], bool)):
                            state["highlights"][team].append([h[0], time.time() + h[1] / SCOREBOARD_FPS])
                    elif payload[0] == "SET_HIGHLIGHT":
                        state["highlights"]["a"] = []
                        state["highlights"]["b"] = []
                    elif payload[0] == "QUESTION":
                        def _count(v):
                            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
                        q = _count(payload[1])
                        if q is not None:
                            tossups = _count(payload[2]) if len(payload) > 2 else None
                            lightnings = _count(payload[3]) if len(payload) > 3 else None
                            phase = payload[4] if len(payload) > 4 else None
                            state["question"] = [
                                q,
                                tossups if tossups is not None else 0,
                                lightnings if lightnings is not None else 0,
                                phase if phase in ("tossup", "lightning") else "tossup",
                            ]
                except Exception:
                    pass
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "SDMSG":
            parts = data.split("|", 1)
            item = game_list.get(parts[0]) if len(parts) >= 2 else None
            if item is not None:
                try:
                    payload = json.loads(parts[1])
                    team, line = payload[0], payload[1]
                    if team in ("a", "b"):
                        st = item["scoreboard_state"]
                        st["msg_seq"] += 1
                        msgs = st["messages"][team]
                        msgs.append([st["msg_seq"], line])
                        del msgs[:-5]
                except Exception:
                    pass
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "ADPLR": #add a player to the database
            try:
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, KeyError, IndexError):
                    server_socket.sendto(b"error", addr)
                    continue

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS players (
                        username TEXT PRIMARY KEY,
                        first_name TEXT NOT NULL,
                        last_name TEXT NOT NULL
                    )
                """)
                c.execute("""
                INSERT INTO players (username, first_name, last_name)
                VALUES (?, ?, ?)
                ON CONFLICT(username) DO UPDATE SET
                    first_name=excluded.first_name,
                    last_name=excluded.last_name
                """, (
                    data[0],
                    data[1],
                    data[2]
                ))
                conn.commit()
                conn.close()
                server_socket.sendto(b"pass", addr)
            except Exception:
                server_socket.sendto(b"error", addr)

        elif code == "PLNUM":
            num = random.randint(100000, 999999)
            while str(num) in game_list:
                num = random.randint(100000, 999999)
            game_list[str(num)] = {
                "game_id": str(num),
                "last_active": time.time(),
                "session_name": data,
                "session_stats": {},
                "scoreboard_state": empty_scoreboard_state(),
                "acks": []
            }
            mark_active_game(num)
            server_socket.sendto(str(num).encode(), addr)
        elif code == "PLACK":
            item = game_list.get(data.strip())
            if item is None:
                server_socket.sendto(b"nogame", addr)
                continue
            item["last_active"] = time.time()
            sent_list = []
            for ack in sorted(item["acks"]):
                if sent_list and ack == sent_list[-1][1] + 1:
                    sent_list[-1][1] = ack
                else:
                    sent_list.append([ack, ack])
            server_socket.sendto(("ACKS|" + json.dumps(sent_list)).encode(), addr)
        elif code == "STGME":
            try:
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, KeyError, IndexError):
                    server_socket.sendto(b"error", addr)
                    continue

                if len(data) > 2:
                    named = game_list.get(str(data[2]))
                    if named is not None:
                        named["scoreboard_state"]["names"]["a"] = data[1].get("a_name") or "Team A"
                        named["scoreboard_state"]["names"]["b"] = data[1].get("b_name") or "Team B"
                        bump_version(named)

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS games (
                        date TEXT PRIMARY KEY,
                        data TEXT NOT NULL
                    )
                """)
                while True:
                    c.execute("SELECT 1 FROM games WHERE date = ?", (data[0],))
                    if c.fetchone() is None:
                        break
                    data[0] = datetime.datetime.fromtimestamp(datetime.datetime.strptime(data[0], "%b %d, %Y, %I:%M:%S.%f %p").timestamp() + 0.000001).strftime("%b %d, %Y, %I:%M:%S.%f %p")
                c.execute("""
                INSERT INTO games (date, data)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    data=excluded.data
                """, (
                    data[0],
                    json.dumps(data[1])
                ))
                conn.commit()
                conn.close()
                server_socket.sendto("pass".encode(), addr)
            except Exception:
                server_socket.sendto("error".encode(), addr)
        elif code == "RESCR":
            item = game_list.get(data.split("|")[0])
            if item is not None:
                old = item["scoreboard_state"]
                st = empty_scoreboard_state()
                st["msg_seq"] = old["msg_seq"]
                st["version"] = old["version"]
                item["scoreboard_state"] = st
                item["session_stats"] = {}
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "PACKS":
            conn = None
            try:
                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                try:
                    cursor.execute("SELECT * FROM packets")
                    result = cursor.fetchall()
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e).lower():
                        raise
                    cursor.execute("""
                        CREATE TABLE IF NOT EXISTS packets (
                            id TEXT PRIMARY KEY,
                            name TEXT NOT NULL,
                            date TEXT NOT NULL
                        )
                    """)
                    conn.commit()

                    cursor.execute("SELECT * FROM packets")
                    result = cursor.fetchall()

                rows = [dict(row) for row in result]
                cursor.close()
                server_socket.sendto(json.dumps(rows).encode(), addr)
            except Exception:
                server_socket.sendto(b"error", addr)
            finally:
                # Without this the handler leaks one sqlite connection per request.
                if conn is not None:
                    conn.close()
        elif code == "ADPAC":
            try:
                try:
                    data = json.loads(data)
                except (json.JSONDecodeError, KeyError, IndexError):
                    server_socket.sendto(b"error", addr)
                    continue

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                c = conn.cursor()
                c.execute("""
                    CREATE TABLE IF NOT EXISTS packets (
                        id TEXT PRIMARY KEY,
                        name TEXT NOT NULL,
                        date TEXT NOT NULL
                    )
                """)
                c.execute("""
                INSERT INTO packets (id, name, date)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    date=excluded.date
                """, (
                    data[0],
                    data[1],
                    data[2]
                ))
                conn.commit()
                conn.close()
                server_socket.sendto("pass".encode(), addr)
            except Exception:
                server_socket.sendto(b"error", addr)
        elif code == "WRPAC":
            try:
                data = json.loads(data)
                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                cursor = conn.cursor()
                cursor.execute("UPDATE packets SET date = ? WHERE id = ?", (data["date"], data["id"]))
                cursor.close()
                conn.commit()
                conn.close()
                server_socket.sendto(b"pass", addr)
            except Exception:
                server_socket.sendto(b"error", addr)
                continue
        elif code == "WRROW":
            conn = None
            try:
                payload = json.loads(data)

                req_id = payload["id"]

                add = payload["data"]
                # Exactly [username, field, value, date_time, question_num, team].
                # Anything else misparses once the trailing three are popped off.
                if len(add) != 6:
                    server_socket.sendto(b"error", addr)
                    continue

                username = add[0]
                field = add[1]
                value = add[2]
                team = add.pop(-1)
                question = add.pop(-1)
                date_time = add.pop(-1)

                scalar_fields = ["bonus_ans", "bonus_heard"]
                json_array_fields = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]

                if field not in scalar_fields and field != "lightning" and field not in json_array_fields:
                    server_socket.sendto(b"error", addr)
                    continue

                def _is_num(x):
                    return isinstance(x, (int, float)) and not isinstance(x, bool)

                def _is_num_list(x, n):
                    return isinstance(x, list) and len(x) == n and all(_is_num(v) for v in x)

                if field in scalar_fields:
                    if not _is_num(value):
                        server_socket.sendto(b"error", addr)
                        continue
                elif field == "lightning":
                    if not _is_num_list(value, 3):
                        server_socket.sendto(b"error", addr)
                        continue
                else:
                    if not _is_num_list(value, 4):
                        server_socket.sendto(b"error", addr)
                        continue

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                c.execute("SELECT data FROM games WHERE date = ?", (date_time,))
                row = c.fetchone()
                if not row:
                    conn.close()
                    conn = None
                    # The game row was never created (lost STGME). Tell the client
                    # so it re-queues the change instead of discarding it as written.
                    server_socket.sendto(b"nogame", addr)
                    continue

                arr = json.loads(row["data"])
                applied = arr.setdefault("applied_ids", [])

                if req_id in applied:
                    conn.close()
                    conn = None
                    game_list[str(payload["game_id"])]["acks"] = applied
                    server_socket.sendto(b"pass", addr)
                    continue

                arr["player_data"].append({"question_data": add, "question_num": question, "team": team})
                applied.append(req_id)
                c.execute("UPDATE games SET data = ? WHERE date = ?", (json.dumps(arr), date_time))


                try:
                    c.execute("SELECT * FROM players")
                    result = c.fetchall()
                except sqlite3.OperationalError as e:
                    if "no such table" not in str(e).lower():
                        raise
                    c.execute("""
                        CREATE TABLE IF NOT EXISTS players (
                            username TEXT PRIMARY KEY,
                            first_name TEXT NOT NULL,
                            last_name TEXT NOT NULL
                        )
                    """)
                    conn.commit()

                    c.execute("SELECT * FROM players")
                    result = c.fetchall()

                rows = [dict(row) for row in result]
                name_rows = {}
                for i in rows:
                    name_rows[i["username"]] = i["first_name"] + " " +i["last_name"][:1] + "."
                conn.commit()
                conn.close()
                conn = None

                for i in range(len(arr["player_data"])):
                    user = arr["player_data"][i]["question_data"][0]
                    if user in name_rows:
                        arr["player_data"][i]["question_data"][0] = name_rows[user]
                tracked = game_list.get(str(payload.get("game_id")))
                if tracked is not None:
                    tracked["session_stats"] = {"player_data": arr["player_data"]}
                    mark_active_game(tracked["game_id"])

                game_list[str(payload["game_id"])]["acks"] = applied
                server_socket.sendto("pass".encode(), addr)
            except Exception:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                server_socket.sendto(b"error", addr)
                continue
        elif code == "CHNME":
            conn = None
            try:
                try:
                    payload = json.loads(data)
                    old_username = payload["old_username"]
                    new_username = payload["new_username"]
                    first_name = payload["first_name"]
                    last_name = payload["last_name"]
                except (json.JSONDecodeError, KeyError, TypeError):
                    server_socket.sendto(b"error", addr)
                    continue

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()

                c.execute("SELECT username FROM players WHERE username = ?", (old_username,))
                if c.fetchone() is None:
                    conn.close()
                    conn = None
                    server_socket.sendto(b"notfound", addr)
                    continue

                if new_username != old_username:
                    c.execute("SELECT username FROM players WHERE username = ?", (new_username,))
                    if c.fetchone() is not None:
                        conn.close()
                        conn = None
                        server_socket.sendto(b"exists", addr)
                        continue

                c.execute(
                    "UPDATE players SET username = ?, first_name = ?, last_name = ? WHERE username = ?",
                    (new_username, first_name, last_name, old_username),
                )

                if new_username != old_username:
                    c.execute("""
                        CREATE TABLE IF NOT EXISTS games (
                            date TEXT PRIMARY KEY,
                            data TEXT NOT NULL
                        )
                    """)
                    c.execute("SELECT date, data FROM games")
                    for game in c.fetchall():
                        arr = json.loads(game["data"])
                        changed = False
                        for entry in arr.get("player_data", []):
                            question_data = entry.get("question_data")
                            if question_data and question_data[0] == old_username:
                                question_data[0] = new_username
                                changed = True
                        if changed:
                            c.execute("UPDATE games SET data = ? WHERE date = ?", (json.dumps(arr), game["date"]))

                conn.commit()
                conn.close()
                conn = None
                server_socket.sendto(b"pass", addr)
            except Exception:
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
                server_socket.sendto(b"error", addr)
                continue
        else:
            server_socket.sendto(b"error", addr)

    except Exception as e:
        print(f"Error handling {code} from {addr}: {type(e).__name__}: {e}")
        try:
            server_socket.sendto(b"error", addr)
        except Exception:
            pass
