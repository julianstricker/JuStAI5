import asyncio

from justai.audio.arbitration import ArbitrationContext, ArbitrationResult, WakeArbiter
from justai.audio.processor import WakeCandidate


def cand(ep: str, score: float = 0.8, snr: float = 20.0, t: float = 0.0,
         playback: bool = False) -> WakeCandidate:
    return WakeCandidate(ep, "hey_jarvis", score, t, -30.0, snr, 0.9, playback)


CTX = {
    "living": ArbitrationContext("house", 0, False),
    "kitchen": ArbitrationContext("house", 0, False),
    "garage": ArbitrationContext("garage", 0, False),
}


async def run(cands: list[WakeCandidate], ctx=None, delays=None) -> list[ArbitrationResult]:
    ctx = ctx or CTX
    results: list[ArbitrationResult] = []

    async def handler(r: ArbitrationResult) -> None:
        results.append(r)

    arb = WakeArbiter(lambda ep: ctx.get(ep), handler, window_s=0.1)
    for i, c in enumerate(cands):
        if delays:
            await asyncio.sleep(delays[i])
        arb.submit(c)
    await asyncio.sleep(0.25)
    return results


async def test_same_wakeword_in_two_rooms_starts_one_session() -> None:
    results = await run([cand("living", 0.7, snr=10), cand("kitchen", 0.9, snr=30)])
    assert len(results) == 1
    assert results[0].winner.endpoint_id == "kitchen"
    assert [c.endpoint_id for c in results[0].losers] == ["living"]


async def test_louder_signal_wins_over_slightly_higher_confidence() -> None:
    results = await run([cand("living", 0.82, snr=35), cand("kitchen", 0.85, snr=5)])
    assert results[0].winner.endpoint_id == "living"


async def test_independent_groups_are_not_arbitrated_together() -> None:
    results = await run([cand("living"), cand("garage")])
    assert sorted(r.winner.endpoint_id for r in results) == ["garage", "living"]


async def test_endpoint_with_active_session_wins() -> None:
    ctx = dict(CTX)
    ctx["living"] = ArbitrationContext("house", 0, True)
    results = await run([cand("living", 0.6, snr=5), cand("kitchen", 0.99, snr=40)], ctx)
    assert results[0].winner.endpoint_id == "living"


async def test_priority_breaks_ties() -> None:
    ctx = dict(CTX)
    ctx["kitchen"] = ArbitrationContext("house", 2, False)
    results = await run([cand("living"), cand("kitchen")], ctx)
    assert results[0].winner.endpoint_id == "kitchen"


async def test_late_candidate_after_window_is_separate_decision() -> None:
    results = await run([cand("living"), cand("kitchen")], delays=[0, 0.2])
    assert len(results) == 2
