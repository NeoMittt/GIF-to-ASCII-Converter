import math
import os
import re
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

# Палитра символов от самого тёмного к самому светлому
PALETTE = " .:-=+*#%@"
STABILITY = 16

# Шаблон генерируемого автономного модуля
TEMPLATE = '''"""ASCII-арт: __NAME__
Запуск из консоли: python __NAME__.py
Импорт в проект:   from __NAME__ import play
"""
import os
import shutil
import sys
import time

CLEAR_EACH_FRAME = False  # True: перед каждым кадром очищать терминал; False: перерисовывать поверх
WIDTH = __WIDTH__
HEIGHT = __HEIGHT__
DELAYS = __DELAYS__
FRAMES = __FRAMES__


def play(loop: bool = True, clear_each_frame: bool = CLEAR_EACH_FRAME) -> None:
    """Проигрывает или выводит ASCII-арт в терминале."""
    os.system("")  # Включаем поддержку ANSI в Windows
    if shutil.get_terminal_size((80, 24)).columns < WIDTH:
        print(f"Окно уже арта (нужно {WIDTH} символов): растяни окно или уменьши шрифт")
        time.sleep(2)
    if shutil.get_terminal_size((80, 24)).lines <= HEIGHT:
        print(f"Окно ниже арта (нужно {HEIGHT} строк): растяни окно или уменьши шрифт")
        time.sleep(2)
    if len(FRAMES) == 1:
        sys.stdout.write(FRAMES[0] + "\\033[0m\\n")
        sys.stdout.flush()
        return
    sys.stdout.write("\\033[?25l" + ("" if clear_each_frame else "\\033[2J"))
    sys.stdout.flush()
    frames_lines = [frame.split("\\n") for frame in FRAMES]
    prev_lines: list[str] | None = None
    try:
        while True:
            for frame, lines, delay_ms in zip(FRAMES, frames_lines, DELAYS):
                t0 = time.perf_counter()
                if clear_each_frame:
                    buf = "\\033[2J\\033[H" + frame + "\\033[0m"
                elif prev_lines is None:
                    buf = "\\033[H" + frame + "\\033[0m"
                    prev_lines = lines
                else:
                    buf = "".join(
                        f"\\033[{i + 1};1H{line}\\033[0m\\033[K"
                        for i, line in enumerate(lines)
                        if i >= len(prev_lines) or line != prev_lines[i]
                    )
                    prev_lines = lines
                sys.stdout.write("\\033[?2026h" + buf + "\\033[?2026l")
                sys.stdout.flush()
                wait = delay_ms / 1000.0 - (time.perf_counter() - t0)
                if wait > 0:
                    time.sleep(wait)
            if not loop:
                break
    finally:
        sys.stdout.write("\\033[?25h\\033[0m")
        sys.stdout.flush()


if __name__ == "__main__":
    try:
        play()
        if len(FRAMES) == 1:
            input("Enter — выход")
    except KeyboardInterrupt:
        pass
'''


def ask_settings() -> tuple[str, int, bool] | None:
    """Открывает окно настроек и выбора файла; возвращает (путь, ширина, цвет) или None."""
    root = tk.Tk()
    root.title("ASCII-арт")
    root.resizable(False, False)

    width_var = tk.IntVar(value=100)
    color_var = tk.BooleanVar(value=False)
    result: list[tuple[str, int, bool]] = []

    frame = ttk.Frame(root, padding=15)
    frame.pack(fill="both", expand=True)

    ttk.Label(frame, text="Размер (ширина в символах):").pack(anchor="w", pady=(0, 5))
    presets = [("Маленький (60)", 60), ("Средний (100)", 100), ("Большой (160)", 160), ("Огромный (240)", 240)]
    for label, val in presets:
        ttk.Radiobutton(frame, text=label, variable=width_var, value=val).pack(anchor="w", pady=2)

    ttk.Checkbutton(frame, text="Цветной режим", variable=color_var).pack(anchor="w", pady=(10, 12))

    def on_choose() -> None:
        path = filedialog.askopenfilename(
            parent=root,
            title="Выберите картинку или GIF",
            filetypes=[("Картинки и GIF", "*.gif *.png *.jpg *.jpeg *.bmp *.webp")],
        )
        if path:
            result.append((path, width_var.get(), color_var.get()))
            root.destroy()

    ttk.Button(frame, text="Выбрать файл…", command=on_choose).pack(fill="x")
    root.mainloop()
    return result[0] if result else None


def frame_to_ascii(
    frame: Image.Image, width: int, color: bool, state: list | None = None
) -> tuple[str, list]:
    """Преобразует один кадр PIL Image в многострочную ASCII-строку с учётом сглаживания."""
    rgba = frame.convert("RGBA")
    bg = Image.new("RGBA", rgba.size, (0, 0, 0, 255))
    rgb = Image.alpha_composite(bg, rgba).convert("RGB")

    w, h = rgb.size
    height = max(1, round(width * h / w * 0.5))
    resized = rgb.resize((width, height), Image.Resampling.LANCZOS)
    px = resized.load()

    if state is None or len(state) != width * height:
        state = [None] * (width * height)

    lines = []
    n_chars = len(PALETTE) - 1
    for y in range(height):
        row_chars = []
        prev_color = None
        row_offset = y * width
        for x in range(width):
            r, g, b = px[x, y]
            pos = row_offset + x
            saved = state[pos]
            if (
                STABILITY > 0
                and saved is not None
                and max(abs(r - saved[0]), abs(g - saved[1]), abs(b - saved[2])) <= STABILITY
            ):
                r, g, b = saved
            else:
                state[pos] = (r, g, b)

            idx = int((0.299 * r + 0.587 * g + 0.114 * b) / 255 * n_chars)
            ch = PALETTE[idx]
            if color:
                if (r, g, b) != prev_color:
                    row_chars.append(f"\033[38;2;{r};{g};{b}m{ch}")
                    prev_color = (r, g, b)
                else:
                    row_chars.append(ch)
            else:
                row_chars.append(ch)
        line = "".join(row_chars) + ("\033[0m" if color else "")
        lines.append(line)
    return "\n".join(lines), state


def load_frames(path: str, width: int, color: bool) -> tuple[list[str], list[int]]:
    """Загружает изображение/GIF, прореживает при >200 кадрах и конвертирует в ASCII."""
    with Image.open(path) as img:
        if getattr(img, "n_frames", 1) == 1:
            img = ImageOps.exif_transpose(img)
        raw_frames: list[tuple[Image.Image, int]] = []
        for frame in ImageSequence.Iterator(img):
            delay = max(20, int(frame.info.get("duration", 100) or 100))
            raw_frames.append((frame.copy(), delay))

    n = len(raw_frames)
    if n > 200:
        k = math.ceil(n / 200)
        sampled = [
            (raw_frames[i][0], sum(d for _, d in raw_frames[i : i + k]))
            for i in range(0, n, k)
        ]
    else:
        sampled = raw_frames

    ascii_frames: list[str] = []
    state: list | None = None
    for f, _ in sampled:
        ascii_str, state = frame_to_ascii(f, width, color, state)
        ascii_frames.append(ascii_str)
    delays = [d for _, d in sampled]
    return ascii_frames, delays


def build_module(name: str, frames: list[str], delays: list[int], width: int) -> str:
    """Собирает код автономного Python-модуля из шаблона через str.replace."""
    height = frames[0].count("\n") + 1
    return (
        TEMPLATE.replace("__FRAMES__", repr(frames))
        .replace("__DELAYS__", repr(delays))
        .replace("__WIDTH__", str(width))
        .replace("__HEIGHT__", str(height))
        .replace("__NAME__", name)
    )


def main() -> None:
    """Точка входа: выбор параметров, генерация модуля, сохранение и запуск."""
    settings = ask_settings()
    if not settings:
        return
    src_path, width, color = settings

    try:
        print("Конвертирую, подожди…")
        frames, delays = load_frames(src_path, width, color)
        if not frames:
            raise ValueError("Нет доступных кадров в изображении.")

        out_dir = Path(__file__).resolve().parent / "ascii_arts"
        out_dir.mkdir(parents=True, exist_ok=True)

        stem = re.sub(r"[^0-9a-zA-Z_]", "_", Path(src_path).stem)
        if re.search(r"[0-9a-zA-Z]", stem) is None:
            stem = "art"
        if not stem or stem[0].isdigit():
            stem = "art_" + stem
        base_name = f"{stem}_ascii"

        mod_name = base_name
        out_path = out_dir / f"{mod_name}.py"
        counter = 2
        while out_path.exists():
            mod_name = f"{base_name}_{counter}"
            out_path = out_dir / f"{mod_name}.py"
            counter += 1

        code = build_module(mod_name, frames, delays, width)
        out_path.write_text(code, encoding="utf-8")

        size_kb = out_path.stat().st_size / 1024
        print(f"Сохранено: {out_path} ({size_kb:.1f} КБ)")

        if messagebox.askyesno("Готово", "Запустить сейчас?"):
            subprocess.run([sys.executable, str(out_path)])

    except FileNotFoundError:
        messagebox.showerror("Ошибка", "Выбранный файл не найден.")
    except (UnidentifiedImageError, ValueError):
        messagebox.showerror("Ошибка", "Файл не удалось открыть как поддерживаемое изображение.")
    except PermissionError:
        messagebox.showerror("Ошибка", "Нет прав на чтение файла или запись в папку ascii_arts.")
    except OSError as exc:
        messagebox.showerror("Ошибка", f"Ошибка файловой системы или чтения картинки: {exc}")


if __name__ == "__main__":
    main()