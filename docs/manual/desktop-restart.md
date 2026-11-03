# Restart the NeuralCompanion desktop

Right-click the header power button in any state, including while NC is
initializing, stopping, or waiting for cleanup. The centered restart dialog
offers **Save and restart NC**, **Do not save and restart NC**, and **Cancel**.

**Save and restart NC** saves the current conversation to its existing file,
or opens **Save Chat Context As** if it has no file yet. The five-second
countdown starts after saving succeeds. A save failure or cancelled Save As
keeps NC open. If a running reply adds output during the countdown, NC saves
those changes before restarting too.

**Do not save and restart NC** starts the countdown without saving the
conversation or asking again. Settings still use normal persistence. Cancel
or Escape during the countdown prevents restart; any completed save remains
saved. Left-clicking the power button retains its usual runtime action.

## Slash command

Enter `/restart_nc` in the desktop conversation composer, or select it from the
slash-command menu. It works whether the NC runtime is initialized or stopped.

A small centered confirmation displays the NC logo and says:

> You are about to restart NeuralCompanion.
> Restarting in 5 seconds.
> Press Enter to restart now or Esc to cancel.

The first Enter executes the command and opens the confirmation. Press Enter
again (or choose **Restart (Enter)**) to continue immediately. With no input, NC restarts
automatically after 5000 ms. **Esc** or **Cancel (Esc)** dismisses it and stops the timer
without closing NC. Reopening starts a fresh five-second countdown. The command creates no chat turn.

Save important transcript changes with **Conversation → Save** first.

Restart uses the normal desktop shutdown and session-saving flow, including
MuseTalk cleanup and closing detached windows. If cleanup rejects shutdown, NC
stays open and the pending restart is canceled. The replacement starts from the
same checkout and Python environment only after the old process exits.

If the replacement cannot launch, read the restart error and use
`run_neural_companion.bat` to reopen the same installation. See
[Troubleshooting](troubleshooting.md).
