# End-to-end architecture document

[`end_to_end_setup.pdf`](end_to_end_setup.pdf) is a 14-page picture-rich
reference: UML deployment & component views, sequence diagrams (parameter
load, arm/takeoff, leader-follow with watchdog), the swarm network topology,
three deployment modes side-by-side, the field setup map for the Phase 2.5b
demo, and the authority hierarchy + failsafe waterfall.

Source: [`end_to_end_setup.tex`](end_to_end_setup.tex). All diagrams are
TikZ — no external image dependencies for the build itself.

## Rebuild

```sh
cd docs/architecture/end_to_end
pdflatex -interaction=nonstopmode end_to_end_setup.tex   # twice for TOC + xrefs
pdflatex -interaction=nonstopmode end_to_end_setup.tex
```

Requires the TeX Live `latex-extra` and `pictures` packages (already installed
on the dev image).

## Adding real photos

Two photo placeholders are wired into the document:

| Section | Placeholder file | Suggested shot |
|---|---|---|
| §2 Hardware: single drone | `images/bench_single_drone.jpg` | Airframe on a stand, FC visible, RC RX in place, Jetson cabled to TELEM1, USB to a laptop with Mission Planner up. |
| §9 Field setup, Phase 2.5b | `images/field_phase_2_5b.jpg` | Field with drones in the diamond, safety pilots behind the safety line, ops laptop in the foreground. |

To swap a placeholder for the real photo:

1. Drop the JPG into `images/` with the filename above.
2. In `end_to_end_setup.tex`, find the matching `\photoplaceholder{…}` call.
3. Replace the `\photoplaceholder{…}{…}{…}` line with:
   ```latex
   \includegraphics[width=15cm]{images/bench_single_drone.jpg}
   ```
4. Rebuild (two passes).

The `\photoplaceholder` command is defined near the top of the source and can
be deleted entirely once both photos are in.
