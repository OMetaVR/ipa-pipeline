#!/usr/bin/env python3
"""Upload a decrypted IPA to whichever of your forks injects into that app.

    push-ipa.py ~/Downloads/com.spotify.client-9.1.88-Decrypted.ipa
    push-ipa.py Twitch.ipa --no-build      # store it, don't run the watcher

Reads the IPA's bundle ID, finds the fork(s) in projects.json whose
.ometa/config.json injects into that app, checks the IPA is decrypted, and
uploads it to each fork's private "base-ipas" draft release as
<app>_<version>.ipa. Then runs the fork's watcher, which starts a build if
upstream needs it. Needs the gh CLI, logged in.
"""

import argparse
import base64
import json
import plistlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
from common import base_asset_name  # noqa: E402

DRAFT_TAG = "base-ipas"

LC_ENCRYPTION_INFO = 0x21
LC_ENCRYPTION_INFO_64 = 0x2C
FAT_MAGICS = {0xCAFEBABE: False, 0xCAFEBABF: True}  # value: 64-bit fat_arch


def cryptids(f):
    """Yield the cryptid of every slice in a Mach-O file object."""
    head = f.read(8)
    magic, = struct.unpack(">I", head[:4])
    if magic in FAT_MAGICS:
        nfat, = struct.unpack(">I", head[4:8])
        size = 32 if FAT_MAGICS[magic] else 20
        archs = [f.read(size) for _ in range(nfat)]
        offsets = [struct.unpack(">Q" if size == 32 else ">I", a[8:16] if size == 32 else a[8:12])[0] for a in archs]
        for off in offsets:
            f.seek(off)
            yield from cryptids(f)
        return
    f.seek(f.tell() - 8)
    start = f.tell()
    hdr = f.read(32)
    magic, = struct.unpack("<I", hdr[:4])
    if magic not in (0xFEEDFACE, 0xFEEDFACF):
        return
    ncmds, = struct.unpack("<I", hdr[16:20])
    f.seek(start + (32 if magic == 0xFEEDFACF else 28))
    for _ in range(ncmds):
        cmd, size = struct.unpack("<II", f.read(8))
        body = f.read(size - 8)
        if cmd in (LC_ENCRYPTION_INFO, LC_ENCRYPTION_INFO_64):
            yield struct.unpack("<I", body[8:12])[0]


def read_ipa(path):
    """Return (Info.plist, [encrypted binaries])."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        plist_name = next((n for n in names if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n)), None)
        if not plist_name:
            sys.exit("Not an IPA: no Payload/*.app/Info.plist")
        app = plist_name.rsplit("/", 1)[0]
        info = plistlib.loads(z.read(plist_name))
        binaries = [f"{app}/{info['CFBundleExecutable']}"]
        binaries += [n for n in names if re.fullmatch(re.escape(app) + r"/Frameworks/([^/]+)\.framework/\1", n)]
        encrypted = []
        with tempfile.TemporaryDirectory() as tmp:
            for name in binaries:
                out = Path(tmp) / "bin"
                with z.open(name) as src, open(out, "wb") as dst:
                    shutil.copyfileobj(src, dst)
                with open(out, "rb") as f:
                    if any(cryptids(f)):
                        encrypted.append(name)
    return info, encrypted


def gh(*args):
    p = subprocess.run(["gh", *args], text=True, capture_output=True)
    if p.returncode:
        sys.exit(f"gh {' '.join(args)} failed:\n{p.stderr}")
    return p.stdout


def fork_config(repo):
    try:
        data = json.loads(gh("api", f"repos/{repo}/contents/.ometa/config.json"))
    except SystemExit:
        return None
    return json.loads(base64.b64decode(data["content"]))


def upload(repo, config, ipa, version, run_watcher):
    drafts = json.loads(gh("api", f"repos/{repo}/releases?per_page=100"))
    if not any(r["draft"] and r["tag_name"] == DRAFT_TAG for r in drafts):
        gh("release", "create", DRAFT_TAG, "-R", repo, "--draft", "--title", "Base IPAs (private)",
           "--notes", "Decrypted IPAs used as build input. Kept as a draft so it isn't public.")
    with tempfile.TemporaryDirectory() as tmp:
        named = Path(tmp) / base_asset_name(config, version)
        named.symlink_to(ipa.resolve())
        print(f"  uploading {named.name} to {repo}…")
        gh("release", "upload", DRAFT_TAG, str(named), "-R", repo, "--clobber")
    if run_watcher:
        gh("workflow", "run", "ometa-watch.yml", "-R", repo)
        print(f"  started the watcher: gh run list -R {repo}")


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("ipa", type=Path)
    ap.add_argument("--no-build", action="store_true", help="upload only, don't run the watcher")
    args = ap.parse_args()

    info, encrypted = read_ipa(args.ipa)
    bundle, version = info["CFBundleIdentifier"], info["CFBundleShortVersionString"]
    if encrypted:
        sys.exit(f"{bundle} {version} is still encrypted:\n  " + "\n  ".join(encrypted))
    print(f"Decrypted {bundle} {version}: OK")

    targets = []
    for repo in json.loads((ROOT / "projects.json").read_text()):
        cfg = fork_config(repo)
        base = (cfg or {}).get("base")
        if base and not base.get("url") and base["bundleId"] == bundle:
            targets.append((repo, cfg))
    if not targets:
        sys.exit(f"No fork in projects.json injects into {bundle}.")

    for repo, cfg in targets:
        upload(repo, cfg, args.ipa, version, not args.no_build)


if __name__ == "__main__":
    main()
