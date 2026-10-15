#!/usr/bin/env bash
# Fork an upstream repo into OMetaVR and wire it to this pipeline.
#
#   scripts/new-fork.sh <owner/repo> <runner> [checkout-dir]
#   scripts/new-fork.sh claration/feather macos-latest /mnt/sda2/PROJECTS/iOS/feather
#
# Creates the fork, clones it, adds the two ometa-*.yml caller workflows and a
# starter .ometa/ folder (edit config.json and build.sh, then commit and push),
# and turns on Actions with only our workflows enabled.
set -euo pipefail

UPSTREAM="$1" RUNNER="$2"
NAME="${UPSTREAM#*/}"
DIR="${3:-$(pwd)/$NAME}"
FORK="OMetaVR/$NAME"

gh repo view "$FORK" >/dev/null 2>&1 || gh repo fork "$UPSTREAM" --clone=false --default-branch-only
[ -d "$DIR/.git" ] || git clone --quiet --recurse-submodules "https://github.com/$FORK.git" "$DIR"
cd "$DIR"
git config core.fileMode false
git remote get-url upstream >/dev/null 2>&1 || git remote add upstream "https://github.com/$UPSTREAM.git"

mkdir -p .github/workflows .ometa
cat > .github/workflows/ometa-watch.yml <<EOF
# OMetaVR pipeline: https://github.com/OMetaVR/ipa-pipeline
name: OMetaVR Watch

on:
  schedule:
    - cron: "$((RANDOM % 60)) */3 * * *"
  workflow_dispatch:

permissions:
  contents: write
  issues: write
  actions: write

jobs:
  watch:
    uses: OMetaVR/ipa-pipeline/.github/workflows/watch.yml@main
EOF

cat > .github/workflows/ometa-build.yml <<EOF
# OMetaVR pipeline: https://github.com/OMetaVR/ipa-pipeline
name: OMetaVR Build
run-name: Build \${{ inputs.upstream_tag }}

on:
  workflow_dispatch:
    inputs:
      upstream_tag:
        description: "Upstream release tag to build"
        required: true
        type: string
      base_version:
        description: "Base app version to inject into (from the base-ipas draft); blank if none"
        required: false
        default: ""
        type: string

concurrency:
  group: ometa-build-\${{ inputs.upstream_tag }}

permissions:
  contents: write

jobs:
  build:
    uses: OMetaVR/ipa-pipeline/.github/workflows/build.yml@main
    with:
      upstream_tag: \${{ inputs.upstream_tag }}
      base_version: \${{ inputs.base_version }}
      runner: $RUNNER
EOF

[ -f .ometa/config.json ] || cat > .ometa/config.json <<EOF
{
  "upstream": "$UPSTREAM",
  "name": "$NAME",
  "base": null
}
EOF
[ -f .ometa/build.sh ] || printf '#!/usr/bin/env bash\nsource "$PIPELINE/lib/helpers.sh"\n# Build, then copy release files to "$OUT".\n' > .ometa/build.sh

gh api -X PUT "repos/$FORK/actions/permissions" -F enabled=true -f allowed_actions=all >/dev/null
echo "Fork ready at $DIR. Edit .ometa/config.json and .ometa/build.sh, then commit and push."
