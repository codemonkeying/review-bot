# review-bot

An advisory pull-request reviewer for GitHub Actions, written by a **free** hosted model.
It posts one review per head commit (on the Reviews tab, event `COMMENT`) with a
verdict line and up to five findings tagged **HIGH**, **MED** or **LOW**. It is a cheap
second opinion, never a merge gate.

- **Free-model only.** The model id must end in `:free`/`-free`; anything else is
  refused, so it cannot spend against an account. No API key is needed.
- **Never silent.** Empty or failed model replies are retried (with backoff); if none
  succeeds, a visible "No usable review" note is posted instead.
- **Untrusted input.** The diff is treated as data; the prompt tells the model to quote
  the line it means rather than guess line numbers.
- **Same-repo PRs only.** PRs from forks are skipped.
- Stdlib-only Python, no dependencies.

## Use it

Copy [`examples/caller.yml`](examples/caller.yml) to `.github/workflows/pr-review.yml`
in your repo. That's all.

**Pinning:** `@main` tracks the latest version. To pin, use a tag or sha in `uses:` and
pass the same value as `bot_ref` (a called workflow can't see its own ref, so the
script is checked out from `bot_ref`, default `main`):

```yaml
    uses: codemonkeying/review-bot/.github/workflows/review.yml@v1
    with:
      bot_ref: v1
```

## Per-repo settings

Optionally add `.github/review.toml` (see [`examples/review.toml`](examples/review.toml)).
It is read from the PR's **base** commit, so a PR can't reconfigure its own review.
An unreadable config (not UTF-8, over 64 KB, an API error) stops the run with a clear
error rather than reviewing with the wrong settings.

| key            | meaning                                              | default |
|----------------|------------------------------------------------------|---------|
| `enabled`      | `false` turns the bot off for the repo               | `true`  |
| `model`        | free model id                                        | `nvidia/nemotron-3.5-super-vl:free` |
| `extra_prompt` | extra review guidance for this repo (max 4000 chars) | none    |
| `diff_limit`   | chars of diff sent to the model, 1000..200000        | `24000` |

Precedence for the model: the caller's `with: model:` input, then `review.toml`, then
the default.

## Tests

```
python3 tests/test_pr_review.py
```

Offline; GitHub and the model are stubbed.
