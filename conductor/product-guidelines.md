# Product Guidelines: KataGo Local Analysis

## Architectural Principles
- **Safety and Isolation:** The core guiding principle is to ensure the new localized analysis feature is strictly additive. When no region constraint is provided, the engine's execution path and performance characteristics must remain identical to the original version.
- **Engine-Level Enforcement:** The rectangular constraint should be passed into the C++ search engine. This ensures that visits and playouts are focused exclusively on the specified area, avoiding wasted computation on moves outside the region.
- **Strict Containment:** The search must be restricted such that *all* moves in the variation (not just the root move) are contained within the user-specified bounds. This ensures the engine solves the local problem accurately within the given context.

## Implementation Guidelines
- **API Extension:** The `/analyze` endpoint in the Python API will be extended with an optional `region_bounds` field.
- **Default Behavior:** If `region_bounds` is omitted, the engine will perform standard full-board analysis.
- **Boundary Handling:** The analysis will still take place on the full board to preserve global context (liberties, connections to outside groups), but candidate moves will be filtered during the search expansion.
- **Regression Testing:** Automated tests must verify that standard 19x19 analysis results are unchanged when the new feature is inactive.

## Visual and Documentation Identity
- **API Documentation:** Clearly document the coordinate system used for the bounding box (e.g., (0,0) as top-left).
- **Transparency:** The API response should ideally acknowledge when a region constraint was applied to avoid confusion with full-board analysis results.
