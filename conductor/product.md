# Product Guide: KataGo Local Analysis

## Overview
KataGo Local Analysis provides the capability to perform localized search and move prediction within a user-specified rectangular region. This allows for focused analysis of local Go problems such as tsumego, tesuji, and life-and-death situations, while still accounting for the global board state.

## Project Goal
Enable KataGo to perform localized analysis and move prediction within a user-specified rectangular region of the Go board, treating it as a local problem (tsumego/tesuji) via the existing real-time API.

## Core Features
- **Rectangular Region Constraint:**  Allow users to specify a bounding box (x1, y1, x2, y2) in the `/analyze` API request.
- **Localized Search:**  Restrict the engine's search and move generation to the specified region.
- **API Integration:**  Seamlessly integrate with the existing `MoveRequest` and `MoveResponse` structures in the Python real-time API.
- **Search Optimization:**  Ensure the engine effectively focuses its computational resources (visits/playouts) on the local problem.

## User Experience
1.  **Client:** The user (or client software) sends a POST request to `/analyze`.
2.  **Request:** The JSON body includes standard board state (moves, rules) AND a new optional `region_bounds` field (e.g., `{"x1": 0, "y1": 0, "x2": 6, "y2": 6}`).
3.  **Processing:** KataGo receives the request. The prediction engine respects the bounds, only considering candidate moves within the rectangle.
4.  **Response:** The API returns the standard analysis result (best move, win rate, ownership, etc.), but the best move and principal variation (PV) are guaranteed to be within the specified region.

## Success Metrics
-   **Functional Correctness:** The engine *never* returns a move outside the specified rectangle when `region_bounds` is provided.
-   **Performance:** The analysis should be at least as fast, if not faster, than full-board analysis for the same number of visits (due to reduced branching factor).
-   **Usability:** The new parameter is easy to use and well-documented in the API schema.
