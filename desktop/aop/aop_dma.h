/* SPDX-License-Identifier: GPL-2.0-only OR MIT */
#ifndef J71B_AOP_DMA_H
#define J71B_AOP_DMA_H
#include <linux/types.h>
#include <linux/ioctl.h>

/* mmap offsets are selector * AOP_DMA_PAGE_SIZE; no physical addresses accepted. */
struct aop_dma_alloc {
	__u64 size;
	__u64 address;
	__u64 index;
};
#define AOP_DMA_START _IO('A', 2)
#define AOP_DMA_ALLOC _IOWR('A', 1, struct aop_dma_alloc)
#define AOP_DMA_MAP_IOP 0
#define AOP_DMA_MAP_SRAM 1
#define AOP_DMA_MAP_BUFFER 0x100
#define AOP_DMA_PAGE_SIZE 0x4000
#endif
