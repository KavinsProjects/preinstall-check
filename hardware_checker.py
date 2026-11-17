#!/usr/bin/env python3
"""Hardware Checker: read-only Linux hardware check for pre-install testing.

v0.1 supports apt-based distributions (Ubuntu, Linux Mint, Debian family).
"""

import argparse
import json
import platform
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

__version__ = "0.1.1"

PASS, FAIL, WARNING, NOT_TESTED = "PASS", "FAIL", "WARNING", "NOT_TESTED"

# Plain-English labels shown on screen (JSON export keeps the original names).
LABELS = {PASS: "OK", FAIL: "PROBLEM", WARNING: "CHECK", NOT_TESTED: "SKIPPED"}

# Optional tools the checks use, mapped to their apt package names.
OPTIONAL_TOOLS = {"lspci": "pciutils", "lsusb": "usbutils", "mokutil": "mokutil"}


def result(component, status, details, hint=""):
    r = {"component": component, "status": status, "details": details}
    if hint:
        r["hint"] = hint
    return r


def run_command(command, timeout=10):
    """Run a system command safely and return its output."""
    try:
        proc = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
        return proc.stdout.strip() if proc.returncode == 0 else None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def read_text(path):
    try:
        return Path(path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return None


def get_system_info():
    """Detect Linux distribution and system information."""
    os_info = {}
    content = read_text("/etc/os-release") or ""
    for line in content.splitlines():
        if "=" in line:
            key, value = line.strip().split("=", 1)
            os_info[key] = value.strip('"')

    distro_id = os_info.get("ID", "unknown").lower()
    id_like = os_info.get("ID_LIKE", "").lower()
    apt_family = (
        distro_id in ("ubuntu", "linuxmint", "debian")
        or "ubuntu" in id_like
        or "debian" in id_like
    )
    package_manager = "apt" if shutil.which("apt-get") else None
    supported = apt_family and package_manager == "apt"

    return {
        "distribution": os_info.get("PRETTY_NAME", "Unknown"),
        "distribution_id": distro_id,
        "version": os_info.get("VERSION_ID", "Unknown"),
        "kernel": platform.release(),
        "architecture": platform.machine(),
        "package_manager": package_manager,
        "supported": supported,
    }


def find_missing_tools():
    """Return apt packages for optional tools that are not installed."""
    return sorted(
        pkg for tool, pkg in OPTIONAL_TOOLS.items() if shutil.which(tool) is None
    )


def detect_environment():
    """Return 'wsl', 'vm', or 'bare-metal'."""
    proc_version = (read_text("/proc/version") or "").lower()
    if "microsoft" in proc_version or "wsl" in proc_version:
        return "wsl"
    virt = run_command(["systemd-detect-virt"])
    if virt and virt != "none":
        return "vm"
    return "bare-metal"


# ---------------------------------------------------------------- checks

def check_cpu():
    content = read_text("/proc/cpuinfo")
    if content is None:
        return result("CPU", NOT_TESTED, "Could not read CPU information")

    match = re.search(r"model name\s*:\s*(.+)", content) or re.search(
        r"Processor\s*:\s*(.+)", content
    )
    cores = content.count("processor\t:")
    if match:
        return result("CPU", PASS, f"{match.group(1).strip()} ({cores} threads)")
    return result("CPU", WARNING, "CPU information could not be identified")


def check_ram():
    content = read_text("/proc/meminfo")
    if content is None:
        return result("RAM", NOT_TESTED, "Could not read memory information")
    match = re.search(r"MemTotal:\s+(\d+)\s+kB", content)
    if not match:
        return result("RAM", WARNING, "Could not parse memory size")
    gb = int(match.group(1)) / 1024 / 1024
    if gb >= 3.5:
        return result("RAM", PASS, f"{gb:.1f} GB")
    return result(
        "RAM", WARNING, f"{gb:.1f} GB",
        "Under 4 GB is tight for modern desktops; pick a lightweight edition (e.g. Xfce)",
    )


def check_gpu(env):
    """Detect GPU via PCI class codes (0300 VGA, 0301 XGA, 0302 3D, 0380 other display)."""
    devices = run_command(["lspci", "-nnk"])
    wsl_gpu = env == "wsl" and Path("/dev/dxg").exists()

    if devices is None:
        if wsl_gpu:
            return [result("GPU", PASS, "WSL GPU passthrough available (/dev/dxg)")]
        return [result(
            "GPU", NOT_TESTED, "Could not look for a graphics card",
            "Install the 'pciutils' package and run again",
        )]

    gpu_blocks = [
        block for block in devices.split("\n\n")
        if re.search(r"\[03(00|01|02|80)\]", block.splitlines()[0] if block else "")
    ]

    if not gpu_blocks:
        if wsl_gpu:
            return [result("GPU", PASS, "WSL GPU passthrough available (/dev/dxg)")]
        return [result(
            "GPU", FAIL, "No graphics card detected",
            "Run 'ubuntu-drivers devices' to see if a driver is available",
        )]

    results = []
    for block in gpu_blocks:
        lines = block.splitlines()
        # "06:00.0 VGA compatible controller [0300]: AMD ... [1002:1681] (rev c7)"
        name = lines[0].split(": ", 1)[-1]
        name = re.sub(r"\[[0-9a-f]{4}:[0-9a-f]{4}\]|\(rev [0-9a-f]+\)", "", name).strip()
        results.append(result("GPU", PASS, name))

        driver = next(
            (l.split(":", 1)[1].strip() for l in lines
             if "Kernel driver in use:" in l),
            None,
        )
        is_nvidia = "nvidia" in block.lower()
        if driver is None:
            results.append(result(
                "GPU Driver", FAIL, "The graphics card is found but no driver is using it",
                "Run 'ubuntu-drivers devices' then 'sudo ubuntu-drivers autoinstall'"
                if is_nvidia else "Try a newer kernel or a newer distro release",
            ))
        elif driver == "nouveau" and is_nvidia:
            results.append(result(
                "GPU Driver", WARNING,
                "Working, but using the basic open-source 'nouveau' driver",
                "For better performance: 'sudo ubuntu-drivers autoinstall'",
            ))
        else:
            results.append(result("GPU Driver", PASS, f"Working (driver: {driver})"))
    return results


def check_audio():
    cards = read_text("/proc/asound/cards")
    if cards and "no soundcards" not in cards.lower() and cards.strip():
        names = re.findall(r"\]:\s*(.+)", cards)
        return result("Audio", PASS, "; ".join(n.strip() for n in names) or "Sound card detected")

    output = run_command(["wpctl", "status"]) or run_command(["pactl", "list", "short", "sinks"])
    if output:
        return result("Audio", PASS, "Audio sink information available")

    if cards is not None:
        return result("Audio", FAIL, "No sound card detected")
    return result("Audio", NOT_TESTED, "No audio information available")


def check_network():
    base = Path("/sys/class/net")
    try:
        interfaces = [i.name for i in base.iterdir() if i.name != "lo"]
    except OSError:
        return result("Network", NOT_TESTED, "Could not read network interfaces")

    if not interfaces:
        return result("Network", FAIL, "No network interfaces detected")

    wireless = [n for n in interfaces if (base / n / "wireless").exists()]
    return result(
        "Network", PASS,
        f"Interfaces: {', '.join(interfaces)}; "
        f"Wi-Fi: {', '.join(wireless) if wireless else 'Not detected'}",
    )


def check_bluetooth():
    try:
        adapters = list(Path("/sys/class/bluetooth").iterdir())
    except OSError:
        adapters = []
    if adapters:
        return result("Bluetooth", PASS, f"Adapter detected: {', '.join(a.name for a in adapters)}")
    return result("Bluetooth", WARNING, "No Bluetooth adapter detected")


def check_storage():
    """List real disks only; hide loop/zram devices and mark removable drives."""
    output = run_command(["lsblk", "-dn", "-o", "NAME,SIZE,TYPE,RM"])
    if not output:
        return result("Storage", NOT_TESTED, "Storage information unavailable")

    disks = []
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        name, size, kind, removable = parts[:4]
        if kind != "disk" or name.startswith(("loop", "zram", "ram")):
            continue
        label = "removable, probably your live USB" if removable == "1" else "internal"
        disks.append(f"{name} {size} ({label})")

    if not disks:
        return result("Storage", WARNING, "No disks detected",
                      "The installer needs a disk to install onto")
    return result("Storage", PASS, "; ".join(disks))


def check_webcam():
    """Use video4linux names; /dev/video* also includes metadata nodes."""
    names = []
    try:
        for dev in sorted(Path("/sys/class/video4linux").iterdir()):
            name = read_text(dev / "name")
            index = read_text(dev / "index")
            # index 0 is the capture node; others are usually metadata
            if name and (index is None or index.strip() == "0"):
                names.append(name.strip())
    except OSError:
        pass

    if names:
        return result("Webcam", PASS, f"Camera detected: {', '.join(names)}")
    return result("Webcam", WARNING, "No camera detected (normal if this laptop has no webcam)")


def check_usb():
    """Report USB devices from sysfs, skipping the virtual root hubs.

    `lsusb` counts every entry, including one invisible root hub per USB
    controller and built-in parts such as Bluetooth, so its total looks much
    bigger than the number of physical ports.
    """
    usb_root = Path("/sys/bus/usb/devices")
    try:
        entries = list(usb_root.iterdir())
    except OSError:
        entries = []

    if not any(e.name.startswith("usb") for e in entries):
        return result("USB", NOT_TESTED, "No USB information available")

    plugged, built_in = [], []
    for entry in entries:
        if not (entry / "idVendor").exists():
            continue  # an interface entry, not a device
        product = (read_text(entry / "product") or "").strip() or "Unknown device"
        if "root hub" in product.lower():
            continue
        location = (read_text(entry / "removable") or "").strip()
        (plugged if location == "removable" else built_in).append(product)

    if plugged:
        text = f"Working. Plugged into your ports: {', '.join(plugged)}"
    else:
        text = "Working. Nothing detected in your ports"
    if built_in:
        text += f"; {len(built_in)} built-in part(s) such as Bluetooth or hubs"
    return result("USB", PASS, text)


def check_touchpad():
    content = read_text("/proc/bus/input/devices")
    if content is None:
        return result("Touchpad", NOT_TESTED, "Could not read input devices")
    if re.search(r"touchpad|trackpad", content, re.IGNORECASE):
        return result("Touchpad", PASS, "Touchpad detected")
    return result("Touchpad", WARNING, "No touchpad detected (fine on desktops)")


def check_battery():
    try:
        batteries = [p.name for p in Path("/sys/class/power_supply").iterdir()
                     if p.name.startswith("BAT")]
    except OSError:
        batteries = []
    if batteries:
        return result("Battery", PASS, f"Detected: {', '.join(batteries)}")
    return result("Battery", WARNING, "No battery detected (fine on desktops)")


def check_boot_mode():
    if Path("/sys/firmware/efi").exists():
        details = "UEFI"
        sb = run_command(["mokutil", "--sb-state"])
        if sb:
            details += f"; {sb.splitlines()[0]}"
        return result("Boot Mode", PASS, details)
    return result("Boot Mode", PASS, "Legacy BIOS")


def check_firmware_errors():
    """Look for firmware load failures in the kernel log."""
    output = run_command(["dmesg"])
    if output is None:
        return result("Firmware", NOT_TESTED, "Kernel log unavailable",
                      "Try running with sudo")

    errors = [
        l.strip() for l in output.splitlines()
        if re.search(r"firmware.*(failed|missing|not found)|failed to load.*firmware",
                     l, re.IGNORECASE)
    ]
    if errors:
        shown = " | ".join(e.split("] ", 1)[-1] for e in errors[:3])
        return result(
            "Firmware", WARNING, f"{len(errors)} firmware error(s): {shown}",
            "Some hardware may need extra firmware (try 'sudo apt install linux-firmware')",
        )
    return result("Firmware", PASS, "No firmware load errors in kernel log")


# ---------------------------------------------------------------- report

def generate_report(system_info, env, results, missing_tools):
    counts = {
        s: sum(1 for r in results if r["status"] == s)
        for s in (PASS, FAIL, WARNING, NOT_TESTED)
    }

    print("\n" + "=" * 56)
    print("                  HARDWARE CHECKER")
    print("=" * 56)
    print(f"Operating System : {system_info['distribution']}")
    print(f"Kernel           : {system_info['kernel']}")
    print(f"Architecture     : {system_info['architecture']}")
    print(f"Environment      : {env}")
    print(f"Package manager  : {system_info['package_manager']}")

    if env in ("wsl", "vm"):
        label = "WSL" if env == "wsl" else "a virtual machine"
        print(f"\nNote: running in {label}. Hardware results are not meaningful.")
        print("Run this from a live USB session on the real PC.")

    print("\n" + "-" * 56)
    print("                  SCAN RESULTS")
    print("-" * 56)
    print("OK = working   CHECK = look at it   PROBLEM = needs fixing\n")
    for r in results:
        print(f"[{LABELS[r['status']]:<7}] {r['component']:<11} {r['details']}")
        if r.get("hint") and r["status"] != PASS:
            print(f"{'':<10}-> What to do: {r['hint']}")

    print("\n" + "=" * 56)
    print("                    SUMMARY")
    print("=" * 56)
    print(f"Working fine    : {counts[PASS]}")
    print(f"Worth checking  : {counts[WARNING]}")
    print(f"Problems        : {counts[FAIL]}")
    print(f"Skipped         : {counts[NOT_TESTED]}")

    if env == "bare-metal":
        print()
        if counts[FAIL]:
            print("Some parts need attention before you install (see 'What to do' above).")
        elif counts[WARNING]:
            print("Mostly good. Items marked CHECK may be normal for your laptop")
            print("(for example, no webcam on a model that never had one).")
        else:
            print("Everything we tested looks good for installing Linux.")

    print("\nScan completed.")
    print("=" * 56)

    if missing_tools:
        print("\nTip: some checks were limited because tools are missing.")
        print(f"Install them with: sudo apt install -y {' '.join(missing_tools)}")
    return counts


def main():
    parser = argparse.ArgumentParser(description="Read-only Linux hardware checker")
    parser.add_argument("--json", metavar="FILE", help="Export results to a JSON file")
    parser.add_argument(
        "--version", action="version", version=f"hardware-checker {__version__}"
    )
    args = parser.parse_args()

    print("\nStarting Linux hardware scan...")

    system_info = get_system_info()
    if not system_info["supported"]:
        print(f"\nUnsupported system: {system_info['distribution']}")
        print("v0.1 supports apt-based distributions only (Ubuntu, Linux Mint, Debian).")
        print("Support for other package managers is planned.")
        return

    env = detect_environment()
    missing_tools = find_missing_tools()

    results = [
        check_cpu(),
        check_ram(),
        *check_gpu(env),
        check_audio(),
        check_network(),
        check_bluetooth(),
        check_storage(),
        check_webcam(),
        check_usb(),
        check_touchpad(),
        check_battery(),
        check_boot_mode(),
        check_firmware_errors(),
    ]

    counts = generate_report(system_info, env, results, missing_tools)

    if args.json:
        report = {
            "scan_time": datetime.now().astimezone().isoformat(),
            "version": __version__,
            "environment": env,
            "missing_tools": missing_tools,
            "system": system_info,
            "summary": counts,
            "results": results,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=4)
        print(f"\nJSON report saved to: {args.json}")


if __name__ == "__main__":
    main()