# Third-party notices

## Fredoka (font)

The setup screen's wordmark is drawn from the Fredoka typeface (Bold). The font is used only at build time
(`cli/tools/make_wordmark.py`) to render the wordmark once into braille text (`cli/src/lflabs_memory_cli/banner_art.py`).
The font file does not ship in the package, and nothing renders a font at run time.

- Source: https://github.com/hafontia/Fredoka-One
- Copyright 2016 The Fredoka Project Authors (https://github.com/hafontia/Fredoka-One)
- License: SIL Open Font License, Version 1.1. The full text is in `cli/tools/fonts/OFL-Fredoka.txt`.

## Models

Search and sensitivity labels run on small models on your Mac. They are not in the wheel or the installer:
`dawnmere setup` downloads the first three on first run from this repo's
[models release](https://github.com/LF-Labs-Inc/dawnmere/releases/tag/models-2026-10-28), and the two for Chinese and
Japanese are downloaded the first time you save or ask something in Chinese or Japanese, from
[Models 2026-11-10](https://github.com/LF-Labs-Inc/dawnmere/releases/tag/models-2026-11-10). Each file's size and
sha256 is checked against the engine's `models.json` before it is used. `dawnmere doctor --licenses` lists them.

- **Embeddings:** [BAAI/bge-small-en-v1.5](https://huggingface.co/BAAI/bge-small-en-v1.5), converted to int8 ONNX.
  License: MIT.
- **Reranker:** [cross-encoder/ms-marco-MiniLM-L-6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L-6-v2),
  converted to int8 ONNX. License: Apache-2.0. It was trained on MS MARCO, whose terms allow non-commercial research
  use only.
- **Embeddings for Chinese and Japanese:** [intfloat/multilingual-e5-small](https://huggingface.co/intfloat/multilingual-e5-small)
  (revision 614241f), converted to int8 ONNX. License: MIT.
- **Reranker for Chinese and Japanese:**
  [cross-encoder/mmarco-mMiniLMv2-L12-H384-v1](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1)
  (revision 1427fd6), converted to int8 ONNX. License: Apache-2.0. It was trained on mMARCO, a translation of MS MARCO,
  whose terms allow non-commercial research use only.
- **Sensitivity labels:** friday-sense-v3-mmbert, LF Labs' fine-tune of
  [jhu-clsp/mmBERT-base](https://huggingface.co/jhu-clsp/mmBERT-base) (MIT), as int8 ONNX, with its runtime
  `friday_sense.py`, its tokenizer and its thresholds.
