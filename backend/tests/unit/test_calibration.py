import numpy as np
from scipy.signal import chirp

from justai.audio.dsp import SR
from justai.audio.engine import onset_delay
from justai.audio.simulation import AcousticParams, AcousticRoom


def test_onset_delay_with_hardware_ducking() -> None:
    """Tapo-like device: only the first 200 ms of each sound leak into the mic."""
    room = AcousticRoom(AcousticParams(echo_delay_s=1.83, echo_gain=0.5, hardware_ducking=True,
                                       noise_dbfs=-72))
    t = np.arange(int(0.6 * SR)) / SR
    sweep = (chirp(t, 400, t[-1], 3200) * 0.5 * 32767).astype(np.int16)
    signal = np.concatenate([np.concatenate([sweep, np.zeros(int(0.9 * SR), np.int16)])
                             for _ in range(3)])
    t0 = 50.0
    room.speaker_emit(t0, signal)
    mic_t0 = t0 + 0.3
    mic = np.concatenate([room.mic(mic_t0 + i / SR, 320) for i in range(0, int(7 * SR), 320)])
    d = onset_delay(mic, mic_t0, signal, t0)
    assert d is not None and abs(d - 1.83) < 0.03


def test_onset_delay_needs_consistent_onsets() -> None:
    rng = np.random.default_rng(0)
    mic = (rng.standard_normal(5 * SR) * 50).astype(np.int16)
    ref = np.zeros(5 * SR, np.int16)
    assert onset_delay(mic, 0.0, ref, 0.0) is None
