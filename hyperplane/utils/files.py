# files.py
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

"""Miscellaneous utilities for file operations."""
import shutil
from os import PathLike, getenv
from pathlib import Path
from typing import Optional
from urllib.parse import quote

from gi.repository import Gio, GLib, Gtk

from hyperplane import shared

# TODO: Handle errors better


def __emit_tags_changed(_file: Gio.File, _result: Gio.Task, path: Path) -> None:
    tags = path.relative_to(shared.home).parent.parts

    shared.postmaster.emit(
        "tag-location-created",
        Gtk.StringList.new(tags),
        Gio.File.new_for_path(str(Path(shared.home, *tags))),
    )


def copy(src: PathLike, dst: PathLike, tags: bool = False) -> None:
    """
    Asynchronously copies a file or directory from `src` to `dst`.

    Directories are copied recursively.

    If a file or directory with the same name already exists at `dst`,
    FileExistsError will be raised.

    If `tags` is true, it is assumed that the destination is a path representing tags.
    This is information is necessary for updating the list of valid tag directories.
    """

    src = Path(src)
    dst = Path(dst)

    if dst.exists():
        raise FileExistsError

    tags_changed = tags and (not dst.parent.is_dir())

    if not (parent := Path(dst).parent).is_dir():
        parent.mkdir(parents=True)

    if src.is_dir():
        # Gio doesn't support recursive copies
        task = Gio.Task.new(
            None,
            None,
            __emit_tags_changed if tags_changed else None,
            None,
            None,
            dst if tags_changed else None,
        )
        task.run_in_thread(lambda *_: shutil.copytree(src, dst))
        return

    Gio.File.new_for_path(str(src)).copy_async(
        Gio.File.new_for_path(str(dst)),
        Gio.FileCopyFlags.NONE,
        GLib.PRIORITY_DEFAULT,
        callback=__emit_tags_changed if tags_changed else None,
        user_data=dst,
    )


def move(src: PathLike, dst: PathLike, tags: bool = False) -> None:
    """
    Asynchronously moves a file or directory from `src` to `dst`.

    Directories are moved recursively.

    If a file or directory with the same name already exists at `dst`,
    FileExistsError will be raised.

    If `tags` is true, it is assumed that the destination is a path representing tags.
    This is information is necessary for updating the list of valid tag directories.
    """

    src = Path(src)
    dst = Path(dst)

    if dst.exists():
        raise FileExistsError

    tags_changed = tags and (not dst.parent.is_dir())

    if not (parent := dst.parent).is_dir():
        parent.mkdir(parents=True)

    # Gio doesn't seem to work with trashed items
    task = Gio.Task.new(
        None,
        None,
        __emit_tags_changed if tags_changed else None,
        None,
        None,
        dst if tags_changed else None,
    )
    task.run_in_thread(lambda *_: shutil.copytree(src, dst))


def restore(
    path: Optional[PathLike] = None,
    t: Optional[int] = None,
    gfile: Optional[Gio.File] = None,
) -> None:
    """
    Tries to asynchronously restore a file or directory from the trash
    either deleted from `path` at `t` or represented by `gfile`.
    """

    def do_restore(trash_path, orig_path):
        # Move the item in Trash/files back to the original location
        try:
            move(trash_path, orig_path)
        except FileExistsError:
            return

        __remove_trashinfo(trash_path, orig_path)

    def query_cb(gfile, result):
        try:
            file_info = gfile.query_info_finish(result)
        except GLib.Error:
            return

        orig_path = file_info.get_attribute_byte_string(
            Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH
        )

        uri = file_info.get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI)

        try:
            trash_path = get_gfile_path(Gio.File.new_for_uri(uri))
        except FileNotFoundError:
            return

        do_restore(trash_path, orig_path)

    if path and t:
        try:
            # Look up the trashed file's path and original path
            trash_path, orig_path = __trash_lookup(path, t)
        except FileNotFoundError:
            return

        do_restore(trash_path, orig_path)
        return

    if gfile:
        gfile.query_info_async(
            ",".join(
                (
                    Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH,
                    Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI,
                )
            ),
            Gio.FileQueryInfoFlags.NONE,
            GLib.PRIORITY_DEFAULT,
            None,
            query_cb,
        )


def trash_rm(gfile: Gio.File) -> None:
    """
    Tries to asynchronously remove a file or directory that is in the trash.

    Directories are removed recursively.
    """

    def query_cb(gfile, result):
        try:
            file_info = gfile.query_info_finish(result)
        except GLib.Error:
            return

        orig_path = file_info.get_attribute_byte_string(
            Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH
        )

        uri = file_info.get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI)

        try:
            trash_path = get_gfile_path(Gio.File.new_for_uri(uri))
        except FileNotFoundError:
            return

        rm(trash_path)
        __remove_trashinfo(trash_path, orig_path)

    gfile.query_info_async(
        ",".join(
            (
                Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH,
                Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI,
            )
        ),
        Gio.FileQueryInfoFlags.NONE,
        GLib.PRIORITY_DEFAULT,
        None,
        query_cb,
    )


def rm(path: PathLike) -> None:
    """
    Tries to asynchronously remove the file or directory at `path`.

    Directories are removed recursively.
    """

    if Path(path).is_dir():
        GLib.Thread.new(None, shutil.rmtree, path, True)
    else:
        Gio.File.new_for_path(str(path)).delete_async(GLib.PRIORITY_DEFAULT)


def get_copy_path(path: PathLike) -> Path:
    """Returns the path that should be used if `dst` already exists for a paste operation."""

    path = Path(path)

    # "File (copy)"
    if not (
        (
            copy_path := (path.parent / f'{path.stem} ({_("copy")}){path.suffix}')
        ).exists()
    ):
        return copy_path

    # "File (copy n)"
    n = 2
    while True:
        if not (
            (copy_path := path.parent / f'{path.stem} ({_("copy")} {n}){path.suffix}')
        ).exists():
            return copy_path
        n += 1


def get_gfile_display_name(gfile: Gio.File) -> str:
    """Gets the display name for a `GFile`."""
    # HACK: Don't call this. Store this info somewhere instead.
    return gfile.query_info(
        Gio.FILE_ATTRIBUTE_STANDARD_DISPLAY_NAME, Gio.FileAttributeInfoFlags.NONE
    ).get_display_name()


def get_gfile_path(gfile: Gio.File, uri_fallback=False) -> Path | str:
    """
    Gets a pathlib.Path to represent a `GFile`.

    If `uri_fallback` is true and no path can be retreived but the `GFile`
    has a valid URI, returns that instead.
    """

    if path := gfile.get_path():
        return Path(path)

    try:
        uri = gfile.query_info(
            Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI, Gio.FileQueryInfoFlags.NONE
        ).get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI)
    except GLib.Error as error:
        raise FileNotFoundError from error

    if uri and (path := Gio.File.new_for_uri(uri).get_path()):
        return Path(path)

    if uri_fallback and (gfile_uri := gfile.get_uri()):
        return gfile_uri

    raise FileNotFoundError


def validate_name(
    gfile: Gio.File, name: str, siblings: Optional[bool] = False
) -> (bool, Optional[str]):
    """
    The first return value is true if `name` is a valid name for a new file or folder
    in the directory represented by `gfile`.

    The second is either a warning or error depenging on whether the first return value was true.
    This should be displayed to the user before the file operation.

    Set `siblings` to true for a move operation in the same directory (a rename).
    """
    try:
        path = Path(get_gfile_path(gfile))
    except FileNotFoundError:
        # Assume that locations without paths are not writable
        # TODO: This may be incorrect
        return False, _("The path is not writable.")

    is_dir = path.is_dir()
    is_file = (not is_dir) and (path.exists())

    # TODO: More elegant (cross-platfrom) way to check for invalid paths
    if name in (".", ".."):
        if is_dir:
            error = _('A folder cannot be called "{}".').format(name)
        else:
            error = _('A file cannot be called "{}".').format(name)
        return False, error

    if "/" in name:
        if is_dir:
            error = _('Folder names cannot conrain "{}".').format("/")
        else:
            error = _('File names cannot conrain "{}".').format("/")
        return False, error

    new_path = Path(path.parent, name) if siblings else path / name
    new_is_dir = new_path.is_dir()
    new_is_file = (not new_is_dir) and (new_path.exists())

    if new_is_dir and is_dir and new_path != path:
        error = _("A folder with that name already exists.")
        return False, error

    if new_is_file and is_file and new_path != path:
        error = _("A file with that name already exists.")
        return False, error

    if name[0] == ".":
        if is_dir:
            warning = _("Folders with “.” at the beginning of their name are hidden.")
        else:
            warning = _("Files with “.” at the beginning of their name are hidden.")
        return True, warning

    return True, None


def __trash_lookup(path: PathLike, t: int) -> (PathLike, PathLike):
    trash = Gio.File.new_for_uri("trash://")

    files = trash.enumerate_children(
        ",".join(
            (
                Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI,
                Gio.FILE_ATTRIBUTE_TRASH_DELETION_DATE,
                Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH,
            )
        ),
        Gio.FileAttributeInfoFlags.NONE,
    )

    path = str(path)

    while file_info := files.next_file():
        orig_path = file_info.get_attribute_byte_string(
            Gio.FILE_ATTRIBUTE_TRASH_ORIG_PATH
        )
        del_date = file_info.get_deletion_date()
        uri = file_info.get_attribute_string(Gio.FILE_ATTRIBUTE_STANDARD_TARGET_URI)

        if not orig_path == path:
            continue

        if not GLib.DateTime.new_from_unix_utc(t).equal(del_date):
            continue

        trash_path = get_gfile_path(Gio.File.new_for_uri(uri))
        return trash_path, orig_path

    raise FileNotFoundError


def __remove_trashinfo(trash_path: PathLike, orig_path: PathLike) -> None:
    trashinfo = (
        Path(getenv("HOST_XDG_DATA_HOME", Path.home() / ".local" / "share"))
        / "Trash"
        / "info"
        / (trash_path.name + ".trashinfo")
    )

    try:
        keyfile = GLib.KeyFile.new()
        keyfile.load_from_file(str(trashinfo), GLib.KeyFileFlags.NONE)
    except GLib.Error:
        return

    # Double-check that the file is the right one
    if keyfile.get_string("Trash Info", "Path") == quote(orig_path):
        try:
            Gio.File.new_for_path(str(trashinfo)).delete()
        except GLib.Error:
            pass
