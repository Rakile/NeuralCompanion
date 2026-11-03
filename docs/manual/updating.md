# Updating NeuralCompanion

Start NC with `run_neural_companion.bat`. The launcher checks the current branch against the same branch on this installation's `origin`. When an update is available, choose **Y** to apply a normal fast-forward update, or **N** to keep the current version. Keep the public release checkout on `main` with `origin` set to `https://github.com/Rakile/NeuralCompanion`.

The launcher's **Force** option saves local tracked/untracked changes in a Git stash before trying the same fast-forward update. It does not reset your checkout or bypass unrelated histories. Review any local modifications before restoring a stash.

## Moving from an earlier public installation

This distribution starts a new public Git history. An older clone cannot pull across that history with a fast-forward update. Keep the old installation as a backup and clone the public repository into a new folder, then follow [Installation](../install.md). Do not overwrite the old folder.

Use a different parent folder from the old installation, then run:

```powershell
git clone --single-branch --branch main --no-tags https://github.com/Rakile/NeuralCompanion.git
cd NeuralCompanion
.\INSTALL_NEURAL_COMPANION.bat
```

This installs the new source and its matching dependencies. Reusing an old
virtual environment is not a migration step. Start with text chat, then enable
speech, avatars and remote connections one at a time.

Save/export chats, Personas and presets using their documented controls. Local session files may contain credentials; keep backups private. Reuse model/package folders through their supported settings where appropriate. Do not copy the old `.git`, environments, caches or application source over the new installation. See [Personas](personas.md), [Memory](memory.md), and [Troubleshooting](../troubleshooting.md).

Once installed from the new public history, later public commits use normal updates again.

## Android companion

A new signed Android download is deferred from the desktop 0.5.0 release.
The existing alpha APK remains a legacy download; its compatibility with
desktop 0.5.0 has not been validated. Phone application source is included for
maintainers who build and test their own client.

When a validated 0.5.0 Android build becomes available, it will use application
ID `com.neuralcompanion.mainchatremote`. This installs separately from older
Android Remote builds, so saved pairing and login state do not move automatically.
Pair the new app with your desktop and sign in again for Internet mode. Keep
the old phone app until you have checked the new connection.

## Legacy downloads

Earlier public tags and their download releases remain available as legacy
versions. They do not form part of the new `main` branch's history. The
`--no-tags` clone option keeps those legacy versions out of a fresh checkout;
normal later updates of `main` still work through the launcher.
