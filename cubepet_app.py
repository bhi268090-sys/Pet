import base64
import json
import math
import os
import random
import re
import struct
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from cubepet_profiles import PET_PROFILES, PetProfile
try:
    from PIL import Image, ImageTk, ImageOps  # type: ignore

    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False

try:
    import ctypes
    from ctypes import wintypes

    USER32 = ctypes.windll.user32
    KERNEL32 = ctypes.windll.kernel32
except Exception:
    USER32 = None
    KERNEL32 = None

try:
    import winsound
except ImportError:
    winsound = None


class AnnoyingBlockPet:
    def __init__(self) -> None:
        # Config via environment variables:
        # - CUBEPET_SOUND=1 enables Tk bell sounds (default off)
        # - CUBEPET_STEAL_FOCUS=1 re-enables focus stealing (default off; fixes "typing blocked")
        # - CUBEPET_RESPECT_INPUT=0 disables input-respect suppression (default on)
        # - CUBEPET_ACTIVE_GRACE_S=1.2 sets "user active" threshold (seconds)
        # - CUBEPET_NOTIFICATIONS=0 disables Windows notifications (default on)
        # - CUBEPET_IMAGE_IDLE_S=0.05 minimum idle seconds for image-heist (default 0.05)
        # - CUBEPET_IMAGE_MIN_S=10 / CUBEPET_IMAGE_MAX_S=22 image-heist window (seconds)
        # - CUBEPET_DISCORD_RPC=1 enables Discord Rich Presence (default off)
        # - CUBEPET_DISCORD_RPC_CLIENT_ID=... required for Discord RPC
        # - CUBEPET_DEBUG=1 enables extra logging to cubepet.log (default off)
        # - CUBEPET_HORROR_GAME=0 disables the hidden horror mini-game (default on)
        # - CUBEPET_PROFILE=cube|aki|pamuk selects the pet profile (default cube)
        # - CUBEPET_SELECT_PET=1 shows the options window on startup (default off)
        # - CUBEPET_HUNGER=1 enables the hunger bar + feeding (default off)
        # - CUBEPET_HUNGER_FULL_S=900 seconds to drain from full->empty (default 900)
        # - CUBEPET_EDITOR_MISCHIEF=1 makes the prank editor type more often (default off)
        self.asset_dir = Path(__file__).resolve().parent
        self.log_path = self.asset_dir / "cubepet.log"
        self.image_cache_path = self.asset_dir / ".image_cache.txt"
        self.settings_path = self.asset_dir / ".cubepet_settings.json"

        self.root = tk.Tk()
        self.root.title("Ultra Nerviger Block")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")
        # .pyw: make sure callback exceptions don't disappear silently.
        self.root.report_callback_exception = self._report_callback_exception  # type: ignore[assignment]

        # Optimization: Cache screen dimensions to avoid Tcl calls in loops
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self._load_settings()
        self.pet_profile: PetProfile = PET_PROFILES.get(self.pet_profile_id, PET_PROFILES["cube"])
        self._apply_pet_profile(self.pet_profile_id, persist=False)
        self._discord_rpc = None
        self._discord_rpc_connected = False
        self._last_rpc_update_t = 0.0

        # Feeding / "data" memory used for the prank editor typing.
        self.food_tokens: list[str] = []

        # Hunger state (only active when hunger_enabled is true).
        self._hunger_last_t = time.monotonic()

        # Options window state.
        self.options_window: tk.Toplevel | None = None
        self._opt_profile_var: tk.StringVar | None = None
        self._opt_hunger_var: tk.BooleanVar | None = None
        self._opt_mischief_var: tk.BooleanVar | None = None
        self._opt_start_var: tk.BooleanVar | None = None

        self.block_size = 94
        self.root.geometry(f"{self.block_size}x{self.block_size}+140+120")

        self.block = tk.Canvas(
            self.root,
            bg="#000000",
            width=self.block_size,
            height=self.block_size,
            bd=0,
            highlightthickness=2,
            highlightbackground="#141414",
            cursor="fleur",
        )
        self.block.pack(fill="both", expand=True)

        self.x = 140.0
        self.y = 120.0
        # Smoother, less "teleporty" baseline movement.
        self.vx = random.choice([-1.0, 1.0]) * random.uniform(1.2, 2.4)
        self.vy = random.choice([-1.0, 1.0]) * random.uniform(1.2, 2.4)
        self.max_speed = 6.2
        self.escape_boost = 3.2
        self.wander_x = self.x
        self.wander_y = self.y
        self.next_wander_change = 0

        self._drag_offset_x = 0
        self._drag_offset_y = 0
        self._dragging = False
        self.ignore_drag_until_release = False
        self._press_started_at = 0.0
        self._press_start_root_x = 0
        self._press_start_root_y = 0
        self._drag_moved_since_press = False

        self.image_paths = self._load_image_cache(max_files=350)
        self._image_scan_in_progress = False
        if not self.image_paths:
            # First run without cache: do a quick scan synchronously so image-heists can start soon.
            self.image_paths = self._collect_image_paths(max_files=160)
        self._start_image_scan_background(max_files=350)

        self.heist_active = False
        self.heist_kind = "image"
        self.heist_stage = "idle"
        self.heist_direction = 1
        self.heist_exit_x = 0.0
        self.heist_exit_y = 0.0
        self.heist_target_x = 0.0
        self.heist_speed = 10.5
        self.heist_payload_window: tk.Toplevel | None = None
        self.heist_image_photo = None
        self.heist_payload_w = 0
        self.heist_payload_h = 0
        self.pending_image_photo = None
        self.heist_editor_text: tk.Text | None = None
        self.heist_editor_typing_until = 0.0
        self.heist_editor_next_type = 0.0
        self.heist_linger_until = 0.0
        # Visual rope overlay used during image-heist pull.
        self.rope_window: tk.Toplevel | None = None
        self.rope_canvas: tk.Canvas | None = None
        self.rope_line_shadow = None
        self.rope_line = None
        self.rope_phase = random.uniform(0.0, math.pi * 2.0)
        self.angry_until = 0.0
        self.angry_catch_cooldown_until = 0.0

        self.emotion = "frech"
        self.confused_until = 0.0
        self.stunned_until = 0.0
        self.face_assets = self._load_face_assets()

        self.cursor_heist_active = False
        self.cursor_heist_until = 0.0
        # Random short mouse-locks (1-2s), separate from the long "heist" behavior.
        self.window_kill_active = False
        self.window_kill_target = (0, 0)
        self.window_kill_until = 0.0
        self.next_window_kill_at = 0.0
        self.mouse_lock_active = False
        self.mouse_lock_until = 0.0
        now = time.monotonic()
        # Keep mouse locks a bit random, but not constant.
        self.next_mouse_lock_at = now + random.uniform(12.0, 24.0)
        self.close_prompt_window: tk.Toplevel | None = None
        self.youtube_prompt_window: tk.Toplevel | None = None
        self.last_youtube_answer = ""
        self._youtube_in_last = False
        self._youtube_prompted_session = False
        self.discord_prompt_window: tk.Toplevel | None = None
        self.discord_bubble_window: tk.Toplevel | None = None
        self.discord_username = self._load_cached_discord_username()
        self._discord_in_last = False
        self._discord_prompted_session = False
        # Drag revenge (2x strong drag-away): spawn clone and play cursor ping-pong for 20s.
        self.drag_shoo_count = 0
        self.drag_shoo_until = 0.0
        self.cursor_pingpong_active = False
        self.cursor_pingpong_until = 0.0
        self._cursor_pingpong_start_t = 0.0
        self._cursor_pingpong_phase_a = 0.0
        self._cursor_pingpong_phase_b = 0.0
        self._cursor_pingpong_leg_t0 = 0.0
        self._cursor_pingpong_leg_dt = 0.28
        self._cursor_pingpong_from = (0, 0)
        self._cursor_pingpong_to = (0, 0)
        self._cursor_pingpong_target_is_clone = True
        self.close_attack_active = False
        self.close_attack_until = 0.0
        self.close_attack_phase = 0.0
        
        self.pp_ball_vx = 0.0
        self.pp_ball_vy = 0.0
        self.dying = False
        self.scary_mode = False
        self._final_bloody_img = None
        self.scary_editor_count = 0
        self._static_noise_wav: bytes | None = None
        self._log_once_keys: set[str] = set()

        # Final/Horror screen state (used for the Easter egg mini-game).
        self.final_window: tk.Toplevel | None = None
        self.final_canvas: tk.Canvas | None = None
        self.final_text_idx = 0
        self.final_message = ""
        self._final_stage = "idle"  # idle | dots | ending | game
        self._final_after_show_bloody: str | None = None
        self._final_after_type_msg: str | None = None
        self._final_after_resurrect: str | None = None
        self._final_after_fx: str | None = None
        self._final_dot_centers: list[tuple[int, int]] = []
        self._final_dot_item_ids: list[int] = []
        self._final_click_seq: list[int] = []
        self._final_click_started_at = 0.0

        self._hg_active = False
        self._hg_after_tick: str | None = None
        self._hg_after_fx: str | None = None
        self._hg_started_at = 0.0
        self._hg_score = 0
        self._hg_target_score = 3
        self._hg_time_limit_s = 22.0
        self._hg_enemy_x = 0.0
        self._hg_enemy_y = 0.0
        self._hg_enemy_v = 4.2
        self._hg_collect_x = 0.0
        self._hg_collect_y = 0.0
        self._hg_noise_items: list[int] = []
        self._hg_ids: dict[str, int] = {}
        self._hg_last_mouse = (self.screen_w // 2, self.screen_h // 2)

        self.intro_active = True
        self.intro_until = time.monotonic() + 2.9
        self.intro_window: tk.Toplevel | None = None
        now = time.monotonic()
        # More frequent "classic" timings.
        self.next_image_heist_at = now + random.uniform(self.image_min_s, self.image_max_s)
        self.next_editor_heist_at = now + random.uniform(17.0, 38.0)
        self.next_clone_spawn_at = now + random.uniform(26.0, 52.0)
        self.clone_window: tk.Toplevel | None = None
        self.clone_canvas: tk.Canvas | None = None
        self.clone_x = 0.0
        self.clone_y = 0.0
        self.clone_vx = 0.0
        self.clone_vy = 0.0
        self.clone_until = 0.0
        self.clone_face_key = "frech"

        self._draw_face()
        self._show_intro_credit()

        self.block.bind("<ButtonPress-1>", self._start_drag)
        self.block.bind("<B1-Motion>", self._drag_window)
        self.block.bind("<ButtonRelease-1>", self._stop_drag)
        self.block.bind("<Enter>", self._run_away_from_mouse)
        # Right click: normal close prompt (no trolling).
        self.block.bind("<ButtonPress-3>", self._on_right_click)

        # Emergency exit (works even when a Toplevel has focus).
        self.root.bind_all("<Escape>", self._on_escape)
        self.root.bind_all("<Control-Shift-Q>", self._on_ctrl_shift_q)

        self.root.after(16, self._motion_loop)
        self.root.after(650, self._annoy_loop)
        self.root.after(900, self._youtube_watch_loop)
        self.root.after(1100, self._discord_watch_loop)
        self.root.after(1200, self._hunger_loop)

        if self.discord_rpc_enabled:
            self._init_discord_rpc()
        if self.notifications_enabled:
            self._notify_pet(f"{self.pet_profile.name} ist gestartet.")

    def _log(self, msg: str) -> None:
        # Minimal file logger because this is a .pyw (no console).
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
        except Exception:
            pass
    
    def _log_once(self, key: str, msg: str) -> None:
        try:
            keys = getattr(self, "_log_once_keys", None)
            if keys is None:
                self._log_once_keys = set()
                keys = self._log_once_keys
            if key in keys:
                return
            keys.add(key)
            self._log(msg)
        except Exception:
            pass

    def _log_exc(self, where: str) -> None:
        # Best-effort exception logger (useful for .pyw where stderr is hidden).
        try:
            import traceback

            tb = traceback.format_exc().rstrip()
            if not tb:
                return
            if bool(getattr(self, "debug_enabled", False)):
                self._log(f"EXC {where}:\n{tb}")
            else:
                # Keep logs small unless debug is enabled.
                last = tb.splitlines()[-1] if tb else "unknown"
                self._log(f"EXC {where}: {last}")
        except Exception:
            pass

    def _report_callback_exception(self, exc, val, tb) -> None:
        try:
            import traceback

            msg = "".join(traceback.format_exception(exc, val, tb)).rstrip()
            debug = bool(getattr(self, "debug_enabled", False))
            if debug:
                self._log(f"TK EXC:\n{msg}")
            else:
                last = msg.splitlines()[-1] if msg else "unknown"
                self._log(f"TK EXC: {last}")
        except Exception:
            pass

    def _after_cancel(self, after_id: str | None) -> None:
        if not after_id:
            return
        try:
            self.root.after_cancel(after_id)
        except Exception:
            pass

    def _env_bool(self, name: str, default: bool) -> bool:
        raw = os.environ.get(name, "").strip()
        if raw == "":
            return default
        if raw in {"1", "true", "TRUE", "yes", "YES", "on", "ON"}:
            return True
        if raw in {"0", "false", "FALSE", "no", "NO", "off", "OFF"}:
            return False
        return default

    def _env_float(self, name: str, default: float) -> float:
        raw = os.environ.get(name, "").strip()
        if raw == "":
            return default
        try:
            return float(raw)
        except Exception:
            return default

    def _load_persistent_settings(self) -> dict[str, object]:
        try:
            if not self.settings_path.exists():
                return {}
            raw = self.settings_path.read_text(encoding="utf-8", errors="ignore")
            data = json.loads(raw)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {}

    def _save_persistent_settings(self) -> None:
        try:
            data = {
                "version": 1,
                "profile_id": getattr(self, "pet_profile_id", "cube"),
                "show_options_on_start": bool(getattr(self, "show_options_on_start", False)),
                "hunger_enabled": bool(getattr(self, "hunger_enabled", False)),
                "editor_mischief_enabled": bool(getattr(self, "editor_mischief_enabled", False)),
                "hunger": float(getattr(self, "hunger", 1.0)),
            }
            txt = json.dumps(data, ensure_ascii=True, indent=2, sort_keys=True)
            self.settings_path.write_text(txt, encoding="utf-8")
        except Exception:
            pass

    def _normalize_profile_id(self, profile_id: str) -> str:
        pid = (profile_id or "").strip().lower()
        if pid in PET_PROFILES:
            return pid
        return "cube"

    def _load_settings(self) -> None:
        persisted = self._load_persistent_settings()

        # Disable Windows "bell" sound spam by default. Set CUBEPET_SOUND=1 to enable.
        self.sounds_enabled = self._env_bool("CUBEPET_SOUND", default=False)
        self.debug_enabled = self._env_bool("CUBEPET_DEBUG", default=False)
        self.horror_game_enabled = self._env_bool("CUBEPET_HORROR_GAME", default=True)

        # Fix for "typing gets blocked": don't steal focus by default.
        # Old behavior can be re-enabled with CUBEPET_STEAL_FOCUS=1.
        self.allow_focus_steal = self._env_bool("CUBEPET_STEAL_FOCUS", default=False)

        # When enabled (default), suppress the most disruptive behaviors while the user is actively
        # typing/clicking in other apps. Disable via CUBEPET_RESPECT_INPUT=0.
        self.respect_user_input = self._env_bool("CUBEPET_RESPECT_INPUT", default=True)

        # "Recently active" threshold for GetLastInputInfo (seconds).
        self.active_grace_s = self._env_float("CUBEPET_ACTIVE_GRACE_S", default=1.2)

        # Optional: Windows notifications / Discord Rich Presence (best-effort, no hard dependency).
        # Notifications are enabled by default. Disable via CUBEPET_NOTIFICATIONS=0.
        self.notifications_enabled = self._env_bool("CUBEPET_NOTIFICATIONS", default=True)

        self.discord_rpc_enabled = self._env_bool("CUBEPET_DISCORD_RPC", default=False)
        # Default to the requested Cupet Discord client ID when the environment
        # variable is not set.
        self.discord_rpc_client_id = os.environ.get(
            "CUBEPET_DISCORD_RPC_CLIENT_ID", "1470109631333404742"
        ).strip()

        # Image heist tuning (this is the prank users notice most).
        self.image_idle_s = self._env_float("CUBEPET_IMAGE_IDLE_S", default=0.05)
        if self.image_idle_s < 0.0:
            self.image_idle_s = 0.0
        self.image_min_s = self._env_float("CUBEPET_IMAGE_MIN_S", default=10.0)
        self.image_max_s = self._env_float("CUBEPET_IMAGE_MAX_S", default=22.0)
        if self.image_min_s < 2.0:
            self.image_min_s = 2.0
        if self.image_max_s < self.image_min_s:
            self.image_max_s = self.image_min_s

        # Pet profile / feature toggles (safe defaults, persisted values, env overrides).
        self.pet_profile_id = self._normalize_profile_id(str(persisted.get("profile_id", "cube")))
        self.show_options_on_start = bool(persisted.get("show_options_on_start", False))
        self.hunger_enabled = bool(persisted.get("hunger_enabled", False))
        self.editor_mischief_enabled = bool(persisted.get("editor_mischief_enabled", False))
        try:
            self.hunger = float(persisted.get("hunger", 1.0))
        except Exception:
            self.hunger = 1.0
        self.hunger = max(0.0, min(1.0, self.hunger))

        self.hunger_full_s = self._env_float("CUBEPET_HUNGER_FULL_S", default=900.0)
        if self.hunger_full_s < 30.0:
            self.hunger_full_s = 30.0

        env_profile = os.environ.get("CUBEPET_PROFILE", "").strip()
        if env_profile:
            self.pet_profile_id = self._normalize_profile_id(env_profile)
        if self._env_bool("CUBEPET_SELECT_PET", default=False):
            self.show_options_on_start = True
        if os.environ.get("CUBEPET_HUNGER", "").strip() != "":
            self.hunger_enabled = self._env_bool("CUBEPET_HUNGER", default=self.hunger_enabled)
        if os.environ.get("CUBEPET_EDITOR_MISCHIEF", "").strip() != "":
            self.editor_mischief_enabled = self._env_bool(
                "CUBEPET_EDITOR_MISCHIEF", default=self.editor_mischief_enabled
            )

    def _apply_pet_profile(self, profile_id: str, persist: bool = True) -> None:
        pid = self._normalize_profile_id(profile_id)
        self.pet_profile_id = pid
        self.pet_profile = PET_PROFILES.get(pid, PET_PROFILES["cube"])
        try:
            self.root.title(f"{self.pet_profile.name} - Ultra Nerviger Block")
        except Exception:
            pass

        # If the options window is open, keep the selection in sync.
        try:
            if self._opt_profile_var is not None:
                self._opt_profile_var.set(self.pet_profile_id)
        except Exception:
            pass

        if persist:
            self._save_persistent_settings()

        # Best-effort: refresh face/HUD when switching pets at runtime.
        if getattr(self, "block", None) is not None:
            try:
                self._draw_face()
            except Exception:
                pass

    def _user_is_active(self) -> bool:
        if not self.respect_user_input:
            return False
        return self._user_idle_seconds() < self.active_grace_s

    def _can_start_major_prank(self, now: float, user_active: bool | None = None) -> bool:
        if user_active is None:
            user_active = self._user_is_active()
        if self.intro_active:
            return False
        if self._dragging or self.ignore_drag_until_release:
            return False
        if self.scary_mode:
            return False
        if (
            self.close_prompt_window is not None
            or self.youtube_prompt_window is not None
            or getattr(self, "options_window", None) is not None
        ):
            return False
        if self.discord_prompt_window is not None:
            return False
        if self.heist_active or self.cursor_heist_active or self.cursor_pingpong_active:
            return False
        if self.heist_payload_window is not None:
            return False
        if self.mouse_lock_active or self.close_attack_active:
            return False
        if self.window_kill_active:
            return False
        if now < self.stunned_until:
            return False
        if user_active:
            return False
        return True


    def _load_image_cache(self, max_files: int) -> list[Path]:
        # Optimization: keep a cache of image paths to avoid walking the whole home folder every start.
        try:
            if not self.image_cache_path.exists():
                return []
            raw = self.image_cache_path.read_text(encoding="utf-8", errors="ignore")
            out: list[Path] = []
            exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ppm", ".pgm"}
            if not PIL_AVAILABLE:
                exts = {".png", ".gif", ".ppm", ".pgm"}
            for line in raw.splitlines():
                s = line.strip()
                if not s:
                    continue
                p = Path(s)
                if p.suffix.lower() not in exts:
                    continue
                if not p.exists():
                    continue
                out.append(p)
                if len(out) >= max_files:
                    break
            random.shuffle(out)
            if out:
                self._log(f"Loaded image cache: {len(out)} files.")
            return out
        except Exception:
            return []

    def _save_image_cache(self, paths: list[Path]) -> None:
        try:
            txt = "\n".join(str(p) for p in paths)
            self.image_cache_path.write_text(txt, encoding="utf-8")
        except Exception:
            pass

    def _start_image_scan_background(self, max_files: int) -> None:
        if self._image_scan_in_progress:
            return
        self._image_scan_in_progress = True

        def worker() -> None:
            try:
                paths = self._collect_image_paths(max_files=max_files)
                self._save_image_cache(paths)

                def apply() -> None:
                    self.image_paths = paths
                    self._image_scan_in_progress = False
                    self._log(f"Image scan done: {len(paths)} files.")

                self.root.after(0, apply)
            except Exception:
                self._image_scan_in_progress = False
                if self.debug_enabled:
                    self._log_exc("_start_image_scan_background.worker")

        threading.Thread(target=worker, daemon=True).start()

    def _make_noactivate(self, win: tk.Toplevel) -> None:
        # Bugfix: prevent prank windows from stealing focus (avoids "typing gets blocked").
        if USER32 is None:
            return
        try:
            hwnd = int(win.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = USER32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            USER32.SetWindowLongW(hwnd, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW)
        except Exception:
            self._log_once("noactivate_failed", "Failed to mark prank window as NOACTIVATE.")
            if self.debug_enabled:
                self._log_exc("_make_noactivate")
    
    def _make_clickthrough(self, win: tk.Toplevel) -> None:
        # Used for fullscreen overlay visuals (rope). Best-effort.
        if USER32 is None:
            return
        try:
            hwnd = int(win.winfo_id())
            GWL_EXSTYLE = -20
            WS_EX_LAYERED = 0x00080000
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_NOACTIVATE = 0x08000000
            WS_EX_TOOLWINDOW = 0x00000080
            style = USER32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            USER32.SetWindowLongW(
                hwnd,
                GWL_EXSTYLE,
                style | WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW,
            )
        except Exception:
            self._log_once("clickthrough_failed", "Failed to mark overlay window as click-through.")
            if self.debug_enabled:
                self._log_exc("_make_clickthrough")

    # (removed: pause/status UI)

    def _user_idle_seconds(self) -> float:
        # Uses Windows GetLastInputInfo when available; otherwise returns a "very idle" value.
        if USER32 is None or KERNEL32 is None:
            return 9999.0
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if not USER32.GetLastInputInfo(ctypes.byref(lii)):
                return 9999.0

            now_ms = int(KERNEL32.GetTickCount() & 0xFFFFFFFF)
            last_ms = int(lii.dwTime & 0xFFFFFFFF)
            # Handle 32-bit wraparound.
            elapsed_ms = (now_ms - last_ms) & 0xFFFFFFFF
            return float(elapsed_ms) / 1000.0
        except Exception:
            return 9999.0

    def _init_discord_rpc(self) -> None:
        # Optional integration: requires pypresence and a Discord app client id.
        if not self.discord_rpc_client_id:
            self._log("Discord RPC enabled but CUBEPET_DISCORD_RPC_CLIENT_ID is empty.")
            return
        try:
            from pypresence import Presence  # type: ignore
        except Exception:
            self._log("Discord RPC enabled but pypresence import failed.")
            return

        try:
            rpc = Presence(self.discord_rpc_client_id)
            rpc.connect()
            self._discord_rpc = rpc
            self._discord_rpc_connected = True
            self._update_discord_rpc(force=True)
        except Exception:
            self._discord_rpc = None
            self._discord_rpc_connected = False
            self._log("Discord RPC connect failed.")

    def _update_discord_rpc(self, force: bool = False) -> None:
        now = time.monotonic()
        
        # Try to reconnect if enabled but not connected
        if self.discord_rpc_enabled and not self._discord_rpc_connected:
            if now - self._last_rpc_update_t > 60.0:
                self._last_rpc_update_t = now
                self._init_discord_rpc()
            return

        if not self._discord_rpc_connected or self._discord_rpc is None:
            return

        if (not force) and (now - self._last_rpc_update_t) < 15.0:
            return
        try:
            self._discord_rpc.update(
                details=f"Spielt {getattr(self.pet_profile, 'name', 'CubePet')}",
                state="Ultra Nerviger Block",
            )
            self._last_rpc_update_t = now
        except Exception:
            # Discord closed / IPC broken. We'll stop trying silently.
            self._discord_rpc_connected = False
            self._discord_rpc = None

    def _notify(self, title: str, message: str) -> None:
        # Best-effort Windows notification; tries winotify, then win10toast.
        if not self.notifications_enabled:
            return
        try:
            from winotify import Notification  # type: ignore

            toast = Notification(app_id="CubePet", title=title, msg=message, duration="short")
            toast.show()
            return
        except Exception:
            self._log("winotify notification failed.")
            pass
        try:
            from win10toast import ToastNotifier  # type: ignore

            ToastNotifier().show_toast(title, message, duration=4, threaded=True)
            return
        except Exception:
            self._log("win10toast notification failed.")
            pass

    def _notify_pet(self, message: str) -> None:
        try:
            title = getattr(self, "pet_profile", None)
            name = title.name if title is not None else "CubePet"
        except Exception:
            name = "CubePet"
        self._notify(name, message)

    def _ding(self) -> None:
        if self.sounds_enabled:
            try:
                self.root.bell()
            except tk.TclError:
                pass
    
    def _on_escape(self, _event=None):
        # Prefer "escape hatch" behavior inside the horror flow instead of killing the whole app.
        try:
            if getattr(self, "_hg_active", False):
                self._horror_game_end(win=False, aborted=True)
                return "break"
            if getattr(self, "dying", False) and getattr(self, "final_window", None) is not None:
                self._resurrect_pet()
                return "break"
            self.root.destroy()
        except Exception:
            pass
        return "break"

    def _on_ctrl_shift_q(self, _event=None):
        try:
            self.root.destroy()
        except Exception:
            pass
        return "break"

    def _start_drag(self, event) -> None:
        if (
            self.intro_active
            or self.close_prompt_window is not None
            or self.youtube_prompt_window is not None
            or self.options_window is not None
            or self.cursor_pingpong_active
        ):
            return
        self._stop_heist()
        self.cursor_heist_active = False
        self._dragging = True
        self.ignore_drag_until_release = False
        self._drag_offset_x = event.x
        self._drag_offset_y = event.y
        self._press_started_at = time.monotonic()
        self._press_start_root_x = event.x_root
        self._press_start_root_y = event.y_root
        self._drag_moved_since_press = False

    def _drag_window(self, event) -> None:
        if self.ignore_drag_until_release:
            return
        if (
            abs(event.x_root - self._press_start_root_x) > 6
            or abs(event.y_root - self._press_start_root_y) > 6
        ):
            self._drag_moved_since_press = True
        x = event.x_root - self._drag_offset_x
        y = event.y_root - self._drag_offset_y
        self._move_clamped(x, y)

    def _stop_drag(self, event) -> None:
        was_click = (
            not self._drag_moved_since_press
            and time.monotonic() - self._press_started_at < 0.35
            and abs(event.x_root - self._press_start_root_x) <= 8
            and abs(event.y_root - self._press_start_root_y) <= 8
        )
        self._dragging = False
        self.ignore_drag_until_release = False

        # Fix: Prevent instant catch if angry by adding a grace period
        now = time.monotonic()
        self.stunned_until = max(self.stunned_until, now + 0.7)
        self.angry_catch_cooldown_until = max(self.angry_catch_cooldown_until, now + 2.5)

        if was_click:
            self._on_pet_clicked()
        else:
            # "Normal weg ziehen": big drag move counts. Two in a row triggers ping-pong.
            dx = float(event.x_root - self._press_start_root_x)
            dy = float(event.y_root - self._press_start_root_y)
            dist = (dx * dx + dy * dy) ** 0.5
            now = time.monotonic()
            if dist >= 120.0 and not self.intro_active:
                if now > self.drag_shoo_until:
                    self.drag_shoo_count = 0
                self.drag_shoo_count += 1
                self.drag_shoo_until = now + 6.0
                if self.drag_shoo_count >= 2:
                    self.drag_shoo_count = 0
                    self.drag_shoo_until = 0.0
                    self._start_cursor_pingpong(now)

    def _run_away_from_mouse(self, event) -> None:
        if (
            self.intro_active
            or self.heist_active
            or self.cursor_heist_active
            or self.cursor_pingpong_active
            or self.close_attack_active
            or self.close_prompt_window is not None
            or getattr(self, "options_window", None) is not None
        ):
            return
        if random.random() < 0.96:
            away_x = self.x - event.x_root
            away_y = self.y - event.y_root
            mag = max(1.0, (away_x * away_x + away_y * away_y) ** 0.5)
            self.vx += (away_x / mag) * self.escape_boost
            self.vy += (away_y / mag) * self.escape_boost
            if random.random() < 0.4:
                self._ding()

    def _move_clamped(self, x: int, y: int) -> None:
        max_x = max(0, self.screen_w - self.block_size)
        max_y = max(0, self.screen_h - self.block_size)
        x = max(0, min(x, max_x))
        y = max(0, min(y, max_y))
        self.x = float(x)
        self.y = float(y)
        self.root.geometry(f"+{x}+{y}")

    def _motion_loop(self) -> None:
        if self.dying:
            return
        now = time.monotonic()

        if self.intro_active:
            self.vx = 0.0
            self.vy = 0.0
            if now >= self.intro_until:
                self._end_intro_credit()
            self._update_emotion(now)
            self.root.after(16, self._motion_loop)
            return

        if self.close_attack_active and now >= self.close_attack_until:
            self.close_attack_active = False

        if self.cursor_heist_active and now >= self.cursor_heist_until:
            self.cursor_heist_active = False

        if self.window_kill_active and now >= self.window_kill_until:
            self.window_kill_active = False

        if self.mouse_lock_active and now >= self.mouse_lock_until:
            self.mouse_lock_active = False

        if self.cursor_pingpong_active and now >= self.cursor_pingpong_until:
            self.cursor_pingpong_active = False
            # Give both a little kick so they don't "stick" after ping-pong ends.
            self.vx += random.uniform(-1.2, 1.2)
            self.vy += random.uniform(-1.2, 1.2)
            if self.clone_window is not None:
                self.clone_vx += random.uniform(-2.0, 2.0)
                self.clone_vy += random.uniform(-2.0, 2.0)

        if (
            self.close_prompt_window is not None
            or self.youtube_prompt_window is not None
            or self.options_window is not None
        ):
            self.vx = 0.0
            self.vy = 0.0
            self._update_emotion(now)
            self.root.after(16, self._motion_loop)
            return

        if self.discord_prompt_window is not None:
            # Don't move while asking for the username (typing + cursor control).
            self.vx = 0.0
            self.vy = 0.0
            self._update_emotion(now)
            self.root.after(16, self._motion_loop)
            return

        if self.cursor_pingpong_active:
            # Freeze movement while playing ping-pong with the cursor.
            self.vx = 0.0
            self.vy = 0.0
            self._pingpong_move_pets(now)
            self._pingpong_cursor(now)
            self._update_emotion(now)
            # Higher update rate makes the cursor effectively "unmovable" by the user.
            self.root.after(8, self._motion_loop)
            return

        if self.heist_active:
            self._heist_tick()
        elif not self._dragging and not self.ignore_drag_until_release:
            if now >= self.stunned_until:
                cursor_target = None
                if now < self.angry_until and USER32 is not None:
                    cursor_target = self._get_cursor_pos()
                if cursor_target is not None:
                    tx = float(cursor_target[0] - self.block_size / 2)
                    ty = float(cursor_target[1] - self.block_size / 2)
                    if now >= self.angry_catch_cooldown_until:
                        cx = self.x + self.block_size / 2
                        cy = self.y + self.block_size / 2
                        dx = cursor_target[0] - cx
                        dy = cursor_target[1] - cy
                        if (dx * dx + dy * dy) ** 0.5 <= 22.0:
                            self._start_angry_catch(now)
                            cursor_target = None
                if cursor_target is not None:
                    self._steer_to_target(tx, ty, force=0.72)
                    self._clamp_velocity(self.max_speed + 2.8)
                else:
                    tx, ty = self._choose_target()
                    force = 0.9 if self.scary_mode else 0.42
                    limit = self.max_speed * 1.5 if self.scary_mode else self.max_speed
                    self._steer_to_target(tx, ty, force=force)
                    self._clamp_velocity(limit)
                self._advance_position(allow_offscreen=False)
            else:
                self.vx *= 0.7
                self.vy *= 0.7

        if self.clone_window is not None:
            self._clone_tick(now)

        if self.close_attack_active:
            self._whirl_cursor()
        elif self.cursor_heist_active:
            self._pull_cursor_to_cube()
        elif self.window_kill_active:
            self._update_window_kill_cursor()
        elif self.mouse_lock_active:
            self._pull_cursor_to_cube()

        self._update_emotion(now)

        self.root.after(16, self._motion_loop)

    def _choose_target(self) -> tuple[float, float]:
        if self.next_wander_change <= 0 or random.random() < 0.04:
            max_x = max(0, self.screen_w - self.block_size)
            max_y = max(0, self.screen_h - self.block_size)
            self.wander_x = random.randint(0, max_x)
            self.wander_y = random.randint(0, max_y)
            self.next_wander_change = random.randint(24, 130)
        else:
            self.next_wander_change -= 1
        return (self.wander_x, self.wander_y)

    def _steer_to_target(self, tx: float, ty: float, force: float) -> None:
        dx = tx - self.x
        dy = ty - self.y
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        self.vx += (dx / dist) * force
        self.vy += (dy / dist) * force
        # Small jitter keeps it alive without looking glitchy.
        self.vx += random.uniform(-0.06, 0.06)
        self.vy += random.uniform(-0.06, 0.06)
        
        if self.scary_mode:
            self.vx += random.uniform(-0.8, 0.8)
            self.vy += random.uniform(-0.8, 0.8)

    def _clamp_velocity(self, limit: float) -> None:
        speed = (self.vx * self.vx + self.vy * self.vy) ** 0.5
        if speed > limit:
            factor = limit / speed
            self.vx *= factor
            self.vy *= factor
        self.vx *= 0.992
        self.vy *= 0.992

    def _advance_position(self, allow_offscreen: bool) -> None:
        self.x += self.vx
        self.y += self.vy

        if allow_offscreen:
            min_x = -self.block_size - 150
            max_x = self.screen_w + 150
            min_y = -40
            max_y = self.screen_h - self.block_size + 40
            self.x = max(min_x, min(self.x, max_x))
            self.y = max(min_y, min(self.y, max_y))
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
            return

        max_x = max(0, self.screen_w - self.block_size)
        max_y = max(0, self.screen_h - self.block_size)

        bounced = False
        if self.x < 0:
            self.x = 0
            self.vx = abs(self.vx) * 0.95
            bounced = True
        elif self.x > max_x:
            self.x = float(max_x)
            self.vx = -abs(self.vx) * 0.95
            bounced = True

        if self.y < 0:
            self.y = 0
            self.vy = abs(self.vy) * 0.95
            bounced = True
        elif self.y > max_y:
            self.y = float(max_y)
            self.vy = -abs(self.vy) * 0.95
            bounced = True

        if bounced and random.random() < 0.34:
            self._ding()

        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

    def _start_window_kill(self) -> bool:
        if USER32 is None:
            return False
        hwnd = USER32.GetForegroundWindow()
        if not hwnd:
            return False
        if hwnd == int(self.root.winfo_id()):
            return False
        
        rect = wintypes.RECT()
        if USER32.GetWindowRect(hwnd, ctypes.byref(rect)) == 0:
            return False
            
        tx = rect.right - 25
        ty = rect.top + 15
        tx = max(0, min(tx, self.screen_w - 5))
        ty = max(0, min(ty, self.screen_h - 5))

        self.window_kill_target = (tx, ty)
        self.window_kill_active = True
        self.window_kill_until = time.monotonic() + 3.5
        self._ding()
        return True

    def _update_window_kill_cursor(self) -> None:
        if USER32 is None: return
        cpos = self._get_cursor_pos()
        if not cpos: return
        cx, cy = cpos
        tx, ty = self.window_kill_target
        dx, dy = tx - cx, ty - cy
        dist = (dx * dx + dy * dy) ** 0.5
        
        if dist < 15.0:
            USER32.SetCursorPos(tx, ty)
            USER32.mouse_event(0x0002, 0, 0, 0, 0) # Down
            USER32.mouse_event(0x0004, 0, 0, 0, 0) # Up
            self.window_kill_active = False
            self.angry_until = time.monotonic() + 1.5
        else:
            step = min(45.0, dist * 0.55)
            nx = int(cx + (dx / dist) * step)
            ny = int(cy + (dy / dist) * step)
            USER32.SetCursorPos(nx, ny)

    def _start_angry_catch(self, now: float) -> None:
        if self.cursor_heist_active:
            return
        self.cursor_heist_active = True
        self.cursor_heist_until = max(self.cursor_heist_until, now + 6.0)
        self.angry_until = 0.0
        self.angry_catch_cooldown_until = now + 0.6
        self.mouse_lock_active = False
        self.vx += random.choice([-1.0, 1.0]) * random.uniform(2.6, 4.4)
        self.vy += random.uniform(-2.8, 2.8)
        self._clamp_velocity(self.max_speed + 3.6)
        self._ding()

    def _start_cursor_heist(self) -> None:
        self.cursor_heist_active = True
        # Keep the "shake revenge" shorter; random mouse locks cover the short cases.
        self.cursor_heist_until = time.monotonic() + 3.0
        self.vx += random.choice([-1.0, 1.0]) * random.uniform(4.0, 6.3)
        self.vy += random.uniform(-2.4, 2.4)
        self._ding()

    def _pull_cursor_to_cube(self) -> None:
        if USER32 is None:
            return
        pos = self._get_cursor_pos()
        if pos is None:
            return
        cx, cy = pos
        target_x = int(self.x + self.block_size / 2 + random.randint(-10, 10))
        target_y = int(self.y + self.block_size / 2 + random.randint(-10, 10))
        dx = target_x - cx
        dy = target_y - cy
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        step = min(26.0, dist * 0.45)
        nx = int(cx + (dx / dist) * step)
        ny = int(cy + (dy / dist) * step)
        nx = max(0, min(nx, self.screen_w - 1))
        ny = max(0, min(ny, self.screen_h - 1))
        USER32.SetCursorPos(nx, ny)

    def _start_cursor_pingpong(self, now: float) -> None:
        if USER32 is None:
            return
        if self.close_prompt_window is not None or self.youtube_prompt_window is not None:
            return

        # Stop other cursor games and heists.
        self._stop_heist()
        self.cursor_heist_active = False
        self.mouse_lock_active = False
        self.close_attack_active = False
        self.ignore_drag_until_release = False
        self._dragging = False
        self.stunned_until = max(self.stunned_until, now + 0.4)

        if self.clone_window is None:
            self._spawn_clone(now)
        # Make sure the clone doesn't instantly vanish right after ping-pong ends.
        self.clone_until = max(self.clone_until, now + 25.0)

        self.cursor_pingpong_active = True
        self.cursor_pingpong_until = now + 20.0
        
        # Setup "Real" Ping Pong
        # 1. Position Pets at edges
        self.x = 10.0
        self.y = self.screen_h / 2 - self.block_size / 2
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
        
        if self.clone_window is not None:
            self.clone_x = float(self.screen_w - self.block_size - 10)
            self.clone_y = self.screen_h / 2 - self.block_size / 2
            self.clone_window.geometry(f"+{int(self.clone_x)}+{int(self.clone_y)}")

        # 2. Launch Ball (Cursor) from center
        start_x = self.screen_w // 2
        start_y = self.screen_h // 2
        USER32.SetCursorPos(start_x, start_y)
        
        # Random velocity
        speed = random.uniform(10.0, 15.0)
        angle = random.uniform(-0.6, 0.6) # radians
        if random.random() < 0.5:
            angle += math.pi
        
        self.pp_ball_vx = math.cos(angle) * speed
        self.pp_ball_vy = math.sin(angle) * speed

    def _pingpong_move_pets(self, now: float) -> None:
        # AI Logic: Paddles follow the ball (cursor)
        cpos = self._get_cursor_pos()
        if not cpos:
            return
        _, cy = cpos
        
        target_y = cy - self.block_size / 2
        speed_limit = 14.0 
        
        # Move Main Pet (Left)
        dy = target_y - self.y
        if abs(dy) > speed_limit:
            self.y += speed_limit if dy > 0 else -speed_limit
        else:
            self.y = target_y
            
        max_y = max(0, self.screen_h - self.block_size)
        self.y = max(0.0, min(self.y, float(max_y)))
        self.x = 10.0
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")

        # Move Clone (Right)
        if self.clone_window is not None and self.clone_window.winfo_exists():
            dy_clone = target_y - self.clone_y
            if abs(dy_clone) > speed_limit:
                self.clone_y += speed_limit if dy_clone > 0 else -speed_limit
            else:
                self.clone_y = target_y
            
            self.clone_y = max(0.0, min(self.clone_y, float(max_y)))
            self.clone_x = float(self.screen_w - self.block_size - 10)
            self.clone_window.geometry(f"+{int(self.clone_x)}+{int(self.clone_y)}")

    def _pingpong_cursor(self, now: float) -> None:
        if USER32 is None:
            return

        cpos = self._get_cursor_pos()
        if not cpos:
            return
        cx, cy = cpos

        # Physics Step
        nx = cx + self.pp_ball_vx
        ny = cy + self.pp_ball_vy

        # Bounce Top/Bottom
        if ny <= 0:
            ny = 0
            self.pp_ball_vy = abs(self.pp_ball_vy)
        elif ny >= self.screen_h - 1:
            ny = self.screen_h - 1
            self.pp_ball_vy = -abs(self.pp_ball_vy)

        # Paddle Collision
        # Pet (Left)
        if nx < self.x + self.block_size:
            if self.y - 10 < ny < self.y + self.block_size + 10:
                nx = self.x + self.block_size + 5
                self.pp_ball_vx = abs(self.pp_ball_vx) * 1.05
                offset = (ny - (self.y + self.block_size / 2)) / (self.block_size / 2)
                self.pp_ball_vy += offset * 3.0
                self._ding()

        # Clone (Right)
        if self.clone_window is not None and self.clone_window.winfo_exists():
            if nx > self.clone_x:
                if self.clone_y - 10 < ny < self.clone_y + self.block_size + 10:
                    nx = self.clone_x - 5
                    self.pp_ball_vx = -abs(self.pp_ball_vx) * 1.05
                    offset = (ny - (self.clone_y + self.block_size / 2)) / (self.block_size / 2)
                    self.pp_ball_vy += offset * 3.0
                    self._ding()

        # Score / Reset
        if nx < -50 or nx > self.screen_w + 50:
            nx = self.screen_w // 2
            ny = self.screen_h // 2
            speed = random.uniform(10.0, 15.0)
            angle = random.uniform(-0.6, 0.6)
            if random.random() < 0.5:
                angle += math.pi
            self.pp_ball_vx = math.cos(angle) * speed
            self.pp_ball_vy = math.sin(angle) * speed

        USER32.SetCursorPos(int(nx), int(ny))

    def _pet_center(self) -> tuple[int, int]:
        return (int(self.x + self.block_size / 2), int(self.y + self.block_size / 2))

    def _clone_center_or_pet(self) -> tuple[int, int]:
        if self.clone_window is None or not self.clone_window.winfo_exists():
            return self._pet_center()
        return (int(self.clone_x + self.block_size / 2), int(self.clone_y + self.block_size / 2))

    def _get_cursor_pos(self) -> tuple[int, int] | None:
        if USER32 is None:
            return None
        point = wintypes.POINT()
        if USER32.GetCursorPos(ctypes.byref(point)) == 0:
            return None
        return (int(point.x), int(point.y))

    def _on_pet_clicked(self) -> None:
        if self.intro_active:
            return
        # Left click is used for dragging; keep it as a harmless "poke".
        now = time.monotonic()
        self.confused_until = max(self.confused_until, now + random.uniform(0.35, 0.85))

    def _on_right_click(self, _event) -> None:
        if self.intro_active:
            return
        self._show_close_prompt()

    def _show_close_prompt(self) -> None:
        self._hide_close_prompt()
        self._hide_options_window()

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#ffd9ec")

        frame = tk.Frame(win, bg="#ffd9ec", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)

        label = tk.Label(
            frame,
            text="willst du mich wirklich schliessen?",
            bg="#ffd9ec",
            fg="#3b0a1d",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=7,
        )
        label.pack()

        buttons = tk.Frame(frame, bg="#ffd9ec")
        buttons.pack(pady=(0, 8))
        yes_btn = tk.Button(
            buttons,
            text="Ja",
            width=7,
            command=self._close_prompt_yes,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        yes_btn.pack(side="left", padx=(0, 6))
        no_btn = tk.Button(
            buttons,
            text="Nein",
            width=7,
            command=self._close_prompt_no,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        no_btn.pack(side="left", padx=(0, 6))
        opt_btn = tk.Button(
            buttons,
            text="Optionen",
            width=9,
            command=self._close_prompt_options,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        opt_btn.pack(side="left")

        win.update_idletasks()
        px = int(self.x + self.block_size + 10)
        py = int(self.y - 10)
        max_x = max(0, self.screen_w - win.winfo_width())
        max_y = max(0, self.screen_h - win.winfo_height())
        px = max(0, min(px, max_x))
        py = max(0, min(py, max_y))
        win.geometry(f"+{px}+{py}")

        self.close_prompt_window = win
        # No sound here (user asked for no Windows sound spam).

    def _close_prompt_yes(self) -> None:
        self._hide_close_prompt()
        self._start_final_sequence()

    def _close_prompt_options(self) -> None:
        self._hide_close_prompt()
        self._show_options_window()

    def _start_final_sequence(self) -> None:
        if self.dying:
            return

        self.dying = True
        self.scary_mode = False
        self._hg_active = False
        self._final_stage = "dots"
        self._final_click_seq = []
        self._final_click_started_at = 0.0
        self._after_cancel(self._final_after_show_bloody)
        self._after_cancel(self._final_after_type_msg)
        self._after_cancel(self._final_after_resurrect)
        self._after_cancel(self._final_after_fx)
        self._final_after_show_bloody = None
        self._final_after_type_msg = None
        self._final_after_resurrect = None
        self._final_after_fx = None

        self.root.withdraw()

        if self.final_window is not None and self.final_window.winfo_exists():
            try:
                self.final_window.destroy()
            except Exception:
                pass
        self.final_window = None
        self.final_canvas = None
        
        self.final_window = tk.Toplevel(self.root)
        # Keep cursor visible for the (hidden) click-sequence Easter egg.
        self.final_window.configure(bg="black", cursor="arrow")
        self.final_window.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        self.final_window.overrideredirect(True)
        self.final_window.attributes("-topmost", True)
        
        self.final_canvas = tk.Canvas(self.final_window, bg="black", highlightthickness=0)
        self.final_canvas.pack(fill="both", expand=True)
        self.final_canvas.bind("<Motion>", self._hg_on_motion)
        if self.horror_game_enabled:
            self.final_canvas.bind("<Button-1>", self._on_final_canvas_click)
        
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        r = 25
        gap = 90
        self._final_dot_centers = []
        self._final_dot_item_ids = []
        for i in range(-1, 2):
            x = cx + i * gap
            self._final_dot_centers.append((x, cy))
            item = self.final_canvas.create_oval(
                x - r,
                cy - r,
                x + r,
                cy + r,
                fill="#ff0000",
                outline="#ff0000",
                tags=("dots", f"dot{len(self._final_dot_centers)-1}"),
            )
            self._final_dot_item_ids.append(item)
            
        self._final_dots_fx()
        self._final_after_show_bloody = self.root.after(10000, self._show_bloody_ending)

    def _hg_on_motion(self, event) -> None:
        # Motion fallback (when USER32 cursor APIs are unavailable).
        try:
            self._hg_last_mouse = (int(event.x), int(event.y))
        except Exception:
            pass

    def _final_dots_fx(self) -> None:
        # Subtle pulse/flicker so the dots feel like "eyes".
        if self._final_stage != "dots":
            return
        if self.final_canvas is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return

        base_r = 25
        pulse = random.randint(-3, 3)
        r = max(16, base_r + pulse)
        for idx, (cx, cy) in enumerate(self._final_dot_centers):
            if idx >= len(self._final_dot_item_ids):
                continue
            item = self._final_dot_item_ids[idx]
            try:
                self.final_canvas.coords(item, cx - r, cy - r, cx + r, cy + r)
                # Random tiny brightness changes look like a CRT glitch.
                c = "#ff0000" if random.random() < 0.75 else "#b30000"
                self.final_canvas.itemconfig(item, fill=c, outline=c)
            except Exception:
                continue

        # Very slight background flicker.
        try:
            bg = "#000000" if random.random() < 0.86 else "#050000"
            self.final_canvas.configure(bg=bg)
        except Exception:
            pass

        self._after_cancel(self._final_after_fx)
        self._final_after_fx = self.root.after(random.randint(70, 140), self._final_dots_fx)

    def _on_final_canvas_click(self, event) -> None:
        if not self.horror_game_enabled:
            return
        if self._final_stage != "dots":
            return
        if self.final_canvas is None:
            return

        # Identify which dot was clicked (if any).
        try:
            ex = int(getattr(event, "x", -9999))
            ey = int(getattr(event, "y", -9999))
        except Exception:
            return
        hit = None
        for idx, (cx, cy) in enumerate(self._final_dot_centers):
            dx = ex - cx
            dy = ey - cy
            if (dx * dx + dy * dy) ** 0.5 <= 32.0:
                hit = idx
                break
        if hit is None:
            return

        # Hidden sequence: click the three dots left -> middle -> right quickly.
        secret = [0, 1, 2]
        now = time.monotonic()
        if self._final_click_started_at <= 0.0 or (now - self._final_click_started_at) > 1.6:
            self._final_click_started_at = now
            self._final_click_seq = []
        self._final_click_seq.append(hit)

        # If the sequence diverges, reset but allow restarting immediately.
        prefix_ok = self._final_click_seq == secret[: len(self._final_click_seq)]
        if not prefix_ok:
            self._final_click_started_at = now
            self._final_click_seq = [hit] if hit == secret[0] else []
            return

        if len(self._final_click_seq) >= len(secret):
            self._final_click_seq = []
            self._final_click_started_at = 0.0
            self._start_horror_game()

    def _start_horror_game(self) -> None:
        # Convert the final screen into a hidden horror mini-game (Easter egg).
        if self.final_canvas is None or self.final_window is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return

        self._final_stage = "game"
        self._hg_active = True
        self._hg_started_at = time.monotonic()
        self._hg_score = 0
        self._hg_enemy_v = random.uniform(3.8, 4.9)
        self._hg_noise_items = []
        self._hg_ids = {}

        # Cancel the normal ending flow.
        self._after_cancel(self._final_after_show_bloody)
        self._after_cancel(self._final_after_fx)
        self._final_after_show_bloody = None
        self._final_after_fx = None

        # Make it harder to "read" the screen: hide cursor once the game starts.
        try:
            self.final_window.configure(cursor="none")
        except Exception:
            pass

        # Setup scene.
        self.final_canvas.delete("all")
        self.final_canvas.configure(bg="black")

        w = max(1, int(self.screen_w))
        h = max(1, int(self.screen_h))

        # Player is the cursor (tracked globally on Windows, otherwise via <Motion> events).
        px, py = self._get_cursor_pos() or self._hg_last_mouse
        px = max(0, min(int(px), w - 1))
        py = max(0, min(int(py), h - 1))
        self._hg_ids["player"] = self.final_canvas.create_oval(
            px - 6, py - 6, px + 6, py + 6, fill="#c7d2fe", outline="#111827", width=2, tags="hg"
        )

        # Enemy: a big "eye" that hunts you.
        edge = random.choice(["l", "r", "t", "b"])
        if edge == "l":
            self._hg_enemy_x, self._hg_enemy_y = (-40.0, float(random.randint(0, h)))
        elif edge == "r":
            self._hg_enemy_x, self._hg_enemy_y = (float(w + 40), float(random.randint(0, h)))
        elif edge == "t":
            self._hg_enemy_x, self._hg_enemy_y = (float(random.randint(0, w)), -40.0)
        else:
            self._hg_enemy_x, self._hg_enemy_y = (float(random.randint(0, w)), float(h + 40))

        ex, ey = int(self._hg_enemy_x), int(self._hg_enemy_y)
        self._hg_ids["enemy_outer"] = self.final_canvas.create_oval(
            ex - 26, ey - 18, ex + 26, ey + 18, fill="#2a0000", outline="#7f0000", width=3, tags="hg"
        )
        self._hg_ids["enemy_iris"] = self.final_canvas.create_oval(
            ex - 10, ey - 10, ex + 10, ey + 10, fill="#ff0000", outline="#b30000", width=2, tags="hg"
        )
        self._hg_ids["enemy_pupil"] = self.final_canvas.create_oval(
            ex - 4, ey - 4, ex + 4, ey + 4, fill="#000000", outline="#000000", width=1, tags="hg"
        )

        # Collectible "sigil".
        self._hg_spawn_collectible()

        # Noise overlay (re-used items, updated in the FX tick).
        for _ in range(90):
            x = random.randint(0, w)
            y = random.randint(0, h)
            item = self.final_canvas.create_line(
                x, y, x + random.randint(1, 120), y, fill="#0b0000", width=random.randint(1, 3), tags="hg_noise"
            )
            self._hg_noise_items.append(item)
        try:
            self.final_canvas.tag_lower("hg_noise")
        except Exception:
            pass

        # Minimal HUD (kept subtle).
        self._hg_ids["hud"] = self.final_canvas.create_text(
            20,
            18,
            text="",
            fill="#a30000",
            font=("Consolas", 14, "bold"),
            anchor="w",
            tags="hg",
        )

        # Kick off loops.
        self._after_cancel(self._hg_after_tick)
        self._after_cancel(self._hg_after_fx)
        self._hg_after_tick = self.root.after(16, self._horror_game_tick)
        self._hg_after_fx = self.root.after(70, self._horror_game_fx_tick)

        # Sound: short static burst on entry (best-effort).
        self._play_jumpscare_sound()

    def _hg_spawn_collectible(self) -> None:
        w = max(1, int(self.screen_w))
        h = max(1, int(self.screen_h))
        margin = 80
        self._hg_collect_x = float(random.randint(margin, max(margin, w - margin)))
        self._hg_collect_y = float(random.randint(margin, max(margin, h - margin)))

        # Replace previous collectible drawing.
        for k in ["sigil_a", "sigil_b", "sigil_c"]:
            item = self._hg_ids.pop(k, None)
            if item is not None:
                try:
                    self.final_canvas.delete(item)  # type: ignore[arg-type]
                except Exception:
                    pass

        cx, cy = int(self._hg_collect_x), int(self._hg_collect_y)
        self._hg_ids["sigil_a"] = self.final_canvas.create_polygon(
            cx, cy - 14, cx + 14, cy + 12, cx - 14, cy + 12,
            fill="",
            outline="#ff0000",
            width=3,
            tags="hg",
        )
        self._hg_ids["sigil_b"] = self.final_canvas.create_line(
            cx - 10, cy + 8, cx + 10, cy - 6, fill="#b30000", width=2, tags="hg"
        )
        self._hg_ids["sigil_c"] = self.final_canvas.create_oval(
            cx - 3, cy - 3, cx + 3, cy + 3, fill="#ff0000", outline="#ff0000", tags="hg"
        )

    def _horror_game_tick(self) -> None:
        if not self._hg_active:
            return
        if self.final_canvas is None or self.final_window is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return

        now = time.monotonic()
        elapsed = now - self._hg_started_at
        remaining = max(0.0, self._hg_time_limit_s - elapsed)

        # Player position (cursor).
        pos = self._get_cursor_pos()
        if pos is None:
            pos = self._hg_last_mouse
        px, py = pos
        w = max(1, int(self.screen_w))
        h = max(1, int(self.screen_h))
        px = max(0, min(int(px), w - 1))
        py = max(0, min(int(py), h - 1))

        # Enemy chases player; speeds up as you collect sigils / time passes.
        speed = self._hg_enemy_v + self._hg_score * 0.85 + min(2.4, elapsed * 0.06)
        dx = float(px) - self._hg_enemy_x
        dy = float(py) - self._hg_enemy_y
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        self._hg_enemy_x += (dx / dist) * speed + random.uniform(-0.25, 0.25)
        self._hg_enemy_y += (dy / dist) * speed + random.uniform(-0.25, 0.25)
        self._hg_enemy_x = max(-60.0, min(self._hg_enemy_x, float(w + 60)))
        self._hg_enemy_y = max(-60.0, min(self._hg_enemy_y, float(h + 60)))

        # Draw updates.
        try:
            self.final_canvas.coords(self._hg_ids["player"], px - 6, py - 6, px + 6, py + 6)
        except Exception:
            pass
        ex, ey = int(self._hg_enemy_x), int(self._hg_enemy_y)
        try:
            self.final_canvas.coords(self._hg_ids["enemy_outer"], ex - 26, ey - 18, ex + 26, ey + 18)
            self.final_canvas.coords(self._hg_ids["enemy_iris"], ex - 10, ey - 10, ex + 10, ey + 10)
            # Pupil follows a bit (makes it feel alive).
            ox = max(-5.0, min(5.0, dx / dist * 5.0))
            oy = max(-4.0, min(4.0, dy / dist * 4.0))
            self.final_canvas.coords(self._hg_ids["enemy_pupil"], ex - 4 + ox, ey - 4 + oy, ex + 4 + ox, ey + 4 + oy)
        except Exception:
            pass

        # HUD (subtle).
        try:
            self.final_canvas.itemconfig(
                self._hg_ids["hud"],
                text=f"{self._hg_score}/{self._hg_target_score}  {remaining:0.1f}s",
            )
        except Exception:
            pass

        # Collision: if the eye touches you, you lose.
        if dist <= 28.0:
            self._horror_game_end(win=False, aborted=False)
            return

        # Collectible pickup.
        cdx = float(px) - self._hg_collect_x
        cdy = float(py) - self._hg_collect_y
        if (cdx * cdx + cdy * cdy) ** 0.5 <= 26.0:
            self._hg_score += 1
            # Flash for impact.
            try:
                self.final_canvas.configure(bg="#120000")
            except Exception:
                pass
            self._ding()
            if self._hg_score >= self._hg_target_score:
                self._horror_game_end(win=True, aborted=False)
                return
            self._hg_spawn_collectible()

        # Time out: you lose.
        if remaining <= 0.0:
            self._horror_game_end(win=False, aborted=False)
            return

        self._after_cancel(self._hg_after_tick)
        self._hg_after_tick = self.root.after(16, self._horror_game_tick)

    def _horror_game_fx_tick(self) -> None:
        if not self._hg_active or self.final_canvas is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return

        # Noise + flicker.
        try:
            bg = "#000000" if random.random() < 0.82 else "#070000"
            self.final_canvas.configure(bg=bg)
        except Exception:
            pass
        for item in self._hg_noise_items[:]:
            try:
                x = random.randint(0, max(1, self.screen_w))
                y = random.randint(0, max(1, self.screen_h))
                self.final_canvas.coords(item, x, y, x + random.randint(5, 220), y)
                self.final_canvas.itemconfig(
                    item,
                    fill="#0b0000" if random.random() < 0.7 else "#220000",
                    width=random.randint(1, 3),
                )
            except Exception:
                continue

        # Random whisper text (short-lived).
        if random.random() < 0.10:
            try:
                tid = self.final_canvas.create_text(
                    random.randint(60, max(60, self.screen_w - 60)),
                    random.randint(60, max(60, self.screen_h - 60)),
                    text=random.choice(["NICHT HINSEHEN", "LAUF", "HINTER DIR", "DU BIST ZU LANGSAM", "NULL"]),
                    fill="#7f0000",
                    font=("Consolas", random.randint(18, 34), "bold"),
                    tags=("hg", "hg_whisper"),
                )
                self.root.after(250, lambda: self.final_canvas.delete(tid))
            except Exception:
                pass

        self._after_cancel(self._hg_after_fx)
        self._hg_after_fx = self.root.after(random.randint(60, 120), self._horror_game_fx_tick)

    def _horror_game_end(self, win: bool, aborted: bool) -> None:
        # Internal helper that can be called from binds without keeping args.
        self._horror_game_end_impl(win=win, aborted=aborted)

    def _horror_game_end_impl(self, win: bool, aborted: bool) -> None:
        if not self._hg_active:
            return
        self._hg_active = False
        self._after_cancel(self._hg_after_tick)
        self._after_cancel(self._hg_after_fx)
        self._hg_after_tick = None
        self._hg_after_fx = None

        if self.final_canvas is None or self.final_window is None:
            self._resurrect_pet()
            return

        try:
            self.final_canvas.delete("all")
            self.final_canvas.configure(bg="black")
        except Exception:
            pass

        if aborted:
            msg = "..."
            color = "#7f0000"
        elif win:
            msg = "DU HAST ES GEFUNDEN."
            color = "#a30000"
        else:
            msg = "ZU SPAET."
            color = "#ff0000"

        try:
            self.final_canvas.create_text(
                self.screen_w // 2,
                self.screen_h // 2 + 180,
                text=msg,
                fill=color,
                font=("Consolas", 32, "bold"),
            )
        except Exception:
            pass

        if (not win) and (not aborted):
            # On loss: quick in-place jumpscare.
            try:
                img = self._final_bloody_img or self.face_assets.get("mad")
                if img:
                    self.final_canvas.create_image(self.screen_w // 2, self.screen_h // 2, image=img)
            except Exception:
                pass
            self._play_jumpscare_sound()
            self._final_after_resurrect = self.root.after(700, self._resurrect_pet)
            return

        # On win/abort: short pause then resurrect.
        self._final_after_resurrect = self.root.after(1200, self._resurrect_pet)

    def _show_bloody_ending(self) -> None:
        if self._final_stage != "dots":
            return
        if self.final_canvas is None or self.final_window is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return
        self._final_stage = "ending"
        self._after_cancel(self._final_after_fx)
        self._final_after_fx = None
        try:
            self.final_window.configure(cursor="none")
        except Exception:
            pass
        self.final_canvas.delete("dots")
        
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        
        # Try to create a "bloody" version if PIL is available, else use mad face
        img = self.face_assets.get("mad")
        if PIL_AVAILABLE and img:
            try:
                path = self.asset_dir / "Wutend_Bild.png"
                if path.exists():
                    with Image.open(path) as _im:  # type: ignore[name-defined]
                        pil_img = _im.convert("RGBA")
                    r, g, b, a = pil_img.split()
                    r = r.point(lambda i: min(255, int(i * 1.5)))  # Boost red
                    g = g.point(lambda i: max(0, int(i * 0.30)))   # Reduce green
                    b = b.point(lambda i: max(0, int(i * 0.30)))   # Reduce blue
                    pil_img = Image.merge("RGBA", (r, g, b, a))
                    resampling = getattr(Image, "Resampling", Image)  # type: ignore[name-defined]
                    pil_img = pil_img.resize((256, 256), resampling.LANCZOS)
                    self._final_bloody_img = ImageTk.PhotoImage(pil_img)
                    img = self._final_bloody_img
            except Exception:
                self._log_exc("_show_bloody_ending")
        
        if img:
            self.final_canvas.create_image(cx, cy, image=img, tags="face")
            
        self.final_text_idx = 0
        self.final_message = "warum?"
        self._after_cancel(self._final_after_type_msg)
        self._final_after_type_msg = self.root.after(2000, self._type_final_message)

    def _type_final_message(self) -> None:
        if self._final_stage != "ending":
            return
        if self.final_canvas is None:
            return
        try:
            if not self.final_canvas.winfo_exists():
                return
        except Exception:
            return
            
        if self.final_text_idx < len(self.final_message):
            char = self.final_message[self.final_text_idx]
            self.final_text_idx += 1
            
            current = self.final_message[:self.final_text_idx]
            self.final_canvas.delete("msg")
            
            cx = self.screen_w // 2
            cy = self.screen_h // 2 + 160
            self.final_canvas.create_text(cx, cy, text=current, fill="red", font=("Segoe UI", 28, "bold"), tags="msg")
            
            self._after_cancel(self._final_after_type_msg)
            self._final_after_type_msg = self.root.after(600, self._type_final_message)
        else:
            self._after_cancel(self._final_after_resurrect)
            self._final_after_resurrect = self.root.after(10000, self._resurrect_pet)

    def _resurrect_pet(self) -> None:
        # Stop any pending "final screen" callbacks.
        self._after_cancel(self._final_after_show_bloody)
        self._after_cancel(self._final_after_type_msg)
        self._after_cancel(self._final_after_resurrect)
        self._after_cancel(self._final_after_fx)
        self._final_after_show_bloody = None
        self._final_after_type_msg = None
        self._final_after_resurrect = None
        self._final_after_fx = None

        # Stop any horror game loops.
        self._hg_active = False
        self._after_cancel(self._hg_after_tick)
        self._after_cancel(self._hg_after_fx)
        self._hg_after_tick = None
        self._hg_after_fx = None
        self._hg_noise_items = []
        self._hg_ids = {}

        # Safety: remove any leftover overlay visuals.
        self._destroy_rope_overlay()

        if self.final_window is not None:
            self.final_window.destroy()
            self.final_window = None
        self.final_canvas = None
        self._final_stage = "idle"
        
        self.dying = False
        self.scary_mode = True
        self.root.deiconify()
        self.root.lift()
        self.emotion = "scary"
        self._draw_face()
        self.x = self.screen_w / 2 - self.block_size / 2
        self.y = self.screen_h / 2 - self.block_size / 2
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
        
        # FIX: Restart the loops that were stopped by dying=True
        self._motion_loop()
        self._annoy_loop()
        self._scary_loop()

    def _close_prompt_no(self) -> None:
        self._hide_close_prompt()

    def _hide_close_prompt(self) -> None:
        if self.close_prompt_window is not None and self.close_prompt_window.winfo_exists():
            self.close_prompt_window.destroy()
        self.close_prompt_window = None

    def _hide_options_window(self) -> None:
        if self.options_window is not None and self.options_window.winfo_exists():
            self.options_window.destroy()
        self.options_window = None
        self._opt_profile_var = None
        self._opt_hunger_var = None
        self._opt_mischief_var = None
        self._opt_start_var = None

    def _feed_from_file_dialog(self) -> None:
        try:
            chosen = filedialog.askopenfilename(
                parent=self.root,
                title="Fuettern mit Daten: Datei waehlen",
            )
        except Exception:
            chosen = ""
        if not chosen:
            return
        self._feed_from_path(Path(chosen))

    def _tokens_from_data(self, data: bytes) -> list[str]:
        # Keep tokens short and printable; they will be inserted into the prank editor window.
        try:
            s = data.decode("utf-8", errors="ignore")
        except Exception:
            s = ""
        toks = re.findall(r"[A-Za-z0-9_]{2,}", s)
        out: list[str] = []
        for t in toks:
            t = t.strip()
            if not t:
                continue
            if len(t) > 24:
                t = t[:24]
            out.append(t)
            if len(out) >= 160:
                break
        if out:
            random.shuffle(out)
            return out

        # Binary / no words: fall back to base64 chunks.
        b64 = base64.b64encode(data[:2048]).decode("ascii", errors="ignore")
        out = [b64[i : i + 10] for i in range(0, min(len(b64), 600), 10) if b64[i : i + 10]]
        if out:
            random.shuffle(out)
        return out

    def _feed_from_path(self, path: Path) -> None:
        try:
            with path.open("rb") as f:
                sample = f.read(8192)
        except Exception:
            self._notify_pet("Konnte Datei nicht lesen.")
            return

        new_tokens = self._tokens_from_data(sample)
        if new_tokens:
            self.food_tokens.extend(new_tokens)
            # Keep memory bounded.
            if len(self.food_tokens) > 900:
                self.food_tokens = self.food_tokens[-700:]

        # Feeding refills hunger (if enabled) and updates the HUD.
        try:
            self.hunger = max(0.0, min(1.0, float(getattr(self, "hunger", 1.0)) + 0.55))
        except Exception:
            self.hunger = 1.0
        self._save_persistent_settings()
        try:
            self._draw_hud()
        except Exception:
            pass

        self._notify_pet(f"Nom nom: {path.name}")

    def _show_options_window(self) -> None:
        if self.intro_active:
            return
        self._hide_options_window()

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#dbeafe")

        frame = tk.Frame(win, bg="#dbeafe", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)

        title = tk.Label(
            frame,
            text=f"Optionen ({self.pet_profile.name})",
            bg="#dbeafe",
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=6,
        )
        title.pack(anchor="w")

        # Pet selection
        self._opt_profile_var = tk.StringVar(value=self.pet_profile_id)

        def _on_profile_change() -> None:
            if self._opt_profile_var is None:
                return
            self._apply_pet_profile(self._opt_profile_var.get(), persist=True)
            try:
                title.configure(text=f"Optionen ({self.pet_profile.name})")
            except Exception:
                pass

        pets = tk.Frame(frame, bg="#dbeafe")
        pets.pack(fill="x", padx=10, pady=(0, 6))
        tk.Label(
            pets,
            text="Pet:",
            bg="#dbeafe",
            fg="#0f172a",
            font=("Segoe UI", 9, "bold"),
        ).pack(side="left")
        for pid in ["cube", "aki", "pamuk"]:
            prof = PET_PROFILES.get(pid)
            if prof is None:
                continue
            tk.Radiobutton(
                pets,
                text=prof.name,
                bg="#dbeafe",
                fg="#0f172a",
                selectcolor="#bfdbfe",
                activebackground="#dbeafe",
                activeforeground="#0f172a",
                variable=self._opt_profile_var,
                value=pid,
                command=_on_profile_change,
            ).pack(side="left", padx=(8, 0))

        # Toggles
        toggles = tk.Frame(frame, bg="#dbeafe")
        toggles.pack(fill="x", padx=10, pady=(0, 6))
        self._opt_hunger_var = tk.BooleanVar(value=bool(getattr(self, "hunger_enabled", False)))
        self._opt_mischief_var = tk.BooleanVar(
            value=bool(getattr(self, "editor_mischief_enabled", False))
        )
        self._opt_start_var = tk.BooleanVar(value=bool(getattr(self, "show_options_on_start", False)))

        def _on_toggle() -> None:
            try:
                if self._opt_hunger_var is not None:
                    self.hunger_enabled = bool(self._opt_hunger_var.get())
                if self._opt_mischief_var is not None:
                    self.editor_mischief_enabled = bool(self._opt_mischief_var.get())
                if self._opt_start_var is not None:
                    self.show_options_on_start = bool(self._opt_start_var.get())
                self._save_persistent_settings()
                self._draw_hud()
            except Exception:
                pass

        tk.Checkbutton(
            toggles,
            text="Hunger-Bar",
            bg="#dbeafe",
            fg="#0f172a",
            selectcolor="#bfdbfe",
            activebackground="#dbeafe",
            activeforeground="#0f172a",
            variable=self._opt_hunger_var,
            command=_on_toggle,
        ).pack(side="left")
        tk.Checkbutton(
            toggles,
            text="Editor-Mischief",
            bg="#dbeafe",
            fg="#0f172a",
            selectcolor="#bfdbfe",
            activebackground="#dbeafe",
            activeforeground="#0f172a",
            variable=self._opt_mischief_var,
            command=_on_toggle,
        ).pack(side="left", padx=(10, 0))
        tk.Checkbutton(
            toggles,
            text="Beim Start",
            bg="#dbeafe",
            fg="#0f172a",
            selectcolor="#bfdbfe",
            activebackground="#dbeafe",
            activeforeground="#0f172a",
            variable=self._opt_start_var,
            command=_on_toggle,
        ).pack(side="left", padx=(10, 0))

        # Actions
        actions = tk.Frame(frame, bg="#dbeafe")
        actions.pack(fill="x", padx=10, pady=(0, 10))
        tk.Button(
            actions,
            text="Fuettern (Datei...)",
            command=self._feed_from_file_dialog,
            bg="#ffffff",
            fg="#0f172a",
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="left")
        tk.Button(
            actions,
            text="Schliessen",
            command=self._hide_options_window,
            bg="#ffffff",
            fg="#0f172a",
            relief="flat",
            padx=8,
            pady=3,
        ).pack(side="right")

        win.update_idletasks()
        px = int(self.x + self.block_size + 10)
        py = int(self.y - 10)
        max_x = max(0, self.screen_w - win.winfo_width())
        max_y = max(0, self.screen_h - win.winfo_height())
        px = max(0, min(px, max_x))
        py = max(0, min(py, max_y))
        win.geometry(f"+{px}+{py}")

        self.options_window = win

    def _start_close_attack(self) -> None:
        if USER32 is None:
            return
        self.close_attack_active = True
        self.close_attack_until = time.monotonic() + 1.35
        self.close_attack_phase = random.uniform(0.0, 6.2)
        self._ding()

    def _whirl_cursor(self) -> None:
        if USER32 is None:
            return
        cx = self.x + self.block_size / 2
        cy = self.y + self.block_size / 2
        self.close_attack_phase += 0.55
        radius = 90 + 32 * (0.5 + random.random())
        tx = int(cx + radius * math.cos(self.close_attack_phase))
        ty = int(cy + radius * math.sin(self.close_attack_phase))
        tx += random.randint(-18, 18)
        ty += random.randint(-18, 18)
        tx = max(0, min(tx, self.screen_w - 1))
        ty = max(0, min(ty, self.screen_h - 1))
        USER32.SetCursorPos(tx, ty)

    def _scary_loop(self) -> None:
        if not self.scary_mode:
            return

        # Random scary events
        if random.random() < 0.12:
            self._scary_teleport()
        elif random.random() < 0.08:
            self._spawn_scary_text()
        elif random.random() < 0.08:
            self._spawn_scary_editor()
        elif random.random() < 0.03:
            self._trigger_jumpscare()
        elif random.random() < 0.06:
            self._scary_cursor_glitch()

        # Variable delay for unpredictability
        delay = random.randint(150, 1200)
        self.root.after(delay, self._scary_loop)

    def _scary_teleport(self) -> None:
        # Glitch/Teleport effect
        max_x = max(0, self.screen_w - self.block_size)
        max_y = max(0, self.screen_h - self.block_size)
        
        # Teleport near current position or completely random
        if random.random() < 0.7:
            offset = 200
            self.x += random.uniform(-offset, offset)
            self.y += random.uniform(-offset, offset)
        else:
            self.x = random.uniform(0, max_x)
            self.y = random.uniform(0, max_y)
            
        self.x = max(0, min(self.x, max_x))
        self.y = max(0, min(self.y, max_y))
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
        self.vx = random.uniform(-15, 15)
        self.vy = random.uniform(-15, 15)

    def _spawn_scary_editor(self, x: int | None = None, y: int | None = None) -> None:
        if not self.root.winfo_exists() or self.dying:
            return
            
        if self.scary_editor_count > 25:
            return
        self.scary_editor_count += 1

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#f3f4f6")

        titlebar = tk.Frame(win, bg="#e5e7eb")
        titlebar.pack(fill="x")
        
        names = ["nicht_schliessen.txt", "hinter_dir.txt", "666.txt", "run.bat", "error.log"]
        title = tk.Label(
            titlebar,
            text=f"{random.choice(names)} - Notepad",
            bg="#e5e7eb",
            fg="#111827",
            font=("Segoe UI", 9, "bold"),
            anchor="w",
            padx=8,
            pady=4,
        )
        title.pack(side="left", fill="x", expand=True)

        def _on_close() -> None:
            try:
                cx = win.winfo_x()
                cy = win.winfo_y()
            except Exception:
                cx, cy = 0, 0
            win.destroy()
            self.scary_editor_count -= 1
            
            # Double trouble logic with safety cap
            if self.scary_editor_count < 15:
                self._spawn_scary_editor(cx, cy)
                self._spawn_scary_editor(cx, cy)
            elif self.scary_editor_count < 25:
                self._spawn_scary_editor(cx, cy)

        close_btn = tk.Button(
            titlebar,
            text="X",
            command=_on_close,
            bg="#f3f4f6",
            fg="#111827",
            activebackground="#ef4444",
            activeforeground="#ffffff",
            bd=0,
            relief="flat",
            padx=6,
            pady=2,
            font=("Segoe UI", 9, "bold"),
        )
        close_btn.pack(side="right", padx=4, pady=2)

        text = tk.Text(win, width=28, height=6, bg="#ffffff", fg="#0f172a", font=("Consolas", 10), bd=0, highlightthickness=0)
        text.pack(fill="both", expand=True, padx=6, pady=6)
        msgs = ["DU KANNST NICHT ENTKOMMEN", "LASS ES", "ICH SEHE DICH", "...", "DONT TOUCH ME", "ERROR 666"]
        text.insert("end", random.choice(msgs))
        
        win.update_idletasks()
        if x is None: x = random.randint(0, max(0, self.screen_w - win.winfo_width()))
        if y is None: y = random.randint(0, max(0, self.screen_h - win.winfo_height()))
        else: x, y = max(0, min(x + random.randint(-50, 50), self.screen_w - win.winfo_width())), max(0, min(y + random.randint(-50, 50), self.screen_h - win.winfo_height()))
        win.geometry(f"+{x}+{y}")
        self._make_noactivate(win)

    def _spawn_scary_text(self) -> None:
        if not self.root.winfo_exists() or self.dying:
            return
            
        messages = ["ICH SEHE DICH", "LAUF", "HILFE", "WARUM?", "NULL", "666", "TOT", "KEIN ENTKOMMEN", "HINTER DIR"]
        msg = random.choice(messages)
        
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="black")
        
        lbl = tk.Label(win, text=msg, fg="red", bg="black", font=("Segoe UI", random.randint(20, 40), "bold"))
        lbl.pack()

        win.update_idletasks()
        w = max(1, win.winfo_width())
        h = max(1, win.winfo_height())
        x = random.randint(0, max(0, self.screen_w - w))
        y = random.randint(0, max(0, self.screen_h - h))
        win.geometry(f"+{x}+{y}")
        
        # Make it non-interactive and transparent to clicks if possible (simple way: just destroy fast)
        self._make_noactivate(win)
        
        # Destroy after short time
        self.root.after(random.randint(800, 2000), win.destroy)

    def _trigger_jumpscare(self) -> None:
        # Fullscreen flash of the scary face
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        win.configure(bg="black")
        
        canvas = tk.Canvas(win, bg="black", highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        
        img = self._final_bloody_img or self.face_assets.get("mad")
        if img:
            # Center image
            canvas.create_image(self.screen_w//2, self.screen_h//2, image=img)
            
        self._play_jumpscare_sound()
        # Very short duration
        self.root.after(150, win.destroy)

    def _play_jumpscare_sound(self) -> None:
        if winsound is None or not self.sounds_enabled:
            self._ding()
            return

        try:
            wav_data = self._get_static_noise()
            # Play directly (async) without thread overhead since data is cached
            winsound.PlaySound(wav_data, winsound.SND_MEMORY | winsound.SND_ASYNC)
        except Exception:
            self._log_once("jumpscare_sound_failed", "Jumpscare sound failed (winsound).")
            if self.debug_enabled:
                self._log_exc("_play_jumpscare_sound")

    def _get_static_noise(self) -> bytes:
        if self._static_noise_wav is not None:
            return self._static_noise_wav
            
        # Generate 0.4s of loud static noise (white noise) once and cache it
        duration_ms = 400
        rate = 11025
        num_samples = int(rate * (duration_ms / 1000.0))
        
        wav = bytearray()
        # RIFF header
        wav.extend(b'RIFF')
        wav.extend(struct.pack('<I', 36 + num_samples))
        wav.extend(b'WAVE')
        # fmt chunk
        wav.extend(b'fmt ')
        wav.extend(struct.pack('<IHHIIHH', 16, 1, 1, rate, rate, 1, 8))
        # data chunk
        wav.extend(b'data')
        wav.extend(struct.pack('<I', num_samples))
        
        for _ in range(num_samples):
            wav.append(random.randint(0, 255))
            
        self._static_noise_wav = bytes(wav)
        return self._static_noise_wav

    def _scary_cursor_glitch(self) -> None:
        if USER32 is None: return
        cpos = self._get_cursor_pos()
        if not cpos: return
        cx, cy = cpos
        
        def _shake(steps: int) -> None:
            if steps <= 0 or not self.root.winfo_exists() or self.dying:
                return
            nx = cx + random.randint(-50, 50)
            ny = cy + random.randint(-50, 50)
            nx = max(0, min(nx, self.screen_w))
            ny = max(0, min(ny, self.screen_h))
            USER32.SetCursorPos(nx, ny)
            self.root.after(20, lambda: _shake(steps - 1))

        _shake(5)

    def _annoy_loop(self) -> None:
        # Update screen cache
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        if self.dying:
            return
        now = time.monotonic()
        idle_s = self._user_idle_seconds() if self.respect_user_input else 9999.0
        user_active = idle_s < self.active_grace_s
        image_idle_ok = idle_s >= self.image_idle_s
        editor_idle_ok = idle_s >= 0.25

        if not self._dragging and not self.intro_active:
            self.root.lift()
            if self.allow_focus_steal and (not user_active) and random.random() < 0.48:
                try:
                    self.root.focus_force()
                except tk.TclError:
                    pass
            if random.random() < 0.38:
                self._ding()
            if random.random() < 0.31:
                self.vx += random.uniform(-1.0, 1.0)
                self.vy += random.uniform(-1.0, 1.0)
            if self._can_start_major_prank(now, user_active=user_active):
                if now >= self.next_editor_heist_at:
                    if editor_idle_ok and self._start_editor_heist():
                        if self.notifications_enabled:
                            self._notify_pet(f"{self.pet_profile.name} macht jetzt Editor-Heist.")
                        self.next_editor_heist_at = now + random.uniform(22.0, 54.0)
                        self.next_image_heist_at = max(
                            self.next_image_heist_at, now + random.uniform(7.0, 16.0)
                        )
                    else:
                        self.next_editor_heist_at = now + random.uniform(10.0, 20.0)
                elif now >= self.next_image_heist_at:
                    if image_idle_ok and self._start_image_heist():
                        if self.notifications_enabled:
                            self._notify_pet(f"{self.pet_profile.name} klaut ein Bild.")
                        self.next_image_heist_at = now + random.uniform(self.image_min_s, self.image_max_s)
                    else:
                        # If it couldn't start (user too active / no images yet), retry soon.
                        self.next_image_heist_at = now + random.uniform(4.0, 9.0)
            if now >= self.stunned_until and not self.cursor_heist_active:
                if random.random() < 0.20:
                    self.confused_until = now + random.uniform(0.6, 1.4)

        # Separate Window Kill Logic (More frequent, less strict on idle)
        if (
            not self.intro_active
            and not self._dragging
            and now >= self.stunned_until
            and not self.window_kill_active
            and not self.heist_active
            and not self.cursor_heist_active
            and not self.close_attack_active
            and self.close_prompt_window is None
            and self.youtube_prompt_window is None
            and self.discord_prompt_window is None
            and USER32 is not None
            and now >= self.next_window_kill_at
            and now >= self.angry_until
        ):
            if random.random() < 0.15:
                if self._start_window_kill():
                    self.next_window_kill_at = now + random.uniform(15.0, 45.0)

        if (
            not self.intro_active
            and not self._dragging
            and now >= self.stunned_until
            and self.close_prompt_window is None
            and self.youtube_prompt_window is None
            and not self.heist_active
            and not self.window_kill_active
            and not self.cursor_heist_active
            and not self.cursor_pingpong_active
            and not self.close_attack_active
            and USER32 is not None
            and now >= self.next_mouse_lock_at
            and (not user_active)
            and now >= self.angry_until
        ):
            # Occasional short mouse lock.
            if random.random() < 0.30:
                self.mouse_lock_active = True
                self.mouse_lock_until = now + random.uniform(0.9, 1.7)
                self.next_mouse_lock_at = now + random.uniform(12.0, 28.0)
                self.confused_until = max(self.confused_until, self.mouse_lock_until)
            else:
                self.next_mouse_lock_at = now + random.uniform(6.0, 12.0)

        if (
            not self.intro_active
            and self.clone_window is None
            and now >= self.next_clone_spawn_at
            and random.random() < 0.50
        ):
            self._spawn_clone(now)

        delay = random.randint(380, 1100)
        if self._discord_rpc_connected:
            self._update_discord_rpc(force=False)
        self.root.after(delay, self._annoy_loop)

    def _hunger_loop(self) -> None:
        if self.dying:
            return
        now = time.monotonic()
        try:
            last = float(getattr(self, "_hunger_last_t", now))
        except Exception:
            last = now
        dt = max(0.0, min(now - last, 4.0))
        self._hunger_last_t = now

        if bool(getattr(self, "hunger_enabled", False)):
            try:
                full_s = float(getattr(self, "hunger_full_s", 900.0))
            except Exception:
                full_s = 900.0
            if full_s < 30.0:
                full_s = 30.0
            try:
                h = float(getattr(self, "hunger", 1.0))
            except Exception:
                h = 1.0
            h = max(0.0, min(1.0, h - (dt / full_s)))
            self.hunger = h
            try:
                self._draw_hud()
            except Exception:
                pass

            # Persist hunger occasionally without spamming disk writes.
            try:
                last_save = float(getattr(self, "_hunger_last_save_t", 0.0))
            except Exception:
                last_save = 0.0
            if now - last_save >= 45.0:
                self._hunger_last_save_t = now
                self._save_persistent_settings()

        self.root.after(1200, self._hunger_loop)

    def _youtube_watch_loop(self) -> None:
        # Checks if the user is currently in a browser on youtube.com and prompts once per "session".
        # A "session" is continuous time while a YouTube tab/window is foreground.
        try:
            in_youtube = self._foreground_is_browser_youtube()
        except Exception:
            in_youtube = False

        if not in_youtube:
            self._youtube_in_last = False
            self._youtube_prompted_session = False
        else:
            # Rising edge: entered YouTube.
            if not self._youtube_in_last:
                self._youtube_in_last = True
                self._youtube_prompted_session = False

            if (
                not self._youtube_prompted_session
                and self.youtube_prompt_window is None
                and not self.intro_active
                and self.options_window is None
            ):
                self._youtube_prompted_session = True
                if self.notifications_enabled:
                    self._notify_pet(f"YouTube erkannt: {self.pet_profile.name} nervt jetzt.")
                self._show_youtube_prompt()

        self.root.after(700, self._youtube_watch_loop)

    def _discord_watch_loop(self) -> None:
        # If Discord is foreground, say it once per "session" (continuous time in foreground).
        try:
            in_discord = self._foreground_is_discord()
        except Exception:
            in_discord = False

        if not in_discord:
            self._discord_in_last = False
            self._discord_prompted_session = False
        else:
            if not self._discord_in_last:
                self._discord_in_last = True
                self._discord_prompted_session = False

            if (
                not self._discord_prompted_session
                and not self.intro_active
                and not self.cursor_pingpong_active
                and self.close_prompt_window is None
                and self.youtube_prompt_window is None
                and self.options_window is None
                and self.discord_prompt_window is None
            ):
                self._discord_prompted_session = True
                if self.notifications_enabled:
                    self._notify_pet(f"Discord erkannt: {self.pet_profile.name} schaut zu.")
                self._on_discord_foreground()

        self.root.after(800, self._discord_watch_loop)

    def _foreground_is_browser_youtube(self) -> bool:
        if USER32 is None:
            return False

        hwnd = USER32.GetForegroundWindow()
        if not hwnd:
            return False

        title = self._get_window_title(hwnd).lower()
        if not title:
            return False

        # Heuristic: most browsers show "YouTube" in the tab title.
        is_youtube_title = ("youtube" in title) or ("youtube.com" in title)
        if not is_youtube_title:
            return False

        proc = self._get_window_process_name(hwnd).lower()
        if not proc:
            # If we can't read process name, fall back to title-only.
            return True

        browsers = {
            "chrome.exe",
            "msedge.exe",
            "firefox.exe",
            "opera.exe",
            "brave.exe",
            "vivaldi.exe",
        }
        return proc in browsers

    def _foreground_is_discord(self) -> bool:
        if USER32 is None:
            return False
        hwnd = USER32.GetForegroundWindow()
        if not hwnd:
            return False
        proc = self._get_window_process_name(hwnd).lower()
        if not proc:
            return False
        return proc in {"discord.exe", "discordcanary.exe", "discordptb.exe"}

    def _get_window_title(self, hwnd) -> str:
        if USER32 is None:
            return ""
        length = USER32.GetWindowTextLengthW(hwnd)
        if length <= 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        USER32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value or ""

    def _get_window_process_name(self, hwnd) -> str:
        if USER32 is None or KERNEL32 is None:
            return ""

        pid = ctypes.c_ulong(0)
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not pid.value:
            return ""

        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        hproc = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, 0, pid.value)
        if not hproc:
            return ""

        try:
            size = ctypes.c_ulong(260)
            buf = ctypes.create_unicode_buffer(size.value)
            # QueryFullProcessImageNameW returns full path; we only want the exe name.
            ok = KERNEL32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size))
            if not ok:
                return ""
            full = buf.value or ""
            return os.path.basename(full)
        finally:
            try:
                KERNEL32.CloseHandle(hproc)
            except Exception:
                pass

    def _load_cached_discord_username(self) -> str:
        # Optional: user can set DISCORD_USERNAME env var, or we cache locally in the project folder.
        env_name = os.environ.get("DISCORD_USERNAME", "").strip()
        if env_name:
            return env_name
        try:
            p = self.asset_dir / ".discord_username.txt"
            if p.exists():
                return p.read_text(encoding="utf-8").strip()
        except Exception:
            pass
        return ""

    def _save_cached_discord_username(self, name: str) -> None:
        try:
            (self.asset_dir / ".discord_username.txt").write_text(name, encoding="utf-8")
        except Exception:
            pass

    def _on_discord_foreground(self) -> None:
        name = self.discord_username.strip()
        if not name:
            name = self._try_read_discord_username_from_files()
            if name:
                self.discord_username = name
                self._save_cached_discord_username(name)

        if name:
            self._show_discord_bubble(name)
        else:
            self._show_discord_username_prompt()

    def _try_read_discord_username_from_files(self) -> str:
        # Best-effort only. We intentionally do NOT scrape tokens.
        appdata = os.environ.get("APPDATA", "")
        if not appdata:
            return ""

        candidates = [
            Path(appdata) / "discord" / "settings.json",
            Path(appdata) / "discord" / "Local State",
            Path(appdata) / "discordcanary" / "settings.json",
            Path(appdata) / "discordcanary" / "Local State",
            Path(appdata) / "discordptb" / "settings.json",
            Path(appdata) / "discordptb" / "Local State",
        ]

        for p in candidates:
            if not p.exists():
                continue
            try:
                raw = p.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            raw_stripped = raw.strip()
            if not raw_stripped:
                continue

            # Try JSON parse first.
            try:
                import json

                data = json.loads(raw_stripped)
                found = self._search_json_for_username(data)
                if found:
                    return found
            except Exception:
                pass

            # Fallback: lightweight regex search for something like "username":"...".
            try:
                import re

                m = re.search(r"\"username\"\\s*:\\s*\"([^\"]{2,64})\"", raw_stripped, flags=re.IGNORECASE)
                if m:
                    return m.group(1).strip()
            except Exception:
                pass

        return ""

    def _search_json_for_username(self, obj) -> str:
        # Walks a JSON structure, searching for a plausible username field.
        if isinstance(obj, dict):
            for k, v in obj.items():
                key = str(k).lower()
                if key in {"username", "user_name", "displayname", "display_name"} and isinstance(v, str):
                    s = v.strip()
                    if 2 <= len(s) <= 64:
                        return s
                out = self._search_json_for_username(v)
                if out:
                    return out
        elif isinstance(obj, list):
            for item in obj:
                out = self._search_json_for_username(item)
                if out:
                    return out
        return ""

    def _hide_discord_bubble(self) -> None:
        if self.discord_bubble_window is not None and self.discord_bubble_window.winfo_exists():
            self.discord_bubble_window.destroy()
        self.discord_bubble_window = None

    def _show_discord_bubble(self, username: str) -> None:
        self._hide_discord_bubble()

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#e8f1ff")

        frame = tk.Frame(win, bg="#e8f1ff", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)

        label = tk.Label(
            frame,
            text=f"ahh du bist doch auf discord ({username})",
            bg="#e8f1ff",
            fg="#0a1a3b",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=7,
        )
        label.pack()

        win.update_idletasks()
        px = int(self.x + self.block_size + 10)
        py = int(self.y + self.block_size // 2 - win.winfo_height() // 2)
        max_x = max(0, self.screen_w - win.winfo_width())
        max_y = max(0, self.screen_h - win.winfo_height())
        px = max(0, min(px, max_x))
        py = max(0, min(py, max_y))
        win.geometry(f"+{px}+{py}")

        self.discord_bubble_window = win
        self.root.after(2600, self._hide_discord_bubble)

    def _hide_discord_username_prompt(self) -> None:
        if self.discord_prompt_window is not None and self.discord_prompt_window.winfo_exists():
            self.discord_prompt_window.destroy()
        self.discord_prompt_window = None

    def _show_discord_username_prompt(self) -> None:
        # One-time ask if we can't resolve the username safely from local config.
        self._stop_heist()
        self.cursor_heist_active = False
        self.close_attack_active = False
        self.mouse_lock_active = False
        self.cursor_pingpong_active = False

        if self.discord_prompt_window is not None:
            return

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#fff7d6")

        frame = tk.Frame(win, bg="#fff7d6", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)

        label = tk.Label(
            frame,
            text="ahh du bist doch auf discord\nwie ist dein username?",
            bg="#fff7d6",
            fg="#3b2a0a",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=7,
            justify="left",
        )
        label.pack()

        entry_var = tk.StringVar(value="")
        entry = tk.Entry(frame, textvariable=entry_var, width=28)
        entry.pack(padx=10, pady=(0, 8))

        buttons = tk.Frame(frame, bg="#fff7d6")
        buttons.pack(pady=(0, 10))

        def _submit() -> None:
            name = entry_var.get().strip()
            if name:
                self.discord_username = name
                self._save_cached_discord_username(name)
                self._show_discord_bubble(name)
            self._hide_discord_username_prompt()

        def _skip() -> None:
            self._hide_discord_username_prompt()

        ok_btn = tk.Button(
            buttons,
            text="OK",
            width=7,
            command=_submit,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        ok_btn.pack(side="left", padx=(0, 6))
        skip_btn = tk.Button(
            buttons,
            text="Egal",
            width=7,
            command=_skip,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        skip_btn.pack(side="left")

        win.update_idletasks()
        # Put the prompt near the center so it's easy to type into.
        px = int(self.screen_w * 0.5 - win.winfo_width() * 0.5)
        py = int(self.screen_h * 0.5 - win.winfo_height() * 0.5)
        px = max(0, min(px, self.screen_w - win.winfo_width()))
        py = max(0, min(py, self.screen_h - win.winfo_height()))
        win.geometry(f"+{px}+{py}")

        self.discord_prompt_window = win
        try:
            entry.focus_set()
        except tk.TclError:
            pass

    def _show_youtube_prompt(self) -> None:
        # While this prompt is open, the pet stands still (handled in _motion_loop).
        self._stop_heist()
        self.cursor_heist_active = False
        self.close_attack_active = False
        self.mouse_lock_active = False

        if self.youtube_prompt_window is not None:
            return

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#e7fff0")

        frame = tk.Frame(win, bg="#e7fff0", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)

        label = tk.Label(
            frame,
            text="was kuckst du jetzt auf youtube",
            bg="#e7fff0",
            fg="#0b2b16",
            font=("Segoe UI", 9, "bold"),
            padx=10,
            pady=7,
        )
        label.pack()

        entry_var = tk.StringVar(value="")
        entry = tk.Entry(frame, textvariable=entry_var, width=30)
        entry.pack(padx=10, pady=(0, 8))

        buttons = tk.Frame(frame, bg="#e7fff0")
        buttons.pack(pady=(0, 10))

        def _submit() -> None:
            self.last_youtube_answer = entry_var.get().strip()
            self._hide_youtube_prompt()

        def _skip() -> None:
            self.last_youtube_answer = ""
            self._hide_youtube_prompt()

        ok_btn = tk.Button(
            buttons,
            text="OK",
            width=7,
            command=_submit,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        ok_btn.pack(side="left", padx=(0, 6))
        skip_btn = tk.Button(
            buttons,
            text="Egal",
            width=7,
            command=_skip,
            bg="#ffffff",
            fg="#111111",
            relief="flat",
        )
        skip_btn.pack(side="left")

        win.update_idletasks()
        px = int(self.x + self.block_size + 10)
        py = int(self.y - 10)
        max_x = max(0, self.screen_w - win.winfo_width())
        max_y = max(0, self.screen_h - win.winfo_height())
        px = max(0, min(px, max_x))
        py = max(0, min(py, max_y))
        win.geometry(f"+{px}+{py}")

        self.youtube_prompt_window = win
        try:
            entry.focus_set()
        except tk.TclError:
            pass

    def _hide_youtube_prompt(self) -> None:
        if self.youtube_prompt_window is not None and self.youtube_prompt_window.winfo_exists():
            self.youtube_prompt_window.destroy()
        self.youtube_prompt_window = None
    
    def _heist_image_target_size(self) -> tuple[int, int]:
        # Make the "stolen picture" window predictable and keep it within the screen on small displays.
        # Typical result is 460x300, but it scales down if the screen is tiny.
        try:
            sw = int(self.screen_w)
            sh = int(self.screen_h)
        except Exception:
            sw, sh = 1920, 1080
        w = min(460, max(240, sw - 260))
        h = min(300, max(180, sh - 300))
        return (int(w), int(h))

    def _start_image_heist(self) -> bool:
        if self.heist_payload_window is not None:
            return False
        if not self.image_paths:
            self._log("Image heist: no image paths (yet).")
            return False
        chosen_photo = None
        # Try a few random cached paths. If a file can't be opened/decoded, drop it from the list
        # so we don't keep hitting the same broken file repeatedly.
        for _ in range(12):
            if not self.image_paths:
                break
            path = random.choice(self.image_paths)
            chosen_photo = self._load_photo(path)
            if chosen_photo is not None:
                break
            try:
                self.image_paths.remove(path)
            except Exception:
                pass
        if chosen_photo is None:
            self._log("Image heist: failed to load any image (12 tries).")
            return False

        self.pending_image_photo = chosen_photo
        self.heist_kind = "image"
        self.heist_active = True
        self.heist_stage = "exit"
        self._log("Image heist: started (exit stage).")
        self.heist_direction = random.choice([1, -1])
        self.heist_exit_x = (
            -self.block_size - 60
            if self.heist_direction == 1
            else self.screen_w + 60
        )
        self.heist_exit_y = random.randint(
            20, max(30, self.screen_h - self.block_size - 20)
        )
        self.heist_target_x = random.randint(
            int(self.screen_w * 0.25),
            int(self.screen_w * 0.75),
        )
        self.heist_speed = random.uniform(8.8, 13.0)
        return True

    def _start_editor_heist(self) -> bool:
        if self.heist_payload_window is not None:
            return False
        self.heist_kind = "editor"
        self.heist_active = True
        self.heist_stage = "exit"
        self.heist_direction = random.choice([1, -1])
        self.heist_exit_x = (
            -self.block_size - 60
            if self.heist_direction == 1
            else self.screen_w + 60
        )
        self.heist_exit_y = random.randint(
            20, max(30, self.screen_h - self.block_size - 20)
        )
        self.heist_target_x = random.randint(
            int(self.screen_w * 0.23),
            int(self.screen_w * 0.76),
        )
        self.heist_speed = random.uniform(8.0, 11.6)
        return True
    
    def _heist_payload_gap(self) -> int:
        # Space between the cube and the payload window.
        return 18

    def _heist_payload_pet_bounds(self) -> tuple[float, float, float, float]:
        # Compute a pet position range where the payload can stay fully on-screen without clamping.
        pad = 10
        gap = self._heist_payload_gap()
        pw = float(self.heist_payload_w)
        ph = float(self.heist_payload_h)

        x_min = float(pad)
        x_max = float(max(pad, self.screen_w - self.block_size - pad))

        if self.heist_direction == 1:
            # Payload is left of the cube.
            x_min = max(x_min, float(pad + pw + gap))
        else:
            # Payload is right of the cube.
            x_max = min(
                x_max,
                float(self.screen_w - pad - self.block_size - gap - pw),
            )

        y_min = float(pad)
        y_max = float(max(pad, self.screen_h - self.block_size - pad))

        # payload_y = pet_y + (block_size - payload_h)/2, keep payload fully visible.
        y_min = max(y_min, float(pad + (ph - self.block_size) / 2.0))
        y_max = min(y_max, float(self.screen_h - pad - (self.block_size + ph) / 2.0))

        return (x_min, x_max, y_min, y_max)

    def _heist_adjust_target_for_payload(self) -> None:
        # Once we know payload dimensions, pick a target position that keeps everything visible.
        x_min, x_max, y_min, y_max = self._heist_payload_pet_bounds()

        if y_max >= y_min:
            self.y = max(y_min, min(self.y, y_max))

        if x_max >= x_min:
            self.heist_target_x = float(random.randint(int(x_min), int(x_max)))
        else:
            # If the screen is too small to satisfy the constraints, pick the "least bad" position.
            tx = x_min if self.heist_direction == 1 else x_max
            self.heist_target_x = float(max(0.0, min(tx, float(self.screen_w - self.block_size))))

    def _heist_tick(self) -> None:
        if self.heist_stage == "exit":
            self._steer_to_target(self.heist_exit_x, self.heist_exit_y, force=0.90)
            self._clamp_velocity(14.0)
            self._advance_position(allow_offscreen=True)
            gone = (self.heist_direction == 1 and self.x <= -self.block_size - 10) or (
                self.heist_direction == -1
                and self.x >= self.screen_w + 10
            )
            if gone:
                self._begin_pull_stage()
            return

        if self.heist_stage == "pull":
            self.x += self.heist_direction * self.heist_speed
            self.y += random.uniform(-0.7, 0.7)
            # Keep payload visible based on its real size.
            _x_min, _x_max, y_min, y_max = self._heist_payload_pet_bounds()
            if y_max >= y_min:
                self.y = max(y_min, min(self.y, y_max))
            else:
                # Fallback: old clamp.
                self.y = max(10.0, min(self.y, float(self.screen_h - self.block_size - 10)))
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
            self._position_payload_window()

            reached = (self.heist_direction == 1 and self.x >= self.heist_target_x) or (
                self.heist_direction == -1 and self.x <= self.heist_target_x
            )
            if reached:
                # Snap to the final target so the payload doesn't end up slightly misaligned due to overshoot.
                try:
                    self.x = float(self.heist_target_x)
                    self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
                    self._position_payload_window()
                except Exception:
                    pass
                if self.heist_kind == "editor":
                    now = time.monotonic()
                    self.heist_stage = "linger"
                    self.heist_linger_until = now + random.uniform(2.2, 4.0)
                    chance = 0.12
                    dur = 2.0
                    if getattr(self, "editor_mischief_enabled", False):
                        try:
                            chance = float(getattr(self.pet_profile, "editor_typing_chance", 0.22))
                        except Exception:
                            chance = 0.22
                        dur = random.uniform(1.6, 3.1)
                    if random.random() < chance:
                        self.heist_editor_typing_until = min(
                            self.heist_linger_until, now + dur
                        )
                        self.heist_editor_next_type = 0.0
                    else:
                        self.heist_editor_typing_until = 0.0
                        self.heist_editor_next_type = 0.0
                    self.vx = 0.0
                    self.vy = 0.0
                else:
                    self._stop_heist(destroy_payload=False)
                    self.vx += random.uniform(-2.4, 2.4)
                    self.vy += random.uniform(-2.4, 2.4)
            return

        if self.heist_stage == "linger":
            now = time.monotonic()
            self._position_payload_window()
            if now < self.heist_editor_typing_until:
                self._tick_editor_typing(now)
            if now >= self.heist_linger_until:
                self._stop_heist(destroy_payload=False)
                self.vx += random.uniform(-1.7, 1.7)
                self.vy += random.uniform(-1.7, 1.7)

    def _begin_pull_stage(self) -> None:
        if self.heist_kind == "image":
            if self.pending_image_photo is None:
                self._stop_heist()
                return
        elif self.heist_kind != "editor":
            self._stop_heist()
            return

        self.heist_stage = "pull"
        self.x = (
            -self.block_size - 20
            if self.heist_direction == 1
            else self.screen_w + 20
        )
        self.vx = 0.0
        self.vy = 0.0

        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#111111")

        if self.heist_kind == "image":
            frame = tk.Frame(win, bg="#0f172a", bd=2, relief="solid")
            frame.pack(fill="both", expand=True)
            titlebar = tk.Frame(frame, bg="#1f2937")
            titlebar.pack(fill="x")
            title = tk.Label(
                titlebar,
                text="stolen_picture.png",
                bg="#1f2937",
                fg="#f8fafc",
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                padx=8,
                pady=4,
            )
            title.pack(side="left", fill="x", expand=True)
            close_btn = tk.Button(
                titlebar,
                text="X",
                command=self._on_payload_close,
                bg="#ef4444",
                fg="#ffffff",
                activebackground="#dc2626",
                activeforeground="#ffffff",
                bd=0,
                relief="flat",
                padx=6,
                pady=2,
                font=("Segoe UI", 9, "bold"),
            )
            close_btn.pack(side="right", padx=4, pady=2)
            img_w, img_h = self._heist_image_target_size()
            canvas = tk.Canvas(
                frame,
                width=img_w,
                height=img_h,
                bg="#0f172a",
                bd=0,
                highlightthickness=0,
            )
            canvas.pack()
            if self.pending_image_photo is not None:
                canvas.create_image(img_w // 2, img_h // 2, image=self.pending_image_photo)
            self.heist_image_photo = self.pending_image_photo
            self.pending_image_photo = None
            self.heist_editor_text = None
        else:
            outer = tk.Frame(win, bg="#f3f4f6", bd=2, relief="solid")
            outer.pack(fill="both", expand=True)

            titlebar = tk.Frame(outer, bg="#e5e7eb")
            titlebar.pack(fill="x")
            title = tk.Label(
                titlebar,
                text=self.pet_profile.editor_title,
                bg="#e5e7eb",
                fg="#111827",
                font=("Segoe UI", 9, "bold"),
                anchor="w",
                padx=8,
                pady=4,
            )
            title.pack(side="left", fill="x", expand=True)
            close_btn = tk.Button(
                titlebar,
                text="X",
                command=self._on_payload_close,
                bg="#f3f4f6",
                fg="#111827",
                activebackground="#ef4444",
                activeforeground="#ffffff",
                bd=0,
                relief="flat",
                padx=6,
                pady=2,
                font=("Segoe UI", 9, "bold"),
            )
            close_btn.pack(side="right", padx=4, pady=2)

            menubar = tk.Frame(outer, bg="#f8fafc")
            menubar.pack(fill="x")
            for label_text in ["File", "Edit", "Format", "View", "Help"]:
                item = tk.Label(
                    menubar,
                    text=label_text,
                    bg="#f8fafc",
                    fg="#111827",
                    font=("Segoe UI", 9),
                    padx=6,
                    pady=2,
                )
                item.pack(side="left")

            text = tk.Text(
                outer,
                width=34,
                height=8,
                bg="#ffffff",
                fg="#0f172a",
                insertbackground="#0f172a",
                font=("Consolas", 10),
                bd=0,
                highlightthickness=0,
                wrap="word",
            )
            text.pack(fill="both", expand=True, padx=6, pady=6)
            text.insert(
                "end",
                self.pet_profile.editor_intro_text,
            )
            text.see("end")
            self.heist_editor_text = text
            self.heist_image_photo = None

        win.update_idletasks()
        self.heist_payload_window = win
        # Don't steal focus from whatever the user is typing in.
        self._make_noactivate(win)
        self.heist_payload_w = max(120, win.winfo_width())
        self.heist_payload_h = max(50, win.winfo_height())
        self._heist_adjust_target_for_payload()
        self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
        self._position_payload_window()
        self._ding()

    def _position_payload_window(self) -> None:
        if self.heist_payload_window is None or not self.heist_payload_window.winfo_exists():
            return
        gap = self._heist_payload_gap()
        if self.heist_direction == 1:
            # Payload trails behind on the left side.
            payload_x = int(self.x - (self.heist_payload_w + gap))
        else:
            # Payload trails behind on the right side.
            payload_x = int(self.x + self.block_size + gap)
        payload_y = int(self.y + (self.block_size - self.heist_payload_h) / 2)
        max_x_on = max(0, self.screen_w - self.heist_payload_w)
        max_y = max(0, self.screen_h - self.heist_payload_h)

        # During "pull" allow the payload to start off-screen and slide in, otherwise it looks like it spawns.
        if self.heist_stage == "pull":
            min_x = -self.heist_payload_w - 140
            max_x = self.screen_w + 140
        else:
            min_x = 0
            max_x = max_x_on

        payload_x = max(min_x, min(payload_x, max_x))
        payload_y = max(0, min(payload_y, max_y))
        self.heist_payload_window.geometry(f"+{payload_x}+{payload_y}")

        if self.heist_kind == "image":
            self._ensure_rope_overlay()
            self._update_rope(payload_x, payload_y)

    def _destroy_rope_overlay(self) -> None:
        if self.rope_window is not None:
            try:
                if self.rope_window.winfo_exists():
                    self.rope_window.destroy()
            except Exception:
                pass
        self.rope_window = None
        self.rope_canvas = None
        self.rope_line_shadow = None
        self.rope_line = None

    def _ensure_rope_overlay(self) -> None:
        # Rope is only shown while pulling an image payload.
        if self.heist_kind != "image":
            self._destroy_rope_overlay()
            return
        if self.heist_stage != "pull":
            self._destroy_rope_overlay()
            return
        if self.heist_payload_window is None:
            self._destroy_rope_overlay()
            return

        if self.rope_window is not None:
            try:
                if self.rope_window.winfo_exists():
                    return
            except Exception:
                pass
            self._destroy_rope_overlay()

        if USER32 is None:
            # Without USER32 we can't make a fullscreen overlay click-through safely.
            self._log_once("rope_no_user32", "Rope overlay disabled (USER32 unavailable).")
            return

        # Transparent overlay window that covers the screen.
        trans = "#00ff00"
        try:
            win = tk.Toplevel(self.root)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
            win.configure(bg=trans)

            # Windows Tk supports transparentcolor; if not, don't risk blocking input.
            try:
                win.attributes("-transparentcolor", trans)
            except Exception:
                win.destroy()
                self._log_once("rope_no_transparentcolor", "Rope overlay disabled (-transparentcolor unsupported).")
                return

            canvas = tk.Canvas(win, bg=trans, highlightthickness=0, bd=0)
            canvas.pack(fill="both", expand=True)

            shadow = canvas.create_line(
                0,
                0,
                0,
                0,
                fill="#000000",
                width=6,
                capstyle="round",
                joinstyle="round",
                smooth=True,
                splinesteps=12,
                tags="rope",
            )
            line = canvas.create_line(
                0,
                0,
                0,
                0,
                fill="#7f1d1d",
                width=3,
                capstyle="round",
                joinstyle="round",
                smooth=True,
                splinesteps=12,
                tags="rope",
            )

            self.rope_window = win
            self.rope_canvas = canvas
            self.rope_line_shadow = shadow
            self.rope_line = line
            self._make_clickthrough(win)
            # Keep the actual heist windows visually above the rope overlay.
            try:
                self.heist_payload_window.lift()
                self.root.lift()
            except Exception:
                pass
        except Exception:
            self._destroy_rope_overlay()
            if self.debug_enabled:
                self._log_exc("_ensure_rope_overlay")

    def _update_rope(self, payload_x: int, payload_y: int) -> None:
        if self.rope_canvas is None or self.rope_window is None:
            return
        if self.rope_line is None or self.rope_line_shadow is None:
            return
        try:
            if not self.rope_window.winfo_exists():
                return
        except Exception:
            return

        # Keep overlay sized to the current screen cache.
        try:
            self.rope_window.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        except Exception:
            pass

        # Rope anchor points.
        pet_y = float(self.y) + self.block_size / 2.0
        if self.heist_direction == 1:
            sx = float(self.x)
            ex = float(payload_x + self.heist_payload_w)
        else:
            sx = float(self.x + self.block_size)
            ex = float(payload_x)
        sy = pet_y
        ey = float(payload_y) + self.heist_payload_h / 2.0

        dx = ex - sx
        dy = ey - sy
        dist = max(1.0, (dx * dx + dy * dy) ** 0.5)
        nx = -dy / dist
        ny = dx / dist

        # Wavy rope (stronger in the middle, tighter near the ends).
        tnow = time.monotonic()
        phase = tnow * 7.0 + self.rope_phase
        amp = min(22.0, 2.5 + dist * 0.030)

        pts: list[float] = []
        n = 9
        for i in range(n):
            t = i / (n - 1)
            x = sx + dx * t
            y = sy + dy * t
            if 0 < i < n - 1:
                envelope = math.sin(math.pi * t)
                w1 = math.sin(phase + t * math.pi * 2.6)
                w2 = math.sin(phase * 0.7 + t * math.pi * 4.2)
                wig = (w1 * 0.80 + w2 * 0.20) * amp * envelope
                x += nx * wig
                y += ny * wig
            pts.extend([x, y])

        try:
            self.rope_canvas.coords(self.rope_line_shadow, *pts)
            self.rope_canvas.coords(self.rope_line, *pts)
        except Exception:
            pass

    def _editor_random_chunk(self) -> str:
        # Only types into the prank Notepad-style window (never edits real files).
        prof = getattr(self, "pet_profile", PET_PROFILES["cube"])
        base_chunks = list(getattr(prof, "editor_chunks", ())) or ["lol "]

        mischief = bool(getattr(self, "editor_mischief_enabled", False))
        hunger_enabled = bool(getattr(self, "hunger_enabled", False))
        try:
            hunger = float(getattr(self, "hunger", 1.0))
        except Exception:
            hunger = 1.0

        # If hungry, beg for data.
        if hunger_enabled and hunger <= 0.22 and random.random() < 0.55:
            chunk = random.choice(
                [
                    "fuetter mich ",
                    "daten pls ",
                    "ich hab hunger ",
                    "gib daten ",
                    "DATA! ",
                ]
            )
        # If we got fed with data, occasionally spit it back out into the editor.
        elif mischief and self.food_tokens and random.random() < 0.55:
            k = min(len(self.food_tokens), random.randint(1, 3))
            toks = random.sample(self.food_tokens, k=k)
            chunk = " ".join(toks) + " "
        else:
            chunk = random.choice(base_chunks)

        # Extra "random kacke" in mischief mode.
        if mischief and random.random() < 0.14:
            alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
            n = random.randint(4, 11)
            chunk += "".join(random.choice(alphabet) for _ in range(n)) + " "

        if len(chunk) > 140:
            chunk = chunk[:140] + " "
        return chunk

    def _tick_editor_typing(self, now: float) -> None:
        if self.heist_editor_text is None:
            return
        if now < self.heist_editor_next_type:
            return

        chunk = self._editor_random_chunk()
        if random.random() < (0.40 if getattr(self, "editor_mischief_enabled", False) else 0.35):
            chunk += "\n"
        self.heist_editor_text.insert("end", chunk)
        self.heist_editor_text.see("end")
        self.heist_editor_next_type = now + random.uniform(0.08, 0.20)

    def _on_payload_close(self) -> None:
        self._stop_heist(destroy_payload=False)
        if self.heist_payload_window is not None and self.heist_payload_window.winfo_exists():
            self.heist_payload_window.destroy()
        self.heist_payload_window = None
        self.heist_image_photo = None
        self.heist_payload_w = 0
        self.heist_payload_h = 0
        self.heist_editor_text = None
        now = time.monotonic()
        self.angry_until = max(self.angry_until, now + 5.0)

    def _stop_heist(self, destroy_payload: bool = True) -> None:
        # Always remove visual overlays when a heist stops.
        self._destroy_rope_overlay()
        was_active = self.heist_active or self.heist_stage != "idle"
        self.heist_active = False
        self.heist_kind = "image"
        self.heist_stage = "idle"
        self.pending_image_photo = None
        if destroy_payload and was_active:
            if (
                self.heist_payload_window is not None
                and self.heist_payload_window.winfo_exists()
            ):
                self.heist_payload_window.destroy()
            self.heist_payload_window = None
            self.heist_image_photo = None
            self.heist_payload_w = 0
            self.heist_payload_h = 0
            self.heist_editor_text = None
        self.heist_editor_typing_until = 0.0
        self.heist_editor_next_type = 0.0
        self.heist_linger_until = 0.0

    def _show_intro_credit(self) -> None:
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="#ffef9a")

        frame = tk.Frame(win, bg="#ffef9a", bd=2, relief="solid")
        frame.pack(fill="both", expand=True)
        label = tk.Label(
            frame,
            text="made by Lennart and Ben",
            bg="#ffef9a",
            fg="#111111",
            font=("Segoe UI", 10, "bold"),
            padx=10,
            pady=8,
        )
        label.pack()

        win.update_idletasks()
        x = int(self.x + self.block_size + 14)
        y = int(self.y - 2)
        max_x = max(0, self.screen_w - win.winfo_width())
        max_y = max(0, self.screen_h - win.winfo_height())
        x = max(0, min(x, max_x))
        y = max(0, min(y, max_y))
        win.geometry(f"+{x}+{y}")

        self.intro_window = win

    def _end_intro_credit(self) -> None:
        self.intro_active = False
        if self.intro_window is not None and self.intro_window.winfo_exists():
            self.intro_window.destroy()
        self.intro_window = None
        if bool(getattr(self, "show_options_on_start", False)):
            self._show_options_window()

    def _spawn_clone(self, now: float) -> None:
        # Clone is a separate window that runs around for a while, then disappears.
        win = tk.Toplevel(self.root)
        win.overrideredirect(True)
        win.attributes("-topmost", True)
        win.configure(bg="black")

        canvas = tk.Canvas(
            win,
            bg="#000000",
            width=self.block_size,
            height=self.block_size,
            bd=0,
            highlightthickness=2,
            highlightbackground="#141414",
            cursor="pirate",
        )
        canvas.pack(fill="both", expand=True)

        self.clone_face_key = random.choice(["frech", "silly", "confused"])
        img = self.face_assets.get(self.clone_face_key) or self.face_assets.get("frech")
        if img is not None:
            canvas.create_image(
                self.block_size // 2,
                self.block_size // 2,
                image=img,
                tags="face",
            )
        else:
            canvas.create_text(
                self.block_size // 2,
                self.block_size // 2,
                text="CLONE",
                fill="#f0f0f0",
                font=("Segoe UI", 10, "bold"),
                tags="face",
            )

        max_x = max(0, self.screen_w - self.block_size)
        max_y = max(0, self.screen_h - self.block_size)
        self.clone_x = float(max(0, min(int(self.x + random.randint(-140, 140)), max_x)))
        self.clone_y = float(max(0, min(int(self.y + random.randint(-120, 120)), max_y)))
        self.clone_vx = random.choice([-1.0, 1.0]) * random.uniform(3.0, 6.5)
        self.clone_vy = random.choice([-1.0, 1.0]) * random.uniform(3.0, 6.5)
        win.geometry(f"{self.block_size}x{self.block_size}+{int(self.clone_x)}+{int(self.clone_y)}")

        self.clone_window = win
        self.clone_canvas = canvas
        self.clone_until = now + random.uniform(10.0, 22.0)
        self.next_clone_spawn_at = now + random.uniform(30.0, 75.0)
        self._ding()

    def _clone_tick(self, now: float) -> None:
        if self.clone_window is None:
            return
        if now >= self.clone_until or not self.clone_window.winfo_exists():
            self._destroy_clone()
            return

        # Simple movement with bouncing.
        self.clone_x += self.clone_vx
        self.clone_y += self.clone_vy

        max_x = max(0, self.screen_w - self.block_size)
        max_y = max(0, self.screen_h - self.block_size)

        bounced = False
        if self.clone_x < 0:
            self.clone_x = 0.0
            self.clone_vx = abs(self.clone_vx) * 0.95
            bounced = True
        elif self.clone_x > max_x:
            self.clone_x = float(max_x)
            self.clone_vx = -abs(self.clone_vx) * 0.95
            bounced = True

        if self.clone_y < 0:
            self.clone_y = 0.0
            self.clone_vy = abs(self.clone_vy) * 0.95
            bounced = True
        elif self.clone_y > max_y:
            self.clone_y = float(max_y)
            self.clone_vy = -abs(self.clone_vy) * 0.95
            bounced = True

        if bounced and random.random() < 0.18:
            self._ding()

        self.clone_window.geometry(f"+{int(self.clone_x)}+{int(self.clone_y)}")

        if random.random() < 0.05:
            self.clone_vx += random.uniform(-1.8, 1.8)
            self.clone_vy += random.uniform(-1.8, 1.8)

    def _destroy_clone(self) -> None:
        if self.clone_window is not None and self.clone_window.winfo_exists():
            self.clone_window.destroy()
        self.clone_window = None
        self.clone_canvas = None

    def _update_emotion(self, now: float) -> None:
        target = "frech"
        if now < self.angry_until or self.close_attack_active or self.cursor_heist_active or self.window_kill_active:
            target = "mad"
        elif self.close_prompt_window is not None:
            target = "silly"
        elif now < self.stunned_until or now < self.confused_until:
            target = "confused"

        if target != self.emotion:
            self.emotion = target
            self._draw_face()

    def _draw_face(self) -> None:
        self.block.delete("face")
        key = "frech"
        
        if self.emotion == "scary":
            if self._final_bloody_img:
                self.block.create_image(
                    self.block_size // 2,
                    self.block_size // 2,
                    image=self._final_bloody_img,
                    tags="face",
                )
                self._draw_hud()
                return
            key = "mad"

        if self.emotion == "silly":
            key = "silly"
        elif self.emotion == "confused":
            key = "confused"
        elif self.emotion == "mad":
            key = "mad"

        image = self.face_assets.get(key)
        if image is None:
            self.block.create_text(
                self.block_size // 2,
                self.block_size // 2,
                text=key.upper(),
                fill="#f0f0f0",
                font=("Segoe UI", 10, "bold"),
                tags="face",
            )
            self._draw_hud()
            return

        self.block.create_image(
            self.block_size // 2,
            self.block_size // 2,
            image=image,
            tags="face",
        )
        self._draw_hud()

    def _draw_hud(self) -> None:
        # Lightweight overlay; used for optional hunger bar and per-pet name tag.
        try:
            self.block.delete("hud")
        except Exception:
            return

        hunger_on = bool(getattr(self, "hunger_enabled", False))
        show_name = bool(getattr(self, "pet_profile_id", "cube") != "cube")
        if (not hunger_on) and (not show_name):
            return

        if show_name:
            try:
                name = str(getattr(self.pet_profile, "name", "")).strip() or "Pet"
            except Exception:
                name = "Pet"
            pid = str(getattr(self, "pet_profile_id", "cube"))
            if pid == "aki":
                tag_bg = "#fecaca"
                tag_fg = "#7f1d1d"
            elif pid == "pamuk":
                tag_bg = "#bbf7d0"
                tag_fg = "#14532d"
            else:
                tag_bg = "#e5e7eb"
                tag_fg = "#111827"
            self.block.create_rectangle(
                4,
                4,
                4 + min(64, 8 + len(name) * 6),
                18,
                fill=tag_bg,
                outline="",
                tags="hud",
            )
            self.block.create_text(
                8,
                11,
                text=name[:10],
                fill=tag_fg,
                font=("Segoe UI", 8, "bold"),
                anchor="w",
                tags="hud",
            )

        if not hunger_on:
            return

        try:
            h = float(getattr(self, "hunger", 1.0))
        except Exception:
            h = 1.0
        h = max(0.0, min(1.0, h))

        pad = 5
        bar_h = 6
        x0 = pad
        x1 = max(pad + 1, self.block_size - pad)
        y1 = max(pad + 1, self.block_size - pad)
        y0 = max(pad, y1 - bar_h)

        if h >= 0.50:
            color = "#22c55e"
        elif h >= 0.20:
            color = "#f59e0b"
        else:
            color = "#ef4444"

        self.block.create_rectangle(
            x0,
            y0,
            x1,
            y1,
            fill="#0b0b0b",
            outline="#111111",
            width=1,
            tags="hud",
        )
        fill_w = int((x1 - x0) * h)
        if fill_w > 0:
            self.block.create_rectangle(
                x0,
                y0,
                x0 + fill_w,
                y1,
                fill=color,
                outline="",
                tags="hud",
            )

    def _load_face_assets(self) -> dict[str, object]:
        files = {
            "frech": "Frech_Birld.png",
            "silly": "Silly_Bild.png",
            "confused": "Verwirrt_Bild.png",
            "mad": "Wutend_Bild.png",
        }
        loaded: dict[str, object] = {}
        for key, filename in files.items():
            photo = self._load_face_asset(self.asset_dir / filename)
            if photo is not None:
                loaded[key] = photo
        return loaded

    def _load_face_asset(self, path: Path):
        if not path.exists():
            return None
        target = max(24, self.block_size - 4)
        try:
            if PIL_AVAILABLE:
                with Image.open(path) as _im:  # type: ignore[name-defined]
                    pil = ImageOps.exif_transpose(_im)  # type: ignore[name-defined]
                    image = pil.convert("RGBA")
                resampling = getattr(Image, "Resampling", Image)  # type: ignore[name-defined]
                image = image.resize((target, target), resampling.LANCZOS)
                return ImageTk.PhotoImage(image)  # type: ignore[name-defined]
            photo = tk.PhotoImage(file=str(path))
            w = max(1, photo.width())
            h = max(1, photo.height())
            factor = max(w / target, h / target, 1.0)
            if factor > 1.0:
                step = max(1, int(math.ceil(factor)))
                photo = photo.subsample(step, step)
            return photo
        except Exception:
            return None

    def _collect_image_paths(self, max_files: int) -> list[Path]:
        exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ppm", ".pgm"}
        if not PIL_AVAILABLE:
            # Without PIL, Tkinter only supports PNG, GIF, PPM/PGM reliably
            exts = {".png", ".gif", ".ppm", ".pgm"}
            
        search_roots = [
            (Path.home() / "Pictures", 7),
            (Path.home() / "Desktop", 5),
            (Path.home() / "Downloads", 5),
            (Path.home(), 3),
        ]

        found: list[Path] = []
        seen: set[str] = set()
        skip_dirs = {"node_modules", "venv", ".git", "__pycache__", "$recycle.bin", "system volume information"}

        for root, max_depth in search_roots:
            if not root.exists():
                continue
            for dirpath, dirnames, filenames in os.walk(root):
                rel_depth = len(Path(dirpath).relative_to(root).parts)
                if rel_depth >= max_depth:
                    dirnames[:] = []
                dirnames[:] = [
                    d
                    for d in dirnames
                    if d.lower() not in skip_dirs and not d.startswith(".")
                ]

                for filename in filenames:
                    suffix = Path(filename).suffix.lower()
                    if suffix not in exts:
                        continue
                    file_path = Path(dirpath) / filename
                    key = str(file_path).lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append(file_path)
                    if len(found) >= max_files:
                        random.shuffle(found)
                        return found

        random.shuffle(found)
        return found

    def _load_photo(self, path: Path):
        try:
            target_w, target_h = self._heist_image_target_size()
            if PIL_AVAILABLE:
                with Image.open(path) as _im:  # type: ignore[name-defined]
                    pil = ImageOps.exif_transpose(_im)  # type: ignore[name-defined]
                    image = pil.convert("RGBA") if pil.mode != "RGBA" else pil.copy()
                resampling = getattr(Image, "Resampling", Image)  # type: ignore[name-defined]
                image.thumbnail((target_w, target_h), resample=resampling.LANCZOS)
                return ImageTk.PhotoImage(image)  # type: ignore[name-defined]

            photo = tk.PhotoImage(file=str(path))
            w = max(1, photo.width())
            h = max(1, photo.height())
            factor = max(w / target_w, h / target_h, 1.0)
            if factor > 1.0:
                step = max(1, int(math.ceil(factor)))
                photo = photo.subsample(step, step)
            return photo
        except Exception:
            return None

    def run(self) -> None:
        self.root.mainloop()
