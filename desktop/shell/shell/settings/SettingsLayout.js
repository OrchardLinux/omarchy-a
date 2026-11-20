// Where each setting lives in the Settings window: sections, their groups
// and rows, in the order a person looks for them. What a row does comes from
// the Omarchy menu (omarchy-menu.jsonc): a row names a menu entry and takes
// its label, icon, `when`, `checked` and action from there, so the menu and
// Settings never disagree about what a setting does. Settings only decides
// where it lives.
//
// A row is one of:
//   { entry: "<menu id>" }            the entry as it is: a submenu opens as a
//                                     page (a list to pick one from when its
//                                     children carry `checked`), an action runs
//   { entry: "<menu id>", page: "<native page>" }
//                                     the entry, shown by Settings' own page
//   { toggle: ["<turns on>", "<turns off>"], label: "<i18n key>" }
//                                     a menu pair (X On / X Off, each shown
//                                     while it would change something) as one
//                                     switch: on while the second is shown
//   { page: "<native page>", label: "<i18n key>", icon: "<glyph>" }
//                                     a Settings page with no menu entry
// and may add `value: "<command>"`, whose first line is the row's current
// value where the entry itself does not say it.
//
// A section is { id, label, icon or iconEntry, groups: [{ label, rows }] },
// or a menu's children as they are (`menu`, Learn); `startsGroup` puts a
// gap before it in the list, as the sections fall into kinds;
// a group's label is an i18n key, or "" for none. `card` puts the row at the
// top of the section as a large card (the theme).

var SECTIONS = [
  {
    id: "general",
    label: "settings.general",
    iconEntry: "setup",
    groups: [
      { label: "", rows: [
        { entry: "setup.language" },
        { entry: "update.timezone" },
        { entry: "update.time" }
      ] },
      { label: "settings.network", rows: [
        { entry: "setup.network.dns" },
        { entry: "setup.network.qr" },
        { entry: "trigger.tests.network-speedtest" }
      ] },
      { label: "", rows: [
        { entry: "setup.config" },
        { entry: "trigger.tests.disk-speedtest" }
      ] },
      { label: "settings.advanced", rows: [
        { entry: "setup.direct-boot" },
        { entry: "setup.reset" }
      ] }
    ]
  },
  {
    id: "appearance",
    label: "settings.appearance",
    iconEntry: "appearance",
    groups: [
      { label: "", card: true, rows: [
        { entry: "appearance.theme", page: "theme", value: "omarchy-theme-current" }
      ] },
      { label: "settings.style", rows: [
        { entry: "appearance.background", page: "background",
          value: "f=$(readlink -f ~/.local/state/omarchy/current/background 2>/dev/null) && f=${f##*/} && f=${f%.*} && f=${f#[0-9]-} && f=${f#[0-9][0-9]-} && echo \"${f//-/ }\"" },
        { entry: "appearance.font", value: "omarchy-font-current" },
        { entry: "appearance.icons", page: "icons", value: "omarchy-icons-current" },
        { entry: "appearance.unlock" },
        { toggle: ["appearance.animations-on", "appearance.animations-off"], label: "settings.animations" }
      ] },
      { label: "settings.launcher", rows: [
        { toggle: ["trigger.toggle.launcher-frosted", "trigger.toggle.launcher-opaque"], label: "settings.frostedLauncher" }
      ] },
      { label: "settings.bar", rows: [
        { toggle: ["appearance.top-bar.show", "appearance.top-bar.hide"], label: "settings.showBar" },
        { entry: "appearance.top-bar.position", value: "omarchy-bar position" },
        { entry: "appearance.top-bar.background" },
        { toggle: ["appearance.top-bar.indicators.battery-percentage-on", "appearance.top-bar.indicators.battery-percentage-off"], label: "settings.batteryPercentage" },
        { entry: "appearance.top-bar.indicators.clock" }
      ] },
      { label: "settings.windows", rows: [
        { toggle: ["appearance.windows.gaps-on", "appearance.windows.gaps-off"], label: "settings.windowGaps" },
        { entry: "appearance.windows.corners" },
        { entry: "appearance.windows.transparency" },
        { toggle: ["appearance.windows.one-window-ratio-on", "appearance.windows.one-window-ratio-off"], label: "settings.oneWindowRatio" }
      ] },
      { label: "settings.workspace", rows: [
        { entry: "appearance.workspace-layout" },
        { entry: "appearance.dock" }
      ] },
      { label: "settings.branding", rows: [
        { entry: "appearance.branding.screensaver" },
        { entry: "appearance.branding.about" }
      ] }
    ]
  },
  {
    id: "display",
    label: "settings.display",
    icon: "󰍹",
    groups: [
      { label: "", rows: [
        { toggle: ["trigger.toggle.nightlight-on", "trigger.toggle.nightlight-off"], label: "settings.nightLight" },
        { entry: "setup.monitors" },
        { toggle: ["trigger.hardware.laptop-display-on", "trigger.hardware.laptop-display-off"], label: "settings.builtInDisplay" },
        { toggle: ["trigger.hardware.mirror-display-on", "trigger.hardware.mirror-display-off"], label: "settings.mirrorDisplays" },
        { toggle: ["trigger.hardware.hybrid-gpu-on", "trigger.hardware.hybrid-gpu-off"], label: "settings.hybridGpu" }
      ] }
    ]
  },
  {
    id: "keyboard",
    label: "settings.keyboard",
    iconEntry: "setup.keyboard",
    groups: [
      { label: "settings.keyboard", rows: [
        { entry: "setup.keyboard.inputs" },
        { entry: "setup.keyboard.input-methods" },
        { entry: "setup.keyboard.keybindings" },
        { entry: "setup.config.xcompose" },
        { entry: "setup.input" }
      ] },
      { label: "settings.touch", rows: [
        { toggle: ["trigger.hardware.touchscreen-on", "trigger.hardware.touchscreen-off"], label: "settings.touchscreen" },
        { toggle: ["trigger.hardware.touchpad-on", "trigger.hardware.touchpad-off"], label: "settings.touchpad" },
        { entry: "trigger.hardware.touchpad-haptics" }
      ] }
    ]
  },
  {
    id: "behaviour",
    label: "settings.behaviour",
    icon: "󰔡",
    groups: [
      { label: "", rows: [
        { toggle: ["trigger.toggle.maximize-windows-on", "trigger.toggle.maximize-windows-off"], label: "settings.maximizeWindows" },
        { toggle: ["trigger.toggle.screensaver-on", "trigger.toggle.screensaver-off"], label: "settings.screensaver" }
      ] }
    ]
  },
  {
    id: "notifications",
    label: "settings.notifications",
    icon: "󰂚",
    startsGroup: true,
    groups: [
      { label: "", rows: [
        { toggle: ["trigger.toggle.notifications-stack", "trigger.toggle.notifications-one"], label: "settings.stackNotifications" },
        { toggle: ["trigger.toggle.notifications-off", "trigger.toggle.notifications-on"], label: "settings.focus" }
      ] }
    ]
  },
  {
    id: "security",
    label: "settings.security",
    iconEntry: "setup.security",
    startsGroup: true,
    groups: [
      { label: "settings.signIn", rows: [
        { entry: "update.password.user" },
        { entry: "update.password.drive" },
        { entry: "setup.security.fingerprint" },
        { entry: "setup.security.fido2" },
        { entry: "setup.security.passwordless-sudo" }
      ] },
      { label: "settings.remoteAccess", rows: [
        { entry: "setup.security.sshd" },
        { entry: "setup.security.ssh-agent" },
        { entry: "setup.security.sudoless-docker" }
      ] },
      { label: "settings.debug", rows: [
        { toggle: ["trigger.toggle.crash-capture-on", "trigger.toggle.crash-capture-off"], label: "settings.crashCapture" }
      ] }
    ]
  },
  {
    id: "apps",
    label: "settings.apps",
    iconEntry: "install",
    startsGroup: true,
    groups: [
      { label: "settings.defaultApps", rows: [
        { entry: "setup.default.browser" },
        { entry: "setup.default.terminal" },
        { entry: "setup.default.editor" },
        { entry: "setup.default.dictation" }
      ] },
      { label: "", rows: [
        { entry: "install" },
        { entry: "remove" },
        { entry: "setup.plugin" }
      ] }
    ]
  },
  {
    id: "update",
    label: "settings.softwareUpdate",
    iconEntry: "update",
    groups: [
      { label: "", rows: [
        { entry: "update.omarchy" },
        { entry: "update.channel" },
        { entry: "update.kernel" },
        { entry: "update.firmware" },
        { entry: "update.themes" },
        { entry: "update.icons" }
      ] },
      { label: "settings.troubleshoot", rows: [
        { entry: "update.process" },
        { entry: "update.config" },
        { entry: "update.hardware" }
      ] }
    ]
  },
  {
    id: "learn",
    label: "settings.learn",
    iconEntry: "learn",
    menu: "learn",
    groups: [],
    startsGroup: true
  },
  {
    id: "about",
    label: "settings.about",
    iconEntry: "system.about",
    groups: [
      { label: "", rows: [
        { entry: "system.about" }
      ] }
    ],
    page: "about"
  }
]

// Menu entries that live elsewhere in the touch shell, so Settings does not
// place them: what you do now (launcher Actions), ending the session
// (launcher), apps, and the menu's own sections whose children are placed.
var ELSEWHERE = [
  "apps", "agent", "trigger", "system", "setup", "appearance", "update", "update.password",
  "setup.default", "setup.keyboard", "setup.security", "setup.network", "appearance.top-bar",
  "appearance.top-bar.indicators", "appearance.windows", "appearance.branding",
  "trigger.toggle", "trigger.hardware", "trigger.tests",
  "trigger.emoji", "trigger.clipboard-history", "trigger.reminder", "trigger.capture",
  "trigger.transcode", "trigger.share", "trigger.activity",
  "trigger.toggle.idle-lock-on", "trigger.toggle.idle-lock-off",
  "system.lock", "system.suspend", "system.hibernate", "system.logout", "system.reboot",
  "system.shutdown", "system.screensaver"
]

if (typeof module !== "undefined") module.exports = { SECTIONS: SECTIONS, ELSEWHERE: ELSEWHERE }
