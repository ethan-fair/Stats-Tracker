import socket
import sqlite3
import json
import random
import os
import time
import datetime
import zlib

os.chdir(os.path.dirname(os.path.abspath(__file__)))

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

IP = "127.0.0.1"
PORT = 9999
server_socket.bind((IP, PORT))
server_socket.settimeout(1)

print("Server open on \033[32m" + IP + ":" + str(PORT) + "\033[0m")

DB_TIMEOUT = 1.0

game_list = {}

last_cleared_date = None
last_pltme = datetime.datetime.min

SCOREBOARD_FPS = 40


def empty_scoreboard_state():
    return {
        "score": {"a": 0, "b": 0},
        "messages": {"a": [], "b": []},
        "seats": {"a": [], "b": []},
        "highlights": {"a": [], "b": []},
        "question": [0, "tossup"],
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
        active_games_last_flush = now + 5
        if reconcile:
            active_games_last_reconcile = now - ACTIVE_GAMES_RECONCILE_INTERVAL + 5
    finally:
        if conn is not None:
            conn.close()


def bump_version(item):
    item["last_active"] = time.monotonic()
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
        "score": {"a": st["score"]["a"], "b": st["score"]["b"]},
        "seats": st["seats"],
        "question": st["question"],
        "names": st["names"],
        "messages": st["messages"],
        "highlights": highlights,
    }


clear_active_games()

while True:
    try:
        current_time = time.monotonic()
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
    except OSError:
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
            server_socket.sendto(b"lists" if data == "LISTS" else b"pass", addr)
        elif code == "KPALV": #Keep a game alive while the client idles at a menu
            item = game_list.get(data)
            if item is not None:
                item["last_active"] = time.monotonic()
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "PLTME":
            last_pltme = max(datetime.datetime.now(), last_pltme + datetime.timedelta(microseconds=1))
            server_socket.sendto(last_pltme.strftime("%b %d, %Y, %I:%M:%S.%f %p").encode(), addr)
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
                for i in rows[int(data or 0):int(data or 0) + 30]:
                    if name_rows and len(json.dumps(name_rows + [dict(i)]).encode()) > 548:
                        break
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
                    score = json.loads(parts[1])
                    if isinstance(score, dict) and all(isinstance(score.get(t), (int, float)) and not isinstance(score.get(t), bool) and -10**6 < score.get(t) < 10**6 for t in "ab"):
                        item["scoreboard_state"]["score"] = score
                except Exception:
                    pass
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "STSCR": #Send seat data to scoreboards
            parts = data.split("|", 1)
            gid, _, seq = parts[0].partition(":")
            item = game_list.get(gid) if len(parts) >= 2 else None
            if item is not None:
                try:
                    payload = json.loads(parts[1])
                    state = item["scoreboard_state"]
                    seqs = item.setdefault("seqs", {})
                    if payload[0] == "NEW_PLAYERS":
                        for key, names in payload[1].items():
                            if key in ("a", "b") and isinstance(names, list) and all(isinstance(n, str) for n in names) and int(seq or 0) >= seqs.get(key, 0):
                                seqs[key] = int(seq or 0)
                                previous_names = state["seats"][key].copy()
                                state["seats"][key] = names
                                for i in range(len(state["seats"][key])):
                                    if state["seats"][key][i] not in previous_names and len(state["seats"][key][i]) != 0:
                                        state["highlights"][key].append([i + 1, time.time() + 3])
                    elif payload[0] == "HIGHLIGHT":
                        team, h = payload[1], payload[2]
                        if (team in ("a", "b") and isinstance(h, list) and len(h) == 2
                                and isinstance(h[0], int) and not isinstance(h[0], bool)
                                and isinstance(h[1], (int, float)) and not isinstance(h[1], bool) and 0 <= h[1] <= 10**9):
                            state["highlights"][team].append([h[0], time.time() + h[1] / SCOREBOARD_FPS])
                    elif payload[0] == "SET_HIGHLIGHT":
                        state["highlights"]["a"] = []
                        state["highlights"]["b"] = []
                    elif payload[0] == "QUESTION":
                        def _count(v):
                            return v if isinstance(v, int) and not isinstance(v, bool) and v >= 0 else None
                        q = _count(payload[1])
                        if q is not None and int(seq or 0) >= seqs.get("question", 0):
                            seqs["question"] = int(seq or 0)
                            phase = payload[2] if len(payload) > 2 else None
                            state["question"] = [q, phase if phase in ("tossup", "lightning") else "tossup"]
                except Exception:
                    pass
                bump_version(item)
                server_socket.sendto(b"pass", addr)
            else:
                server_socket.sendto(b"error", addr)
        elif code == "STMSG":
            parts = data.split("|", 1)
            item = game_list.get(parts[0]) if len(parts) >= 2 else None
            if item is not None:
                try:
                    payload = json.loads(parts[1])
                    team, lines = payload[0], payload[1]
                    if team in ("a", "b") and isinstance(lines, list):
                        st = item["scoreboard_state"]
                        st["messages"][team] = [[int(entry[0]), str(entry[1])] for entry in lines][-5:]
                        for entry in st["messages"][team]:
                            if entry[0] > st["msg_seq"]:
                                st["msg_seq"] = entry[0]
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
                ON CONFLICT(username) DO NOTHING
                """, (
                    data[0],
                    data[1],
                    data[2]
                ))
                c.execute("SELECT first_name, last_name FROM players WHERE username = ?", (data[0],))
                existing = c.fetchone()
                conn.commit()
                conn.close()
                server_socket.sendto(b"pass" if list(existing) == [data[1], data[2]] else ("exists|" + existing[0] + " " + existing[1]).encode(), addr)
            except Exception:
                server_socket.sendto(b"error", addr)

        elif code == "PLNUM":
            token, _, data = data.rpartition("|")
            num = next((gid for gid, item in game_list.items() if token and item.get("token") == token), None)
            if num is not None:
                server_socket.sendto(num.encode(), addr)
                continue
            num = random.randint(100000, 999999)
            while str(num) in game_list:
                num = random.randint(100000, 999999)
            game_list[str(num)] = {
                "game_id": str(num),
                "last_active": time.monotonic(),
                "session_name": data,
                "session_stats": {},
                "scoreboard_state": empty_scoreboard_state(),
                "all_games": {},
                "changes": [],
                "token": token,
                "date": None
            }
            mark_active_game(num)
            server_socket.sendto(str(num).encode(), addr)
        elif code == "PLACK":
            item = game_list.get(data.strip())
            if item is None:
                server_socket.sendto(b"nogame", addr)
                continue
            item["last_active"] = time.monotonic()
            sent_list = {}
            for i in item["all_games"].keys():
                ack_list = []
                for ack in sorted(item["all_games"][i]):
                    if ack_list and ack == ack_list[-1][1] + 1:
                        ack_list[-1][1] = ack
                    else:
                        ack_list.append([ack, ack])
                sent_list[i] = ack_list
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
                        named["date"] = data[0]
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
                c.execute("""
                INSERT INTO games (date, data)
                VALUES (?, ?)
                ON CONFLICT(date) DO NOTHING
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
                item["date"] = None
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
                    cursor.execute("SELECT * FROM packets WHERE id = ?", (data,))
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
            payload = json.loads(data)
            if (len(payload["data"]) != 6 or not isinstance(payload["id"], int) or payload["id"] < 1
                    or not isinstance(payload["game_id"], int) or not 100000 <= payload["game_id"] <= 999999
                    or payload.get("hash") != zlib.crc32(json.dumps([payload["id"], payload["data"], payload["game_id"]]).encode())):
                continue
            if str(payload["game_id"]) not in game_list:
                game_list[str(payload["game_id"])] = {"game_id": str(payload["game_id"]), "last_active": time.monotonic(), "session_name": "", "session_stats": {}, "scoreboard_state": empty_scoreboard_state(), "all_games": {}, "changes": []}
            if payload["id"] not in [c[0] for c in game_list[str(payload["game_id"])]["changes"]]:
                game_list[str(payload["game_id"])]["changes"].append([payload["id"], payload["data"]])
        elif code == "COMIT":
            conn = None
            try:
                tracked = game_list.get(data.strip())
                if tracked is None:
                    server_socket.sendto(b"nogame", addr)
                    continue
                pending = tracked["changes"]

                scalar_fields = ["bonus_ans", "bonus_heard"]
                json_array_fields = ["lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash"]

                def _is_num(x):
                    return isinstance(x, int) and not isinstance(x, bool) and x in (0, 1)

                def _is_num_list(x, n):
                    return isinstance(x, list) and len(x) == n and all(_is_num(v) for v in x) and sum(x) == 1

                by_date = {}
                rejected = []
                for entry in pending:
                    add = list(entry[1])
                    if (len(add) == 6 and (isinstance(add[0], str) and add[0] or isinstance(add[0], list) and add[0] and all(isinstance(u, str) and u for u in add[0])) and isinstance(add[3], str) and isinstance(add[4], int) and add[4] >= 1 and add[5] in ("a", "b")
                            and ((add[1] in scalar_fields and _is_num(add[2])) or (add[1] == "lightning" and _is_num_list(add[2], 3)) or (add[1] in json_array_fields and _is_num_list(add[2], 4)))):
                        by_date.setdefault(add[3], []).append((entry[0], add))
                    else:
                        rejected.append(entry)
                if not pending:
                    server_socket.sendto(b"pass", addr)
                    continue

                conn = sqlite3.connect("players.db", timeout=DB_TIMEOUT)
                conn.row_factory = sqlite3.Row
                c = conn.cursor()
                c.execute("SELECT date, data FROM games WHERE date IN (" + ",".join("?" * len(by_date)) + ")", list(by_date))
                games = {row["date"]: json.loads(row["data"]) for row in c.fetchall()}
                for date_time in by_date:
                    if date_time not in games:
                        games[date_time] = {"packet": "pass", "player_data": [], "name": "Recovered game"}
                        c.execute("INSERT OR IGNORE INTO games (date, data) VALUES (?, ?)", (date_time, "{}"))
                if rejected:
                    print(f"Rejected {len(rejected)} change(s) for game {tracked['game_id']}: {ascii(rejected)}")
                    c.execute("CREATE TABLE IF NOT EXISTS rejected_changes (game_id TEXT, change TEXT, UNIQUE (game_id, change))")
                    c.executemany("INSERT OR IGNORE INTO rejected_changes VALUES (?, ?)", [(tracked["game_id"], json.dumps(entry)) for entry in rejected])
                    for entry in rejected:
                        tracked["all_games"].setdefault(entry[1][3] if len(entry[1]) > 3 and isinstance(entry[1][3], str) else "", []).append(entry[0])
                for date_time, arr in games.items():
                    applied = arr.setdefault("applied_ids", [])
                    seen = set(applied)
                    for req_id, add in by_date[date_time]:
                        if req_id in seen:
                            continue
                        team = add.pop(-1)
                        question = add.pop(-1)
                        add.pop(-1)
                        for user in add[0] if isinstance(add[0], list) else [add[0]]:
                            arr["player_data"].append({"question_data": [user] + add[1:], "question_num": question, "team": team})
                        applied.append(req_id)
                        seen.add(req_id)
                c.executemany("UPDATE games SET data = ? WHERE date = ?", [(json.dumps(arr), date_time) for date_time, arr in games.items()])
                conn.commit()
                tracked["changes"] = []

                for date_time, arr in games.items():
                    tracked["all_games"][date_time] = arr["applied_ids"] + [i for i in tracked["all_games"].get(date_time, []) if i not in arr["applied_ids"]]
                if "date" not in tracked and len(games) == 1:
                    tracked["date"] = next(iter(games))
                    tracked["scoreboard_state"]["names"] = {"a": games[tracked["date"]].get("a_name") or "Team A", "b": games[tracked["date"]].get("b_name") or "Team B"}
                if tracked.get("date") in games:
                    arr = games[tracked["date"]]
                    name_rows = {}
                    for row in c.execute("SELECT username, first_name, last_name FROM players"):
                        name_rows[row["username"]] = row["first_name"] + " " + row["last_name"][:1] + "."
                    for i in range(len(arr["player_data"])):
                        user = arr["player_data"][i]["question_data"][0]
                        if user in name_rows:
                            arr["player_data"][i]["question_data"][0] = name_rows[user]
                    tracked["session_stats"] = {"player_data": arr["player_data"]}
                    mark_active_game(tracked["game_id"])
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
                    c.execute("SELECT username FROM players WHERE username = ? AND first_name = ? AND last_name = ?", (new_username, first_name, last_name))
                    renamed = c.fetchone() is not None and new_username != old_username
                    conn.close()
                    conn = None
                    server_socket.sendto(b"pass" if renamed else b"notfound", addr)
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
