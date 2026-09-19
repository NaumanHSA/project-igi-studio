// The only things the editor page may ask of the desktop app. The page itself
// has no Node and cannot reach anything else; see main.js.
'use strict';

const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('studioApp', {
  desktop: true,
  version: () => ipcRenderer.invoke('studio:version'),
  // a native folder picker, for pointing the studio at the game
  pickFolder: (title) => ipcRenderer.invoke('studio:pick-folder', title),
  // show a folder in Explorer (folders only)
  openFolder: (p) => ipcRenderer.invoke('studio:open-folder', p),
  // Settings, Updates: look for a new version at start (on or off), and look now
  updates: {
    get: () => ipcRenderer.invoke('studio:updates-get'),
    set: (on) => ipcRenderer.invoke('studio:updates-set', on === true),
    check: () => ipcRenderer.invoke('studio:updates-check'),
  },
});
