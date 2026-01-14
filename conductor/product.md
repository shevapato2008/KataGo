# Product Guide: KataGo Local Analysis

## Initial Concept
我们需要构建给定棋盘某个区域上的预测能力，可能katago目前已经支持这个功能，这点我并不确定。以一个具体的场景说明我刚才提到的需求。围棋里有很多局部问题，比如死活题、局部的腾挪、手筋等。以死活题为例，限定在棋盘某个区域（可能是角上也可能是边上）一方先行争取活棋或者杀掉对方。实际上就是划定某个长方形区域下围棋。也就是在局部预测最优解的问题。需要调研一下KataGo提供给远程访问的/analyze接口是否已经支持这个功能，如果不支持，需要开发这个功能。即客户端把死活棋相关的特定区域四角或者四边坐标传进来，/analyze api照常返回最优解。

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
