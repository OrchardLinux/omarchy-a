// SPDX-License-Identifier: GPL-2.0-only OR MIT
/* Synthetic AFK records only. This executable never opens the DMA device. */
#define main aop_daemon_main
#include "aop.c"
#undef main
#include <assert.h>

static uint8_t ring[448];

static void put32(unsigned offset, uint32_t value)
{
	memcpy(ring + offset, &value, sizeof(value));
}

static void setup(void)
{
	memset(afk, 0, sizeof(afk));
	memset(ring, 0, sizeof(ring));
	managed_error = 0;
	managed_code = -1;
	managed_state_path = NULL;
	afk[0x36].confirmed = afk[0x36].rx_ready = 1;
	afk[0x36].cpu = ring;
	afk[0x36].rx_size = sizeof(ring);
	put32(0, 256);
	put32(128, 128);
	put32(192, 0x20504f41);
	put32(196, 50);
	put32(200, 0x10000010);
	ring[208] = 2;
	put32(224, 10);
	ring[228] = 2;
	ring[230] = 0xc4;
	ring[248] = 2;
	ring[249] = 3;
	put32(250, 123);
}

int main(void)
{
	setup();
	managed_poll();
	assert(!managed_error && managed_code == 3 && managed_stamp == 123);
	assert(read_le32(ring + 64) == 128);
	setup();
	put32(196, 999);
	managed_poll();
	assert(managed_error && managed_code == -1);
	setup();
	put32(64, 3);
	managed_poll();
	assert(managed_error);
	setup();
	afk[0x36].rx_size = 64;
	managed_poll();
	assert(managed_error);
	setup();
	ring[249] = 7;
	managed_poll();
	assert(managed_error && managed_code == -1);
	puts("AOP synthetic protocol checks passed");
	return 0;
}
