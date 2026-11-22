#!/usr/bin/python3
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import urllib.request


REVISION = "010d9f202122d168dcc598c492317a9d8c8c3945"
PROTOCOLS_REVISION = "ee78491a237eaff9389a0ccf8680521d074407d3"
ROOT = Path.home() / ".local/lib/alacritty-egl-wayland" / REVISION
SOURCES = ROOT / "sources"
SOURCES.mkdir(parents=True, exist_ok=True)


def download(name, url):
    destination = SOURCES / name
    if destination.is_dir():
        return
    with urllib.request.urlopen(url, timeout=60) as response:
        archive = response.read()
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as source:
        roots = {Path(member.name).parts[0] for member in source.getmembers() if member.name}
        if len(roots) != 1:
            raise RuntimeError("Unexpected source archive layout")
        source.extractall(SOURCES, filter="data")
    (SOURCES / roots.pop()).rename(destination)


download("egl-wayland", f"https://api.github.com/repos/NVIDIA/egl-wayland/tarball/{REVISION}")
download(
    "wayland-protocols",
    "https://gitlab.freedesktop.org/wayland/wayland-protocols/-/archive/"
    + PROTOCOLS_REVISION + "/wayland-protocols-" + PROTOCOLS_REVISION + ".tar.gz",
)
environment = os.environ.copy()
environment["PKG_CONFIG_PATH"] = str(ROOT / "build-deps/share/pkgconfig") + (
    ":" + environment["PKG_CONFIG_PATH"] if environment.get("PKG_CONFIG_PATH") else ""
)


def run(arguments):
    print("Running:", " ".join(map(str, arguments)), flush=True)
    with (ROOT / "build.log").open("a") as log:
        subprocess.run(list(map(str, arguments)), env=environment, stdout=log, stderr=log, check=True)


def configure(build, source, *options):
    arguments = ["meson", "setup"]
    if (build / "meson-private/coredata.dat").exists():
        arguments.append("--reconfigure")
    run([*arguments, build, source, *options])


configure(
    ROOT / "protocols-build",
    SOURCES / "wayland-protocols",
    "--prefix", ROOT / "build-deps", "-Dtests=false",
)
run(["meson", "install", "-C", ROOT / "protocols-build"])
configure(
    ROOT / "build", SOURCES / "egl-wayland",
    "--prefix", ROOT, "--libdir", "lib", "--buildtype", "release",
)
run(["meson", "compile", "-C", ROOT / "build"])
run(["meson", "install", "-C", ROOT / "build"])
run([
    "cc", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
    "-Wl,-z,relro,-z,now", "-Wl,--no-as-needed",
    Path(__file__).with_name("launch-env.c"),
    ROOT / "lib/libnvidia-egl-wayland.so.1",
    "-Wl,-rpath," + str(ROOT / "lib"),
    "-o", ROOT / "lib/libalacritty-egl-preload.so",
])
library = ROOT / "lib/libnvidia-egl-wayland.so.1.1.25"
(ROOT / "provenance.json").write_text(json.dumps({
    "source": "https://github.com/NVIDIA/egl-wayland/pull/206",
    "revision": REVISION,
    "protocols_version": "1.49",
    "protocols_revision": PROTOCOLS_REVISION,
    "library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
}, indent=2) + "\n")
print("Built:", library)
