# Autokerner 9 Hybrid 0.1.0 beta

Copy `Autokerner9.py` to FontLab 9's Scripts folder, then Refresh Scripts.
macOS: `~/Library/Application Support/FontLab/FontLab 9/Scripts`.
Windows: `%APPDATA%\FontLab\FontLab 9\Scripts` (unverified).

Choose spacing and kerning engines independently. To try the illustrated mix,
select Autokerner spacing and FL Neural kerning. Calculate/Compare, inspect,
then apply selected changes. Save a source copy first. Preferences are separate
from Classic. The full Classic interface and RU/EN/DE are retained.

Authored text kern requires Add to it. With multiple masters, Apply writes
spacing and prepares a kerning export plan; it preserves the source kern.
Preview does not shape text kern. For compatible TT variable export, import
`resources/Autokerner9-compatible-TT.fl_profile` into FontLab export profiles.
Exact avar preservation is verified for one-axis Nunito/v1; not every VF is covered.
Revert restores spacing/discards the plan, but keeps already exported files.

[Full manual and limitations](https://github.com/pavljenko/Autokerner/blob/main/docs/fontlab9.md)
· [Slides](https://github.com/pavljenko/Autokerner/tree/main/docs/images/fontlab9).
Public beta, macOS FontLab 9.0.9806 tested. The designer makes the final decision.

Sasha Pavljenko, MIT (LICENSE). Bundled fontTools: FONTTOOLS-LICENSE.txt.
[Support](https://pavljenko.ru/product/autokerner?lang=en) · pavljenko@ya.ru.
