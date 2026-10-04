# Telemetry Policy

Part of the [geoctl PRD](PRD.md). Working name; see PRD.

This document is both the internal design and the draft of the public policy that will ship in the README and `docs/telemetry.md`.

## 1. Principles

1. **Opt-in.** Nothing is sent unless the user explicitly enables it.
2. **Minimal.** Only data needed to answer: "Is anyone using this, which commands, and where does it break?"
3. **Never content.** No URLs, domains, page content, repo data, file paths, prompts, model outputs, or API keys, ever.
4. **Inspectable.** Users can see the exact payload before and after enabling it.
5. **Easy off.** One command, one environment variable, always honored.

## 2. Why opt-in rather than opt-out

The tool crawls websites and (later) reads repositories. Developers are rightly cautious about such tools phoning home. Opt-in costs some data volume but protects trust, which matters more for an early open-source project. Free signals (PyPI downloads, GitHub stars/issues, Action usage) complement it.

*This is a design decision, recorded in [DECISIONS](DECISIONS.md) ADR-005. It can be revisited, but changing from opt-in to opt-out later would require a clear announcement and a major version bump.*

## 3. How consent works

- On first interactive run (stdin and stdout are a TTY, not CI), the tool shows one prompt:

  ```
  Help improve geoctl? Share anonymous usage stats (commands, version, OS,
  error types). Never URLs, content, or keys. See what's sent: geoctl telemetry show
  Enable? [y/N]
  ```

  Default is **No**. The answer is stored in the user config.
- In non-interactive environments (CI, pipes), no prompt is shown and telemetry is **off** unless `GEOCTL_TELEMETRY=1` is set explicitly.
- `geoctl telemetry enable | disable | status | show` manage it at any time.

## 4. Hard off-switches

Telemetry is disabled, regardless of other settings, if any of these hold:

- `DO_NOT_TRACK=1`
- `GEOCTL_TELEMETRY=0`
- Running in a detected CI environment without explicit `GEOCTL_TELEMETRY=1`
- `[telemetry] enabled = false` in config

## 5. What is collected

One event per command invocation, sent asynchronously with a short timeout so it never slows or breaks the CLI.

| Field | Example | Purpose |
|---|---|---|
| `install_id` | random UUIDv4, generated locally on opt-in | Count unique installs without identifying anyone |
| `event` | `command_run` | |
| `command` | `audit` | Which commands are used |
| `tool_version` | `0.1.0` | Version adoption |
| `python_version` | `3.12` (major.minor) | Compatibility decisions |
| `os` | `linux`, `darwin`, `windows` | Platform support |
| `flags_used` | `["--eval", "--format"]` | Names of flags only, never values |
| `eval_enabled` | `true` | Feature usage |
| `provider_family` | `openai` (provider prefix only) | Which providers to prioritize; no model strings with custom endpoints |
| `pages_bucket` | `"6-10"` | Coarse size, bucketed |
| `duration_bucket` | `"10-30s"` | Coarse performance, bucketed |
| `exit_code` | `0` | Success/failure rate |
| `error_type` | `FETCH_TIMEOUT` | Stable error code only, no message text |

## 6. What is never collected

- URLs, hostnames, domains, or IP addresses of targets
- Page content, extracted text, headings, or structured data
- Facts files, questions, answers, prompts, or model outputs
- API keys or any environment variable values
- File paths, repository names, usernames, hostnames, or git remotes
- Config file contents
- The user's IP address is not stored by the collection endpoint (server logs strip it; documented)

## 7. Transparency tooling

- `geoctl telemetry show` prints the exact JSON that the *last* invocation would send, and a sample for the next.
- `GEOCTL_TELEMETRY_DEBUG=1` prints each payload to stderr instead of sending it.
- The payload schema is versioned and lives in the repo (`telemetry_schema.json`); changes require a changelog entry and, if new fields are added, a note in the release.
- The receiving endpoint's code (or a precise description of it) is public.

## 8. Data handling

- **Storage:** analytics store with access limited to maintainers.
- **Retention:** raw events kept for 12 months, then aggregated; aggregates may be kept indefinitely.
- **Sharing:** never sold; not shared with third parties except the infrastructure provider that processes events.
- **Deletion:** because events are keyed only by a random `install_id`, users can request deletion by providing that ID (shown by `geoctl telemetry status`). Rotating the ID: `geoctl telemetry disable && geoctl telemetry enable`.
- **Legal:** the data is designed to be non-personal. Confirm applicable requirements (e.g. GDPR treatment of an install ID) before launch.

## 9. Engineering requirements

- Telemetry code lives in one module (`telemetry.py`) with no dependency on audit data models, so it cannot accidentally include content.
- A unit test asserts the payload only contains allow-listed fields (an allow-list, not a deny-list).
- Network failures are swallowed silently; telemetry must never change exit codes or output.
- Timeout ≤ 2 seconds; no retries.
- Contributor rule: any PR touching `telemetry.py` needs a maintainer review focused on privacy.

## 10. Hosted service note

The future hosted service has different, contractual data handling (users upload sites and accounts exist). It will have its own privacy policy. This document covers only the open-source CLI.
