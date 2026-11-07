# Changes / Изменения

## 1.0.1 — 2026-11-07 · FontLab 8 / browser

- Fix: independently changed composite-letter sidebearings are measured from
  resolved outlines rather than inheriting only the base's delta. Components,
  reference density, selected scope and protections are retained.
- Reproduced in unmodified 1.0.0 on five real fonts; Karla is an outline-j control.
  112 automated tests, one skipped, no failures. No fresh FontLab 8 runtime was
  available; the same repair passed native Apply/read-back/Undo in FontLab 9.
- Existing UI, Fine-tuning, RU/EN/DE, author/support links and kerning defaults retained.
- Matching browser archive rebuilt. Updating this repository does not deploy the separate website.

RU: исправлены апроши составных букв; прежний интерфейс и настройки сохранены.

## FL9 0.1.0-beta.1 — 2026-11-07 · separate public beta

- Full Classic interface plus independent native/own engine selection and comparison.
- Preserving authored text-kern route, MM/VF export planning and supported original
  avar persistence through normal VFJ Save. Unsupported constructs are blocked.
- Same composite-letter fix. Six approved slides: interface, method and four local
  examples, not a general engine ranking. Yanone g/j example withdrawn.
- macOS FontLab 9.0.9806 coverage; Windows unverified. Preview does not shape
  authored text kern; exact avar coverage is one-axis Nunito, v1.

RU: отдельная бета гибрида FontLab 9; решение о применении остаётся за дизайнером.

## 1.0.0 — 2026-11-06

- Stable FontLab 8 edition; the spacing and kerning algorithms are unchanged from 0.5.4.
- Fix: the Apply guard compares pair values and identities, class members and class sides for the calculated masters, rather than just pair counts. Edits after Calculate invalidate the result. API record ordering does not trigger a false change.
- Seven new regression tests; 106 tests pass. The real Calculate/Apply scenario passes on Forum, Ledger and Kelly Slab in FontLab 9.0.9805.
- Script and browser builds rebuilt from the same versioned source; installation archives include license and checksums.
- No hybrid FontLab 9 engines in this release. Historical FontLab 8.4.3 macOS coverage; no fresh FontLab 8 or Windows runtime verification on the release machine.

Обычная версия для FontLab 8. Исправлена защита от устаревшего расчёта: ручные изменения пар и классов после расчёта блокируют применение. Алгоритмы апрошей и кернинга прежние. Сборки и документация обновлены. Гибрид для FontLab 9 развивается отдельно и в выпуск не включён.

Known limits remain: inspect generated spacing visually; joined scripts need manual handling; normal spacing can change monospaced widths; replacing `kern` feature text removes handwritten rules; a kerning-pair budget can omit weaker proposals. Save a source copy before applying.

Ограничения сохраняются: нужен оптический просмотр; соединяемые письменности требуют ручной работы; обычная расстановка может менять моноширинные метрики; снятие feature `kern` затрагивает ручной код; предел пар может отсечь часть предложений. Перед применением сохраните копию источника.
