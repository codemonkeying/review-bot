"""Offline tests for pr_review.py: free-model guard, review extraction, main() flow
with stubbed GitHub/model calls, diff trimming, backoff and .github/review.toml."""
import base64
import importlib.util
import sys
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("pr_review", ROOT / "pr_review.py")
pr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pr)
FAIL = []


def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond:
        FAIL.append(name)


check("free :free", pr._is_free("nvidia/nemotron-3.5-lightning:free"))
check("free -free", pr._is_free("reflection/beam-free"))
check("paid refused", not pr._is_free("claude-sonnet-4-6"))
check("paid refused 2", not pr._is_free("gpt-4o"))

ex = pr.extract_review
R = "Looks good overall; one nit in foo.py."
check("tagged content", ex(f"x <review>{R}</review>", None) == R)
check("reasoning never posted", ex(None, f"thinking... <review>{R}</review>") == "")
check("raw reasoning not posted", ex(None, "Here's a thinking process: 1. ...") == "")
check("untagged content kept", ex(R, None) == R)
check("think block stripped", ex(f"<think>hmm</think>{R}", None) == R)
check("last tag wins", ex(f"<review>draft draft draft draft</review> <review>{R}</review>", None) == R)
check("echoed instruction dropped", ex(None, "wrap it between <review> and </review> tags") == "")
check("unclosed think dropped", ex(f"{R} <think>secret chain of thought", None) == R)
check("lone close think", ex(f"chain of thought here</think>{R}", None) == R)
check("unclosed review -> tail", ex(f"drafts... <review>{R}", None) == R)
check("tagged unusable, no draft fallback", ex("lots of draft notes <review></review>", None) == "")
check("uppercase tags", ex(f"<REVIEW>{R}</REVIEW>", None) == R)
check("mentions neutralised", "@team" not in ex(f"<review>{R} cc @team</review>", None))
check("length capped", len(ex("<review>" + "x" * 9000 + "</review>", None)) < 6100)

check("review inside think ignored", ex(f"<think>x <review>draft draft draft draft</review></think>{R}", None) == R)
check("cut-off think with review dropped", ex("<think>long chain of thought <review>partial partial", None) == "")
check("reasoning unclosed not posted", ex(None, f"thinking <review>{R} and more drafts") == "")

# main(): stubbed _gh / model, no network
import os as _os
calls = []
SEEN = {}
pr.time.sleep = lambda s: None   # no real backoff waits in tests
CFG = {"toml": None}
def run_main(review, reviews, head_sha="abc1234def", toml=None, base="base000"):
    calls.clear()
    CFG["toml"] = toml
    seen = {"n": 0}
    def gh(method, path, token, body=None, accept=None):
        calls.append((method, path, body))
        if "/contents/.github/review.toml" in path:
            if CFG["toml"] is None:
                raise urllib.error.HTTPError(path, 404, "nf", {}, None)
            if isinstance(CFG["toml"], Exception):
                raise CFG["toml"]
            if isinstance(CFG["toml"], (dict, list)):
                return CFG["toml"]
            raw = CFG["toml"] if isinstance(CFG["toml"], bytes) else CFG["toml"].encode()
            return {"type": "file", "encoding": "base64", "size": len(raw),
                    "content": base64.b64encode(raw).decode()}
        if method == "GET" and "/reviews" in path:
            return reviews
        if accept and "diff" in accept:
            return "diff --git a/x b/x\n+1\n"
        if method == "GET":
            return {"title": "t", "body": "desc", "base": {"sha": base} if base else {},
                    "head": {"sha": head_sha} if head_sha else {}}
        return {}
    def model(*a):
        seen["n"] += 1
        seen["args"] = a
        return review(seen["n"]) if callable(review) else review
    pr._gh = gh
    pr._review_from_model = model
    _os.environ.update(GITHUB_TOKEN="t", GITHUB_REPOSITORY="o/r", PR_NUMBER="1")
    _os.environ.pop("REVIEW_MODEL", None)
    pr.main()
    SEEN.update(seen)
    return [c for c in calls if c[0] in ("POST", "PATCH")], seen["n"]
w, n = run_main("", [])
check("main: empty x3 -> retried TRIES times", n == pr.TRIES)
check("main: empty -> visible 'no review' note posted as a review", len(w) == 1
      and w[0][1].endswith("/pulls/1/reviews") and "No usable review" in w[0][2]["body"])
w, n = run_main(lambda k: "" if k < 2 else R, [])
check("main: empty then usable -> retry wins", n == 2 and R in w[0][2]["body"])
w, n = run_main(R, [])
check("main: review posted as COMMENT review with sha", len(w) == 1 and w[0][2]["event"] == "COMMENT"
      and w[0][2]["commit_id"] == "abc1234def" and "`abc1234`" in w[0][2]["body"])
w, n = run_main(R, [{"body": pr.MARKER + " old", "commit_id": "abc1234def", "user": {"type": "Bot"}}])
check("main: same commit already reviewed -> no duplicate", w == [])
w, n = run_main(R, [{"body": "quoting " + pr.MARKER, "commit_id": "abc1234def", "user": {"type": "User"}}])
n0 = n
w, n = run_main(R, [{"body": pr.MARKER + " " + pr.NO_REVIEW, "commit_id": "abc1234def", "user": {"type": "Bot"}}])
check("main: earlier 'no review' note doesn't block a real review", len(w) == 1 and R in w[0][2]["body"])
w, n = run_main(R, [{"body": pr.MARKER + " old", "commit_id": "abc1234def", "user": {"type": "Bot"}}])
check("main: dedup happens before any model call", n == 0)
import http.client as _hc
def _boom(k):
    raise _hc.RemoteDisconnected("dropped")
w, n = run_main(_boom, [])
check("main: dropped connection -> retried, note posted", n == pr.TRIES and "No usable review" in w[0][2]["body"])
check("main: human quote doesn't suppress the review", len(w) == 1)
w, n = run_main(R, [], head_sha=None)
check("main: no sha -> no empty code span, no commit_id", "``" not in w[0][2]["body"] and "commit_id" not in w[0][2])
big = "".join(f"diff --git a/f{i}.py b/f{i}.py\n" + "+x\n" * 3000 for i in range(4))
txt, om = pr._trim_diff(big, 20000)
check("trim: cuts at a file boundary", txt.endswith("+x\n") and txt.count("diff --git") >= 1 and om)
check("trim: omitted files listed", all(o.startswith("f") for o in om))
import urllib.error as _ue
e429 = _ue.HTTPError("u", 429, "rl", {"Retry-After": "7"}, None)
check("backoff honours Retry-After", pr._backoff(e429, 1) == 7)
check("backoff default grows", pr._backoff(ValueError(), 1) == 20 and pr._backoff(ValueError(), 2) == 60)


# per-repo config (.github/review.toml on the base ref)
w, n = run_main(R, [], toml="enabled = false\n")
check("config: enabled=false -> no model call, nothing posted", n == 0 and w == [])
w, n = run_main(R, [], toml='model = "a/b:free"\nextra_prompt = "check SQL"\ndiff_limit = 5000\n')
check("config: model used in header", "(a/b:free)" in w[0][2]["body"])
check("config: extra_prompt + diff_limit passed to model", SEEN["args"][4:] == ("check SQL", 5000))
check("config: read from base sha, not head", any("ref=base000" in c[1] for c in calls))
w, n = run_main(R, [])
check("config: missing file -> defaults", SEEN["args"][4:] == ("", pr.DIFF_LIMIT)
      and pr.DEFAULT_MODEL in w[0][2]["body"])
def dies(raw):
    try:
        pr.parse_config(raw)
    except SystemExit:
        return True
    return False
check("config: bad toml rejected", dies("model = "))
check("config: diff_limit out of range rejected", dies("diff_limit = 10"))
check("config: diff_limit bool rejected", dies("diff_limit = true"))
check("config: enabled non-bool rejected", dies('enabled = "no"'))
check("config: extra_prompt capped", len(pr.parse_config('extra_prompt = "' + "x" * 9000 + '"')["extra_prompt"]) == 4000)
_os.environ["REVIEW_MODEL"] = "claude-sonnet-4-6"
try:
    pr.main()
    check("config: paid model refused", False)
except SystemExit as e:
    check("config: paid model refused", e.code == 2)
_os.environ.pop("REVIEW_MODEL", None)
try:
    run_main(R, [], toml='model = "gpt-4o"\n')
    check("config: paid model in review.toml refused", False)
except SystemExit as e:
    check("config: paid model in review.toml refused", e.code == 2 and not any(c[0] == "POST" for c in calls))
def exits(**kw):
    try:
        run_main(R, [], **kw)
    except SystemExit as e:
        return e.code != 0 and not any(c[0] == "POST" for c in calls)
    return False
check("config: 403 -> clear exit", exits(toml=urllib.error.HTTPError("u", 403, "x", {}, None)))
check("config: 5xx retried then exit", exits(toml=urllib.error.HTTPError("u", 502, "x", {}, None))
      and sum("/contents/" in c[1] for c in calls) == 2)
check("config: >1MB empty content -> exit", exits(toml={"type": "file", "encoding": "none", "content": ""}))
check("config: directory -> exit", exits(toml=[{"name": "x"}]))
check("config: non-UTF8 -> exit", exits(toml=b"\xff\xfe model"))
check("config: oversize -> exit", exits(toml=b"#" * (pr.CONFIG_MAX + 1)))
check("config: no base sha -> exit", exits(base=None))
check("free: /free suffix not accepted", not pr._is_free("x/free"))
w, n = run_main(R, [], toml={"type": "file", "encoding": "base64", "size": 0, "content": ""})
check("config: empty file -> defaults", len(w) == 1)
import http.client as _hc2
check("config: network error retried then exit", exits(toml=_hc2.RemoteDisconnected("x"))
      and sum("/contents/" in c[1] for c in calls) == 2)
print("ALL PASS" if not FAIL else f"FAILED: {FAIL}")
sys.exit(1 if FAIL else 0)
