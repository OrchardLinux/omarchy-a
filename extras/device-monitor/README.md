# Optional device monitor

A small, read-only battery and system dashboard for Omarchy A. It uses only
Python's standard library and does not change the image build or enable a
service by default. The interface is available in English and Simplified Chinese.

## What it records

- Battery capacity, status, signed net current, voltage, temperature, and
  Lightning power-source/input-limit readings exposed by Orchard's drivers.
- CPU utilization and load, available/used memory and swap, root filesystem
  capacity and partition I/O, active network interface counters, and uptime.
- One sample per minute: 24 hours of system history and seven days of battery
  history in SQLite. Existing battery samples survive the additive table setup.

CPU percentages cover all cores (100% means all cores busy). Disk I/O covers the
root partition, not the whole device. Network counters prefer active physical
interfaces; when none exist they fall back to eligible active interfaces.
Missing sensors display as unavailable. Initial rates require two readings.

Charts offer 1/6/24-hour windows, with four-minute averages for the 24-hour view.
Peaks come from the raw minute samples, not instantaneous events. Reboots,
interface changes, counter resets and gaps over 150 seconds are excluded from
traffic/I/O totals and shown as breaks. History starts when monitoring is enabled.

## Install on the tablet

From this directory, on a running Omarchy A system with Python 3 and systemd:

```sh
getent passwd ipad-battery-monitor >/dev/null || sudo useradd --system --user-group --no-create-home --shell /usr/bin/nologin ipad-battery-monitor
sudo install -d -m 0755 /opt/ipad-battery-monitor
sudo install -m 0644 battery-monitor.py system_telemetry.py index.html index.zh-CN.html /opt/ipad-battery-monitor/
sudo install -m 0644 ipad-battery-monitor.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now ipad-battery-monitor.service
```

Open <http://127.0.0.1:3001/> on the tablet, or use an SSH forward from another
computer (`tablet` is the default Omarchy A account):

```sh
ssh -N -L 3001:127.0.0.1:3001 tablet@TABLET_ADDRESS
```

Then open the same localhost URL on that computer. `/zh-CN` opens the Chinese
page. `/health` returns a minimal service check; `/api/battery?view=current`
returns current readings without querying historical rows. Use
`/api/battery?hours=1`, `6`, or `24` for history, summaries and current readings.

The server and unit bind to loopback by default. There is no built-in login or
TLS: keep it behind SSH or an authenticated reverse proxy. Do not expose the
bare port directly to the internet. The unit restricts networking to localhost;
changing the bind address alone does not enable remote access.

Configuration environment variables: `BATTERY_BIND` (127.0.0.1),
`BATTERY_PORT` (3001), `BATTERY_DATABASE`
(`/var/lib/ipad-battery-monitor/history.sqlite3`) and `BATTERY_POWER_PATH`
(`/sys/class/power_supply`). The last is useful for sensor fixtures in tests.
Battery and Lightning supply names currently match the J71b Orchard driver;
other devices may expose different supply names and need adaptation.

```sh
sudo systemctl status ipad-battery-monitor
sudo journalctl -u ipad-battery-monitor --since '10 minutes ago'
sudo systemctl disable --now ipad-battery-monitor  # stop; preserves history
```

## Resource use and privacy

The service reads `/proc` and `/sys` counters. It performs no speed tests,
collects no process lists, IP addresses or user content, and cannot control
charging, drivers or power limits. Internal boot IDs and interface names are
stored only to distinguish counter continuity. HTTP request logging is disabled.

Current readings are cached for five seconds and polled by the page every
20 seconds. History refreshes every five minutes, is cached briefly, and is
bounded by retention. Background tabs stop polling. Charts render in the client.
The service has an eight-request thread limit, a 64 MiB memory limit and a
10% single-core CPU quota. It runs as a dedicated unprivileged account with
a private state directory. Sampling commits share one long-lived SQLite
connection to avoid a checkpoint on every close.

On a J71b (A10, two cores, approximately 2 GiB RAM), a previous deployment of
this collector/dashboard used 0.094 CPU seconds over a 60-second observation
(about 0.16% of one core), with approximately 29 MiB process RSS. An isolated
1,440-row fixture added about 240 KiB to the main database for the system table;
this excludes battery rows and WAL space. These are short observations and a
synthetic storage test, not a 24-hour soak or a guarantee under concurrent load.
The English page and loopback-default packaging added here have not been
separately reinstalled on hardware; the earlier Chinese deployment was used
to check live sensor readings, chart rendering and phone layout.

## Tests

From the repository root:

```sh
python3 -m unittest discover -s tests -p test_device_monitor.py -v
```

The standard repository test command also discovers these tests. They use
temporary databases and sensor fixtures, never the tablet's real history.
