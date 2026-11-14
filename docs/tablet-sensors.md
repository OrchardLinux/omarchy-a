# Tablet light and orientation

Orientation already comes from iio-sensor-proxy and the kernel's accelerometer mount matrix. Labwc maps touch to the panel, so display and touch rotate together. This remains the native orientation path; no extra board matrix or second sensor reader is installed.

The Display panel's Rotation Lock and `omarchy-rotation-lock on|off|toggle|status` use the same lock as the orientation helper. While locked the helper keeps watching; after unlock it applies the last settled pose even without a new sensor event. Undefined/flat poses stay ignored and the existing half-second settling remains. The helper exits with labwc.

Auto Brightness uses the existing tablet ALS curve, smoothing, hysteresis, ramp and manual-change pause policy. It is **off by default** because panel/light calibration still needs device validation. Enable it with the Auto Brightness switch in the Display panel, or:

```sh
omarchy-auto-brightness on
omarchy-auto-brightness status
omarchy-auto-brightness off
```

It reads generic IIO lux or iio-sensor-proxy. Missing sensors are harmless; the switch appears when an IIO light sensor and panel exist. Its process follows the compositor lifetime. Logs are in `$XDG_RUNTIME_DIR/arch-ipad-auto-brightness.log`; `--list` shows discovery and `--probe 20` computes a dry run without backlight writes.

User preferences live in `~/.config/omarchy/als-brightness.conf` and the switch is saved in `~/.local/state/omarchy/display`. Optional configuration keys are `enabled`, `backlight`, `curve`, `min_pct`, `max_pct`, `lux_scale`, `smooth_secs`, `hysteresis`, `min_pct_step`, `min_interval`, `ramp_pct_per_s`, `override_secs`, and `poll_hz`. The default curve is `0:10, 5:18, 20:30, 80:50, 250:70, 700:90, 1500:100` (lux:percent). Readings pass through a five-sample median and log-lux smoothing. Manual changes pause automatic adjustment for 30 seconds.

Automatic writes use omarchy-powerd's control socket, serialized with its existing screen/sleep/wake state machine. The request names the panel and supplies the expected old raw value. Powerd accepts only positive, in-range levels for that panel while lit and rejects stale values. A dark panel, unavailable power daemon or manual edit therefore stops a ramp. Wake still restores the level through powerd before automatic adjustment resumes. No brightnessctl helper, root user daemon or passwordless brightness sudo rule is added.

Both fresh desktop staging and the public-root builder include the helper and its CLI command. A running install needs those files plus the updated power daemon; restart omarchy-powerd and log into a fresh labwc session. Preserve local autostart/menu edits when applying by hand. The power daemon remains the sole owner of screen-off and sleep.

Host checks cover the retained light policy, switch state, missing power daemon, stale-value/dark-panel refusal, manual pause, actual socket writes, rotation debounce/lock/unlock and compositor exit, plus staging and public-root inclusion. Physical lux response, all four orientation directions, touch mapping and power-button/idle/sleep coexistence still need a device run.

