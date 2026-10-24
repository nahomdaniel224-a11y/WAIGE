
import ctypes
import html
import json
import os
import re
import struct
import sys
import threading
import urllib.parse
import urllib.request
import tkinter as tk
import tkinter.font as tkfont

import customtkinter as ctk


APP_NAME = "WAIGE"
APP_VERSION = "1.1.0"

BG = "#07111F"
SIDEBAR = "#0B192B"
PANEL = "#102035"
USER_BUBBLE = "#163A5A"
ACCENT = "#1685C5"
ACCENT_HOVER = "#2198D8"
TEXT = "#F1F6FF"
MUTED = "#8CA4BE"
CYAN = "#75D9FF"

FONT_FILE = "WAIGE Font.ttf"

LANGUAGES = {
    "english": "en",
    "hindi": "hi",
    "amharic": "am",
    "french": "fr",
    "arabic": "ar",
    "spanish": "es",
    "chinese": "zh",
    "mandarin": "zh",
    "german": "de",
    "italian": "it",
    "portuguese": "pt",
    "russian": "ru",
    "japanese": "ja",
    "korean": "ko",
    "turkish": "tr",
    "swahili": "sw",
    "somali": "so",
    "oromo": "om",
    "tigrinya": "ti",
    "dutch": "nl",
    "polish": "pl",
    "greek": "el",
    "thai": "th",
    "vietnamese": "vi",
    "indonesian": "id",
    "filipino": "tl",
    "bengali": "bn",
    "urdu": "ur",
    "persian": "fa",
    "hebrew": "he",
    "ukrainian": "uk",
    "romanian": "ro",
    "swedish": "sv",
    "danish": "da",
    "norwegian": "no",
    "finnish": "fi",
    "czech": "cs",
    "hungarian": "hu",
    "malay": "ms",
    "nepali": "ne",
    "punjabi": "pa",
}

ALIASES = {
    "tagalog": "filipino",
    "afaan oromo": "oromo",
    "mandarin chinese": "mandarin",
    "simplified chinese": "chinese",
    "chinese simplified": "chinese",
}


def resource_path(filename):
    """Locate resources in development and PyInstaller builds."""
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
    else:
        base = os.path.dirname(os.path.abspath(__file__))

    return os.path.join(base, filename)


def read_font_family(font_path):
    """Read a font's family name from its TrueType name table."""
    try:
        with open(font_path, "rb") as file:
            data = file.read()

        if len(data) < 12:
            return None

        table_count = struct.unpack_from(">H", data, 4)[0]
        tables = {}

        for index in range(table_count):
            offset = 12 + index * 16
            if offset + 16 > len(data):
                break

            tag, checksum, table_offset, length = struct.unpack_from(
                ">4sIII", data, offset
            )

            if table_offset + length <= len(data):
                tables[tag.decode("ascii", errors="ignore")] = (
                    table_offset, length
                )

        if "name" not in tables:
            return None

        table_offset, table_length = tables["name"]
        table = data[table_offset:table_offset + table_length]

        if len(table) < 6:
            return None

        _, count, string_offset = struct.unpack_from(">HHH", table, 0)
        candidates = []

        for index in range(count):
            offset = 6 + index * 12
            if offset + 12 > len(table):
                break

            platform, encoding, language, name_id, length, name_offset = (
                struct.unpack_from(">HHHHHH", table, offset)
            )

            # Prefer typographic family name, then ordinary family name.
            if name_id not in (16, 1):
                continue

            start = string_offset + name_offset
            end = start + length

            if end > len(table):
                continue

            raw = table[start:end]

            try:
                if platform in (0, 3):
                    value = raw.decode("utf-16-be").strip("\x00")
                elif platform == 1:
                    value = raw.decode("mac_roman").strip("\x00")
                else:
                    continue
            except (UnicodeDecodeError, LookupError):
                continue

            if value:
                priority = (
                    0 if name_id == 16 else 1,
                    0 if platform == 3 and language == 0x0409 else 1,
                    0 if platform == 3 else 1,
                )
                candidates.append((priority, value))

        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]

    except (OSError, ValueError, struct.error):
        pass

    return None


class PrivateFont:
    """Make the bundled font available to this Windows process."""

    def __init__(self, path):
        self.path = path
        self.loaded = False
        self.family = None

        if not os.path.isfile(path):
            return

        self.family = read_font_family(path)

        if sys.platform != "win32":
            return

        try:
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            add_font = gdi32.AddFontResourceExW
            add_font.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.c_void_p,
            ]
            add_font.restype = ctypes.c_int

            # FR_PRIVATE: make this font available privately to the process.
            self.loaded = add_font(path, 0x10, None) > 0
        except (OSError, AttributeError):
            self.loaded = False

    def close(self):
        if not self.loaded or sys.platform != "win32":
            return

        try:
            gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
            remove_font = gdi32.RemoveFontResourceExW
            remove_font.argtypes = [
                ctypes.c_wchar_p,
                ctypes.c_uint,
                ctypes.c_void_p,
            ]
            remove_font.restype = ctypes.c_bool
            remove_font(self.path, 0x10, None)
        except (OSError, AttributeError):
            pass

        self.loaded = False


def normalize_text(text):
    return re.sub(r"\s+", " ", text).strip()


def language_code(name):
    name = normalize_text(name).strip(" ?.!,'\"").lower()
    name = ALIASES.get(name, name)
    return LANGUAGES.get(name)


def parse_question(question):
    """Recognize common translation-question formats."""
    question = normalize_text(question)

    patterns = [
        (
            r"^(?:how do you say|how do i say|how to say|"
            r"how would you say)\s+(.+?)\s+in\s+([a-zA-Z ]+)\??$",
            "english_to_target",
        ),
        (
            r"^what is\s+(.+?)\s+in\s+([a-zA-Z ]+)\??$",
            "english_to_target",
        ),
        (
            r"^translate\s+(.+?)\s+from\s+([a-zA-Z ]+)"
            r"\s+to\s+([a-zA-Z ]+)\??$",
            "source_to_target",
        ),
        (
            r"^translate\s+(.+?)\s+(?:to|into)\s+([a-zA-Z ]+)\??$",
            "english_to_target",
        ),
    ]

    for pattern, mode in patterns:
        match = re.match(pattern, question, flags=re.IGNORECASE)
        if not match:
            continue

        groups = match.groups()

        if mode == "source_to_target":
            phrase, source_name, target_name = groups
            source = language_code(source_name)
            target = language_code(target_name)

            if not source or not target:
                return None, (
                    "I couldn't recognize the source or target language. "
                    "Please check the language names and try again."
                )
        else:
            phrase, target_name = groups
            source = "en"
            target = language_code(target_name)

            if not target:
                return None, (
                    "I don't recognize that target language. Try Hindi, "
                    "Amharic, French, Arabic, Spanish, or another supported "
                    "language."
                )

        phrase = phrase.strip(" ?.!,'\"")

        if not phrase:
            return None, "Please enter a word or phrase to translate."

        if len(phrase) > 500:
            return None, "Please keep each translation request under 500 characters."

        return {
            "phrase": phrase,
            "source": source,
            "target": target,
        }, None

    return None, (
        "I'm WAIGE, your language assistant.\n\n"
        "Try asking:\n"
        "• How do you say car in Hindi?\n"
        "• How do I say good morning in Amharic?\n"
        "• Translate bonjour from French to English.\n\n"
        "I specialize in language questions and translations."
    )


def translate_text(phrase, source, target):
    """Request a translation from the online MyMemory service."""
    query = urllib.parse.urlencode({
        "q": phrase,
        "langpair": f"{source}|{target}",
    })

    url = "https://api.mymemory.translated.net/get?" + query
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "WAIGE-Language-Assistant/1.1",
            "Accept": "application/json",
        },
    )

    with urllib.request.urlopen(request, timeout=25) as response:
        data = json.loads(response.read().decode("utf-8"))

    if data.get("responseStatus") != 200:
        detail = data.get("responseDetails") or "The service returned an error."
        raise RuntimeError(detail)

    result = data.get("responseData", {}).get("translatedText", "")
    result = html.unescape(result).strip()

    if not result:
        raise RuntimeError("The translation service returned an empty result.")

    return result


class WAIGEApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("WAIGE — Language Assistant")
        self.geometry("1050x740")
        self.minsize(650, 540)
        self.configure(fg_color=BG)

        self.busy = False
        self.loading = False
        self.loading_dots = 0
        self.closed = False
        self.font_resource = PrivateFont(resource_path(FONT_FILE))

        self.setup_fonts()

        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.create_sidebar()
        self.create_main_area()
        self.show_welcome()

        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.entry.focus_set()

    def setup_fonts(self):
        self.font_family = "Segoe UI"

        if self.font_resource.loaded and self.font_resource.family:
            try:
                available = set(tkfont.families(self))
                if self.font_resource.family in available:
                    self.font_family = self.font_resource.family
            except tk.TclError:
                pass

        self.font_normal = ctk.CTkFont(
            family=self.font_family, size=14
        )
        self.font_small = ctk.CTkFont(
            family=self.font_family, size=11
        )
        self.font_heading = ctk.CTkFont(
            family=self.font_family, size=20, weight="bold"
        )
        self.font_logo = ctk.CTkFont(
            family=self.font_family, size=23, weight="bold"
        )

    def create_sidebar(self):
        self.sidebar = ctk.CTkFrame(
            self,
            width=225,
            corner_radius=0,
            fg_color=SIDEBAR,
        )
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_propagate(False)

        brand = ctk.CTkFrame(
            self.sidebar, fg_color="transparent"
        )
        brand.pack(fill="x", padx=18, pady=(24, 25))

        ctk.CTkLabel(
            brand,
            text="W",
            width=43,
            height=43,
            corner_radius=13,
            fg_color="#1768A6",
            text_color="white",
            font=ctk.CTkFont(
                family=self.font_family, size=24, weight="bold"
            ),
        ).pack(side="left")

        ctk.CTkLabel(
            brand,
            text="WAIGE",
            font=self.font_logo,
            text_color=TEXT,
        ).pack(side="left", padx=10)

        ctk.CTkButton(
            self.sidebar,
            text="+   New chat",
            anchor="w",
            height=43,
            corner_radius=10,
            fg_color="#142A42",
            hover_color="#1B3D5D",
            font=self.font_normal,
            command=self.new_chat,
        ).pack(fill="x", padx=14, pady=(0, 25))

        ctk.CTkLabel(
            self.sidebar,
            text="LANGUAGES",
            font=ctk.CTkFont(
                family=self.font_family, size=10, weight="bold"
            ),
            text_color=MUTED,
        ).pack(anchor="w", padx=19, pady=(0, 10))

        for language in (
            "English", "Hindi", "Amharic", "French",
            "Arabic", "Spanish", "Chinese", "Japanese",
            "German", "Swahili", "Oromo", "Tigrinya",
        ):
            ctk.CTkLabel(
                self.sidebar,
                text=f"  •  {language}",
                font=self.font_normal,
                text_color="#C0D0E3",
            ).pack(anchor="w", padx=19, pady=4)

        ctk.CTkFrame(
            self.sidebar, height=1, fg_color="#20354C"
        ).pack(fill="x", padx=15, pady=19)

        ctk.CTkLabel(
            self.sidebar,
            text="●  ONLINE TRANSLATION",
            text_color="#75D9A5",
            font=self.font_small,
        ).pack(anchor="w", padx=18)

        ctk.CTkLabel(
            self.sidebar,
            text="An internet connection is\nrequired for translations.",
            justify="left",
            text_color=MUTED,
            font=self.font_small,
        ).pack(anchor="w", padx=18, pady=(7, 0))

        ctk.CTkLabel(
            self.sidebar,
            text=f"WAIGE  v{APP_VERSION}",
            text_color="#667F98",
            font=self.font_small,
        ).pack(side="bottom", pady=17)

    def create_main_area(self):
        self.main = ctk.CTkFrame(
            self, fg_color=BG, corner_radius=0
        )
        self.main.grid(row=0, column=1, sticky="nsew")
        self.main.grid_columnconfigure(0, weight=1)
        self.main.grid_rowconfigure(1, weight=1)

        header = ctk.CTkFrame(
            self.main,
            height=66,
            corner_radius=0,
            fg_color=SIDEBAR,
        )
        header.grid(row=0, column=0, sticky="ew")
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header,
            text="Language Assistant",
            font=ctk.CTkFont(
                family=self.font_family, size=17, weight="bold"
            ),
            text_color=TEXT,
        ).grid(row=0, column=0, sticky="w", padx=23, pady=18)

        ctk.CTkLabel(
            header,
            text="LANGUAGE MODE",
            text_color=CYAN,
            font=self.font_small,
        ).grid(row=0, column=1, sticky="e", padx=22)

        self.chat = ctk.CTkScrollableFrame(
            self.main,
            fg_color=BG,
            corner_radius=0,
        )
        self.chat.grid(
            row=1, column=0, sticky="nsew", padx=0, pady=0
        )
        self.chat.grid_columnconfigure(0, weight=1)

        bottom = ctk.CTkFrame(
            self.main, fg_color=BG, corner_radius=0
        )
        bottom.grid(
            row=2, column=0, sticky="ew", padx=22, pady=(8, 18)
        )
        bottom.grid_columnconfigure(0, weight=1)

        self.status = ctk.CTkLabel(
            bottom,
            text="",
            text_color=CYAN,
            font=self.font_small,
        )
        self.status.grid(
            row=0, column=0, columnspan=2, sticky="w", pady=(0, 7)
        )

        self.entry = ctk.CTkTextbox(
            bottom,
            height=68,
            corner_radius=15,
            fg_color="#102239",
            border_width=1,
            border_color="#29445F",
            text_color=TEXT,
            font=self.font_normal,
            wrap="word",
        )
        self.entry.grid(
            row=1, column=0, sticky="ew", padx=(0, 10)
        )
        self.entry.bind("<Return>", self.on_enter)

        self.send_button = ctk.CTkButton(
            bottom,
            text="➤",
            width=54,
            height=54,
            corner_radius=14,
            font=ctk.CTkFont(
                family=self.font_family, size=23, weight="bold"
            ),
            fg_color=ACCENT,
            hover_color=ACCENT_HOVER,
            command=self.send_message,
        )
        self.send_button.grid(row=1, column=1, sticky="se")

        ctk.CTkLabel(
            bottom,
            text="Type a language question and press Enter to send.",
            text_color="#7288A1",
            font=self.font_small,
        ).grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(8, 0)
        )

    def show_welcome(self):
        self.add_message(
            "WAIGE",
            "Hello! I'm WAIGE, your language assistant.\n\n"
            "Ask me how to say a word or phrase in another language.\n\n"
            "For example:\n"
            "How do you say car in Hindi?",
        )

    def add_message(self, speaker, message):
        is_user = speaker == "You"

        row = ctk.CTkFrame(self.chat, fg_color="transparent")
        row.pack(fill="x", padx=22, pady=9)

        bubble = ctk.CTkFrame(
            row,
            fg_color=USER_BUBBLE if is_user else PANEL,
            corner_radius=15,
        )
        bubble.pack(
            side="right" if is_user else "left",
            anchor="e" if is_user else "w",
            padx=(65, 0) if is_user else (0, 65),
        )

        ctk.CTkLabel(
            bubble,
            text=speaker,
            font=ctk.CTkFont(
                family=self.font_family, size=11, weight="bold"
            ),
            text_color=CYAN if not is_user else "#D8ECFF",
        ).pack(anchor="w", padx=14, pady=(10, 2))

        ctk.CTkLabel(
            bubble,
            text=message,
            font=self.font_normal,
            text_color=TEXT,
            justify="left",
            wraplength=570,
        ).pack(anchor="w", padx=14, pady=(3, 12))

        if not is_user:
            ctk.CTkButton(
                bubble,
                text="Copy answer",
                width=94,
                height=27,
                corner_radius=7,
                fg_color="#1B3047",
                hover_color="#294761",
                font=self.font_small,
                command=lambda value=message: self.copy_answer(value),
            ).pack(anchor="w", padx=12, pady=(0, 10))

        self.after(100, self.scroll_to_bottom)

    def scroll_to_bottom(self):
        try:
            self.chat._parent_canvas.yview_moveto(1.0)
        except (AttributeError, tk.TclError):
            pass

    def copy_answer(self, message):
        self.clipboard_clear()
        self.clipboard_append(message)
        self.status.configure(text="Answer copied to clipboard.")

    def on_enter(self, event):
        if event.state & 0x0001:
            return None

        self.send_message()
        return "break"

    def send_message(self):
        if self.busy:
            return

        question = self.entry.get("1.0", "end").strip()
        if not question:
            return

        self.entry.delete("1.0", "end")
        self.add_message("You", question)

        parsed, error = parse_question(question)

        if error:
            self.add_message("WAIGE", error)
            return

        self.busy = True
        self.loading = True
        self.loading_dots = 0
        self.send_button.configure(state="disabled")
        self.animate_loading()

        threading.Thread(
            target=self.translation_worker,
            args=(parsed,),
            daemon=True,
        ).start()

    def animate_loading(self):
        if self.closed or not self.loading:
            return

        self.loading_dots = (self.loading_dots % 3) + 1
        dots = "." * self.loading_dots

        self.status.configure(
            text=f"WAIGE is analysing your question{dots}"
        )
        self.after(400, self.animate_loading)

    def translation_worker(self, parsed):
        try:
            translated = translate_text(
                parsed["phrase"],
                parsed["source"],
                parsed["target"],
            )

            answer = (
                f"Translation: {translated}\n\n"
                f"From: {parsed['source'].upper()}\n"
                f"To: {parsed['target'].upper()}\n\n"
                "Note: Check the translation in context when accuracy is important."
            )
            error = None

        except Exception:
            answer = ""
            error = (
                "I couldn't retrieve a translation right now.\n\n"
                "Please check your internet connection and try again. "
                "The translation service may also be temporarily unavailable "
                "or rate-limited."
            )

        try:
            self.after(
                0, lambda: self.finish_translation(answer, error)
            )
        except (RuntimeError, tk.TclError):
            pass

    def finish_translation(self, answer, error):
        if self.closed:
            return

        self.loading = False
        self.busy = False
        self.send_button.configure(state="normal")
        self.status.configure(text="")

        if error:
            self.add_message("WAIGE", error)
        else:
            self.add_message("WAIGE", answer)

    def new_chat(self):
        if self.busy:
            self.status.configure(
                text="Please wait for the current translation to finish."
            )
            return

        for widget in self.chat.winfo_children():
            widget.destroy()

        self.status.configure(text="")
        self.show_welcome()
        self.entry.focus_set()

    def on_close(self):
        self.closed = True
        self.loading = False

        if self.font_resource:
            self.font_resource.close()

        self.destroy()


if __name__ == "__main__":
    app = WAIGEApp()
    app.mainloop()
