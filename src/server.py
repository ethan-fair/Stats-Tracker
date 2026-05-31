import socket
import sqlite3
import json
import random
import os
import time
from datetime import date
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

server_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

IP = "localhost"
PORT = 9999
server_socket.bind((IP, PORT))
server_socket.settimeout(1)

print("Server open on \033[32m" + IP + ":" + str(PORT) + "\033[0m")

num_list = []
game_list = {}

last_cleared_date = None

processed_ids = {}

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
        x = game_list[key]
        del game_list[key]
        if x["game_id"] in num_list:
            num_list.remove(x["game_id"])
        processed_ids.pop(x["game_id"], None)

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
                    last_name TEXT NOT NULL,
                    tuh INTEGER DEFAULT 0,
                    powers INTEGER DEFAULT 0,
                    tens INTEGER DEFAULT 0,
                    negs INTEGER DEFAULT 0,
                    lit TEXT NOT NULL,
                    history TEXT NOT NULL,
                    science TEXT NOT NULL,
                    fine_arts TEXT NOT NULL,
                    geography TEXT NOT NULL,
                    current_events TEXT NOT NULL,
                    rmpss TEXT NOT NULL,
                    trash TEXT NOT NULL,
                    lightning TEXT NOT NULL,
                    bonus_ans INTEGER DEFAULT 0,
                    bonus_heard INTEGER DEFAULT 0
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
        found = False
        for index, item in game_list.items():
            if str(item["game_id"]) == data:
                found = True
                server_socket.sendto(b"pass", addr)
        if not found:
            server_socket.sendto(b"invalid", addr)
    elif code == "SUBCD": #Add ip to scoreboards listening
        for index, item in game_list.items():
            if str(item["game_id"]) == data:
                item["last_active"] = time.time()
                if addr not in item["scoreboards"]:
                    item["scoreboards"].append(addr)
                item["pending_acks"].pop(addr, None)
        server_socket.sendto(b"pass", addr)
    elif code == "RMSCR": #Remove a scoreboard
        for index, item in game_list.items():
            scoreboards = item["scoreboards"]
            if any(str(s) == str(addr) for s in scoreboards):
                item["last_active"] = time.time()
                item["scoreboards"] = [s for s in scoreboards if str(s) != str(addr)]
                server_socket.sendto(b"pass", addr)
    elif code == "CLOSE": #Close client link
        to_pop = None
        for index, item in game_list.items():
            if str(item["game_id"]) == data:
                item["last_active"] = time.time()
                to_pop = index
        if to_pop is not None:
            item = game_list.pop(to_pop)
            try:
                num = int(data)
            except Exception:
                continue
            if num in num_list:
                num_list.remove(num)
                processed_ids.pop(num, None)
            for i in item["scoreboards"]:
                server_socket.sendto(b"CLOSED", i)
            server_socket.sendto(b"pass", addr)
    elif code == "HLSCR": #Send score data to scoreboards
        flag = False
        for index, item in game_list.items():
            if len(data.split("|")) >= 2:
                if str(item["game_id"]) == data.split("|")[0]:
                    flag = True
                    item["last_active"] = time.time()
                    for addr_key in list(item["pending_acks"]):
                        item["pending_acks"][addr_key] += 1

                    unresponsive = [a for a, count in item["pending_acks"].items() if count >= 5]
                    if unresponsive:
                        for dead in unresponsive:
                            print(f"Removing unresponsive scoreboard: {dead}")
                            del item["pending_acks"][dead]
                        item["scoreboards"] = [s for s in item["scoreboards"] if s not in unresponsive]

                    for i in item["scoreboards"]:
                        server_socket.sendto(("SCORE|" + data.split("|")[1]).encode(), i)
                        if i not in item["pending_acks"]:
                            item["pending_acks"][i] = 0
                    server_socket.sendto(b"pass", addr)
            else:
                break
        if not flag:
            server_socket.sendto(b"error", addr)
    elif code == "STSCR": #Send seat data to scoreboards
        flag = False
        for index, item in game_list.items():
            if len(data.split("|")) >= 2:
                if str(item["game_id"]) == data.split("|")[0]:
                    flag = True
                    item["last_active"] = time.time()
                    for addr_key in list(item["pending_acks"]):
                        item["pending_acks"][addr_key] += 1

                    unresponsive = [a for a, count in item["pending_acks"].items() if count >= 5]
                    if unresponsive:
                        for dead in unresponsive:
                            print(f"Removing unresponsive scoreboard: {dead}")
                            del item["pending_acks"][dead]
                        item["scoreboards"] = [s for s in item["scoreboards"] if s not in unresponsive]

                    for i in item["scoreboards"]:
                        server_socket.sendto(("SEAT|" + data.split("|")[1]).encode(), i)
                        if i not in item["pending_acks"]:
                            item["pending_acks"][i] = 0
                    server_socket.sendto(b"pass", addr)
            else:
                break
        if not flag:
            server_socket.sendto(b"error", addr)
    elif code == "SCRCK": #Scoreboard acknowledged score receipt
        for index, item in game_list.items():
            item["pending_acks"].pop(addr, None)
    elif code == "SDMSG":
        flag = False
        for index, item in game_list.items():
            if len(data.split("|")) >= 2:
                if str(item["game_id"]) == data.split("|")[0]:
                    flag = True
                    item["last_active"] = time.time()
                    for addr_key in list(item["pending_acks"]):
                        item["pending_acks"][addr_key] += 1

                    unresponsive = [a for a, count in item["pending_acks"].items() if count >= 5]
                    if unresponsive:
                        for dead in unresponsive:
                            print(f"Removing unresponsive scoreboard: {dead}")
                            del item["pending_acks"][dead]
                        item["scoreboards"] = [s for s in item["scoreboards"] if s not in unresponsive]

                    for i in item["scoreboards"]:
                        server_socket.sendto(("MESSAGE|" + data.split("|")[1]).encode(), i)
                        if i not in item["pending_acks"]:
                            item["pending_acks"][i] = 0
                    server_socket.sendto(b"pass", addr)
            else:
                break
        if not flag:
            server_socket.sendto(b"error", addr)
    elif code == "ADPLR": #add a player to the database
        try:
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
                        last_name TEXT NOT NULL,
                        tuh INTEGER DEFAULT 0,
                        powers INTEGER DEFAULT 0,
                        tens INTEGER DEFAULT 0,
                        negs INTEGER DEFAULT 0,
                        lit TEXT NOT NULL,
                        history TEXT NOT NULL,
                        science TEXT NOT NULL,
                        fine_arts TEXT NOT NULL,
                        geography TEXT NOT NULL,
                        current_events TEXT NOT NULL,
                        rmpss TEXT NOT NULL,
                        trash TEXT NOT NULL,
                        lightning TEXT NOT NULL,
                        bonus_ans INTEGER DEFAULT 0,
                        bonus_heard INTEGER DEFAULT 0
                    )
                """)
                conn.commit()

                cursor.execute("SELECT * FROM players")
                result = cursor.fetchall()
            
            rows = [dict(row) for row in result]

            conn.close()

            try:
                data = json.loads(data)
            except (json.JSONDecodeError, KeyError, IndexError):
                server_socket.sendto(b"error", addr)
                continue

            to_insert = {"username": data[0], "first_name": data[1], "last_name": data[2], "tuh": 0, "powers": 0, "tens": 0, "negs": 0, "lit": [0, 0, 0, 0], "history": [0, 0, 0, 0], "science": [0, 0, 0, 0], "fine_arts": [0, 0, 0, 0], "geography": [0, 0, 0, 0], "current_events": [0, 0, 0, 0], "rmpss": [0, 0, 0, 0], "trash": [0, 0, 0, 0], "lightning": [0, 0, 0], "bonus_ans": 0, "bonus_heard": 0}

            conn = sqlite3.connect("players.db")
            c = conn.cursor()
            for key, value in to_insert.items():
                if type(value) is list:
                    to_insert[key] = json.dumps(value)
            c.execute("""
            INSERT INTO players (username, first_name, last_name, tuh, powers, tens, negs, lit, history, science, fine_arts, geography, current_events, rmpss, trash, lightning, bonus_ans, bonus_heard)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(username) DO UPDATE SET
                first_name=excluded.first_name,
                last_name=excluded.last_name,
                tuh=excluded.tuh,
                powers=excluded.powers,
                tens=excluded.tens,
                negs=excluded.negs,
                lit=excluded.lit,
                history=excluded.history,
                science=excluded.science,
                fine_arts=excluded.fine_arts,
                geography=excluded.geography,
                current_events=excluded.current_events,
                rmpss=excluded.rmpss,
                trash=excluded.trash,
                lightning=excluded.lightning,
                bonus_ans=excluded.bonus_ans,
                bonus_heard=excluded.bonus_heard
            """, (
                to_insert["username"],
                to_insert["first_name"],
                to_insert["last_name"],
                to_insert["tuh"],
                to_insert["powers"],
                to_insert["tens"],
                to_insert["negs"],
                to_insert["lit"],
                to_insert["history"],
                to_insert["science"],
                to_insert["fine_arts"],
                to_insert["geography"],
                to_insert["current_events"],
                to_insert["rmpss"],
                to_insert["trash"],
                to_insert["lightning"],
                to_insert["bonus_ans"],
                to_insert["bonus_heard"]
            ))
            conn.commit()
            conn.close()
            server_socket.sendto(b"pass", addr)
        except Exception:
            server_socket.sendto(b"error", addr)
        
    elif code == "PLNUM":
        num = random.randint(100000, 999999)
        while num in num_list:
            num = random.randint(100000, 999999)
        game_list[str(addr)] = {
            "game_id": num,
            "scoreboards": [],
            "pending_acks": {},
            "last_active": time.time(),
            "session_name": data,
            "game_logs": {}
        }
        num_list.append(num)
        processed_ids[num] = set()
        server_socket.sendto(str(num).encode(), addr)
    elif code == "STGME":
        try:
            conn = sqlite3.connect("players.db")
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            try:
                cursor.execute("SELECT * FROM games")
                result = cursor.fetchall()
            except:
                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS games (
                        date TEXT PRIMARY KEY,
                        data TEXT NOT NULL
                    )
                """)
                conn.commit()

                cursor.execute("SELECT * FROM games")
                result = cursor.fetchall()

            rows = [dict(row) for row in result]
            cursor.close()
            rows = json.loads(json.dumps(rows))
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, KeyError, IndexError):
                server_socket.sendto(b"error", addr)
                continue
            rows.append({"date": data[0], "data": json.dumps(data[1])})
            conn.commit()
            conn.close()
            
            conn = sqlite3.connect("players.db")
            c = conn.cursor()
            for player in rows:
                c.execute("""
                INSERT INTO games (date, data)
                VALUES (?, ?)
                ON CONFLICT(date) DO UPDATE SET
                    data=excluded.data
                """, (
                    player["date"],
                    player["data"]
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
        flag = False
        for index, item in game_list.items():
            if str(item["game_id"]) == data.split("|")[0]:
                flag = True
                item["last_active"] = time.time()
                for addr_key in list(item["pending_acks"]):
                    item["pending_acks"][addr_key] += 1

                unresponsive = [a for a, count in item["pending_acks"].items() if count >= 5]
                if unresponsive:
                    for dead in unresponsive:
                        print(f"Removing unresponsive scoreboard: {dead}")
                        del item["pending_acks"][dead]
                    item["scoreboards"] = [s for s in item["scoreboards"] if s not in unresponsive]

                for i in item["scoreboards"]:
                    server_socket.sendto("RESET|".encode(), i)
                    if i not in item["pending_acks"]:
                        item["pending_acks"][i] = 0
                server_socket.sendto(b"pass", addr)
        if not flag:
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
            conn.close()
            try:
                data = json.loads(data)
            except (json.JSONDecodeError, KeyError, IndexError):
                server_socket.sendto(b"error", addr)
                continue
            rows.append({"id": data[0], "name": data[1], "date": data[2]})

            conn = sqlite3.connect("players.db")
            c = conn.cursor()
            for player in rows:
                c.execute("""
                INSERT INTO packets (id, name, date)
                VALUES (?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    date=excluded.date
                """, (
                    player["id"],
                    player["name"],
                    player["date"]
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

            if payload["game_id"] not in num_list:
                server_socket.sendto("error".encode(), addr)
                continue

            if req_id in processed_ids[payload["game_id"]]:
                server_socket.sendto("pass".encode(), addr)
                continue

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

            scalar_fields = ["powers", "tens", "negs", "tuh", "bonus_ans", "bonus_heard"]
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
            else:  # json_array_fields
                if not _is_num_list(value, 4):
                    server_socket.sendto(b"error", addr)
                    continue

            conn = sqlite3.connect("players.db")
            conn.row_factory = sqlite3.Row
            c = conn.cursor()

            c.execute("SELECT * FROM players WHERE username = ?", (username,))
            player_row = c.fetchone()
            if player_row is None:
                conn.close()
                conn = None
                server_socket.sendto(b"error", addr)
                continue

            c.execute("SELECT data FROM games WHERE date = ?", (date_time,))
            row = c.fetchone()
            if row:
                arr = json.loads(row["data"])
                arr["player_data"].append({"question_data": add, "question_num": question, "team": team})
                c.execute("UPDATE games SET data = ? WHERE date = ?", (json.dumps(arr), date_time))

            if field in scalar_fields:
                c.execute(f"UPDATE players SET {field} = {field} + ? WHERE username = ?", (value, username))
            elif field == "lightning":
                arr = json.loads(player_row["lightning"])
                arr[0] += value[0]
                arr[1] += value[1]
                arr[2] += value[2]
                c.execute("UPDATE players SET lightning = ? WHERE username = ?", (json.dumps(arr), username))
            else:  # json_array_fields
                arr = json.loads(player_row[field])
                arr[0] += value[0]
                arr[1] += value[1]
                arr[2] += value[2]
                arr[3] += value[3]
                c.execute(f"UPDATE players SET {field} = ? WHERE username = ?", (json.dumps(arr), username))

            conn.commit()
            conn.close()
            conn = None
            processed_ids[payload["game_id"]].add(req_id)
            server_socket.sendto("pass".encode(), addr)
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