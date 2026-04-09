# Contributing

NeuralCompanion is the shared source repository for collaborative development. Treat it as the curated codebase, not as a local lab dump.

## Workflow

- Create a feature branch for each change.
- Keep `main` as the tested integration branch.
- Merge tested work back into `main` in small, reviewable changes.
- If a feature is experimental or incomplete, keep it on a branch until it is stable enough to share.

## What Not To Commit

Do not commit local-only or generated artifacts unless the repository intentionally decides to vendor them.

This includes:

- runtime output
- session files
- logs
- generated audio, images, or video
- model weights and checkpoints
- bundled third-party apps or tool installs
- machine-specific cache folders

If you intentionally need to vendor a large or third-party asset, document why in the PR and keep the scope explicit.

## Repo Hygiene

- Prefer relative paths in docs and code comments.
- Avoid machine-local absolute paths in committed documentation.
- Keep commits focused on one change area.
- Update docs when behavior or setup changes.
- Do not mix unrelated cleanup into feature branches unless it is necessary for the feature.

## Before Merging

- Run the relevant local validation for your change.
- Sanity-check `.gitignore` coverage if your work creates new runtime artifacts.
- Review the diff for accidental binaries or generated files.
- Make sure the branch is understandable to another contributor without local context.

## Practical Rule

If a file is produced by running the app rather than authored as source, it probably does not belong in the repo.
