"""Voice comparison with the real speaker model: wake phrase vs. conversation speech."""

from __future__ import annotations

import numpy as np
import pytest

from justai.audio.dsp import resample
from justai.audio.speaker import SpeakerEmbedder, similarity
from justai.conversation.manager import OTHER_SPEAKER_SIMILARITY

from .conftest import models_dir, speak

pytestmark = pytest.mark.models


@pytest.fixture(scope="module")
def embedder() -> SpeakerEmbedder:
    path = models_dir() / "speaker" / "wespeaker_en_voxceleb_resnet34.onnx"
    if not path.exists():
        pytest.skip("speaker model not available")
    return SpeakerEmbedder(path)


def camera(pcm):  # type: ignore[no-untyped-def]
    """8 kHz camera microphone bandwidth."""
    return resample(resample(pcm, 16000, 8000), 8000, 16000)


def wake_window(pcm):  # type: ignore[no-untyped-def]
    """Like the processor: the last 1.6 s around the detection, with low room noise."""
    rng = np.random.default_rng(0)
    out = (rng.standard_normal(int(1.6 * 16000)) * 30).astype(np.int16)
    n = min(pcm.size, out.size)
    out[:n] = np.clip(out[:n].astype(np.int32) + pcm[:n], -32768, 32767)
    return out


@pytest.mark.parametrize(("voice", "other"), [("de_DE-thorsten-medium", "en_US-lessac-medium"),
                                         ("en_US-lessac-medium", "it_IT-paola-medium")])
def test_wake_phrase_matches_own_conversation_but_not_other_voice(embedder, voice, other) -> None:  # type: ignore[no-untyped-def]
    conversation = embedder.embed(camera(speak("Wie wird das Wetter morgen? Und wann fährt der Zug?", voice)))
    same = embedder.embed(wake_window(camera(speak("Hey Jarvis!", voice))))
    different = embedder.embed(wake_window(camera(speak("Hey Jarvis!", other))))
    assert conversation is not None and same is not None and different is not None
    print(f"{voice}: same {similarity(same, conversation):.2f}, other {similarity(different, conversation):.2f}")
    assert similarity(same, conversation) >= OTHER_SPEAKER_SIMILARITY + 0.1
    assert similarity(different, conversation) < OTHER_SPEAKER_SIMILARITY
