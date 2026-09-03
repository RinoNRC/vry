import asyncio
import json
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import quote

import flet as ft

from src.app_state import app_state
from src.constants import DEFAULT_CONFIG, version
from src.stats import Stats
from src.system_notifications import show_system_notification


BACKGROUND = "#080B10"
SURFACE = ft.Colors.with_opacity(0.82, "#11151D")
SURFACE_ALT = ft.Colors.with_opacity(0.76, "#171C26")
BORDER = "#252C38"
TEXT = "#F4F1EA"
MUTED = "#8C95A5"
ACCENT = "#FF4655"
ALLY = "#49A8FF"
ENEMY = "#FF5E6B"


def _asset_path(relative_path):
    root = Path(sys.executable).parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parents[1]
    return str(root / "assets" / relative_path)


def _map_name(value):
    if isinstance(value, (tuple, list)):
        value = value[0] if value else "-"
    return str(value or "-").rstrip("/").split("/")[-1].replace("_", " ")


def _server_name(value):
    server_id = str(value or "").lower()
    locations = {
        "frankfurt": "Франкфурт",
        "stockholm": "Стокгольм",
        "paris": "Париж",
        "london": "Лондон",
        "warsaw": "Варшава",
        "madrid": "Мадрид",
        "istanbul": "Стамбул",
        "bahrain": "Бахрейн",
        "tokyo": "Токио",
        "singapore": "Сингапур",
        "sydney": "Сидней",
        "mumbai": "Мумбаи",
        "hongkong": "Гонконг",
        "hong-kong": "Гонконг",
        "seoul": "Сеул",
        "oregon": "Орегон",
        "virginia": "Северная Вирджиния",
        "texas": "Техас",
        "illinois": "Иллинойс",
        "georgia": "Джорджия",
        "california": "Северная Калифорния",
        "miami": "Майами",
        "mexico": "Мехико",
        "santiago": "Сантьяго",
        "saopaulo": "Сан-Паулу",
        "sao-paulo": "Сан-Паулу",
    }
    for token, location in locations.items():
        if token in server_id:
            return location
    if not server_id:
        return "Сервер неизвестен"
    fallback = server_id.split(".")[-1]
    fallback = fallback.removeprefix("eu-gp-").removeprefix("na-gp-").removeprefix("ap-gp-")
    return fallback.replace("-", " ").title()


def _rank_meta(tier):
    try:
        tier = int(tier)
    except (TypeError, ValueError):
        tier = 0
    ranks = [
        (0, "Unranked", "#69717F", ft.Icons.HELP_OUTLINE_ROUNDED),
        (3, "Iron", "#77736B", ft.Icons.HEXAGON_OUTLINED),
        (6, "Bronze", "#B78358", ft.Icons.SHIELD_OUTLINED),
        (9, "Silver", "#BFC6CA", ft.Icons.SHIELD_OUTLINED),
        (12, "Gold", "#E6C24F", ft.Icons.MILITARY_TECH_ROUNDED),
        (15, "Platinum", "#46C6D4", ft.Icons.DIAMOND_OUTLINED),
        (18, "Diamond", "#D77AD8", ft.Icons.DIAMOND_ROUNDED),
        (21, "Ascendant", "#4BC487", ft.Icons.CHANGE_HISTORY_ROUNDED),
        (24, "Immortal", "#F05D6F", ft.Icons.WHATSHOT_ROUNDED),
        (27, "Radiant", "#FFF0A6", ft.Icons.AUTO_AWESOME_ROUNDED),
    ]
    start, name, color, icon = ranks[0]
    for candidate in ranks:
        if tier >= candidate[0]:
            start, name, color, icon = candidate
    division = tier - start + 1 if 3 <= tier <= 26 else None
    label = f"{name} {division}" if division else name
    return label, color, icon


def _rank_badge(tier, suffix=None):
    label, color, icon = _rank_meta(tier)
    label_controls = [ft.Text(label, size=11, color=color, weight=ft.FontWeight.BOLD, no_wrap=True)]
    if suffix:
        label_controls.append(ft.Text(str(suffix).strip(" ()"), size=10, color=MUTED, weight=ft.FontWeight.W_600, no_wrap=True))
    return ft.Row(
        spacing=4,
        tight=True,
        controls=[
            ft.Container(
                width=24,
                height=24,
                border_radius=7,
                bgcolor=ft.Colors.with_opacity(0.12, color),
                border=ft.border.all(1, ft.Colors.with_opacity(0.42, color)),
                alignment=ft.alignment.center,
                content=ft.Icon(icon, size=15, color=color),
            ),
            ft.Column(spacing=0, tight=True, controls=label_controls),
        ],
    )


def _official_rank_badge(tier, icon_url, suffix=None):
    label, color, fallback_icon = _rank_meta(tier)
    details = [
        ft.Text(label, size=13, color=color, weight=ft.FontWeight.BOLD, no_wrap=True)
    ]
    if suffix:
        details.append(
            ft.Text(
                str(suffix).strip(" ()"),
                size=10,
                color=MUTED,
                weight=ft.FontWeight.W_600,
                no_wrap=True,
            )
        )
    return ft.Row(
        spacing=8,
        tight=True,
        controls=[
            ft.Image(
                src=icon_url,
                width=54,
                height=54,
                fit=ft.ImageFit.CONTAIN,
                error_content=ft.Icon(fallback_icon, size=30, color=color),
            ),
            ft.Column(spacing=1, tight=True, controls=details),
        ],
    )


def _secondary_rank_text(tier, suffix=None):
    label, color, _ = _rank_meta(tier)
    controls = [
        ft.Text(
            label,
            size=11,
            color=ft.Colors.with_opacity(0.76, color),
            weight=ft.FontWeight.W_600,
            no_wrap=True,
        )
    ]
    if suffix:
        controls.append(
            ft.Text(
                str(suffix).strip(" ()"),
                size=9,
                color="#697282",
                weight=ft.FontWeight.W_600,
                no_wrap=True,
            )
        )
    return ft.Row(spacing=5, tight=True, controls=controls)


class ValorantApp:
    def __init__(self, page):
        self.page = page
        self.selected_view = 0
        self.expanded_players = set()
        self.sort_key = "rank"
        self.sort_descending = True
        self._wide_team_layout = None
        self._animated_match_key = None
        self._pending_team_panels = []
        self.settings = self._load_settings()
        self.feature_settings = self._load_feature_settings()
        self.stats_store = Stats()
        self.history = []
        self.encounters = {}
        self.last_game_state = None
        self.notification_keys = set()
        self.player_panel_open = False
        self._last_view_index = None
        self._navigation_needs_update = True
        self._mounted = False
        self.scroll_positions = {}
        self.scroll_controls = {}
        self.shimmer_controls = []
        self.last_revision = -1
        self.snapshot = app_state.snapshot()
        self.content = ft.Container(expand=True, padding=ft.padding.only(26, 18, 40, 22))
        self.view_switcher = ft.AnimatedSwitcher(
            content=ft.Container(),
            expand=True,
            duration=240,
            reverse_duration=180,
            switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
            transition=ft.AnimatedSwitcherTransition.FADE,
        )
        self.hero_switcher = ft.AnimatedSwitcher(
            content=ft.Container(),
            duration=520,
            reverse_duration=360,
            switch_in_curve=ft.AnimationCurve.EASE_OUT_CUBIC,
            switch_out_curve=ft.AnimationCurve.EASE_IN,
            transition=ft.AnimatedSwitcherTransition.FADE,
        )
        self.ambient_blob_a = ft.Container(
            left=-180,
            top=-220,
            width=620,
            height=620,
            border_radius=310,
            opacity=0.32,
            gradient=ft.RadialGradient(colors=["#61232D", ft.Colors.with_opacity(0, "#61232D")]),
            animate_position=ft.Animation(8000, ft.AnimationCurve.EASE_IN_OUT),
            animate_opacity=ft.Animation(8000, ft.AnimationCurve.EASE_IN_OUT),
        )
        self.ambient_blob_b = ft.Container(
            right=-160,
            bottom=-260,
            width=720,
            height=720,
            border_radius=360,
            opacity=0.24,
            gradient=ft.RadialGradient(colors=["#173E59", ft.Colors.with_opacity(0, "#173E59")]),
            animate_position=ft.Animation(9000, ft.AnimationCurve.EASE_IN_OUT),
            animate_opacity=ft.Animation(9000, ft.AnimationCurve.EASE_IN_OUT),
        )
        self.status_text = ft.Text("STARTING", size=11, color=ACCENT, weight=ft.FontWeight.BOLD)
        self.status_dot = ft.Container(width=8, height=8, border_radius=4, bgcolor=ACCENT)
        self.status_panel = ft.Container(
            padding=10,
            border_radius=10,
            bgcolor=ft.Colors.with_opacity(0.10, ACCENT),
            border=ft.border.all(1, ft.Colors.with_opacity(0.32, ACCENT)),
            animate=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
            content=ft.Row(controls=[self.status_dot, self.status_text], spacing=9),
        )
        self.credit_signature = self._build_credit_signature()
        self.brand_mark = self._build_brand_mark()
        self.navigation = None
        self.nav_items = []
        self.player_scrim = ft.Container(
            left=192,
            top=0,
            right=0,
            bottom=0,
            visible=False,
            bgcolor=ft.Colors.with_opacity(0.58, "#000000"),
            on_click=self._close_player_panel,
        )
        self.player_panel = ft.Container(
            width=450,
            right=-470,
            top=0,
            bottom=0,
            padding=18,
            bgcolor="#0C1016",
            border=ft.border.only(left=ft.BorderSide(1, BORDER)),
            shadow=ft.BoxShadow(blur_radius=30, color=ft.Colors.with_opacity(0.55, "#000000"), offset=ft.Offset(-8, 0)),
            animate_position=ft.Animation(260, ft.AnimationCurve.EASE_OUT_CUBIC),
        )

    def build(self):
        self.page.title = f"vRY // VALORANT companion v{version}"
        self.page.bgcolor = BACKGROUND
        self.page.padding = 0
        self.page.theme_mode = ft.ThemeMode.DARK
        self.page.theme = ft.Theme(
            font_family="Bahnschrift",
            scrollbar_theme=ft.ScrollbarTheme(
                thumb_visibility=False,
                track_visibility=False,
                thickness=0,
            ),
        )
        self.page.window.width = 1520
        self.page.window.height = 800
        self.page.window.min_width = 1200
        self.page.window.min_height = 700
        self.page.window.frameless = True
        self.page.window.title_bar_hidden = True
        self.page.window.title_bar_buttons_hidden = True
        self.page.on_resized = self._handle_resize

        self.navigation = ft.Container(
            width=192,
            padding=ft.padding.symmetric(horizontal=12, vertical=16),
            gradient=ft.LinearGradient(
                begin=ft.alignment.top_center,
                end=ft.alignment.bottom_center,
                colors=["#151016", "#0B1017", "#090D13", "#0D1119"],
                stops=[0, 0.32, 0.72, 1],
            ),
            border=ft.border.only(right=ft.BorderSide(1, BORDER)),
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=self._navigation_content(),
        )

        self.page.add(
            ft.Column(
                expand=True,
                spacing=0,
                controls=[
                    self._title_bar(),
                    ft.Stack(
                        expand=True,
                        controls=[
                            ft.Container(
                                left=0,
                                top=0,
                                right=0,
                                bottom=0,
                                gradient=ft.LinearGradient(
                                    begin=ft.alignment.top_left,
                                    end=ft.alignment.bottom_right,
                                    colors=["#070A0F", "#0B1018", "#100B10"],
                                ),
                            ),
                            self.ambient_blob_a,
                            self.ambient_blob_b,
                            ft.Container(
                                right=38,
                                bottom=-55,
                                content=ft.Text("vRY", size=210, color=ft.Colors.with_opacity(0.035, "#FFFFFF"), weight=ft.FontWeight.BOLD),
                            ),
                            ft.Row(expand=True, spacing=0, controls=[self.navigation, self.content]),
                        ],
                    ),
                ],
            )
        )
        self.player_scrim.top = 38
        self.player_panel.top = 38
        if hasattr(self.page, "overlay"):
            self.page.overlay.extend([self.player_scrim, self.player_panel])
            self.credit_signature.left = 12
            self.credit_signature.bottom = 30
            self.page.overlay.append(self.credit_signature)
        self._refresh_history()
        self.render()
        self.page.run_task(self.refresh_loop)
        self.page.run_task(self._ambient_loop)
        self.page.run_task(self._shimmer_loop)
        self.page.run_task(self._start_credit_animation)
        self.page.run_task(self._start_brand_animation)

    def _scrollable_column(self, view_id, controls, spacing=10, enabled=True, list_view=False):
        control_type = ft.ListView if list_view else ft.Column
        kwargs = {
            "key": f"scroll-{view_id}",
            "expand": True,
            "spacing": spacing,
            "controls": controls,
            "on_scroll": lambda event, key=view_id: self._remember_scroll(key, event),
            "on_scroll_interval": 40,
        }
        if list_view:
            kwargs["auto_scroll"] = False
        else:
            kwargs["scroll"] = ft.ScrollMode.HIDDEN if enabled else None
        column = control_type(**kwargs)
        self.scroll_controls[view_id] = column
        return column

    def _remember_scroll(self, view_id, event):
        pixels = getattr(event, "pixels", None)
        if pixels is not None:
            self.scroll_positions[view_id] = max(0, float(pixels))

    async def _restore_scroll(self, view_id):
        for delay in (0.04, 0.16, 0.35):
            await asyncio.sleep(delay)
            control = self.scroll_controls.get(view_id)
            offset = self.scroll_positions.get(view_id, 0)
            if control is not None and offset > 0:
                try:
                    control.scroll_to(offset=offset, duration=0)
                except AssertionError:
                    pass

    def _viewport_width(self):
        return getattr(self.page, "width", None) or self.page.window.width or 0

    def _handle_resize(self, _):
        wide_layout = self._viewport_width() >= 1200
        if wide_layout != self._wide_team_layout:
            self._wide_team_layout = wide_layout
            self.render()

    def _title_bar(self):
        drag_area = ft.WindowDragArea(
            expand=True,
            content=ft.Container(
                padding=ft.padding.only(left=14),
                alignment=ft.alignment.center_left,
                content=ft.Row(
                    spacing=9,
                    controls=[
                        ft.Container(width=7, height=7, border_radius=4, bgcolor=ACCENT),
                        ft.Text("vRY  /  VALORANT COMPANION", size=10, color=MUTED, weight=ft.FontWeight.W_600),
                    ],
                ),
            ),
        )
        return ft.Container(
            height=38,
            bgcolor="#090D13",
            border=ft.border.only(bottom=ft.BorderSide(1, BORDER)),
            content=ft.Row(
                spacing=0,
                controls=[
                    drag_area,
                    self._window_button(ft.Icons.REMOVE_ROUNDED, self._minimize_window, "Свернуть"),
                    self._window_button(ft.Icons.CROP_SQUARE_ROUNDED, self._toggle_maximize, "Развернуть"),
                    self._window_button(ft.Icons.CLOSE_ROUNDED, self._close_window, "Закрыть", close=True),
                ],
            ),
        )

    def _window_button(self, icon, handler, tooltip, close=False):
        return ft.IconButton(
            icon=icon,
            icon_size=15,
            icon_color=MUTED,
            width=44,
            height=38,
            padding=0,
            tooltip=tooltip,
            hover_color="#7E202A" if close else SURFACE_ALT,
            on_click=handler,
        )

    def _minimize_window(self, _):
        self.page.window.minimized = True
        self.page.update()

    def _toggle_maximize(self, _):
        self.page.window.maximized = not self.page.window.maximized
        self.page.update()

    def _close_window(self, _):
        self.page.window.close()

    def _navigation_content(self):
        self.nav_items = [
            self._nav_item(0, ft.Icons.GRID_VIEW_ROUNDED, "Матч"),
            self._nav_item(1, ft.Icons.HISTORY_ROUNDED, "История"),
            self._nav_item(2, ft.Icons.MONITOR_HEART_ROUNDED, "Диагностика"),
            self._nav_item(3, ft.Icons.ACCOUNT_CIRCLE_ROUNDED, "Аккаунт"),
            self._nav_item(4, ft.Icons.TUNE_ROUNDED, "Настройки"),
        ]
        navigation_column = ft.Column(
            expand=True,
            controls=[
                ft.Container(
                    padding=ft.padding.only(left=10, bottom=20),
                    content=ft.Column(
                        spacing=0,
                        controls=[
                            self.brand_mark,
                            ft.Text("TACTICAL INTEL", size=10, color=MUTED, weight=ft.FontWeight.W_600),
                        ],
                    ),
                ),
                *self.nav_items[:4],
                ft.Container(expand=True),
                self.nav_items[4],
                self.status_panel,
                ft.Container(width=168, height=48),
                ft.Text(f"LOCAL MODE  /  v{version}", size=9, color="#555E6D"),
            ],
        )
        return ft.Stack(
            expand=True,
            controls=[
                navigation_column,
            ],
        )

    def _update_navigation_selection(self):
        for index, item in enumerate(self.nav_items):
            selected = self.selected_view == index
            item.bgcolor = "#26171C" if selected else None
            item.border = ft.border.all(1, "#4B2028" if selected else "#0C1016")
            stripe, icon, label = item.content.controls
            stripe.bgcolor = ACCENT if selected else ft.Colors.TRANSPARENT
            stripe.shadow = ft.BoxShadow(blur_radius=9, color=ft.Colors.with_opacity(0.62, ACCENT)) if selected else None
            icon.color = ACCENT if selected else MUTED
            label.color = TEXT if selected else MUTED
            try:
                item.update()
            except AssertionError:
                self._navigation_needs_update = True

    def _nav_item(self, index, icon, label):
        selected = self.selected_view == index
        return ft.Container(
            height=44,
            padding=ft.padding.symmetric(horizontal=12),
            margin=ft.margin.only(bottom=6),
            border_radius=10,
            bgcolor="#26171C" if selected else None,
            border=ft.border.all(1, "#4B2028" if selected else "#0C1016"),
            on_click=lambda _, value=index: self.change_view(value),
            content=ft.Row(
                spacing=9,
                controls=[
                    ft.Container(
                        width=3,
                        height=26,
                        border_radius=2,
                        bgcolor=ACCENT if selected else ft.Colors.TRANSPARENT,
                        shadow=ft.BoxShadow(blur_radius=9, color=ft.Colors.with_opacity(0.62, ACCENT)) if selected else None,
                    ),
                    ft.Icon(icon, size=19, color=ACCENT if selected else MUTED),
                    ft.Text(label, size=16, color=TEXT if selected else MUTED, weight=ft.FontWeight.W_600),
                ],
            ),
        )

    def change_view(self, index):
        self._close_player_panel(update=False)
        self.selected_view = index
        if index == 1:
            self._refresh_history()
        self._update_navigation_selection()
        self.render()

    async def refresh_loop(self):
        while True:
            snapshot = app_state.snapshot()
            if snapshot["revision"] != self.last_revision:
                self.snapshot = snapshot
                self.last_revision = snapshot["revision"]
                self._handle_notifications(snapshot)
                if self.selected_view in {1, 2, 3, 4}:
                    await asyncio.sleep(0.75)
                    continue
                if self.player_panel_open:
                    self.status_text.value = str(snapshot.get("status", "Starting")).upper()
                    self.status_text.update()
                    self.status_dot.update()
                    self.status_panel.update()
                else:
                    self.render()
            await asyncio.sleep(0.75)

    async def _ambient_loop(self):
        alternate = False
        while True:
            await asyncio.sleep(8)
            if self.selected_view in {1, 2, 3, 4}:
                continue
            alternate = not alternate
            self.ambient_blob_a.left = 80 if alternate else -180
            self.ambient_blob_a.top = -80 if alternate else -220
            self.ambient_blob_a.opacity = 0.22 if alternate else 0.32
            self.ambient_blob_b.right = 80 if alternate else -160
            self.ambient_blob_b.bottom = -120 if alternate else -260
            self.ambient_blob_b.opacity = 0.32 if alternate else 0.24
            try:
                self.ambient_blob_a.update()
                self.ambient_blob_b.update()
            except Exception:
                return

    async def _shimmer_loop(self):
        bright = False
        while True:
            await asyncio.sleep(0.7)
            bright = not bright
            for index, control in enumerate(self.shimmer_controls):
                control.opacity = (0.92 if bright else 0.42) - min(index * 0.05, 0.25)
                try:
                    control.update()
                except Exception:
                    pass

    def _build_credit_signature(self):
        self.credit_name = ft.ShaderMask(
            shader=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=[ACCENT, "#FF9B72", "#FFE3A3"],
            ),
            blend_mode=ft.BlendMode.SRC_IN,
            left=0,
            top=0,
            opacity=1,
            animate_opacity=ft.Animation(1500, ft.AnimationCurve.EASE_IN_OUT),
            content=ft.Text("RinoNRC", size=13, color="#FFFFFF", weight=ft.FontWeight.BOLD),
        )
        self.credit_name_reverse = ft.ShaderMask(
            shader=ft.LinearGradient(
                begin=ft.alignment.center_left,
                end=ft.alignment.center_right,
                colors=["#FFE3A3", "#FF9B72", ACCENT],
            ),
            blend_mode=ft.BlendMode.SRC_IN,
            left=0,
            top=0,
            opacity=0,
            animate_opacity=ft.Animation(1500, ft.AnimationCurve.EASE_IN_OUT),
            content=ft.Text("RinoNRC", size=13, color="#FFFFFF", weight=ft.FontWeight.BOLD),
        )
        self.credit_name.on_animation_end = self._credit_name_animation_end
        name_stack = ft.Stack(
            width=96,
            height=18,
            controls=[self.credit_name, self.credit_name_reverse],
        )
        self.credit_track = ft.Container(
            left=0,
            right=0,
            bottom=0,
            height=2,
            border_radius=1,
            bgcolor=ft.Colors.with_opacity(0.13, "#FFFFFF"),
        )
        self.credit_shine = ft.Container(
            left=4,
            bottom=0,
            width=34,
            height=2,
            border_radius=1,
            opacity=1,
            gradient=ft.LinearGradient(colors=[ft.Colors.with_opacity(0, ACCENT), "#FFD09A", ft.Colors.with_opacity(0, ACCENT)]),
            shadow=ft.BoxShadow(blur_radius=6, color=ft.Colors.with_opacity(0.55, ACCENT)),
            animate_position=ft.Animation(1500, ft.AnimationCurve.EASE_IN_OUT),
            animate_opacity=ft.Animation(700, ft.AnimationCurve.EASE_IN_OUT),
            on_animation_end=self._credit_shine_animation_end,
        )
        return ft.Container(
            width=168,
            height=48,
            padding=ft.padding.symmetric(horizontal=9, vertical=6),
            border_radius=9,
            bgcolor=ft.Colors.with_opacity(0.34, "#171D27"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.25, ACCENT)),
            ink=True,
            tooltip="Telegram: @rinonrc",
            on_click=lambda _: self.page.launch_url("https://t.me/rinonrc"),
            content=ft.Stack(
                controls=[
                    ft.Column(
                        spacing=0,
                        controls=[
                            ft.Text("CREATED BY", size=7, color="#737C8B", weight=ft.FontWeight.BOLD),
                            name_stack,
                        ],
                    ),
                    self.credit_track,
                    self.credit_shine,
                ],
            ),
        )

    async def _start_credit_animation(self):
        await asyncio.sleep(0.35)
        self.credit_shine.left = 116
        self.credit_name.opacity = 0
        self.credit_name_reverse.opacity = 1
        try:
            self.credit_shine.update()
            self.credit_name.update()
            self.credit_name_reverse.update()
        except AssertionError:
            pass

    def _credit_shine_animation_end(self, _):
        self.credit_shine.left = 4 if self.credit_shine.left > 50 else 116
        self.credit_shine.opacity = 0.55 if self.credit_shine.left > 50 else 1
        try:
            self.credit_shine.update()
        except AssertionError:
            pass

    def _credit_name_animation_end(self, _):
        showing_primary = self.credit_name.opacity > 0.5
        self.credit_name.opacity = 0 if showing_primary else 1
        self.credit_name_reverse.opacity = 1 if showing_primary else 0
        try:
            self.credit_name.update()
            self.credit_name_reverse.update()
        except AssertionError:
            pass

    def _build_brand_mark(self):
        self.brand_phase = "reveal"
        self.brand_index = 0
        self.brand_letters = [
            ft.Text(
                letter,
                size=28,
                color=color,
                weight=ft.FontWeight.BOLD,
                opacity=0,
                animate_opacity=ft.Animation(220, ft.AnimationCurve.EASE_OUT),
                on_animation_end=self._brand_letter_animation_end,
            )
            for letter, color in (("v", ACCENT), ("R", "#FF9B72"), ("Y", "#FFE3A3"))
        ]
        return ft.Row(spacing=0, tight=True, controls=self.brand_letters)

    async def _start_brand_animation(self):
        await asyncio.sleep(0.55)
        self.brand_letters[0].opacity = 1
        try:
            self.brand_letters[0].update()
        except AssertionError:
            pass

    def _brand_letter_animation_end(self, _):
        if self.brand_phase == "reveal":
            self.brand_index += 1
            if self.brand_index < len(self.brand_letters):
                self.brand_letters[self.brand_index].opacity = 1
                try:
                    self.brand_letters[self.brand_index].update()
                except AssertionError:
                    pass
            else:
                self.brand_phase = "pause"
                self.page.run_task(self._brand_begin_hide)
        elif self.brand_phase == "hide":
            self.brand_index -= 1
            if self.brand_index >= 0:
                self.brand_letters[self.brand_index].opacity = 0
                try:
                    self.brand_letters[self.brand_index].update()
                except AssertionError:
                    pass
            else:
                self.brand_phase = "pause"
                self.page.run_task(self._brand_begin_reveal)

    async def _brand_begin_hide(self):
        await asyncio.sleep(1.3)
        self.brand_phase = "hide"
        self.brand_index = len(self.brand_letters) - 1
        self.brand_letters[self.brand_index].opacity = 0
        try:
            self.brand_letters[self.brand_index].update()
        except AssertionError:
            pass

    async def _brand_begin_reveal(self):
        await asyncio.sleep(0.45)
        self.brand_phase = "reveal"
        self.brand_index = 0
        self.brand_letters[self.brand_index].opacity = 1
        try:
            self.brand_letters[self.brand_index].update()
        except AssertionError:
            pass

    def render(self):
        status = self.snapshot.get("status", "Starting")
        has_error = bool(self.snapshot.get("error"))
        status_color = self._status_color(status, has_error)
        self.status_text.value = str(status).upper()
        self.status_text.color = status_color
        self.status_dot.bgcolor = status_color
        self.status_panel.bgcolor = ft.Colors.with_opacity(0.10, status_color)
        self.status_panel.border = ft.border.all(1, ft.Colors.with_opacity(0.32, status_color))
        if self.selected_view == 0:
            view = self._match_view()
        elif self.selected_view == 1:
            view = self._history_view()
        elif self.selected_view == 2:
            view = self._diagnostics_view()
        elif self.selected_view == 3:
            view = self._account_view()
        else:
            view = self._settings_view()
        initial_render = self._last_view_index is None
        reveal_view = not initial_render and self.selected_view != self._last_view_index
        if initial_render:
            self._last_view_index = self.selected_view
        view_wrapper = ft.Container(
            key=f"view-{self.selected_view}-{status}",
            content=view,
            padding=ft.padding.only(right=12),
            expand=True,
            opacity=0 if reveal_view else 1,
            offset=ft.Offset(0, 0.035) if reveal_view else ft.Offset(0, 0),
            animate_opacity=ft.Animation(260, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(300, ft.AnimationCurve.EASE_OUT_CUBIC),
        )
        self.view_switcher.content = view_wrapper
        self.content.content = self.view_switcher
        full_update = not self._mounted or self._navigation_needs_update
        if full_update:
            self.page.update()
            self._mounted = True
            self._navigation_needs_update = False
        else:
            try:
                self.view_switcher.update()
                self.status_text.update()
                self.status_dot.update()
                self.status_panel.update()
            except AssertionError:
                # Test pages and a just-mounted Flet session may not expose child controls yet.
                self.page.update()
        scroll_id = {0: "match", 1: "history", 2: "diagnostics", 3: "account", 4: "settings"}.get(self.selected_view)
        if scroll_id:
            self.page.run_task(self._restore_scroll, scroll_id)
        if reveal_view:
            self._last_view_index = self.selected_view
            self.page.run_task(self._reveal_view, view_wrapper)
        if self._pending_team_panels:
            pending_panels = self._pending_team_panels
            self._pending_team_panels = []
            self.page.run_task(self._reveal_team_panels, pending_panels)

    def _status_color(self, status, has_error=False):
        if has_error or status == "Error":
            return ENEMY
        return {
            "INGAME": "#4BC487",
            "PREGAME": "#E6C24F",
            "MENUS": ALLY,
            "Connecting": ACCENT,
            "Launching VALORANT": "#E6C24F",
            "Waiting for VALORANT": MUTED,
        }.get(status, ACCENT)

    async def _reveal_view(self, view):
        await asyncio.sleep(0.03)
        view.opacity = 1
        view.offset = ft.Offset(0, 0)
        try:
            view.update()
        except Exception:
            pass

    async def _reveal_team_panels(self, panels):
        await asyncio.sleep(0.04)
        for panel in panels:
            panel.opacity = 1
            panel.offset = ft.Offset(0, 0)
            panel.update()
            await asyncio.sleep(0.09)

    def _load_settings(self):
        settings = dict(DEFAULT_CONFIG.get("table", {}))
        try:
            with open("config.json", "r", encoding="utf-8") as config_file:
                settings.update(json.load(config_file).get("table", {}))
        except (OSError, json.JSONDecodeError):
            pass
        return settings

    def _load_feature_settings(self):
        settings = dict(DEFAULT_CONFIG.get("flags", {}))
        try:
            with open("config.json", "r", encoding="utf-8") as config_file:
                settings.update(json.load(config_file).get("flags", {}))
        except (OSError, json.JSONDecodeError):
            pass
        return settings

    def _save_feature_setting(self, key, value):
        self.feature_settings[key] = value
        config = {}
        try:
            with open("config.json", "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
        except (OSError, json.JSONDecodeError):
            config = {"flags": {}}
        config.setdefault("flags", {}).update(self.feature_settings)
        try:
            with open("config.json", "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4)
        except OSError:
            pass

    def _refresh_history(self):
        self.history = self.stats_store.get_history(30)
        self.encounters = self.stats_store.get_encounters()

    def _feature_setting_tile(self, key, label, description):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=10,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            content=ft.Row(
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(label, size=15, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text(description, size=12, color=MUTED),
                        ],
                    ),
                    ft.Switch(
                        value=bool(self.feature_settings.get(key, True)),
                        active_color=ACCENT,
                        on_change=lambda event, setting_key=key: self._save_feature_setting(setting_key, event.control.value),
                    ),
                ],
            ),
        )

    def _save_setting(self, key, value):
        self.settings[key] = value
        config = {}
        try:
            with open("config.json", "r", encoding="utf-8") as config_file:
                config = json.load(config_file)
        except (OSError, json.JSONDecodeError):
            config = {"table": {}}
        config.setdefault("table", {}).update(self.settings)
        try:
            with open("config.json", "w", encoding="utf-8") as config_file:
                json.dump(config, config_file, indent=4)
        except OSError:
            pass

    def _setting_tile(self, key, label, description):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            border_radius=10,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            content=ft.Row(
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text(label, size=15, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text(description, size=12, color=MUTED),
                        ],
                    ),
                    ft.Switch(
                        value=bool(self.settings.get(key, True)),
                        active_color=ACCENT,
                        on_change=lambda event, setting_key=key: self._save_setting(setting_key, event.control.value),
                    ),
                ],
            ),
        )

    def _toggle_setting_card(self, section, key, label, description, icon):
        values = self.settings if section == "table" else self.feature_settings
        save = self._save_setting if section == "table" else self._save_feature_setting
        active = bool(values.get(key, True))
        icon_control = ft.Icon(icon, size=22, color=ACCENT if active else MUTED)
        icon_box = ft.Container(
            width=42,
            height=42,
            border_radius=11,
            bgcolor=ft.Colors.with_opacity(0.14, ACCENT) if active else "#171C25",
            alignment=ft.alignment.center,
            content=icon_control,
        )
        state_text = ft.Text("ВКЛ", size=8, color=ACCENT if active else MUTED, weight=ft.FontWeight.BOLD)
        thumb = ft.Container(
            left=23 if active else 3,
            top=3,
            width=18,
            height=18,
            border_radius=9,
            bgcolor="#FFFFFF" if active else "#69717E",
            shadow=ft.BoxShadow(blur_radius=5, color=ft.Colors.with_opacity(0.35, "#000000")),
            animate_position=ft.Animation(170, ft.AnimationCurve.EASE_OUT_CUBIC),
        )
        toggle = ft.Container(
            width=44,
            height=24,
            border_radius=12,
            bgcolor=ACCENT if active else "#242B36",
            animate=ft.Animation(170, ft.AnimationCurve.EASE_OUT),
            content=ft.Stack(controls=[thumb]),
        )
        card = ft.Container(
            col={"xs": 12, "lg": 6},
            height=88,
            padding=12,
            border_radius=13,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            animate=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
            ink=True,
        )

        def update_visual(enabled):
            icon_control.color = ACCENT if enabled else MUTED
            icon_box.bgcolor = ft.Colors.with_opacity(0.14, ACCENT) if enabled else "#171C25"
            state_text.value = "ВКЛ" if enabled else "ВЫКЛ"
            state_text.color = ACCENT if enabled else MUTED
            toggle.bgcolor = ACCENT if enabled else "#242B36"
            thumb.left = 23 if enabled else 3
            thumb.bgcolor = "#FFFFFF" if enabled else "#69717E"

        def toggle_setting(_):
            nonlocal active
            active = not active
            values[key] = active
            save(key, active)
            update_visual(active)
            try:
                icon_box.update()
                toggle.update()
                state_text.update()
            except AssertionError:
                pass

        def hover_card(event):
            hovering = str(event.data).lower() == "true"
            card.bgcolor = "#211920" if hovering and active else "#181E27" if hovering else "#16141A" if active else SURFACE
            card.update()

        card.on_click = toggle_setting
        card.content = ft.Row(
            controls=[
                icon_box,
                ft.Column(
                    expand=True,
                    spacing=3,
                    alignment=ft.MainAxisAlignment.CENTER,
                    controls=[
                        ft.Text(label, size=14, color=TEXT, weight=ft.FontWeight.BOLD),
                        ft.Text(description, size=10, color=MUTED, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                ),
                ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=3, controls=[toggle, state_text]),
            ],
        )
        return card

    def _save_rank_icon_style(self, event):
        selected = next(iter(event.control.selected), "official")
        self._save_setting("rank_icon_style", selected)

    def _rank_icon_style_tile(self):
        selected_style = self.settings.get("rank_icon_style", "official")
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=12),
            border_radius=10,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            content=ft.Row(
                controls=[
                    ft.Column(
                        expand=True,
                        spacing=2,
                        controls=[
                            ft.Text("Эмблемы рангов", size=14, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text("Стиль рангов в подробной карточке игрока", size=11, color=MUTED),
                        ],
                    ),
                    ft.SegmentedButton(
                        selected={selected_style},
                        show_selected_icon=False,
                        segments=[
                            ft.Segment(value="minimal", label=ft.Text("Минималистичные", size=11)),
                            ft.Segment(value="official", label=ft.Text("Официальные", size=11)),
                        ],
                        on_change=self._save_rank_icon_style,
                    ),
                ],
            ),
        )

    def _settings_view(self):
        display_cards = [
            self._toggle_setting_card("table", "skin", "Скин", "Выбранный weapon skin игрока", ft.Icons.AUTO_AWESOME_ROUNDED),
            self._toggle_setting_card("table", "rr", "Очки RR", "Текущий ranked rating", ft.Icons.SPEED_ROUNDED),
            self._toggle_setting_card("table", "peakrank", "Пиковый ранг", "Лучший ранг игрока в сезоне", ft.Icons.WORKSPACE_PREMIUM_ROUNDED),
            self._toggle_setting_card("table", "previousrank", "Прошлый ранг", "Ранг в предыдущем акте", ft.Icons.HISTORY_ROUNDED),
            self._toggle_setting_card("table", "leaderboard", "Позиция в рейтинге", "Место игрока в leaderboard", ft.Icons.LEADERBOARD_ROUNDED),
            self._toggle_setting_card("table", "headshot_percent", "Процент попаданий в голову", "Headshot percentage", ft.Icons.CENTER_FOCUS_STRONG_ROUNDED),
            self._toggle_setting_card("table", "winrate", "Процент побед", "Win rate и количество игр", ft.Icons.PERCENT_ROUNDED),
            self._toggle_setting_card("table", "kd", "K/D", "Соотношение убийств и смертей", ft.Icons.QUERY_STATS_ROUNDED),
            self._toggle_setting_card("table", "level", "Уровень аккаунта", "Уровень профиля VALORANT", ft.Icons.BADGE_ROUNDED),
            self._toggle_setting_card("table", "earned_rr", "Изменение RR", "Полученный или потерянный RR", ft.Icons.TRENDING_UP_ROUNDED),
        ]
        live_cards = [
            self._toggle_setting_card("flags", "auto_launch_valorant", "Автозапуск VALORANT", "Запускать игру автоматически, если lockfile не найден", ft.Icons.PLAY_CIRCLE_ROUNDED),
            self._toggle_setting_card("flags", "repeat_encounters", "Повторные встречи", "Метка прошлых матчей с игроком", ft.Icons.REPLAY_ROUNDED),
            self._toggle_setting_card("flags", "team_average_rank", "Средний ранг команды", "Средний tier и RR каждой команды", ft.Icons.GROUP_WORK_ROUNDED),
            self._toggle_setting_card("flags", "notifications", "Уведомления", "Главный переключатель уведомлений", ft.Icons.NOTIFICATIONS_ACTIVE_ROUNDED),
            self._toggle_setting_card("flags", "match_start_notification", "Начало матча", "Уведомление при переходе в INGAME", ft.Icons.SPORTS_ESPORTS_ROUNDED),
            self._toggle_setting_card("flags", "high_rank_notification", "Высокий ранг", "Immortal и Radiant в составе", ft.Icons.MILITARY_TECH_ROUNDED),
            self._toggle_setting_card("flags", "repeat_encounter_notification", "Знакомый игрок", "Уведомление о повторной встрече", ft.Icons.PERSON_SEARCH_ROUNDED),
        ]
        return ft.Column(
            expand=True,
            spacing=14,
            controls=[
                self._header("DISPLAY CONTROL", "Настройки", "Выберите, какие показатели показывать в тактической сводке."),
                self._scrollable_column("settings", [
                        self._settings_section_header("ВИЗУАЛЬНЫЙ СТИЛЬ", "Оформление рангов и подробной карточки"),
                        self._rank_icon_style_tile(),
                        self._settings_section_header("ПОКАЗАТЕЛИ ИГРОКА", "Управление информацией в тактической сводке"),
                        ft.ResponsiveRow(spacing=10, run_spacing=10, controls=display_cards),
                        self._settings_section_header("LIVE-ФУНКЦИИ", "События матча и интеллектуальные подсказки"),
                        ft.ResponsiveRow(spacing=10, run_spacing=10, controls=live_cards),
                        self._settings_section_header("CREDITS", "Авторы и информация о приложении"),
                        self._credits_card(),
                    ], spacing=12),
            ],
        )

    def _settings_section_header(self, title, description):
        return ft.Row(
            controls=[
                ft.Container(width=4, height=28, border_radius=2, bgcolor=ACCENT),
                ft.Column(spacing=1, controls=[ft.Text(title, size=10, color=ACCENT, weight=ft.FontWeight.BOLD), ft.Text(description, size=10, color=MUTED)]),
                ft.Container(expand=True, height=1, bgcolor=BORDER),
            ],
        )

    def _credits_card(self):
        return ft.Container(
            padding=16,
            border_radius=14,
            bgcolor=ft.Colors.with_opacity(0.78, "#11151D"),
            border=ft.border.all(1, ft.Colors.with_opacity(0.38, ACCENT)),
            content=ft.Row(
                controls=[
                    ft.Container(
                        width=54,
                        height=54,
                        border_radius=14,
                        gradient=ft.LinearGradient(begin=ft.alignment.top_left, end=ft.alignment.bottom_right, colors=[ACCENT, "#9F2936"]),
                        alignment=ft.alignment.center,
                        content=ft.Image(src=_asset_path("branding/vry-mark.svg"), width=54, height=54, fit=ft.ImageFit.COVER),
                    ),
                    ft.Column(
                        expand=True,
                        spacing=3,
                        controls=[
                            ft.Text("RinoNRC", size=17, color=TEXT, weight=ft.FontWeight.BOLD),
                            ft.Text("Создатель GUI-сборки", size=11, color=ACCENT, weight=ft.FontWeight.W_600),
                            ft.Text("Основано на проекте VALORANT rank yoinker", size=10, color=MUTED),
                        ],
                    ),
                    ft.OutlinedButton(
                        text="@rinonrc",
                        icon=ft.Icons.SEND_ROUNDED,
                        tooltip="Открыть Telegram",
                        style=self._secondary_button_style(),
                        on_click=lambda _: self.page.launch_url("https://t.me/rinonrc"),
                    ),
                    ft.Container(
                        padding=ft.padding.symmetric(horizontal=9, vertical=5),
                        border_radius=7,
                        bgcolor=ft.Colors.with_opacity(0.12, "#FFFFFF"),
                        content=ft.Text(f"v{version}", size=10, color=MUTED, weight=ft.FontWeight.BOLD),
                    ),
                ],
            ),
        )

    def _history_view(self):
        if not self.history:
            return ft.Column(
                expand=True,
                spacing=14,
                controls=[
                    self._history_header(False),
                    ft.Container(
                        expand=True,
                        alignment=ft.alignment.center,
                        content=ft.Column(
                            tight=True,
                            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                            controls=[
                                ft.Icon(ft.Icons.HISTORY_ROUNDED, size=40, color=ACCENT),
                                ft.Text("История пока пуста", size=18, color=TEXT, weight=ft.FontWeight.BOLD),
                                ft.Text("Сыграйте матч, чтобы здесь появились встреченные игроки.", size=12, color=MUTED),
                            ],
                        ),
                    ),
                ],
            )
        account_puuid = (self.snapshot.get("account") or {}).get("profile", {}).get("puuid") or (self.snapshot.get("heartbeat") or {}).get("puuid")
        repeated_players = sorted(
            (
                encounter for puuid, encounter in self.encounters.items()
                if puuid != account_puuid and encounter["count"] > 1
            ),
            key=lambda encounter: (encounter["count"], encounter["lastSeenAt"]),
            reverse=True,
        )
        controls = [
            ft.ResponsiveRow(
                spacing=10,
                controls=[
                    self._history_stat("Матчей", len(self.history), ft.Icons.SPORTS_ESPORTS_ROUNDED),
                    self._history_stat("Игроков", len(self.encounters), ft.Icons.GROUP_ROUNDED),
                    self._history_stat("Повторных встреч", len(repeated_players), ft.Icons.REPLAY_ROUNDED),
                ],
            ),
            self._activity_chart(),
        ]
        if repeated_players:
            controls.append(ft.Text("ЧАСТЫЕ ВСТРЕЧИ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD))
            controls.append(
                ft.Row(
                    scroll=ft.ScrollMode.HIDDEN,
                    controls=[
                        ft.Container(
                            width=190,
                            padding=10,
                            border_radius=10,
                            bgcolor=SURFACE,
                            border=ft.border.all(1, BORDER),
                            content=ft.Column(
                                spacing=3,
                                controls=[
                                    ft.Text(encounter["lastName"], size=13, color=TEXT, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    ft.Text(f"{encounter['count']} матчей  /  {encounter['lastAgent']}", size=10, color=MUTED),
                                ],
                            ),
                        )
                        for encounter in repeated_players[:10]
                    ],
                )
            )
        controls.append(ft.Text("ПОСЛЕДНИЕ СЕССИИ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD))
        controls.extend(self._history_match_card(match) for match in self.history)
        return ft.Column(
            expand=True,
            spacing=14,
            controls=[
                self._history_header(True),
                self._scrollable_column("history", controls, spacing=10, list_view=True),
            ],
        )

    def _history_header(self, show_clear):
        return ft.Row(
            vertical_alignment=ft.CrossAxisAlignment.START,
            controls=[
                self._header("LOCAL ARCHIVE", "История", "Уникальные игровые сессии из локального журнала встреч."),
                ft.Container(expand=True),
                ft.OutlinedButton(
                    text="Очистить историю",
                    icon=ft.Icons.DELETE_OUTLINE_ROUNDED,
                    visible=show_clear,
                    style=ft.ButtonStyle(color=ENEMY, side=ft.BorderSide(1, ft.Colors.with_opacity(0.55, ENEMY))),
                    on_click=self._confirm_clear_history,
                ),
            ],
        )

    def _confirm_clear_history(self, _):
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE,
            title=ft.Text("Очистить историю?", color=TEXT, weight=ft.FontWeight.BOLD),
            content=ft.Text("Все локальные матчи и данные повторных встреч будут удалены. Это действие нельзя отменить.", color=MUTED),
            actions=[
                ft.TextButton("Отмена", on_click=lambda _: self.page.close(dialog)),
                ft.TextButton("Очистить", style=ft.ButtonStyle(color=ENEMY), on_click=lambda _: self._clear_history(dialog)),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.open(dialog)

    def _clear_history(self, dialog):
        self.stats_store.clear_data()
        self.history = []
        self.encounters = {}
        self.page.close(dialog)
        self.render()

    def _history_stat(self, label, value, icon):
        return ft.Container(
            col={"xs": 12, "sm": 4},
            padding=12,
            border_radius=10,
            bgcolor=SURFACE_ALT,
            border=ft.border.all(1, BORDER),
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=22, color=ACCENT),
                    ft.Column(spacing=1, controls=[ft.Text(str(value), size=20, color=TEXT, weight=ft.FontWeight.BOLD), ft.Text(label, size=10, color=MUTED)]),
                ],
            ),
        )

    def _activity_chart(self):
        map_counts = {}
        day_counts = {}
        for match in self.history:
            map_name = str(match.get("map") or "Unknown")
            map_counts[map_name] = map_counts.get(map_name, 0) + 1
            if match.get("epoch"):
                day = datetime.fromtimestamp(match["epoch"]).date()
                day_counts[day] = day_counts.get(day, 0) + 1
        top_maps = sorted(map_counts.items(), key=lambda item: item[1], reverse=True)[:5]
        max_count = max(map_counts.values(), default=1)
        max_day = max(day_counts.values(), default=1)
        map_bars = [
            ft.Row(
                spacing=8,
                controls=[
                    ft.Text(name, width=82, size=10, color=TEXT if index == 0 else MUTED, weight=ft.FontWeight.BOLD if index == 0 else ft.FontWeight.W_500, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.ProgressBar(value=count / max_count, expand=True, height=7, border_radius=4, color=ACCENT if index == 0 else ft.Colors.with_opacity(0.58, ACCENT), bgcolor="#252C38"),
                    ft.Container(width=34, alignment=ft.alignment.center_right, content=ft.Text(str(count), size=10, color=TEXT, weight=ft.FontWeight.BOLD)),
                ],
            )
            for index, (name, count) in enumerate(top_maps)
        ]
        today = datetime.now().date()
        recent_days = [(today - timedelta(days=offset)) for offset in reversed(range(10))]
        day_cells = []
        for day in recent_days:
            count = day_counts.get(day, 0)
            intensity = count / max_day if count else 0
            day_cells.append(
                ft.Column(
                    expand=True,
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=5,
                    controls=[
                        ft.Container(
                            width=42,
                            height=48,
                            border_radius=9,
                            bgcolor=ft.Colors.with_opacity(0.10 + intensity * 0.58, ALLY) if count else "#171D26",
                            border=ft.border.all(1, ft.Colors.with_opacity(0.25 + intensity * 0.45, ALLY) if count else BORDER),
                            alignment=ft.alignment.center,
                            tooltip=f"{day.strftime('%d.%m.%Y')}: {count} матчей",
                            content=ft.Text(str(count), size=15, color=TEXT if count else "#4C5563", weight=ft.FontWeight.BOLD),
                        ),
                        ft.Text(day.strftime("%d.%m"), size=7, color=MUTED),
                    ],
                )
            )
        return ft.ResponsiveRow(
            spacing=10,
            run_spacing=10,
            controls=[
                ft.Container(
                    col={"xs": 12, "lg": 6},
                    height=188,
                    padding=14,
                    border_radius=14,
                    bgcolor=SURFACE,
                    border=ft.border.all(1, BORDER),
                    content=ft.Column(spacing=9, controls=[ft.Row(controls=[ft.Icon(ft.Icons.MAP_ROUNDED, size=18, color=ACCENT), ft.Text("ПОПУЛЯРНЫЕ КАРТЫ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD), ft.Container(expand=True), ft.Text(f"{sum(map_counts.values())} матчей", size=9, color=MUTED)]), *(map_bars or [ft.Text("Недостаточно данных", size=11, color=MUTED)])]),
                ),
                ft.Container(
                    col={"xs": 12, "lg": 6},
                    height=188,
                    padding=14,
                    border_radius=14,
                    bgcolor=SURFACE,
                    border=ft.border.all(1, BORDER),
                    content=ft.Column(spacing=12, controls=[ft.Row(controls=[ft.Icon(ft.Icons.CALENDAR_MONTH_ROUNDED, size=18, color=ALLY), ft.Text("АКТИВНОСТЬ ЗА 10 ДНЕЙ", size=10, color=ALLY, weight=ft.FontWeight.BOLD), ft.Container(expand=True), ft.Text(f"{sum(day_counts.get(day, 0) for day in recent_days)} матчей", size=9, color=MUTED)]), ft.Row(expand=True, alignment=ft.MainAxisAlignment.SPACE_AROUND, vertical_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, controls=day_cells)]),
                ),
            ],
        )

    def _history_match_card(self, match):
        players = list(match["players"].values())
        played_at = datetime.fromtimestamp(match["epoch"]).strftime("%d.%m.%Y  %H:%M") if match["epoch"] else "Unknown"
        return ft.Container(
            padding=12,
            border_radius=10,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            ink=True,
            animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
            on_click=lambda _, selected_match=match: self.page.run_task(self._deferred_history_open, selected_match),
            content=ft.Row(
                controls=[
                    ft.Container(width=4, height=38, border_radius=2, bgcolor=ACCENT),
                    ft.Column(expand=True, spacing=2, controls=[ft.Text(str(match["map"] or "Unknown"), size=14, color=TEXT, weight=ft.FontWeight.BOLD), ft.Text(f"{match.get('mode') or 'Режим не сохранён'}  /  {played_at}", size=10, color=MUTED)]),
                    ft.Text(f"{len(players)} игроков", size=11, color=MUTED),
                    ft.Row(spacing=4, controls=[_rank_badge(player.get("rank")) for player in players[:3]]),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=20, color=MUTED),
                ],
            ),
        )

    def _history_match_sections(self, match):
        players = list(match["players"].values())
        teams = {}
        for player in players:
            team = str(player.get("team") or "")
            teams.setdefault(team, []).append(player)
        populated = [team for team in teams if team]
        def rank_score(player):
            try:
                return int(player.get("rank") or 0) * 100 + int(player.get("rr") or 0)
            except (TypeError, ValueError):
                return 0

        if len(populated) < 2:
            return [("СОСТАВ", MUTED, sorted(players, key=rank_score, reverse=True))]
        account_puuid = match.get("account_puuid")
        account_team = str(match["players"].get(account_puuid, {}).get("team") or "")
        sections = []
        for team in sorted(populated, key=lambda value: value != account_team):
            if account_team:
                label = "ВАША КОМАНДА" if team == account_team else "ПРОТИВНИКИ"
            else:
                label = {"blue": "СИНЯЯ КОМАНДА", "red": "КРАСНАЯ КОМАНДА"}.get(team.lower(), f"КОМАНДА {team.upper()}")
            color = ALLY if team == account_team or team.lower() == "blue" else ENEMY
            sections.append((label, color, sorted(teams[team], key=rank_score, reverse=True)))
        return sections

    def _history_player_row(self, player, is_self=False):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=10, vertical=8),
            border_radius=9,
            bgcolor="#1B171E" if is_self else "#0D1118",
            border=ft.border.all(1, ft.Colors.with_opacity(0.55, ACCENT) if is_self else BORDER),
            content=ft.Row(
                controls=[
                    ft.Container(
                        visible=is_self,
                        padding=ft.padding.symmetric(horizontal=5, vertical=2),
                        border_radius=5,
                        bgcolor=ACCENT,
                        content=ft.Text("ВЫ", size=7, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                    ),
                    ft.Column(
                        expand=True,
                        spacing=1,
                        controls=[
                            ft.Text(player.get("name", "Unknown"), size=13, color=TEXT, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(player.get("agent", "Unknown"), size=10, color=MUTED),
                        ],
                    ),
                    _rank_badge(player.get("rank")),
                    ft.Container(width=58, alignment=ft.alignment.center_right, content=ft.Text(f"{player.get('rr', 0)} RR", size=11, color=ACCENT, weight=ft.FontWeight.BOLD)),
                    ft.TextButton(
                        text="VTL",
                        icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                        tooltip="Открыть профиль VTL.LOL",
                        on_click=lambda _, puuid=player.get("puuid"): self._open_history_vtl(puuid),
                    ),
                ],
            ),
        )

    def _open_history_vtl(self, puuid):
        if puuid:
            self.page.launch_url(f"https://vtl.lol/id/{quote(str(puuid), safe='')}")

    async def _deferred_history_open(self, match):
        await asyncio.sleep(0.06)
        self._show_history_match(match)

    def _show_history_match(self, match):
        self.player_panel_open = True
        played_at = datetime.fromtimestamp(match["epoch"]).strftime("%d.%m.%Y  %H:%M") if match["epoch"] else "Unknown"
        hero_background = (
            ft.Image(src=match.get("mapSplash"), left=0, top=0, right=0, bottom=0, fit=ft.ImageFit.COVER, opacity=0.42)
            if match.get("mapSplash")
            else ft.Container(left=0, top=0, right=0, bottom=0, bgcolor=SURFACE_ALT)
        )
        controls = [
            ft.Container(
                height=130,
                border_radius=13,
                clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                content=ft.Stack(
                    controls=[
                        hero_background,
                        ft.Container(left=0, top=0, right=0, bottom=0, gradient=ft.LinearGradient(begin=ft.alignment.center_left, end=ft.alignment.center_right, colors=["#080B10", ft.Colors.with_opacity(0.45, "#080B10")])),
                        ft.Container(
                            left=0,
                            top=0,
                            right=0,
                            bottom=0,
                            padding=14,
                            content=ft.Column(
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=4,
                                controls=[
                                    ft.Text(str(match.get("map") or "Unknown"), size=25, color=TEXT, weight=ft.FontWeight.BOLD),
                                    ft.Text(f"{match.get('mode') or 'Режим не сохранён'}  /  {played_at}", size=11, color=MUTED),
                                ],
                            ),
                        ),
                        ft.IconButton(right=5, top=5, icon=ft.Icons.CLOSE_ROUNDED, icon_color=TEXT, on_click=self._close_player_panel),
                    ],
                ),
            ),
            ft.ResponsiveRow(
                spacing=8,
                controls=[
                    self._detail_metric("Игроков", len(match["players"])),
                    self._detail_metric("Сервер", match.get("server") or "N/A"),
                    self._detail_metric("Match ID", str(match["match_id"])[:12] + "..."),
                ],
            ),
            ft.Row(
                alignment=ft.MainAxisAlignment.END,
                controls=[
                    ft.Icon(ft.Icons.SORT_ROUNDED, size=16, color=ACCENT),
                    ft.Text("Сортировка: ранг ↓", size=10, color=MUTED, weight=ft.FontWeight.W_600),
                ],
            ),
        ]
        for label, color, players in self._history_match_sections(match):
            controls.append(
                ft.Row(
                    controls=[
                        ft.Container(width=7, height=7, border_radius=4, bgcolor=color),
                        ft.Text(label, size=10, color=color, weight=ft.FontWeight.BOLD),
                        ft.Container(expand=True, height=1, bgcolor=BORDER),
                        ft.Text(str(len(players)), size=10, color=MUTED),
                    ],
                )
            )
            controls.extend(self._history_player_row(player, player.get("puuid") == match.get("account_puuid")) for player in players)

        self.player_panel.width = 520
        self.player_panel.content = ft.Column(expand=True, scroll=ft.ScrollMode.HIDDEN, spacing=9, controls=controls)
        self.player_panel.right = 0
        self.player_scrim.visible = True
        if hasattr(self.page, "overlay"):
            try:
                self.player_panel.update()
                self.player_scrim.update()
            except AssertionError:
                pass
        else:
            self.page.update()
        self.page.run_task(self._restore_history_scroll)

    async def _restore_history_scroll(self):
        # Flet may perform a second layout pass after an overlay is opened.
        for delay in (0.08, 0.25, 0.5):
            await asyncio.sleep(delay)
            control = self.scroll_controls.get("history")
            offset = self.scroll_positions.get("history", 0)
            if control is not None and offset > 0:
                try:
                    control.scroll_to(offset=offset, duration=0)
                except AssertionError:
                    pass

    def _diagnostics_view(self):
        heartbeat = self.snapshot.get("heartbeat") or {}
        heartbeat_at = self.snapshot.get("heartbeat_at") or self.snapshot.get("updated_at", time.time())
        age = max(0, int(time.time() - heartbeat_at))
        uptime = max(0, int(time.time() - self.snapshot.get("started_at", time.time())))
        error = self.snapshot.get("error")
        quality = "Стабильно" if age < 5 else "Задержка" if age < 15 else "Нет обновлений"
        quality_color = "#4BC487" if age < 5 else "#E6C24F" if age < 15 else ENEMY
        puuid = str(heartbeat.get("puuid") or "")
        match_id = str(heartbeat.get("matchId") or "")
        diagnostics = [
            ("Monitor", "Ошибка" if error else "Активен", ENEMY if error else "#4BC487"),
            ("Riot Client", "Подключён" if heartbeat else "Ожидание", "#4BC487" if heartbeat else "#E6C24F"),
            ("Качество", quality, quality_color),
            ("Game state", heartbeat.get("state", "Unknown"), ACCENT),
            ("Region", str(heartbeat.get("region", "Unknown")).upper(), TEXT),
            ("Heartbeat", f"{age} сек. назад", TEXT if age < 10 else "#E6C24F"),
            ("Uptime", self._format_duration(uptime), TEXT),
            ("Players", len(heartbeat.get("players") or {}), TEXT),
            ("Server", _server_name(heartbeat.get("server")), MUTED),
            ("Version", heartbeat.get("appVersion", version), MUTED),
            ("Account", f"{puuid[:8]}...{puuid[-4:]}" if len(puuid) > 12 else "N/A", MUTED),
            ("Match ID", f"{match_id[:8]}...{match_id[-4:]}" if len(match_id) > 12 else "N/A", MUTED),
        ]
        controls = [
            ft.Row(
                vertical_alignment=ft.CrossAxisAlignment.START,
                controls=[
                    self._header("SYSTEM HEALTH", "Диагностика", "Состояние Riot monitor и безопасный журнал событий."),
                    ft.Container(expand=True),
                    ft.OutlinedButton(
                        text="Очистить журнал",
                        icon=ft.Icons.DELETE_SWEEP_ROUNDED,
                        on_click=self._clear_diagnostic_events,
                    ),
                ],
            )
        ]
        controls.append(
            ft.ResponsiveRow(
                spacing=10,
                run_spacing=10,
                controls=[
                    ft.Container(
                        col={"xs": 12, "sm": 6, "lg": 3},
                        padding=12,
                        border_radius=10,
                        bgcolor=SURFACE,
                        border=ft.border.all(1, BORDER),
                        content=ft.Column(spacing=3, controls=[ft.Text(label.upper(), size=9, color=MUTED, weight=ft.FontWeight.BOLD), ft.Text(str(value), size=14, color=color, weight=ft.FontWeight.BOLD, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]),
                    )
                    for label, value, color in diagnostics
                ],
            )
        )
        controls.append(self._connection_timeline())
        controls.append(self._heartbeat_graph())
        if error:
            controls.append(ft.Container(padding=12, border_radius=10, bgcolor="#2A151A", border=ft.border.all(1, "#5B2730"), content=ft.Text(error, size=11, color="#FF9DA6")))
        controls.append(
            ft.Row(
                controls=[
                    ft.Text("ЖУРНАЛ СОБЫТИЙ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD),
                    ft.Container(expand=True, height=1, bgcolor=BORDER),
                    ft.Text(f"{len(self.snapshot.get('events') or [])} / 100", size=9, color=MUTED),
                ],
            )
        )
        events = list(reversed(self.snapshot.get("events") or []))
        if events:
            controls.extend(self._diagnostic_event_row(event) for event in events)
        else:
            controls.append(ft.Container(padding=18, alignment=ft.alignment.center, content=ft.Text("Событий пока нет", size=12, color=MUTED)))
        header = controls.pop(0)
        return ft.Column(
            expand=True,
            spacing=14,
            controls=[
                header,
                self._scrollable_column("diagnostics", controls, spacing=10),
            ],
        )

    def _connection_timeline(self):
        heartbeat = self.snapshot.get("heartbeat") or {}
        error = bool(self.snapshot.get("error"))
        connected = bool(heartbeat)
        steps = [
            ("Riot Client", connected, ft.Icons.DESKTOP_WINDOWS_ROUNDED),
            ("Lockfile", connected, ft.Icons.KEY_ROUNDED),
            ("API", connected and not error, ft.Icons.CLOUD_DONE_ROUNDED),
            ("WebSocket", connected and not error, ft.Icons.CABLE_ROUNDED),
        ]
        controls = []
        for index, (label, active, icon) in enumerate(steps):
            color = "#4BC487" if active else ENEMY if error and index > 1 else MUTED
            controls.append(ft.Column(horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4, controls=[ft.Container(width=30, height=30, border_radius=15, bgcolor=ft.Colors.with_opacity(0.14, color), alignment=ft.alignment.center, content=ft.Icon(icon, size=16, color=color)), ft.Text(label, size=9, color=color, weight=ft.FontWeight.W_600)]))
            if index < len(steps) - 1:
                controls.append(ft.Container(expand=True, height=1, bgcolor=ft.Colors.with_opacity(0.35, color), margin=ft.margin.only(bottom=22)))
        return ft.Container(padding=12, border_radius=12, bgcolor=SURFACE, border=ft.border.all(1, BORDER), content=ft.Column(spacing=7, controls=[ft.Text("CONNECTION TIMELINE", size=9, color=ACCENT, weight=ft.FontWeight.BOLD), ft.Row(vertical_alignment=ft.CrossAxisAlignment.CENTER, controls=controls)]))

    def _heartbeat_graph(self):
        points = self.snapshot.get("heartbeat_history") or []
        gaps = []
        for previous, current in zip(points, points[1:]):
            gaps.append(max(0.1, min(10, current - previous)))
        if not gaps:
            gaps = [0.1]
        max_gap = max(gaps)
        bars = [ft.Container(width=8, height=max(8, int(48 * gap / max_gap)), border_radius=3, bgcolor=ENEMY if gap > 5 else "#4BC487" if gap < 2 else "#E6C24F") for gap in gaps[-30:]]
        return ft.Container(padding=12, border_radius=12, bgcolor=SURFACE, border=ft.border.all(1, BORDER), content=ft.Column(spacing=6, controls=[ft.Row(controls=[ft.Text("HEARTBEAT GRAPH", size=9, color=ACCENT, weight=ft.FontWeight.BOLD), ft.Container(expand=True), ft.Text(f"{len(points)} точек", size=9, color=MUTED)]), ft.Container(height=62, content=ft.Row(alignment=ft.MainAxisAlignment.END, vertical_alignment=ft.CrossAxisAlignment.END, spacing=4, controls=bars))]))

    def _format_duration(self, seconds):
        hours, remainder = divmod(int(seconds), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours:
            return f"{hours}ч {minutes}м"
        if minutes:
            return f"{minutes}м {seconds}с"
        return f"{seconds}с"

    def _diagnostic_event_row(self, event):
        styles = {
            "error": (ft.Icons.ERROR_OUTLINE_ROUNDED, ENEMY),
            "state": (ft.Icons.SYNC_ALT_ROUNDED, ACCENT),
            "match": (ft.Icons.SPORTS_ESPORTS_ROUNDED, ALLY),
            "data": (ft.Icons.STORAGE_ROUNDED, "#4BC487"),
            "info": (ft.Icons.INFO_OUTLINE_ROUNDED, MUTED),
        }
        icon, color = styles.get(event.get("level"), styles["info"])
        event_time = datetime.fromtimestamp(event.get("time", 0)).strftime("%H:%M:%S")
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=12, vertical=9),
            border_radius=9,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            content=ft.Row(
                controls=[
                    ft.Container(width=30, height=30, border_radius=8, bgcolor=ft.Colors.with_opacity(0.12, color), alignment=ft.alignment.center, content=ft.Icon(icon, size=17, color=color)),
                    ft.Column(expand=True, spacing=2, controls=[ft.Text(event.get("title", "Событие"), size=12, color=TEXT, weight=ft.FontWeight.BOLD), ft.Text(event.get("message", ""), size=10, color=MUTED)]),
                    ft.Text(event_time, size=9, color="#616A78"),
                ],
            ),
        )

    def _clear_diagnostic_events(self, _):
        app_state.clear_events()
        self.snapshot["events"] = []
        self.render()

    def _account_view(self):
        heartbeat = self.snapshot.get("heartbeat") or {}
        account = self.snapshot.get("account") or {}
        player = account.get("profile")
        if not player:
            puuid = heartbeat.get("puuid")
            player = (heartbeat.get("players") or {}).get(puuid)
            if player:
                account = {
                    "profile": player,
                    "state": heartbeat.get("state"),
                    "mode": heartbeat.get("mode"),
                    "map": heartbeat.get("map"),
                    "server": heartbeat.get("server"),
                    "region": heartbeat.get("region"),
                    "updatedAt": self.snapshot.get("heartbeat_at"),
                }
        if not player:
            return self._waiting_view("IDENTITY", "Аккаунт", "Текущий профиль Riot.", ft.Icons.ACCOUNT_CIRCLE_ROUNDED, "Аккаунт не загружен", "Откройте VALORANT, чтобы получить данные текущего профиля.")
        updated_at = account.get("updatedAt")
        updated_text = datetime.fromtimestamp(updated_at).strftime("%H:%M:%S") if updated_at else "Unknown"
        state = account.get("state") or "Unknown"
        state_color = "#4BC487" if state == "INGAME" else ACCENT if state == "PREGAME" else ALLY
        agent_label = player.get("agent") or "Агент не выбран"
        return self._scrollable_column("account", [
                ft.Row(
                    controls=[
                        self._header("IDENTITY", "Аккаунт", "Профиль обновляется при входе в лобби, выборе агента и начале матча."),
                        ft.Container(expand=True),
                        ft.Container(
                            padding=ft.padding.symmetric(horizontal=9, vertical=5),
                            border_radius=7,
                            bgcolor=ft.Colors.with_opacity(0.13, state_color),
                            border=ft.border.all(1, ft.Colors.with_opacity(0.35, state_color)),
                            content=ft.Row(spacing=6, controls=[ft.Container(width=7, height=7, border_radius=4, bgcolor=state_color), ft.Text(state, size=10, color=state_color, weight=ft.FontWeight.BOLD)]),
                        ),
                    ],
                ),
                self._account_hero(account, player, agent_label),
                ft.Text("РЕЙТИНГ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD),
                ft.Container(
                    padding=14,
                    border_radius=12,
                    bgcolor=SURFACE,
                    border=ft.border.all(1, BORDER),
                    content=ft.Row(
                        spacing=26,
                        controls=[
                            ft.Column(spacing=4, controls=[ft.Text("ТЕКУЩИЙ", size=9, color=MUTED, weight=ft.FontWeight.BOLD), self._card_rank_badge(player.get("rank"), player.get("rankIcon"))]),
                            ft.Column(spacing=4, controls=[ft.Text("ПИКОВЫЙ", size=9, color=MUTED, weight=ft.FontWeight.BOLD), self._card_rank_badge(player.get("peakRank"), player.get("peakRankIcon"), player.get("peakRankAct"))]),
                            ft.Column(spacing=4, controls=[ft.Text("ПРОШЛЫЙ", size=9, color=MUTED, weight=ft.FontWeight.BOLD), self._card_rank_badge(player.get("previousRank"), player.get("previousRankIcon"))]),
                        ],
                    ),
                ),
                ft.ResponsiveRow(
                    spacing=10,
                    run_spacing=10,
                    controls=[
                        self._detail_metric("RR", player.get("rr", "-"), ACCENT),
                        self._detail_metric("ΔRR", player.get("earnedRR", "-"), self._heat_color("earned_rr", player) or TEXT),
                        self._detail_metric("Leaderboard", f"#{player.get('leaderboard')}" if player.get("leaderboard") else "-"),
                        self._detail_metric("HS%", f"{player.get('headshotPercentage', '-')}%", self._heat_color("headshot_percent", player) or TEXT),
                        self._detail_metric("Win rate", player.get("winPercentage", "-"), self._heat_color("winrate", player) or TEXT),
                        self._detail_metric("K/D", player.get("kd", "-"), self._heat_color("kd", player) or TEXT),
                    ],
                ),
                self._account_rank_progress(player),
                self._account_recent_stats(player),
                ft.Text("ТЕКУЩАЯ СЕССИЯ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD),
                ft.Container(
                    padding=14,
                    border_radius=12,
                    bgcolor=SURFACE,
                    border=ft.border.all(1, BORDER),
                    content=ft.ResponsiveRow(
                        spacing=10,
                        run_spacing=10,
                        controls=[
                            self._account_context_item("Состояние", state, ft.Icons.RADAR_ROUNDED),
                            self._account_context_item("Режим", account.get("mode") or "N/A", ft.Icons.SPORTS_ESPORTS_ROUNDED),
                            self._account_context_item("Карта", _map_name(account.get("map")), ft.Icons.MAP_ROUNDED),
                            self._account_context_item("Сервер", _server_name(account.get("server")), ft.Icons.DNS_ROUNDED),
                            self._account_context_item("Регион", str(account.get("region") or "-").upper(), ft.Icons.PUBLIC_ROUNDED),
                            self._account_context_item("Обновлено", updated_text, ft.Icons.UPDATE_ROUNDED),
                        ],
                    ),
                ),
                ft.Container(
                    visible=bool(player.get("skin")),
                    padding=12,
                    border_radius=10,
                    bgcolor="#0D1118",
                    border=ft.border.all(1, BORDER),
                    content=ft.Row(controls=[ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ACCENT), ft.Column(spacing=2, controls=[ft.Text("ТЕКУЩИЙ СКИН", size=8, color=MUTED, weight=ft.FontWeight.BOLD), ft.Text(player.get("skin", "-"), size=13, color=TEXT, weight=ft.FontWeight.W_600)])]),
                ),
            ], spacing=14)

    def _account_hero(self, account, player, agent_label):
        player_card = player.get("playerCard")
        background = ft.Image(src=player_card, left=0, top=0, right=0, bottom=0, fit=ft.ImageFit.COVER, opacity=0.34) if player_card else ft.Container(left=0, top=0, right=0, bottom=0, bgcolor=SURFACE)
        return ft.Container(
            height=174,
            border_radius=16,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            border=ft.border.all(1, BORDER),
            content=ft.Stack(
                controls=[
                    background,
                    ft.Container(left=0, top=0, right=0, bottom=0, gradient=ft.LinearGradient(begin=ft.alignment.center_left, end=ft.alignment.center_right, colors=["#080B10", ft.Colors.with_opacity(0.78, "#080B10"), ft.Colors.with_opacity(0.24, "#080B10")])),
                    ft.Container(
                        left=18,
                        top=18,
                        right=18,
                        bottom=18,
                        content=ft.Row(
                            controls=[
                                self._agent_avatar(player, 82),
                                ft.Column(expand=True, spacing=5, controls=[ft.Text(player.get("name", "Unknown"), size=28, color=TEXT, weight=ft.FontWeight.BOLD), ft.Text(f"{agent_label}  /  LEVEL {player.get('level', '-')}", size=13, color="#C9D0DB"), _rank_badge(player.get("rank"))]),
                                ft.Column(horizontal_alignment=ft.CrossAxisAlignment.END, spacing=7, controls=[ft.Text(str(account.get("state") or "Unknown"), size=10, color=ACCENT, weight=ft.FontWeight.BOLD), ft.ElevatedButton(text="VTL.LOL", icon=ft.Icons.OPEN_IN_NEW_ROUNDED, style=self._primary_button_style(), on_click=lambda _: self._open_profile_for(player, "vtl")), ft.OutlinedButton(text="Скопировать ник", icon=ft.Icons.CONTENT_COPY_ROUNDED, style=self._secondary_button_style(), disabled=player.get("streamerMode") or "#" not in player.get("name", ""), on_click=lambda event: self._copy_riot_id(player, event.control))]),
                            ],
                        ),
                    ),
                ],
            ),
        )

    def _account_rank_progress(self, player):
        try:
            rr = max(0, min(100, int(player.get("rr") or 0)))
        except (TypeError, ValueError):
            rr = 0
        tier = self._rank_value(player)
        current = _rank_meta(tier)[0]
        next_rank = "Radiant" if tier >= 27 else _rank_meta(tier + 1)[0]
        return ft.Container(
            padding=14,
            border_radius=12,
            bgcolor=SURFACE,
            border=ft.border.all(1, BORDER),
            content=ft.Column(spacing=7, controls=[ft.Row(controls=[ft.Text("ПРОГРЕСС РАНГА", size=9, color=ACCENT, weight=ft.FontWeight.BOLD), ft.Container(expand=True), ft.Text(f"{rr} / 100 RR", size=11, color=TEXT, weight=ft.FontWeight.BOLD)]), ft.ProgressBar(value=rr / 100, color=ACCENT, bgcolor="#252C38", height=7, border_radius=4), ft.Row(controls=[ft.Text(current, size=10, color=MUTED), ft.Container(expand=True), ft.Text(f"Следующий: {next_rank}", size=10, color=MUTED)])]),
        )

    def _account_recent_stats(self, player):
        entries = self.stats_store.get_player_history(player.get("puuid"), 20)
        numeric = lambda key: [float(entry[key]) for entry in entries if entry.get(key) not in (None, "", "N/A")]
        hs = numeric("hs")
        kd = numeric("kd")
        wins = numeric("winRate")
        agents = {}
        for entry in entries:
            agent = entry.get("agent")
            if agent:
                agents[agent] = agents.get(agent, 0) + 1
        favorite = max(agents, key=agents.get) if agents else "N/A"
        return ft.Column(spacing=8, controls=[ft.Text("ПОСЛЕДНИЕ 20 МАТЧЕЙ", size=10, color=ACCENT, weight=ft.FontWeight.BOLD), ft.ResponsiveRow(spacing=10, controls=[self._detail_metric("Матчи", len(entries)), self._detail_metric("Средний HS%", f"{sum(hs) / len(hs):.1f}%" if hs else "N/A"), self._detail_metric("Средний K/D", f"{sum(kd) / len(kd):.2f}" if kd else "N/A"), self._detail_metric("Средний WR", f"{sum(wins) / len(wins):.1f}%" if wins else "N/A"), self._detail_metric("Любимый агент", favorite)])])

    def _account_context_item(self, label, value, icon):
        return ft.Container(
            col={"xs": 6, "md": 4},
            padding=9,
            border_radius=9,
            bgcolor="#0D1118",
            content=ft.Row(
                controls=[
                    ft.Icon(icon, size=18, color=MUTED),
                    ft.Column(expand=True, spacing=1, controls=[ft.Text(label.upper(), size=8, color=MUTED, weight=ft.FontWeight.BOLD), ft.Text(str(value), size=12, color=TEXT, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)]),
                ],
            ),
        )

    def _open_profile_for(self, player, service):
        self.selected_player = player
        if service == "vtl":
            self._open_vtl_profile(None)
        else:
            self._open_tracker_profile(None)

    def _copy_riot_id(self, player, button=None):
        riot_id = str(player.get("name") or "")
        if not riot_id or player.get("streamerMode") or "#" not in riot_id:
            return
        self.page.set_clipboard(riot_id)
        if button is not None:
            button.text = "Скопировано"
            button.icon = ft.Icons.CHECK_ROUNDED
            try:
                button.update()
            except AssertionError:
                pass
            self.page.run_task(self._reset_copy_button, button)

    async def _reset_copy_button(self, button):
        await asyncio.sleep(1.6)
        button.text = "Скопировать ник"
        button.icon = ft.Icons.CONTENT_COPY_ROUNDED
        try:
            button.update()
        except AssertionError:
            pass

    def _header(self, eyebrow, title, description, centered=False):
        return ft.Column(
            spacing=5,
            horizontal_alignment=ft.CrossAxisAlignment.CENTER if centered else ft.CrossAxisAlignment.START,
            controls=[
                ft.Text(eyebrow, size=10, color=ACCENT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER if centered else None),
                ft.Text(title, size=30, color=TEXT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER if centered else None),
                ft.Text(description, size=13, color=MUTED, text_align=ft.TextAlign.CENTER if centered else None),
            ],
        )

    def _primary_button_style(self):
        return ft.ButtonStyle(
            color="#FFFFFF",
            bgcolor=ACCENT,
            overlay_color=ft.Colors.with_opacity(0.16, "#FFFFFF"),
            padding=ft.padding.symmetric(horizontal=14, vertical=10),
            shape=ft.RoundedRectangleBorder(radius=9),
        )

    def _secondary_button_style(self):
        return ft.ButtonStyle(
            color="#C8CFDA",
            bgcolor=ft.Colors.with_opacity(0.32, "#171D27"),
            side=ft.BorderSide(1, "#343C49"),
            overlay_color=ft.Colors.with_opacity(0.08, "#FFFFFF"),
            padding=ft.padding.symmetric(horizontal=12, vertical=9),
            shape=ft.RoundedRectangleBorder(radius=9),
        )

    def _waiting_view(self, eyebrow, title, description, icon, waiting_title, waiting_text, error=None):
        controls = [
            ft.Icon(icon, size=40, color=ACCENT),
            ft.Text(waiting_title, size=18, color=TEXT, weight=ft.FontWeight.BOLD, text_align=ft.TextAlign.CENTER),
            ft.Text(waiting_text, size=12, color=MUTED, text_align=ft.TextAlign.CENTER),
        ]
        if error:
            controls.append(
                ft.Container(
                    width=560,
                    padding=12,
                    border_radius=10,
                    bgcolor="#2A151A",
                    border=ft.border.all(1, "#5B2730"),
                    content=ft.Text(error, color="#FF9DA6", size=11, text_align=ft.TextAlign.CENTER),
                )
            )
        waiting_content = ft.Container(
            expand=True,
            alignment=ft.alignment.center,
            content=ft.Column(
                tight=True,
                width=620,
                spacing=9,
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                controls=controls,
            ),
        )
        return ft.Column(
            expand=True,
            spacing=14,
            controls=[self._header(eyebrow, title, description), waiting_content],
        )

    def _match_loading_view(self, error=None):
        skeletons = []
        for index in range(5):
            skeleton = ft.Container(
                height=54,
                padding=10,
                border_radius=10,
                opacity=0.78 - index * 0.06,
                animate_opacity=ft.Animation(650, ft.AnimationCurve.EASE_IN_OUT),
                bgcolor=ft.Colors.with_opacity(0.62, "#151B24"),
                border=ft.border.all(1, ft.Colors.with_opacity(0.55, BORDER)),
                content=ft.Row(
                    controls=[
                        ft.Container(width=32, height=32, border_radius=16, gradient=ft.LinearGradient(colors=["#242C38", "#343D49", "#242C38"])),
                        ft.Column(expand=True, spacing=6, controls=[ft.Container(width=180 + index * 18, height=9, border_radius=5, bgcolor="#303946"), ft.Container(width=90, height=7, border_radius=4, bgcolor="#242C37")]),
                        ft.Container(width=100, height=22, border_radius=7, bgcolor="#252E3A"),
                        ft.Container(width=64, height=22, border_radius=7, bgcolor="#202833"),
                    ],
                ),
            )
            skeletons.append(skeleton)
        self.shimmer_controls = skeletons
        controls = [
            self._header("LIVE SESSION", "Тактическая сводка", "Подключаемся к Riot Client и собираем данные игроков."),
            ft.Container(
                padding=12,
                border_radius=10,
                bgcolor=ft.Colors.with_opacity(0.70, SURFACE),
                content=ft.Row(controls=[ft.Icon(ft.Icons.RADAR_ROUNDED, color=ACCENT), ft.Text("Ожидание данных матча...", size=12, color=MUTED)]),
            ),
            *skeletons,
        ]
        if error:
            controls.insert(1, ft.Container(padding=10, border_radius=9, bgcolor="#2A151A", content=ft.Text(error, size=10, color="#FF9DA6")))
        return ft.Column(expand=True, spacing=8, controls=controls)

    def _match_hero(self, heartbeat, compact=False):
        splash = heartbeat.get("mapSplash")
        map_name = _map_name(heartbeat.get("map"))
        state = str(heartbeat.get("state", "Unknown"))
        mode = str(heartbeat.get("mode", "Unknown"))
        own_team = heartbeat.get("ownTeam")
        side_name = {"blue": "Синяя команда", "red": "Красная команда"}.get(str(own_team).lower()) if own_team else None
        background = (
            ft.Image(src=splash, left=0, top=0, right=0, bottom=0, fit=ft.ImageFit.COVER, opacity=0.54)
            if splash
            else ft.Container(left=0, top=0, right=0, bottom=0, bgcolor=SURFACE_ALT)
        )
        return ft.Container(
            height=122 if compact else 158,
            border_radius=16,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            border=ft.border.all(1, "#343B48"),
            content=ft.Stack(
                controls=[
                    background,
                    ft.Container(
                        left=0,
                        top=0,
                        right=0,
                        bottom=0,
                        gradient=ft.LinearGradient(
                            begin=ft.alignment.center_left,
                            end=ft.alignment.center_right,
                            colors=["#080B10", ft.Colors.with_opacity(0.78, "#080B10"), ft.Colors.with_opacity(0.18, "#080B10")],
                        ),
                    ),
                    ft.Container(
                        right=18,
                        bottom=-8,
                        content=ft.Text(
                            map_name.upper(),
                            size=52,
                            color=ft.Colors.with_opacity(0.16, "#FFFFFF"),
                            weight=ft.FontWeight.BOLD,
                            no_wrap=True,
                        ),
                    ),
                    ft.Container(
                        left=0,
                        top=0,
                        right=0,
                        bottom=0,
                        padding=ft.padding.symmetric(horizontal=22, vertical=12 if compact else 18),
                        alignment=ft.alignment.center_left,
                        content=ft.Column(
                            alignment=ft.MainAxisAlignment.CENTER,
                            spacing=9,
                            controls=[
                                ft.Row(
                                    spacing=7,
                                    controls=[
                                        ft.Container(
                                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                            border_radius=6,
                                            bgcolor=ACCENT,
                                            content=ft.Text(state.upper(), size=9, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                                        ),
                                        ft.Container(
                                            padding=ft.padding.symmetric(horizontal=8, vertical=3),
                                            border_radius=6,
                                            bgcolor=ft.Colors.with_opacity(0.20, "#FFFFFF"),
                                            content=ft.Text(mode.upper(), size=9, color=TEXT, weight=ft.FontWeight.W_600),
                                        ),
                                    ],
                                ),
                                ft.Text("Тактическая сводка", size=28 if compact else 32, color=TEXT, weight=ft.FontWeight.BOLD),
                                ft.Row(
                                    spacing=7,
                                    controls=[
                                        ft.Icon(ft.Icons.MAP_ROUNDED, size=15, color=ACCENT),
                                        ft.Text(map_name, size=13, color="#D7DCE5", weight=ft.FontWeight.W_600),
                                        ft.Text("/", size=12, color=MUTED),
                                        ft.Text(f"{len(heartbeat.get('players') or {})} игроков", size=12, color=MUTED),
                                        ft.Text("/", size=12, color=MUTED),
                                        ft.Icon(ft.Icons.DNS_ROUNDED, size=15, color=ALLY),
                                        ft.Text(_server_name(heartbeat.get("server")), size=12, color="#D7DCE5", weight=ft.FontWeight.W_600),
                                        ft.Container(
                                            visible=bool(side_name),
                                            margin=ft.margin.only(left=4),
                                            padding=ft.padding.symmetric(horizontal=7, vertical=3),
                                            border_radius=6,
                                            bgcolor=ft.Colors.with_opacity(0.14, ALLY if str(own_team).lower() == "blue" else ENEMY),
                                            content=ft.Text(side_name or "", size=10, color=ALLY if str(own_team).lower() == "blue" else ENEMY, weight=ft.FontWeight.BOLD),
                                        ),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ]
            ),
        )

    def _set_sort(self, column_key):
        sort_fields = {
            "name": "name",
            "rank": "rank",
            "skin": "skin",
            "rr": "rr",
            "peakrank": "peakRank",
            "previousrank": "previousRank",
            "leaderboard": "leaderboard",
            "headshot_percent": "headshotPercentage",
            "winrate": "winPercentage",
            "kd": "kd",
            "level": "level",
            "earned_rr": "earnedRR",
        }
        selected_key = sort_fields[column_key]
        if self.sort_key == selected_key:
            self.sort_descending = not self.sort_descending
        else:
            self.sort_key = selected_key
            self.sort_descending = column_key != "name"
        self.render()

    def _sort_players(self, players):
        def sort_value(player):
            value = player.get(self.sort_key, "")
            if self.sort_key == "winPercentage":
                value = str(value).split(" ", 1)[0]
            if self.sort_key == "name":
                return str(value).casefold()
            try:
                return float(value)
            except (TypeError, ValueError):
                return -1.0

        return sorted(players, key=sort_value, reverse=self.sort_descending)

    def _notify(self, title, message, color=ACCENT):
        if not self.feature_settings.get("notifications", True):
            return
        self.page.open(
            ft.SnackBar(
                content=ft.Row(
                    controls=[
                        ft.Container(width=4, height=34, border_radius=2, bgcolor=color),
                        ft.Column(spacing=1, controls=[ft.Text(title, size=13, color=TEXT, weight=ft.FontWeight.BOLD), ft.Text(message, size=11, color=MUTED)]),
                    ],
                ),
                bgcolor="#111721",
                show_close_icon=True,
                close_icon_color=MUTED,
                duration=6500,
                margin=18,
                shape=ft.RoundedRectangleBorder(radius=12),
            )
        )

    def _handle_notifications(self, snapshot):
        heartbeat = snapshot.get("heartbeat") or {}
        state = heartbeat.get("state")
        match_key = heartbeat.get("matchId") or f"{heartbeat.get('map')}:{heartbeat.get('time')}"
        if state == "INGAME" and self.last_game_state != "INGAME" and self.feature_settings.get("match_start_notification", True):
            key = ("match-start", match_key)
            if key not in self.notification_keys:
                self.notification_keys.add(key)
                message = f"{heartbeat.get('mode', 'Unknown')}  /  {_map_name(heartbeat.get('map'))}"
                if not show_system_notification("Матч начался", message):
                    self._notify("Матч начался", message)

        players = heartbeat.get("players") or {}
        if state in {"PREGAME", "INGAME"}:
            high_ranked = [player for player in players.values() if self._rank_value(player) >= 24]
            if high_ranked and self.feature_settings.get("high_rank_notification", True):
                key = ("high-rank", match_key)
                if key not in self.notification_keys:
                    self.notification_keys.add(key)
                    if self.selected_view == 0:
                        names = ", ".join(player.get("name", "Unknown") for player in high_ranked[:3])
                        self._notify("Высокий ранг в лобби", names, _rank_meta(max(self._rank_value(player) for player in high_ranked))[1])

            repeated = [
                (player, self._past_encounter_count(player.get("puuid"), heartbeat.get("matchId")))
                for player in players.values()
                if player.get("puuid") != heartbeat.get("puuid")
            ]
            repeated = [(player, count) for player, count in repeated if count > 0]
            if repeated and self.feature_settings.get("repeat_encounter_notification", True):
                key = ("repeat", match_key)
                if key not in self.notification_keys:
                    self.notification_keys.add(key)
                    if self.selected_view == 0:
                        player, count = max(repeated, key=lambda item: item[1])
                        self._notify("Повторная встреча", f"{player.get('name', 'Unknown')}: прошлых матчей {count}", ALLY)
        self.last_game_state = state

    def _rank_value(self, player):
        try:
            return int(player.get("rank") or 0)
        except (TypeError, ValueError):
            return 0

    def _past_encounter_count(self, puuid, current_match_id=None):
        encounter = self.encounters.get(puuid) or {}
        count = int(encounter.get("count", 0))
        if current_match_id and any(
            match["match_id"] == current_match_id and puuid in match["players"]
            for match in self.history
        ):
            count -= 1
        return max(0, count)

    def _encounter_badge(self, player):
        if not self.feature_settings.get("repeat_encounters", True):
            return ft.Container(visible=False)
        heartbeat = self.snapshot.get("heartbeat") or {}
        if player.get("puuid") == heartbeat.get("puuid"):
            return ft.Container(visible=False)
        count = self._past_encounter_count(player.get("puuid"), heartbeat.get("matchId"))
        return ft.Container(
            visible=count > 0,
            padding=ft.padding.symmetric(horizontal=5, vertical=1),
            border_radius=5,
            bgcolor=ft.Colors.with_opacity(0.16, ALLY),
            tooltip=f"Предыдущих встреч: {count}",
            content=ft.Text(f"x{count}", size=8, color=ALLY, weight=ft.FontWeight.BOLD),
        )

    def _match_view(self):
        heartbeat = self.snapshot.get("heartbeat") or {}
        players = heartbeat.get("players") or {}
        error = self.snapshot.get("error")

        if not players:
            return self._match_loading_view(error)
        self.shimmer_controls = []

        body = []
        if error:
            body.append(
                ft.Container(
                    padding=12,
                    border_radius=10,
                    bgcolor="#2A151A",
                    border=ft.border.all(1, "#5B2730"),
                    content=ft.Text(error, color="#FF9DA6", size=11),
                )
            )

        sections = self._player_sections(heartbeat, players)
        mode = str(heartbeat.get("mode") or "").strip().lower()
        is_deathmatch = mode in {"deathmatch", "death match"}
        use_team_panels = len(sections) == 2 and mode not in {"deathmatch", "death match"} and self._viewport_width() >= 1200
        compact_match = use_team_panels or len(players) > 6
        self._wide_team_layout = self._viewport_width() >= 1200
        if use_team_panels:
            match_key = (
                heartbeat.get("state"),
                heartbeat.get("map"),
                tuple(sorted(players.keys())),
            )
            animate_teams = match_key != self._animated_match_key
            team_panels = [
                self._team_panel(label, color, section_players, heartbeat, animate_teams)
                for label, color, section_players in sections
            ]
            if animate_teams:
                self._animated_match_key = match_key
                self._pending_team_panels = team_panels
            body.append(
                ft.Row(
                    vertical_alignment=ft.CrossAxisAlignment.START,
                    spacing=12,
                    controls=team_panels,
                )
            )
        else:
            body.append(self._player_table_header())
            for label, color, section_players in sections:
                body.append(
                    ft.Container(
                        margin=ft.margin.only(top=6),
                        content=ft.Row(
                            controls=[
                                ft.Text(label, size=10, color=color, weight=ft.FontWeight.BOLD),
                                ft.Container(expand=True, height=1, bgcolor=BORDER),
                                ft.Text(str(len(section_players)), size=10, color=MUTED),
                            ]
                        ),
                    )
                )
                body.extend(
                    self._player_row(player, player.get("puuid") == heartbeat.get("puuid"), compact_match)
                    for player in self._sort_players(section_players)
                )

        hero = self._match_hero(heartbeat, compact_match)
        hero.key = f"hero-{heartbeat.get('map')}-{heartbeat.get('state')}"
        self.hero_switcher.height = hero.height
        self.hero_switcher.content = hero
        return ft.Column(
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            spacing=14,
            controls=[
                self.hero_switcher,
                self._scrollable_column("match", body, spacing=5 if compact_match else 10, enabled=is_deathmatch),
            ],
        )

    def _player_sections(self, heartbeat, players):
        player_list = list(players.values())
        mode = str(heartbeat.get("mode") or "").strip().lower()
        if mode in {"deathmatch", "death match"}:
            return [("ИГРОКИ", MUTED, player_list)]

        groups = {}
        for player in player_list:
            team = str(player.get("team") or "").strip()
            groups.setdefault(team, []).append(player)

        populated_teams = [team for team in groups if team]
        if len(populated_teams) <= 1:
            if heartbeat.get("ownTeam") and populated_teams:
                return [("ВАША КОМАНДА", ALLY, player_list)]
            return [("СОСТАВ", ALLY if populated_teams else MUTED, player_list)]

        local_puuid = heartbeat.get("puuid")
        local_team = next(
            (
                str(player.get("team"))
                for player in player_list
                if player.get("puuid") == local_puuid and player.get("team")
            ),
            None,
        )
        ordered_teams = sorted(populated_teams, key=lambda team: team != local_team)
        sections = []
        for team in ordered_teams:
            if local_team:
                label = "ВАША КОМАНДА" if team == local_team else "ПРОТИВНИКИ"
            else:
                label = {"blue": "СИНЯЯ КОМАНДА", "red": "КРАСНАЯ КОМАНДА"}.get(team.lower(), f"КОМАНДА {team.upper()}")
            color = ALLY if team == local_team or team.lower() == "blue" else ENEMY
            sections.append((label, color, groups[team]))
        return sections

    def _team_panel_columns(self):
        return [
            ("rank", "РАНГ", 2),
            ("rr", "RR", 1),
            ("headshot_percent", "HS%", 1),
            ("winrate", "WR", 2),
            ("kd", "K/D", 1),
            ("level", "LVL", 1),
        ]

    def _team_panel(self, label, color, players, heartbeat, animate=False):
        header = ft.Container(
            padding=ft.padding.only(left=10, right=10, top=8, bottom=6),
            content=ft.Row(
                spacing=3,
                controls=[
                    self._sortable_header("name", "ИГРОК", expand=3),
                    *[
                        self._sortable_header(key, column_label, expand=weight)
                        for key, column_label, weight in self._team_panel_columns()
                    ],
                ],
            ),
        )
        cards = [
            self._team_player_card(player, player.get("puuid") == heartbeat.get("puuid"), color)
            for player in self._sort_players(players)
        ]
        return ft.Container(
            expand=True,
            opacity=0 if animate else 1,
            offset=ft.Offset(0, 0.08) if animate else ft.Offset(0, 0),
            animate_opacity=ft.Animation(280, ft.AnimationCurve.EASE_OUT),
            animate_offset=ft.Animation(280, ft.AnimationCurve.EASE_OUT_CUBIC),
            padding=6,
            border_radius=13,
            bgcolor=ft.Colors.with_opacity(0.54, SURFACE),
            border=ft.border.all(1, ft.Colors.with_opacity(0.30, color)),
            content=ft.Column(
                spacing=5,
                controls=[
                    ft.Row(
                        controls=[
                            ft.Container(width=7, height=7, border_radius=4, bgcolor=color),
                            ft.Text(label, size=12, color=color, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True),
                            self._team_average_badge(players),
                            ft.Text(str(len(players)), size=10, color=MUTED),
                        ],
                    ),
                    header,
                    *cards,
                ],
            ),
        )

    def _team_average_badge(self, players):
        if not self.feature_settings.get("team_average_rank", True):
            return ft.Container(visible=False)
        scores = []
        for player in players:
            try:
                tier = int(player.get("rank") or 0)
                rr = max(0, min(99, int(player.get("rr") or 0)))
            except (TypeError, ValueError):
                continue
            if tier >= 3:
                scores.append(tier * 100 + rr)
        if not scores:
            return ft.Text("AVG Unranked", size=9, color=MUTED)
        average = round(sum(scores) / len(scores))
        tier, rr = divmod(average, 100)
        label, rank_color, _ = _rank_meta(tier)
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=7, vertical=3),
            border_radius=6,
            bgcolor=ft.Colors.with_opacity(0.11, rank_color),
            tooltip=f"Средний ранг по {len(scores)} рейтинговым игрокам",
            content=ft.Text(f"AVG {label}  {rr} RR", size=9, color=rank_color, weight=ft.FontWeight.BOLD),
        )

    def _agent_avatar(self, player, size=30):
        image_url = player.get("agentImgLink")
        fallback = ft.Container(
            width=size,
            height=size,
            border_radius=size / 2,
            bgcolor=SURFACE_ALT,
            alignment=ft.alignment.center,
            content=ft.Icon(ft.Icons.PERSON_ROUNDED, size=size * 0.55, color=MUTED),
        )
        if not image_url:
            return fallback
        return ft.Image(
            src=image_url,
            width=size,
            height=size,
            border_radius=size / 2,
            fit=ft.ImageFit.COVER,
            error_content=fallback,
        )

    def _player_hover(self, event, is_self=False, base_color="#0D1118"):
        hovering = str(event.data).lower() == "true"
        if hovering:
            event.control.bgcolor = "#2A1C23" if is_self else "#181E28"
            event.control.border = ft.border.all(1, ft.Colors.with_opacity(0.72, ACCENT))
        else:
            event.control.bgcolor = "#1B171E" if is_self else base_color
            event.control.border = ft.border.all(1, ft.Colors.with_opacity(0.62, ACCENT) if is_self else BORDER)
        event.control.update()

    def _team_player_card(self, player, is_self, team_color):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=8, vertical=5),
            border_radius=9,
            bgcolor="#1B171E" if is_self else "#0D1118",
            border=ft.border.all(1, ft.Colors.with_opacity(0.62, ACCENT) if is_self else BORDER),
            animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
            ink=True,
            on_hover=lambda event, own=is_self: self._player_hover(event, own),
            on_click=lambda _, selected_player=player: self._show_player_card(selected_player),
            content=ft.Column(
                spacing=4,
                controls=[
                    ft.Row(
                        spacing=3,
                        controls=[
                    ft.Container(
                        expand=3,
                        content=ft.Row(
                            spacing=6,
                            controls=[
                                self._agent_avatar(player, 24),
                                ft.Column(
                                    expand=True,
                                    spacing=1,
                                    controls=[
                                        ft.Row(
                                            spacing=4,
                                            controls=[
                                                ft.Container(
                                                    visible=is_self,
                                                    padding=ft.padding.symmetric(horizontal=4, vertical=1),
                                                    border_radius=4,
                                                    bgcolor=ACCENT,
                                                    content=ft.Text("ВЫ", size=7, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                                                ),
                                                ft.Text(
                                                    player.get("name", "Unknown"),
                                                    expand=True,
                                                    size=13,
                                                    color=TEXT,
                                                    weight=ft.FontWeight.BOLD,
                                                    max_lines=1,
                                                    overflow=ft.TextOverflow.ELLIPSIS,
                                                ),
                                                ft.Container(
                                                    visible=bool(player.get("partyNumber")),
                                                    padding=ft.padding.symmetric(horizontal=4, vertical=1),
                                                    border_radius=4,
                                                    bgcolor=ft.Colors.with_opacity(0.14, ACCENT),
                                                    content=ft.Text(f"P{player.get('partyNumber', '')}", size=7, color=ACCENT, weight=ft.FontWeight.BOLD),
                                                ),
                                                self._encounter_badge(player),
                                            ],
                                        ),
                                        ft.Text("Скрытый ник" if player.get("streamerMode") else player.get("agent", "Agent pending"), size=10, color=team_color),
                                    ],
                                ),
                            ],
                        ),
                    ),
                            *[
                                self._player_cell(key, player, weight)
                                for key, _, weight in self._team_panel_columns()
                            ],
                        ],
                    ),
                    ft.Container(
                        padding=ft.padding.only(top=4),
                        border=ft.border.only(top=ft.BorderSide(1, "#1A202A")),
                        content=ft.Row(
                            spacing=5,
                            controls=[
                                ft.Container(
                                    expand=2,
                                    padding=ft.padding.symmetric(horizontal=4, vertical=2),
                                    border_radius=7,
                                    bgcolor=None,
                                    content=ft.Column(
                                        spacing=3,
                                        controls=[
                                            ft.Text("ПИКОВЫЙ РАНГ", size=8, color=ACCENT if self.sort_key == "peakRank" else MUTED, weight=ft.FontWeight.BOLD),
                                            _secondary_rank_text(player.get("peakRank"), player.get("peakRankAct")),
                                        ],
                                    ),
                                ),
                                *(
                                    [
                                        ft.Container(
                                            expand=2,
                                            padding=ft.padding.symmetric(horizontal=4, vertical=2),
                                            border_radius=7,
                                            bgcolor=None,
                                            content=ft.Column(
                                                spacing=3,
                                                controls=[
                                                    ft.Text("ПРОШЛЫЙ РАНГ", size=8, color=ACCENT if self.sort_key == "previousRank" else MUTED, weight=ft.FontWeight.BOLD),
                                                    _secondary_rank_text(player.get("previousRank")),
                                                ],
                                            ),
                                        )
                                    ]
                                    if self.settings.get("previousrank", False)
                                    else []
                                ),
                                *(
                                    [
                                        ft.Container(
                                            expand=2,
                                            padding=ft.padding.symmetric(horizontal=4, vertical=2),
                                            border_radius=7,
                                            tooltip=player.get("skin", "-"),
                                            content=ft.Column(
                                                spacing=3,
                                                controls=[
                                                    ft.Text("СКИН", size=8, color=ACCENT if self.sort_key == "skin" else MUTED, weight=ft.FontWeight.BOLD),
                                                    ft.Text(
                                                        player.get("skin", "-"),
                                                        size=11,
                                                        color=TEXT,
                                                        weight=ft.FontWeight.W_600,
                                                        max_lines=1,
                                                        overflow=ft.TextOverflow.ELLIPSIS,
                                                    ),
                                                ],
                                            ),
                                        )
                                    ]
                                    if self.settings.get("skin", True)
                                    else []
                                ),
                            ],
                        ),
                    ),
                ],
            ),
        )

    def _visible_columns(self):
        columns = [
            ("rank", "РАНГ", 2),
            ("skin", "СКИН", 2),
            ("rr", "RR", 1),
            ("peakrank", "ПИКОВЫЙ РАНГ", 2),
            ("previousrank", "ПРОШЛЫЙ РАНГ", 2),
            ("leaderboard", "ПОЗ.", 1),
            ("headshot_percent", "HS%", 1),
            ("winrate", "WR", 2),
            ("kd", "K/D", 1),
            ("level", "УРОВЕНЬ", 1),
            ("earned_rr", "ΔRR", 1),
        ]
        return [column for column in columns if column[0] == "rank" or self.settings.get(column[0], True)]

    def _sortable_header(self, key, label, expand=None, width=None):
        sort_fields = {
            "name": "name",
            "rank": "rank",
            "skin": "skin",
            "rr": "rr",
            "peakrank": "peakRank",
            "previousrank": "previousRank",
            "leaderboard": "leaderboard",
            "headshot_percent": "headshotPercentage",
            "winrate": "winPercentage",
            "kd": "kd",
            "level": "level",
            "earned_rr": "earnedRR",
        }
        sortable = key == "rank"
        active = sortable and self.sort_key == sort_fields[key]
        return ft.Container(
            expand=expand,
            width=width,
            padding=ft.padding.symmetric(horizontal=4, vertical=3),
            border_radius=5,
            bgcolor=ft.Colors.with_opacity(0.12, ACCENT) if active else None,
            tooltip=f"Сортировать: {label}" if sortable else None,
            on_click=(lambda _, column_key=key: self._set_sort(column_key)) if sortable else None,
            content=ft.Row(
                spacing=2,
                controls=[
                    ft.Text(label, size=10, color=ACCENT if active else MUTED, weight=ft.FontWeight.BOLD, no_wrap=True),
                    ft.Icon(
                        ft.Icons.SOUTH_ROUNDED if self.sort_descending else ft.Icons.NORTH_ROUNDED,
                        size=12,
                        color=ACCENT,
                        visible=active,
                    ),
                ],
            ),
        )

    def _player_table_header(self):
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=14, vertical=8),
            border_radius=8,
            bgcolor="#0D1118",
            border=ft.border.only(bottom=ft.BorderSide(1, BORDER)),
            content=ft.Row(
                spacing=4,
                controls=[
                    ft.Container(width=3),
                    self._sortable_header("name", "ИГРОК", width=210),
                    *[
                        self._sortable_header(key, label, expand=weight)
                        for key, label, weight in self._visible_columns()
                    ],
                ],
            ),
        )

    def _player_cell(self, key, player, weight):
        if key == "rank":
            content = _rank_badge(player.get("rank"))
        elif key == "peakrank":
            content = _rank_badge(player.get("peakRank"), player.get("peakRankAct"))
        elif key == "previousrank":
            content = _rank_badge(player.get("previousRank"))
        else:
            earned_rr = player.get("earnedRR", "-")
            afk_penalty = player.get("afkPenalty", 0)
            try:
                earned_number = int(earned_rr)
                earned_rr = f"+{earned_number}" if earned_number > 0 else str(earned_number)
                if int(afk_penalty):
                    earned_rr = f"{earned_rr} ({afk_penalty})"
            except (TypeError, ValueError):
                earned_number = 0
            values = {
                "skin": player.get("skin", "-"),
                "rr": player.get("rr", 0),
                "leaderboard": f"#{player.get('leaderboard')}" if str(player.get("leaderboard", "0")) not in {"", "0", "None"} else "-",
                "headshot_percent": f"{player.get('headshotPercentage', '-')}%",
                "winrate": player.get("winPercentage", "-"),
                "kd": player.get("kd", "-"),
                "level": player.get("level", "-"),
                "earned_rr": earned_rr,
            }
            value = str(values.get(key, "-"))
            if key == "earned_rr":
                color = "#4BC487" if earned_number > 0 else ENEMY if earned_number < 0 else MUTED
            else:
                color = ACCENT if key == "rr" else TEXT if key == "skin" else MUTED
            content = ft.Text(
                value,
                size=11 if key == "skin" else 12,
                color=color,
                weight=ft.FontWeight.W_600,
                max_lines=1,
                overflow=ft.TextOverflow.ELLIPSIS,
                tooltip=value if key == "skin" else None,
            )
            heat_color = self._heat_color(key, player)
            if heat_color:
                content = ft.Container(
                    padding=ft.padding.symmetric(horizontal=6, vertical=4),
                    border_radius=6,
                    bgcolor=ft.Colors.with_opacity(0.13, heat_color),
                    border=ft.border.all(1, ft.Colors.with_opacity(0.24, heat_color)),
                    content=content,
                )
        return ft.Container(expand=weight, alignment=ft.alignment.center_left, content=content)

    def _heat_color(self, key, player):
        if key == "earned_rr":
            value = player.get("earnedRR")
            thresholds = (1, 0)
        elif key == "rr":
            value = player.get("rr")
            thresholds = (70, 30)
        elif key == "headshot_percent":
            value = player.get("headshotPercentage")
            thresholds = (28, 18)
        elif key == "winrate":
            value = str(player.get("winPercentage", "")).split(" ", 1)[0]
            thresholds = (53, 47)
        elif key == "kd":
            value = player.get("kd")
            thresholds = (1.15, 0.9)
        else:
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        if number >= thresholds[0]:
            return "#4BC487"
        if number >= thresholds[1]:
            return "#E6C24F"
        return ENEMY

    def _detail_metric(self, label, value, color=TEXT):
        return ft.Container(
            col={"xs": 6, "md": 4},
            padding=12,
            border_radius=10,
            bgcolor="#0D1118",
            border=ft.border.all(1, BORDER),
            content=ft.Column(
                spacing=3,
                controls=[
                    ft.Text(label.upper(), size=9, color=MUTED, weight=ft.FontWeight.BOLD),
                    ft.Text(str(value), size=15, color=color, weight=ft.FontWeight.BOLD),
                ],
            ),
        )

    def _card_rank_badge(self, tier, icon_url, suffix=None):
        if self.settings.get("rank_icon_style", "official") == "official" and icon_url:
            return _official_rank_badge(tier, icon_url, suffix)
        return _rank_badge(tier, suffix)

    def _player_inventory_view(self, player):
        weapons = [
            weapon for weapon in (player.get("weapons") or {}).values()
            if weapon.get("weapon")
        ]
        if not weapons:
            return ft.Text("Инвентарь недоступен для этого состояния игры.", size=12, color=MUTED)
        return ft.Column(
            spacing=7,
            controls=[
                ft.Container(
                    padding=ft.padding.symmetric(horizontal=8, vertical=6),
                    border_radius=7,
                    bgcolor="#0D1118",
                    content=ft.Row(
                        controls=[
                            ft.Image(
                                src=weapon.get("skinDisplayIcon"),
                                width=82,
                                height=42,
                                fit=ft.ImageFit.CONTAIN,
                            ) if weapon.get("skinDisplayIcon") else ft.Icon(ft.Icons.HIDE_IMAGE_ROUNDED, color=MUTED),
                            ft.Column(
                                expand=True,
                                spacing=1,
                                controls=[
                                    ft.Text(weapon.get("weapon", "Weapon").upper(), size=9, color=ACCENT, weight=ft.FontWeight.BOLD),
                                    ft.Text(weapon.get("skinDisplayName", "Standard"), size=12, color=TEXT, weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ],
                            ),
                        ],
                    ),
                )
                for weapon in weapons
            ],
        )

    def _toggle_player_inventory(self, _):
        self.player_inventory_open = not self.player_inventory_open
        self.player_inventory_button.text = "Скрыть все скины" if self.player_inventory_open else "Показать все скины"
        self.player_inventory_container.visible = self.player_inventory_open
        try:
            self.player_inventory_button.update()
            self.player_inventory_container.update()
        except AssertionError:
            pass

    def _open_vtl_profile(self, _):
        puuid = self.selected_player.get("puuid") if self.selected_player else None
        if puuid:
            self.page.launch_url(f"https://vtl.lol/id/{quote(str(puuid), safe='')}")

    def _open_tracker_profile(self, _):
        if not self.selected_player or self.selected_player.get("streamerMode"):
            return
        riot_id = str(self.selected_player.get("name") or "")
        if "#" in riot_id:
            self.page.launch_url(
                f"https://tracker.gg/valorant/profile/riot/{quote(riot_id, safe='')}/overview"
            )

    def _show_player_card(self, player):
        self.player_panel_open = True
        self.selected_player = player
        self.player_inventory_open = False
        dialog = ft.AlertDialog(
            modal=True,
            bgcolor=SURFACE,
            surface_tint_color=SURFACE,
            inset_padding=24,
            content_padding=20,
            shape=ft.RoundedRectangleBorder(radius=16),
            content=ft.Container(
                width=414,
                content=ft.Column(
                    tight=True,
                    spacing=16,
                    controls=[
                        ft.Row(
                            controls=[
                                ft.Image(src=player.get("agentImgLink"), width=64, height=64, border_radius=14, fit=ft.ImageFit.COVER)
                                if player.get("agentImgLink")
                                else ft.Container(width=64, height=64, border_radius=14, bgcolor=SURFACE_ALT, alignment=ft.alignment.center, content=ft.Icon(ft.Icons.PERSON_ROUNDED, size=30, color=MUTED)),
                                ft.Column(
                                    expand=True,
                                    spacing=3,
                                    controls=[
                                        ft.Text(player.get("name", "Unknown"), size=24, color=TEXT, weight=ft.FontWeight.BOLD),
                                        ft.Text(
                                            f"{'Скрытый ник  /  ' if player.get('streamerMode') else ''}{player.get('agent', 'Unknown agent')}  /  LEVEL {player.get('level', '-')}",
                                            size=12,
                                            color=MUTED,
                                        ),
                                    ],
                                ),
                                ft.IconButton(icon=ft.Icons.CLOSE_ROUNDED, icon_color=MUTED, on_click=self._close_player_panel),
                            ],
                        ),
                        ft.Row(
                            spacing=18,
                            controls=[
                                ft.Column(spacing=4, controls=[ft.Text("ТЕКУЩИЙ", size=8, color=MUTED), self._card_rank_badge(player.get("rank"), player.get("rankIcon"))]),
                                ft.Column(spacing=4, controls=[ft.Text("ПИКОВЫЙ", size=8, color=MUTED), self._card_rank_badge(player.get("peakRank"), player.get("peakRankIcon"), player.get("peakRankAct"))]),
                                ft.Column(spacing=4, controls=[ft.Text("ПРОШЛЫЙ", size=8, color=MUTED), self._card_rank_badge(player.get("previousRank"), player.get("previousRankIcon"))]),
                            ],
                        ),
                        ft.ResponsiveRow(
                            spacing=9,
                            run_spacing=9,
                            controls=[
                                self._detail_metric("RR", player.get("rr", "-"), ACCENT),
                                self._detail_metric("HS%", f"{player.get('headshotPercentage', '-')}%", self._heat_color("headshot_percent", player) or TEXT),
                                self._detail_metric("Win rate", player.get("winPercentage", "-"), self._heat_color("winrate", player) or TEXT),
                                self._detail_metric("K/D", player.get("kd", "-"), self._heat_color("kd", player) or TEXT),
                                self._detail_metric("Leaderboard", f"#{player.get('leaderboard')}" if player.get("leaderboard") else "-"),
                                self._detail_metric("ΔRR", player.get("earnedRR", "-"), self._heat_color("earned_rr", player) or TEXT),
                            ],
                        ),
                        ft.Container(
                            padding=12,
                            border_radius=10,
                            bgcolor="#0D1118",
                            border=ft.border.all(1, BORDER),
                            content=ft.Row(
                                controls=[
                                    ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, color=ACCENT, size=20),
                                    ft.Column(
                                        spacing=2,
                                        controls=[
                                            ft.Text("ВЫБРАННЫЙ СКИН", size=8, color=MUTED, weight=ft.FontWeight.BOLD),
                                            ft.Text(player.get("skin", "Не определён"), size=13, color=TEXT, weight=ft.FontWeight.W_600),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                    ],
                ),
            ),
        )
        details = dialog.content
        self.player_inventory_button = ft.ElevatedButton(
            text="Показать все скины",
            icon=ft.Icons.AUTO_AWESOME_ROUNDED,
            style=self._primary_button_style(),
            on_click=self._toggle_player_inventory,
        )
        self.player_inventory_container = ft.Container(
            visible=False,
            padding=ft.padding.only(top=4),
            content=self._player_inventory_view(player),
        )
        tracker_available = not player.get("streamerMode") and "#" in str(player.get("name") or "")
        external_actions = ft.Row(
            spacing=6,
            wrap=True,
            controls=[
                self.player_inventory_button,
                ft.OutlinedButton(
                    text="VTL.LOL",
                    icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                    style=self._secondary_button_style(),
                    tooltip="Открыть профиль VTL.LOL",
                    on_click=self._open_vtl_profile,
                ),
                ft.OutlinedButton(
                    text="Tracker.gg",
                    icon=ft.Icons.OPEN_IN_NEW_ROUNDED,
                    style=self._secondary_button_style(),
                    disabled=not tracker_available,
                    tooltip="Открыть Tracker.gg" if tracker_available else "Riot ID скрыт режимом конфиденциальности",
                    on_click=self._open_tracker_profile,
                ),
                ft.OutlinedButton(
                    text="Скопировать ник",
                    icon=ft.Icons.CONTENT_COPY_ROUNDED,
                    style=self._secondary_button_style(),
                    disabled=player.get("streamerMode") or "#" not in str(player.get("name") or ""),
                    on_click=lambda event: self._copy_riot_id(player, event.control),
                ),
            ],
        )
        details.content.controls.extend([
            external_actions,
            self.player_inventory_container,
        ])
        details.width = None
        details.expand = True
        details.content.tight = False
        details.content.expand = True
        details.content.scroll = ft.ScrollMode.HIDDEN
        self.player_panel.width = 450
        self.player_panel.content = details
        self.player_panel.right = 0
        self.player_scrim.visible = True
        try:
            self.player_panel.update()
            self.player_scrim.update()
        except AssertionError:
            pass
        self.page.run_task(self._restore_scroll, "match")

    def _close_player_panel(self, _=None, update=True):
        self.player_panel_open = False
        self.player_panel.right = -(self.player_panel.width + 20)
        self.player_scrim.visible = False
        if update:
            try:
                self.player_panel.update()
                self.player_scrim.update()
            except AssertionError:
                pass
            scroll_id = {0: "match", 1: "history"}.get(self.selected_view)
            if scroll_id:
                self.page.run_task(self._restore_scroll, scroll_id)

    def _player_row(self, player, is_self=False, compact=False):
        team = str(player.get("team") or "")
        team_color = ALLY if team.lower() == "blue" else ENEMY if team else MUTED
        return ft.Container(
            padding=ft.padding.symmetric(horizontal=10 if compact else 14, vertical=3 if compact else 8),
            border_radius=8 if compact else 10,
            bgcolor="#1B171E" if is_self else SURFACE,
            border=ft.border.all(1, ft.Colors.with_opacity(0.58, ACCENT) if is_self else BORDER),
            animate=ft.Animation(140, ft.AnimationCurve.EASE_OUT),
            ink=True,
            on_click=lambda _, selected_player=player: self._show_player_card(selected_player),
            content=ft.Row(
                spacing=4,
                controls=[
                    ft.Container(width=3, height=26 if compact else 38, border_radius=2, bgcolor=ACCENT if is_self else team_color),
                    ft.Container(
                        width=210,
                        content=ft.Row(
                            spacing=5 if compact else 7,
                            controls=[
                                self._agent_avatar(player, 24 if compact else 34),
                                ft.Column(
                                    expand=True,
                                    spacing=2,
                                    controls=[
                                        ft.Row(
                                            spacing=5,
                                            controls=[
                                                ft.Container(
                                                    visible=is_self,
                                                    padding=ft.padding.symmetric(horizontal=5, vertical=1),
                                                    border_radius=5,
                                                    bgcolor=ACCENT,
                                                    content=ft.Text("ВЫ", size=7, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                                                ),
                                                ft.Text(
                                                    player.get("name", "Unknown"),
                                                    expand=True,
                                                    size=13 if compact else 15,
                                                    color=TEXT,
                                                    weight=ft.FontWeight.BOLD,
                                                    max_lines=1,
                                                    overflow=ft.TextOverflow.ELLIPSIS,
                                                    tooltip=player.get("name", "Unknown"),
                                                ),
                                                ft.Container(
                                                    visible=bool(player.get("partyNumber")),
                                                    padding=ft.padding.symmetric(horizontal=5, vertical=1),
                                                    border_radius=5,
                                                    bgcolor=ft.Colors.with_opacity(0.14, ACCENT),
                                                    content=ft.Text(f"P{player.get('partyNumber', '')}", size=7, color=ACCENT, weight=ft.FontWeight.BOLD),
                                                ),
                                                self._encounter_badge(player),
                                            ],
                                        ),
                                        ft.Text("Скрытый ник" if player.get("streamerMode") else player.get("agent", "Agent pending"), size=10 if compact else 12, color=MUTED),
                                    ],
                                ),
                            ],
                        ),
                    ),
                    *[self._player_cell(key, player, weight) for key, _, weight in self._visible_columns()],
                ],
            ),
        )

    def _skins_view(self):
        loadouts = self.snapshot.get("loadouts") or {}
        players = loadouts.get("Players") or {}
        if not players:
            return self._waiting_view(
                "LOCAL INVENTORY",
                "Скины игроков",
                "Инвентари загружаются из Riot API и остаются внутри приложения.",
                ft.Icons.AUTO_AWESOME_ROUNDED,
                "Скины ещё не загружены",
                "Откройте матч. Инвентари игроков будут показаны здесь локально, без внешнего сайта.",
            )

        body = []
        for label, color, section_players in self._skin_sections(players):
            body.append(
                ft.Container(
                    margin=ft.margin.only(top=5),
                    content=ft.Row(
                        controls=[
                            ft.Text(label, size=10, color=color, weight=ft.FontWeight.BOLD),
                            ft.Container(expand=True, height=1, bgcolor=BORDER),
                            ft.Text(str(len(section_players)), size=10, color=MUTED),
                        ]
                    ),
                )
            )
            body.extend(self._skin_player_card(player_id, player) for player_id, player in section_players)

        return ft.Column(
            expand=True,
            alignment=ft.MainAxisAlignment.START,
            spacing=14,
            controls=[
                self._header("LOCAL INVENTORY", "Скины игроков", "Нажмите на игрока, чтобы развернуть его инвентарь."),
                ft.Column(expand=True, scroll=ft.ScrollMode.HIDDEN, spacing=9, controls=body),
            ],
        )

    def _skin_sections(self, players):
        player_items = list(players.items())
        heartbeat = self.snapshot.get("heartbeat") or {}
        mode = str(heartbeat.get("mode") or "").strip().lower()
        if mode in {"deathmatch", "death match"}:
            return [("ИГРОКИ", MUTED, player_items)]

        groups = {}
        for player_id, player in player_items:
            team = str(player.get("Team") or "").strip()
            groups.setdefault(team, []).append((player_id, player))
        populated_teams = [team for team in groups if team]
        if len(populated_teams) <= 1:
            return [("СОСТАВ", ALLY if populated_teams else MUTED, player_items)]

        local_puuid = heartbeat.get("puuid")
        local_team = str((heartbeat.get("players") or {}).get(local_puuid, {}).get("team") or "")
        ordered_teams = sorted(populated_teams, key=lambda team: team != local_team)
        sections = []
        for team in ordered_teams:
            if local_team:
                label = "ВАША КОМАНДА" if team == local_team else "ПРОТИВНИКИ"
            else:
                label = {"blue": "СИНЯЯ КОМАНДА", "red": "КРАСНАЯ КОМАНДА"}.get(team.lower(), f"КОМАНДА {team.upper()}")
            color = ALLY if team == local_team or team.lower() == "blue" else ENEMY
            sections.append((label, color, groups[team]))
        return sections

    def toggle_player(self, player_id):
        if player_id in self.expanded_players:
            self.expanded_players.remove(player_id)
        else:
            self.expanded_players.add(player_id)
        self.render()

    def _skin_player_card(self, player_id, player):
        expanded = player_id in self.expanded_players
        is_self = player_id == (self.snapshot.get("heartbeat") or {}).get("puuid")
        weapons = [weapon for weapon in (player.get("Weapons") or {}).values() if weapon.get("weapon")]
        weapon_controls = []
        for weapon in weapons:
            image = weapon.get("skinDisplayIcon")
            weapon_controls.append(
                ft.Container(
                    col={"xs": 12, "md": 6, "xl": 4},
                    height=78,
                    padding=8,
                    border_radius=10,
                    bgcolor="#0D1118",
                    border=ft.border.all(1, "#1C2330"),
                    content=ft.Row(
                        controls=[
                            ft.Image(src=image, width=100, height=54, fit=ft.ImageFit.CONTAIN) if image else ft.Icon(ft.Icons.HIDE_IMAGE_ROUNDED, color=MUTED),
                            ft.Column(
                                expand=True,
                                alignment=ft.MainAxisAlignment.CENTER,
                                spacing=2,
                                controls=[
                                    ft.Text(weapon.get("weapon", "Weapon").upper(), size=8, color=ACCENT, weight=ft.FontWeight.BOLD),
                                    ft.Text(weapon.get("skinDisplayName", "Standard"), size=13, color=TEXT, weight=ft.FontWeight.W_600, max_lines=2),
                                ],
                            ),
                        ],
                    ),
                )
            )

        header = ft.Container(
            height=54,
            padding=ft.padding.symmetric(horizontal=12),
            border_radius=10,
            on_click=lambda _, value=player_id: self.toggle_player(value),
            content=ft.Row(
                controls=[
                    ft.Image(src=player.get("Agent"), width=34, height=34, border_radius=17, fit=ft.ImageFit.COVER) if player.get("Agent") else ft.Icon(ft.Icons.PERSON_ROUNDED, color=MUTED),
                    ft.Column(
                        expand=True,
                        spacing=0,
                        alignment=ft.MainAxisAlignment.CENTER,
                        controls=[
                            ft.Row(
                                spacing=5,
                                controls=[
                                    ft.Text(player.get("Name", "Unknown player"), size=15, color=TEXT, weight=ft.FontWeight.BOLD),
                                    ft.Container(
                                        visible=is_self,
                                        padding=ft.padding.symmetric(horizontal=5, vertical=1),
                                        border_radius=5,
                                        bgcolor=ACCENT,
                                        content=ft.Text("ВЫ", size=7, color="#FFFFFF", weight=ft.FontWeight.BOLD),
                                    ),
                                ],
                            ),
                            ft.Text(f"LEVEL {player.get('Level', '-')}  /  {player.get('Team', 'TEAM')}", size=9, color=MUTED),
                        ],
                    ),
                    ft.Text(f"{len(weapons)} СКИНОВ", size=9, color=MUTED, weight=ft.FontWeight.W_600),
                    ft.Icon(ft.Icons.KEYBOARD_ARROW_UP_ROUNDED if expanded else ft.Icons.KEYBOARD_ARROW_DOWN_ROUNDED, size=20, color=ACCENT),
                ],
            ),
        )
        controls = [header]
        if expanded:
            controls.append(
                ft.Container(
                    padding=ft.padding.only(left=12, right=12, bottom=12),
                    content=ft.ResponsiveRow(
                        spacing=9,
                        run_spacing=9,
                        controls=weapon_controls or [ft.Text("Инвентарь пуст", size=11, color=MUTED)],
                    ),
                )
            )

        return ft.Container(
            border_radius=12,
            bgcolor="#1B171E" if is_self else SURFACE,
            border=ft.border.all(1, ACCENT if is_self else ("#3A2730" if expanded else BORDER)),
            animate=ft.Animation(160, ft.AnimationCurve.EASE_OUT),
            content=ft.Column(
                spacing=0,
                controls=controls,
            ),
        )


def main(page):
    ValorantApp(page).build()


def run_gui():
    ft.app(target=main)
