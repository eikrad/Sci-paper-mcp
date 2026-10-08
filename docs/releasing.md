# Releasing

Versions and the CHANGELOG are written by [release-please](https://github.com/googleapis/release-please)
from Conventional Commit messages. Nobody edits version numbers by hand.

## How a release happens

1. Changes reach `main` the usual way: feature branch → `staging` → `main`.
2. On every push to `main`, the **Release** workflow (`.github/workflows/release-please.yml`)
   opens or updates a pull request titled `chore(main): release X.Y.Z`. It bumps the version in
   `pyproject.toml`, syncs `uv.lock` and adds the `CHANGELOG.md` entry.
3. When you want to release, merge that pull request. release-please tags `vX.Y.Z`, publishes a
   GitHub release with the same notes and opens a pull request that merges `main` back into
   `staging`. Merge that one too.

Until you merge the release PR, it keeps collecting whatever lands on `main`. The install snippet in
the README pins a tag (`…@v0.1.0`); it works once that tag exists.

## The first release

The repo has no earlier tag, and the README already points at `v0.1.0`. The package entry in
`release-please-config.json` therefore carries `"release-as": "0.1.0"` and the manifest starts at
`0.0.0`. After the first release PR has been merged, remove the `release-as` line (otherwise the next
release would be pinned to 0.1.0 as well).

## Which version comes next

Before 1.0 (`bump-minor-pre-major` and `bump-patch-for-minor-pre-major` in `release-please-config.json`):

| Commit | Effect on 0.1.0 |
|---|---|
| `fix: …` or `feat: …` | 0.1.1 |
| `feat!: …` or a `BREAKING CHANGE:` footer | 0.2.0 |
| `docs`, `chore`, `build`, `ci`, `test`, `refactor`, `style` | no release on its own |

`feat`, `fix`, `perf`, `security` and `revert` appear in the CHANGELOG; the other types are hidden.
The **Commit messages** check fails a pull request with a commit that lacks a prefix, since
release-please would silently leave that commit out.

## One-time setup

Pull requests opened with the workflow's own `GITHUB_TOKEN` do not trigger other workflows, so CI
would not run on the release PR. Without further setup the workflow still works: it falls back to
`GITHUB_TOKEN`, but then the release PR's checks have to be run by hand. To get the full flow:

1. Repository Settings → Actions → General → Workflow permissions: allow GitHub Actions to create
   and approve pull requests (needed for the fallback; harmless with the token).
2. Create a [fine-grained token](https://github.com/settings/personal-access-tokens/new) for this
   repository only, with **Contents: Read and write** and **Pull requests: Read and write**, and an
   expiry you will remember.
3. Store it as the repository secret `RELEASE_PLEASE_TOKEN` (Settings → Secrets and variables →
   Actions). Job-Tracker and Bandsearch use the same secret name; one token can cover all three
   repositories if you select each of them.

## Changing the next version by hand

Set `"release-as": "1.0.0"` for the `"."` package in `release-please-config.json`, merge it to `main`,
and remove the line again after the release.
