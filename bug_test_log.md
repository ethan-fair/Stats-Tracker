# Bug Test Log

Date: 2026-05-21
Status: Complete

## Files reviewed
- src/client.py (901 lines) — done
- src/gui.py (475 lines) — done
- src/server.py (537 lines) — done

## Summary of critical/high bugs
See conversation output for full report. Top items:

### client.py
1. [critical] line 705 — `int(data)` after PLNUM crashes on TIMEOUT (only SVRCLS handled).
2. [critical] line 689 — `writeToDatabase()` runs before `game_id_num` is defined → NameError on changes.json replay.
3. [critical] line 900 — `sendMessage("CLOSE" + str(game_id_num))` in outer except raises NameError if exception fires before line 709.
4. [high] line 37 — `if not config:` always False; dead branch. Use return value of `config.read()`.
5. [high] line 854 — Stats Viewer crashes (AttributeError) on TIMEOUT response from RWUSR.
6. [high] lines 667-683 — `sendMessage` finally double-closes / NameError on socket failure.

### gui.py
1. [high] line 27 — Same `if not config:` bug; ConfigParser is always truthy.
2. [high] lines 27-38 — On config error, falls through into main loop with undefined IP/PORT → NameError.
3. [high] line 347 — `pygame.mixer.pre_init(buffer=1024)` called AFTER `pygame.init()` → no-op.
4. [high] lines 292-298 — SeatTracker.update prune loop uses shifting indices → wrong items removed.
5. [medium] line 341 — Bare except in listen_for_server swallows everything.
6. [medium] lines 46-66 — Socket leaks in session validation loop.

### server.py
1. [critical] line 54 — `data.decode()` raises UnicodeDecodeError on non-UTF-8 UDP packet → kills main loop.
2. [critical] lines 117-122 — RMSCR pops scoreboards by index while iterating → skip/IndexError.
3. [critical] line 131 — `num_list.remove(int(data))` crashes on malformed CLOSE or duplicate.
4. [critical] lines 485-499 — WRROW dict/list access not in try block; `add.pop(-1)` on short list crashes loop.
5. [high] lines 466-475 — WRPAC `data["date"]/data["id"]` outside try → KeyError kills loop.
6. [high] line 318 — `processed_ids[num]` never cleaned on game removal (lines 37-44, 130) → memory leak.
7. [high] lines 111-115 — SUBCD sends no reply; client retries until timeout.
8. [high] lines 472-475, 340-349 — Cursor/conn close anti-patterns; conn leak on exception.
9. [high] lines 521-533 — WRROW assumes value list length without validation.
