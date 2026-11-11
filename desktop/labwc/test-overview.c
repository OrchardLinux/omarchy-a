/* SPDX-License-Identifier: GPL-2.0-only */
#include <assert.h>
#include <stdio.h>
#include "overview-math.h"

static struct overview_grid
grid(int count, double width, double height)
{
    /* Maximised windows have the shape of the free area; gap 24, label 44. */
    return overview_grid(count, width, height, width / height, 24, 44);
}

int main(void)
{
    /* iPad landscape below the bar: 3 in 2 + 1, 8 in 3 + 3 + 2, 15 in 5 x 3 */
    struct overview_grid g = grid(3, 1024, 730);
    assert(g.cols == 2 && g.rows == 2);
    assert(overview_grid_row_length(&g, 3, 0) == 2 && overview_grid_row_length(&g, 3, 1) == 1);
    g = grid(8, 1024, 730);
    assert(g.cols == 3 && g.rows == 3 && overview_grid_row_length(&g, 8, 2) == 2);
    g = grid(15, 1024, 730);
    assert(g.cols == 5 && g.rows == 3);
    /* iPad portrait: 8 in 3 + 3 + 2 as well */
    g = grid(8, 768, 986);
    assert(g.cols == 3 && g.rows == 3);
    /* One window is not blown up to the whole screen. */
    g = grid(1, 1024, 730);
    assert(g.cols == 1 && g.pic_width <= 1024 * 0.6 + 1 && g.pic_height <= 730 * 0.6 + 1);
    /* Past 20 the cards stop shrinking and rows are added to scroll through. */
    struct overview_grid twenty = grid(20, 1024, 730), more = grid(27, 1024, 730);
    assert(more.cols == twenty.cols && more.pic_width == twenty.pic_width);
    assert(more.rows == (27 + more.cols - 1) / more.cols && more.rows > twenty.rows);
    assert(grid(0, 1024, 730).cols == 0);

    /* Four fingers: up or down together, not sideways, not a pinch. */
    assert(overview_swipe_decide(2, -10, 1) == OVERVIEW_SWIPE_WAIT);
    assert(overview_swipe_decide(3, -20, 2) == OVERVIEW_SWIPE_UP);
    assert(overview_swipe_decide(-4, 22, 2) == OVERVIEW_SWIPE_DOWN);
    assert(overview_swipe_decide(18, -20, 0) == OVERVIEW_SWIPE_WAIT); /* diagonal: not yet */
    assert(overview_swipe_decide(45, -5, 0) == OVERVIEW_SWIPE_REJECT);
    assert(overview_swipe_decide(0, -20, -50) == OVERVIEW_SWIPE_REJECT);

    /* Letting go: a flick decides, otherwise the nearer end. */
    assert(overview_swipe_settle(0.2, 2.0) == 1);
    assert(overview_swipe_settle(0.8, -2.0) == 0);
    assert(overview_swipe_settle(0.6, 0.1) == 1);
    assert(overview_swipe_settle(0.4, 0.0) == 0);
    puts("overview math: ok");
    return 0;
}
