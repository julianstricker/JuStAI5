"""Generate synthetic speech clips with Piper (many voices / speakers).

Usage: generate_clips.py pos|adv|adv2|neg COUNT   (run inside the work directory, see README.md)
"""
import json
import os
import multiprocessing as mp
import random
import sys
from pathlib import Path

import numpy as np
from scipy.signal import resample_poly

ROOT = Path(os.environ.get("WAKEWORD_WORK", ".")).resolve()
OUT = ROOT / "clips"
SR = 16000

POSITIVE = ["hey justy", "hey justi", "hey, justy", "hey justy!", "hey dschasti", "hey jasty"]
POSITIVE_DE = ["hey justy", "hey justi", "hey, justi", "hey jasti"]
ADVERSARIAL = [
    "hey just", "hey justin", "hey judy", "hey dusty", "hey rusty", "hey christie", "hey jesse",
    "hey jersey", "hey siri", "hey google", "hey jarvis", "hey alexa", "hey busty", "hey justice",
    "just see", "hey you stay", "justy", "hey", "hey gusti", "hey kirsty", "hey misty", "hey lucky",
    "hey justus", "hey jessy", "hey chrissy", "hey thirsty", "hey trusty", "hey jetzt", "hey ist",
    "hey du", "hey kristin", "hey susi", "hey sushi", "hey mystery", "hey history",
]
_NAMES = [
    "mackie", "zacky", "jacky", "micky", "ricky", "nicky", "becky", "lucky", "packy", "tacky", "zucky",
    "mucki", "hacky", "jackie", "sacky", "sunny", "tommy", "timmy", "danny", "sandy", "randy", "andy",
    "mandy", "lenny", "kenny", "benny", "jimmy", "johnny", "bobby", "mikey", "zaki", "maxi", "moni",
    "susi", "mausi", "hasi", "wusti", "pusti", "gusti", "husti", "fusti", "casey", "katie", "lassie",
    "jessy", "dackel", "zack", "mack", "jack", "max", "mick", "nick", "rick", "zoey", "lucy", "lisa",
    "tilly", "billy", "willy", "molly", "polly", "holly", "ronny", "connie", "yacky", "jaggy", "mucky",
    "stucki", "rocky", "ducky", "sticky", "tricky", "picky", "quicky", "dusti", "justa", "justo",
]
ADVERSARIAL2 = [f"hey {n}" for n in _NAMES] * 2 + list(_NAMES) * 2 + [f"hey, {n}!" for n in _NAMES]

SENTENCES_EN = [
    "what time is it", "turn on the light in the kitchen", "play some music please",
    "the weather is nice today", "can you tell me a joke", "i will be back in a minute",
    "did you see the game last night", "please close the window", "how are you doing",
    "set a timer for ten minutes", "what is on my calendar tomorrow", "the dog is in the garden",
    "i think we should leave soon", "let us have dinner at eight", "who is at the door",
    "this is a very long sentence about nothing in particular", "good morning everyone",
    "thanks a lot for your help", "i do not know what to say", "it is getting late",
]
SENTENCES_DE = [
    "wie spät ist es", "mach bitte das licht in der küche an", "spiel etwas musik",
    "das wetter ist heute schön", "erzähl mir einen witz", "ich bin gleich wieder da",
    "hast du das spiel gestern gesehen", "bitte schließ das fenster", "wie geht es dir",
    "stell einen timer auf zehn minuten", "was steht morgen in meinem kalender",
    "der hund ist im garten", "ich glaube wir sollten bald gehen", "lass uns um acht essen",
    "wer ist an der tür", "guten morgen zusammen", "vielen dank für deine hilfe",
    "ich weiß nicht was ich sagen soll", "es wird langsam spät", "das ist ja wirklich interessant",
    "heute gibt es nudeln mit tomatensauce", "kannst du mir kurz helfen", "ich habe hunger",
    "wo sind meine schlüssel", "jetzt oder nie", "das hat er gut gemacht", "ach so ist das",
]


class LazyVoice:
    """Loads the ONNX voice on first use, single-threaded (one worker process per core)."""

    def __init__(self, path):
        self.path, self._voice = path, None

    def synthesize(self, *a, **kw):
        if self._voice is None:
            import onnxruntime as ort
            from piper import PiperVoice

            orig = ort.InferenceSession.__init__

            def patched(self_, path, sess_options=None, *args, **kwargs):
                sess_options = sess_options or ort.SessionOptions()
                sess_options.intra_op_num_threads = 1
                sess_options.inter_op_num_threads = 1
                orig(self_, path, sess_options, *args, **kwargs)

            ort.InferenceSession.__init__ = patched
            self._voice = PiperVoice.load(str(self.path))
            ort.InferenceSession.__init__ = orig
        return self._voice.synthesize(*a, **kw)


def load_voices():
    voices = []
    for f in sorted((ROOT / "voices").glob("*.onnx")):
        cfg = json.loads(Path(str(f) + ".json").read_text())
        lang = cfg["language"]["code"][:2]
        n_spk = cfg.get("num_speakers", 1)
        voices.append((f.stem, lang, n_spk, LazyVoice(f)))
    return voices


def synth(voice, n_spk, text, rng):
    from piper import SynthesisConfig

    cfg = SynthesisConfig(
        speaker_id=rng.randrange(n_spk) if n_spk > 1 else None,
        length_scale=rng.uniform(0.8, 1.35),
        noise_scale=rng.uniform(0.4, 1.0),
        noise_w_scale=rng.uniform(0.4, 1.0),
    )
    chunks = list(voice.synthesize(text, syn_config=cfg))
    audio = np.concatenate([np.frombuffer(c.audio_int16_bytes, dtype=np.int16) for c in chunks])
    sr = chunks[0].sample_rate
    x = audio.astype(np.float32) / 32768.0
    if sr != SR:
        g = np.gcd(sr, SR)
        x = resample_poly(x, SR // g, sr // g)
    # trim leading/trailing silence, keep a tiny margin
    idx = np.where(np.abs(x) > 0.01 * max(1e-6, np.abs(x).max()))[0]
    if len(idx) == 0:
        return None
    return x[max(0, idx[0] - 800): idx[-1] + 800].astype(np.float32)


def worker(args):
    wid, kind, count, seed = args
    rng = random.Random(seed)
    voices = load_voices()
    en = [v for v in voices if v[1] == "en"]
    de = [v for v in voices if v[1] == "de"]
    other = voices
    out = []
    for i in range(count):
        if kind == "pos":
            pool, phrases = (en, POSITIVE) if rng.random() < 0.55 else (de, POSITIVE_DE)
        elif kind == "adv":
            pool, phrases = (en if rng.random() < 0.6 else de), ADVERSARIAL
        elif kind == "adv2":
            pool, phrases = (en if rng.random() < 0.5 else de), ADVERSARIAL2
        else:
            if rng.random() < 0.5:
                pool, phrases = en, SENTENCES_EN
            else:
                pool, phrases = de, SENTENCES_DE
            if rng.random() < 0.1:
                pool = other
        name, lang, n_spk, voice = rng.choice(pool)
        text = rng.choice(phrases)
        try:
            x = synth(voice, n_spk, text, rng)
        except Exception as exc:  # a few odd speaker/phrase combos may fail
            print("skip", name, text, exc, file=sys.stderr)
            continue
        if x is not None:
            out.append((kind, name, text, x))
    return out


if __name__ == "__main__":
    kind, total = sys.argv[1], int(sys.argv[2])
    nproc = 7
    per = total // nproc + 1
    OUT.mkdir(exist_ok=True)
    with mp.get_context("spawn").Pool(nproc) as pool:
        results = pool.map(worker, [(w, kind, per, hash((kind, w)) & 0xFFFF) for w in range(nproc)])
    clips = [c for r in results for c in r][:total]
    lens = np.array([len(c[3]) for c in clips])
    np.save(OUT / f"{kind}.npy", np.array([c[3] for c in clips], dtype=object), allow_pickle=True)
    (OUT / f"{kind}.json").write_text(json.dumps([[c[1], c[2]] for c in clips]))
    print(kind, len(clips), "clips; mean length s:", lens.mean() / SR, "max:", lens.max() / SR)
