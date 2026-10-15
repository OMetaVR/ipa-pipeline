"""Naming rules shared by watch.py, push-ipa.py and the build workflow."""

import re


def slug(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def base_asset_name(config, version):
    return f"{slug(config['base']['name'])}_{version}.ipa"


def base_versions(config, asset_names):
    """Versions of the base IPAs in the draft release, oldest first."""
    prefix = slug(config["base"]["name"]) + "_"
    found = [n[len(prefix):-4] for n in asset_names if n.startswith(prefix) and n.endswith(".ipa")]
    return sorted(found, key=lambda v: [int(p) if p.isdigit() else 0 for p in re.split(r"[.-]", v)])


def release_tag(config, upstream_tag, base_version=None):
    """Tag of the fork's release for an upstream tag (+ the base app version, when one is injected)."""
    base = config.get("base")
    if base and base_version and not base.get("url"):
        return f"{upstream_tag}-{slug(base['name'])}{base_version}"
    return upstream_tag


if __name__ == "__main__":
    # CLI for the build workflow: common.py release-tag <config> <upstream_tag> [base_version]
    import json
    import sys

    cmd, cfg = sys.argv[1], json.load(open(sys.argv[2]))
    if cmd == "release-tag":
        print(release_tag(cfg, sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None))
    elif cmd == "base-asset":
        print(base_asset_name(cfg, sys.argv[3]))
