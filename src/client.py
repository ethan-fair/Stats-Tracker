import os
import json
import time
import socket
import configparser
import sys
import datetime
import atexit
import signal
import threading

os.chdir(os.path.dirname(os.path.abspath(__file__)))

changes_to_send = []
change_id_counter = 0

def queue_change(data):
    global change_id_counter
    change_id_counter += 1
    changes_to_send.append({"id": change_id_counter, "data": data})

def close():
    global changes_to_send
    if changes_to_send:
        writeToDatabase()
    if changes_to_send:
        print(changes_to_send)
        with open("changes.json", "w") as f:
            json.dump(changes_to_send, f)
            changes_to_send = []

def handle_exit_signals(signum, frame):
    sys.exit(0)

atexit.register(close)

if hasattr(signal, 'SIGHUP'):
    signal.signal(signal.SIGHUP, handle_exit_signals)
signal.signal(signal.SIGTERM, handle_exit_signals)
signal.signal(signal.SIGINT, handle_exit_signals)

scriptRunning = True

config = configparser.ConfigParser()
config.read('../config.ini')

if not (config.has_section("CONNECTION") and config.has_section("FORMAT")):
    print("config.ini does not exist.")
    scriptRunning = False
    input("Press enter to continue.")

if scriptRunning:
    try:
        IP = config["CONNECTION"]["ip"]
        PORT = int(config["CONNECTION"]["port"])
        use_rich_text = config["FORMAT"]["use_rich_text"]
    except:
        print("config.ini is incorrectly formatted.")
        scriptRunning = False
        input("Press enter to continue.")


#Declaration of colors
if scriptRunning:
    if use_rich_text == "True":
        RED = "\033[31m"
        GREEN = "\033[32m"
        BLUE = "\033[1;34m"
        RESET = "\033[0m"
    else:
        RED = ""
        GREEN = ""
        BLUE = ""
        RESET = ""

def prompt_name(prompt):
    while True:
        value = input(prompt).strip()
        if value:
            return value
        print("That cannot be empty. Please enter a value.")

def seat_index(value, team):
    seat = int(value)
    if seat < 1:
        raise IndexError
    return team[seat - 1]

def questionTracker(rows, tossups, lightnings, teamA, teamB, teamAName = "Team A", teamBName = "Team B"):
    global changes_to_send
    score = {"a": 0, "b": 0}
    tossup = 0
    game_date_time = sendMessage("PLTME")
    if game_date_time == "SVRCLS" or game_date_time == "TIMEOUT":
        game_date_time = datetime.datetime.now().strftime("%b %d, %Y, %I:%M:%S.%f %p")
    do_name = False
    if tossups > 0:
        while True:
            packet = input(f"Enter {GREEN}packet name{RESET} for tossups (ex: {GREEN}IS #226A P1{RESET}) or pass: ").lower()
            if packet == "pass":
                break
            packs_response = sendMessage("PACKS")
            if packs_response in ("TIMEOUT", "SVRCLS", "error"):
                print(f"Could not reach the server to look up packets. {GREEN}Try again{RESET}.")
                continue
            try:
                previous_packets = json.loads(packs_response)
            except (json.JSONDecodeError, TypeError):
                print(f"Received an unexpected response from the server. {GREEN}Try again{RESET}.")
                continue
            ids = []
            names = {}
            flag = False
            declined = False
            for previous_packet in previous_packets:
                ids.append(previous_packet["id"])
                names[previous_packet["id"]] = previous_packet["name"]
                if previous_packet["id"] == packet:
                    confirm = input("Packet is " + GREEN + names[packet] + RESET + " and was last played " + str(abs((datetime.datetime.now().date() - datetime.datetime.strptime(previous_packet["date"], "%m/%d/%Y").date()).days)) + " days ago.\nConfirm packet (y / n): ").lower().strip()
                    flag = True
                    if confirm == "y":
                        sendMessage("WRPAC" + json.dumps({"date": datetime.date.today().strftime("%m/%d/%Y"), "id": packet}))
                    else:
                        declined = True
                    break
            if declined:
                continue
            if not flag:
                packet_name = input(f"Packet is not identified in the database.\nEnter a name for the packet (ex: {GREEN}Invitational Series #226A Packet 1{RESET}) or pass: ").strip()
                if packet_name.lower() == "pass":
                    continue
                sendMessage("ADPAC" + json.dumps([packet, packet_name, datetime.date.today().strftime("%m/%d/%Y")]))
                names[packet] = packet_name
            break
    if teamAName == "Team A" or teamBName == "Team B":
        name = input("Enter session name: ").strip()
    else:
        name = teamAName + " vs. " + teamBName
    stgme_response = sendMessage("STGME" + json.dumps([game_date_time, {"packet": packet, "player_data": [], "name": name, "a_name": teamAName, "b_name": teamBName}]), repeat=3)
    if stgme_response != "pass":
        print(RED + "Warning" + RESET + ": the server did not confirm that the game was registered. Stats will be kept locally and retried, but check the connection.")
    while tossup < tossups:
        full_name_list = {}
        name_list = {}
        all_users = []
        for player in rows:
            all_users.append(player["username"])
            full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
            name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["SET_HIGHLIGHT", []]))
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": ["" if i.startswith("!") else name_list[i] for i in teamA], "b": ["" if i.startswith("!") else name_list[i] for i in teamB]}]))
        to_highlight = []
        for num, i in enumerate(teamA):
            if not i.startswith("!"):
                sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", "a", [num + 1, ]]))
        tossup += 1
        category = ""
        while True:
            print(GREEN + "Tossup " + str(tossup) + RESET + ": ")
            print(f"Enter {GREEN}category{RESET} (number): ")
            print(f"\t{RED}1.{RESET} Literature")
            print(f"\t{RED}2.{RESET} History")
            print(f"\t{RED}3.{RESET} Science")
            print(f"\t{RED}4.{RESET} Fine Arts")
            print(f"\t{RED}5.{RESET} Geography")
            print(f"\t{RED}6.{RESET} Current Events")
            print(f"\t{RED}7.{RESET} Religion, Mythology, Politics, Social Science (RMPSS)")  
            print(f"\t{RED}8.{RESET} Trash / Pop Culture")
            print(f"\t{RED}9.{RESET} Substitutions")
            catNum = input("Selection: ").strip()
            valid = False
            try:
                catNum = int(catNum)
                if catNum > 0 and catNum <= 9:
                    valid = True
            except:
                pass
            if valid:
                match catNum:
                    case 1:
                        category = "lit"
                    case 2:
                        category = "history"
                    case 3:
                        category = "science"
                    case 4:
                        category = "fine_arts"
                    case 5:
                        category = "geography"
                    case 6:
                        category = "current_events"
                    case 7:
                        category = "rmpss"
                    case 8:
                        category = "trash"
                    case 9:
                        category = "subs"
                break
            else:
                print("That is not a valid input")
                continue
        if category == "subs":
            tossup -= 1
            while True:
                full_name_list = {}
                name_list = {}
                all_users = []
                for player in rows:
                    all_users.append(player["username"])
                    full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                    name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
                playerId = ""
                team = ""
                index = -1
                invalid_input = False
                player = input(f"{GREEN}Input{RESET} player (team & seat or player ID) to be subbed {GREEN}OUT{RESET}, or enter \"c\" to cancel: ").lower()
                if player == "c":
                    break
                if not player.isalnum():
                    invalid_input = True
                elif len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = seat_index(player[1:], teamA)
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = seat_index(player[:1], teamA)
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = seat_index(player[1:], teamB)
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = seat_index(player[:1], teamB)
                        except:
                            invalid_input = True
                    else:
                        invalid_input = True
                else:
                    if player in teamA or player in teamB:
                        playerId = player
                    else:
                        invalid_input = True  
                if invalid_input:
                    print("That is not a valid player.")
                    continue
                if playerId.isalpha():
                    confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + full_name_list[playerId] + ": ").lower().strip()
                    if confirm != "y":
                        continue
                else:
                    print("That is not a valid player.")
                    continue
                if playerId in teamA:
                    team = "a"
                    index = teamA.index(playerId)
                elif playerId in teamB:
                    team = "b"
                    index = teamB.index(playerId)
                while True:
                    id = input(f"Enter user ID to {GREEN}replace{RESET} " + full_name_list[playerId] + ": ").lower().strip()
                    if not id.isalpha():
                        print("Usernames can only contain letters.")
                        continue
                    if id in teamA or id in teamB:
                        print("That player is already in play.")
                        continue
                    elif id in all_users:
                        confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed in is " + full_name_list[id] + " (y or n): ").strip()
                        if confirm.lower() == "y":
                            if team == "a":
                                teamA[index] = id
                            elif team == "b":
                                teamB[index] = id
                            break
                        else:
                            continue
                    elif len(id) >= 3:
                        choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ").strip()
                        if choice.lower() == "y":
                            first_name = prompt_name(f"Enter the player's {GREEN}first name{RESET}: ")
                            last_name = prompt_name(f"Enter the player's {GREEN}last name{RESET}: ")
                            sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                            all_users.append(id)
                            full_name_list[id] = BLUE + first_name + " " + last_name[0] + "." + RESET
                            name_list[id] = first_name + " " + last_name[0] + "."
                            rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                            writeToDatabase()
                            break
                        else:
                            continue
                    elif len(id) < 3:
                        print("Usernames must be 3 characters or longer.")
                        continue
                    
                if team == "a":
                    teamA[index] = id
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": ["" if i.startswith("!") else name_list[i] for i in teamA]}]))
                elif team == "b":
                    teamB[index] = id
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"b": ["" if i.startswith("!") else name_list[i] for i in teamB]}]))
                print(full_name_list[playerId] + " has been replaced by " + full_name_list[id] + ".")
                sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + " -> " + name_list[id]]))
                sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [index + 1, 400]]))
        else:
            team_a_answer = False
            team_b_answer = False
            bonus = True
            while True:
                full_name_list = {}
                name_list = {}
                all_users = []
                for player in rows:
                    all_users.append(player["username"])
                    full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                    name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
                playerId = ""
                invalid_input = False
                return_with_neg_error = False
                seat_num = 0
                player = input("Player (team & seat or player ID, pass for no answer): ").lower().strip()
                if not player.isalnum():
                    invalid_input = True
                elif len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = seat_index(player[1:], teamA)
                            seat_num = int(player[1:])
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = seat_index(player[:1], teamA)
                            seat_num = int(player[:1])
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = seat_index(player[1:], teamB)
                            seat_num = int(player[1:])
                            team = "b"
                            if team_b_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = seat_index(player[:1], teamB)
                            seat_num = int(player[:1])
                            team = "b"
                            if team_b_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    else:
                        invalid_input = True
                    if not invalid_input:
                        if playerId.isalpha():
                            if input(f"{GREEN}Confirm{RESET} that the player is " + full_name_list[playerId] + " (y or n): ").lower().strip() != "y":
                                continue
                        else:
                            if input(f"{GREEN}Confirm{RESET} that the player is in seat " + str(seat_num) + " on team " + team.upper() + " (y or n): ").lower().strip() != "y":
                                continue
                elif player == "pass":
                    print("No player answered.")
                    bonus = False
                    break
                else:
                    if player in teamA:
                        playerId = player
                        team = "a"
                        seat_num = teamA.index(player) + 1
                        if team_a_answer:
                            return_with_neg_error = True
                    elif player in teamB:
                        playerId = player
                        team = "b"
                        seat_num = teamB.index(player) + 1
                        if team_b_answer:
                            return_with_neg_error = True
                    else:
                        invalid_input = True
                if invalid_input:
                    print("That is not a valid player.")
                    continue
                if return_with_neg_error:
                    print(f"A player on {BLUE}team " + team.upper() + RESET + " has already answered.")
                    continue
                while True:
                    answerType = input(f"{GREEN}Power{RESET}, {GREEN}ten{RESET}, {GREEN}neg{RESET}, or {GREEN}zero{RESET} (1, 2, 3, or 4): ").lower().strip()
                    if answerType == "power" or answerType == "1" or answerType == "15":
                        finalType = 1
                    elif answerType == "ten" or answerType == "2" or answerType == "10":
                        finalType = 2
                    elif answerType == "neg" or answerType == "3" or answerType == "-5":
                        finalType = 3
                    elif answerType == "zero" or answerType == "4" or answerType == "0":
                        finalType = 4
                    else:
                        print("That is not a valid input.")
                        continue
                    break
                if finalType == 1:
                    queue_change([playerId, category, [1, 0, 0, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] += 15
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": 15"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 10**8]]))
                elif finalType == 2:
                    queue_change([playerId, category, [0, 1, 0, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] += 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": 10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 10**8]]))
                elif finalType == 3:
                    queue_change([playerId, category, [0, 0, 1, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] -= 5
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": -5"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 200]]))
                    if playerId in teamA:
                        team_a_answer = True
                    elif playerId in teamB:
                        team_b_answer = True
                elif finalType == 4:
                    if playerId in teamA:
                        team_a_answer = True
                    elif playerId in teamB:
                        team_b_answer = True
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": 0"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 200]]))
                if team_a_answer and team_b_answer:
                    bonus = False
                    break
                if finalType == 1 or finalType == 2 or (team_a_answer and team_b_answer):
                    break
            for i, dict in enumerate(rows):
                if (dict["username"] in teamA or dict["username"] in teamB):
                    queue_change([dict["username"], category, [0, 0, 0, 1], game_date_time, tossup, "a" if dict["username"] in teamA else "b"])
            if bonus:
                for i in range(3):
                    while True:
                        print(f"{GREEN}Bonus " + str(i + 1) + RESET + f" for {GREEN}team " + team.upper() + RESET + ":")
                        choice = input(f"{GREEN}Correct{RESET} or {GREEN}incorrect{RESET}(c or i): ").lower().strip()
                        if choice == "c":
                            if team == "a":
                                for player in teamA:
                                    queue_change([player, "bonus_ans", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                                    queue_change([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            elif team == "b":
                                for player in teamB:
                                    queue_change([player, "bonus_ans", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                                    queue_change([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            score[team] += 10
                            sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                            break
                        elif choice == "i":
                            if team == "a":
                                for player in teamA:
                                    queue_change([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            elif team == "b":
                                for player in teamB:
                                    queue_change([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            break
                        else:
                            print("That is not a valid input.")
            if tossup < tossups:
                print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            elif lightnings > 0:
                print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            writeToDatabase()
            sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["SET_HIGHLIGHT", []]))
    while True:
        if lightnings == 0:
            break
        full_name_list = {}
        name_list = {}
        all_users = []
        for player in rows:
            all_users.append(player["username"])
            full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
            name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
        playerId = ""
        team = ""
        index = -1
        invalid_input = False
        player = input(f"{GREEN}Input{RESET} player (team & seat or player ID) to be subbed {GREEN}OUT{RESET}, or enter \"c\" to cancel: ").lower().strip()
        if player == "c":
            break
        if not player.isalnum():
            invalid_input = True
        elif len(player) == 2:
            if (player[:1] == "a"):
                try:
                    playerId = seat_index(player[1:], teamA)
                except:
                    invalid_input = True
            elif (player[1:] == "a"):
                try:
                    playerId = seat_index(player[:1], teamA)
                except:
                    invalid_input = True
            elif (player[:1] == "b"):
                try:
                    playerId = seat_index(player[1:], teamB)
                except:
                    invalid_input = True
            elif (player[1:] == "b"):
                try:
                    playerId = seat_index(player[:1], teamB)
                except:
                    invalid_input = True
            else:
                invalid_input = True
        else:
            if player in teamA or player in teamB:
                playerId = player
            else:
                invalid_input = True     
        if invalid_input:
            print("That is not a valid player.")
            continue
        if playerId.isalpha():
            confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + full_name_list[playerId] + ": ").lower().strip()
            if confirm != "y":
                continue
        else:
            print("That is not a valid player.")
            continue
        if confirm != "y":
            continue
        if playerId in teamA:
            team = "a"
            index = teamA.index(playerId)
        elif playerId in teamB:
            team = "b"
            index = teamB.index(playerId)
        while True:
            id = input(f"Enter user ID to {GREEN}replace{RESET} " + full_name_list[playerId] + ": ").lower().strip()
            if not id.isalpha():
                print("Usernames can only contain letters.")
                continue
            if id in teamA or id in teamB:
                print("That player is already in play.")
                continue
            if id in all_users:
                confirm = input(f"Confirm that the player is " + full_name_list[id] + " (y or n): ").strip()
                if confirm.lower() == "y":
                    if team == "a":
                        teamA[index] = id
                    elif team == "b": 
                        teamB[index] = id
                    break
                else:
                    continue
            elif len(id) >= 3:
                choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ").strip()
                if choice.lower() == "y":
                    first_name = prompt_name(f"Enter the player's {GREEN}first name{RESET}: ")
                    last_name = prompt_name(f"Enter the player's {GREEN}last name{RESET}: ")
                    sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                    if team == "a":
                        teamA[index] = id
                    elif team == "b":
                        teamB[index] = id
                    writeToDatabase()
                    all_users.append(id)
                    full_name_list[id] = BLUE + first_name + " " + last_name[0] + "." + RESET
                    name_list[id] = first_name + " " + last_name[0] + "."
                    rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                    break
                else:
                    continue
            elif len(id) < 3:
                print("Usernames must be 3 characters or longer.")
                continue
        if team == "a":
            teamA[index] = id
            sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": ["" if i.startswith("!") else name_list[i] for i in teamA]}]))
        elif team == "b":
            teamB[index] = id
            sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"b": ["" if i.startswith("!") else name_list[i] for i in teamB]}]))
        print(full_name_list[playerId] + " has been replaced by " + full_name_list[id] + ".")
        sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + " -> " + name_list[id]]))
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [index + 1, 400]]))
    writeToDatabase()
    for i in range(lightnings):
        writeToDatabase()
        full_name_list = {}
        name_list = {}
        all_users = []
        for player in rows:
            all_users.append(player["username"])
            full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
            name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["SET_HIGHLIGHT", []]))
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": ["" if i.startswith("!") else name_list[i] for i in teamA], "b": ["" if i.startswith("!") else name_list[i] for i in teamB]}]))
        print(GREEN + "Lightning " + str(i + 1) + RESET + ":")
        while True:
            full_name_list = {}
            name_list = {}
            all_users = []
            for player in rows:
                all_users.append(player["username"])
                full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
            playerId = ""
            invalid_input = False
            seat_num = 0
            player = input(f"{GREEN}Player{RESET} (team & seat or player ID): ").lower().strip()
            do_pass = False
            if not player.isalnum():
                invalid_input = True
            elif len(player) == 2:
                if (player[:1] == "a"):
                    try:
                        playerId = seat_index(player[1:], teamA)
                        seat_num = int(player[1:])
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[1:] == "a"):
                    try:
                        playerId = seat_index(player[:1], teamA)
                        seat_num = int(player[:1])
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[:1] == "b"):
                    try:
                        playerId = seat_index(player[1:], teamB)
                        seat_num = int(player[1:])
                        team = "b"
                    except:
                        invalid_input = True
                elif (player[1:] == "b"):
                    try:
                        playerId = seat_index(player[:1], teamB)
                        seat_num = int(player[:1])
                        team = "b"
                    except:
                        invalid_input = True
                else:
                    invalid_input = True
                if not invalid_input:
                    if playerId.isalpha():
                        if input(f"{GREEN}Confirm{RESET} that the player is " + full_name_list[playerId] + " (y or n): ").lower().strip() != "y":
                            continue
                    else:
                        if input(f"{GREEN}Confirm{RESET} that the player is in seat " + str(seat_num) + " on team " + team.upper() + " (y or n): ").lower().strip() != "y":
                            continue
            elif player == "pass":
                print("No player answered, going to next question.")
                do_pass = True
                break
            else:
                if player in teamA:
                    playerId = player
                    team = "a"
                    seat_num = teamA.index(player) + 1
                elif player in teamB:
                    playerId = player
                    team = "b"
                    seat_num = teamB.index(player) + 1
                else:
                    invalid_input = True
            if invalid_input:
                print("That is not a valid player.")
                continue
            break
        for dict in rows:
            if dict["username"] in teamA or dict["username"] in teamB:
                queue_change([dict["username"], "lightning", [0, 0, 1], game_date_time, i + 1, "a" if dict["username"] in teamA else "b"])
        writeToDatabase()
        if do_pass:
            writeToDatabase()
            pass
        else:
            while True:
                up_or_down = input("Correct or incorrect (c or i): ").lower().strip()
                up_or_down = "".join(up_or_down.split())
                if up_or_down == "+10" or up_or_down == "+" or up_or_down == "plus" or up_or_down == "c":
                    if team == "a":
                        score["a"] += 10
                    elif team == "b":
                        score["b"] += 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": +10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 400]]))
                    queue_change([playerId, "lightning", [1, 0, 0], game_date_time, i + 1, "a" if playerId in teamA else "b"])
                elif up_or_down == "-10" or up_or_down == "-" or up_or_down == "neg" or up_or_down == "i":
                    if team == "a":
                        score["a"] -= 10
                    elif team == "b":
                        score["b"] -= 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": -10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", team, [seat_num, 400]]))
                    queue_change([playerId, "lightning", [0, 1, 0], game_date_time, i + 1, "a" if playerId in teamA else "b"])
                else:
                    print("That is not a valid input.")
                    continue
                writeToDatabase()
                break
        writeToDatabase()
        if i < lightnings - 1:
            print("Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
            time.sleep(2)
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["SET_HIGHLIGHT", []]))
    print("Final Score: " + BLUE + str(score["a"]) + " - " + str(score["b"]) + RESET)
    time.sleep(2)

def writeToDatabase():
    global changes_to_send
    length = len(changes_to_send)
    for i in range(length):
        change = changes_to_send.pop(0)
        msg = sendMessage("WRROW" + json.dumps({"id": change["id"], "data": change["data"]}), repeat=1)
        if msg == "TIMEOUT" or msg == "SVRCLS" or msg == "nogame":
            changes_to_send.insert(0, change)
            break

    
def sendMessage(message: str, repeat = 1, timeout = 2.0):
    for i in range(repeat):
        client_socket = None
        try:
            client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            client_socket.settimeout(timeout)
            client_socket.sendto(message.encode(), (IP, PORT))
            data, addr = client_socket.recvfrom(4096)
            data = data.decode("utf-8")
            client_socket.close()
            return data
        except socket.timeout:
            pass
        except ConnectionResetError:
            return "SVRCLS"
        finally:
            if client_socket:
                client_socket.close()
    return "TIMEOUT"

def renamePlayer(rows):
    all_users = [player["username"] for player in rows]
    if not all_users:
        print("There are no players in the database to rename.")
        return

    full_name_list = {}
    for player in rows:
        full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"] + RESET

    while True:
        target = input(f"Enter the {GREEN}username{RESET} of the player to rename, or \"c\" to cancel: ").lower().strip()
        if target == "c":
            return
        if target in all_users:
            confirm = input(f"{GREEN}Confirm{RESET} that you want to rename " + full_name_list[target] + " (y or n): ").lower().strip()
            if confirm == "y":
                break
            else:
                continue
        print("That username is not in the database.")

    current = next(player for player in rows if player["username"] == target)

    while True:
        new_username = input(f"Enter the {GREEN}new username{RESET} (or press enter to keep \"" + target + "\"): ").lower().strip()
        if new_username == "":
            new_username = target
        if new_username != target and new_username in all_users:
            print("That username already exists. Choose a different one.")
            continue
        if not new_username.isalpha():
            print("Usernames can only contain letters.")
            continue
        if len(new_username) < 3:
            print("Usernames must be 3 characters or longer.")
            continue
        break

    first_name = input(f"Enter the {GREEN}new first name{RESET} (or press enter to keep \"" + current["first_name"] + "\"): ").strip()
    if first_name == "":
        first_name = current["first_name"]
    last_name = input(f"Enter the {GREEN}new last name{RESET} (or press enter to keep \"" + current["last_name"] + "\"): ").strip()
    if last_name == "":
        last_name = current["last_name"]

    response = sendMessage("CHNME" + json.dumps({
        "old_username": target,
        "new_username": new_username,
        "first_name": first_name,
        "last_name": last_name,
    }))

    if response == "pass":
        current["username"] = new_username
        current["first_name"] = first_name
        current["last_name"] = last_name
        print(BLUE + first_name + " " + last_name + RESET + " has been updated.")
    elif response == "exists":
        print("That username already exists on the server. No changes were made.")
    elif response == "notfound":
        print("That player no longer exists on the server. No changes were made.")
    else:
        print(f"Could not reach the server or an error occurred. {GREEN}Try again{RESET}.")

name_rows = []

fieldnames = ["username", "first_name", "last_name", "lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash", "lightning"]

try:
    if scriptRunning:
        data = sendMessage("PLNME")
        if data == "SVRCLS" or data == "TIMEOUT":
            print(f"Server is closed. {GREEN}Launch{RESET} the server and try again or {GREEN}change{RESET} the IP.")
            scriptRunning = False
            input(f"Press {GREEN}enter{RESET} to continue.")
        else:
            name_rows = json.loads(data)

    if scriptRunning:
        data = sendMessage("PLNUM")
        if data == "SVRCLS" or data == "TIMEOUT":
            print(f"Server is closed. {GREEN}Launch{RESET} the server and try again or {GREEN}change{RESET} the IP.")
            scriptRunning = False
            input(f"Press {GREEN}enter{RESET} to continue.")
        else:
            game_id_num = int(data)
            print("Game ID: " + GREEN + str(game_id_num) + RESET)

            def keepalive_loop():
                while True:
                    time.sleep(300)
                    try:
                        sendMessage("KPALV" + str(game_id_num), repeat=1)
                    except Exception:
                        pass
            threading.Thread(target=keepalive_loop, daemon=True).start()

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
        changes_to_send = migrated
        writeToDatabase()
        os.remove("changes.json")

    while scriptRunning:
        print("Select a command: ")
        print(f"\t{RED}1.{RESET} Start Game")
        print(f"\t{RED}2.{RESET} Rename Player")
        print(f"\t{RED}3.{RESET} Close")
        while True:
            selection = input("Selection: ").strip()
            if selection == "1":
                sendMessage("RESCR" + str(game_id_num))
                while True:
                    tossups = input(f"Enter number of {GREEN}tossups{RESET}: ").strip()
                    try:
                        tossups = int(tossups)
                        break
                    except:
                        print("That is not a valid input.")
                while True:
                    lightnings = input(f"Enter number of {GREEN}lightnings{RESET}: ").strip()
                    try:
                        lightnings = int(lightnings)
                        break
                    except:
                        print("That is not a valid input.")
                while True:
                    players = input(f"Enter number of {GREEN}players per team{RESET}: ").strip()
                    try:
                        players = int(players)
                        if players <= 0:
                            print("That is not a valid number of players.")
                            continue
                        break
                    except:
                        print("That is not a valid input.")
                teamA = [""] * players
                teamB = [""] * players
                full_name_list = {}
                name_list = {}
                all_users = []
                for player in name_rows:
                    all_users.append(player["username"])
                    full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                    name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
                name_list["!player"] = ""
                teamAName = "team A"
                teamBName = "team B"
                team_a_individual = input(f"{GREEN}Use{RESET} individual stats for team A (y or n): ").lower().strip()
                team_b_individual = input(f"{GREEN}Use{RESET} individual stats for team B (y or n): ").lower().strip()
                if team_a_individual == "y" and team_b_individual == "y":
                    choice = input(f"{GREEN}Use{RESET} team names (y or n): ")
                else:
                    choice = "y"
                if choice == "y":
                    teamAName = input(f"{GREEN}Enter{RESET} the name for team A: ")
                    teamBName = input(f"{GREEN}Enter{RESET} the name for team B: ")
                if team_a_individual == "y":
                    for i in range(players):
                        while True:
                            id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}{teamAName}{RESET}: ").lower().strip()
                            if not id.isalpha():
                                print("That is not a valid username.")
                                continue
                            if id in teamA or id in teamB:
                                print("That player is already in the game.")
                                continue
                            if id in all_users:
                                confirm = input("Confirm that the player is " + full_name_list[id] + " (y or n): ").strip()
                                if confirm.lower() == "y":
                                    teamA[i] = id
                                    break
                                else:
                                    continue
                            elif len(id) >= 3:
                                choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ").strip()
                                if choice.lower() == "y":
                                    first_name = prompt_name(f"Enter the player's {GREEN}first name{RESET}: ")
                                    last_name = prompt_name(f"Enter the player's {GREEN}last name{RESET}: ")
                                    sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                                    teamA[i] = id
                                    name_rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                                    break
                                else:
                                    continue
                            elif len(id) < 3:
                                print("Usernames must be 3 characters or longer.")
                                continue
                else:
                    teamA = ["!playerA"] * players
                    name_rows = [row for row in name_rows if row["username"] != "!playerA"]
                    name_rows += [{"username": i, "first_name": "Team", "last_name": "A"} for i in teamA]
                if team_b_individual == "y":
                    for i in range(players):
                        while True:
                            id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}{teamBName}{RESET}: ").lower().strip()
                            if not id.isalpha():
                                print("That is not a valid username.")
                                continue
                            if id in teamA or id in teamB:
                                print("That player is already in the game.")
                                continue
                            if id in all_users:
                                confirm = input("Confirm that the player is " + full_name_list[id] + " (y or n): ").strip()
                                if confirm.lower() == "y":
                                    teamB[i] = id
                                    break
                                else:
                                    continue
                            elif len(id) >= 3:
                                choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ").strip()
                                if choice.lower() == "y":
                                    first_name = prompt_name(f"Enter the player's {GREEN}first name{RESET}: ")
                                    last_name = prompt_name(f"Enter the player's {GREEN}last name{RESET}: ")
                                    sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                                    teamB[i] = id
                                    name_rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                                    break
                                else:
                                    continue
                            elif len(id) < 3:
                                print("Usernames must be 3 characters or longer.")
                                continue
                else:
                    teamB = ["!playerB"] * players
                    name_rows = [row for row in name_rows if row["username"] != "!playerB"]
                    name_rows += [{"username": i, "first_name": "Team", "last_name": "B"} for i in teamB]
                full_name_list = {}
                name_list = {}
                all_users = []
                for player in name_rows:
                    all_users.append(player["username"])
                    full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                    name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
                
                writeToDatabase()
                sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": ["" for i in range(len(teamA))] if team_a_individual != "y" else [name_list[i] for i in teamA], "b": ["" for i in range(len(teamB))] if team_b_individual != "y" else [name_list[i] for i in teamB]}]))
                questionTracker(name_rows, tossups, lightnings, teamA, teamB, teamAName = teamAName if teamAName != "team A" else "Team A", teamBName = teamBName if teamBName != "team B" else "Team B")
                input(f"Press {GREEN}enter{RESET} to continue.")
                break

            elif selection == "2":
                renamePlayer(name_rows)
                input(f"Press {GREEN}enter{RESET} to continue.")
                break

            elif selection == "3":
                scriptRunning = False
                break
            else:
                print("That is not a valid input.")

    close()
    try:
        sendMessage("CLOSE" + str(game_id_num), repeat=1)
    except:
        pass
except OSError:
    close()
    try:
        if sendMessage("CLOSE" + str(game_id_num), repeat=1) != "pass":
            input(f"The connection to the server has failed.\nPress {GREEN}enter{RESET} to continue.")
    except:
        input(f"The connection to the server has failed.\nPress {GREEN}enter{RESET} to continue.")
"""except Exception as e:
    close()
    try:
        sendMessage("CLOSE" + str(game_id_num), repeat=1)
    except:
        pass
    input(f"An unexpected error occurred: {type(e).__name__}: {e}\nPress enter to continue.")"""

atexit.unregister(close)