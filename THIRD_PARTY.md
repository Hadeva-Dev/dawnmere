# Third-party notices

## Jost (font)

The setup screen's wordmark is drawn from the Jost typeface. The font is used only at build time
(`cli/tools/make_wordmark.py`) to render the wordmark once into braille text (`cli/src/lflabs_memory_cli/banner_art.py`).
The font file does not ship in the package, and nothing renders a font at run time.

- Source: https://github.com/google/fonts/tree/main/ofl/jost
- Copyright 2020 The Jost Project Authors (https://github.com/indestructible-type)
- License: SIL Open Font License, Version 1.1. The full text is in `cli/tools/fonts/OFL-Jost.txt`.

## Models

Search and sensitivity labels run on three small models on your Mac. They are not in the wheel or the installer:
`dawnmere setup` downloads them on first run from this repo's
[models release](https://github.com/Hadeva-Dev/dawnmere/releases/tag/models-2026-10-28), and checks each file's size
and sha256 against the engine's `models.json` before using it. `dawnmere doctor --licenses` lists them.

- **Embeddings:** [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), converted to int8 ONNX.
  License: MIT.
- **Reranker:** [cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2),
  converted to int8 ONNX. License: Apache-2.0.
- **Sensitivity labels:** friday-sense-v3-mmbert, LF Labs' fine-tune of
  [jhu-clsp/mmBERT-base](https://huggingface.co/jhu-clsp/mmBERT-base) (MIT), as int8 ONNX, with its runtime
  `friday_sense.py`, its tokenizer and its thresholds.
