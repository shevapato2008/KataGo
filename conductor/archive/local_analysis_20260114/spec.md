# Spec: Rectangular Region Constraint for Local Analysis

## Overview
This track implements the ability to restrict KataGo's search and move prediction to a specific rectangular region of the board. This is useful for solving local Go problems (tsumego, tesuji) while maintaining the global context of the full board.

## Coordinate System
- The bounding box is defined by two points: `(x1, y1)` and `(x2, y2)`.
- `(0, 0)` is the top-left corner of the board.
- For a standard 19x19 board, coordinates range from 0 to 18.
- The region is inclusive: a point `(x, y)` is within the region if `x1 <= x <= x2` and `y1 <= y <= y2`.

## API Changes (Python)
The `/analyze` endpoint in the real-time API will be updated to accept an optional `region_bounds` object in the JSON request body.

**Request Schema Update (`MoveRequest`):**
```json
{
  "id": "...",
  "moves": [...],
  "region_bounds": {
    "x1": 0,
    "y1": 0,
    "x2": 6,
    "y2": 6
  },
  ...
}
```

**Internal Handling:**
The Python API will pass these bounds to the C++ engine as part of the analysis query.

## Engine Changes (C++)
The KataGo analysis engine (and GTP extension) must be modified to respect the bounds.

1.  **GTP/Analysis Config:** Add support for parsing `regionBounds` in the analysis query JSON.
2.  **Search Restriction:**
    - In `Search.cpp` or equivalent, modify the move selection logic (e.g., in `getPlaySelectionValues` or during node expansion).
    - Ensure that *any* move considered during the search tree expansion is checked against the `regionBounds`.
    - If a move is outside the bounds, it should be treated as illegal/ignored for the purpose of the current search.
    - **Note:** The PASS move should generally still be allowed as an exit condition for the search, unless specified otherwise.

## Implementation approach: "Strict Containment"
As defined in the Product Guidelines, *all* moves in the search variations must be within the specified region. This ensures that the engine focuses entirely on solving the local problem and does not "escape" to other parts of the board.

## Regression Testing
- Verify that when `region_bounds` is not provided, the engine behaves identically to the baseline.
- Verify that when `region_bounds` is provided, the best move and all PV moves are strictly within the rectangle.
- Verify that boundary effects (liberties, connections) are correctly handled by keeping the full board context.
