#!/usr/bin/env python3
"""Apply verified AOP orientation codes to a labwc output and its touchscreen."""
import argparse
import json
import math
import os
import re
import shutil
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

MATRICES = {
    "normal": (1, 0, 0, 0, 1, 0),
    "90": (0, -1, 1, 1, 0, 0),
    "180": (-1, 0, 1, 0, -1, 1),
    "270": (0, 1, 0, -1, 0, 1),
}


def compose(rotation, baseline):
    a, b, c, d, e, f = rotation
    g, h, i, j, k, l = baseline
    return (a*g+b*j, a*h+b*k, a*i+b*l+c,
            d*g+e*j, d*h+e*k, d*i+e*l+f)


def touch_xml(original, device_name, matrix):
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    root = ET.fromstring(original, parser=parser) if original else ET.Element("labwc_config")
    ns = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
    if root.tag != ns + "labwc_config":
        raise ValueError("unexpected labwc XML root")
    group = root.find(ns + "libinput")
    if group is None:
        group = ET.SubElement(root, ns + "libinput")
    matches = [node for node in group.findall(ns + "device")
               if node.get("category", "").casefold() == device_name.casefold()]
    device = matches[-1] if matches else ET.SubElement(group, ns + "device", category=device_name)
    calibration = device.find(ns + "calibrationMatrix")
    if calibration is None:
        calibration = ET.SubElement(device, ns + "calibrationMatrix")
    calibration.text = " ".join(format(x, ".9g") for x in matrix)
    ET.indent(root, space="  ")
    return ET.tostring(root, encoding="utf-8", xml_declaration=True) + b"\n"


def base_matrix(config, rc):
    if "base_matrix" in config:
        return config["base_matrix"]
    # Save the pre-rotation calibration on first use; subsequent daemon starts
    # must not compose a rotation onto the controller's own previous output.
    backup = rc.with_name(rc.name + ".before-aop-rotation")
    source = backup if backup.exists() else rc
    if source.exists():
        root = ET.fromstring(source.read_bytes())
        ns = root.tag.partition("}")[0] + "}" if root.tag.startswith("{") else ""
        for device in reversed(root.findall(ns + "libinput/" + ns + "device")):
            if device.get("category", "").casefold() == config["touch_device"].casefold():
                matrix = device.find(ns + "calibrationMatrix")
                if matrix is not None and matrix.text:
                    return tuple(map(float, matrix.text.split()))
    return MATRICES["normal"]


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = (path.stat().st_mode & 0o777) if path.exists() else 0o600
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as file:
            os.fchmod(file.fileno(), mode)
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def native_output(text, requested=None):
    outputs = []
    for section in re.split(r"(?=^\S)", text, flags=re.MULTILINE):
        name = re.match(r"^(\S+)\s+\"", section)
        if not name or "  Enabled: yes" not in section:
            continue
        if requested and name[1] != requested:
            continue
        if not re.search(r"\b(?:1536x2048|2048x1536) px,.*current", section):
            continue
        transform = re.search(r"^\s+Transform:\s+(\S+)", section, flags=re.MULTILINE)
        if transform:
            outputs.append((name[1], transform[1]))
    if len(outputs) != 1:
        raise ValueError("expected one enabled native iPad panel")
    return outputs[0]


def run(*args):
    return subprocess.run(args, check=True, capture_output=True, text=True, timeout=10).stdout


class Controller:
    def __init__(self, config, runner=run):
        if config.get("animate_rotation", False):
            raise ValueError("rotation animation is disabled: the software prototype stutters")
        self.config = config
        self.runner = runner
        self.rc = Path(config.get("labwc_config", "~/.config/labwc/rc.xml")).expanduser()
        self.baseline = tuple(base_matrix(config, self.rc))
        if len(self.baseline) != 6 or any(not math.isfinite(float(x)) for x in self.baseline):
            raise ValueError("base_matrix must have six finite numbers")
        self.baseline = tuple(map(float, self.baseline))

    def apply(self, transform):
        if transform not in MATRICES:
            raise ValueError("unsupported display transform")
        name, previous = native_output(self.runner("wlr-randr"), self.config.get("output"))
        original = self.rc.read_bytes() if self.rc.exists() else b""
        changed = touch_xml(original, self.config["touch_device"],
                            compose(MATRICES[transform], self.baseline))
        # Parse and prepare the complete input update before changing the display.
        backup = self.rc.with_name(self.rc.name + ".before-aop-rotation")
        if original and not backup.exists():
            backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(self.rc, backup)
        output_changed = False
        config_changed = False
        try:
            if previous != transform:
                self.runner("wlr-randr", "--output", name, "--transform", transform)
                output_changed = True
            if changed != original:
                atomic_write(self.rc, changed)
                config_changed = True
                self.runner("labwc", "--reconfigure")
        except Exception:
            if config_changed:
                if original:
                    atomic_write(self.rc, original)
                else:
                    self.rc.unlink(missing_ok=True)
                try:
                    self.runner("labwc", "--reconfigure")
                except Exception:
                    pass
            if output_changed:
                try:
                    self.runner("wlr-randr", "--output", name, "--transform", previous)
                except Exception:
                    pass
            raise
        print(f"output={name} transform={transform}; touch calibration updated", flush=True)


def orientation(path, now=None):
    now = time.time() if now is None else now
    stat = path.stat()
    if stat.st_size > 80 or not -2 <= now - stat.st_mtime <= 5:
        raise ValueError("orientation state is stale or invalid")
    fields = path.read_text().split()
    if len(fields) != 2:
        raise ValueError("invalid orientation state")
    code, timestamp = map(int, fields)
    if not 0 <= code <= 6 or timestamp < 0:
        raise ValueError("invalid orientation values")
    return code


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("~/.config/apple-aop/rotation.json").expanduser())
    parser.add_argument("--set", choices=MATRICES, help="apply one transform, then exit")
    args = parser.parse_args()
    config = json.loads(args.config.read_text())
    controller = Controller(config)
    if args.set:
        controller.apply(args.set)
        return
    mapping = config["codes"]
    if not mapping or any(str(int(k)) != k or not 0 <= int(k) <= 6 or v not in MATRICES
                          for k, v in mapping.items()):
        raise ValueError("codes must contain the physically verified orientation mapping")
    state = Path(config.get("state_file", "/run/apple-aop/orientation"))
    lock = Path("~/.config/apple-aop/rotation.lock").expanduser()
    applied = candidate = None
    since = 0.0
    while True:
        try:
            desired = None if lock.exists() else mapping.get(str(orientation(state)))
        except (OSError, ValueError):
            desired = None
        if desired is None:
            # Calibration can change the output while locked. Reapply the live
            # sensor state after unlocking, even when its code has not changed.
            applied = None
        if desired != candidate:
            candidate, since = desired, time.monotonic()
        if desired and desired != applied and time.monotonic() - since >= 0.4:
            try:
                controller.apply(desired)
                applied = desired
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                print(f"rotation deferred: {error}", flush=True)
                time.sleep(2)
        time.sleep(0.1)


if __name__ == "__main__":
    main()
