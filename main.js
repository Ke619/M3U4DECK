'use strict';

const { app, BrowserWindow, ipcMain, dialog } = require('electron');
const path = require('path');
const http = require('http');
const { spawn } = require('child_process');
const fs = require('fs');

// ── FFmpeg ────────────────────────────────────────────────────────────────────
let currentFfmpeg = null;
let streamGeneration = 0;

const getFfmpegPath = () => {
  const { execSync } = require('child_process');

  // 1. Try system ffmpeg
  try {
    const sys = execSync('which ffmpeg').toString().trim();
    if (sys && fs.existsSync(sys)) return sys;
  } catch {}

  // 2. Try next to the AppImage
  const appImagePath = process.env.APPIMAGE;
  if (appImagePath) {
    const nextTo = path.join(path.dirname(appImagePath), 'resources', 'ffmpeg-linux', 'ffmpeg');
    if (fs.existsSync(nextTo)) return nextTo;
  }

  // 3. Try next to the executable
  const nextToExe = path.join(path.dirname(process.execPath), '..', 'resources', 'ffmpeg-linux', 'ffmpeg');
  if (fs.existsSync(nextToExe)) return nextToExe;

  // 4. Try inside app resources
  const internal = path.join(process.resourcesPath, 'ffmpeg-linux', 'ffmpeg');
  if (fs.existsSync(internal)) return internal;

  throw new Error('FFmpeg not found. Install ffmpeg or place it in resources/ffmpeg-linux/ffmpeg');
};

const killProcess = (proc) => new Promise((resolve) => {
  if (!proc || proc.killed) return resolve();
  const cleanup = () => { proc.removeAllListeners(); resolve(); };
  proc.once('close', cleanup);
  proc.once('exit', cleanup);
  try { if (!proc.kill('SIGKILL')) cleanup(); } catch { cleanup(); }
});

const getLiveFlags = (url) => [
  '-hide_banner', '-loglevel', 'error',
  '-reconnect', '1', '-reconnect_streamed', '1', '-reconnect_delay_max', '5',
  '-i', url,
  '-c:v', 'libx264', '-preset', 'ultrafast', '-tune', 'zerolatency',
  '-profile:v', 'baseline', '-level', '3.0',
  '-c:a', 'aac', '-ar', '44100', '-ac', '2',
  '-f', 'mp4', '-movflags', 'frag_keyframe+empty_moov',
  'pipe:1'
];

// ── Playlist storage ──────────────────────────────────────────────────────────
const getPlaylistsPath = () => path.join(app.getPath('userData'), 'playlists.json');
const loadPlaylists = () => {
  try {
    const p = getPlaylistsPath();
    if (fs.existsSync(p)) return JSON.parse(fs.readFileSync(p, 'utf-8'));
  } catch {}
  return [];
};
const savePlaylists = (list) => fs.writeFileSync(getPlaylistsPath(), JSON.stringify(list, null, 2));

// ── M3U Parser ────────────────────────────────────────────────────────────────
const parseM3U = (text) => {
  const lines = text.split('\n').map(l => l.trim()).filter(Boolean);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    if (!lines[i].startsWith('#EXTINF')) continue;
    const url = lines[i + 1];
    if (!url || url.startsWith('#')) continue;
    const inf = lines[i];
    out.push({
      name:  inf.includes(',') ? inf.slice(inf.lastIndexOf(',') + 1).trim() : 'Unknown',
      logo:  (inf.match(/tvg-logo="([^"]*)"/) || [])[1] || '',
      group: (inf.match(/group-title="([^"]*)"/) || [])[1] || 'Other',
      url,
    });
  }
  return out;
};

// ── HTTP Proxy ────────────────────────────────────────────────────────────────
const proxyServer = http.createServer(async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', '*');

  if (req.url?.startsWith('/stream')) {
    const url = new URL(req.url, 'http://localhost:3444');
    const target = url.searchParams.get('url');
    if (!target) { res.writeHead(400); return res.end('Missing url'); }

    const myGen = ++streamGeneration;
    await killProcess(currentFfmpeg);
    currentFfmpeg = null;
    if (myGen !== streamGeneration) { res.writeHead(409); return res.end(); }

    let ffmpegPath;
    try { ffmpegPath = getFfmpegPath(); } catch (e) {
      res.writeHead(500); return res.end(e.message);
    }

    const ffmpeg = spawn(ffmpegPath, getLiveFlags(target));
    currentFfmpeg = ffmpeg;
    res.writeHead(200, { 'Content-Type': 'video/mp4', 'Cache-Control': 'no-cache', 'Connection': 'keep-alive' });
    res.on('close', async () => { if (ffmpeg && !ffmpeg.killed) await killProcess(ffmpeg); });
    ffmpeg.stdout.pipe(res);
    ffmpeg.on('close', () => { if (currentFfmpeg === ffmpeg) currentFfmpeg = null; });
    return;
  }

  if (req.url === '/kill') {
    await killProcess(currentFfmpeg);
    currentFfmpeg = null;
    res.writeHead(200); return res.end('ok');
  }

  res.writeHead(404); res.end();
});

// ── IPC ───────────────────────────────────────────────────────────────────────
ipcMain.handle('get-playlists', () => loadPlaylists());

ipcMain.handle('add-playlist-url', async (_, { name, url }) => {
  try {
    const resp = await fetch(url);
    if (!resp.ok) return { success: false, error: `HTTP ${resp.status}` };
    const text = await resp.text();
    const channels = parseM3U(text);
    if (!channels.length) return { success: false, error: 'No channels found' };
    const list = loadPlaylists();
    const pl = { id: Date.now().toString(), name, url, type: 'url', count: channels.length };
    list.push(pl);
    savePlaylists(list);
    return { success: true, pl };
  } catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle('add-playlist-file', async () => {
  const result = await dialog.showOpenDialog({
    filters: [{ name: 'M3U Playlist', extensions: ['m3u', 'm3u8'] }],
    properties: ['openFile'],
  });
  if (result.canceled || !result.filePaths.length) return { success: false, error: 'Cancelled' };
  try {
    const filePath = result.filePaths[0];
    const text = fs.readFileSync(filePath, 'utf-8');
    const channels = parseM3U(text);
    if (!channels.length) return { success: false, error: 'No channels found' };
    const name = path.basename(filePath, path.extname(filePath));
    const list = loadPlaylists();
    const pl = { id: Date.now().toString(), name, filePath, type: 'file', count: channels.length };
    list.push(pl);
    savePlaylists(list);
    return { success: true, pl, name };
  } catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle('load-playlist', async (_, pl) => {
  try {
    let text;
    if (pl.type === 'url') {
      const r = await fetch(pl.url);
      text = await r.text();
    } else {
      text = fs.readFileSync(pl.filePath, 'utf-8');
    }
    return { success: true, channels: parseM3U(text) };
  } catch (e) { return { success: false, error: e.message }; }
});

ipcMain.handle('remove-playlist', (_, id) => {
  const list = loadPlaylists().filter(p => p.id !== id);
  savePlaylists(list);
  return { success: true };
});

ipcMain.handle('kill-stream', async () => {
  await killProcess(currentFfmpeg);
  currentFfmpeg = null;
  return { success: true };
});

// ── App ───────────────────────────────────────────────────────────────────────
let win;

app.whenReady().then(() => {
  proxyServer.listen(3444, () => console.log('Proxy on :3444'));

  win = new BrowserWindow({
    width: 1280,
    height: 720,
    backgroundColor: '#0a0a0f',
    title: 'IPTV Player',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });

  win.loadFile(path.join(__dirname, 'index.html'));
  win.setMenuBarVisibility(false);
});

app.on('window-all-closed', async () => {
  await killProcess(currentFfmpeg);
  proxyServer.close();
  app.quit();
});
