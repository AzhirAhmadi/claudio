"""claudio command line."""

from __future__ import annotations

import argparse
import json
import re
import sys
import time

from . import config as configmod
from . import consent, engines, hooks, voices
from . import pronounce as pronouncemod
from . import setup as setupmod
from .describe import describe

VERSION = "0.1.0"


def engine_choice(value: str) -> str:
    """argparse type: accept neural/local (and their config spellings)."""
    resolved = consent.normalise(value)
    if resolved is None:
        raise argparse.ArgumentTypeError(f"{value!r} is not neural or local")
    return resolved


def parse_duration(text: str) -> float:
    """'30m' / '2h' / '90' / 'today' / 'forever' -> absolute epoch seconds."""
    text = (text or "30m").strip().lower()
    if text in {"forever", "off", "always"}:
        return 4102444800.0
    if text in {"today", "eod"}:
        now = time.localtime()
        return time.mktime((now.tm_year, now.tm_mon, now.tm_mday, 23, 59, 59, 0, 0, -1))
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*([smhd]?)", text)
    if not match:
        raise SystemExit(f"claudio: cannot read duration {text!r} "
                         "(try 30m, 2h, today, forever)")
    factor = {"s": 1, "": 60, "m": 60, "h": 3600, "d": 86400}[match.group(2)]
    return time.time() + float(match.group(1)) * factor


# --------------------------------------------------------------------------- #
# commands
# --------------------------------------------------------------------------- #

def cmd_hook(args) -> int:
    """Read a hook payload on stdin and announce it. Always exits 0."""
    cfg = configmod.load()
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        return 0
    announcement = hooks.build(payload, cfg)
    if not announcement:
        return 0
    if hooks.already_said(announcement.text, float(cfg.get("notify", "dedupe_seconds"))):
        return 0
    if cfg.get("notify", "banner"):
        engines.banner(announcement.label, announcement.text)
    if not hooks.muted(cfg):
        quiet_when_focused = cfg.get("notify", "skip_turn_end_when_focused")
        if (announcement.kind == "turn_end" and quiet_when_focused
                and engines.claude_is_focused()):
            return 0
        engines.speak(cfg, announcement.text)
    return 0


def cmd_engine(args) -> int:
    """Show or change the engine. Switching to neural always re-shows the disclosure."""
    cfg = configmod.load()
    current = str(cfg.get("speech", "engine")).lower()
    if not args.name:
        print(consent.switch_summary(current))
        if consent.needs_disclosure(cfg):
            print("\n  No acceptance recorded for this engine. Run "
                  "`claudio engine neural` to review what is sent.")
        return 0

    target = consent.normalise(args.name)
    if target is None:
        print(f"claudio: unknown engine {args.name!r} (use neural or local)",
              file=sys.stderr)
        return 2

    if target == consent.NEURAL:
        # Always disclose again, even when already on neural.
        if args.yes:
            print(consent.disclaimer())
            print("\n  --yes given; accepting on your behalf.\n")
            accepted = True
        else:
            chosen, accepted = consent.ask()
            if chosen != consent.NEURAL:
                consent.record(cfg, consent.LOCAL, False)
                print(consent.switch_summary(consent.LOCAL))
                return 0
        consent.record(cfg, consent.NEURAL, accepted)
    else:
        consent.record(cfg, consent.LOCAL, False)

    print(consent.switch_summary(target))
    return 0


def cmd_setup(args) -> int:
    for note in setupmod.setup(force_config=args.force, engine=args.engine):
        print(note)
    checks, healthy = setupmod.doctor()
    if not healthy:
        print("\nsome checks failed - run `claudio doctor` for detail")
        return 1
    print("\nready. Restart Claude Code (or start a new session) to load the hooks.")
    return 0


def cmd_doctor(args) -> int:
    checks, healthy = setupmod.doctor()
    for check in checks:
        print(check.render())
    print("\nhealthy" if healthy else "\nproblems found above")
    return 0 if healthy else 1


def cmd_uninstall(args) -> int:
    removed = setupmod.uninstall_hooks()
    print(f"removed hooks: {', '.join(removed)}" if removed else "no claudio hooks found")
    print(f"config left in place at {configmod.config_path()}")
    return 0


def cmd_mute(args) -> int:
    until = parse_duration(args.duration)
    hooks.set_mute(until=until, disabled=False)
    cfg = configmod.load()
    print(hooks.muted(cfg) or "muted")
    return 0


def cmd_unmute(args) -> int:
    hooks.set_mute(until=0, disabled=False)
    print("on")
    return 0


def cmd_toggle(args) -> int:
    cfg = configmod.load()
    if hooks.muted(cfg):
        hooks.set_mute(until=0, disabled=False)
    else:
        hooks.set_mute(disabled=True)
    print(hooks.muted(configmod.load()) or "on")
    return 0


def cmd_status(args) -> int:
    cfg = configmod.load()
    print(hooks.muted(cfg) or "on")
    return 0


def cmd_say(args) -> int:
    """Speak arbitrary text. This is how Claude talks to you on purpose."""
    cfg = configmod.load()
    text = " ".join(args.text).strip()
    if not text:
        print("claudio say: nothing to say", file=sys.stderr)
        return 1
    if cfg.get("notify", "banner") and not args.quiet:
        engines.banner("claudio", text)
    if hooks.muted(cfg) and not args.force:
        print(f"suppressed ({hooks.muted(cfg)}); use --force to speak anyway")
        return 0
    used = engines.speak(cfg, text)
    print(f"spoke via {used}")
    return 0


def cmd_voice(args) -> int:
    cfg = configmod.load()
    key = "voice" if str(cfg.get("speech", "engine")).lower() == "edge" else "fallback_voice"
    if args.name:
        configmod.set_value("speech", key, args.name)
        cfg = configmod.load()
    print(cfg.get("speech", key))
    return 0


def cmd_voices(args) -> int:
    cfg = configmod.load()
    if args.local:
        found = engines.premium_local_voices()
        if not found:
            print(NO_PREMIUM)
            return 1
        for name in found:
            print(f"{'*' if name == cfg.get('speech', 'fallback_voice') else ' '} {name}")
        return 0
    hits, total = voices.list_neural(args.prefix, cfg.get("speech", "voice"))
    if not total:
        print("could not reach edge-tts - run `claudio doctor`")
        return 1
    current = cfg.get("speech", "voice")
    for name in hits:
        print(f"{'*' if name == current else ' '} {name}")
    print(f"\n{len(hits)} of {total} voices matching {args.prefix!r}")
    return 0


def cmd_demo(args) -> int:
    cfg = configmod.load()
    text = " ".join(args.text) or voices.DEMO_TEXT
    if args.local or str(cfg.get("speech", "engine")).lower() != "edge":
        played = voices.audition_local(cfg, text, args.only or None)
        if not played:
            print(NO_PREMIUM)
            return 1
        print("\nPick one:  claudio voice <name>")
        return 0
    results = voices.audition_neural(cfg, text, args.only or None)
    if not any(ok for _, ok in results):
        print("nothing could be synthesised - run `claudio doctor`")
        return 1
    print("\nPick one:  claudio voice <name>")
    print("Full list: claudio voices --prefix en-   (or de-, fr-, ...)")
    return 0


def cmd_pronounce(args) -> int:
    """Show the respelling table, or what it would do to a line of text."""
    cfg = configmod.load()
    table = cfg.pronounce
    if not args.text:
        if not table:
            print("no [pronounce] entries yet. Add them to "
                  f"{configmod.config_path()}:\n\n"
                  '  [pronounce]\n  Bestellung = "Be-shtell-ung"')
            return 0
        width = max(len(w) for w in table)
        for word, spoken in sorted(table.items()):
            print(f"  {word:<{width}}  ->  {spoken}")
        return 0

    text = " ".join(args.text)
    hits = pronouncemod.preview(text, table)
    spoken = pronouncemod.apply(text, table)
    print(f"  written: {text}")
    print(f"  spoken : {spoken}")
    if hits:
        print("  applied: " + ", ".join(f"{found} -> {rep}" for found, rep in hits))
    else:
        print("  applied: nothing matched")
    return 0


def cmd_config(args) -> int:
    path = configmod.config_path()
    if args.path:
        print(path)
        return 0
    if not path.exists():
        print(f"no config yet at {path} - run `claudio setup`")
        return 1
    print(path)
    print(path.read_text())
    return 0


def cmd_explain(args) -> int:
    """Show what a tool call would sound like. Useful for writing rules."""
    cfg = configmod.load()
    try:
        payload = json.loads(args.tool_input) if args.tool_input else {}
    except ValueError:
        print("claudio explain: --input must be valid JSON", file=sys.stderr)
        return 1
    described = describe(args.tool, payload)
    rule = cfg.rule_for(args.tool)
    variables = {"session": args.session, **described.as_template_vars()}
    print(f"tool     : {args.tool}")
    print(f"phrase   : {described.phrase}")
    print(f"fields   : {json.dumps(described.fields, indent=11)[1:-1].strip() or '(none)'}")
    if rule and rule.skip:
        print("rule     : skip = true  -> nothing would be spoken")
        return 0
    if rule and rule.say:
        print(f"rule     : {rule.say!r}")
        print(f"would say: {hooks.render(rule.say, variables)}")
    else:
        print(f"would say: {args.session}: wants to {described.phrase}")
    return 0


NO_PREMIUM = """No Premium or Enhanced voice is installed - only the robotic compact ones.

Install one (free; costs disk space, not money):
  1. System Settings -> Accessibility -> "Read & Speak"
  2. click the "System voice" pop-up -> "Manage Voices"
  3. expand English (US); uninstalled voices show a download icon
  4. download one marked (Premium), e.g. "Ava (Premium)"

Siri voices cannot be used here: macOS does not expose them to say(1).
Or stay on neural voices, which need no download:  claudio demo"""


# --------------------------------------------------------------------------- #
# parser
# --------------------------------------------------------------------------- #

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="claudio",
        description="Spoken notifications for Claude Code on macOS.",
        epilog="Start with:  claudio setup",
    )
    parser.add_argument("--version", action="version", version=f"claudio {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<command>")

    def add(name, func, help_text, **kwargs):
        item = sub.add_parser(name, help=help_text, **kwargs)
        item.set_defaults(func=func)
        return item

    item = add("setup", cmd_setup, "install config + wire Claude Code hooks")
    item.add_argument("--force", action="store_true", help="overwrite an existing config")
    item.add_argument("--engine", type=engine_choice, metavar="neural|local",
                      help="skip the interactive question (unattended installs)")

    item = add("engine", cmd_engine, "show or change the voice engine")
    item.add_argument("name", nargs="?", metavar="neural|local")
    item.add_argument("--yes", action="store_true",
                      help="accept the neural disclosure without prompting")

    add("doctor", cmd_doctor, "check everything claudio needs")
    add("uninstall", cmd_uninstall, "remove claudio's hooks from Claude Code")

    item = add("say", cmd_say, "speak a line of text now")
    item.add_argument("text", nargs="+")
    item.add_argument("--force", action="store_true", help="speak even while muted")
    item.add_argument("--quiet", action="store_true", help="no banner")

    item = add("mute", cmd_mute, "silence speech (30m, 2h, today, forever)")
    item.add_argument("duration", nargs="?", default="30m")

    add("unmute", cmd_unmute, "resume speech")
    add("toggle", cmd_toggle, "flip between on and off")
    add("status", cmd_status, "one word: on, off, or muted <time>")

    item = add("voice", cmd_voice, "show or set the active voice")
    item.add_argument("name", nargs="?")

    item = add("voices", cmd_voices, "list available voices")
    item.add_argument("--prefix", default="en-", help="language prefix, e.g. de-")
    item.add_argument("--local", action="store_true", help="installed macOS voices instead")

    item = add("demo", cmd_demo, "hear a sentence in each candidate voice")
    item.add_argument("text", nargs="*")
    item.add_argument("--local", action="store_true", help="audition macOS voices")
    item.add_argument("--only", action="append", help="audition just this voice (repeatable)")

    item = add("pronounce", cmd_pronounce,
               "show the respelling table, or test it on some text")
    item.add_argument("text", nargs="*")

    item = add("config", cmd_config, "show the config file")
    item.add_argument("--path", action="store_true", help="print the path only")

    item = add("explain", cmd_explain, "preview what a tool call would sound like")
    item.add_argument("tool", help="tool name, e.g. Edit or Bash")
    item.add_argument("--input", dest="tool_input", help="tool_input as JSON")
    item.add_argument("--session", default="my session", help="session name to use")

    add("hook", cmd_hook, "internal: consume a hook payload on stdin")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
