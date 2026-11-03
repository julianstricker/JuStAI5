# Training your own wakeword

*[Deutsch](README.de.md) · English*

These scripts train an openWakeWord model (`<name>.onnx`) for a phrase of your choice, on a
normal CPU, without Google Colab. They produced the bundled **Hey Justy** model. The result
is an ordinary openWakeWord classifier (input `[1, 16, 96]`, output `[1, 1]`) that JuStAI5
accepts under *Rooms → edit endpoint → Wakeword → Upload own wakeword*.

How it works: [Piper](https://github.com/OHF-Voice/piper1-gpl) voices speak the phrase (many
speakers, English and German) and look-alike phrases (names that rhyme, other wakewords).
Clips are mixed with noise, reverb and other speech, turned into openWakeWord embeddings,
and a small classifier is trained against these plus real background audio from the
openWakeWord project. The classifier is exported to ONNX.

Requirements: Linux, Python 3.10+, `curl`, Docker with the JuStAI5 core container running
(`justai5-core-1`; the feature models and the openWakeWord package are copied from it so the
embeddings match what the core computes at runtime), about 6 GB disk, 8 CPU cores and
roughly 1.5 hours. No GPU needed.

## 1. Set up a work directory

```bash
tools/wakeword/setup.sh ~/wakeword-train
cd ~/wakeword-train
export WAKEWORD_WORK=$PWD
```

This creates a virtualenv and downloads about 3 GB (Python packages, ACAV100M and
validation features from the openWakeWord project on Hugging Face, Piper voices).

## 2. Choose your phrase

The phrase is defined by lists at the top of `generate_clips.py`:

| List | What it contains | Used for |
|---|---|---|
| `POSITIVE`, `POSITIVE_DE` | spellings of your phrase for English / German voices | the wakeword |
| `ADVERSARIAL` | similar-sounding phrases (`hey judy`, `hey dusty`, …) | must **not** trigger |
| `ADVERSARIAL2` (`_NAMES`) | many names with the same ending, with and without "hey" | must **not** trigger |
| `SENTENCES_EN`, `SENTENCES_DE` | everyday sentences | must **not** trigger |

Edit them for your phrase. If the voice pronounces it wrongly, spell it phonetically
("hey siri" → `hey seer ee`) and keep one entry per spelling you want recognised. When a
word triggers by mistake in daily use, add it to `ADVERSARIAL2` and train again.

## 3. Generate clips (about 45 minutes)

```bash
python=venv/bin/python
$python ../path/to/JuStAI5/tools/wakeword/generate_clips.py pos 6000
$python ../path/to/JuStAI5/tools/wakeword/generate_clips.py adv 2500
$python ../path/to/JuStAI5/tools/wakeword/generate_clips.py adv2 3500
$python ../path/to/JuStAI5/tools/wakeword/generate_clips.py neg 3500
```

(Warnings like "Missing phoneme from id map" are harmless.) Listen to a few clips first if
you are unsure about the pronunciation: `clips/pos.npy` holds the audio (16 kHz float
arrays), `clips/pos.json` the voice and text of each clip.

## 4. Train and export (about 1 hour; the first run embeds all clips)

```bash
MODEL_NAME=hey_justi $python ../path/to/JuStAI5/tools/wakeword/train.py
```

The script prints, every 750 steps, the recall on held-out synthetic examples and the
false activations per hour on a held-out part of the real background recording, and
keeps the best checkpoint. Result: `$WAKEWORD_WORK/hey_justi.onnx`. The file name becomes
the ID, so use only lower-case letters, digits and `_`.

Good values for the final line: `recall@0.8` of 0.8 or more and `ev/h@0.8` below 1.

## 5. Install and test

Upload the file in the interface (*Rooms → edit endpoint → Wakeword → Upload own
wakeword*), select it and set the threshold to about 0.8. The synthetic-voice numbers are
optimistic: test with your own voice, in your rooms, with background noise. If it misses
you, or triggers on other words, extend the lists in step 2 and train again.

To add the model to JuStAI5 itself, put it in `plugins/openwakeword/models/` and add its
phrase to `PHRASES` in `plugins/openwakeword/plugin.py`.

## Files

| File | Purpose |
|---|---|
| `setup.sh` | virtualenv, models, negative data, Piper voices |
| `generate_clips.py` | synthetic clips with Piper |
| `features.py` | augmentation (noise, reverb, babble) and embeddings (helpers) |
| `train.py` | classifier training, selection by false activations per hour, ONNX export |
