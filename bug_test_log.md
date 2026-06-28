# Bug Test Log

## Pass 2 — Date: 2026-06-11
Status: Complete (all Pass 1 items verified fixed; new findings below)

### Files reviewed
- src/client.py, src/server.py, src/bot.py, src/pdf.py, src/gui.py — full review + live integration test (scripted game, DB verification)

### Fixed in this pass
1. [critical][data loss] client.py — STGME (game registration) response was never checked; if that one UDP packet was lost, the server had no game row and replied "pass" to every WRROW while discarding it, so the client deleted each queued change believing it was saved. An entire game's stats could vanish silently. Client now sends STGME with retries and warns if unconfirmed; server now replies "nogame" for writes to an unknown game and the client re-queues those changes (they persist in changes.json).
2. [high][data] client.py:944/979 — combined-team placeholder rows ("!playerA"/"!playerB") accumulated in name_rows across games in one session; a second combined-team game queued 2x tossup-heard markers per question, doubling the seat count pdf.py infers and halving bonus conversion / inflating TUH in reports. Old entries are now stripped before re-adding.
3. [high][data] client.py:261 — the tossup-phase substitution flow did not lowercase the replacement username (the lightning-phase flow did), so "Dave" and "dave" became two separate players and split stats. Now lowercased.
4. [medium][data/UX] client.py:121-128 — answering "n" to "Confirm packet" fell through (the `continue` bound to the for loop, not the prompt loop) and the game proceeded with the unconfirmed packet. Now re-prompts.
5. [medium][crash] client.py lightning player parse — missing `else: invalid_input = True` (present in all other parses): a 2-char garbage entry like "cc" led to a "seat 0" confirm prompt and a KeyError crash if confirmed.
6. [medium][data] client.py renamePlayer — accepted non-alphabetic usernames, which break every later isalpha()-based routing (player renders as "Combined Score" in PDFs, cannot be entered in game). Now validated.
7. [medium][crash] bot.py — a valid player with no recorded data in the selected date(s) made pdf.generate_player_report return None and discord.File(None) raised ("interaction failed"). All three report paths now reply with a friendly message.
8. [medium][crash] gui.py:344 — on bad config, "pass" at the session prompt, or connection failure, the script still started the listener thread and pygame fullscreen window with client_socket/session undefined (NameError + ghost window). Now exits cleanly.

### Operational issues — resolved in same-day follow-up
- Game expiry while idle: the server still expires games after 1800 s without activity, but the client now sends a KPALV keepalive (new protocol code) from a background thread every 5 minutes, so idling at a menu no longer kills the scoreboard link. The server refreshes last_active on KPALV.
- gui.py now sends RMSCR on shutdown (and calls pygame.quit()); the server's RMSCR handler now also clears the scoreboard's pending_acks entry and replies exactly once.
- bot.py single-date/range modals now defer the interaction before building the PDF (avoids Discord's 3-second deadline) and reply via followup.
- gui.py session-validation loop closes its socket on every path (was leaked on the invalid-session retry).
- client.py writeToDatabase re-queues a failed change at the FRONT, preserving event order.
- Dead code removed: bot.py UsernameModal; duplicate title assignment in pdf.py _header_block. Server STGME/ADPAC/ADPLR no longer read and rewrite the entire table per call — each now lazily creates its table and upserts only the new row (same protocol behavior).

---

## Pass 1 — Date: 2026-05-21
Status: Complete (all items below confirmed fixed as of Pass 2)

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
