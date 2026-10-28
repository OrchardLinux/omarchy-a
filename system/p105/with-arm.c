/* SPDX-License-Identifier: MIT */
/* Keep the ARM handler in the build container's user and mount namespaces. */
#include <stdio.h>
#include <sys/mount.h>
#include <sys/stat.h>
#include <unistd.h>

int main(int argc, char **argv) {
    if (argc < 2) return 2;
    if (mkdir("/run/omarchy-binfmt", 0700)) {
        perror("create build binfmt directory");
        return 1;
    }
    if (mount("binfmt_misc", "/run/omarchy-binfmt", "binfmt_misc",
              MS_NOSUID | MS_NODEV, 0)) {
        perror("mount build binfmt");
        return 1;
    }
    FILE *stream = fopen("/run/omarchy-binfmt/register", "w");
    if (!stream) { perror("open build binfmt"); return 1; }
    const char *entry = ":omarchy-armv7:M::"
        "\\x7fELF\\x01\\x01\\x01\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x00\\x02\\x00\\x28\\x00:"
        "\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\x00\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xff\\xfe\\xff\\xff\\xff:"
        "/usr/libexec/omarchy-build/qemu-arm:PF";
    if (fputs(entry, stream) < 0 || fclose(stream)) {
        perror("register build ARM handler");
        return 1;
    }
    execvp(argv[1], argv + 1);
    perror("execute ARM build");
    return 1;
}
