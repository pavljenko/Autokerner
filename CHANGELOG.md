# Changes / Изменения

## 1.0.0 — 2026-11-06

- Stable FontLab 8 edition; the spacing and kerning algorithms are unchanged from 0.5.4.
- Fix: the Apply guard compares pair values and identities, class members and class sides for the calculated masters, rather than just pair counts. Edits after Calculate invalidate the result. API record ordering does not trigger a false change.
- Seven new regression tests; 106 tests pass. The real Calculate/Apply scenario passes on Forum, Ledger and Kelly Slab in FontLab 9.0.9805.
- Script and browser builds rebuilt from the same versioned source; installation archives include license and checksums.
- No hybrid FontLab 9 engines in this release. Historical FontLab 8.4.3 macOS coverage; no fresh FontLab 8 or Windows runtime verification on the release machine.

Обычная версия для FontLab 8. Исправлена защита от устаревшего расчёта: ручные изменения пар и классов после расчёта блокируют применение. Алгоритмы апрошей и кернинга прежние. Сборки и документация обновлены. Гибрид для FontLab 9 развивается отдельно и в выпуск не включён.

Known limits remain: inspect generated spacing visually; joined scripts need manual handling; normal spacing can change monospaced widths; replacing `kern` feature text removes handwritten rules; a kerning-pair budget can omit weaker proposals. Save a source copy before applying.

Ограничения сохраняются: нужен оптический просмотр; соединяемые письменности требуют ручной работы; обычная расстановка может менять моноширинные метрики; снятие feature `kern` затрагивает ручной код; предел пар может отсечь часть предложений. Перед применением сохраните копию источника.
