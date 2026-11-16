<div align="center">

# 📹 iCSee for Linux

### A fast, dependency-light Python client for **Xiongmai** IP cameras & DVRs — the ones sold as **iCSee** / **XMEye**.

Watch your camera, grab snapshots, record video, control PTZ and listen to live audio **straight from your Linux machine** — no cloud, no proprietary app, no browser plugins.

[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/platform-Linux-informational.svg)](#requirements)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)
[![Protocol](https://img.shields.io/badge/protocol-DVRIP%2034567-orange.svg)](#how-it-works)

[**Quick start**](#-quick-start) · [**Features**](#-features) · [**CLI**](#-command-line) · [**GUI**](#-graphical-interface) · [**Docs**](#-how-it-works) · [🇧🇷 Português](README.pt-BR.md)

</div>

---

> **⭐ If this project saves you from the sluggish official app, please give it a star — it genuinely helps others find it.**

---

## Why this exists

Xiongmai-based cameras (**iCSee**, **XMEye**, and dozens of white-label brands)
ship with closed mobile apps and flaky browser plugins. On Linux there's often
*nothing* that just works. **iCSee for Linux** talks the camera's own native LAN
protocol (**DVRIP**, TCP port `34567`) directly — so you get a clean CLI, a
usable GUI, and a hackable Python API, with **zero cloud dependency**.

```bash
python3 icsee_gui.py --host 192.168.1.10 --user admin --password SENHA
```

<div align="center">

<!-- Add a screenshot or GIF here to make the repo shine:
     drop it at docs/demo.gif and uncomment the line below -->
<!-- ![Live view demo](docs/demo.gif) -->
*Live H.265 view · PTZ · snapshot · recording · audio — in one window.*

</div>

---

## ✨ Features

- 🔎 **Auto-discovery** — find every camera on your LAN in seconds
- 🖥️ **Live video** — H.264 **and** H.265/HEVC, Main or sub-stream
- 🔊 **Live audio** — G.711 listening, toggle on/off
- 📷 **Snapshots** — instant JPEG grab
- ⏺️ **Recording** — dump the raw stream, remux to MP4 with one ffmpeg line
- 🎮 **PTZ & zoom** — pan/tilt/zoom/focus/iris control
- 🪟 **Resizable GUI** — video scales with the window, keeps aspect ratio
- 🧰 **Clean Python API** — embed it in your own scripts in 5 lines
- 🪶 **Tiny footprint** — the protocol core is **pure standard-library Python**, no pip install needed
- 🔐 **Local-first** — speaks to the device on your network, nothing leaves your LAN

---

## 🚀 Quick start

```bash
# 1. Get it
git clone https://github.com/admin/icsee-for-linux.git
cd icsee-for-linux
pip install -r requirements.txt          # only needed for the GUI

# 2. Find your camera
python3 discover.py

# 3. Check it answers
python3 icsee_client.py --host 192.168.1.10 --user admin --password SENHA info

# 4. Open the live viewer
python3 icsee_gui.py --host 192.168.1.10 --user admin --password SENHA
```

> 💡 Factory defaults are usually user `admin` with an **empty** password
> (`--password ""`).

---

## 📦 Requirements

| | Needed for | Notes |
|---|---|---|
| **Python 3.8+** | everything | protocol core uses **only the standard library** |
| **ffmpeg** | GUI / live view | decodes H.264 & H.265 — must be on `PATH` |
| **Pillow**, **numpy** | GUI | `pip install -r requirements.txt` |
| **aplay** or **pw-play** | live audio | from `alsa-utils` or PipeWire (optional) |

> The GUI audio feature uses Python's `audioop`, so for audio prefer **Python 3.8–3.12**.

```bash
# Debian/Ubuntu
sudo apt install ffmpeg alsa-utils
# Fedora
sudo dnf install ffmpeg alsa-utils
# Arch
sudo pacman -S ffmpeg alsa-utils
```

---

## 🔎 Discover cameras

```bash
python3 discover.py                       # auto-detect your subnet
python3 discover.py --subnet 192.168.1.0/24
python3 discover.py --no-scan             # UDP broadcast only (fast)
```

```
3 device(s) found:

  IP        : 192.168.1.10
  Name      : camera_2e30
  MAC       : f8:16:0c:xx:xx:xx
  TCP Port  : 34567
  HTTP Port : 80
```

---

## 🖥️ Command line

```
python3 icsee_client.py --host HOST [--user USER] [--password PASS] COMMAND
```

| Command | What it does |
|---|---|
| `info` | Print `SystemInfo` (model, firmware, channels…) |
| `login` | Test authentication |
| `getconfig <name>` | Read a config block |
| `ability [name]` | Read device capabilities |
| `snapshot <file.jpg>` | Grab one JPEG frame |
| `record <sec> <file>` | Record the live stream for N seconds |
| `live` | Live view in a window (needs `ffplay`/`mpv`) |
| `ptz <dir> [sec]` | PTZ / zoom control |

```bash
# Snapshot
python3 icsee_client.py --host 192.168.1.10 --password SENHA snapshot shot.jpg

# Record 30s, then wrap into MP4 with no re-encoding
python3 icsee_client.py --host 192.168.1.10 --password SENHA record 30 clip.h265
ffmpeg -framerate 12 -i clip.h265 -c copy clip.mp4

# PTZ
python3 icsee_client.py --host 192.168.1.10 --password SENHA ptz right 0.5
python3 icsee_client.py --host 192.168.1.10 --password SENHA ptz zoomin
```

PTZ directions: `up` `down` `left` `right` `upleft` `upright` `downleft`
`downright` `zoomin` `zoomout` `focusfar` `focusnear` `irisopen` `irisclose`.

### Use it as a library

```python
from icsee_client import DVRIPClient

with DVRIPClient("192.168.1.10") as cam:
    cam.login("admin", "SENHA")
    print(cam.system_info())
    open("shot.jpg", "wb").write(cam.snapshot())
    cam.record("clip.h265", seconds=10)
```

---

## 🪟 Graphical interface

```bash
python3 icsee_gui.py --host 192.168.1.10 --user admin --password SENHA
# or launch with blank fields and fill them in the window:
python3 icsee_gui.py
```

- **Live video** that resizes with the window (keeps aspect ratio)
- **Stream** selector — `Main` (full res) or `Extra1` (light sub-stream)
- **Codec** selector — `hevc` (H.265) or `h264`
- **PTZ pad** + **Zoom +/−**
- **📷 Photo**, **🔊 Audio** (toggle), **⏺ Record**

---

## 🧠 How it works

Xiongmai devices expose the **DVRIP** ("Sofia") protocol on TCP **34567**: a
20-byte binary header followed by a **JSON** body.

<details>
<summary><b>Packet header (20 bytes, little-endian)</b></summary>

| Offset | Size | Field |
|---|---|---|
| 0 | 1 | `0xFF` flag |
| 1 | 1 | version |
| 2 | 2 | reserved |
| 4 | 4 | SessionID |
| 8 | 4 | sequence number |
| 12 | 2 | total / current packet |
| 14 | 2 | message ID |
| 16 | 4 | data length |

</details>

- **Login** uses a custom password hash (MD5 → 8 chars of a 62-char alphabet).
  Empty password → `tlJwpbo6`. Body:
  `{"EncryptType":"MD5","LoginType":"DVRIP-Web","PassWord":"<hash>","UserName":"admin"}`
- **Video** comes from `OPMonitor`. Each frame carries a small Xiongmai header
  (`00 00 01 <type>`); the client de-muxes the stream, reassembles frames that
  span multiple network packets, and emits a clean H.264/H.265 **Annex-B**
  elementary stream.
- **Audio** is **G.711 A-law, 8 kHz, mono**, interleaved in the same stream.

---

## 🌍 Remote access (over the internet)

This client talks to the device on your **local network**. To reach it from
outside, use:

- 🔒 **VPN** ([WireGuard](https://www.wireguard.com/) /
  [Tailscale](https://tailscale.com/)) — run it on a device that stays on at
  home; connect from anywhere and use the camera's LAN IP. **Nothing is exposed.**
- 🌐 **Port-forward + DDNS** on your router (forward `34567`). Works instantly
  but **exposes the camera** — use a strong password and a non-standard port.

> The official apps' zero-config remote access uses the vendor's **proprietary
> P2P cloud**, which is intentionally **not** implemented here.

---

## 🧯 Troubleshooting

| Symptom | Fix |
|---|---|
| `Ret=205` / "user locked" | Anti-brute-force lockout from wrong passwords — wait 1–5 min or reboot the device |
| `Connection refused` on 34567 | Same lockout, or PC/camera on different networks/VLANs |
| GUI connects but no video | Check the **codec** (`hevc` vs `h264`); 4MP/8MP cams are usually H.265 |
| Top of frame fine, rest garbled | Wrong codec or packet loss — try the `Extra1` stream |
| Choppy / stuttering video | PC can't keep up with `Main` — switch to `Extra1` |
| No audio | Install `alsa-utils`/PipeWire; ambient audio may just be very quiet |

---

## 🗺️ Roadmap

- [ ] Two-way audio (talk-back / intercom)
- [ ] SD-card recording search & playback
- [ ] Multi-camera grid view
- [ ] Config **write** helpers (resolution, bitrate, OSD)
- [ ] Packaged `.desktop` launcher / PyPI release

Contributions and ideas are very welcome — see [CONTRIBUTING](CONTRIBUTING.md).

---

## 🤝 Contributing

PRs, bug reports and device-compatibility notes are welcome! Tell us your camera
**model + firmware** (`icsee_client.py ... info`) in issues so we can grow the
compatibility list. Start with [CONTRIBUTING.md](CONTRIBUTING.md).

---

## ⚖️ Disclaimer

Independent project, **not affiliated** with Xiongmai or the iCSee/XMEye apps.
All trademarks belong to their owners. The protocol was implemented
independently for **local-network interoperability**. Use it only on devices you
own or are authorized to manage. Provided "as is", without warranty.

---

## 📄 License

[MIT](LICENSE) — do whatever you want, just keep the notice.

<div align="center">

**Found it useful? Drop a ⭐ and share it with someone fighting the official app.**

</div>
