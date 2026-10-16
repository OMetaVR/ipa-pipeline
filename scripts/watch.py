#!/usr/bin/env python3
"""Decide whether a fork needs a build. Run by the reusable watch workflow.

Reads the fork's .ometa/config.json and looks at upstream's latest published
release. If the fork has no release for it yet, it starts the fork's build
(when any base IPA it needs is available) or opens an issue asking for the
decrypted IPA. Needs the gh CLI with GH_TOKEN and GITHUB_REPOSITORY set.
"""

import base64
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import base_asset_name, base_versions, release_tag  # noqa: E402

REPO = os.environ["GITHUB_REPOSITORY"]
CONFIG = json.loads(Path(os.environ.get("OMETA_CONFIG", ".ometa/config.json")).read_text())
UPSTREAM = CONFIG["upstream"]
BASE = CONFIG.get("base")
BUILD_WORKFLOW = "ometa-build.yml"
DRAFT_TAG = "base-ipas"
NEED_IPA_LABEL = "needs-ipa"
BUILD_FAILED_LABEL = "build-failed"


def gh(*args, check=True):
    p = subprocess.run(["gh", *args], text=True, capture_output=True)
    if check and p.returncode:
        raise SystemExit(f"gh {' '.join(args)} failed:\n{p.stderr}")
    return p


def gh_json(*args):
    return json.loads(gh(*args).stdout)


def upstream_file(path, ref):
    return base64.b64decode(gh_json("api", f"repos/{UPSTREAM}/contents/{path}?ref={ref}")["content"]).decode()


def ensure_issue(title, body, label=None):
    issues = gh_json("issue", "list", "-R", REPO, "--state", "open", "--search", f'in:title "{title}"', "--json", "number,title")
    if any(i["title"] == title for i in issues):
        return
    args = ["issue", "create", "-R", REPO, "--title", title, "--body", body]
    if label:
        gh("label", "create", label, "-R", REPO, "--color", "D93F0B", "--force")
        args += ["--label", label]
    gh(*args)
    print(f"Opened issue: {title}")


def close_issues(label, comment):
    for i in gh_json("issue", "list", "-R", REPO, "--state", "open", "--label", label, "--json", "number"):
        gh("issue", "close", str(i["number"]), "-R", REPO, "--comment", comment)


def appstore_version():
    try:
        with urllib.request.urlopen(f"https://itunes.apple.com/lookup?id={BASE['appStoreId']}") as r:
            return json.load(r)["results"][0]["version"]
    except Exception:
        return None


def disable_upstream_workflows():
    """Upstream's own workflows would run (and mostly fail) in the fork; keep only ours on."""
    for wf in gh_json("workflow", "list", "-R", REPO, "--all", "--json", "id,path,state"):
        if not Path(wf["path"]).name.startswith("ometa-") and wf["state"] == "active":
            gh("workflow", "disable", str(wf["id"]), "-R", REPO, check=False)
            print(f"Disabled upstream workflow {wf['path']}")


def target_version(release):
    """The base app version upstream targets, or None when any version will do."""
    spec, tag = BASE["version"], release["tag_name"]
    if spec["from"] == "upstream-tag":
        return re.search(spec["regex"], tag).group(1)
    if spec["from"] == "upstream-asset":
        for asset in release["assets"]:
            if m := re.search(spec["regex"], asset["name"]):
                return m.group(1)
        raise SystemExit(f"No asset on upstream {tag} matches {spec['regex']}")
    if spec["from"] == "upstream-file":
        ref = gh_json("api", f"repos/{UPSTREAM}")["default_branch"] if spec.get("ref") == "default" else tag
        return re.search(spec["regex"], upstream_file(spec["file"], ref)).group(1)
    return None  # "any"


def main():
    disable_upstream_workflows()

    release = gh_json("api", f"repos/{UPSTREAM}/releases/latest")
    tag = release["tag_name"]
    print(f"Upstream {UPSTREAM} latest release: {tag}")

    needs_draft = bool(BASE) and not BASE.get("url")
    want = target_version(release) if needs_draft else None
    if want:
        print(f"Targets {BASE['name']} {want}")

    releases = gh_json("api", f"repos/{REPO}/releases?per_page=100")
    published = {r["tag_name"] for r in releases if not r["draft"]}
    if want:
        built = release_tag(CONFIG, tag, want) in published
    else:
        built = any(t == tag or t.startswith(f"{tag}-") for t in published)
    if built:
        print(f"Already released for {tag}")
        for label in (NEED_IPA_LABEL, BUILD_FAILED_LABEL):
            close_issues(label, f"Built and released for upstream {tag}.")
        return

    runs = gh_json("run", "list", "-R", REPO, "-w", BUILD_WORKFLOW, "-L", "20", "--json", "displayTitle,status,conclusion")
    mine = [r for r in runs if r["displayTitle"] == f"Build {tag}"]
    if any(r["status"] != "completed" for r in mine):
        print(f"A build for {tag} is already running")
        return
    if any(r["conclusion"] == "failure" for r in mine):
        ensure_issue(f"Build failed for {tag}",
                     f"The build for upstream `{tag}` failed, so the watcher won't retry it automatically.\n\n"
                     f"Fix the cause, then re-run it: Actions → OMetaVR Build → Run workflow (upstream tag `{tag}`).",
                     label=BUILD_FAILED_LABEL)
        print(f"Previous build for {tag} failed; not retrying")
        return

    version = ""
    if needs_draft:
        draft = next((r for r in releases if r["draft"] and r["tag_name"] == DRAFT_TAG), None)
        available = base_versions(CONFIG, [a["name"] for a in draft["assets"]] if draft else [])
        if want:
            version = want if want in available else ""
        elif available:
            version = available[-1]  # newest uploaded
        if not version:
            latest = appstore_version()
            need = want or latest or "latest"
            ensure_issue(
                f"Decrypted {BASE['name']} {need} needed",
                f"Upstream released [`{tag}`](https://github.com/{UPSTREAM}/releases/tag/{tag})"
                + (f", which targets **{BASE['name']} {want}**." if want else
                   f". Any {BASE['name']} version works; the newest one you upload is used.")
                + (f" (Latest on the App Store: {latest}.)" if latest else "")
                + f"\n\nGet a decrypted `{BASE['bundleId']}` IPA and run:\n\n"
                f"```\npush-ipa.py /path/to/{BASE['name']}.ipa\n```\n\n"
                f"(from [ipa-pipeline](https://github.com/OMetaVR/ipa-pipeline)). "
                f"The build starts automatically and this issue closes once it's released.",
                label=NEED_IPA_LABEL,
            )
            return
        print(f"Using {base_asset_name(CONFIG, version)}")

    gh("workflow", "run", BUILD_WORKFLOW, "-R", REPO, "-f", f"upstream_tag={tag}", "-f", f"base_version={version}")
    print(f"Started build for {tag}")


if __name__ == "__main__":
    main()
