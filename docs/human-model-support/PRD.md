# Product Requirement Document (PRD): Human-Like Model Support for Remote Engines

## 1. Overview
Currently, KaTrain supports "Human-Like" play styles (Ranked, Pro Era) only when using the local KataGo engine. This feature relies on a secondary "human model" loaded by the engine. When using a remote/HTTP backend, KaTrain assumes this capability is missing, disabling these strategies.

This project aims to extend support for Human-Like strategies to the HTTP engine backend, allowing users to play against calibrated ranked bots even when offloading compute to a server.

## 2. Problem Statement
*   **Limitation:** `KataGoHttpEngine` does not flag itself as having a human model (`has_human_model = False`).
*   **Consequence:** The `HumanStyleStrategy` in `ai.py` aborts immediately and falls back to `PolicyStrategy` when using an HTTP backend, even if the remote server actually has the human model loaded.
*   **User Impact:** Users with powerful remote servers cannot use KaTrain's teaching/ranked modes effectively.

## 3. Goals
1.  **Enable Human Strategies for HTTP:** Allow `HumanStyleStrategy` to function with `KataGoHttpEngine`.
2.  **Configuration:** Provide a mechanism to inform KaTrain that the remote server supports human models.
3.  **Data Flow:** Ensure user selections for Strategy (e.g., "Rank 5k") and Strength are correctly serialized and sent to the remote engine.

## 4. User Stories
*   **As a user**, I want to connect to my home server via HTTP and play a game against a "5 Kyu" bot, so I can save battery on my laptop while getting a calibrated game.
*   **As a developer**, I want the Web UI to correctly fetch and update AI settings so that the core logic sends the right parameters to the engine.

## 5. Technical Requirements

### 5.1 Server-Side (KataGo Context)
*   **Engine:** The remote KataGo instance **must** be started with the `-human-model` flag pointing to a valid `.bin.gz` human model.
*   **Protocol:** The server **should** expose its capabilities in the health check response (e.g., `{"has_human_model": true}`).
*   **API:** The server must accept `humanSLProfile` in the `overrideSettings` JSON field and pass it through to the engine.

### 5.2 Client-Side (KaTrain Core)
*   `KataGoHttpEngine` must attempt to detect `has_human_model` from the server's health check response.
*   Configuration (`engine/http_has_human_model`) will serve as a fallback or forced override.
*   `KataGoHttpEngine` must expose `has_human_model` status to the strategies.

### 5.3 Web UI / State Management
*   **Strategy Selection:** The UI needs to map user choices (e.g., "Pro", "Ranked") to the underlying `Player` object's `player_subtype`.
*   **Strength Settings:** The UI needs to update `config.json` entries (e.g., `ai/human/human_kyu_rank`).
*   **Synchronization:** These updates must trigger `game.update_state()` or similar to ensure the next move generation uses the new settings.

## 6. Constraints
*   We cannot automatically detect if the remote server has the model without a protocol update or a "probing" query (which might be complex). A manual config switch is the MVP approach.
*   Network latency might slightly delay "Human" moves compared to local play, but this is acceptable.
