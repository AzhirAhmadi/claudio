# claudio

Spoken notifications for [Claude Code](https://claude.com/claude-code) on macOS.

Not "Claude needs your attention." Instead: **which session**, and **what it actually wants**.

```
"billing refactor: edit invoice policy, changing validates :amount, presence: true"
"api cleanup: run the checkout specs"
"sick leave fix is waiting. Should I open the PR as a draft?"
```

Because when three sessions are running and every permission prompt says the same
eleven words, the notification tells you nothing. `claudio` reads the actual tool
call — which file, which command, which agent — and says that instead.

## Install

```bash
brew install AzhirAhmadi/claudio/claudio && claudio setup
```

`setup` writes a documented config, wires the Claude Code hooks, verifies
everything, and **asks which voice engine you want** — because the better-sounding
one sends text to Microsoft, and you should decide that with the facts in front of
you, not discover it later. See [Privacy](#privacy--read-this-if-you-use-claude-code-at-work).

Then restart Claude Code. No API key, no account, nothing to paste.

<details>
<summary>Without Homebrew</summary>

```bash
curl -fsSL https://raw.githubusercontent.com/AzhirAhmadi/claudio/main/install.sh | sh
```

Installs [uv](https://docs.astral.sh/uv/) if missing, then the tool, then runs setup.
</details>

## What you hear

| When | Example |
|---|---|
| Permission needed | *"billing refactor: edit invoice policy, changing validates :amount"* |
| Session waiting | *"sick leave fix is waiting. Should I open the PR as a draft?"* |
| Long turn finished | *"specs: all 14 pass. Shall I merge?"* |

Three things keep it from becoming noise:

- A finished turn is only announced if it ran longer than `min_turn_seconds` (45 by
  default) — if it was quick, you were watching.
- Nothing is spoken at turn end while Claude is the front app.
- Repeats inside `dedupe_seconds` are dropped.

The session name is the title you see in the sidebar. `claudio` recovers it from the
transcript, because a manually set title never reaches `~/.claude/sessions/`. A
sorting-key prefix like `2-1994 ` is dropped before speaking — it reads terribly out
loud.

## Silence it

Speech always leaves a banner behind, so muting loses nothing.

```bash
claudio mute 1h        # also: 30m, 2h, today, forever
claudio unmute
claudio status         # on | off | muted 47m
claudio toggle         # bind this to a hotkey
```

## Voices

322 neural voices, free, no key. Hear the good ones and pick:

```bash
claudio demo                       # auditions a curated shortlist
claudio voice en-GB-SoniaNeural    # set it
claudio voices --prefix de-        # list a language
```

Two distinctions worth knowing. **`Multilingual`** variants pronounce foreign words
inside an English sentence correctly — worth a lot if your branch names aren't
English. And the **`Conversation, Copilot`** voices (Ava, Andrew, Brian, Emma) are
tuned for short assistant utterances; the `News, Novel` ones read declamatory on a
one-line notification.

Prefer to stay fully offline? `engine = "say"` uses macOS's built-in synthesiser.
Its stock voices are robotic, so download a better one — free, and only costs disk
space:

> System Settings → Accessibility → **Read & Speak** → **System voice** → **Manage
> Voices** → download one marked **(Premium)**

Then `claudio demo --local`. Siri's voices can't be used: macOS doesn't expose them
to `say(1)`, even though the assets are on disk.

## Rules — control what gets said

Out of the box a permission request already describes itself. Rules let you reword
it, or stay quiet for tools you don't care about. Config lives at
`~/.config/claudio/config.toml`.

```toml
[[rule]]
tool = "Read"
skip = true                                   # reading files is never worth an interruption

[[rule]]
tool = "Bash"
say = "{session}: {description}"              # already imperative; don't add a verb

[[rule]]
tool = "mcp__*"                               # globs work
say = "careful — database access on {server}"
```

`tool` is an exact name or a glob. `say` is a template. `skip = true` stays silent.
First matching rule wins.

Available placeholders, beyond `{session}`, `{tool}` and `{phrase}`:

| Tool | Fields |
|---|---|
| `Edit` `Write` `Read` | `{file}` `{path}` `{change}` `{lines}` |
| `Bash` | `{description}` `{command}` `{program}` |
| `Grep` `Glob` | `{pattern}` `{path}` |
| `WebFetch` `WebSearch` | `{domain}` `{query}` `{url}` |
| `Task` | `{agent_type}` `{description}` |
| `mcp__*` | `{server}` `{mcp_tool}` |

`{description}` for Bash is the human-readable summary Claude writes for every shell
call — usually far better to hear than the raw command.

Test a rule without waiting for a real prompt:

```bash
claudio explain Bash --input '{"command":"rails db:migrate","description":"Run migrations"}'
```

## Let Claude talk to you deliberately

`claudio say` speaks arbitrary text, so Claude can use it as a tool:

```bash
claudio say "The migration finished. 4,812 rows backfilled."
```

Add this to your `CLAUDE.md` to make it a habit:

```markdown
When you finish a long task and I may have walked away, run:
  claudio say "<one short sentence>"
```

It honours mute, so it won't betray you in a meeting.

## Commands

| | |
|---|---|
| `claudio setup` | write config, wire hooks, verify |
| `claudio doctor` | check everything, with fixes |
| `claudio say <text>` | speak now |
| `claudio mute [dur]` / `unmute` / `toggle` / `status` | control |
| `claudio demo [text]` | audition voices |
| `claudio voices [--prefix] [--local]` | list voices |
| `claudio voice [name]` | show or set the voice |
| `claudio explain <tool> --input <json>` | preview a rule |
| `claudio engine [neural\|local]` | show or change the engine (re-shows the disclosure) |
| `claudio config [--path]` | show the config |
| `claudio uninstall` | remove the hooks |

## How it works

Three Claude Code hooks, wired into `~/.claude/settings.json`:

- **`PermissionRequest`** carries `tool_name` and `tool_input` — this is what makes
  the specific descriptions possible.
- **`Notification`** covers idle sessions. Its `permission_prompt` variant is
  suppressed when `PermissionRequest` already said something richer.
- **`Stop`** carries `last_assistant_message` for the end of a long turn.

The hook returns in milliseconds; synthesis is detached, so the 10-second hook
timeout can never bite. When a neural voice can't be reached — offline, VPN, DNS —
it degrades to the local `say` voice rather than going silent. Hearing the robotic
voice means you're offline, not that something broke.

`setup` only ever appends its own hook entries, backs up `settings.json` first, and
`uninstall` removes exactly what it added.

## Privacy — read this if you use Claude Code at work

`claudio` speaks the content of your sessions: session titles, file names, shell
command descriptions, and the last thing Claude said. **With `engine = "edge"`, that
text is sent to Microsoft's Edge TTS endpoint to be synthesised** — the same service
the Edge browser's Read Aloud uses. No key, no account, and `claudio` stores nothing.
But the text does leave your machine.

For notification-length strings about a personal project, that is usually fine. **If
you work on a private or client codebase, it may not be** — a session title and a
file name can be enough to disclose something you are not allowed to disclose.

### You are asked, not opted in

`claudio setup` prints exactly what would be sent — item by item, including that a
single line of the code being edited is part of it — and then asks. **Declining is
the default:** a bare Enter, a Ctrl-C, or no terminal at all (a piped `curl | sh`)
all select the local engine. Acceptance is recorded in `state.json`, not in the
editable config, so it cannot be forged by hand-editing a file.

Switching later re-shows the whole disclosure every time:

```bash
claudio engine neural     # discloses, then asks
claudio engine local      # no prompt needed; nothing leaves your Mac
claudio engine            # what am I on right now?
```

If `config.toml` says neural but no acceptance was ever recorded, `claudio doctor`
flags it rather than quietly proceeding.

On the local engine, download a Premium voice (see [Voices](#voices)) so it doesn't
sound robotic. You can also stay on neural but go quiet for a while — `claudio mute
today` — since a muted announcement is never synthesised and so never sent anywhere.

### Credentials

**`claudio` needs no API key, token, or account.** Nothing to paste, nothing to
rotate, nothing to leak. `config.toml` holds only voice and behaviour settings, and
a test in this repo fails the build if any credential-shaped name appears in `src/`.

If a future engine ever does need a key, the rule is: `claudio setup` asks for it
interactively, it goes into the **macOS Keychain**, and it never touches
`config.toml` or the repo.

### What this repo does not contain

This tool was written while working on a private codebase, so `tests/test_no_private_data.py`
scans every file on each test run and fails on employer names, internal domain
vocabulary, ticket IDs, real email addresses, and anything shaped like a
credential — API keys, tokens, JWTs, private keys, database URLs with passwords.
Every example in the docs and tests is invented.

## Requirements

macOS (Apple Silicon or Intel), Claude Code, Python 3.11+. Homebrew installs its own
Python, so there's nothing else to manage.

## License

MIT
