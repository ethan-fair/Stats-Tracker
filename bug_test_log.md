# Bug Test Log

## Pass 3 — Date: 2026-07-31
Status: Complete — all findings below fixed and verified, except P3-10 and P3-16 (left as-is by request)

### Fixed in this pass
Every finding below is resolved and re-tested in a sandbox copy, except:
- **P3-10** (malformed one-element HIGHLIGHT payload) — left in place by request. Still a no-op.
- **P3-16** ("zero" outcome records nothing) — kept as designed by request; a dead buzz still counts only
  as tossup-heard.
Also decided: unconfirmed player registrations are retried in memory only, never written to disk (P3-2).

Verification performed after the fixes:
- P3-1: 0-tossup lightning-only game now plays to completion (was UnboundLocalError at registration).
- P3-2: with a proxy dropping the first 3 ADPLR packets, the client warned, retried from writeToDatabase,
  and the player landed in the players table on the 4th attempt.
- P3-3: `/games` now answers with a message on both the None and exception paths.
- P3-4: combined 2-seat team reports 2 lightning heard for 2 questions (was 4); individual players unchanged.
- P3-5: 40 PACKS requests grew open descriptors on players.db by 0 (was +40).
- P3-6: answering "Y" now prompts for team names; seat prompts show the real team names.
- P3-7: lightning conversion table prints the real team names.
- P3-8 / P3-20: one error message and one prompt on a bad config; changes.json preserved intact.
- P3-9 / P3-12 / P3-14: CLOSE on an unknown game replies "pass"; RWUSR replies "error"; a 3-element
  WRROW payload is rejected as "error" instead of being misparsed.
- P3-15: a stat rejected 3 times is dropped with a named warning and the other 8 queued changes survive
  to changes.json (previously the first error silently discarded the change).
- P3-17: with players.db made unreadable, PLNME and PACKS reply "error" and the server stays up.
- Full protocol fuzz of every opcode re-run: server survives, all replies as expected.
- Full scripted game (2 tossups + bonuses + 2 lightnings, individual vs combined team) replayed
  end-to-end; match report builds, and now also builds when a player row is missing.

### Reported by user after Pass 3 fixes — fixed
21. [medium][data] pdf.py — `_player_table` and `_player_table_lightning` each built their player list from
    *every* event belonging to the team, not just the events of the phase being tabulated. A player
    substituted out during the tossups still appears in the lightning table (0 pts, empty bar) despite never
    playing a lightning question; symmetrically, a player substituted in for the lightning round alone
    appeared in the tossup table, because team-level bonus events are queued for whoever is seated.
    Reproduced: in a 2-tossup / 2-lightning game with `bbb` subbed out after tossup 1, `bbb` had only
    `lit` + bonus events and no `lightning` event, yet was listed in the lightning table. Both tables now
    keep only players with at least one event of the relevant phase (a category field for tossups,
    `lightning` for lightning). Verified: lightning table lists the two players who played lightnings and
    drops the substituted-out player, the tossup table still lists all three, and a phase table with no
    qualifying players still renders.

### New finding discovered while fixing
20. [medium][crash/data] client.py — the changes.json replay was not gated on `scriptRunning`, so with a
    malformed config.ini the client tried to resend queued stats with `IP`/`PORT` undefined and died with
    `NameError: name 'IP' is not defined` — after which the original code path would have already removed
    changes.json. Reproduced before the fix. The replay is now gated on `scriptRunning`, and changes.json is
    only deleted once the queue actually drains. Colour constants are also now always defined, so the exit
    path cannot raise a second NameError on top of the first failure.

### Files reviewed
- src/client.py, src/server.py, src/gui.py, src/pdf.py, src/bot.py — full review against "Use Guide.rtf",
  plus live integration testing in an isolated sandbox copy (own players.db): scripted full game
  (2 tossups + bonuses + 2 lightnings, one individual team and one combined team), lightning-only game,
  malformed-config run of gui.py, protocol fuzzing of every server opcode, and fd-leak measurement.

### Verification of Pass 1 / Pass 2
All Pass 1 and Pass 2 items re-checked in the current source. Every one is resolved except:
- **Pass 1 / server.py item 8 ("Cursor/conn close anti-patterns; conn leak on exception") — only partly fixed.**
  WRROW and CHNME are correct now, but the PACKS handler still never calls `conn.close()` (measured: 40 PACKS
  requests → 40 leaked sqlite descriptors that are never reclaimed; PLNME, which does close, leaks none), and
  RWUSR still leaks its connection on the exception path. See P3-5 and P3-12.
- **Pass 2 item 7 ("All three report paths now reply with a friendly message") — the fix covered the three
  *player* report paths only.** The `/games` match-report path in bot.py has no `None` check and no exception
  handling at all. See P3-3.
Note: Pass 1 client.py item 5 (Stats Viewer / RWUSR crash) is resolved by removal — the Stats Viewer menu
entry no longer exists, which leaves RWUSR as dead protocol code on the server.

### New findings

#### High
1. [high][crash] client.py:139 — `packet` is only assigned inside `if tossups > 0:` (line 97), but is read
   unconditionally when building the STGME payload. Any game with **0 tossups** (a lightning-only game, which
   the guide supports) dies with `UnboundLocalError: cannot access local variable 'packet'` immediately after
   team setup, discarding all roster entry. Reproduced. A negative tossup count hits the same path (see P3-13).
2. [high][data loss + crash] client.py:288, 572, 946, 981 — the **ADPLR (add player) response is never
   checked** (`sendMessage(...)` at default `repeat=1`, return value discarded). If that single UDP packet is
   lost, the player is still added to the local roster and to the game, so stats are written under a username
   with no row in `players`. Consequences: (a) `pdf.py:216`/`pdf.py:269` do `names[p]` and raise
   `KeyError` — reproduced — so **every match report for that game crashes permanently**; (b) the player is
   rejected by `/stats` as "not an authorised username". This is the same failure mode Pass 2 fixed for STGME,
   left unfixed for ADPLR.
3. [high][crash/UX] bot.py:404-409 — `/games` calls `pdf.generate_match_report(...)` with no `None` check and
   no try/except, after `interaction.response.defer()`. `generate_match_report` returns `None` for a game it
   cannot find (`discord.File(None)` then raises) and propagates the P3-2 `KeyError`. Because the interaction
   was already deferred, Discord shows only "The application did not respond" with no reason.

#### Medium
4. [medium][data] pdf.py:243-286 — `_player_table_lightning` never collapses the per-seat duplication for
   combined (non-individual) teams. Reproduced: a 2-seat combined team reports **4 lightning heard for 2
   lightning questions** (individual players correctly report 2); a 4-player team would report 4x. The tossup
   equivalent `_player_table` does apply the `/seats` correction (lines 198-199), and `_team_block_lightning`
   does not even accept a `seats` argument. Inflates `max_tuh`, so the combined team's lightning distribution
   bar is drawn against a baseline several times too large.
5. [medium][resource] server.py:321-343 — the PACKS handler opens a sqlite connection and closes only the
   cursor. Measured: 40 PACKS requests grew the server's open descriptors on players.db from 4 to 44, with no
   reclamation; the same test against PLNME (which calls `conn.close()`) grew it by 0. The client sends PACKS
   on every packet-name entry, so a long tournament session walks toward the process fd limit.
6. [medium][UX/data] client.py:918 — `choice = input("Use team names (y or n): ")` is the only y/n prompt in
   the client that is neither lowercased nor stripped. Reproduced: answering **"Y" silently skips both team
   name prompts** and drops through to the session-name prompt. Related, same block: the team names
   themselves (lines 922-923) are never stripped or checked for empty, so pressing enter yields a session
   name of " vs. " and blank team headers in the PDF.

#### Low
7. [low][UX] pdf.py:339 — `_lightning_table` hardcodes `"Team A"` / `"Team B"` while `_bonus_table`
   immediately above it uses the real `game_data["a_name"]` / `["b_name"]`. Reproduced: an Alpha-vs-Beta game
   prints "Team A"/"Team B" in the lightning conversion table only.
8. [low][UX] gui.py:20-31 — the `has_section` check sets `running = False` but execution still falls into
   `config["CONNECTION"]["ip"]`, so a malformed config prints two different error messages and two "Press
   enter to continue" prompts before exiting. Reproduced.
9. [low][protocol] server.py:152-157 — CLOSE for an unknown or already-expired game id sends **no reply**
   (reproduced: timeout). The client then blocks for its full 2 s socket timeout on exit, and the OSError
   path at client.py:1027 reports a false "The connection to the server has failed."
10. [low][dead code] **NOT FIXED — left as-is by request.** client.py:152-155 — the per-tossup highlight loop sends `["HIGHLIGHT", "a", [num + 1, ]]`,
    a **one-element** highlight payload. Both the server (`len(h) == 2`, line 183) and gui.py (line 402)
    reject it, so the loop is a no-op that still costs one UDP round-trip per player per tossup. It also only
    ever iterates `teamA`, and `to_highlight = []` (line 152) is never used.
11. [low][UX] client.py:216 — the tossup-phase substitution prompt uses `.lower()` without `.strip()`, unlike
    the identical lightning-phase prompt at line 498; a trailing space makes `isalnum()` fail and the entry is
    rejected as "not a valid player".
12. [low][robustness] server.py:294-312 — RWUSR's bare `except: pass` sends **no reply at all** on failure
    (client waits out the timeout) and leaks its connection on that path. RWUSR is also now dead protocol code.
13. [low][validation] client.py:880-892 — tossup and lightning counts accept negative numbers (players per
    team is correctly validated as `> 0`, these are not). Negative tossups triggers P3-1; negative lightnings
    makes the post-tossup substitution phase run in a game that then plays no lightning round.
14. [low][robustness] server.py:399 — WRROW guards `len(add) < 3` and then pops three trailing elements, so
    payloads of length 3-5 are silently misparsed. Verified this cannot corrupt the DB (the mis-parsed
    date lookup falls through to "nogame"/"error"), but the guard should be `< 6`.
15. [low][data] client.py:730 — `writeToDatabase` re-queues only on `TIMEOUT` / `SVRCLS` / `nogame`. Any
    server-side `"error"` reply for WRROW (validation failure, DB hiccup) silently **discards** that stat,
    since the change was already popped off the queue.
16. [low][design] **NOT FIXED — kept as designed by request.** client.py:436 — the "zero" outcome records no `queue_change` at all. The 4-slot vector
    (power / ten / neg / heard) has no zero slot, so a dead buzz is indistinguishable from never buzzing in
    every report, even though the guide presents it as one of four distinct outcomes.
17. [low][robustness] server.py:51+ — the main loop has no top-level exception guard around opcode handling,
    and the PLNME/PACKS branches carry no try/except of their own. Fuzzing every opcode with malformed
    payloads did not crash the server, so this is not remotely triggerable today; but a locked or corrupted
    players.db in those two branches would kill the process for all connected clients.
18. [low][cosmetic] gui.py:185-257 — `Counter.update` zfills signed score strings, so during a digit-count
    change with negative scores (e.g. -5 → -15) the roll animation renders wrong digits and can drop the
    minus sign for the duration of the animation. Static analysis only.
19. [low][cosmetic] gui.py:373, 380, 390 — the scoreboard parses payloads with `msg.split("|")[1]` while the
    server correctly uses `split("|", 1)`. A player or team name containing "|" truncates the JSON, and the
    resulting decode error is swallowed by the `except Exception: pass` at line 434, silently dropping the
    update.

---

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
