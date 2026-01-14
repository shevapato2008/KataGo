# Plan: Rectangular Region Constraint Implementation

## Phase 1: C++ Engine Implementation [checkpoint: 94962f8]
- [x] Task: Define `AnalysisBounds` data structure and coordinate validation logic in C++. 81f94f5
- [x] Task: Update the analysis query parser in `command/analysis.cpp` (or relevant file) to support the `regionBounds` field. d3f950b
- [x] Task: Write unit tests in C++ to verify that `AnalysisBounds` correctly identifies points inside/outside the rectangle. 81f94f5
- [x] Task: Implement move filtering in the search loop (e.g., `Search::getPlaySelectionValues` or node expansion) to respect the bounds. c2bdfb1
- [x] Task: Write integration tests for the C++ analysis engine to verify localized move prediction on a 19x19 board. c2bdfb1
- [x] Task: Conductor - User Manual Verification 'C++ Engine Implementation' (Protocol in workflow.md) c2bdfb1

## Phase 2: Python API Integration [checkpoint: 7fd4956]
- [x] Task: Update the `MoveRequest` Pydantic model in `python/realtime_api/main.py` to include the optional `region_bounds` field. 154ab91
- [x] Task: Modify `python/realtime_api/katago_wrapper.py` (or equivalent) to pass the bounds to the C++ engine query. 154ab91
- [x] Task: Write failing integration tests in Python that call `/analyze` with `region_bounds` and expect localized moves. 7fb5c23
- [x] Task: Implement the passing of bounds and verify that the API returns the correct localized results. 7fb5c23
- [x] Task: Conductor - User Manual Verification 'Python API Integration' (Protocol in workflow.md) af9237c

## Phase 3: Final Verification and Documentation
- [x] Task: Perform a full regression test suite to ensure no impact on standard 19x19 analysis. 2ac5d1d
- [x] Task: Update API documentation (if any) to reflect the new `region_bounds` parameter. bd26700
- [x] Task: Conductor - User Manual Verification 'Final Verification and Documentation' (Protocol in workflow.md) bd26700
