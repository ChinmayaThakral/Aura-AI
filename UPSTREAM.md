# Fork maintenance

Work in this repository: [ChinmayaThakral/Aura-AI](https://github.com/ChinmayaThakral/Aura-AI).
Its working/default branch is `macos`; `master` preserves upstream's Windows
branch. `origin` points to this fork, and `upstream` points to
[Rkcr7/Aura-AI](https://github.com/Rkcr7/Aura-AI).

The migration combines upstream `macos` at `5c061ad` with upstream `master` at
`dd23428`, including the 28 intervening master commits, then applies the local
macOS customizations. The MIT license and upstream attribution are retained.
The original Windows README is preserved as [README-UPSTREAM.md](README-UPSTREAM.md);
the main [README](README.md) describes this fork's Mac workflow.

The imported work includes Quotio configuration, app packaging, onboarding/key
fixes, optional profile defaults, Chrome/desktop sync, continuous conversation,
native shortcuts/window controls, and direct Mac playback capture. Conflicts
were reconciled to keep upstream's base64 audio transport, 1024-sample batching,
provider key filtering/catalogue, provider-specific screenshot limits, smaller
screenshots, reduced motion, safe Markdown and KaTeX math rendering.
Desktop screenshots use the native main-display capture path on request, so
direct playback and vision do not require an Aura Chrome tab.

Customizations were imported as source-file changes rather than publishing the
private repository's commit history. Saved credentials and personal profiles
remain in ignored local files; generated builds and virtual environments are
also excluded. The previous checkout is retained locally as a backup and is no
longer the working repository.

## Updating later

```sh
git fetch upstream
git switch macos
git pull --ff-only origin macos
git switch -c feature/upstream-sync
git merge upstream/macos
git merge upstream/master
```

Resolve platform conflicts using the Mac AppKit window manager and Cocoa
startup path. Retain shared upstream fixes; keep both audio capture paths,
48 kHz mono PCM and the backend/frontend transport in agreement. Run the
[validation checks](CONTRIBUTING.md#validation), then push to `origin` and open
a PR against this fork's `macos` branch. Do not push directly to `upstream`.

After changing bundled resources, rebuild/install Aura, fully restart it and
hard-refresh any optional Aura Chrome page. Source runs use this checkout's
ignored configuration; packaged apps keep using
`~/Library/Application Support/Aura/`.
