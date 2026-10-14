"""Speech output outside of a conversation turn (announcements, greetings, plugins).

Everything is routed by the Output Router and played through the speaker channel,
so it is part of the echo reference of every endpoint in that room.
"""

from __future__ import annotations

from justai_sdk.events import new_id

from justai.ai.router import AIRouter
from justai.audio.dsp import SR, StreamResampler
from justai.audio.engine import AudioEngine
from justai.common.errors import Unavailable
from justai.output.router import OutputKind, OutputRequest, OutputRouter, RouteDecision


class SpeechService:
    def __init__(self, router: OutputRouter, audio: AudioEngine, ai: AIRouter) -> None:
        self.router = router
        self.audio = audio
        self.ai = ai

    def resolve(self, *, target_room_id: str | None, origin_endpoint_id: str | None = None,
                origin_room_id: str | None = None, explicit_cross_room: bool = False,
                permissions: frozenset[str] = frozenset(), system: bool = False) -> RouteDecision:
        return self.router.route(OutputRequest(
            OutputKind.AUDIO, origin_endpoint_id=origin_endpoint_id, origin_room_id=origin_room_id,
            target_room_id=target_room_id, explicit_cross_room=explicit_cross_room,
            permissions=permissions, admin=system))

    async def say(self, text: str, decision: RouteDecision, *, language: str | None = None,
                  wait: bool = True) -> None:
        speaker = self.audio.speakers.get(decision.device_id)
        if speaker is None:
            raise Unavailable("speaker has no audio channel")
        uid = new_id("say")
        done = speaker.begin(uid)
        resampler: StreamResampler | None = None
        async for chunk in self.ai.synthesize(text, language=language):
            if resampler is None or resampler.in_rate != chunk.sample_rate:
                resampler = StreamResampler(chunk.sample_rate, SR)
            pcm = resampler.process(chunk.pcm)
            if pcm.size:
                await speaker.enqueue(uid, pcm)
        speaker.end(uid)
        if wait:
            await done.wait()
