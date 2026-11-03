# Eigenes Wakeword trainieren

*Deutsch · [English](README.md)*

Diese Skripte trainieren ein openWakeWord-Modell (`<name>.onnx`) für eine beliebige Phrase,
auf einer normalen CPU und ohne Google Colab. Damit wurde das mitgelieferte Modell
**Hey Justy** erzeugt. Das Ergebnis ist ein gewöhnlicher openWakeWord-Klassifikator (Eingang
`[1, 16, 96]`, Ausgang `[1, 1]`), den JuStAI5 unter *Räume → Endpoint bearbeiten → Wakeword
→ Eigenes Wakeword hochladen* annimmt.

So funktioniert es: [Piper](https://github.com/OHF-Voice/piper1-gpl)-Stimmen sprechen die
Phrase (viele Sprecher, Englisch und Deutsch) sowie ähnlich klingende Phrasen (reimende
Namen, andere Wakewords). Die Clips werden mit Rauschen, Hall und anderer Sprache gemischt,
in openWakeWord-Embeddings umgerechnet, und ein kleiner Klassifikator wird gegen diese und
echte Hintergrundaufnahmen des openWakeWord-Projekts trainiert und als ONNX exportiert.

Voraussetzungen: Linux, Python 3.10+, `curl`, Docker mit laufendem JuStAI5-Core-Container
(`justai5-core-1`; Feature-Modelle und openWakeWord-Paket werden von dort kopiert, damit die
Embeddings denen im Betrieb entsprechen), etwa 6 GB Platz, 8 CPU-Kerne und rund 1,5
Stunden. Keine GPU nötig.

## 1. Arbeitsverzeichnis einrichten

```bash
tools/wakeword/setup.sh ~/wakeword-train
cd ~/wakeword-train
export WAKEWORD_WORK=$PWD
```

Das legt eine virtuelle Umgebung an und lädt etwa 3 GB (Python-Pakete, ACAV100M- und
Validierungs-Features des openWakeWord-Projekts von Hugging Face, Piper-Stimmen).

## 2. Phrase festlegen

Die Phrase steht in den Listen am Anfang von `generate_clips.py`:

| Liste | Inhalt | Zweck |
|---|---|---|
| `POSITIVE`, `POSITIVE_DE` | Schreibweisen deiner Phrase für englische / deutsche Stimmen | das Wakeword |
| `ADVERSARIAL` | ähnlich klingende Phrasen (`hey judy`, `hey dusty`, …) | soll **nicht** auslösen |
| `ADVERSARIAL2` (`_NAMES`) | viele Namen mit gleicher Endung, mit und ohne „hey“ | soll **nicht** auslösen |
| `SENTENCES_EN`, `SENTENCES_DE` | Alltagssätze | soll **nicht** auslösen |

Passe sie an deine Phrase an. Wird sie falsch ausgesprochen, schreibe sie lautmalerisch
(„hey siri“ → `hey seer ee`) und nimm je erkannter Schreibweise einen Eintrag. Löst im
Alltag ein anderes Wort fälschlich aus, trage es in `ADVERSARIAL2` ein und trainiere neu.

## 3. Clips erzeugen (etwa 45 Minuten)

```bash
python=venv/bin/python
$python ../pfad/zu/JuStAI5/tools/wakeword/generate_clips.py pos 6000
$python ../pfad/zu/JuStAI5/tools/wakeword/generate_clips.py adv 2500
$python ../pfad/zu/JuStAI5/tools/wakeword/generate_clips.py adv2 3500
$python ../pfad/zu/JuStAI5/tools/wakeword/generate_clips.py neg 3500
```

(Warnungen wie „Missing phoneme from id map“ sind harmlos.) Wenn du bei der Aussprache
unsicher bist, hör vorher einige Clips an: `clips/pos.npy` enthält das Audio (16 kHz,
Float-Arrays), `clips/pos.json` Stimme und Text je Clip.

## 4. Trainieren und exportieren (etwa 1 Stunde, der erste Lauf berechnet alle Embeddings)

```bash
MODEL_NAME=hey_justi $python ../pfad/zu/JuStAI5/tools/wakeword/train.py
```

Alle 750 Schritte zeigt das Skript die Erkennungsrate auf zurückgehaltenen synthetischen
Beispielen und die Fehlauslösungen pro Stunde auf einem zurückgehaltenen Teil der echten
Hintergrundaufnahme und behält den besten Zwischenstand. Ergebnis:
`$WAKEWORD_WORK/hey_justi.onnx`. Der Dateiname wird zur ID, also nur Kleinbuchstaben,
Ziffern und `_` verwenden.

Gute Werte in der letzten Zeile: `recall@0.8` ab 0,8 und `ev/h@0.8` unter 1.

## 5. Installieren und testen

Datei in der Oberfläche hochladen (*Räume → Endpoint bearbeiten → Wakeword → Eigenes
Wakeword hochladen*), auswählen und die Schwelle auf etwa 0,8 stellen. Die Zahlen mit
synthetischen Stimmen sind optimistisch: Teste mit deiner eigenen Stimme, in deinen Räumen
und mit Hintergrundgeräuschen. Verpasst es dich oder löst es bei anderen Wörtern aus,
ergänze die Listen aus Schritt 2 und trainiere neu.

Um das Modell fest in JuStAI5 aufzunehmen, lege es in `plugins/openwakeword/models/` ab und
trage die Phrase in `PHRASES` in `plugins/openwakeword/plugin.py` ein.

## Dateien

| Datei | Zweck |
|---|---|
| `setup.sh` | virtuelle Umgebung, Modelle, Negativdaten, Piper-Stimmen |
| `generate_clips.py` | synthetische Clips mit Piper |
| `features.py` | Augmentierung (Rauschen, Hall, Stimmengewirr) und Embeddings (Hilfsfunktionen) |
| `train.py` | Training, Auswahl nach Fehlauslösungen pro Stunde, ONNX-Export |
