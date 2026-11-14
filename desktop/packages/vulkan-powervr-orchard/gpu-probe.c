/* SPDX-License-Identifier: MIT
 * Generated-by: LLM
 *
 * gpu-probe RENDER-NODE DISPLAY-CARD
 *
 * Does what Labwc's GLES2 renderer does for one frame, without modesetting:
 * opens EGL on the render node, allocates one output buffer of the display's
 * size there, draws into it, reads it back, and hands the buffer to the
 * display controller as a framebuffer. Exits 0 only if all of that worked and
 * the renderer is not a software one. The caller bounds the run time and sets
 * the environment the desktop would run with.
 */
#define _GNU_SOURCE
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES2/gl2.h>
#include <GLES2/gl2ext.h>
#include <drm_fourcc.h>
#include <fcntl.h>
#include <gbm.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include <xf86drm.h>
#include <xf86drmMode.h>

#define CHECK(x) do { if (!(x)) { fprintf(stderr, "GPU-PROBE FAIL: %s\n", #x); return 1; } } while (0)

static const EGLint context_attrs[] = {EGL_CONTEXT_CLIENT_VERSION, 2, EGL_NONE};

/* wlroots' order: the EGL device that is this DRM node, then GBM. */
static EGLContext open_egl(int render, struct gbm_device *gbm, int use_device, EGLDisplay *dpy)
{
    *dpy = EGL_NO_DISPLAY;
    if (use_device) {
        const char *client = eglQueryString(EGL_NO_DISPLAY, EGL_EXTENSIONS);
        if (!client || !strstr(client, "EGL_EXT_device_enumeration") || !strstr(client, "EGL_EXT_platform_device"))
            return EGL_NO_CONTEXT;
        PFNEGLQUERYDEVICESEXTPROC devices = (void *)eglGetProcAddress("eglQueryDevicesEXT");
        PFNEGLQUERYDEVICESTRINGEXTPROC string = (void *)eglGetProcAddress("eglQueryDeviceStringEXT");
        drmDevice *node = NULL;
        EGLDeviceEXT list[16];
        EGLint count = 0;
        if (!devices || !string || drmGetDevice2(render, 0, &node) || !devices(16, list, &count)) return EGL_NO_CONTEXT;
        for (EGLint i = 0; i < count && *dpy == EGL_NO_DISPLAY; i++) {
            const char *extensions = string(list[i], EGL_EXTENSIONS);
            const char *file = extensions && strstr(extensions, "EGL_EXT_device_drm") ?
                string(list[i], EGL_DRM_DEVICE_FILE_EXT) : NULL;
            for (int n = 0; file && n < DRM_NODE_MAX; n++)
                if ((node->available_nodes & (1 << n)) && !strcmp(node->nodes[n], file))
                    *dpy = eglGetPlatformDisplay(EGL_PLATFORM_DEVICE_EXT, list[i], NULL);
        }
        drmFreeDevice(&node);
    } else {
        *dpy = eglGetPlatformDisplay(EGL_PLATFORM_GBM_KHR, gbm, NULL);
    }
    if (*dpy == EGL_NO_DISPLAY || !eglInitialize(*dpy, NULL, NULL)) return EGL_NO_CONTEXT;
    EGLContext ctx = EGL_NO_CONTEXT;
    if (eglBindAPI(EGL_OPENGL_ES_API)) ctx = eglCreateContext(*dpy, EGL_NO_CONFIG_KHR, EGL_NO_CONTEXT, context_attrs);
    if (ctx != EGL_NO_CONTEXT && !eglMakeCurrent(*dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, ctx)) {
        eglDestroyContext(*dpy, ctx);
        ctx = EGL_NO_CONTEXT;
    }
    if (ctx == EGL_NO_CONTEXT) eglTerminate(*dpy);
    return ctx;
}

static GLuint shader(GLenum type, const char *source)
{
    GLuint id = glCreateShader(type);
    GLint ok = 0;
    glShaderSource(id, 1, &source, NULL);
    glCompileShader(id);
    glGetShaderiv(id, GL_COMPILE_STATUS, &ok);
    return ok ? id : 0;
}

int main(int argc, char **argv)
{
    CHECK(argc == 3);
    int render = open(argv[1], O_RDWR | O_CLOEXEC);
    int kms = open(argv[2], O_RDWR | O_CLOEXEC);
    CHECK(render >= 0 && kms >= 0);
    /* The first to open a card becomes its DRM master. Nothing here needs
     * that, and Labwc must get it even if this process were to get stuck. */
    drmDropMaster(kms);

    /* The size Labwc's output buffers will have: the panel's mode. */
    uint32_t width = 0, height = 0;
    drmModeRes *resources = drmModeGetResources(kms);
    for (int i = 0; resources && i < resources->count_connectors && !width; i++) {
        drmModeConnector *connector = drmModeGetConnectorCurrent(kms, resources->connectors[i]);
        if (connector && connector->connection == DRM_MODE_CONNECTED && connector->count_modes > 0) {
            width = connector->modes[0].hdisplay;
            height = connector->modes[0].vdisplay;
        }
        drmModeFreeConnector(connector);
    }
    drmModeFreeResources(resources);
    if (!width || !height) { width = 2048; height = 1536; }

    struct gbm_device *gbm = gbm_create_device(render);
    CHECK(gbm);
    EGLDisplay dpy;
    const char *platform = "device";
    EGLContext ctx = open_egl(render, gbm, 1, &dpy);
    if (ctx == EGL_NO_CONTEXT) { platform = "gbm"; ctx = open_egl(render, gbm, 0, &dpy); }
    CHECK(ctx != EGL_NO_CONTEXT);
    const char *renderer = (const char *)glGetString(GL_RENDERER);
    CHECK(renderer);
    if (!strstr(renderer, "zink") || strstr(renderer, "llvmpipe") || strstr(renderer, "softpipe")) {
        fprintf(stderr, "GPU-PROBE FAIL: not Zink on a GPU: renderer=%s\n", renderer);
        return 1;
    }

    /* The output buffer, allocated on the GPU as wlroots' GBM allocator does. */
    struct gbm_bo *bo = gbm_bo_create(gbm, width, height, GBM_FORMAT_XRGB8888,
                                      GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    if (!bo) {
        const uint64_t linear = DRM_FORMAT_MOD_LINEAR;
        bo = gbm_bo_create_with_modifiers2(gbm, width, height, GBM_FORMAT_XRGB8888, &linear, 1,
                                           GBM_BO_USE_SCANOUT | GBM_BO_USE_RENDERING);
    }
    CHECK(bo);
    int dma = gbm_bo_get_fd(bo);
    CHECK(dma >= 0);
    uint64_t modifier = gbm_bo_get_modifier(bo);
    uint32_t stride = gbm_bo_get_stride(bo);
    const char *egl_extensions = eglQueryString(dpy, EGL_EXTENSIONS);
    CHECK(egl_extensions && strstr(egl_extensions, "EGL_EXT_image_dma_buf_import"));
    EGLint ia[32], n = 0;
    ia[n++] = EGL_WIDTH; ia[n++] = (EGLint)width;
    ia[n++] = EGL_HEIGHT; ia[n++] = (EGLint)height;
    ia[n++] = EGL_LINUX_DRM_FOURCC_EXT; ia[n++] = GBM_FORMAT_XRGB8888;
    ia[n++] = EGL_DMA_BUF_PLANE0_FD_EXT; ia[n++] = dma;
    ia[n++] = EGL_DMA_BUF_PLANE0_OFFSET_EXT; ia[n++] = 0;
    ia[n++] = EGL_DMA_BUF_PLANE0_PITCH_EXT; ia[n++] = (EGLint)stride;
    if (modifier != DRM_FORMAT_MOD_INVALID && strstr(egl_extensions, "EGL_EXT_image_dma_buf_import_modifiers")) {
        ia[n++] = EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT; ia[n++] = (EGLint)(modifier & 0xffffffff);
        ia[n++] = EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT; ia[n++] = (EGLint)(modifier >> 32);
    }
    ia[n] = EGL_NONE;
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

    /* A clear, then geometry through a shader: a desktop is drawn quads. */
    glViewport(0, 0, (GLsizei)width, (GLsizei)height);
    glClearColor(1, 0, 0, 1); glClear(GL_COLOR_BUFFER_BIT);
    GLuint vs = shader(GL_VERTEX_SHADER, "attribute vec2 p; void main() { gl_Position = vec4(p, 0.0, 1.0); }");
    GLuint fs = shader(GL_FRAGMENT_SHADER, "void main() { gl_FragColor = vec4(0.0, 1.0, 0.0, 1.0); }");
    CHECK(vs && fs);
    GLuint program = glCreateProgram();
    GLint linked = 0;
    glAttachShader(program, vs); glAttachShader(program, fs);
    glBindAttribLocation(program, 0, "p");
    glLinkProgram(program);
    glGetProgramiv(program, GL_LINK_STATUS, &linked);
    CHECK(linked);
    static const GLfloat quad[] = {-1, -1, 1, -1, -1, 1, 1, 1};
    glUseProgram(program);
    glVertexAttribPointer(0, 2, GL_FLOAT, GL_FALSE, 0, quad);
    glEnableVertexAttribArray(0);
    glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
    unsigned char pixel[4] = {0};
    glReadPixels((GLint)width / 2, (GLint)height / 2, 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, pixel);
    CHECK(glGetError() == GL_NO_ERROR);
    if (pixel[0] > 5 || pixel[1] < 250 || pixel[2] > 5) {
        fprintf(stderr, "GPU-PROBE FAIL: drew green, read back %u,%u,%u\n", pixel[0], pixel[1], pixel[2]);
        return 1;
    }

    /* The display controller must take the buffer, as at Labwc's first commit. */
    uint32_t handle = 0, fb_id = 0, handles[4] = {0}, pitches[4] = {0}, offsets[4] = {0};
    uint64_t modifiers[4] = {0}, addfb2_modifiers = 0;
    if (drmPrimeFDToHandle(kms, dma, &handle)) {
        fprintf(stderr, "GPU-PROBE FAIL: the display controller cannot import a GPU buffer: %m\n");
        return 1;
    }
    handles[0] = handle; pitches[0] = stride; modifiers[0] = modifier;
    int added = -1;
    if (modifier != DRM_FORMAT_MOD_INVALID && !drmGetCap(kms, DRM_CAP_ADDFB2_MODIFIERS, &addfb2_modifiers) &&
        addfb2_modifiers)
        added = drmModeAddFB2WithModifiers(kms, width, height, DRM_FORMAT_XRGB8888, handles, pitches, offsets,
                                           modifiers, &fb_id, DRM_MODE_FB_MODIFIERS);
    if (added) added = drmModeAddFB2(kms, width, height, DRM_FORMAT_XRGB8888, handles, pitches, offsets, &fb_id, 0);
    if (added) added = drmModeAddFB(kms, width, height, 24, 32, stride, handle, &fb_id);
    if (added) {
        fprintf(stderr, "GPU-PROBE FAIL: the display controller cannot scan out a GPU buffer: %m\n");
        return 1;
    }
    drmModeRmFB(kms, fb_id);
    drmCloseBufferHandle(kms, handle);

    printf("GPU-PROBE PASS renderer=%s egl=%s size=%ux%u render=%s display=%s\n", renderer, platform,
           width, height, argv[1], argv[2]);
    glDeleteProgram(program); glDeleteShader(vs); glDeleteShader(fs);
    glDeleteFramebuffers(1, &fb); glDeleteRenderbuffers(1, &rb); destroy(dpy, image);
    close(dma); gbm_bo_destroy(bo);
    eglMakeCurrent(dpy, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
    eglDestroyContext(dpy, ctx); eglTerminate(dpy);
    gbm_device_destroy(gbm); close(kms); close(render);
    return 0;
}
