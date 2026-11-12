"""Product analytics (plan item 11.3 / G17).

The best version of this needs no new tracking at all: **the server already sees
every duel it runs.** So the numbers are computed from the store, not collected
from the browser.

That single decision buys three things at once:

  * **No third party.** Nothing about your players leaves your server. For a game
    holding real money, sending player behaviour to an outside company is a trust
    and legal cost with no benefit — the same numbers are already here.
  * **No cookies, no client script.** Nothing to consent to, nothing to block,
    nothing to go stale in a cache. A player who blocks every tracker is still
    counted, because counting happens where the duel happens.
  * **No PII.** Nothing here stores an address, a name, or anything that
    identifies a person. The output is counts and distributions — "47 arrived,
    12 connected, 3 played" — never "who did what".

The five numbers, and the question each answers:

  funnel      — from 100 who arrive, how many connect, play, and stake? THIS is
                the one that says where you lose people.
  winLoss     — is the duel fair? A lopsided split means a broken rule, not bad
                luck.
  reactions   — what do human reaction times actually look like? If everyone
                clusters at the anti-bot floor, the floor is wrong.
  abandonment — how often does a duel start and never finish?
  perStake    — which tier do people actually play?
"""
from __future__ import annotations

from typing import Any

# A duel that starts and never reaches a terminal state is "abandoned" for these
# purposes. The store's own sweep eventually voids or settles them; until then
# they are the signal that something is stopping people mid-duel.
TERMINAL = ("settled", "void")

# --- unique-person tracking (audit L-07) --------------------------------------
# The request funnel was honest but blunt: a player who polled the queue 40 times
# counted as 40 "queued", so the step ratios measured polling, not people. The
# server knows the address on every authenticated step, so the fix needs no new
# tracking — just a set instead of a counter.
#
# The set is CAPPED. An unbounded set of addresses is a memory leak an attacker
# can drive by minting wallets, and `truncated: true` is the honest label for
# "this is a lower bound, not a count". 5,000 distinct addresses per step is far
# above any real cohort and far below anything that threatens the process.
_MAX_PEOPLE_PER_STEP = 5_000
_people: dict[str, set[str]] = {}
_people_truncated: set[str] = set()
# Per-process, like every other counter here: with N replicas each sees a slice
# of the traffic. Stated in the output rather than left for the reader to guess.
_people_since = 0.0


def note_person(step: str, address: str) -> None:
    """Record that `address` reached `step`. Never raises, never grows unbounded."""
    global _people_since
    try:
        key = (address or "").strip().lower()
        if not key:
            return
        if not _people_since:
            import timebase

            _people_since = timebase.now()
        bucket = _people.setdefault(step, set())
        if key in bucket:
            return
        if len(bucket) >= _MAX_PEOPLE_PER_STEP:
            _people_truncated.add(step)
            return
        bucket.add(key)
    except Exception:  # noqa: BLE001 — analytics must never break a request
        pass


def people_counts() -> dict[str, Any]:
    """Distinct addresses per step, with the truncation caveat made explicit."""
    return {
        "scope": "this process only — N replicas each report their own slice",
        "sinceResetAt": int(_people_since),
        "capPerStep": _MAX_PEOPLE_PER_STEP,
        "truncated": sorted(_people_truncated),
        "steps": {step: len(bucket) for step, bucket in sorted(_people.items())},
    }


def reset_people() -> None:
    global _people_since
    _people.clear()
    _people_truncated.clear()
    _people_since = 0.0


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = fraction * (len(sorted_values) - 1)
    low = int(index)
    high = min(low + 1, len(sorted_values) - 1)
    weight = index - low
    return sorted_values[low] * (1 - weight) + sorted_values[high] * weight


def _count_for(endpoint_counts: dict[str, int], path: str) -> int:
    """The request count for `path`, whatever method prefix the caller uses.

    Audit 2026-10-16 — a REAL bug, shipped and caught by an adversarial audit:
    `metrics.endpoint_counts()` keys by `"<METHOD> <path>"` (metrics.py), while
    this module looked up the bare path. Every lookup missed, so the funnel
    reported zeros for a server with traffic — and no test saw it, because the
    unit tests hand-built the un-prefixed dict that production never produces.

    Matching on the suffix rather than assuming a shape means the two modules
    cannot drift again, and a test now feeds this function the REAL metrics
    output.
    """
    total = 0
    for key, count in endpoint_counts.items():
        if key == path or key.endswith(f" {path}"):
            total += int(count)
    return total


def _funnel(endpoint_counts: dict[str, int]) -> dict[str, Any]:
    """Where people are lost, from the server's own request counts.

    Each step is the number of requests to the endpoint that represents it, so
    this is a request funnel rather than a person funnel — stated plainly because
    reading it as "unique people" would overstate every step.
    """
    arrived = _count_for(endpoint_counts, "/api/auth/nonce")
    connected = _count_for(endpoint_counts, "/api/auth/verify")
    queued = _count_for(endpoint_counts, "/api/queue")
    settled = _count_for(endpoint_counts, "/api/match/{match_id}/settle")

    def rate(part: int, whole: int) -> float | None:
        return round(part / whole, 4) if whole else None

    return {
        "arrived": arrived,
        "connected": connected,
        "queued": queued,
        "settled": settled,
        "connectRate": rate(connected, arrived),
        "playRate": rate(queued, connected),
        "stakeRate": rate(settled, queued),
        # The step with the worst rate is where the product is losing people.
        "worstStep": min(
            (
                ("connect", rate(connected, arrived)),
                ("play", rate(queued, connected)),
                ("stake", rate(settled, queued)),
            ),
            key=lambda pair: pair[1] if pair[1] is not None else 2.0,
        )[0],
        "note": "request counts, not unique people — a re-poll counts again",
    }


def _from_matches(matches: list[Any]) -> dict[str, Any]:
    """Win/loss, reactions, abandonment and per-stake, from finished duels."""
    settled = [m for m in matches if m.status == "settled"]
    finished = [m for m in matches if m.status in TERMINAL]
    started = [m for m in matches if len(m.players) > 1]

    wins: dict[str, int] = {}
    reactions: list[float] = []
    per_stake: dict[str, dict[str, int]] = {}

    for m in settled:
        key = f"{m.stake:g}"
        bucket = per_stake.setdefault(key, {"settled": 0, "winnerPaid": 0})
        bucket["settled"] += 1
        if m.winner:
            wins[m.winner.lower()] = wins.get(m.winner.lower(), 0) + 1
        for _addr, rounds in (m.rounds or {}).items():
            for r in rounds.values():
                if getattr(r, "result_ms", None):
                    reactions.append(float(r.result_ms))

    # A "top winner" is only reported as a count, never as an address: the point
    # is the distribution, and an address in an analytics payload is PII.
    top_win_count = max(wins.values()) if wins else 0
    reactions.sort()

    return {
        "winLoss": {
            "settled": len(settled),
            "distinctWinners": len(wins),
            # A duel always has exactly one winner, so a healthy distribution has
            # roughly as many winners as duels. Far fewer means a few players win
            # almost everything — worth looking at.
            "duelsPerWinner": round(len(settled) / len(wins), 2) if wins else None,
            "mostWinsByOnePlayer": top_win_count,
        },
        "reactions": {
            "samples": len(reactions),
            "p50Ms": round(_percentile(reactions, 0.50), 1),
            "p95Ms": round(_percentile(reactions, 0.95), 1),
            "minMs": round(reactions[0], 1) if reactions else 0.0,
            "maxMs": round(reactions[-1], 1) if reactions else 0.0,
        },
        "abandonment": {
            "started": len(started),
            "finished": len(finished),
            "rate": round(1 - (len(finished) / len(started)), 4) if started else None,
        },
        "perStake": per_stake,
    }


def snapshot(store: Any, endpoint_counts: dict[str, int]) -> dict[str, Any]:
    """The whole picture, from the server's own data. Never raises."""
    out: dict[str, Any] = {
        "privacy": {
            "thirdParty": False,
            "cookies": False,
            "clientTracking": False,
            "storesPii": False,
            "note": "computed from the server's own match records; nothing leaves this server",
            # Audit L-07, stated rather than implied: counting PEOPLE needs a
            # per-person key, and the key is a public wallet address. It lives in
            # a capped in-process set, is never written to disk and never leaves
            # the server — but a reader deserves to know it exists.
            "inMemoryKeys": "a capped set of wallet ids per step, this process only, never persisted",
        }
    }
    try:
        matches = list(store.recent_matches(limit=2000))
    except Exception as exc:  # noqa: BLE001
        out["available"] = False
        out["reason"] = type(exc).__name__
        # Audit L-07: the people counters live in this process, not in the
        # store, so a store outage is not a reason to blank them.
        out["people"] = people_counts()
        return out
    out["available"] = True
    out.update(_from_matches(matches))
    out["funnel"] = _funnel(endpoint_counts)
    # Audit L-07: the answer to "how many PEOPLE", next to the request funnel.
    out["people"] = people_counts()
    return out
