# Third-party notices

## Jost (font)

The setup screen's wordmark is drawn from the Jost typeface. The font is used only at build time
(`cli/tools/make_wordmark.py`) to render the wordmark once into braille text (`cli/src/lflabs_memory_cli/banner_art.py`).
The font file does not ship in the package, and nothing renders a font at run time.

- Source: https://github.com/google/fonts/tree/main/ofl/jost
- Copyright 2020 The Jost Project Authors (https://github.com/indestructible-type)
- License: SIL Open Font License, Version 1.1. The full text is in `cli/tools/fonts/OFL-Jost.txt`.
