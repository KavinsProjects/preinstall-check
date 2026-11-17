# Preinstall Check

Read-only Linux hardware checker for testing a PC **before installing** a distro. Boot a live USB, run the checker, and see whether audio, GPU driver, Wi-Fi, Bluetooth, webcam and more are detected.

**Version:** 0.1.0
**Supported:** apt-based distributions (Ubuntu, Linux Mint, Debian family)
**Planned:** dnf (Fedora), pacman (Arch), zypper (openSUSE), apk (Alpine) in later versions

## Quick start

```bash
git clone https://github.com/KavinsProjects/preinstall-check.git
cd preinstall-check
bash run.sh
```

`run.sh` installs `python3`, `pciutils`, `usbutils` and `mokutil` through apt if they are missing, then runs the checker. It uses `sudo` when you are not root.

On a live USB, connect to the internet first. No git? Download the files directly:

```bash
curl -O https://raw.githubusercontent.com/KavinsProjects/preinstall-check/main/hardware_checker.py
python3 hardware_checker.py
```

## Usage

```bash
bash run.sh                      # install missing tools, then scan
bash run.sh --no-install         # skip package installs
bash run.sh --json report.json   # also export results as JSON
python3 hardware_checker.py --version
```

Tip: run with `sudo` so the firmware check can read `dmesg`.
To run it as `./run.sh`, make it executable first: `chmod +x run.sh hardware_checker.py`.

## What it checks

| Check | How |
|---|---|
| CPU, RAM | `/proc/cpuinfo`, `/proc/meminfo` |
| GPU + driver | `lspci -nnk` PCI class codes; missing driver is a FAIL |
| Audio | `/proc/asound/cards`, then `wpctl` / `pactl` |
| Network, Wi-Fi | `/sys/class/net` |
| Bluetooth | `/sys/class/bluetooth` |
| Storage | `lsblk` |
| Webcam | `/sys/class/video4linux` |
| USB | `lsusb`, fallback `/sys/bus/usb/devices` |
| Touchpad, battery | `/proc/bus/input/devices`, `/sys/class/power_supply` |
| Boot mode | UEFI or BIOS, Secure Boot state via `mokutil` |
| Firmware errors | `dmesg` |

Statuses: `PASS`, `FAIL`, `WARNING`, `NOT_TESTED`. Touchpad and battery warnings are normal on desktops.

## Running on WSL or a VM

The tool detects WSL and virtual machines and prints a note, because their hardware results are not meaningful. Use it from a live USB session on the real PC. WSL is fine for testing the tool itself.

## JSON output

`--json FILE` writes version, scan time, environment, system info, summary counts, missing tools and every result. This is the input planned for the AI agent layer.

## Roadmap

- **0.1:** apt only (current)
- **0.2+:** more package managers (dnf, pacman, zypper, apk)
- **Later:** AI agent that reads the JSON, explains problems and proposes fixes, asking for confirmation before changing anything

## License

MIT, see [LICENSE](LICENSE).
