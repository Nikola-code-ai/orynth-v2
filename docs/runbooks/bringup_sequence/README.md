# Bring-up sequence document

[`bringup_sequence.pdf`](bringup_sequence.pdf) is a 19-page picture-rich,
**risk-ordered** procedure for taking the repo from "fresh hardware on the
bench" to "five drones in the air." It is the *operational* counterpart to
[`../../architecture/end_to_end/end_to_end_setup.pdf`](../../architecture/end_to_end/end_to_end_setup.pdf)
(architecture) and [`../jetson_swarm_operations.md`](../jetson_swarm_operations.md)
(per-command reference).

Each stage A→G adds **one** new variable on top of the previous one and ends
with an explicit gate before the next stage begins. The document carries:

- the **risk ladder** (Stages A→G) on the cover and as the day-1 checklist;
- a UML deployment view for each stage;
- sequence diagrams for `make demo-up`, a single `/swarm/*` service call, and
  the swarm-wide takeoff fan-out;
- the **multicast vs unicast SPDP** picture that motivates the Cyclone DDS
  peer list, plus a verbatim copy of the per-drone XML;
- the preflight gate as an activity diagram;
- the watchdog as a state machine;
- a top-down field-setup diagram for the five-drone diamond;
- a failure-mode → stage-that-catches-it matrix.

Source: [`bringup_sequence.tex`](bringup_sequence.tex). All diagrams are
TikZ — no external image dependencies for the build itself.

## Rebuild

```sh
cd docs/runbooks/bringup_sequence
pdflatex -interaction=nonstopmode bringup_sequence.tex   # twice for TOC + xrefs
pdflatex -interaction=nonstopmode bringup_sequence.tex
```

Same TeX Live install as `end_to_end_setup.pdf` (`latex-extra` + `pictures`).

## Adding a real flight photo

One photo placeholder is wired in:

| Section | Placeholder file | Suggested shot |
|---|---|---|
| §7 Stage G | `images/diamond_inflight.jpg` | Five-drone diamond formation in the air, safety line and pilots visible in the foreground. |

To swap the placeholder:

1. Drop the JPG into `images/` with the filename above.
2. In `bringup_sequence.tex`, find the matching `\photoplaceholder{…}` call.
3. Replace the `\photoplaceholder{…}{…}{…}` line with:
   ```latex
   \includegraphics[width=14cm]{images/diamond_inflight.jpg}
   ```
4. Rebuild (two passes).
