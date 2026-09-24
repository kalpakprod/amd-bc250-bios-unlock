# Changelog

Every change to this repo ships as a versioned release. Versions follow
[Semantic Versioning 2.0.0](https://semver.org): `MAJOR.MINOR.PATCH`.

## Versioning rules (this repo's interface)

- MAJOR: anything pinned breaks. Release asset filenames or URLs, builder
  script names or CLI, image bytes under an existing name, removed
  `.build.json` fields.
- MINOR: backward-compatible additions. New rungs or images, new tools, new
  docs chapters, new manifest fields.
- PATCH: backward-compatible fixes. Prose and typo fixes, manifest metadata
  corrections, rebuilds with byte-identical output.
- Releases are immutable: a published release's assets never change. A rename
  or a byte change always becomes a NEW version that supersedes the old one.

## [2.1.0] — 2026-09-24

- Added: Linux kernels (bore-vcn 7.2.6-1.3 + bc250 7.2.6-1.206): pacman
  packages, raw vmlinuz+initramfs, 3 mode cmdlines, local patch delta,
  installer scripts, `docs/06-linux-kernels.md`.
- Changed: ladder verdicts (STUB-early BOOTS, FULL-appended 1-blink hang,
  STUB-appended BOOTS, H19 wins). `.txt` cards and `.build.json` metadata
  refreshed; image bytes unchanged.
- Note: bore-vcn 1.3 PKGBUILD + `bc250_vcn_mode` patch source missing
  (stated in `kernels/README.md`).

## [2.0.0] — 2026-09-24

BREAKING: every ladder filename now says what is inside. Image bytes and
shas are unchanged — only names.

- Changed: 7 image files renamed (`FULL`/`STUB` + what differs + placement);
  old `vNN` tags demoted to `alias` in each `.build.json`.
- Changed: 5 builder scripts renamed to match (`build_FULL_…`,
  `build_STUB_…`); default input/output names follow.
- Changed: release assets carry the new names. `v1.0.0` assets keep the old
  names for history.
- Changed: READMEs, guides, tools table, hero panels, driver headers use
  plain names first, alias second.
- Added: a same-name `.txt` card per image (contents, builder, sha, verdict).
- Added: this changelog.
- Frozen: the `v009-rtb` DEBUG string inside the driver binary (renaming it
  would change frozen image bytes).

## [1.0.0] — 2026-09-24

- Initial public showcase: 7-image ladder (old `vNN` names), 5 builders,
  10-gate preflight, OVMF harness, post-flash VCN check, driver sources,
  bilingual README, 5 guides.
