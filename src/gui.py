import os
os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = "hide"
import sys
import ctypes
import pygame
import socket
import configparser
import threading
import json
from queue import Queue

os.chdir(os.path.dirname(os.path.abspath(__file__)))

if "win32" in sys.platform:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        print("worked")
    except AttributeError:
        raise AttributeError

running = True
message_queue = Queue()

config = configparser.ConfigParser()
config.read('../config.ini')

if not config.has_section("CONNECTION"):
    print("config.ini does not exist or is incorrectly formatted.")
    running = False
    input("Press enter to continue.")

try:
    IP = config["CONNECTION"]["ip"]
    PORT = int(config["CONNECTION"]["port"])
except:
    print("The IP or port is incorrectly formatted.")
    running = False
    input("Press enter to continue.")

while running:
    session = input("Enter the \033[32msession id\033[0m: ").lower()
    if session == "pass":
        running = False
        break
    try:
        client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        client_socket.settimeout(0.5)
        client_socket.sendto(str("ADSCR" + session).encode(), (IP, PORT))
        data, addr = client_socket.recvfrom(4096)
        data = data.decode("utf-8")
        client_socket.close()
        if data == "pass":
            break
        else:
            print("Session id is invalid.")
    except (socket.timeout, ConnectionResetError):
        print("Error connecting to server.")
        input("Press \033[32menter\033[0m to continue.")
        running = False
        break
if running:
    client_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    client_socket.bind(("0.0.0.0", 0))
    client_socket.settimeout(0.5)

    client_socket.sendto(("SUBCD" + session).encode(), (IP, PORT))

class TextBox():
    def __init__(self, screen, x, y):
        self.screen = screen
        self.x = x
        self.y = y

        self.lines = []

        self.font = pygame.font.Font("../assets/IBMPlexSerif-Regular.ttf", 20)
        self.text_color = (0, 255, 0)

        self.base_width = 200
        self.padding_x = 10
        self.padding_y = 10
        self.line_spacing = -5

        self.current_width = self.base_width
        self.width_speed = 0.2

        self.type_speed = 1

    def add_line(self, text):
        new_line = {
            "full": text,
            "visible": "",
            "progress": 0
        }

        self.lines.insert(0, new_line)
        self.lines = self.lines[:5]

    def update(self):
        rendered_lines = []
        max_line_width = 0

        for i, line in enumerate(self.lines):
            if i == 0 and line["progress"] < len(line["full"]):
                line["progress"] += self.type_speed
                line["visible"] = line["full"][:line["progress"]]
            else:
                line["visible"] = line["full"]

            surf = self.font.render(line["visible"], True, self.text_color)
            rendered_lines.append(surf)
            max_line_width = max(max_line_width, surf.get_width())

        target_width = max(
            self.base_width,
            max_line_width + self.padding_x * 2
        )

        self.current_width += (target_width - self.current_width) * self.width_speed
        fg_width = int(self.current_width)

        total_height = 0
        heights = []

        for surf in rendered_lines:
            h = surf.get_height()
            heights.append(h)
            total_height += h

        if len(rendered_lines) > 1:
            total_height += self.line_spacing * (len(rendered_lines) - 1)

        fg_height = total_height + self.padding_y * 2

        bg_rect = pygame.Rect(0, 0, fg_width + 6, fg_height + 6)
        bg_rect.midtop = (self.x, self.y)
        if rendered_lines:
            pygame.draw.rect(self.screen, (50, 50, 50), bg_rect)

        fg = pygame.Surface((fg_width, fg_height), pygame.SRCALPHA)
        if rendered_lines:
            pygame.draw.rect(fg, (100, 100, 100), fg.get_rect())

        y = self.padding_y

        for i, surf in enumerate(rendered_lines):
            rect = surf.get_rect()
            rect.centerx = fg_width // 2
            rect.y = y

            fg.blit(surf, rect)

            y += heights[i] + self.line_spacing

        fg_rect = fg.get_rect()
        fg_rect.center = bg_rect.center
        self.screen.blit(fg, fg_rect)

class Counter():
    def __init__ (self, screen, x, y):
        self.x = x
        self.y = y
        self.screen = screen
        self.score = 0
        self.font = pygame.font.Font("../assets/UnicaOne-Regular.ttf", 128)
        self.text_color = (255, 255, 255)
        self.current_width = 195
        self.prev_score = 0
        self.score = 0

        self.anim_progress = 1.0
        self.anim_speed = 0.05 

    def update(self):
        base_width = 195
        base_height = 122
        padding = 10
        overlap = -10

        if self.anim_progress < 1.0:
            self.anim_progress += self.anim_speed
            if self.anim_progress > 1.0:
                self.anim_progress = 1.0

        prev_str = str(self.prev_score)
        curr_str = str(self.score)

        num_digits = max(len(prev_str), len(curr_str))

        prev_str = prev_str.zfill(num_digits)
        curr_str = curr_str.zfill(num_digits)

        digit_width = self.font.size("0")[0]

        if num_digits <= 3:
            target_width = base_width
        else:
            target_width = max(
                base_width,
                digit_width * num_digits + padding * 2 + overlap * (num_digits - 1)
            )

        width_speed = 0.2
        self.current_width += (target_width - self.current_width) * width_speed
        fg_width = int(self.current_width)

        bg_rect = pygame.Rect(0, 0, fg_width + 6, base_height + 6)
        bg_rect.center = (self.x, self.y)
        pygame.draw.rect(self.screen, (50, 50, 50), bg_rect)

        fg = pygame.Surface((fg_width, base_height), pygame.SRCALPHA)
        pygame.draw.rect(fg, (100, 100, 100), fg.get_rect())

        t = self.anim_progress
        t = 1 - (1 - t) ** 3
        offset_y = int(t * self.font.get_height())

        x = fg_width - padding

        for i in range(num_digits - 1, -1, -1):
            prev_digit = prev_str[i]
            curr_digit = curr_str[i]

            prev_len = len(str(self.prev_score))
            curr_len = len(str(self.score))

            if i < num_digits - prev_len:
                prev_digit = None

            if i < num_digits - curr_len:
                curr_digit = None

            if prev_digit is None and curr_digit is None:
                continue

            prev_surface = self.font.render(prev_digit, True, self.text_color) if prev_digit is not None else None
            curr_surface = self.font.render(curr_digit, True, self.text_color) if curr_digit is not None else None

            digit_rect = (prev_surface or curr_surface).get_rect()
            digit_rect.right = x
            center_y = fg.get_height() // 2

            if prev_digit != curr_digit:
                if prev_surface:
                    prev_rect = digit_rect.copy()
                    prev_rect.centery = center_y - offset_y
                    fg.blit(prev_surface, prev_rect)

                if curr_surface:
                    curr_rect = digit_rect.copy()
                    curr_rect.centery = center_y + (self.font.get_height() - offset_y)
                    fg.blit(curr_surface, curr_rect)
            else:
                digit_rect.centery = center_y
                fg.blit(prev_surface, digit_rect)

            x -= digit_rect.width + overlap

        fg_rect = fg.get_rect(center=bg_rect.center)
        self.screen.blit(fg, fg_rect)
    def set_score(self, new_score):
        if new_score != self.score:
            self.prev_score = self.score
            self.score = new_score
            self.anim_progress = 0.0
    def add_score(self, amount):
        self.set_score(self.score + amount)

class SeatTracker():
    def __init__(self, screen, x, y, name_list, alignment):
        self.screen = screen
        self.x = x
        self.y = y
        self.number = len(name_list)
        self.name_list = name_list
        self.alignment = alignment
        self.font = pygame.font.Font("../assets/IBMPlexSerif-Regular.ttf", 20)
        self.timer = 0
        self.highlighted = []

    def update(self):
        # Derive the seat count from the name list itself so number and
        # name_list can never disagree and cause an index error.
        count = len(self.name_list)
        surface = pygame.Surface((250, 55 * max(count, 1)), pygame.SRCALPHA)
        surface.fill((0, 0, 0, 0))
        highlighted_list = []
        remove = []
        for i in range(len(self.highlighted)):
            if self.highlighted[i][1] > 0:
                highlighted_list.append(self.highlighted[i][0])
                self.highlighted[i][1] -= 1
        self.highlighted = [h for h in self.highlighted if h[1] > 0]

        for i in range(count):
            if self.name_list[i] not in highlighted_list:
                if self.alignment == "LEFT":
                    pygame.draw.rect(surface, (50, 50, 50), pygame.Rect(0, 55 * i, 50, 50))
                    pygame.draw.rect(surface, (100, 100, 100), pygame.Rect(5, 55 * i + 5, 40, 40))
                if self.alignment == "RIGHT":
                    pygame.draw.rect(surface, (50, 50, 50), pygame.Rect(200, 55 * i, 50, 50))
                    pygame.draw.rect(surface, (100, 100, 100), pygame.Rect(205, 55 * i + 5, 40, 40))
            else:
                if self.alignment == "LEFT":
                    bottom_rect = pygame.Rect(0, 55 * i, 50, 50)
                    pygame.draw.rect(surface, (0, 100, 0), bottom_rect)
                    pygame.draw.rect(surface, (0, 200, 0), pygame.Rect(5, 55 * i + 5, 40, 40))
                    text = self.font.render(self.name_list[i], True, (0, 255, 0))
                    text_rect = text.get_rect()
                    text_rect.midleft = (bottom_rect.right + 10, bottom_rect.centery)
                elif self.alignment == "RIGHT":
                    bottom_rect = pygame.Rect(200, 55 * i, 50, 50)
                    pygame.draw.rect(surface, (0, 100, 0), bottom_rect)
                    pygame.draw.rect(surface, (0, 200, 0), pygame.Rect(205, 55 * i + 5, 40, 40))
                    text = self.font.render(self.name_list[i], True, (0, 255, 0))
                    text_rect = text.get_rect()
                    text_rect.midright = (bottom_rect.left - 10, bottom_rect.centery)
                #pygame.draw.rect(surface, (0, 0, 0), pygame.Rect(text_rect.left - 5, text_rect.top - 5, text_rect.width + 10, text_rect.height + 10), 2)
                surface.blit(text, text_rect)
                
        rect = surface.get_rect()
        if self.alignment == "LEFT":
            rect.midleft = (self.x, self.y)
        elif self.alignment == "RIGHT":
            rect.midright = (self.x, self.y)
        self.screen.blit(surface, rect)


def listen_for_server(sock):
    while running:
        try:
            data, addr = sock.recvfrom(4096)
            message_queue.put(data.decode("utf-8"))
        except socket.timeout:
            continue
        except Exception as e:
            print(e)

threading.Thread(target=listen_for_server, args=(client_socket,), daemon=True).start()

pygame.init()
game_width = 1280
game_height = 720
final_screen = pygame.display.set_mode((game_width, game_height), pygame.SCALED | pygame.FULLSCREEN)
screen = pygame.Surface((game_width, game_height))
swap_button = pygame.image.load("../assets/swap.png")
bg = pygame.image.load("../assets/bg.png")
bg = pygame.transform.scale(bg, (1280, 720))
button = pygame.transform.scale(swap_button, (50, 50))
button_rect = button.get_rect(topleft = (615, 500))
clock = pygame.time.Clock()
timer = 0
default_pos = True
resubscribe_counter = 0
resubscribe_interval = 400

teamACounter = Counter(screen, 320, 200)
teamBCounter = Counter(screen, 960, 200)
teamAText = TextBox(screen, 320, 500)
teamBText = TextBox(screen, 960, 500)
teamASeats = SeatTracker(screen, 0, 360, [], "LEFT")
teamBSeats = SeatTracker(screen, 1280, 360, [], "RIGHT")

while running:
    while not message_queue.empty():
        try:
            msg = message_queue.get()
            
            if msg.startswith("SCORE|"):
                teamACounter.set_score(json.loads(msg.split("|")[1])["a"])
                teamBCounter.set_score(json.loads(msg.split("|")[1])["b"])
                try:
                    client_socket.sendto(b"SCRCK", (IP, PORT))
                except:
                    pass
            elif msg.startswith("MESSAGE|"):
                data = json.loads(msg.split("|")[1])
                if data[0] == "a":
                    teamAText.add_line(data[1])
                elif data[0] == "b":
                    teamBText.add_line(data[1])
                try:
                    client_socket.sendto(b"SCRCK", (IP, PORT))
                except:
                    pass
            elif msg.startswith("SEAT|"):
                data = json.loads(msg.split("|")[1])
                if data[0] == "NEW_PLAYERS":
                    for key, team in data[1].items():
                        if key == "a":
                            teamASeats.name_list = team.copy()
                            teamASeats.number = len(team)
                        elif key == "b":
                            teamBSeats.name_list = team.copy()
                            teamBSeats.number = len(team)
                elif data[0] == "HIGHLIGHT":
                    h = data[1]
                    if (isinstance(h, list) and len(h) == 2
                            and isinstance(h[0], str)
                            and isinstance(h[1], (int, float))
                            and not isinstance(h[1], bool)):
                        teamASeats.highlighted.append([h[0], h[1]])
                        teamBSeats.highlighted.append([h[0], h[1]])
                elif data[0] == "SET_HIGHLIGHT":
                    teamASeats.highlighted, teamBSeats.highlighted = [], []
                try:
                    client_socket.sendto(b"SCRCK", (IP, PORT))
                except:
                    pass
            elif msg.startswith("RESET|"):
                teamACounter.set_score(0)
                teamBCounter.set_score(0)
                teamAText.lines = []
                teamBText.lines = []
                teamASeats.highlighted = []
                teamASeats.name_list = []
                teamASeats.number = 0
                teamBSeats.highlighted = []
                teamBSeats.name_list = []
                teamBSeats.number = 0
                try:
                    client_socket.sendto(b"SCRCK", (IP, PORT))
                except:
                    pass
            elif msg == "CLOSED":
                print("Client has closed this session.")
                running = False
        except Exception:
            pass

    if timer > 0:
        timer -= 1

    resubscribe_counter += 1
    if resubscribe_counter >= resubscribe_interval:
        resubscribe_counter = 0
        try:
            client_socket.sendto(("SUBCD" + session).encode(), (IP, PORT))
        except:
            pass

    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False
        if event.type == pygame.MOUSEBUTTONDOWN:
            mouse_position = pygame.mouse.get_pos()
            if button_rect.collidepoint(mouse_position) and timer <= 0:
                timer = 10
                if default_pos:
                    teamACounter.x = 960
                    teamBCounter.x = 320
                    teamAText.x = 960
                    teamBText.x = 320
                    teamASeats.x = 1280
                    teamBSeats.x = 0
                    teamASeats.alignment = "RIGHT"
                    teamBSeats.alignment = "LEFT"
                    default_pos = False
                else:
                    teamACounter.x = 320
                    teamBCounter.x = 960
                    teamAText.x = 320
                    teamBText.x = 960
                    teamASeats.x = 0
                    teamBSeats.x = 1280
                    teamASeats.alignment = "LEFT"
                    teamBSeats.alignment = "RIGHT"
                    default_pos = True

    screen.fill((50, 50, 50))
    screen.blit(bg, (0, 0))
    pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(638, 20, 4, 460))
    pygame.draw.rect(screen, (0, 0, 0), pygame.Rect(638, 570, 4, 130))
    screen.blit(button, button_rect)
    for widget in (teamACounter, teamBCounter, teamAText, teamBText, teamASeats, teamBSeats):
        try:
            widget.update()
        except Exception as e:
            print("Render error (skipping frame for widget):", e)

    screen_draw = pygame.transform.smoothscale(screen, final_screen.get_size())

    final_screen.blit(screen_draw, (0, 0))

    pygame.display.flip()
    clock.tick(40)
    pygame.display.set_caption("Scoreboard - session id:" + str(session))

