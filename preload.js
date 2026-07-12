'use strict';
const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('api', {
  getPlaylists:    ()      => ipcRenderer.invoke('get-playlists'),
  addPlaylistUrl:  (data)  => ipcRenderer.invoke('add-playlist-url', data),
  addPlaylistFile: ()      => ipcRenderer.invoke('add-playlist-file'),
  loadPlaylist:    (pl)    => ipcRenderer.invoke('load-playlist', pl),
  removePlaylist:  (id)    => ipcRenderer.invoke('remove-playlist', id),
  killStream:      ()      => ipcRenderer.invoke('kill-stream'),
});
