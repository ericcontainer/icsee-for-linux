# Contributing to iCSee for Linux

Thanks for helping out! 🎉 This project improves fastest when people report how
it behaves with **their** camera.

## Reporting a device (most useful!)

Open an issue with the output of:

```bash
python3 icsee_client.py --host <IP> --user admin --password <PASS> info
```

Include:
- Camera/DVR **model** and **firmware** (from `info`)
- Which **codec** works (`hevc` / `h264`)
- What works and what doesn't (video, audio, PTZ, snapshot)

This grows the compatibility list and helps everyone.

## Bug reports

Please include:
- OS and Python version (`python3 --version`)
- `ffmpeg -version` (first line)
- Exact command and the full error / stack trace
- What you expected vs. what happened

## Pull requests

1. Fork and create a branch (`git checkout -b feature/my-change`).
2. Keep the **protocol core** (`icsee_client.py`, `discover.py`)
   **standard-library only** — no new runtime deps there.
3. Match the existing style; keep functions small and documented.
4. Test against a real device when you can, and say which model in the PR.
5. Open the PR with a clear description.

## Ideas / roadmap

See the roadmap in the [README](README.md#️-roadmap). Two-way audio, SD-card
playback and a multi-camera grid are great places to start.

## Code of conduct

Be kind and constructive. Use this software only on devices you own or are
authorized to manage.
