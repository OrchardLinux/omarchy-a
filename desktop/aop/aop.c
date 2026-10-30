// SPDX-License-Identifier: GPL-2.0-only OR MIT
/* J71b AOP orientation daemon. All DMA is owned by apple-aop-dma. */
#include <stdint.h>
#include <sys/random.h>
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/ioctl.h>
#include <sys/mman.h>
#include <unistd.h>
#include "aop_dma.h"

#define A7IOP_SIZE	0x20000UL	/* ADT says 0x1c000; rounded to 16K pages */
#define SRAM_SIZE	0xA0000UL
#define CPU_CONTROL	0x0044
#define CPU_RUN		(1u << 4)
#define QUEUE_INIT_B	0x0c00
#define QUEUE_START_B	0x0c04
#define QUEUE_INIT_A	0x4000
#define QUEUE_START_A	0x4004
#define TX_STATUS	0x4008
#define RX_STATUS	0x4020
#define TX_MESSAGE	0x4010
#define RX_MESSAGE	0x4038
#define MBOX_ENABLE	(1u << 0)
#define MBOX_EMPTY	(1u << 17)
#define MBOX_ERROR	(3u << 18)

#define EP_SHIFT	56
#define PAYLOAD_MASK	((1ULL << EP_SHIFT) - 1)
#define MGMT_TYPE(m)	(((m) >> 52) & 0xf)
#define MGMT(type, v)	(((uint64_t)(type) << 52) | (v))
#define RTKIT_VERSION	12

static volatile uint8_t *io, *sram;
static int memfd;
static int managed_error, managed_apps_started, managed_code = -1;
static volatile sig_atomic_t stopping;
static uint64_t managed_ecid, managed_stamp;
static const char *managed_state_path;
static unsigned allocation_count;
static uint32_t read_le32(volatile uint8_t *p);
static void managed_poll(void);
static struct {
	unsigned long phys, size;
	void *cpu;
} system_buffers[5];
static unsigned syslog_entries, syslog_size;

static struct {
	unsigned long phys, size;
	unsigned tx_off, tx_size, rx_off, rx_size;
	void *cpu;
	int tx_ready, rx_ready, started, confirmed;
} afk[256];

static uint32_t rd(uint32_t off) { return *(volatile uint32_t *)(io + off); }
static void wr(uint32_t off, uint32_t v) { *(volatile uint32_t *)(io + off) = v; }
static uint64_t rdq(uint32_t off) { return *(volatile uint64_t *)(io + off); }
static void wrq(uint32_t off, uint64_t v) { *(volatile uint64_t *)(io + off) = v; }

static uint64_t counter(void)
{
	uint64_t v;
	__asm__ volatile("isb; mrs %0, cntvct_el0" : "=r"(v));
	return v;
}

static uint64_t freq(void)
{
	uint64_t v;
	__asm__ volatile("mrs %0, cntfrq_el0" : "=r"(v));
	return v;
}

static void *map_selector(unsigned selector, size_t length)
{
	void *p = mmap(NULL, length, PROT_READ | PROT_WRITE, MAP_SHARED,
		      memfd, (off_t)selector * AOP_DMA_PAGE_SIZE);
	if (p == MAP_FAILED) {
		perror("AOP MMIO mmap");
		exit(1);
	}
	return p;
}

static void *managed_alloc(unsigned long size, unsigned long *phys)
{
	struct aop_dma_alloc request = { .size = size };
	if (allocation_count == 64 || ioctl(memfd, AOP_DMA_ALLOC, &request)) {
		printf("coherent DMA allocation failed: %d\n", errno);
		managed_error = 1;
		return NULL;
	}
	void *p = mmap(NULL, request.size, PROT_READ | PROT_WRITE, MAP_SHARED,
		      memfd, request.index * AOP_DMA_PAGE_SIZE);
	if (p == MAP_FAILED) {
		printf("coherent DMA mmap failed: %d\n", errno);
		managed_error = 1;
		return NULL;
	}
	allocation_count++;
	*phys = request.address;
	printf("owned DMA: PA %#lx size %#llx\n", *phys, (unsigned long long)request.size);
	return p;
}

static int send(unsigned ep, uint64_t m)
{
	uint64_t t0 = counter(), hz = freq();
	uint32_t s;

	while (((s = rd(TX_STATUS)) & (MBOX_ENABLE | MBOX_ERROR | MBOX_EMPTY)) !=
	       (MBOX_ENABLE | MBOX_EMPTY)) {
		if (counter() - t0 > hz / 5) {
			printf("  TX not ready (status %#x); not sent: ep %#x %#llx\n", s, ep,
			       (unsigned long long)m);
			managed_error = 1;
			return -1;
		}
	}
	wrq(TX_MESSAGE, ((uint64_t)ep << EP_SHIFT) | (m & PAYLOAD_MASK));
	return 0;
}

/* AFK endpoints use only buffers allocated by the kernel DMA owner. */
static void answer_afk(unsigned ep, uint64_t m)
{
	unsigned type = (m >> 48) & 0xff;
	if (ep < 32)
		return;
	if (type == 0x80) {
		send(ep, 0xa0ULL << 48);
	} else if (type == 0x89) {
		unsigned long size = ((m >> 16) & 0xffff) * 64UL;
		unsigned long len = (size + 0x3fff) & ~0x3fffUL;
		if (afk[ep].phys || !size || len > 0x100000) {
			printf("    AFK ep %#x: duplicate/invalid allocation or pool exhausted\n", ep);
			managed_error = 1;
			return;
		}
		unsigned long phys;
		volatile uint32_t *buffer = managed_alloc(len, &phys);
		if (!buffer)
			return;
		for (unsigned long i = 0; i < len / 4; i++)
			buffer[i] = 0;
		__asm__ volatile("dsb sy" ::: "memory");
		afk[ep].phys = phys;
		afk[ep].cpu = (void *)buffer;
		afk[ep].size = size;
		printf("    AFK ep %#x: pool PA %#lx size %#lx\n", ep, afk[ep].phys, size);
		send(ep, (0xa1ULL << 48) | afk[ep].phys);
	} else if (type == 0x8a || type == 0x8b) {
		unsigned off = ((m >> 32) & 0xffff) * 64;
		unsigned size = ((m >> 16) & 0xffff) * 64;
		if (!afk[ep].phys || !size || off > afk[ep].size || size > afk[ep].size - off) {
			printf("    AFK ep %#x: invalid ring range\n", ep);
			managed_error = 1;
			return;
		}
		if (type == 0x8a) {
			afk[ep].tx_off = off; afk[ep].tx_size = size; afk[ep].tx_ready = 1;
		} else {
			afk[ep].rx_off = off; afk[ep].rx_size = size; afk[ep].rx_ready = 1;
		}
		printf("    AFK ep %#x %s: PA %#lx size %#x\n", ep,
		       type == 0x8a ? "TX" : "RX", afk[ep].phys + off, size);
		if (afk[ep].tx_ready && afk[ep].rx_ready && !afk[ep].started) {
			afk[ep].started = 1;
			send(ep, 0xa3ULL << 48);
		}
	} else if (type == 0x86) {
		afk[ep].confirmed = 1;
		printf("    AFK ep %#x: START acknowledged\n", ep);
	}
}

static void managed_system_rx(unsigned ep, uint64_t m)
{
	unsigned type = MGMT_TYPE(m);
	if (ep == 2 && type == 8) {
		syslog_entries = m & 0xff;
		syslog_size = (m >> 24) & 0xff;
		if (!syslog_entries || !syslog_size)
			managed_error = 1;
		return;
	}
	if (type != 1)
		return;
	if (system_buffers[ep].cpu) {
		printf("system ep %u repeated buffer request / firmware crash\n", ep);
		managed_error = 1;
		return;
	}
	unsigned long size = ((m >> 44) & 0xff) << 12;
	if (!size || (m & ((1ULL << 44) - 1))) {
		printf("unsupported system buffer size/address\n");
		managed_error = 1;
		return;
	}
	unsigned long phys;
	void *cpu = managed_alloc(size, &phys);
	if (!cpu)
		return;
	system_buffers[ep].cpu = cpu;
	system_buffers[ep].phys = phys;
	system_buffers[ep].size = size;
	if (ep == 2) {
		if (syslog_entries * (32 + syslog_size) > size) {
			managed_error = 1;
			return;
		}
	}
	__asm__ volatile("dsb sy" ::: "memory");
	if (send(ep, MGMT(1, ((uint64_t)(size >> 12) << 44) | phys)))
		managed_error = 1;
}

/* The handshake half of rtkit.c: reply to what the AOP says, nothing more. */
static void answer(uint64_t m, unsigned *epmap_done)
{
	static uint32_t endpoints[8];

	switch (MGMT_TYPE(m)) {
	case 1: {
		unsigned min = m & 0xffff, max = (m >> 16) & 0xffff;
		if (min > RTKIT_VERSION || max < RTKIT_VERSION) {
			managed_error = 1;
			printf("  version %u not in [%u,%u]; not replying\n", RTKIT_VERSION, min, max);
			return;
		}
		send(0, MGMT(2, ((uint64_t)RTKIT_VERSION << 16) | RTKIT_VERSION));
		break;
	}
	case 8: {
		unsigned base = (m >> 32) & 7;
		int last = !!(m & (1ULL << 51));
		endpoints[base] = (uint32_t)m;
		send(0, MGMT(8, ((uint64_t)base << 32) | (last ? 1ULL << 51 : 1)));
		if (!last)
			break;
		/* rtkit.c starts these system endpoints; without them RTKit won't boot. */
		static const unsigned sys[] = { 1, 2, 3, 4, 8 };
		for (unsigned i = 0; i < sizeof(sys) / sizeof(sys[0]); i++)
			if (endpoints[sys[i] / 32] & (1u << (sys[i] % 32)))
				send(0, MGMT(5, ((uint64_t)sys[i] << 32) | 2));
		/* Cold boot: rtkit.c now waits for the IOP's own power ack (type 7). */
		*epmap_done = 1;
		send(0, MGMT(6, 0x220));
		break;
	}
	case 7:
		if ((m & 0xff) == 0x20)
			send(0, MGMT(11, 0x20));	/* AP power state ON */
		break;
	case 11:
		if ((m & 0xffff) == 0x20 && !managed_apps_started) {
			managed_apps_started = 1;
			for (unsigned ep = 32; ep < 256; ep++)
				if (endpoints[ep / 32] & (1u << (ep % 32)))
					send(0, MGMT(5, ((uint64_t)ep << 32) | 2));
		}
		break;
	}
}

/* Point the image's p0CE patch variable (EC0 = __ETEXT) at phys. */
static int patch_p0ce(uint8_t *img, long size, uint64_t phys)
{
	for (long off = 0; off + 16 <= size; off += 4) {
		uint32_t *w = (uint32_t *)(img + off);
		if (w[0] == 0x45433070 && w[1] == 8) {
			w[2] = (uint32_t)phys;
			w[3] = (uint32_t)(phys >> 32);
			printf("patched p0CE @%#lx = %#llx\n", off, (unsigned long long)phys);
			return 0;
		}
	}
	printf("p0CE not found in image\n");
	return -1;
}

static long load_image(const char *path, uint8_t *img)
{
	long size = 0, got;
	int fd = open(path, O_RDONLY);

	while (fd >= 0 && (got = read(fd, img + size, SRAM_SIZE + 1 - size)) > 0)
		size += got;
	if (fd >= 0)
		close(fd);
	if (fd < 0 || size <= 0 || size > (long)SRAM_SIZE || size % 4) {
		printf("bad firmware %s (size %ld)\n", path, size);
		return -1;
	}
	return size;
}

static uint32_t read_le32(volatile uint8_t *p)
{
	return (uint32_t)p[0] | (uint32_t)p[1] << 8 | (uint32_t)p[2] << 16 | (uint32_t)p[3] << 24;
}

static void publish_orientation(void)
{
	char temporary[280], text[80];
	if (!managed_state_path || managed_code < 0)
		return;
	snprintf(temporary, sizeof(temporary), "%s.tmp", managed_state_path);
	int length = snprintf(text, sizeof(text), "%d %llu\n", managed_code,
			      (unsigned long long)managed_stamp);
	int fd = open(temporary, O_WRONLY | O_CREAT | O_TRUNC | O_NOFOLLOW, 0644);
	if (fd < 0) {
		managed_error = 1;
		return;
	}
	int failed = write(fd, text, length) != length;
	close(fd);
	if (failed || rename(temporary, managed_state_path))
		managed_error = 1;
}

static void managed_poll(void)
{
	for (unsigned ep = 32; ep < 256 && !managed_error; ep++) {
		if (!afk[ep].confirmed || !afk[ep].rx_ready || !afk[ep].cpu)
			continue;
		volatile uint8_t *ring = (uint8_t *)afk[ep].cpu + afk[ep].rx_off;
		unsigned extent = afk[ep].rx_size;
		if (extent < 256)
			goto bad_ring;
		unsigned size = read_le32(ring);
		if (!size || size >= extent || (extent - size) % 3)
			goto bad_ring;
		unsigned block = (extent - size) / 3;
		if (block < 64 || block % 64 || size % block)
			goto bad_ring;
		for (unsigned budget = 0; budget < 64; budget++) {
			unsigned rp = read_le32(ring + block), wp = read_le32(ring + 2 * block);
			__asm__ volatile("dmb sy" ::: "memory");
			if (rp >= size || wp >= size || rp % block || wp % block)
				goto bad_ring;
			if (rp == wp)
				break;
			unsigned available = wp > rp ? wp - rp : size - rp + wp;
			unsigned original = rp;
			volatile uint8_t *record = ring + 3 * block + rp;
			unsigned length = read_le32(record + 4);
			if (length > size - 16)
				goto bad_ring;
			if (length > size - rp - 16) {
				rp = 0;
				record = ring + 3 * block;
				length = read_le32(record + 4);
			}
			if (read_le32(record) != 0x20504f41 || length > size - rp - 16)
				goto bad_ring;
			unsigned next = ((rp + 16 + length + block - 1) / block * block) % size;
			unsigned used = next >= original ? next - original : size - original + next;
			if (!used || used > available)
				goto bad_ring;
			if (ep == 0x36 && length == 50 && read_le32(record + 8) == 0x10000010 &&
			    read_le32(record + 12) == 0 && record[16] == 2 && record[36] == 2 &&
			    read_le32(record + 32) == 10 && record[37] == 0 &&
			    record[38] == 0xc4 && record[39] == 0 && record[56] == 2) {
				unsigned code = record[57];
				if (code > 6)
					goto bad_ring;
				managed_code = code;
				managed_stamp = (uint64_t)read_le32(record + 58) |
						(uint64_t)read_le32(record + 62) << 32;
				printf("orientation code=%u timestamp=%llu\n", code,
				       (unsigned long long)managed_stamp);
				publish_orientation();
			}
			__asm__ volatile("dmb sy" ::: "memory");
			*(volatile uint32_t *)(ring + block) = next;
			if (block != 64)
				*(volatile uint32_t *)(ring + 64) = next;
		}
		continue;
bad_ring:
		printf("invalid AFK RX ring on endpoint %#x\n", ep);
		managed_error = 1;
	}
}

static void receive(void)
{
	managed_poll();
	for (unsigned budget = 0; budget < 256 && !managed_error; budget++) {
		uint32_t status = rd(RX_STATUS);
		if (status & MBOX_ERROR) {
			managed_error = 1;
			break;
		}
		if (status & MBOX_EMPTY)
			break;
		uint64_t word = rdq(RX_MESSAGE), message = word & PAYLOAD_MASK;
		unsigned ep = word >> EP_SHIFT, done = 0;
		if (ep == 0)
			answer(message, &done);
		else if (ep == 1 || ep == 2 || ep == 4)
			managed_system_rx(ep, message);
		else if (ep >= 32)
			answer_afk(ep, message);
		if ((ep == 4 && (MGMT_TYPE(message) == 8 || MGMT_TYPE(message) == 12)) ||
		    (ep == 2 && MGMT_TYPE(message) == 5))
			send(ep, message);
	}
}

static void stop_requested(int signal_number)
{
	(void)signal_number;
	stopping = 1;
}

static int boot_images(const char *main_path, const char *ext_path)
{
	static uint8_t image[SRAM_SIZE + 1], extension[SRAM_SIZE + 1];
	long size = load_image(main_path, image);
	if (size != 0x86d60 || memcmp(image + 0x86876, "GNRP", 4) ||
	    read_le32(image + 0x8687a) != 32 || memcmp(image + 0x8689e, "DICE", 4) ||
	    read_le32(image + 0x868a2) != 8 || memcmp(image + 0x868ae, "CNON", 4) ||
	    read_le32(image + 0x868b2) != 8 || load_image(ext_path, extension) != 0xa2a0)
		return 1;
	uint8_t entropy[40];
	size_t have = 0;
	while (have < sizeof(entropy)) {
		ssize_t got = getrandom(entropy + have, sizeof(entropy) - have, 0);
		if (got < 0 && errno == EINTR)
			continue;
		if (got <= 0)
			return 1;
		have += got;
	}
	memcpy(image + 0x8687e, entropy, 32);
	memcpy(image + 0x868a6, &managed_ecid, 8);
	memcpy(image + 0x868b6, entropy + 32, 8);
	memset(entropy, 0, sizeof(entropy));
	unsigned long physical;
	void *ext = managed_alloc(0xa2a0, &physical);
	if (!ext || patch_p0ce(image, size, physical))
		return 1;
	memcpy(ext, extension, 0xa2a0);
	for (unsigned long off = 0; off < SRAM_SIZE; off += 4)
		*(volatile uint32_t *)(sram + off) =
			off < (unsigned long)size ? *(uint32_t *)(image + off) : 0;
	for (unsigned long off = 0; off < (unsigned long)size; off += 4)
		if (*(volatile uint32_t *)(sram + off) != *(uint32_t *)(image + off))
			return 1;
	__asm__ volatile("dsb sy" ::: "memory");
	wr(QUEUE_INIT_A, 0x1111);
	wr(QUEUE_INIT_B, 0x1111);
	wr(QUEUE_START_A, 1);
	wr(QUEUE_START_B, 1);
	wr(QUEUE_START_A, 0x1000);
	wr(QUEUE_START_B, 0x1000);
	wr(RX_STATUS, rd(RX_STATUS) | MBOX_ENABLE);
	unsigned drained = 0;
	while (!(rd(RX_STATUS) & MBOX_EMPTY) && drained++ < 256)
		(void)rdq(RX_MESSAGE);
	if (!(rd(RX_STATUS) & MBOX_EMPTY))
		return 1;
	/* Preserve the working firmware cache settings and AOP timebase. */
	return ioctl(memfd, AOP_DMA_START) != 0;
}

int main(int argc, char **argv)
{
	if (argc != 4 || strlen(argv[3]) > 240) {
		fprintf(stderr, "usage: apple-aop-daemon MAIN EXT STATE\n");
		return 2;
	}
	setvbuf(stdout, NULL, _IOLBF, 0);
	uint8_t identity[9];
	int fd = open("/sys/firmware/devicetree/base/chosen/apple,ecid", O_RDONLY | O_CLOEXEC);
	ssize_t got = fd < 0 ? -1 : read(fd, identity, sizeof(identity));
	if (fd >= 0)
		close(fd);
	if (got != 8) {
		fprintf(stderr, "AOP requires the m1n1 ECID handoff\n");
		return 1;
	}
	for (unsigned i = 0; i < 8; i++)
		managed_ecid = (managed_ecid << 8) | identity[i];
	if (!managed_ecid)
		return 1;
	managed_state_path = argv[3];
	memfd = open("/dev/apple-aop-dma", O_RDWR | O_CLOEXEC);
	if (memfd < 0) {
		perror("AOP owner unavailable (a fresh boot is required after stopping)");
		return 1;
	}
	io = map_selector(AOP_DMA_MAP_IOP, A7IOP_SIZE);
	sram = map_selector(AOP_DMA_MAP_SRAM, SRAM_SIZE);
	signal(SIGTERM, stop_requested);
	signal(SIGINT, stop_requested);
	unlink(managed_state_path);
	if (boot_images(argv[1], argv[2]))
		return 1;
	uint64_t started = counter(), heartbeat = started, hz = freq();
	while (!managed_error && !stopping) {
		receive();
		uint64_t now = counter();
		if (now - started > 30 * hz && !afk[0x36].confirmed) {
			fprintf(stderr, "AOP orientation endpoint startup timed out\n");
			managed_error = 1;
		}
		if (now - heartbeat >= hz) {
			publish_orientation();
			heartbeat = now;
		}
		usleep(5000);
	}
	unlink(managed_state_path);
	/* Kernel release runs after the last mapping closes at process exit. */
	return managed_error ? 1 : 0;
}
