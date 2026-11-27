#!/usr/bin/env python3
"""Makes a Pillow that runs on both Apple silicon and Intel Macs, for the self-contained downloads.

    /usr/bin/python3 mac/universal_pillow.py <output dir>      # writes <output dir>/PIL

It downloads the two official Pillow 11.3.0 wheels for Python 3.9 (the one macOS's own /usr/bin/python3 is),
checks each against the SHA-256 published on PyPI, and joins every compiled file of the two into one
universal file with `lipo`. Needs the network the first time; the result is cached by build.sh.
"""
import hashlib
import io
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile

WHEELS = {
    "arm64": ("https://files.pythonhosted.org/packages/b5/a9/5749930caf674695867eb56a581e78eb5f524b7583ff10b01b6e5048acb3/"
              "pillow-11.3.0-cp39-cp39-macosx_11_0_arm64.whl",
              "7aee118e30a4cf54fdd873bd3a29de51e29105ab11f9aad8c32123f58c8f8081"),
    "x86_64": ("https://files.pythonhosted.org/packages/9e/8e/9c089f01677d1264ab8648352dcb7773f37da6ad002542760c80107da816/"
               "pillow-11.3.0-cp39-cp39-macosx_10_10_x86_64.whl",
               "48d254f8a4c776de343051023eb61ffe818299eeac478da55227d96e241de53f"),
}


def fetch(arch):
    url, want = WHEELS[arch]
    data = urllib.request.urlopen(url, timeout=60).read()
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        sys.exit(f"Pillow {arch} wheel does not match its published checksum ({got}); not using it")
    return zipfile.ZipFile(io.BytesIO(data))


def is_macho(path):
    with open(path, "rb") as f:
        return f.read(4) in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")


def main():
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    out = os.path.abspath(sys.argv[1])
    work = tempfile.mkdtemp()
    try:
        trees = {}
        for arch in WHEELS:
            root = os.path.join(work, arch)
            fetch(arch).extractall(root)
            trees[arch] = os.path.join(root, "PIL")
        shutil.rmtree(os.path.join(out, "PIL"), ignore_errors=True)
        os.makedirs(out, exist_ok=True)
        shutil.copytree(trees["arm64"], os.path.join(out, "PIL"))
        joined = 0
        for folder, _dirs, files in os.walk(os.path.join(out, "PIL")):
            for name in files:
                dest = os.path.join(folder, name)
                if not is_macho(dest):
                    continue
                other = os.path.join(trees["x86_64"], os.path.relpath(dest, os.path.join(out, "PIL")))
                if not os.path.exists(other):
                    # the two wheels name their bundled libraries differently: each side keeps its own,
                    # and every joined .so loads the right one for the chip it runs on
                    if ".dylibs" in dest:
                        continue
                    sys.exit(f"the Intel wheel has no {os.path.relpath(other, trees['x86_64'])}")
                tmp = dest + ".fat"
                subprocess.run(["lipo", "-create", dest, other, "-output", tmp], check=True)
                os.replace(tmp, dest)
                joined += 1
        for folder, _dirs, files in os.walk(trees["x86_64"]):        # libraries only the Intel wheel carries
            for name in files:
                src = os.path.join(folder, name)
                dest = os.path.join(out, "PIL", os.path.relpath(src, trees["x86_64"]))
                if ".dylibs" in src and not os.path.exists(dest):
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    shutil.copy2(src, dest)
        print(f"universal Pillow ready: {joined} compiled files joined, in {os.path.join(out, 'PIL')}")
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    main()
