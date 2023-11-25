# window.py
#
# Copyright 2023 kramo
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# SPDX-License-Identifier: GPL-3.0-or-later

from os import sep
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

from gi.repository import Adw, Gio, Gtk

from hyperplane import shared
from hyperplane.items_page import HypItemsPage
from hyperplane.navigation_bin import HypNavigationBin

# This is to avoid a circular import in item.py
from hyperplane.thumbnail import HypThumb  # pylint: disable=unused-import


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/window.ui")
class HypWindow(Adw.ApplicationWindow):
    __gtype_name__ = "HypWindow"

    toast_overlay: Adw.ToastOverlay = Gtk.Template.Child()
    tab_view: Adw.TabView = Gtk.Template.Child()
    toolbar_view: Adw.ToolbarView = Gtk.Template.Child()

    title_stack: Gtk.Stack = Gtk.Template.Child()
    window_title: Adw.WindowTitle = Gtk.Template.Child()
    path_bar_clamp: Adw.Clamp = Gtk.Template.Child()
    path_bar: Gtk.Entry = Gtk.Template.Child()
    search_entry_clamp: Adw.Clamp = Gtk.Template.Child()
    search_entry: Gtk.SearchEntry = Gtk.Template.Child()
    search_button: Gtk.ToggleButton = Gtk.Template.Child()

    rename_popover: Gtk.Popover = Gtk.Template.Child()
    rename_label: Gtk.Label = Gtk.Template.Child()
    rename_entry: Adw.EntryRow = Gtk.Template.Child()
    rename_revealer: Gtk.Revealer = Gtk.Template.Child()
    rename_revealer_label: Gtk.Label = Gtk.Template.Child()
    rename_button: Gtk.Button = Gtk.Template.Child()

    path_bar_connection: int

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)

        if shared.PROFILE == "development":
            self.add_css_class("devel")

        self.tab_view.connect("page-attached", self.__page_attached)

        navigation_view = HypNavigationBin(initial_path=shared.home)
        self.tab_view.append(navigation_view).set_title(
            title := self.get_visible_page().get_title()
        )
        self.set_title(title)

        self.create_action("home", self.__go_home, ("<alt>Home",))
        self.create_action(
            "toggle-path-bar", self.__toggle_path_bar, ("F6", "<primary>l")
        )
        self.create_action("close", self.__on_close_action, ("<primary>w",))
        self.create_action("back", self.__on_back_action)
        self.lookup_action("back").set_enabled(False)
        self.create_action(
            "zoom-in",
            self.__on_zoom_in_action,
            ("<primary>plus", "<Primary>KP_Add", "<primary>equal"),
        )
        self.create_action(
            "zoom-out",
            self.__on_zoom_out_action,
            ("<primary>minus", "<Primary>KP_Subtract", "<Primary>underscore"),
        )

        self.tab_view.connect("notify::selected-page", self.__tab_changed)
        self.tab_view.connect("create-window", self.__create_window)

        self.path_bar.connect("activate", self.__path_bar_activated)

        self.search_entry.set_key_capture_widget(self)
        self.search_entry.connect("search-started", self.__show_search_entry)
        self.search_entry.connect("search-changed", self.__search_changed)
        self.search_entry.connect("stop-search", self.__hide_search_entry)
        self.search_entry.connect("activate", self.__search_activate)
        self.search_button.connect("clicked", self.__search_button_clicked)
        self.searched_page = self.get_visible_page()

    def send_toast(self, message: str) -> None:
        """Displays a toast with the given message in the window."""
        toast = Adw.Toast.new(message)
        toast.set_priority(Adw.ToastPriority.HIGH)
        toast.set_use_markup(False)

        self.toast_overlay.add_toast(toast)

    def new_tab(self, path: Optional[Path] = None, tag: Optional[str] = None) -> None:
        """Open a new path with the given path or tag."""
        if path and path.is_dir():
            navigation_view = HypNavigationBin(initial_path=path)
            self.tab_view.append(navigation_view).set_title(
                navigation_view.view.get_visible_page().get_title()
            )
        elif tag:
            navigation_view = HypNavigationBin(
                initial_tags=self.tab_view.get_selected_page().get_child().tags + [tag]
            )
            self.tab_view.append(navigation_view).set_title(
                navigation_view.view.get_visible_page().get_title()
            )

    def get_visible_page(self) -> HypItemsPage:
        """Return the currently visible HypItemsPage."""
        return self.tab_view.get_selected_page().get_child().view.get_visible_page()

    def update_zoom(self) -> None:
        """Update the zoom level of all items in the navigation stack"""
        shared.postmaster.emit("zoom", shared.state_schema.get_uint("zoom-level"))

    def create_action(
        self, name: str, callback: Callable, shortcuts: Optional[Iterable] = None
    ) -> None:
        """Add an application action.

        Args:
            name: the name of the action
            callback: the function to be called when the action is
              activated
            shortcuts: an optional list of accelerators
        """
        action = Gio.SimpleAction.new(name, None)
        action.connect("activate", callback)
        self.add_action(action)
        if shortcuts:
            self.get_application().set_accels_for_action(f"win.{name}", shortcuts)

    def __tab_changed(self, *_args: Any) -> None:
        if not self.tab_view.get_selected_page():
            return

        self.set_title(self.get_visible_page().get_title())
        self.lookup_action("back").set_enabled(
            bool(
                self.tab_view.get_selected_page()
                .get_child()
                .view.get_navigation_stack()
                .get_n_items()
                - 1
            )
        )

    def __navigation_changed(self, view: Adw.NavigationView, *_args: Any) -> None:
        self.__hide_search_entry()
        view.get_visible_page().flow_box.invalidate_filter()

        title = view.get_visible_page().get_title()
        if page := self.tab_view.get_page(view.get_parent()):
            page.set_title(title)

        if self.tab_view.get_selected_page() == page:
            self.set_title(title)

        self.lookup_action("back").set_enabled(
            bool(
                self.tab_view.get_selected_page()
                .get_child()
                .view.get_navigation_stack()
                .get_n_items()
                - 1
            )
        )

    def __page_attached(self, _view: Adw.TabView, page: Adw.TabPage, _pos: int) -> None:
        page.get_child().view.connect("popped", self.__navigation_changed)
        page.get_child().view.connect("pushed", self.__navigation_changed)

    def __path_bar_activated(self, entry, *_args: Any) -> None:
        text = entry.get_text().strip()
        nav_bin = self.tab_view.get_selected_page().get_child()

        if text.startswith("//"):
            self.__hide_path_bar()
            tags = list(
                tag
                for tag in shared.tags
                if tag in text.lstrip("/").rstrip("/").split("//")
            )
            if not tags:
                self.send_toast(_("No such tags"))
            if tags == self.get_visible_page().tags:
                return
            nav_bin.new_page(tags=tags)
            return

        if (path := Path(text)).is_dir():
            self.__hide_path_bar()
            if path == self.get_visible_page().path:
                return
            nav_bin.new_page(path)
            return

        self.send_toast(_("Unable to find path"))

    def __toggle_search_entry(self, *_args: Any) -> None:
        if self.title_stack.get_visible_child() != self.search_entry_clamp:
            self.__show_search_entry()
            return

        self.__hide_search_entry()

    def __show_search_entry(self, *_args: Any) -> None:
        self.search_button.set_active(True)
        if self.title_stack.get_visible_child() == self.search_entry_clamp:
            return

        self.searched_page = self.get_visible_page()

        self.title_stack.set_visible_child(self.search_entry_clamp)
        self.set_focus(self.search_entry)

    def __hide_search_entry(self, *_args: Any) -> None:
        self.search_button.set_active(False)
        if self.title_stack.get_visible_child() != self.search_entry_clamp:
            return

        self.title_stack.set_visible_child(self.window_title)
        self.search_entry.set_text("")
        shared.search = ""
        self.searched_page.flow_box.invalidate_filter()

        try:
            self.set_focus(self.get_visible_page().flow_box.get_selected_children()[0])
        except IndexError:
            pass

    def __search_activate(self, *_args: Any) -> None:
        try:
            self.get_visible_page().flow_box.get_selected_children()[0].activate()
        except IndexError:
            pass

    def __search_changed(self, entry: Gtk.SearchEntry) -> None:
        shared.search = entry.get_text().strip()
        self.searched_page.flow_box.invalidate_filter()

    def __search_button_clicked(self, *_args: Any) -> None:
        self.__toggle_search_entry()

    def __show_path_bar(self, *_args: Any) -> None:
        if (page := self.get_visible_page()).path:
            self.path_bar.set_text(str(page.path) + sep)
        elif page.tags:
            self.path_bar.set_text("//" + "//".join(page.tags) + "//")

        self.title_stack.set_visible_child(self.path_bar_clamp)
        self.set_focus(self.path_bar)
        self.path_bar.select_region(-1, -1)

        self.path_bar_connection = self.path_bar.connect(
            "notify::has-focus", self.__path_bar_focus
        )

    def __hide_path_bar(self, *_args: Any) -> None:
        self.title_stack.set_visible_child(self.window_title)
        try:
            self.set_focus(self.get_visible_page().flow_box.get_selected_children()[0])
        except IndexError:
            pass

        if self.path_bar_connection:
            self.path_bar.disconnect(self.path_bar_connection)
            self.path_bar_connection = None

    def __toggle_path_bar(self, *_args: Any) -> None:
        if self.title_stack.get_visible_child() != self.path_bar_clamp:
            self.__show_path_bar()
            return

        self.__hide_path_bar()

    def __path_bar_focus(self, entry: Gtk.Entry, *_args: Any) -> None:
        if not entry.has_focus():
            self.__hide_path_bar()

    def __go_home(self, *_args: Any) -> None:
        self.tab_view.get_selected_page().get_child().new_page(shared.home)

    def __on_zoom_in_action(self, *_args: Any) -> None:
        if (zoom_level := shared.state_schema.get_uint("zoom-level")) > 4:
            return

        shared.state_schema.set_uint("zoom-level", zoom_level + 1)
        self.update_zoom()

    def __on_zoom_out_action(self, *_args: Any) -> None:
        if (zoom_level := shared.state_schema.get_uint("zoom-level")) < 2:
            return

        shared.state_schema.set_uint("zoom-level", zoom_level - 1)
        self.update_zoom()

    def __on_close_action(self, *_args: Any) -> None:
        if self.tab_view.get_n_pages() > 1:
            self.tab_view.close_page(self.tab_view.get_selected_page())
        else:
            self.close()

    def __on_back_action(self, *_args: Any) -> None:
        self.tab_view.get_selected_page().get_child().view.pop()

    def __create_window(self, *_args: Any) -> Adw.TabView:
        win = self.get_application().do_activate()

        # Close the initial Home tab
        win.tab_view.close_page(win.tab_view.get_selected_page())
        return win.tab_view
