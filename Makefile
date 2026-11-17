# Omarchy A's own files, as the omarchy-a package installs them. The recipe
# (OrchardLinux/packages, packages/omarchy-a/arch/PKGBUILD) fetches the pinned
# sources and runs, in this tree:
#
#   make WVKBD=<wvkbd 0.20 source> WTYPE=<wtype 0.4 source>
#   make install DESTDIR=<root> OMARCHY=<upstream Omarchy at desktop/upstream.lock> DBUS_NEXT=<unpacked dbus-next 0.2.3 wheel>
#
# The only compiles are the on-screen keyboard (wvkbd with this repository's
# patches) and the startup cursor helper (wtype); desktop/install-tree puts
# every file in place.

BUILD ?= build
CC ?= cc
CFLAGS ?= -O2
PKG_CONFIG ?= pkg-config

all: $(BUILD)/wvkbd-mobintl $(BUILD)/wtype

$(BUILD)/wvkbd-mobintl:
	@test -d "$(WVKBD)" || { echo 'Set WVKBD to the wvkbd v0.20 source' >&2; exit 1; }
	@grep -q preferred_buffer_scale /usr/include/wayland-client-protocol.h || \
		{ echo 'Wayland headers lack the required surface scale events' >&2; exit 1; }
	rm -rf $(BUILD)/wvkbd
	mkdir -p $(BUILD)
	cp -R "$(WVKBD)" $(BUILD)/wvkbd
	patch --batch --fuzz=0 -d $(BUILD)/wvkbd -p1 < desktop/keyboard/wvkbd-0.20.patch
	patch --batch --fuzz=0 -d $(BUILD)/wvkbd -p1 < desktop/keyboard/wvkbd-0.20-layout.patch
	$(MAKE) -C $(BUILD)/wvkbd wvkbd-mobintl
	cp $(BUILD)/wvkbd/wvkbd-mobintl $@

$(BUILD)/wtype:
	@test -d "$(WTYPE)" || { echo 'Set WTYPE to the wtype 0.4 source' >&2; exit 1; }
	rm -rf $(BUILD)/wtype-source
	mkdir -p $(BUILD)
	cp -R "$(WTYPE)" $(BUILD)/wtype-source
	cd $(BUILD)/wtype-source && \
		wayland-scanner private-code protocol/virtual-keyboard-unstable-v1.xml virtual-keyboard-unstable-v1-protocol.c && \
		wayland-scanner client-header protocol/virtual-keyboard-unstable-v1.xml virtual-keyboard-unstable-v1-client-protocol.h && \
		$(CC) $(CPPFLAGS) $(CFLAGS) '-DVERSION="0.4"' -I. main.c virtual-keyboard-unstable-v1-protocol.c \
			$$($(PKG_CONFIG) --cflags --libs wayland-client wayland-cursor xkbcommon) -lrt $(LDFLAGS) -o ../wtype
	# Its license, with the virtual keyboard protocol's notice.
	{ cat $(BUILD)/wtype-source/LICENSE; printf '\nVirtual keyboard protocol:\n\n'; \
	  sed -n '/<copyright>/,/<\/copyright>/{/copyright>/d;s/^[[:space:]]*//;p;}' \
	    $(BUILD)/wtype-source/protocol/virtual-keyboard-unstable-v1.xml; } > $(BUILD)/wtype.LICENSE

install: all
	@test -n "$(DESTDIR)" || { echo 'Set DESTDIR' >&2; exit 1; }
	desktop/install-tree "$(DESTDIR)" "$(BUILD)" "$(OMARCHY)" "$(DBUS_NEXT)"

clean:
	rm -rf $(BUILD)

.PHONY: all install clean
