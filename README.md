![Paper Fetcher](assets/paperFetcher_IMG.png)

# PaperFetcher

> Every morning, a fresh AI / robotics paper from arXiv lands on your phone as a 10-minute podcast.

Reading the latest research is hard to fit into a busy week. PaperFetcher does
it for you while you sleep: it scans the day's arXiv submissions in AI,
machine learning, robotics, computer vision, and NLP, picks the single paper
most aligned with your research interests, has Claude write a conversation
between two co-hosts about it, synthesizes the audio with two distinct voices,
and drops the episode in your Google Drive folder. By the time you wake up,
it's on your phone — ready for the morning commute.

## What you get each day

In a folder named like `2026-05-12/`, locally and synced to your Drive:

| File | What it is |
|---|---|
| **`digest.mp3`** | The episode itself — ~10 minutes, two voices, conversational |
| **`digest.md`** | A written one-paragraph summary, if you'd rather read |
| **`outline.md`** | A structured "cheat sheet" of the paper's key ideas |
| **`paper.pdf`** | The original arXiv PDF, in case you want to dig deeper |

## Install

Ubuntu or Debian — one command:

```bash
wget -qO- https://raw.githubusercontent.com/LucaFrat/PaperFetcher/main/install.sh | bash
```

The installer takes about 10 minutes — most of it the Google Drive browser
auth — and walks you through a friendly setup wizard:

1. **Episode length** — anywhere from 5 to 15 minutes.
2. **Voices** — pick free Edge TTS voices, or paste in your two ElevenLabs
   voice IDs for premium quality.
3. **Schedule** — which days (weekdays only or every day) and what time the pipeline should run.
4. **Google Drive** — the wizard launches `rclone config` if you haven't set
   up a remote yet.

Then, as the final step, the installer opens an **interactive chat with
Claude** to define your research interests. Claude asks focused questions,
shows you drafts as it goes, and writes the result to
`config/interests.md` once you confirm. This profile is what decides which
paper gets picked for you every day — the chat gets you to a much sharper
description than free-form typing usually does.

When you're happy with the draft, ask Claude to save it and type `/exit` to
return to the installer. The pipeline is then armed and will fire
automatically on your chosen schedule.

### Before you install

You'll need:

- **[Claude Code CLI](https://code.claude.com/docs)** — install it and run
  `claude login` with a Max-plan account.
- **A Google account** for Google Drive (the wizard handles the OAuth).
- **(Optional) An [ElevenLabs](https://elevenlabs.io) Creator subscription**
  if you want premium voices. The free Edge TTS option works fine and you
  can switch later. If you go with ElevenLabs, export your API key in the
  same terminal *before* running the installer:

  ```bash
  export ELEVENLABS_API_KEY=sk_xxxxxxxxxxxxxxxxxxxxxxxx
  ```

  (Add it to `~/.bashrc` or `~/.zshrc` to keep it across shells.)

## After install

**Force a test run right now:**

```bash
systemctl --user start paperfatcher.service
```

**Watch it live:**

```bash
journalctl --user -u paperfatcher.service -f
```

**When does the next run happen?**

```bash
systemctl --user list-timers paperfatcher.timer
```

## Cost

| | Cost per month |
|---|---|
| Claude (Max plan) | already covered by your subscription |
| Google Drive (via rclone) | free |
| **Edge TTS** *(default, decent quality)* | free |
| **ElevenLabs** *(optional, premium voices)* | $22/mo (Creator tier) |

A typical 10-minute episode uses ~5,500 ElevenLabs credits — well within
the Creator monthly allowance.

## Customize later

After install, two files in `~/.local/share/paperfetcher/config/` are yours
to tweak any time:

- **`interests.md`** — your research interests. Edit by hand for small
  tweaks, or re-run the Claude chat to rework them from scratch:

  ```bash
  bash ~/.local/share/paperfetcher/installer/onboard_interests.sh
  ```

  The chat reads your existing `interests.md` first and offers to refine it,
  so you won't lose your previous draft unless you ask it to start over.

- **`settings.toml`** — episode length, voice IDs, schedule, Drive folder.
  The wizard wrote sensible values; tune by hand if you want.

After editing either, the next scheduled run picks up the change automatically.

## Uninstall

```bash
bash ~/.local/share/paperfetcher/uninstall.sh
```

Removes the install directory, systemd timer, and API-key file. Doesn't touch
system packages, your rclone config, or the episodes already on your Drive.
Add `--yes` to skip the confirmation.

## Troubleshooting

**The cron didn't fire after I rebooted.**
Linger isn't enabled. Without it, user-level systemd timers pause when you
log out.

```bash
sudo loginctl enable-linger "$USER"
```

**Weekend runs occasionally produce nothing.**
arXiv announces papers Mon-Fri. If you chose "Every day" at install time,
weekend runs pull from the 72-hour fetch window — usually enough material,
but on quiet weeks you may get a "0 papers" no-op. The pipeline logs this
and exits cleanly. If you'd rather skip weekends entirely, re-run the
wizard and pick "Weekdays only".

**ElevenLabs error: "quota_exceeded".**
Either the per-API-key credit cap is set too low (raise it to "Unlimited" in
the ElevenLabs dashboard), or you've used your monthly Creator allowance
(check at elevenlabs.io/app/settings).

**No paper picked on a weekday.**
Probably a transient arXiv outage. Check the most recent log:

```bash
journalctl --user -u paperfatcher.service -n 100
```

## License

Personal project — no license set. If you fork it, add one.
