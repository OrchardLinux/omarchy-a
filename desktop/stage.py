#!/usr/bin/env python3
"""Stage desktop sources into a new Arch root directory; no device access.

This does not install packages, configure boot, or write an iPad filesystem.
The caller must create the tablet user (uid 1000), install packages, and chown
/home/tablet in the finished rootfs. The target must not already exist.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil

HERE = Path(__file__).resolve().parent
PORT = HERE / "shell"
CONFIG = HERE / "configuration"
INPUTS = json.loads((HERE / 'arm64/inputs.json').read_text())
XPI_SHA = INPUTS['omafox_xpi']


def checked(path, digest):
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest, path


def copy(src, dst, mode=None):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    if mode is not None:
        dst.chmod(mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", type=Path, help="new, nonexistent staging directory")
    parser.add_argument("--upstream", type=Path, required=True, help="pinned Omarchy source tree")
    parser.add_argument("--keyboard", type=Path, required=True, help="built wvkbd-mobintl binary")
    parser.add_argument("--keyboard-sha256", required=True, help="hash from the source-build manifest")
    parser.add_argument("--omafox-xpi", type=Path, required=True, help="signed Omafox extension")
    args = parser.parse_args()
    FORK, KEYBOARD, XPI = args.upstream, args.keyboard, args.omafox_xpi
    target = args.target.resolve()
    if target.exists() or target == Path("/") or target.is_relative_to(Path("/Volumes")):
        parser.error("target must be a new local staging directory, not an existing/mounted volume")
    checked(KEYBOARD, args.keyboard_sha256)
    checked(XPI, XPI_SHA)
    source = target / "home/tablet/.local/share/omarchy-ipad"
    # Copy shell sources and immutable upstream theme assets.
    shutil.copytree(PORT, source, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # Greeter assets are system-owned, never read from the user's home directory.
    greeter = target / "usr/share/omarchy-greeter"
    shutil.copytree(HERE / "greeter", greeter)
    # Copy trusted shared UI code, not the tablet user's mutable shell tree.
    for module in ("Commons", "Ui"):
        shutil.copytree(PORT / "shell" / module, greeter / module)
    for name in ("LockView.qml", "LockFeedSurface.qml"):
        copy(PORT / "shell/plugins/lock" / name, greeter / "plugins/lock" / name)
    # Overlay the upstream Jade Horse replacement without updating the whole UI pin.
    themes = source / "themes"
    shutil.copytree(FORK / "themes", themes, symlinks=True)
    shutil.rmtree(themes / "osaka-jade", ignore_errors=True)
    shutil.copytree(HERE / "themes/jade-horse", themes / "jade-horse", dirs_exist_ok=True)
    default = themes / "jade-horse"
    copy(default / "colors.toml", greeter / "default-theme/colors.toml")
    if (default / "shell.toml").is_file():
        copy(default / "shell.toml", greeter / "default-theme/shell.toml")
    backgrounds = sorted(p for p in (default / "backgrounds").iterdir()
                         if p.is_file() and p.suffix.lower() in (".webp", ".png", ".jpg", ".jpeg"))
    if not backgrounds:
        raise ValueError("default theme has no image background")
    copy(backgrounds[0], greeter / "default-theme/background")
    tmpfiles = target / "usr/lib/tmpfiles.d/omarchy-greeter-theme.conf"
    tmpfiles.parent.mkdir(parents=True, exist_ok=True)
    tmpfiles.write_text("d /var/lib/omarchy-greeter-theme 0755 tablet tablet -\n")
    (greeter / "labwc/autostart").chmod(0o755)
    copy(HERE / "greeter/greeter-session", target / "usr/local/libexec/omarchy-greeter-session", 0o755)
    copy(HERE / "greeter/greeter-wake", target / "usr/local/libexec/omarchy-greeter-wake", 0o755)
    keyboard = source / "trials/wvkbd-mobintl-v0.20-font18-special15-state"
    copy(KEYBOARD, keyboard, 0o755)
    for script in (source / "bin").iterdir():
        if script.is_file():
            script.chmod(0o755)
            link = target / "usr/local/bin" / script.name
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(Path("/home/tablet/.local/share/omarchy-ipad/bin") / script.name)
    config = target / "home/tablet/.config"
    mapping = {
        PORT / "config/omarchy/shell.json": config / "omarchy-ipad/shell.json",
        PORT / "labwc-rc.xml": config / "labwc/rc.xml",
        CONFIG / "labwc-autostart": config / "labwc/autostart",
        PORT / "foot/foot.ini": config / "foot/foot.ini",
        PORT / "fastfetch/config.jsonc": config / "fastfetch/config.jsonc",
        PORT / "starship/starship.toml": config / "starship.toml",
        CONFIG / "bashrc": target / "home/tablet/.bashrc",
        CONFIG / "bash_profile": target / "home/tablet/.bash_profile",
        PORT / "fontconfig/fonts.conf": config / "fontconfig/fonts.conf",
        PORT / "fastfetch/about.txt": config / "omarchy/branding/about.txt",
        PORT / "fastfetch/about-compact.txt": config / "omarchy/branding/about-compact.txt",
        CONFIG / "first-theme": target / "usr/local/libexec/arch-ipad-first-theme",
        CONFIG / "scale-output": target / "usr/local/libexec/arch-ipad-scale-output",
        CONFIG / "login-session": target / "usr/local/libexec/arch-ipad-login-session",
        CONFIG / "org.kde.dolphin.desktop": target / "home/tablet/.local/share/applications/org.kde.dolphin.desktop",
        CONFIG / "getty-autologin.conf": target / "etc/systemd/system/getty@tty1.service.d/arch-ipad-autologin.conf",
        CONFIG / "networkmanager.rules": target / "etc/polkit-1/rules.d/40-arch-ipad-networkmanager.rules",
        FORK / "applications/foot.desktop": target / "usr/local/share/applications/foot.desktop",
        XPI: target / "usr/lib/firefox/distribution/extensions/@omafox.xpi",
        CONFIG / "firefox-policies.json": target / "usr/lib/firefox/distribution/policies.json",
    }
    for src, dst in mapping.items():
        copy(src, dst)
    # Branding is static; kernel, memory and CPU information use live probes.
    assert "VM prototype" not in (config / "fastfetch/config.jsonc").read_text()
    # Offer Suspend only when the kernel-side charger PM contract is ready.
    menu = source / "default/omarchy/omarchy-menu.jsonc"
    original_menu = menu.read_text()
    stock_guard = '"when":"! omarchy-toggle-enabled suspend-off && ! omarchy-sleep-disabled"'
    assert original_menu.count(stock_guard) == 1
    menu.write_text(original_menu.replace(stock_guard, '"when":"command -v ipadlinux-suspend-ready >/dev/null && ipadlinux-suspend-ready"'))
    (config / "labwc/autostart").chmod(0o755)
    (target / "usr/local/libexec/arch-ipad-first-theme").chmod(0o755)
    (target / "usr/local/libexec/arch-ipad-scale-output").chmod(0o755)
    (target / "usr/local/libexec/arch-ipad-login-session").chmod(0o755)
    # Record a content hash for each staged payload file.
    files = sorted(p for p in target.rglob("*") if p.is_file() and not p.is_symlink())
    manifest = {str(p.relative_to(target)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    (target / "arch-ipad-ui-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"Staged {len(files)} files, {sum(p.stat().st_size for p in files):,} bytes at {target}")
    print("Not bootable: install signed Arch packages and integrate a frozen device boot bundle separately.")


if __name__ == "__main__":
    main()
