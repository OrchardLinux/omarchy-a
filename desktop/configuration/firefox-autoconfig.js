// Omarchy A: load /usr/lib/firefox/omarchy-a.cfg (Firefox AutoConfig).
pref("general.config.filename", "omarchy-a.cfg");
pref("general.config.obscure_value", 0);
// omarchy-a.cfg registers a stylesheet, which needs the unsandboxed AutoConfig.
pref("general.config.sandbox_enabled", false);
