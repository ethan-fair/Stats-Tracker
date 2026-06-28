import socket
import sqlite3
import json
import random
import os
import time
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

IP = "localhost"
PORT = 9999
server_socket.bind((IP, PORT))
server_socket.settimeout(1)

print("Server open on \033[32m" + IP + ":" + str(PORT) + "\033[0m")

game_list = {}

last_cleared_date = None


def broadcast_to_scoreboards(item, message):
    item["last_active"] = time.time()
    for a in list(item["pending_acks"]):
        item["pending_acks"][a] += 1
    unresponsive = [a for a, c in item["pending_acks"].items() if c >= 5]
    for dead in unresponsive:
        print(f"Removing unresponsive scoreboard: {dead}")
        del item["pending_acks"][dead]
    item["scoreboards"] = [s for s in item["scoreboards"] if s not in unresponsive]
    for s in item["scoreboards"]:
        server_socket.sendto(message.encode(), s)
        item["pending_acks"].setdefault(s, 0)


SCOREBOARD_FPS = 40


def empty_scoreboard_state():
    return {
        "score": {"a": 0, "b": 0},
        "messages": {"a": [], "b": []},
        "seats": {"a": [], "b": []},
        "highlights": {"a": [], "b": []},
    }


while True:
    current_time = time.time()
    to_remove = []

    for key, item in game_list.items():
        if current_time - item["last_active"] > 1800:
            to_remove.append(key)

    for key in to_remove:
        print(f"Removing inactive game: {game_list[key]['game_id']}")
        for scoreboard in game_list[key]["scoreboards"]:
            server_socket.sendto(b"CLOSED", scoreboard)
        del game_list[key]

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
        conn = sqlite3.connect("players.db")
        conn.row_factory = sqlite3.Row

        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM players")
            result = cursor.fetchall()
        except:
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
        conn.close()
        name_rows = []
        for i in rows:
            name_rows.append({"username": i["username"], "first_name": i["first_name"], "last_name": i["last_name"]})
        server_socket.sendto(json.dumps(name_rows).encode(), addr)

    elif code == "ADSCR": #add scoreboard
        if data in game_list:
            server_socket.sendto(b"pass", addr)
        else:
            server_socket.sendto(b"invalid", addr)
    elif code == "SUBCD": #Add ip to scoreboards listening
        item = game_list.get(data)
        if item is not None:
            item["last_active"] = time.time()
            if addr not in item["scoreboards"]:
                item["scoreboards"].append(addr)
                st = item["scoreboard_state"]
                server_socket.sendto(("SEAT|" + json.dumps(["NEW_PLAYERS", st["seats"]])).encode(), addr)
                now = time.time()
                for team in ("a", "b"):
                    for seat, expiry in st["highlights"][team]:
                        remaining = int((expiry - now) * SCOREBOARD_FPS)
                        if remaining > 0:
                            server_socket.sendto(("SEAT|" + json.dumps(["HIGHLIGHT", team, [seat, remaining]])).encode(), addr)
                server_socket.sendto(("SCORE|" + json.dumps(st["score"])).encode(), addr)
                for team in ("a", "b"):
                    for line in st["messages"][team]:
                        server_socket.sendto(("MESSAGE|" + json.dumps([team, line])).encode(), addr)
            item["pending_acks"].pop(addr, None)
        server_socket.sendto(b"pass", addr)
    elif code == "RMSCR": #Remove a scoreboard
        for index, item in game_list.items():
            scoreboards = item["scoreboards"]
            if any(str(s) == str(addr) for s in scoreboards):
                item["last_active"] = time.time()
                item["scoreboards"] = [s for s in scoreboards if str(s) != str(addr)]
                item["pending_acks"].pop(addr, None)
        server_socket.sendto(b"pass", addr)
    elif code == "CLOSE": #Close client link
        item = game_list.pop(data, None)
        if item is not None:
            for i in item["scoreboards"]:
                server_socket.sendto(b"CLOSED", i)
            server_socket.sendto(b"pass", addr)
    elif code == "HLSCR": #Send score data to scoreboards
        parts = data.split("|", 1)
        item = game_list.get(parts[0]) if len(parts) >= 2 else None
        if item is not None:
            try:
                item["scoreboard_state"]["score"] = json.loads(parts[1])
            except Exception:
                pass
            broadcast_to_scoreboards(item, "SCORE|" + parts[1])
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
            except Exception:
                pass
            broadcast_to_scoreboards(item, "SEAT|" + parts[1])
            server_socket.sendto(b"pass", addr)
        else:
            server_socket.sendto(b"error", addr)
    elif code == "SCRCK": #Scoreboard acknowledged score receipt
        for index, item in game_list.items():
            item["pending_acks"].pop(addr, None)
    elif code == "SDMSG":
        parts = data.split("|", 1)
        item = game_list.get(parts[0]) if len(parts) >= 2 else None
        if item is not None:
            try:
                payload = json.loads(parts[1])
                team, line = payload[0], payload[1]
                if team in ("a", "b"):
                    msgs = item["scoreboard_state"]["messages"][team]
                    msgs.append(line)
                    del msgs[:-5]
            except Exception:
                pass
            broadcast_to_scoreboards(item, "MESSAGE|" + parts[1])
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

            conn = sqlite3.connect("players.db")
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
            "game_id": num,
            "scoreboards": [],
            "pending_acks": {},
            "last_active": time.time(),
            "session_name": data,
            "game_logs": {},
            "scoreboard_state": empty_scoreboard_state()
        }
        server_socket.sendto(str(num).encode(), addr)
    elif code == "STGME":
        try:
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, KeyError, IndexError):
                server_socket.sendto(b"error", addr)
                continue

            conn = sqlite3.connect("players.db")
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
    elif code == "RWUSR":
        try:
            conn = sqlite3.connect("players.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM players")
            result = cursor.fetchall()

            rows = [dict(row) for row in result]
            conn.close()
            flag = False
            for i in rows:
                if i["username"] == data:
                    server_socket.sendto(json.dumps(i).encode(), addr)
                    flag = True
            if not flag:
                server_socket.sendto(b"error", addr)
        except:
            pass
    elif code == "RESCR":
        item = game_list.get(data.split("|")[0])
        if item is not None:
            item["scoreboard_state"] = empty_scoreboard_state()
            broadcast_to_scoreboards(item, "RESET|")
            server_socket.sendto(b"pass", addr)
        else:
            server_socket.sendto(b"error", addr)
    elif code == "PACKS":
        conn = sqlite3.connect("players.db")
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT * FROM packets")
            result = cursor.fetchall()
        except:
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
    elif code == "ADPAC":
        try:
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, KeyError, IndexError):
                server_socket.sendto(b"error", addr)
                continue

            conn = sqlite3.connect("players.db")
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
            conn = sqlite3.connect("players.db")
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
            if len(add) < 3:
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

            conn = sqlite3.connect("players.db")
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
                server_socket.sendto(b"pass", addr)
                continue

            arr["player_data"].append({"question_data": add, "question_num": question, "team": team})
            applied.append(req_id)
            c.execute("UPDATE games SET data = ? WHERE date = ?", (json.dumps(arr), date_time))

            conn.commit()
            conn.close()
            conn = None
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

            conn = sqlite3.connect("players.db")
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