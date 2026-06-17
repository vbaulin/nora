import asyncio
import fcntl
import math
import socket
import struct

from maix import app, image

from picoclaw import gateway_running, get_picoclaw_model
from config import (
    DISP_W, DISP_H, ICON_PATH, LINE_H, TEXT_MARGIN, MAX_TEXT_W,
    FONT_NAME, FONT_NAME_LARGE,
)


# ---------------------------------------------------------------------------
# Animation task management
# ---------------------------------------------------------------------------
_anim_task: asyncio.Task | None = None
_home_icon = None


def start_anim(coro) -> None:
    global _anim_task
    if _anim_task and not _anim_task.done():
        _anim_task.cancel()
    _anim_task = asyncio.create_task(coro)


def stop_anim() -> None:
    global _anim_task
    if _anim_task and not _anim_task.done():
        _anim_task.cancel()
    _anim_task = None


def show_home_icon(disp) -> None:
    global _home_icon
    if _home_icon is None:
        img = image.load(ICON_PATH)
        if img is None:
            img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
            img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(8, 10, 24), thickness=-1)

        image.set_default_font(FONT_NAME_LARGE)
        text = "PRESS TO START"
        tw, _ = image.string_size(text)
        x = (DISP_W - tw) // 2
        y = DISP_H - 32

        glow = image.Color.from_rgb(40, 140, 220)
        core = image.Color.from_rgb(125, 225, 255)
        img.draw_string(x - 1, y, text, glow)
        img.draw_string(x + 1, y, text, glow)
        img.draw_string(x, y - 1, text, glow)
        img.draw_string(x, y + 1, text, glow)
        img.draw_string(x, y, text, core)

        image.set_default_font(FONT_NAME)
        _home_icon = img
    disp.display(_home_icon)


async def show_no_speech(disp, duration: float = 2.0):
    img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
    img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(20, 10, 10), thickness=-1)
    cx, cy = DISP_W // 2, 90
    img.draw_circle(cx, cy, 28, image.Color.from_rgb(60, 30, 0), thickness=-1)
    img.draw_circle(cx, cy, 28, image.Color.from_rgb(255, 160, 30), thickness=3)
    tw, _ = image.string_size("No speech detected")
    img.draw_string((DISP_W - tw) // 2, 140,
                    "No speech detected", image.Color.from_rgb(255, 160, 30))
    tw2, _ = image.string_size("Please try again")
    img.draw_string((DISP_W - tw2) // 2, 165,
                    "Please try again", image.Color.from_rgb(120, 120, 150))
    disp.display(img)
    await asyncio.sleep(duration)


async def show_error(disp, message: str = "No response", duration: float = 2.0):
    img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
    img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(15, 5, 5), thickness=-1)
    cx, cy = DISP_W // 2, 90
    img.draw_circle(cx, cy, 28, image.Color.from_rgb(60, 10, 10), thickness=-1)
    img.draw_circle(cx, cy, 28, image.Color.from_rgb(220, 60, 60), thickness=3)
    d = 12
    img.draw_line(cx - d, cy - d, cx + d, cy + d, image.Color.from_rgb(220, 60, 60), thickness=3)
    img.draw_line(cx + d, cy - d, cx - d, cy + d, image.Color.from_rgb(220, 60, 60), thickness=3)
    tw, _ = image.string_size(message)
    img.draw_string((DISP_W - tw) // 2, 140,
                    message, image.Color.from_rgb(220, 60, 60))
    tw2, _ = image.string_size("Please try again")
    img.draw_string((DISP_W - tw2) // 2, 165,
                    "Please try again", image.Color.from_rgb(120, 120, 150))
    disp.display(img)
    await asyncio.sleep(duration)


def show_info_screen(disp) -> None:
    def _get_ip() -> str | None:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            ip = socket.inet_ntoa(fcntl.ioctl(
                s.fileno(),
                0x8915,  # SIOCGIFADDR
                struct.pack('256s', b'wlan0'),
            )[20:24])
            s.close()
            return ip
        except Exception:
            return None

    ip      = _get_ip()
    wifi_ok = ip is not None
    gw      = gateway_running()
    model   = get_picoclaw_model()

    image.set_default_font(FONT_NAME_LARGE)

    img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
    img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(8, 10, 24), thickness=-1)

    gray  = image.Color.from_rgb(110, 110, 140)
    green = image.Color.from_rgb(60, 200, 100)
    red   = image.Color.from_rgb(220, 80, 80)
    white = image.Color.from_rgb(215, 215, 195)
    blue  = image.Color.from_rgb(90, 165, 255)

    y = 14
    title = "PicoClaw"
    tw, _ = image.string_size(title)
    img.draw_string((DISP_W - tw) // 2, y, title, blue)
    y += 30
    img.draw_line(12, y, DISP_W - 12, y, image.Color.from_rgb(40, 50, 90), thickness=1)
    y += 12

    ROW_H = 34

    def _row(label: str, value: str, value_color) -> None:
        nonlocal y
        img.draw_string(14, y, label, gray)
        vw, _ = image.string_size(value)
        img.draw_string(DISP_W - 14 - vw, y, value, value_color)
        y += ROW_H

    _row("WiFi",    "Yes" if wifi_ok else "No",  green if wifi_ok else red)
    _row("IP",      ip    if ip      else "---",  white if ip      else gray)
    y += 2
    img.draw_line(12, y, DISP_W - 12, y, image.Color.from_rgb(30, 35, 60), thickness=1)
    y += 12

    _row("Gateway", "Yes" if gw    else "No",   green if gw    else red)
    _row("Model",   model if model else "---",   white if model else gray)

    disp.display(img)
    image.set_default_font(FONT_NAME)


async def animate_speak_now(disp):
    tw, _ = image.string_size("Listening...")
    tw2, _ = image.string_size("Please speak now")
    frame = 0
    while True:
        t = frame * 0.25
        pulse = (math.sin(t) + 1) / 2          # 0.0 ~ 1.0
        r = int(20 + 12 * pulse)
        v = int(160 + 95 * pulse)
        img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
        img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(10, 10, 30), thickness=-1)
        img.draw_circle(DISP_W // 2, 90, r, image.Color.from_rgb(v, 50, 50), thickness=-1)
        img.draw_circle(DISP_W // 2, 90, r, image.Color.from_rgb(255, 100, 100), thickness=2)
        img.draw_string((DISP_W - tw) // 2, 140,
                        "Listening...", image.Color.from_rgb(240, 240, 240))
        img.draw_string((DISP_W - tw2) // 2, 165,
                        "Please speak now", image.Color.from_rgb(120, 120, 150))
        disp.display(img)
        frame += 1
        await asyncio.sleep(0.02)


async def animate_transcribing(disp):
    tw, _ = image.string_size("Transcribing...")
    tw2, _ = image.string_size("Recognizing speech")
    _dot_phases = [(3 - i) / 3.0 for i in range(3)]
    _dot_colors = [
        (int(int(60 + 195 * p) * 0.27), int(60 + 195 * p), int(int(60 + 195 * p) * 0.55))
        for p in _dot_phases
    ]
    _dot_radii = [max(3, 6 - i) for i in range(3)]
    frame = 0
    while True:
        angle = frame * 0.30
        img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
        img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(10, 20, 15), thickness=-1)
        cx, cy, orbit = DISP_W // 2, 90, 28
        img.draw_circle(cx, cy, orbit, image.Color.from_rgb(20, 60, 30), thickness=3)
        for i in range(3):
            a = angle + i * (2 * math.pi / 3)
            dx = int(orbit * math.cos(a))
            dy = int(orbit * math.sin(a))
            r, g, b = _dot_colors[i]
            img.draw_circle(cx + dx, cy + dy, _dot_radii[i],
                            image.Color.from_rgb(r, g, b), thickness=-1)
        img.draw_string((DISP_W - tw) // 2, 140,
                        "Transcribing...", image.Color.from_rgb(60, 220, 120))
        img.draw_string((DISP_W - tw2) // 2, 165,
                        "Recognizing speech", image.Color.from_rgb(120, 120, 150))
        disp.display(img)
        frame += 1
        await asyncio.sleep(0.02)


async def animate_thinking(disp, tool_names: list | None = None):
    tw, _ = image.string_size("Thinking...")
    tw2, _ = image.string_size("Please wait a moment")
    _dot_phases = [(3 - i) / 3.0 for i in range(3)]
    _dot_colors = [
        (int(int(60 + 195 * p) * 0.31), int(int(60 + 195 * p) * 0.63), int(60 + 195 * p))
        for p in _dot_phases
    ]
    _dot_radii = [max(3, 6 - i) for i in range(3)]
    frame = 0
    while True:
        angle = frame * 0.30
        img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
        img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(10, 10, 30), thickness=-1)
        cx, cy, orbit = DISP_W // 2, 90, 28
        img.draw_circle(cx, cy, orbit, image.Color.from_rgb(40, 40, 80), thickness=3)
        for i in range(3):
            a = angle + i * (2 * math.pi / 3)
            dx = int(orbit * math.cos(a))
            dy = int(orbit * math.sin(a))
            r, g, b = _dot_colors[i]
            img.draw_circle(cx + dx, cy + dy, _dot_radii[i],
                            image.Color.from_rgb(r, g, b), thickness=-1)
        img.draw_string((DISP_W - tw) // 2, 140,
                        "Thinking...", image.Color.from_rgb(80, 160, 255))
        if tool_names:
            tool_text = f"> {tool_names[-1]}"
            twt, _ = image.string_size(tool_text)
            img.draw_string((DISP_W - twt) // 2, 165,
                           tool_text, image.Color.from_rgb(160, 140, 255))
        else:
            img.draw_string((DISP_W - tw2) // 2, 165,
                            "Please wait a moment", image.Color.from_rgb(120, 120, 150))
        disp.display(img)
        frame += 1
        await asyncio.sleep(0.02)


def _strip_emoji(text: str) -> str:
    return "".join(c for c in text if ord(c) <= 0xFFFF and not (0x2600 <= ord(c) <= 0x27BF))


MAX_W = MAX_TEXT_W


def _wrap(text: str, max_lines: int = 0) -> list:
    lines = []
    for para in text.split("\n"):
        if not para:
            continue  # Skip empty lines
        while para and (max_lines == 0 or len(lines) < max_lines):
            lo, hi = 1, len(para)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                w, _ = image.string_size(para[:mid])
                if w <= MAX_W:
                    lo = mid
                else:
                    hi = mid - 1
            lines.append(para[:lo])
            para = para[lo:]
        if max_lines != 0 and len(lines) >= max_lines:
            break
    return lines, bool(text)


def _draw_line_h(img, x: int, y: int, text: str, color) -> int:
    img.draw_string(x, y, text, color)
    _, h = image.string_size(text)
    return max(h + 6, LINE_H)


def _render_frame(question: str, window: list, tool_names: list | None = None) -> image.Image:
    img = image.Image(DISP_W, DISP_H, image.Format.FMT_RGB888)
    img.draw_rect(0, 0, DISP_W, DISP_H, image.Color.from_rgb(8, 8, 24), thickness=-1)

    y = 6
    y += _draw_line_h(img, TEXT_MARGIN, y, "You:", image.Color.from_rgb(120, 180, 255))

    q_lines, _ = _wrap(question, 2)
    for line in q_lines:
        y += _draw_line_h(img, TEXT_MARGIN, y, line, image.Color.from_rgb(200, 200, 200))

    y += 3
    img.draw_line(TEXT_MARGIN, y, DISP_W - TEXT_MARGIN, y, image.Color.from_rgb(50, 50, 80), thickness=1)
    y += 8

    y += _draw_line_h(img, TEXT_MARGIN, y, "PicoClaw:", image.Color.from_rgb(80, 200, 100))

    for line in window:
        if y + LINE_H > DISP_H:
            break
        y += _draw_line_h(img, TEXT_MARGIN, y, line, image.Color.from_rgb(220, 220, 190))

    return img


async def show_result(disp, question: str, answer: str, tool_names: list | None = None, line_delay: float = 0.3, page_pause: float = 1.2):
    ans = _strip_emoji(answer) if answer else "(no response)"

    q_lines, _ = _wrap(question, 2)
    y_est = 6 + LINE_H + len(q_lines) * LINE_H + 3 + 1 + 8 + LINE_H
    max_visible = max(1, (DISP_H - y_est - 4) // LINE_H)

    all_lines, _ = _wrap(ans)

    for i in range(len(all_lines)):
        start_idx = max(0, i + 1 - max_visible)
        window = all_lines[start_idx:i + 1]
        frame = _render_frame(question, window, tool_names)
        disp.display(frame)
        if i < len(all_lines) - 1:
            await asyncio.sleep(line_delay)
