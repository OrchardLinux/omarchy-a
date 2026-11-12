/* SPDX-License-Identifier: MIT
 * Generated-by: LLM
 * Bounded by the caller. Exercise the same GBM/KMS allocation used by stock
 * wlroots, import it on the render GPU, clear and read it back without modesetting.
 */
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <gbm.h>
#include <fcntl.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#define CHECK(x) do { if (!(x)) { fprintf(stderr, "GPU-PROBE failed: %s\n", #x); return 1; } } while (0)
int main(int argc, char **argv)
{
    CHECK(argc == 3);
    int render = open(argv[1], O_RDWR | O_CLOEXEC);
    int kms = open(argv[2], O_RDWR | O_CLOEXEC);
    CHECK(render >= 0 && kms >= 0);
    struct gbm_device *gpu = gbm_create_device(render), *display = gbm_create_device(kms);
    CHECK(gpu && display);
    EGLDisplay dpy = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gpu, NULL);
    CHECK(dpy != EGL_NO_DISPLAY && eglInitialize(dpy, NULL, NULL));
    CHECK(eglBindAPI(EGL_OPENGL_ES_API));
    EGLConfig cfg;
    EGLint count;
    const EGLint attrs[] = {EGL_RENDERABLE_TYPE, EGL_OPENGL_ES2_BIT, EGL_NONE};
    CHECK(eglChooseConfig(dpy, attrs, &cfg, 1, &count) && count == 1);
    const EGLint ca[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};
    EGLContext ctx = eglCreateContext(dpy, cfg, EGL_NO_CONTEXT, ca);
    CHECK(ctx != EGL_NO_CONTEXT && eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx));
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    CHECK(renderer && strstr(renderer, "zink") && strstr(renderer, "PowerVR"));
    struct gbm_bo *bo = gbm_bo_create(display, 32, 32, GBM_FORMAT_XRGB8888,
                                    GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING | GBM_BO_USE_LINEAR);
    CHECK(bo);
    int dma = gbm_bo_get_fd(bo);
    CHECK(dma >= 0);
    const EGLint ia[] = {EGL_WIDTH, 32, EGL_HEIGHT, 32,
        EGL_LINUX_DRM_FOURCC_EXT, GBM_FORMAT_XRGB8888,
        EGL_DMA_BUF_PLANE0_FD_EXT, dma, EGL_DMA_BUF_PLANE0_OFFSET_EXT, 0,
        EGL_DMA_BUF_PLANE0_PITCH_EXT, (EGLint)gbm_bo_get_stride(bo), EGL_NONE};
    PFNEGLCREATEIMAGEKHRPROC create = (void *)eglGetProcAddress("eglCreateImageKHR");
    PFNEGLDESTROYIMAGEKHRPROC destroy = (void *)eglGetProcAddress("eglDestroyImageKHR");
    PFNGLEGLIMAGETARGETRENDERBUFFERSTORAGEOESPROC storage =
        (void *)eglGetProcAddress("glEGLImageTargetRenderbufferStorageOES");
    CHECK(create && destroy && storage);
    EGLImageKHR image = create(dpy, EGL_NO_CONTEXT, EGL_LINUX_DMA_BUF_EXT, NULL, ia);
    CHECK(image != EGL_NO_IMAGE_KHR);
    GLuint rb, fb;
    glGenRenderbuffers(1, &rb); glBindRenderbuffer(GL_RENDERBUFFER, rb);
    storage(GL_RENDERBUFFER, image);
    glGenFramebuffers(1, &fb); glBindFramebuffer(GL_FRAMEBUFFER, fb);
    glFramebufferRenderbuffer(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_RENDERBUFFER, rb);
    CHECK(glCheckFramebufferStatus(GL_FRAMEBUFFER) == GL_FRAMEBUFFER_COMPLETE);
    glViewport(0, 0, 32, 32); glClearColor(1, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    unsigned char pixel[4] = {0};
    glReadPixels(16, 16, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel); glFinish();
    CHECK(glGetError() == GL_NO_ERROR && pixel[0] > 250 && pixel[1] < 5 && pixel[2] < 5);
    printf("GPU-PROBE PASS renderer=%s render=%s kms=%s\n", renderer, argv[1], argv[2]);
    glDeleteFramebuffers(1, &fb); glDeleteRenderbuffers(1, &rb); destroy(dpy, image);
    close(dma); gbm_bo_destroy(bo);
    eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(dpy, ctx); eglTerminate(dpy);
    gbm_device_destroy(display); gbm_device_destroy(gpu); close(kms); close(render);
    return 0;
}
