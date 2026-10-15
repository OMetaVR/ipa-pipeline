# Helpers for .ometa/build.sh recipes. Source this file:
#   source "$PIPELINE/lib/helpers.sh"
# The build workflow provides: SRC (fork checkout), OUT (put release files here),
# BASE_IPA / BASE_VERSION (when the fork injects into an app), UPSTREAM_TAG.

set -euo pipefail

log() { printf '\033[36m==>\033[0m %s\n' "$*"; }

# Default Theos: the last commit before Logos' June 2026 %orig parser change
# (theos/logos 777925d), which breaks tweaks with one-line `{ ... %orig; }` methods.
THEOS_DEFAULT_REF=9bc73406cf80b711ef4d02c15ff1dedc4478a275

# setup_theos [sdk-version] [theos-ref]
# Installs Theos (macOS) into $THEOS and, if given, an iOS SDK from theos/sdks.
setup_theos() {
  local sdk="${1:-}" ref="${2:-$THEOS_DEFAULT_REF}"
  export THEOS="${THEOS:-$RUNNER_TEMP/theos}"
  log "Installing Theos ($ref) to $THEOS"
  brew list ldid >/dev/null 2>&1 || brew install ldid
  brew list dpkg >/dev/null 2>&1 || brew install dpkg
  brew list make >/dev/null 2>&1 || brew install make
  export PATH="$(brew --prefix make)/libexec/gnubin:$PATH"
  if [ ! -d "$THEOS/.git" ]; then
    git clone --quiet --recursive https://github.com/theos/theos.git "$THEOS"
  fi
  if [ "$ref" != "master" ]; then
    git -C "$THEOS" checkout --quiet "$ref"
    git -C "$THEOS" submodule update --quiet --init --recursive
  fi
  if [ -n "$sdk" ] && [ ! -d "$THEOS/sdks/iPhoneOS$sdk.sdk" ]; then
    log "Fetching iPhoneOS$sdk.sdk"
    local tmp; tmp=$(mktemp -d)
    git clone --quiet -n --depth=1 --filter=tree:0 https://github.com/theos/sdks.git "$tmp"
    git -C "$tmp" sparse-checkout set --no-cone "iPhoneOS$sdk.sdk"
    git -C "$tmp" checkout --quiet
    mkdir -p "$THEOS/sdks"
    mv "$tmp/iPhoneOS$sdk.sdk" "$THEOS/sdks/"
    rm -rf "$tmp"
  fi
}

# setup_theos_jailed <github-repo>  e.g. level3tjg/theos-jailed
setup_theos_jailed() {
  local repo="$1" dir="$RUNNER_TEMP/theos-jailed"
  log "Installing $repo"
  rm -rf "$dir"
  git clone --quiet --recursive "https://github.com/$repo.git" "$dir"
  "$dir/install"
}

# install_cyan [git-ref]  (pyzule-rw; injects .debs/dylibs/frameworks into IPAs)
install_cyan() {
  local ref="${1:-main}" venv="$RUNNER_TEMP/cyan-venv"
  log "Installing cyan ($ref)"
  python3 -m venv "$venv"
  "$venv/bin/pip" install --quiet "https://github.com/asdfzxcvbn/pyzule-rw/archive/$ref.zip"
  export PATH="$venv/bin:$PATH"
}

# ipa_info <ipa> <key>  -> value from the app's Info.plist
ipa_info() {
  python3 - "$1" "$2" <<'PY'
import plistlib, re, sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
name = next(n for n in z.namelist() if re.fullmatch(r"Payload/[^/]+\.app/Info\.plist", n))
print(plistlib.loads(z.read(name))[sys.argv[2]])
PY
}

# ipa_remove <ipa> <glob relative to the .app>...  e.g. ipa_remove x.ipa 'PlugIns/*' 'Watch/*'
ipa_remove() {
  local ipa="$1"; shift
  local app; app=$(unzip -Z1 "$ipa" | grep -m1 -oE '^Payload/[^/]+\.app/')
  for g in "$@"; do zip -q -d "$ipa" "$app$g" >/dev/null 2>&1 || true; done
}

# package_app <path/to/X.app> <out.ipa>  -> zips an .app into an IPA
package_app() {
  local app="$1" out="$2" tmp; tmp=$(mktemp -d)
  mkdir -p "$tmp/Payload"
  cp -R "$app" "$tmp/Payload/"
  (cd "$tmp" && zip -qry "$out" Payload)
  rm -rf "$tmp"
}
