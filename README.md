# IPTV Player

A native Linux IPTV player built with Python + GTK4 + MPV.

## Features
- Load M3U playlists from URL or file
- Browse bouquets (groups) then channels
- Embedded MPV video player
- Steam Deck gamepad support
- AppImage — single file, no install needed

## Controls
| Gamepad | Action |
|---------|--------|
| A | Play selected channel |
| B | Go back |
| Y | Focus search |
| D-pad | Navigate |
| Start | Pause/Resume |

## Build
Push to main branch — GitHub Actions will build the AppImage automatically.
Download from the Actions tab → latest run → Artifacts.

## Run
```bash
chmod +x IPTV-Player-x86_64.AppImage
./IPTV-Player-x86_64.AppImage
```
