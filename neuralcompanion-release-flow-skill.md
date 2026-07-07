---
name: neuralcompanion-release-flow
description: Use when working on NeuralCompanion git release workflow, especially origin/main, origin/release, public/main, hotfixes, public releases, back-merges, or syncing private and public repositories.
---

# NeuralCompanion Release Flow

## Branch Roles

Treat the branches as separate lanes:

- `origin/main`: active development. May contain new features, unfinished work, experiments, and future release changes.
- `origin/release`: clean public-release staging branch. Should contain only code that is ready for public release or urgent public hotfixes.
- `public/main`: public repository main branch. It should mirror `origin/release` when publishing releases or hotfixes.

Do not push unfinished `origin/main` work directly to `public/main`.

## Normal Public Release

When the user asks for a public release:

1. Make sure `origin/main` is tested and intended for release.
2. Merge or fast-forward `origin/release` to the chosen `origin/main` release commit.
3. Push `origin/release`.
4. Mirror `origin/release` to `public/main`.
5. Do not invent release commit messages like `merge docs` if this is a major feature release. Use a meaningful release title, for example:
   - `Release NeuralCompanion 0.3`
   - `Release NeuralCompanion 0.3: Discord Voice Bridge`

## Hotfix Flow

Use hotfix flow when public users need a fix but `origin/main` contains unfinished work.

1. Work from `origin/release`, not `origin/main`.
2. Create a hotfix branch from release:

```bash
git checkout release
git pull origin release
git checkout -b hotfix/<short-description>
```

3. Make only the minimal patch needed.
4. Commit the hotfix.
5. Merge the hotfix into `release`.
6. Push `origin/release`.
7. Mirror `origin/release` to `public/main`.
8. Later, back-merge `origin/release` into `origin/main` so development also receives the fix.

## Back-Merge Rule

Back-merge means bringing the already-made release hotfix commit back into `origin/main`.

The patch is created against `origin/release`.

Then Git tries to apply that same commit into `origin/main`.

Use:

```bash
git checkout main
git pull origin main
git merge origin/release
```

If there is a conflict, resolve it by preserving the hotfix behavior while respecting the newer `main` version.

Do not manually reimplement the hotfix unless Git cannot merge it cleanly.

## Safety Rules

Before changing branches:

```bash
git status --short
```

Do not switch branches with uncommitted user work unless it is intentionally committed, stashed, or moved to a separate worktree.

Prefer a separate physical checkout for `origin/release` if there is any risk of confusing release work with active development work.

Suggested layout:

```text
Q:\AA NC\NeuralCompanion-dev       -> origin/main
Q:\AA NC\NeuralCompanion-release   -> origin/release
```

## Public Mirror Rule

`public/main` should normally be updated only from `origin/release`.

Do not let `public/main` diverge with random independent commits. If public docs or media are changed, mirror those changes back into `origin/main` or `origin/release` as appropriate.

## Before Push

Always show or inspect:

```bash
git status --short
git log --oneline --decorate -n 8
git diff --stat origin/<branch>..HEAD
```

If anything looks surprising, stop and ask the user.

## Short Pasteable Instruction

If this is not installed as a skill, paste this into Codex instead:

```text
For NeuralCompanion, use this release workflow:

- origin/main is active development and may contain unfinished work.
- origin/release is the clean public-release staging branch.
- public/main should mirror origin/release, not random dev commits.

For public releases: merge tested origin/main into origin/release, then mirror origin/release to public/main.

For urgent public hotfixes: branch from origin/release, patch only the bug, merge back into origin/release, publish to public/main, then back-merge origin/release into origin/main.

Never push unfinished origin/main directly to public/main.

Before switching branches or pushing, always run:
git status --short
git log --oneline --decorate -n 8

If anything looks surprising, stop and ask.
```
