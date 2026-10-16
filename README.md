# ipa-pipeline

Shared build pipeline for my forks of iOS tweaks and apps. Each fork builds upstream's latest release plus the fork's own changes and publishes IPAs (and jailbreak `.deb`s / dylibs) as GitHub releases, which the [Meta's Apps source](https://github.com/OMetaVR/ipa-source) picks up.

| Fork | Upstream | Base app |
| --- | --- | --- |
| [TwitchAdBlock](https://github.com/OMetaVR/TwitchAdBlock) | gunnerkidBT/TwitchAdBlock | Twitch (version from upstream's tag) |
| [YTMusicUltimate](https://github.com/OMetaVR/YTMusicUltimate) | dayanch96/YTMusicUltimate | YouTube Music (any) |
| [scmusicplus](https://github.com/OMetaVR/scmusicplus) | Rov3r/scmusicplus | SoundCloud (any) |
| [Apollo-Reborn](https://github.com/OMetaVR/Apollo-Reborn) | Apollo-Reborn/Apollo-Reborn | Apollo (public base IPA) |
| [iTorrent](https://github.com/OMetaVR/iTorrent) | XITRIX/iTorrent | none, built from source |
| [feather](https://github.com/OMetaVR/feather) | claration/feather | none, built from source |
| [BHTikTok](https://github.com/OMetaVR/BHTikTok) | BandarHL/BHTikTok | TikTok (any) |
| [NeoFreeBird](https://github.com/OMetaVR/NeoFreeBird) | NeoFreeBird/app (BHTwitter continuation) | X (version from upstream's release assets) |
| [Un-JailedSpeedAds](https://github.com/OMetaVR/Un-JailedSpeedAds) | SoulRune/Un-JailedSpeedAds | none, `.deb`s + injectable dylib |

## Supplying a decrypted IPA

When a fork opens a "Decrypted X needed" issue:

```sh
scripts/push-ipa.py ~/Downloads/some-app-Decrypted.ipa
```

It reads the IPA's bundle ID, finds the fork(s) that inject into that app, checks the IPA is decrypted, uploads it to each fork's private `base-ipas` draft release and runs the fork's watcher. `--no-build` only uploads.

## How a fork is wired up

Each fork's default branch has, on top of upstream:

- `.ometa/config.json`: upstream repo, display name, and the base app (`base`), if any:
  - `name`, `bundleId`, `appStoreId`
  - `version.from`: `upstream-tag` (regex on upstream's release tag), `upstream-asset` (regex on its release asset names), `upstream-file` (regex on a file in upstream), or `any` (the newest IPA you've uploaded)
  - or `url`: a public base IPA (no upload needed)
- `cache` (optional): `{"paths": [...], "key": "<shell command printing a key>"}`, both relative to the fork checkout, for slow dependency builds (FFmpeg etc.). Saved even if the build fails later.
- `.ometa/build.sh`: the build recipe. Runs in the fork's checkout with `SRC`, `OUT`, `BASE_IPA`, `BASE_VERSION`, `UPSTREAM_TAG` and `PIPELINE` set; can `source "$PIPELINE/lib/helpers.sh"` for Theos, cyan and IPA helpers; puts release files in `$OUT`.
- `.ometa/notes.md` (optional): text added to each release.
- `.github/workflows/ometa-watch.yml` and `ometa-build.yml`: call this repo's reusable [`watch.yml`](.github/workflows/watch.yml) and [`build.yml`](.github/workflows/build.yml).

**Watch** (every 3 hours): if upstream has a release the fork hasn't built, it starts **Build** when the base IPA is available, or opens a `needs-ipa` issue. A failed build opens a `build-failed` issue and isn't retried until re-run by hand. It also disables upstream's own workflows in the fork.

**Build**: checks out the fork, merges upstream's release tag in the runner (so the fork itself never has to be synced for a build), gets the base IPA, runs `.ometa/build.sh`, and publishes or updates the release. Release tags are upstream's tag, plus `-<app><version>` when an IPA is injected.

To customize an app, commit to its fork; then run **Actions → OMetaVR Build** (or wait for upstream's next release). To pick up upstream changes in the fork's code itself, use GitHub's "Sync fork".
