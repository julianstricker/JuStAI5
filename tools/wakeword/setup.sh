#!/usr/bin/env bash
# Prepare a work directory for training an openWakeWord model (CPU only, ~6 GB).
#
# Usage:  tools/wakeword/setup.sh /path/to/workdir
# Needs:  python3 (3.10+), curl, and the running JuStAI core container (justai5-core-1),
#         from which the feature models and the openWakeWord package are copied so that the
#         embeddings are identical to what the core computes at runtime.
set -euo pipefail

WORK="${1:?usage: setup.sh WORKDIR}"
CORE="${CORE_CONTAINER:-justai5-core-1}"
mkdir -p "$WORK"/{data,voices,models,clips}
cd "$WORK"

python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q torch --index-url https://download.pytorch.org/whl/cpu
./venv/bin/pip install -q piper-tts onnxruntime numpy scipy tqdm requests soundfile scikit-learn onnx

# Feature models and the openWakeWord package exactly as the core uses them.
for f in melspectrogram.onnx embedding_model.onnx; do
  docker cp "$CORE:/models/openwakeword/$f" models/
done
mkdir -p pkg
docker cp "$CORE:/app/.venv/lib/python3.12/site-packages/openwakeword" pkg/openwakeword

# Negative features (openWakeWord project, Hugging Face): validation recording (~185 MB) and
# three slices of the ACAV100M feature set (~2.3 GB of the 17 GB file, taken via HTTP ranges).
HF=https://huggingface.co/datasets/davidscripka/openwakeword_features/resolve/main
FEAT=openwakeword_features_ACAV100M_2000_hrs_16bit.npy
curl -fL -o data/validation_set_features.npy "$HF/validation_set_features.npy"
WINDOW_BYTES=$((16 * 96 * 2))   # float16 windows of 16 x 96
i=0
for start in 0 1800000 3600000; do
  from=$((128 + start * WINDOW_BYTES)); to=$((from + 250000 * WINDOW_BYTES - 1))
  curl -fL -r "$from-$to" -o "data/acav_$i.bin" "$HF/$FEAT"
  i=$((i + 1))
done

# Piper voices (Hugging Face, rhasspy/piper-voices): several speakers and languages.
PV=https://huggingface.co/rhasspy/piper-voices/resolve/main
for v in en/en_US/libritts_r/medium/en_US-libritts_r-medium en/en_GB/alba/medium/en_GB-alba-medium \
         en/en_US/lessac/medium/en_US-lessac-medium de/de_DE/thorsten/medium/de_DE-thorsten-medium \
         de/de_DE/kerstin/low/de_DE-kerstin-low de/de_DE/ramona/low/de_DE-ramona-low \
         de/de_DE/karlsson/low/de_DE-karlsson-low de/de_DE/eva_k/x_low/de_DE-eva_k-x_low \
         de/de_DE/thorsten_emotional/medium/de_DE-thorsten_emotional-medium \
         it/it_IT/paola/medium/it_IT-paola-medium; do
  n=$(basename "$v")
  curl -fL -o "voices/$n.onnx" "$PV/$v.onnx"
  curl -fL -o "voices/$n.onnx.json" "$PV/$v.onnx.json"
done
echo "ready: $WORK"
