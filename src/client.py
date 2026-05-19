import os
import json
import time
import socket
import configparser
import sys
import datetime

os.chdir(os.path.dirname(os.path.abspath(__file__)))

scriptRunning = True

config = configparser.ConfigParser()
config.read('../config.ini')

if not config:
    print("config.ini does not exist.")
    scriptRunning = False
    input("Press enter to continue.")

try:
    IP = config["CONNECTION"]["ip"]
    PORT = int(config["CONNECTION"]["port"])
    use_rich_text = config["FORMAT"]["use_rich_text"]
except:
    print("config.ini is incorrectly formatted.")
    scriptRunning = False
    input("Press enter to continue.")


#Declaration of colors
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

def questionTracker(rows, tossups, lightnings, teamA, teamB, bouncebacks):
    global changes_to_send
    score = {"a": 0, "b": 0}
    tossup = 0
    game_date_time = datetime.datetime.now().strftime("%b %d, %Y, %I:%M:%S.%f %p")
    do_name = False
    while True:
        packet = input(f"Enter {GREEN}packet name{RESET} for tossups (ex: {GREEN}IS #226A P1{RESET}) or use a session name (name): ").lower()
        if packet == "name":
            do_name = True
            break
        previous_packets = json.loads(sendMessage("PACKS"))
        ids = []
        names = {}
        flag = False
        for previous_packet in previous_packets:
            ids.append(previous_packet["id"])
            names[previous_packet["id"]] = previous_packet["name"]
            if previous_packet["id"] == packet:
                confirm = input("Packet is " + GREEN + names[packet] + RESET + " and was last played " + str(abs((datetime.datetime.now().date() - datetime.datetime.strptime(previous_packet["date"], "%m/%d/%Y").date()).days)) + " days ago.\nConfirm packet (y / n): ").lower()
                flag = True
                if confirm == "y":
                    sendMessage("WRPAC" + json.dumps({"date": datetime.date.today().strftime("%m/%d/%Y"), "id": packet}))
                else:
                    continue
                break
        if not flag:
            packet_name = input(f"Packet is not identified in the database.\nEnter a name for the packet (ex: {GREEN}Invitational Series #226A Packet 1{RESET}) or pass: ")
            if packet_name.lower() == "pass":
                continue
            sendMessage("ADPAC" + json.dumps([packet, packet_name, datetime.date.today().strftime("%m/%d/%Y")]))
            names[packet] = packet_name
        break
    if do_name:
        name = input("Enter session name: ")
    else:
        name = names[packet]
    sendMessage("STGME" + json.dumps([game_date_time, {"packet": packet, "player_data": [], "name": name}]))
    while tossup < tossups:
        full_name_list = {}
        name_list = {}
        all_users = []
        for player in rows:
            all_users.append(player["username"])
            full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
            name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["SET_HIGHLIGHT", []]))
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": [name_list[i] for i in teamA], "b": [name_list[i] for i in teamB]}]))
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
            catNum = input("Selection: ")
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
                if len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = teamA[int(player[1:]) - 1]
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = teamA[int(player[:1]) - 1]
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = teamB[int(player[1:]) - 1]
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = teamB[int(player[:1]) - 1]
                        except:
                            invalid_input = True
                else:
                    if player in teamA or player in teamB:
                        playerId = player
                    else:
                        invalid_input = True
                if invalid_input:
                    print("That is not a valid player.")
                    continue
                confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + full_name_list[playerId] + ": ").lower()
                if confirm != "y":
                    continue
                if playerId in teamA:
                    team = "a"
                    index = teamA.index(playerId)
                elif playerId in teamB:
                    team = "b"
                    index = teamB.index(playerId)
                while True:
                    id = input(f"Enter user ID to {GREEN}replace{RESET} " + full_name_list[playerId] + ": ")
                    if id in teamA or id in teamB:
                        print("That player is already in play.")
                        continue
                    if id in all_users:
                        confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed in is " + full_name_list[id] + " (y or n): ")
                        if confirm.lower() == "y":
                            if team == "a":
                                teamA[index] = id
                            elif team == "b":
                                teamB[index] = id
                            break
                        else:
                            continue
                    elif len(id) >= 3:
                        choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                        if choice.lower() == "y":
                            first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                            last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
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
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": [name_list[i] for i in teamA]}]))
                elif team == "b":
                    teamB[index] = id
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"b": [name_list[i] for i in teamB]}]))
                print(full_name_list[playerId] + " has been replaced by " + full_name_list[id] + ".") 
                sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + " -> " + name_list[id]])) 
                sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 400]]))
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
                player = input("Player (team & seat or player ID): ").lower()
                if len(player) == 2:
                    if (player[:1] == "a"):
                        try:
                            playerId = teamA[int(player[1:]) - 1]
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "a"):
                        try:
                            playerId = teamA[int(player[:1]) - 1]
                            team = "a"
                            if team_a_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[:1] == "b"):
                        try:
                            playerId = teamB[int(player[1:]) - 1]
                            team = "b"
                            if team_b_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    elif (player[1:] == "b"):
                        try:
                            playerId = teamB[int(player[:1]) - 1]
                            team = "b"
                            if team_b_answer:
                                return_with_neg_error = True
                        except:
                            invalid_input = True
                    if not invalid_input:
                        if input(f"{GREEN}Confirm{RESET} that the player is " + full_name_list[playerId] + " (y or n): ").lower() != "y":
                            continue
                elif player == "pass":
                    print("No player answered.")
                    bonus = False
                    break
                else:
                    if player in teamA:
                        playerId = player
                        team = "a"
                        if team_a_answer:
                            return_with_neg_error = True
                    elif player in teamB:
                        playerId = player
                        team = "b"
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
                    answerType = input(f"{GREEN}Power{RESET}, {GREEN}ten{RESET}, {GREEN}neg{RESET}, or {GREEN}zero{RESET} (1, 2, 3, or 4): ").lower()
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
                    changes_to_send.append([playerId, "powers", 1, game_date_time, tossup, "a" if playerId in teamA else "b"])
                    changes_to_send.append([playerId, category, [1, 0, 0, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] += 15
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": 15"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 10**6]]))
                elif finalType == 2:
                    changes_to_send.append([playerId, "tens", 1, game_date_time, tossup, "a" if playerId in teamA else "b"])
                    changes_to_send.append([playerId, category, [0, 1, 0, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] += 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": 10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 10**6]]))
                elif finalType == 3:
                    changes_to_send.append([playerId, "negs", 1, game_date_time, tossup, "a" if playerId in teamA else "b"])
                    changes_to_send.append([playerId, category, [0, 0, 1, 0], game_date_time, tossup, "a" if playerId in teamA else "b"])
                    score[team] -= 5
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": -5"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 200]]))
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
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 400]]))
                if team_a_answer and team_b_answer:
                    bonus = False
                    break
                if finalType == 1 or finalType == 2 or (team_a_answer and team_b_answer):
                    break
            for i, dict in enumerate(rows):
                if (dict["username"] in teamA or dict["username"] in teamB):
                    changes_to_send.append([dict["username"], "tuh", 1, game_date_time, tossup, "a" if dict["username"] in teamA else "b"])
                    changes_to_send.append([dict["username"], category, [0, 0, 0, 1], game_date_time, tossup, "a" if dict["username"] in teamA else "b"])
            if bonus:
                for i in range(3):
                    while True:
                        print(f"{GREEN}Bonus " + str(i + 1) + RESET + f" for {GREEN}team " + team.upper() + RESET + ":")
                        if bouncebacks:
                            choice = input(f"{GREEN}Correct{RESET}, {GREEN}incorrect{RESET}, or {GREEN}bounceback{RESET} (c, i, bb): ").lower()
                        else:
                            choice = input(f"{GREEN}Correct{RESET} or {GREEN}incorrect{RESET}(c or i): ").lower()
                        if choice == "c":
                            if team == "a":
                                for player in teamA:
                                    changes_to_send.append([player, "bonus_ans", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                                    changes_to_send.append([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            elif team == "b":
                                for player in teamB:
                                    changes_to_send.append([player, "bonus_ans", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                                    changes_to_send.append([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            score[team] += 10
                            sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                            break
                        elif choice == "bb" and bouncebacks:
                            if team == "a":
                                scoreAdd = "b"
                            elif team == "b":
                                scoreAdd = "a"
                            score[scoreAdd] += 5
                            sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                            break
                        elif choice == "i":
                            if team == "a":
                                for player in teamA:
                                    changes_to_send.append([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
                            elif team == "b":
                                for player in teamB:
                                    changes_to_send.append([player, "bonus_heard", 1, game_date_time, tossup, "a" if player in teamA else "b"])
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
        player = input(f"{GREEN}Input{RESET} player (team & seat or player ID) to be subbed {GREEN}OUT{RESET}, or enter \"c\" to cancel: ").lower()
        if player == "c":
            break
        if len(player) == 2:
            if (player[:1] == "a"):
                try:
                    playerId = teamA[int(player[1:]) - 1]
                except:
                    invalid_input = True
            elif (player[1:] == "a"):
                try:
                    playerId = teamA[int(player[:1]) - 1]
                except:
                    invalid_input = True
            elif (player[:1] == "b"):
                try:
                    playerId = teamB[int(player[1:]) - 1]
                except:
                    invalid_input = True
            elif (player[1:] == "b"):
                try:
                    playerId = teamB[int(player[:1]) - 1]
                except:
                    invalid_input = True
        else:
            if player in teamA or player in teamB:
                playerId = player
            else:
                invalid_input = True
        if invalid_input:
            print("That is not a valid player.")
            continue
        confirm = input(f"{GREEN}Confirm{RESET} that the player being subbed out is " + full_name_list[playerId] + ": ").lower()
        if confirm != "y":
            continue
        if playerId in teamA:
            team = "a"
            index = teamA.index(playerId)
        elif playerId in teamB:
            team = "b"
            index = teamB.index(playerId)
        while True:
            id = input(f"Enter user ID to {GREEN}replace{RESET} " + full_name_list[playerId] + ": ").lower()
            if id in teamA or id in teamB:
                print("That player is already in play.")
                continue
            if id in all_users:
                confirm = input(f"Confirm that the player is " + full_name_list[id] + " (y or n): ")
                if confirm.lower() == "y":
                    if team == "a":
                        teamA[index] = id
                    elif team == "b": 
                        teamB[index] = id
                    break
                else:
                    continue
            elif len(id) >= 3:
                choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                if choice.lower() == "y":
                    first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                    last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
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
            sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": [name_list[i] for i in teamA]}]))
        elif team == "b":
            teamB[index] = id
            sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"b": [name_list[i] for i in teamB]}]))
        print(full_name_list[playerId] + " has been replaced by " + full_name_list[id] + ".") 
        sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + " -> " + name_list[id]])) 
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 400]]))
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
        sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": [name_list[i] for i in teamA], "b": [name_list[i] for i in teamB]}]))
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
            player = input(f"{GREEN}Player{RESET} (team & seat or player ID): ").lower()
            do_pass = False
            if len(player) == 2:
                if (player[:1] == "a"):
                    try:
                        playerId = teamA[int(player[1:]) - 1]
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[1:] == "a"):
                    try:
                        playerId = teamA[int(player[:1]) - 1]
                        team = "a"
                    except:
                        invalid_input = True
                elif (player[:1] == "b"):
                    try:
                        playerId = teamB[int(player[1:]) - 1]
                        team = "b"
                    except:
                        invalid_input = True
                elif (player[1:] == "b"):
                    try:
                        playerId = teamB[int(player[:1]) - 1]
                        team = "b"
                    except:
                        invalid_input = True
                if not invalid_input:
                    if input(f"{GREEN}Confirm{RESET} that the player is " + full_name_list[playerId] + " (y or n): ").lower() != "y":
                        continue
            elif player == "pass":
                print("No player answered, going to next question.")
                do_pass = True
                break
            else:
                if player in teamA:
                    playerId = player
                    team = "a"
                elif player in teamB:
                    playerId = player
                    team = "b"
                else:
                    invalid_input = True
            if invalid_input:
                print("That is not a valid player.")
                continue
            break
        for dict in rows:
            if dict["username"] in teamA or dict["username"] in teamB:
                changes_to_send.append([dict["username"], "lightning", [0, 0, 1], game_date_time, i + 1, "a" if dict["username"] in teamA else "b"])
        writeToDatabase()
        if do_pass:
            writeToDatabase()
            pass
        else:
            while True:
                up_or_down = input("Correct or incorrect (c or i): ").lower()
                up_or_down = "".join(up_or_down.split())
                if up_or_down == "+10" or up_or_down == "+" or up_or_down == "plus" or up_or_down == "c":
                    if team == "a":
                        score["a"] += 10
                    elif team == "b":
                        score["b"] += 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": +10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 400]]))
                    changes_to_send.append([playerId, "lightning", [1, 0, 0], game_date_time, i + 1, "a" if playerId in teamA else "b"])
                elif up_or_down == "-10" or up_or_down == "-" or up_or_down == "neg" or up_or_down == "i":
                    if team == "a":
                        score["a"] -= 10
                    elif team == "b":
                        score["b"] -= 10
                    sendMessage("HLSCR" + str(game_id_num) + "|" + json.dumps(score))
                    sendMessage("SDMSG" + str(game_id_num) + "|" + json.dumps([team, name_list[playerId] + ": -10"]))
                    sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["HIGHLIGHT", [name_list[playerId], 400]]))
                    changes_to_send.append([playerId, "lightning", [0, 1, 0], game_date_time, i + 1, "a" if playerId in teamA else "b"])
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
    writeToDatabase()

request_counter = 0

def writeToDatabase():
    global changes_to_send, request_counter, game_id_num
    reappend = []
    length = len(changes_to_send)
    for i in range(length):
        data = changes_to_send.pop(0)
        request_counter += 1
        msg = sendMessage("WRROW" + json.dumps({"id": request_counter, "game_id": game_id_num, "data": data}), repeat=1)
        if msg == "TIMEOUT" or msg == "SVRCLS" or msg == "error":
            reappend.append(data)
    for i in reappend:
        changes_to_send.append(i)
    
def sendMessage(message: str, repeat = 5, timeout = 2.0):
    for i in range(repeat):
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
            client_socket.close()
    return "TIMEOUT"
name_rows = []
changes_to_send = []
if os.path.exists("changes.json"):
    with open("changes.json") as f:
        changes_to_send = json.load(f)
    os.remove("changes.json")
fieldnames = ["username", "first_name", "last_name", "tuh", "powers", "tens", "negs", "lit", "history", "science", "fine_arts", "geography", "current_events", "rmpss", "trash", "lightning"]

try:
    if scriptRunning:
        data = sendMessage("PLNME")
        if data == "SVRCLS":
            print(f"Server is closed. {GREEN}Launch{RESET} the server and try again or {GREEN}change{RESET} the IP.")
            scriptRunning = False
            input("Press enter to continue.")
        else:
            name_rows = json.loads(data)

    if scriptRunning:
        data = sendMessage("PLNUM")
        if data == "SVRCLS":
            print(f"Server is closed. {GREEN}Launch{RESET} the server and try again or {GREEN}change{RESET} the IP.")
            scriptRunning = False
        else:
            game_id_num = int(data)
            print("Game ID: " + GREEN + str(game_id_num) + RESET)

    while scriptRunning:
        print("Select a command: ")
        print(f"\t{RED}1.{RESET} Start Game")
        print(f"\t{RED}2.{RESET} Stats Viewer")
        print(f"\t{RED}3.{RESET} Close")
        while True:
            selection = input("Selection: ")
            if selection == "1":
                sendMessage("RESCR" + str(game_id_num))
                while True:
                    tossups = input(f"Enter number of {GREEN}tossups{RESET}: ")
                    try:
                        tossups = int(tossups)
                        break
                    except:
                        print("That is not a valid input.")
                while True:
                    lightnings = input(f"Enter number of {GREEN}lightnings{RESET}: ")
                    try:
                        lightnings = int(lightnings)
                        break
                    except:
                        print("That is not a valid input.")
                while True:
                    players = input(f"Enter number of {GREEN}players per team{RESET}: ")
                    try:
                        players = int(players)
                        if players == 0:
                            print("That is not a valid number of players.")
                            continue
                        break
                    except:
                        print("That is not a valid input.")
                while True:
                    bouncebacks = input(f"Use {GREEN}bouncebacks{RESET} (y or n): ").lower()
                    if bouncebacks == "y":
                        bouncebacks = True
                        break
                    elif bouncebacks == "n":
                        bouncebacks = False
                        break
                    else:
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
                for i in range(players):
                    while True:
                        id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}team A{RESET}: ").lower()
                        if id in teamA or id in teamB:
                            print("That player is already in the game.")
                            continue
                        if id in all_users:
                            confirm = input("Confirm that the player is " + full_name_list[id] + " (y or n): ")
                            if confirm.lower() == "y":
                                teamA[i] = id
                                break
                            else:
                                continue
                        elif len(id) >= 3:
                            choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                            if choice.lower() == "y":
                                first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                                last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
                                sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                                teamA[i] = id
                                name_rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                                break
                            else:
                                continue
                        elif len(id) < 3:
                            print("Usernames must be 3 characters or longer.")
                            continue
                for i in range(players):
                    while True:
                        id = input(f"Enter user ID for {GREEN}seat " + str(i + 1) + RESET + f" on {GREEN}team B{RESET}: ").lower()
                        if id in teamA or id in teamB:
                            print("That player is already in the game.")
                            continue
                        if id in all_users:
                            confirm = input("Confirm that the player is " + full_name_list[id] + " (y or n): ")
                            if confirm.lower() == "y":
                                teamB[i] = id
                                break
                            else:
                                continue
                        elif len(id) >= 3:
                            choice = input(f"Player not found in database. {GREEN}Add{RESET} a player with this username? (y or n): ")
                            if choice.lower() == "y":
                                first_name = input(f"Enter the player's {GREEN}first name{RESET}: ")
                                last_name = input(f"Enter the player's {GREEN}last name{RESET}: ")
                                sendMessage("ADPLR" + json.dumps([id, first_name, last_name]))
                                teamB[i] = id
                                name_rows.append({"username": id, "first_name": first_name, "last_name": last_name})
                                break
                            else:
                                continue
                        elif len(id) < 3:
                            print("Usernames must be 3 characters or longer.")
                            continue
                full_name_list = {}
                name_list = {}
                all_users = []
                for player in name_rows:
                    all_users.append(player["username"])
                    full_name_list[player["username"]] = BLUE + player["first_name"] + " " + player["last_name"][0] + "." + RESET
                    name_list[player["username"]] = player["first_name"] + " " + player["last_name"][0] + "."
                
                writeToDatabase()
                sendMessage("STSCR" + str(game_id_num) + "|" + json.dumps(["NEW_PLAYERS", {"a": [name_list[i] for i in teamA], "b": [name_list[i] for i in teamB]}]))
                questionTracker(name_rows, tossups, lightnings, teamA, teamB, bouncebacks)
                input(f"Press {GREEN}enter{RESET} to continue.")
                break
            elif selection == "2":            
                all_users = []
                full_name_list = {}
                for player in range(len(name_rows)):
                    all_users.append(name_rows[player]["username"])
                    full_name_list[name_rows[player]["username"]] = BLUE + name_rows[player]["first_name"] + " " + name_rows[player]["last_name"] + RESET
                while True:
                    id = input(f"Enter user ID to {GREEN}pull data{RESET}: ")
                    if id in all_users:
                        rows = sendMessage("RWUSR" + id)
                        if rows == "SVRCLS":
                            print(f"Server is closed. {GREEN}Launch{RESET} the server and try again or {GREEN}change{RESET} the IP.")
                            id = "pass"
                        else:
                            rows = json.loads(rows)
                        break
                    elif id.lower() == "pass":
                        id = id.lower()
                        break
                    else:
                        print("That is not a valid user ID.")
                        continue
                if not id == "pass":
                    for key in rows.keys():
                        if isinstance(rows[key], str) and key != "first_name" and key != "last_name" and key != "username":
                            rows[key] = json.loads(rows[key])
                            for item in range(len(rows[key])):
                                rows[key][item] = int(rows[key][item])
                    print_list = [
                        "Data for " + BLUE + rows["first_name"] + rows["last_name"] + RESET + ":",
                        "    " + RED + str(rows["powers"]) + "/" + str(rows["tens"]) + "/" + str(rows["negs"]) + RESET + " with " + str(rows["tuh"]) + " tossups heard." + (" (P%: " + str(round((rows["powers"]) / rows["tuh"] * 10000) / 100) + "%, Points: " + str(rows["powers"] * 15 + rows["tens"] * 10 + rows["negs"] * -5) + ")" if rows["tuh"] > 0 else ""),
                        "\t" + GREEN + "Literature" + RESET + ": " + (RED + str(round((rows["lit"][0] + rows["lit"][1]) / rows["lit"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["lit"][0] + rows["lit"][1]) + "/" + str(rows["lit"][3]) + ", P%: " + str(round((rows["lit"][0]) / rows["lit"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["lit"][2]) / rows["lit"][3] * 10000) / 100) + "%)" if rows["lit"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "History" + RESET + ": " + (RED + str(round((rows["history"][0] + rows["history"][1]) / rows["history"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["history"][0] + rows["history"][1]) + "/" + str(rows["history"][3]) + ", P%: " + str(round((rows["history"][0]) / rows["history"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["history"][2]) / rows["history"][3] * 10000) / 100) + "%)" if rows["history"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Science" + RESET + ": " + (RED + str(round((rows["science"][0] + rows["science"][1]) / rows["science"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["science"][0] + rows["science"][1]) + "/" + str(rows["science"][3]) + ", P%: " + str(round((rows["science"][0]) / rows["science"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["science"][2]) / rows["science"][3] * 10000) / 100) + "%)" if rows["science"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Fine Arts" + RESET + ": " + (RED + str(round((rows["fine_arts"][0] + rows["fine_arts"][1]) / rows["fine_arts"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["fine_arts"][0] + rows["fine_arts"][1]) + "/" + str(rows["fine_arts"][3]) + ", P%: " + str(round((rows["fine_arts"][0]) / rows["fine_arts"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["fine_arts"][2]) / rows["fine_arts"][3] * 10000) / 100) + "%)" if rows["fine_arts"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Geography" + RESET + ": " + (RED + str(round((rows["geography"][0] + rows["geography"][1]) / rows["geography"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["geography"][0] + rows["geography"][1]) + "/" + str(rows["geography"][3]) + ", P%: " + str(round((rows["geography"][0]) / rows["geography"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["geography"][2]) / rows["geography"][3] * 10000) / 100) + "%)" if rows["geography"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Current Events" + RESET + ": " + (RED + str(round((rows["current_events"][0] + rows["current_events"][1]) / rows["current_events"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["current_events"][0] + rows["current_events"][1]) + "/" + str(rows["current_events"][3]) + ", P%: " + str(round((rows["current_events"][0]) / rows["current_events"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["current_events"][2]) / rows["current_events"][3] * 10000) / 100) + "%)" if rows["current_events"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Religion, Mythology, Philosophy, Social Science" + RESET + ": " + (RED + str(round((rows["rmpss"][0] + rows["rmpss"][1]) / rows["rmpss"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["rmpss"][0] + rows["rmpss"][1]) + "/" + str(rows["rmpss"][3]) + ", P%: " + str(round((rows["rmpss"][0]) / rows["rmpss"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["rmpss"][2]) / rows["rmpss"][3] * 10000) / 100) + "%)" if rows["rmpss"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Trash / Pop Culture" + RESET + ": " + (RED + str(round((rows["trash"][0] + rows["trash"][1]) / rows["trash"][3] * 10000) / 100) + f"%{RESET} (" + str(rows["trash"][0] + rows["trash"][1]) + "/" + str(rows["trash"][3]) + ", P%: " + str(round((rows["trash"][0]) / rows["trash"][3] * 10000) / 100) + "%, -5%: " + str(round((rows["trash"][2]) / rows["trash"][3] * 10000) / 100) + "%)" if rows["trash"][3] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Lightning" + RESET + ": " + (RED + str(round(rows["lightning"][0] / rows["lightning"][2] * 10000) / 100) + f"%{RESET} (" + str(rows["lightning"][0]) + "/" + str(rows["lightning"][2]) + ")" if rows["lightning"][2] > 0 else f"{RED}No questions heard{RESET}"),
                        "\t" + GREEN + "Bonus Conversion" + RESET + ": " + (RED + str(round(rows["bonus_ans"] / rows["bonus_heard"] * 10000) / 100) + f"%{RESET} (" + str(rows["bonus_ans"]) + "/" + str(rows["bonus_heard"]) + ")" if rows["bonus_heard"] > 0 else f"{RED}No questions heard{RESET}")
                    ]
                    for i in print_list:
                        print(i)
                    input(f"Press {GREEN}enter{RESET} to continue.")
                break
            elif selection == "3":
                scriptRunning = False
                break
            else:
                print("That is not a valid input.")

    if changes_to_send:
        writeToDatabase()
    if changes_to_send:
        print(changes_to_send)
        with open("changes.json", "w") as f:
            json.dump(changes_to_send, f)
    try:
        sendMessage("CLOSE" + str(game_id_num), repeat=1)
    except:
        pass
#except Exception as e:
except socket.timeout:
    #print(e)
    sendMessage("CLOSE" + str(game_id_num), repeat=1)
