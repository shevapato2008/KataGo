# Server-Side Requirements: Human-Like Model Support

## Overview
KaTrain is implementing support for "Human-Like" play styles (Ranked, Pro Era) using remote HTTP KataGo engines. To support this, the HTTP wrapper around KataGo must expose its capabilities and ensure specific parameters are passed through to the engine.

## 1. Startup & Configuration
The HTTP wrapper script must be able to accept and utilize the `-human-model` argument when launching the KataGo binary.

*   **Requirement:** The wrapper should detect if a human model is loaded.
*   **Flag:** Typically `-human-model <path_to_model.bin.gz>`.

## 2. API Endpoints

### 2.1 Health Check (Capability Handshake)
The health check endpoint (usually `GET /health` or `GET /`) is used by KaTrain to discover server capabilities.

*   **Request:** `GET /health` (or configured health path)
*   **Response Content-Type:** `application/json`
*   **Required Field:** `has_human_model` (boolean)
*   **Logic:**
    *   `true`: If the server was started with a valid human model.
    *   `false`: If only the primary model is loaded.

**Example Response:**
```json
{
  "status": "ok",
  "version": "1.0.0",
  "has_human_model": true
}
```

### 2.2 Analysis Request (Parameter Pass-through)
The analysis endpoint (usually `POST /analyze`) receives queries from KaTrain and forwards them to the KataGo engine via stdin.

*   **Requirement:** The wrapper **MUST NOT** sanitize or remove keys from the `overrideSettings` object in the JSON payload.
*   **Critical Key:** `humanSLProfile`
*   **Description:** This key instructs KataGo to use the secondary human model for the specific query.
*   **Values:** The wrapper should expect string values such as `"rank_10k"`, `"preaz_5k"`, `"proyear_1920"`, etc.

**Example Incoming Request:**
```json
{
  "id": "HTTP:123",
  "moves": [["B", "Q16"], ["W", "D4"]],
  "overrideSettings": {
    "humanSLProfile": "rank_5k"
  }
}
```
**Expected Behavior:** The wrapper forwards this JSON (or the relevant parts) to KataGo. If `humanSLProfile` is stripped, the feature will fail.

## 3. Backward Compatibility
*   If `has_human_model` is missing from the health check, KaTrain will assume `false` (unless manually overridden by the user).
*   Existing analysis requests without `overrideSettings` must continue to function as normal.
