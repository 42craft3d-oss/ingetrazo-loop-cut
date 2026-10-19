# Loop Cut for IngeTrazo

Standalone extension for creating cuts and selecting edge loops on closed meshes. Install [loop_cut.py](loop_cut.py).

Prepared version: v1.1.0 · License: MIT · Author: Daniel Wagner
[Español](README.md) · [Português](README.pt-BR.md)

![Loop Cut cover](media/loop-cut-cover.png)

## What's new in v1.1.0

- Hovering a cylinder side wall automatically detects its closed quad band and previews the transverse cut.
- **Alt+click** selects the green **Edge Loop**.
- **Shift+click** directly on an edge selects the dark-blue **Edge Ring** and adds it to the current selection.
- A normal click keeps the pink cut and one-step undo.

## Demo

Pink is the **Loop Cut** preview, green is the selected **Edge Loop**, and dark blue is the selected **Edge Ring**.

<img src="media/loop-selection-v1.1.0.png" alt="Loop Cut cylinder with a pink cut, green loop, and dark-blue edge ring" width="900">

## Install

1. Download [loop_cut.py](loop_cut.py).
2. In IngeTrazo choose **Extensions → Open add-ons folder**. On Windows it is usually %APPDATA%\IngeTrazo\plugins\.
3. Copy the file there — to update, replace the previous `loop_cut.py` — and restart IngeTrazo.

## Use

1. Activate **Corte em loop** from the menu or LoopTools toolbar.
2. Hover an edge or a quadrilateral side face.

   - No modifier: pink preview for the cut.
   - **Alt:** green preview for the Edge Loop.
   - **Shift:** when directly over an existing edge, dark-blue preview for the Edge Ring.

3. Click:

   - **Click:** create the cut.
   - **Alt+click:** select the green Edge Loop.
   - **Shift+click:** add the dark-blue Edge Ring to the selection.

**Ctrl+Z** undoes a cut. Selections do not change the mesh.

## Behavior and limits

Loop Cut follows opposite edges through a closed quadrilateral band. On a cylinder wall it evaluates the four edges of the face and uses the longest valid closed band, so the user does not need to hit a thin vertical edge.

Dark-blue ring selection uses a different traversal: it follows existing coplanar edges end to end until they close. It requires a real edge and a closed cycle; it does not turn an open curve into a loop.

For compatible mixed-face geometry, normal cutting retains the planar cross-section fallback. Open, holed, branched, or ambiguous paths are rejected before the mesh changes. The extension supports plugin APIs 1 and 2; IngeTrazo's 0.x API may change.

## License

MIT. See [LICENSE](LICENSE).
