# Validation and limits · 1.0.1 / FL9 beta

The independently changed composite-letter spacing defect was reproduced in
the actual unmodified 1.0.0 calculation on five fonts with composite j:
Yanone Kaffeesatz, Alumni Sans, Merriweather, Lora and Comfortaa. Karla's
outline j is the control. [Machine-readable before/after evidence](composite-1.0.1.json).

The repair measures resolved composite-letter outlines without decomposing
the source or adding font-specific/pair-specific exceptions. Reference density,
selection and protections are retained. It is enabled in Classic 1.0.1 and
the FL9 hybrid. The legacy delta-inheritance route remains available to code
comparisons via `component_metrics=False`.

- Classic 1.0.1: 114 automated tests, one skipped, no failures.
- Hybrid working source: 225 tests, one skipped, no failures before packaging.
- Six real fonts × three inputs in FontLab 9: measured Apply/read-back/Undo,
  unchanged contours/reference density, protected j and complete source restoration.
- The unmodified legacy route matched v1.0.0 on 36 real-font configurations.
- Historical FL8 coverage: macOS 8.4.3. A fresh FL8 runtime was unavailable;
  this is not represented as a new FontLab 8 execution test. Windows is unverified.
- Hybrid MM/text `kern`, class-table writing and Undo were checked on Nunito;
  exact `avar` work is specifically one-axis Nunito, avar v1.
- The actual public 1.0.1 and FL9 beta bundles were loaded into FontLab 9 on
  an owned Nunito copy. Both produced identical spacing on three masters;
  each packaged bridge passed Apply and exact Undo, with no documents/windows
  left behind. [Bundle hashes and native protocol](native-release/native.json).

The six presentation slides show the UI, the method and **four** selected local
examples. Before means common input, not an ideal target. Three inputs are
original; one is deliberately perturbed. No kerning/substitutions are rendered.
The selection does not establish a general ranking or frequency of success.

The Yanone g/j slide was withdrawn. A wide leftover gap is not evidence of
good spacing. The excessive composite j field is repaired, but its descender
can still intersect g below the baseline, as in the unkerned original.
Default Autokerner and a checked native Neural proposal both left gj at zero.
The existing full-outline guard option produced +99 U and removed mask overlap
in this one case. That option was diagnosed, not made the default.

Always inspect words and pairs. Neither automatic output nor contour/mask
measurements establish optical quality or universal compatibility.
