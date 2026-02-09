import math
import os
import random
import threading
import time
import tkinter as tk
from pathlib import Path

try:
    from PIL import Image, ImageTk  # type: ignore

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
        self.asset_dir = Path(__file__).resolve().parent
        self.log_path = self.asset_dir / "cubepet.log"
        self.image_cache_path = self.asset_dir / ".image_cache.txt"

        self.root = tk.Tk()
        self.root.title("Ultra Nerviger Block")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.configure(bg="black")

        # Optimization: Cache screen dimensions to avoid Tcl calls in loops
        self.screen_w = self.root.winfo_screenwidth()
        self.screen_h = self.root.winfo_screenheight()

        self._load_settings()
        self._discord_rpc = None
        self._discord_rpc_connected = False
        self._last_rpc_update_t = 0.0

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
        self.block.bind("<Button-3>", self._on_right_click)
        self.block.bind("<ButtonPress-3>", self._on_right_click)

        self.root.bind("<Escape>", lambda _event: self.root.destroy())
        self.root.bind("<Control-Shift-Q>", lambda _event: self.root.destroy())

        self.root.after(16, self._motion_loop)
        self.root.after(650, self._annoy_loop)
        self.root.after(900, self._youtube_watch_loop)
        self.root.after(1100, self._discord_watch_loop)

        if self.discord_rpc_enabled:
            self._init_discord_rpc()
        if self.notifications_enabled:
            self._notify("CubePet", "CubePet ist gestartet.")

    def _log(self, msg: str) -> None:
        # Minimal file logger because this is a .pyw (no console).
        try:
            ts = time.strftime("%Y-%m-%d %H:%M:%S")
            self.log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.log_path.open("a", encoding="utf-8") as f:
                f.write(f"[{ts}] {msg}\n")
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

    def _load_settings(self) -> None:
        # Disable Windows "bell" sound spam by default. Set CUBEPET_SOUND=1 to enable.
        self.sounds_enabled = self._env_bool("CUBEPET_SOUND", default=False)

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

    def _user_is_active(self) -> bool:
        if not self.respect_user_input:
            return False
        return self._user_idle_seconds() < self.active_grace_s

    def _can_start_major_prank(self, now: float) -> bool:
        if self.intro_active:
            return False
        if self._dragging or self.ignore_drag_until_release:
            return False
        if self.close_prompt_window is not None or self.youtube_prompt_window is not None:
            return False
        if self.discord_prompt_window is not None:
            return False
        if self.heist_active or self.cursor_heist_active or self.cursor_pingpong_active:
            return False
        if self.mouse_lock_active or self.close_attack_active:
            return False
        if now < self.stunned_until:
            return False
        if self._user_is_active():
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
            paths = self._collect_image_paths(max_files=max_files)
            self._save_image_cache(paths)

            def apply() -> None:
                self.image_paths = paths
                self._image_scan_in_progress = False
                self._log(f"Image scan done: {len(paths)} files.")

            try:
                self.root.after(0, apply)
            except Exception:
                self._image_scan_in_progress = False

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
            pass

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
        if not self._discord_rpc_connected or self._discord_rpc is None:
            return
        now = time.monotonic()
        if (not force) and (now - self._last_rpc_update_t) < 15.0:
            return
        try:
            self._discord_rpc.update(
                details="Spielt CubePet",
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

    def _ding(self) -> None:
        if self.sounds_enabled:
            try:
                self.root.bell()
            except tk.TclError:
                pass

    def _start_drag(self, event) -> None:
        if (
            self.intro_active
            or self.close_prompt_window is not None
            or self.youtube_prompt_window is not None
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

        if self.close_prompt_window is not None or self.youtube_prompt_window is not None:
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
                    self._steer_to_target(tx, ty, force=0.42)
                    self._clamp_velocity(self.max_speed)
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
        no_btn.pack(side="left")

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

    def _start_final_sequence(self) -> None:
        self.dying = True
        self.root.withdraw()
        
        self.final_window = tk.Toplevel(self.root)
        self.final_window.configure(bg="black", cursor="none")
        self.final_window.geometry(f"{self.screen_w}x{self.screen_h}+0+0")
        self.final_window.overrideredirect(True)
        self.final_window.attributes("-topmost", True)
        
        self.final_canvas = tk.Canvas(self.final_window, bg="black", highlightthickness=0)
        self.final_canvas.pack(fill="both", expand=True)
        
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        r = 25
        gap = 90
        for i in range(-1, 2):
            x = cx + i * gap
            self.final_canvas.create_oval(x - r, cy - r, x + r, cy + r, fill="#ff0000", outline="#ff0000", tags="dots")
            
        self.root.after(10000, self._show_bloody_ending)

    def _show_bloody_ending(self) -> None:
        if not self.final_canvas.winfo_exists():
            return
        self.final_canvas.delete("dots")
        
        cx = self.screen_w // 2
        cy = self.screen_h // 2
        
        # Try to create a "bloody" version if PIL is available, else use mad face
        img = self.face_assets.get("mad")
        if PIL_AVAILABLE and img:
            try:
                path = self.asset_dir / "Wutend_Bild.png"
                if path.exists():
                    pil_img = Image.open(path).convert("RGBA")
                    r, g, b, a = pil_img.split()
                    r = r.point(lambda i: i * 1.5) # Boost red
                    g = g.point(lambda i: i * 0.3) # Reduce green
                    b = b.point(lambda i: i * 0.3) # Reduce blue
                    pil_img = Image.merge("RGBA", (r, g, b, a))
                    pil_img = pil_img.resize((256, 256), Image.Resampling.LANCZOS)
                    self._final_bloody_img = ImageTk.PhotoImage(pil_img)
                    img = self._final_bloody_img
            except Exception:
                pass
        
        if img:
            self.final_canvas.create_image(cx, cy, image=img, tags="face")
            
        self.final_text_idx = 0
        self.final_message = "warum?"
        self.root.after(2000, self._type_final_message)

    def _type_final_message(self) -> None:
        if not self.final_canvas.winfo_exists():
            return
            
        if self.final_text_idx < len(self.final_message):
            char = self.final_message[self.final_text_idx]
            self.final_text_idx += 1
            
            current = self.final_message[:self.final_text_idx]
            self.final_canvas.delete("msg")
            
            cx = self.screen_w // 2
            cy = self.screen_h // 2 + 160
            self.final_canvas.create_text(cx, cy, text=current, fill="red", font=("Segoe UI", 28, "bold"), tags="msg")
            
            self.root.after(600, self._type_final_message)
        else:
            self.root.after(3000, self.root.destroy)

    def _close_prompt_no(self) -> None:
        self._hide_close_prompt()

    def _hide_close_prompt(self) -> None:
        if self.close_prompt_window is not None and self.close_prompt_window.winfo_exists():
            self.close_prompt_window.destroy()
        self.close_prompt_window = None

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
            if (
                now >= self.stunned_until
                and not self.cursor_heist_active
                and not self.mouse_lock_active
                and not self.cursor_pingpong_active
                and not self.heist_active
                and not self.window_kill_active
                and not self.close_attack_active
                and self.heist_payload_window is None
                and self.close_prompt_window is None
                and self.youtube_prompt_window is None
            ):
                if now >= self.next_editor_heist_at:
                    if editor_idle_ok and self._start_editor_heist():
                        if self.notifications_enabled:
                            self._notify("CubePet", "CubePet macht jetzt Editor-Heist.")
                        self.next_editor_heist_at = now + random.uniform(22.0, 54.0)
                        self.next_image_heist_at = max(
                            self.next_image_heist_at, now + random.uniform(7.0, 16.0)
                        )
                    else:
                        self.next_editor_heist_at = now + random.uniform(10.0, 20.0)
                elif now >= self.next_image_heist_at:
                    if image_idle_ok and self._start_image_heist():
                        if self.notifications_enabled:
                            self._notify("CubePet", "CubePet klaut ein Bild.")
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
            ):
                self._youtube_prompted_session = True
                if self.notifications_enabled:
                    self._notify("CubePet", "YouTube erkannt: CubePet nervt jetzt.")
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
                and self.discord_prompt_window is None
            ):
                self._discord_prompted_session = True
                if self.notifications_enabled:
                    self._notify("CubePet", "Discord erkannt: CubePet schaut zu.")
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

    def _start_image_heist(self) -> bool:
        if self.heist_payload_window is not None:
            return False
        if not self.image_paths:
            self._log("Image heist: no image paths (yet).")
            return False
        chosen_photo = None
        for _ in range(10):
            path = random.choice(self.image_paths)
            chosen_photo = self._load_photo(path)
            if chosen_photo is not None:
                break
        if chosen_photo is None:
            self._log("Image heist: failed to load any image (10 tries).")
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
            self.y = max(
                10.0,
                min(
                    self.y,
                    float(self.screen_h - self.block_size - 10),
                ),
            )
            self.root.geometry(f"+{int(self.x)}+{int(self.y)}")
            self._position_payload_window()

            reached = (self.heist_direction == 1 and self.x >= self.heist_target_x) or (
                self.heist_direction == -1 and self.x <= self.heist_target_x
            )
            if reached:
                if self.heist_kind == "editor":
                    now = time.monotonic()
                    self.heist_stage = "linger"
                    self.heist_linger_until = now + random.uniform(2.2, 4.0)
                    if random.random() < 0.12:
                        self.heist_editor_typing_until = min(
                            self.heist_linger_until, now + 2.0
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
                text="✕",
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
            label = tk.Label(frame, image=self.pending_image_photo, bg="#0f172a", bd=0)
            label.pack()
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
                text="annoying_editor.txt - Notepad",
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
                text="✕",
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
                "HEHEHEHA\n\n"
                "ich zieh den editor einfach von der seite rein.\n"
                "du tippst? nein, ich tippe.\n",
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
        self._position_payload_window()
        self._ding()

    def _position_payload_window(self) -> None:
        if self.heist_payload_window is None or not self.heist_payload_window.winfo_exists():
            return
        payload_x = int(self.x - self.heist_direction * (self.heist_payload_w + 18))
        payload_y = int(self.y + (self.block_size - self.heist_payload_h) / 2)
        max_x = max(0, self.screen_w - self.heist_payload_w)
        max_y = max(0, self.screen_h - self.heist_payload_h)
        payload_x = max(0, min(payload_x, max_x))
        payload_y = max(0, min(payload_y, max_y))
        self.heist_payload_window.geometry(f"+{payload_x}+{payload_y}")

    def _tick_editor_typing(self, now: float) -> None:
        if self.heist_editor_text is None:
            return
        if now < self.heist_editor_next_type:
            return

        chunk = random.choice(
            [
                "Halllllo ",
                "HEHEHEHA ",
                "lol ",
                "du kannst nix machen ",
                "hehe ",
                "hmmmm ",
            ]
        )
        if random.random() < 0.35:
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
            return

        self.block.create_image(
            self.block_size // 2,
            self.block_size // 2,
            image=image,
            tags="face",
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
                image = Image.open(path).convert("RGBA")  # type: ignore[name-defined]
                resampling = getattr(Image, "Resampling", Image)  # type: ignore[name-defined]
                image = image.resize((target, target), resampling.LANCZOS)
                return ImageTk.PhotoImage(image)  # type: ignore[name-defined]
            photo = tk.PhotoImage(file=str(path))
            w = max(1, photo.width())
            h = max(1, photo.height())
            factor = max(w / target, h / target, 1)
            if factor > 1:
                step = int(factor) + 1
                photo = photo.subsample(step, step)
            return photo
        except Exception:
            return None

    def _collect_image_paths(self, max_files: int) -> list[Path]:
        exts = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ppm", ".pgm"}
        search_roots = [
            (Path.home() / "Pictures", 7),
            (Path.home() / "Desktop", 5),
            (Path.home() / "Downloads", 5),
            (Path.home(), 3),
        ]

        found: list[Path] = []
        seen: set[str] = set()
        skip_dirs = {"node_modules", "venv", ".git", "__pycache__"}

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
            if PIL_AVAILABLE:
                image = Image.open(path)  # type: ignore[name-defined]
                image.thumbnail((460, 300))
                return ImageTk.PhotoImage(image)  # type: ignore[name-defined]

            photo = tk.PhotoImage(file=str(path))
            w = max(1, photo.width())
            h = max(1, photo.height())
            factor = max(w / 460, h / 300, 1)
            if factor > 1:
                step = int(factor) + 1
                photo = photo.subsample(step, step)
            return photo
        except Exception:
            return None

    def run(self) -> None:
        self.root.mainloop()


if __name__ == "__main__":
    AnnoyingBlockPet().run()
