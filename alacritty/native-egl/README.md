# Native Wayland feedback descriptor fix

NVIDIA egl-wayland 1.1.23 and 1.1.24 can retain per-surface DMA-BUF feedback
descriptors when a client uses swap interval zero. This affects Alacritty on
COSMIC. [NVIDIA issue 205](https://github.com/NVIDIA/egl-wayland/issues/205)
describes the regression; [PR 206](https://github.com/NVIDIA/egl-wayland/pull/206)
adds the missing nonblocking queue dispatch.

`python3 alacritty/native-egl/build.py` builds pinned PR revision
`010d9f202122d168dcc598c492317a9d8c8c3945` under
`~/.local/lib/alacritty-egl-wayland/<revision>/`. It requires Meson, a C compiler,
pkg-config, and the installed EGL, Wayland, libdrm, and EGL external platform
development files. Protocol XML 1.49, commit
`ee78491a237eaff9389a0ccf8680521d074407d3`, is downloaded and built locally. Build
output and provenance stay in that prefix; no system files are installed.

The Stow-managed `~/.local/bin/alacritty` executes `/usr/bin/alacritty` with a
small preload shim on Wayland when the local build exists. Its dependency loads
the patched EGL library under the original SONAME. The shim restores the exact
previous `LD_PRELOAD` value, including its absence, before Alacritty starts.
Custom commands and shell configuration pass through unchanged, and programs
inside the terminal inherit their original environment. Other applications and
X11 launches use the system libraries. Alacritty's built-in direct self-spawn
action bypasses the PATH launcher; IPC windows within a patched process reuse
its patched library.

During development the launcher is linked directly from the isolated task
worktree, leaving the main checkout unchanged.

The patch was unmerged when pinned. Remove the launcher symlink to bypass the
local fix; the versioned library directory can then be removed when no patched
terminal still uses it. Existing windows keep their already loaded libraries; new windows
use the launcher. Once a packaged release includes the fix, remove this local
override after checking that release's behavior.
