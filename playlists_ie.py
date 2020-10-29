#   This program is free software: you can redistribute it and/or modify
#   it under the terms of the GNU General Public License as published by
#   the Free Software Foundation, either version 3 of the License, or
#   (at your option) any later version.

#   This program is distributed in the hope that it will be useful,
#   but WITHOUT ANY WARRANTY; without even the implied warranty of
#   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#   GNU General Public License for more details.

#   You should have received a copy of the GNU General Public License
#   along with this program.  If not, see <http://www.gnu.org/licenses/>.

import os
import logging
import filecmp
import sys

from gi.repository import Gio, GObject, Peas, RB, Gtk


log = logging.getLogger(__name__)

logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)


class PlaylistLoadSavePlugin(GObject.Object, Peas.Activatable):
    __gtype_name__ = 'PlaylistLoadSavePlugin'
    object = GObject.property(type=GObject.Object)
    _menu_names = ['playlist-popup']

    def __init__(self):
        GObject.Object.__init__(self)
        self.config = None
        self.choose_button = None
        self.path_display = None
        self.chooser = None
        self.window = None
        self.action1 = None
        self.action2 = None
        self.messagedialog = None
        self.plugin_info = "playlists_ie"

    def do_activate(self):
        shell = self.object
        app = shell.props.application
        self.window = shell.props.window

        self.action1 = Gio.SimpleAction.new("import-playlists", None)
        self.action1.connect("activate", self.import_playlists, shell)
        self.action2 = Gio.SimpleAction.new("export-playlists", None)
        self.action2.connect("activate", self.export_playlists, shell)
        self.window.add_action(self.action1)
        self.window.add_action(self.action2)

        item1 = Gio.MenuItem.new(label="Import playlists", detailed_action="win.import-playlists")
        item2 = Gio.MenuItem.new(label="Export playlists", detailed_action="win.export-playlists")

        app.add_plugin_menu_item("tools", "import-playlists", item1)
        app.add_plugin_menu_item("tools", "export-playlists", item2)

    def do_deactivate(self):
        shell = self.object
        app = shell.props.application
        app.remove_plugin_menu_item("view", "import-playlists")
        app.remove_plugin_menu_item("view", "export-playlists")
        app.remove_action("import-playlists")
        app.remove_action("export-playlists")
        self.action1 = None
        self.action2 = None


    def export_to_tmp(self, playlist_name, shell):
        settings = Gio.Settings.new("org.gnome.rhythmbox.plugins.playlists_ie")
        ie_folder = settings.get_string("ie-folder")
        pl_man = shell.props.playlist_manager

        if not os.path.isdir(ie_folder):
            self.warn_for_no_present_dir()
            return

        pl_name = playlist_name
        pl_uri = "file://" + os.path.join(ie_folder, "tmp") + ".m3u"
        log.debug("Exporting to tmp: " + pl_name)
        pl_man.export_playlist(pl_name, pl_uri, 1)


    def parse_m3u_to_relative(self, root_folder, playlist_path):
        output = ""
        with open(playlist_path) as playlist_file:
            for line in playlist_file:
                if not line.startswith("#"):
                    output = output + os.path.relpath(line, root_folder)

        with open(playlist_path, "w+") as playlist_file:
            playlist_file.write(output)


    def import_playlists(self, action, parameter, shell):
        settings = Gio.Settings.new("org.gnome.rhythmbox.plugins.playlists_ie")
        ie_folder = settings.get_string("ie-folder")
        if not os.path.isdir(ie_folder):
            self.warn_for_no_present_dir()
            return

        pl_man = shell.props.playlist_manager
        pl_list = pl_man.get_playlists()
        pl_file_count = 0
        processed_pl_files = 0

        #Get the internal plalists names to watch for deleted ones
        internal_playlists = []
        for playlist in pl_list:
            # this name is used for the newly imported playlists
            if playlist.props.name == "Unnamed playlist":
                playlist.props.name = "Unnamed playlist_"

            if playlist.props.name in internal_playlists:
                pl_man.delete_playlist(playlist.props.name) # Clear duplicates
                playlist.props
            # Handle only static playlists (skip auto pl)
            if not isinstance(playlist, RB.AutoPlaylistSource):
                logging.debug("Found static playlist: %s", playlist.props.name)
                internal_playlists.append(playlist.props.name)

        playlist_files = list(sorted(os.listdir(ie_folder)))

        #Start parsing playlist files
        for pl_file in playlist_files:
            if pl_file.endswith(".m3u"):
                # Metadata
                pl_name = pl_file[:-4]
                tmp_path = os.path.join(ie_folder, "tmp.m3u")
                pl_path = os.path.join(ie_folder, pl_name + ".m3u")
                pl_uri = "file://" + pl_path

                # Check for changes (because importing is slow)
                # Export to tmp.m3u and import only if there's a difference to the import candidate
                if pl_name in internal_playlists:
                    internal_playlists.remove(pl_name)
                    self.export_to_tmp(pl_name, shell)
                    # Touch the tmp file if it's not created (e.g. when pl is empty)
                    if not os.path.exists(tmp_path):
                        open(tmp_path, "a").close()
                    self.parse_m3u_to_relative(ie_folder, tmp_path)

                    # If there is a change in the playlist - reimport
                    if not filecmp.cmp(tmp_path, pl_path):
                        log.debug("deleting " + pl_name)
                        pl_man.delete_playlist(pl_name)
                        log.debug("importing " + pl_uri)
                        pl_man.parse_file(pl_uri)
                    os.remove(tmp_path) # Clear the tmp file

                else: # Import a pl missing from the internal list
                    log.debug("importing " + pl_uri)
                    pl_man.parse_file(pl_uri)

                # Correct the name of the imported playlist
                for playlist in pl_man.get_playlists():
                    if playlist.props.name == "Unnamed playlist":
                        playlist.props.name = pl_name

        # If anything is left in the internal pl list: it's been removed externally, so delete it
        for pl in internal_playlists:
            log.debug("deleting " + pl)
            pl_man.delete_playlist(pl)

        # It's impossible to circumvent this sht
        # Add and remove a playlist in order to avoid a UI bug (the last imported playlist gets selected for renaming)
        #tmp_pl = os.path.join(ie_folder, "tmp_tmp_tmp_tmp.m3u")
        #with open(tmp_pl, "a") as tmp:
        #    tmp.write("./mock.mp3")
        #open(tmp_pl, "a").close()
        #os.copy(os.listdir(ie_folder)[0], tmp_pl) # Use the first playlist as a
        #pl_man.parse_file("file://" + tmp_pl)
        #pl_man.create_static_playlist("tmp_tmp_tmp_tmp2")
        #pl_man.delete_playlist("Unnamed playlist")
        #for playlist in pl_man.get_playlists():
        #    if playlist.props.name == "Unnamed playlist":  # that's the one we imported last , so set it's name
        #        playlist.props.name = "tmp_tmp_tmp_tmp"
        #log.debug("deleting tmp")
        #pl_man.delete_playlist("tmp_tmp_tmp_tmp")
        #pl_man.delete_playlist("tmp_tmp_tmp_tmp2")

        #os.remove(tmp_pl)


    def export_playlists(self, action, parameter, shell):
        settings = Gio.Settings.new("org.gnome.rhythmbox.plugins.playlists_ie")
        ie_folder = settings.get_string("ie-folder")
        if not os.path.isdir(ie_folder):
            self.warn_for_no_present_dir()
            return

        pl_man = shell.props.playlist_manager

        pl_list = pl_man.get_playlists()
        pl_count = len(pl_list)
        processed_pl_count = 0
        existing_m3us = []

        # Prepare a list of the existing m3u files
        for file in os.listdir(ie_folder):
            if file.endswith(".m3u"):
                existing_m3us.append(os.path.join(ie_folder,file))

        for playlist in pl_list:
            # Only for static playlists (omit automatic ones)
            if isinstance(playlist, RB.StaticPlaylistSource):
                pl_name = playlist.props.name
                playlist_path = os.path.join(ie_folder, pl_name) + ".m3u"
                tmp_path = os.path.join(ie_folder, "tmp.m3u")

                self.export_to_tmp(pl_name, shell)
                if os.path.isfile(tmp_path):
                    log.debug("Parsing and renaming tmp "+ tmp_path + " to: " + playlist_path)
                    self.parse_m3u_to_relative(ie_folder, tmp_path)
                    if playlist_path in existing_m3us:
                        existing_m3us.remove(playlist_path)
                    os.rename(tmp_path, playlist_path)

        # The m3us left in the list are for removal (they were probably deleted in RB)
        for m3u in existing_m3us:
            os.rename(m3u, m3u+".deleted")

    def warn_for_no_present_dir(self):

        log.debug("reached warning for dir")
        messagedialog = Gtk.MessageDialog(parent=self.window,
                                          flags=Gtk.DialogFlags.MODAL,
                                          type=Gtk.MessageType.WARNING,
                                          buttons=Gtk.ButtonsType.OK,
                                          message_format="Please first select a valid directory." +
                                                         " (Plugins->Preferences)")
        messagedialog.connect("response", self.destroy_warning)
        messagedialog.show()

    def destroy_warning(self, widget, arg1):
        widget.destroy()
