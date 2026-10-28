#!/usr/bin/env python3
"""Stage Omarchy A's P105 desktop into a new directory."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = Path(__file__).resolve().parent
DESKTOP = HERE.parent
PROJECT = DESKTOP.parent
PAYLOAD = Path("home/tablet/.local/share/omarchy-ipad")
KEYBOARD = PAYLOAD / "trials/wvkbd-mobintl-v0.20-font18-special15-state"
MANIFEST = "arch-ipad-ui-manifest.json"
RECEIPT = "p105-desktop.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def check_armhf(path, label="Keyboard"):
    """Check the target ABI without executing the binary on the build host."""
    header = Path(path).read_bytes()[:52]
    if len(header) != 52 or header[:6] != b"\x7fELF\x01\x01":
        raise ValueError(label + " must be a little-endian ELF32 ARM executable")
    if struct.unpack_from("<H", header, 18)[0] != 40:
        raise ValueError(label + " ELF machine is not ARM")
    flags = struct.unpack_from("<I", header, 36)[0]
    if not flags & 0x400 or flags & 0x200:
        raise ValueError(label + " must use the ARM hard-float ABI")


def file_manifest(target):
    return {
        path.relative_to(target).as_posix(): sha(path)
        for path in sorted(target.rglob("*"))
        if path.is_file() and not path.is_symlink() and path != target / MANIFEST
    }


def links(target):
    return {
        path.relative_to(target).as_posix(): os.readlink(path)
        for path in sorted(target.rglob("*"))
        if path.is_symlink()
    }


def copy(source, destination, executable=False):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_symlink():
        destination.unlink()
    shutil.copy2(source, destination)
    if executable:
        destination.chmod(0o755)


def adapt_firefox(path):
    """Merge P105's writable Firefox defaults into the staged browser policy."""
    document = json.loads(path.read_text())
    if not isinstance(document, dict) or not isinstance(document.get("policies"), dict):
        raise ValueError("Firefox policy must contain a policies object")
    policies = document["policies"]
    if "Preferences" in policies and not isinstance(policies["Preferences"], dict):
        raise ValueError("Firefox Preferences policy must be an object")
    defaults_path = HERE / "firefox-defaults.json"
    defaults = json.loads(defaults_path.read_text())
    for name, entry in defaults.items():
        if not isinstance(entry, dict) or entry.get("Status") != "default":
            raise ValueError("P105 Firefox defaults must stay user-adjustable: " + name)
        value_type = entry.get("Type")
        value = entry.get("Value")
        if not ((value_type == "boolean" and type(value) is bool)
                or (value_type == "number" and type(value) is int)):
            raise ValueError("P105 Firefox default has an invalid explicit type: " + name)
    preferences = dict(policies.get("Preferences", {}))
    preferences.update(defaults)
    policies["Preferences"] = preferences
    path.write_text(json.dumps(document, indent=2) + "\n")
    return {"policy_sha256": sha(path), "defaults_sha256": sha(defaults_path), "preferences": defaults}


def adapt_keyboard_bridge(payload):
    """Bridge the built-in Network panel's keyboard state through its facade."""
    api_path = payload / "shell/services/PluginShellApi.qml"
    shell_path = payload / "shell/shell.qml"
    api = api_path.read_text()
    shell = shell_path.read_text()
    if "_keyboardVisibleLookup" in api or "_keyboardVisibleLookup" in shell:
        raise ValueError("Reference shell already has a keyboard bridge; inspect the P105 adapter")
    api_anchor = "  property var _serviceLookup: null\n"
    scoped_anchor = "      pluginId: key,\n      appLibrary:"
    entry_anchor = "      pluginId: target,\n      barConfig:"
    for text, anchor in ((api, api_anchor), (shell, scoped_anchor), (shell, entry_anchor)):
        if text.count(anchor) != 1:
            raise ValueError("Reference shell facade changed; inspect the P105 keyboard bridge")
    api = api.replace(api_anchor,
        "  // P105: expose the built-in Network panel's keyboard state as a scalar.\n"
        "  property var _keyboardVisibleLookup: null\n"
        "  readonly property bool keyboardVisible: _keyboardVisibleLookup ? _keyboardVisibleLookup() : false\n\n"
        + api_anchor)
    for anchor, identifier in ((scoped_anchor, "key"), (entry_anchor, "target")):
        first_line, remainder = anchor.split("\n", 1)
        bridge = (
            first_line + "\n"
            "      _keyboardVisibleLookup: function() {\n"
            "        var entry = currentManifest()\n"
            "        return !!(" + identifier + " === \"omarchy.network\" && entry && entry.__isFirstParty && shell.keyboardVisible)\n"
            "      },\n" + remainder
        )
        shell = shell.replace(anchor, bridge)
    api_path.write_text(api)
    shell_path.write_text(shell)
    return {
        "entry": "omarchy.network", "surface": "read-only keyboardVisible",
        "files": {path.relative_to(payload).as_posix(): sha(path) for path in (api_path, shell_path)},
    }


def adapt_menu(path):
    """Keep source menu actions that have a backend in this desktop profile."""
    original = {}
    for line in path.read_text().splitlines():
        row = line.strip()
        if not row or row.startswith("//") or row in {"{", "}"}:
            continue
        entry = json.loads("{" + row.rstrip(",") + "}")
        if len(entry) != 1 or set(entry) & set(original):
            raise ValueError("Unexpected source menu layout")
        original.update(entry)
    keep = {
        "apps", "learn", "learn.omarchy", "learn.arch", "learn.bash",
        "appearance", "appearance.theme", "appearance.background", "setup",
        "setup.monitors", "setup.network", "about", "system", "system.shutdown",
    }
    if not keep <= original.keys():
        raise ValueError("Reference menu entries changed")
    menu = {name: entry for name, entry in original.items() if name in keep}
    menu["setup.monitors"].update(label="Display", action="omarchy-shell omarchy.monitor toggle")
    menu["setup.network"]["action"] = "omarchy-shell omarchy.network toggle"
    menu["setup.bluetooth"] = {"icon": "󰂯", "label": "Bluetooth", "action": "omarchy-shell omarchy.bluetooth toggle"}
    menu["setup.power"] = {"icon": "󰁹", "label": "Battery", "action": "omarchy-shell omarchy.power toggle"}
    path.write_text(json.dumps(menu, ensure_ascii=False, indent=2) + "\n")
    return {"retained": sorted(keep), "added": ["setup.bluetooth", "setup.power"],
            "omitted": sorted(original.keys() - keep)}


def verify(target):
    record = json.loads((target / RECEIPT).read_text())
    if (record.get("schema"), record.get("profile"), record.get("architecture")) != (1, "p105", "armv7h"):
        raise ValueError("Not a P105 ARMv7h desktop receipt")
    expected = json.loads((target / MANIFEST).read_text())
    if file_manifest(target) != expected:
        raise ValueError("Staged desktop files differ from their manifest")
    if links(target) != record["symlinks"]:
        raise ValueError("Staged desktop symlinks differ from their receipt")
    check_armhf(target / KEYBOARD)
    check_armhf(target / "usr/bin/labwc", "Labwc")
    check_armhf(target / "usr/libexec/omarchy-wtype", "Cursor helper")
    if sha(target / "usr/share/doc/omarchy-p105/support-build.json") != record["support_manifest_sha256"]:
        raise ValueError("Staged support receipt differs from its desktop record")
    if sha(target / KEYBOARD) != record["keyboard_sha256"]:
        raise ValueError("Staged keyboard differs from its receipt")
    print("Verified P105 desktop:", target)


def stage(args):
    target = args.output.resolve()
    if target.exists():
        raise ValueError("Choose a new staging directory")
    if not all((args.upstream, args.keyboard, args.keyboard_sha256, args.support)):
        raise ValueError("--upstream, --keyboard, --keyboard-sha256 and --support are required")
    support = args.support.resolve()
    support_manifest = support / "manifest.json"
    support_record = json.loads(support_manifest.read_text())
    if (support_record.get("schema"), support_record.get("architecture")) != (1, "armv7h"):
        raise ValueError("Desktop support must have an ARMv7h build receipt")
    support_files = {path.relative_to(support).as_posix(): sha(path)
                     for path in sorted(support.rglob("*"))
                     if path.is_file() and not path.is_symlink() and path != support_manifest}
    if support_files != support_record["files"]:
        raise ValueError("Desktop support differs from its build receipt")
    check_armhf(support / "labwc/labwc", "Labwc")
    check_armhf(support / "cursor/wtype", "Cursor helper")
    pins = dict(line.split("=", 1) for line in (DESKTOP / "upstream.lock").read_text().splitlines() if "=" in line)
    upstream = args.upstream.resolve()
    commit = subprocess.check_output(["git", "-C", str(upstream), "rev-parse", "HEAD"], text=True).strip()
    if commit != pins["omarchy_commit"]:
        raise ValueError("Omarchy source does not match desktop/upstream.lock")
    changes = subprocess.check_output([
        "git", "-C", str(upstream), "status", "--porcelain", "--untracked-files=all",
        "--", "themes", "applications/foot.desktop",
    ], text=True)
    if changes:
        raise ValueError("Pinned Omarchy theme/application sources have local changes")
    keyboard = args.keyboard.resolve()
    check_armhf(keyboard)
    if sha(keyboard) != args.keyboard_sha256:
        raise ValueError("Keyboard hash differs")
    xpi = args.omafox_xpi.resolve()
    subprocess.run([
        sys.executable, str(DESKTOP / "stage.py"), str(target),
        "--upstream", str(upstream), "--keyboard", str(keyboard),
        "--keyboard-sha256", args.keyboard_sha256, "--omafox-xpi", str(xpi),
    ], check=True)

    for name, destination in (
        ("login-session", "usr/local/libexec/arch-ipad-login-session"),
        ("labwc-autostart", "home/tablet/.config/labwc/autostart"),
        ("scale-output", "usr/local/libexec/arch-ipad-scale-output"),
    ):
        copy(HERE / name, target / destination, executable=True)
    for name in ("omarchy-desktop-ready", "omarchy-bluetooth-pair"):
        copy(PROJECT / "system/j71b/overlay/usr/libexec" / name,
             target / "usr/libexec" / name, executable=True)
    copy(PROJECT / "system/j71b/overlay/usr/lib/omarchy-bluetooth/policy.py",
         target / "usr/lib/omarchy-bluetooth/policy.py")
    shutil.copytree(support / "bluetooth/lib/dbus_next", target / "usr/lib/omarchy-bluetooth/dbus_next")
    copy(support / "labwc/labwc", target / "usr/bin/labwc", executable=True)
    copy(support / "cursor/wtype", target / "usr/libexec/omarchy-wtype", executable=True)
    copy(HERE / "hw-display", target / "usr/local/bin/omarchy-hw-display", executable=True)
    for source_name, command in (
        ("launch-browser", "omarchy-launch-browser"), ("launch-webapp", "omarchy-launch-webapp"),
        ("launch-terminal", "omarchy-launch-terminal"), ("system-action", "omarchy-system"),
    ):
        copy(HERE / source_name, target / "usr/local/bin" / command, executable=True)
    menu_adaptation = adapt_menu(target / PAYLOAD / "default/omarchy/omarchy-menu.jsonc")
    keyboard_bridge = adapt_keyboard_bridge(target / PAYLOAD)
    firefox_defaults = adapt_firefox(target / "usr/lib/firefox/distribution/policies.json")
    for component in ("labwc", "cursor", "bluetooth"):
        copy(support / component / "LICENSE", target / "usr/share/licenses/omarchy-p105" / component / "LICENSE")
    copy(support_manifest, target / "usr/share/doc/omarchy-p105/support-build.json")
    copy(support / "packages.lock", target / "usr/share/doc/omarchy-p105/build-packages.lock")

    # Cascadia's p105-keys service owns volume, the side switch and Hold.
    # Preserve those hardware procedures and avoid a second action in labwc.
    rc = ET.parse(target / "home/tablet/.config/labwc/rc.xml")
    keyboard_config = rc.getroot().find("keyboard")
    removed = set()
    hardware_keys = {"XF86AudioRaiseVolume", "XF86AudioLowerVolume", "XF86PowerOff"}
    for binding in list(keyboard_config):
        if binding.tag == "keybind" and binding.get("key") in hardware_keys:
            removed.add(binding.get("key"))
            keyboard_config.remove(binding)
    if removed != hardware_keys:
        raise ValueError("Reference labwc hardware bindings changed")
    ET.indent(rc, space="  ")
    for destination in (
        target / "home/tablet/.config/labwc/rc.xml",
        target / PAYLOAD / "labwc-rc.xml",
    ):
        rc.write(destination, encoding="UTF-8", xml_declaration=True)

    record = {
        "schema": 1, "profile": "p105", "architecture": "armv7h",
        "omarchy_commit": commit, "keyboard_sha256": sha(keyboard),
        "omafox_xpi_sha256": sha(xpi), "support_manifest_sha256": sha(support_manifest),
        "native_panel": [768, 1024],
        "logical_scale": 1, "menu": menu_adaptation, "keyboard_bridge": keyboard_bridge,
        "firefox_defaults": firefox_defaults,
        "renderer": {"labwc": "pixman", "qtquick": "software"},
        "symlinks": links(target),
        "scope": "Omarchy A desktop payload; boot and hardware runtime supplied separately",
    }
    (target / RECEIPT).write_text(json.dumps(record, indent=2) + "\n")
    (target / MANIFEST).write_text(json.dumps(file_manifest(target), indent=2) + "\n")
    verify(target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    parser.add_argument("--upstream", type=Path)
    parser.add_argument("--keyboard", type=Path)
    parser.add_argument("--keyboard-sha256")
    parser.add_argument("--support", type=Path, help="output from p105/build-support")
    parser.add_argument("--omafox-xpi", type=Path,
                        default=DESKTOP / "arm64/inputs/@omafox.xpi")
    args = parser.parse_args()
    try:
        if args.verify:
            verify(args.verify.resolve())
        else:
            stage(args)
    except (OSError, KeyError, ValueError, subprocess.CalledProcessError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
