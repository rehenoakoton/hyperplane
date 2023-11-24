# items_page.py
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

from locale import strcoll
from pathlib import Path
from typing import Any, Iterable, Optional

from gi.repository import Adw, Gdk, Gio, Gtk

from hyperplane import shared
from hyperplane.item import HypItem
from hyperplane.tag import HypTag
from hyperplane.utils.iterplane import iterplane


@Gtk.Template(resource_path=shared.PREFIX + "/gtk/items-page.ui")
class HypItemsPage(Adw.NavigationPage):
    __gtype_name__ = "HypItemsPage"

    flow_box: Gtk.FlowBox = Gtk.Template.Child()
    empty_folder: Adw.StatusPage = Gtk.Template.Child()
    empty_filter: Adw.StatusPage = Gtk.Template.Child()
    scrolled_window: Gtk.ScrolledWindow = Gtk.Template.Child()
    right_click_menu: Gtk.PopoverMenu = Gtk.Template.Child()

    def __init__(
        self,
        path: Optional[Path] = None,
        tags: Optional[list[str]] = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.path = path
        self.tags = tags

        if self.path and not self.path.is_dir():
            return

        if self.path == shared.home:
            self.set_title(_("Home"))
        elif self.path:
            self.set_title(self.path.name)
        elif self.tags:
            self.set_title(" + ".join(self.tags))

        self.update()

        self.flow_box.connect("child-activated", self.__child_activated)
        self.flow_box.set_sort_func(self.__sort_func)
        self.flow_box.set_filter_func(self.__filter_func)

        self.right_click_menu.set_parent(self)
        gesture_click = Gtk.GestureClick(button=Gdk.BUTTON_SECONDARY)
        gesture_click.connect("pressed", self.__right_click)
        self.add_controller(gesture_click)
        self.right_click_menu.connect("closed", self.__set_actions)

        shared.postmaster.connect("toggle-hidden", self.__toggle_hidden)

    def update(self) -> None:
        """Updates the visible items in the view."""

        if self.get_child() != self.scrolled_window:
            self.set_child(self.scrolled_window)

        self.flow_box.remove_all()
        if self.path:
            if self.path == shared.home:
                for item in self.path.iterdir():
                    if item.name not in shared.tags:
                        self.flow_box.append(HypItem(item))
                for tag in shared.tags:
                    self.flow_box.append(HypTag(tag))
                return

            for item in self.path.iterdir():
                self.flow_box.append(HypItem(item))

            if "item" not in vars():
                self.set_child(self.empty_folder)

        elif self.tags:
            for item in iterplane(self.tags):
                if isinstance(item, Path):
                    self.flow_box.append(HypItem(item))
                elif isinstance(item, str):
                    self.flow_box.append(HypTag(item))

            if "item" not in vars():
                self.set_child(self.empty_filter)

    def __toggle_hidden(self, *_args: Any) -> None:
        self.flow_box.invalidate_filter()

    def __sort_func(self, child1: Gtk.FlowBoxChild, child2: Gtk.FlowBoxChild) -> int:
        child1 = child1.get_child()
        child2 = child2.get_child()

        if isinstance(child1, HypItem):
            if isinstance(child2, HypItem):
                return strcoll(child1.path.name, child2.path.name)
            return 1
        if isinstance(child2, HypItem):
            return -1
        return strcoll(child1.name, child2.name)

    def __filter_func(self, child: Gtk.FlowBoxChild) -> bool:
        if shared.show_hidden:
            return True

        child = child.get_child()

        if isinstance(child, HypTag):
            return True

        if child.gfile.query_info(
            Gio.FILE_ATTRIBUTE_STANDARD_IS_HIDDEN, Gio.FileQueryInfoFlags.NONE
        ).get_is_hidden():
            return False

        return True

    def __child_activated(
        self, _flow_box: Gtk.FlowBox, flow_box_child: Gtk.FlowBoxChild
    ) -> None:
        if isinstance((item := flow_box_child.get_child()), HypItem):
            if item.path.is_file():
                Gio.AppInfo.launch_default_for_uri(item.gfile.get_uri())
            elif item.path.is_dir():
                self.get_root().tab_view.get_selected_page().get_child().new_page(
                    item.path
                )
        elif isinstance(item, HypTag):
            self.get_root().tab_view.get_selected_page().get_child().new_page(
                tag=item.name
            )

    def set_menu_items(self, menu_items: Iterable[str]) -> None:
        """Disables all right-clickc menu items not in `menu_items`."""
        actions = {
            "rename",
            "copy",
            "cut",
            "paste",
            "trash",
            "new-folder",
            "select-all",
        }

        for action in actions.difference(menu_items):
            try:
                shared.app.lookup_action(action).set_enabled(False)
            except AttributeError:
                pass
        for action in menu_items:
            try:
                shared.app.lookup_action(action).set_enabled(True)
            except AttributeError:
                pass

    def __set_actions(self, *_args: Any) -> None:
        self.set_menu_items(
            {
                "rename",
                "copy",
                "cut",
                "paste",
                "trash",
                "new-folder",
                "select-all",
            }
        )

    def __right_click(self, _gesture, _n, x, y) -> None:
        rectangle = Gdk.Rectangle()
        rectangle.x, rectangle.y, rectangle.width, rectangle.height = x, y, 0, 0
        self.right_click_menu.set_pointing_to(rectangle)
        self.right_click_menu.popup()
