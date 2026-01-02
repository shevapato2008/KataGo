# User’s Question

> I have already refactored my KataGo service into an HTTP-based service.
> This KataGo HTTP service can handle concurrent analysis requests from multiple remote or local clients.
> 
> On the same server, I also have KaTrain, which is a UI developed with Kivy, but it cannot be accessed via a web browser.
> I am currently developing a Web UI that reimplements (recreates) the Kivy UI, so that multiple remote clients can access the UI through a website and play or analyze games concurrently.
> 
> Please evaluate whether the work I am currently doing is on the right track.

---

# ChatGPT response: KataGo Web-Based Multi-Client System

## Architecture Evaluation and Design Assessment

### Document Type

Technical Architecture Assessment & Design Review

---

## 1. Background

KataGo is a high-performance Go engine traditionally consumed via local GUIs such as KaTrain, which is implemented using Kivy and designed primarily for single-user, desktop-based workflows.

In its original form:

* KataGo is driven via GTP or local IPC.
* GUIs such as KaTrain are tightly coupled to a single engine instance.
* Remote or concurrent multi-user access is not supported.

To enable **remote access, concurrent usage, and future scalability**, the system has been refactored into a service-oriented architecture centered around a **KataGo HTTP analysis service** and a **browser-based Web UI**.

---

## 2. Project Goal

The primary goals of the current work are:

1. Enable **multiple remote and local clients** to use KataGo concurrently.
2. Decouple the Go engine from any single UI implementation.
3. Provide a **Web-based UI** that reproduces the functional capabilities of the existing Kivy-based KaTrain UI.
4. Establish a foundation that can later migrate to **cloud-based GPU infrastructure** with minimal architectural changes.

---

## 3. Current System Overview

### 3.1 KataGo HTTP Analysis Service

* KataGo has been refactored into an **HTTP-based service**.
* Clients submit analysis requests via HTTP (and potentially WebSocket).
* The service supports **concurrent analysis requests** from multiple clients.
* Requests may originate from:

  * Local clients (e.g., KaTrain for validation).
  * Remote Web UI clients accessed via a browser.

### 3.2 Existing Desktop UI (KaTrain)

* KaTrain remains deployed locally on the same machine.
* It serves as:

  * A reference implementation.
  * A validation and regression-testing tool.
* KaTrain is **not exposed via the web** and remains desktop-only.

### 3.3 New Web UI (In Development)

* A browser-based UI is being developed.
* Its purpose is to **reimplement the functionality of the Kivy-based UI**, enabling:

  * Remote access.
  * Multi-client simultaneous usage.
* The Web UI communicates exclusively with the KataGo HTTP service.

---

## 4. Architecture Correctness Assessment

### 4.1 Overall Direction

**Assessment: Correct and well-aligned with long-term goals.**

The architectural direction is sound. In particular:

* Exposing KataGo through a service interface rather than binding it to a GUI is the **only viable approach** for multi-user access.
* Treating KaTrain as a local reference rather than the primary UI is a pragmatic and low-risk decision.
* Introducing a Web UI establishes a clean separation between:

  * Engine execution
  * Client presentation
  * Network access

This architecture naturally supports future scaling and cloud deployment.

---

## 5. Key Architectural Risks and Considerations

### 5.1 HTTP Concurrency vs Engine Concurrency

A critical distinction must be made:

> HTTP-level concurrency does **not** imply engine-level concurrency.

KataGo performance is constrained by:

* GPU compute capacity
* CPU threads
* Search configuration (visits, batch size, threads)

Without explicit controls, high request concurrency will:

* Increase latency for all users
* Saturate GPU/CPU resources
* Degrade system stability

**Recommendation**

* Introduce a bounded execution model at the engine layer.
* Use queues, concurrency limits, and backpressure.
* Treat the engine as a scarce shared resource.

---


### 5.2 Process Model: Single Engine vs Engine Pool

The system must clearly choose between:

* **A single KataGo process handling multiple sessions**, or
* **A pool of KataGo processes (worker pool)**

Each has trade-offs in:

* Isolation
* Fault tolerance
* Resource predictability
* Debuggability

This decision should be explicit and documented, as it directly impacts scalability and reliability.

---


### 5.3 Multi-Tenant Session Isolation

With multiple simultaneous users:

* Each game must be isolated.
* Board state, history, and analysis context must never leak across sessions.

**Recommendation**

* Introduce a `game_id` or `session_id`.
* Require it on all analysis-related requests.
* Maintain per-session state on the server side.

---


### 5.4 Cancellation, Timeouts, and Fault Handling

Browser-based clients frequently:

* Close tabs
* Refresh pages
* Lose network connectivity

Without proper cancellation handling, the system will accumulate:

* Orphaned analysis jobs
* Wasted compute
* Unbounded latency growth

**Recommendation**

* Enforce per-task timeouts.
* Support explicit cancellation by task or session ID.
* Automatically cancel engine work when client connections close.

---


### 5.5 Redundant Computation and Caching

Interactive analysis often triggers repeated requests for identical positions.

**Recommendation**

* Compute a deterministic hash based on:

  * Board state
  * Rules
  * Komi
  * Analysis parameters
* Cache results with a short TTL.
* Deduplicate in-flight identical requests.

This significantly improves responsiveness and reduces cost.

---


### 5.6 Web UI Design Considerations

Kivy-based desktop UIs rely heavily on:

* Mouse hover
* Right-click interactions
* Keyboard shortcuts
* Near-zero latency

Web UIs must handle:

* Touch input
* Higher latency
* Browser performance constraints

**Recommendation**

* Prioritize **functional equivalence**, not pixel-perfect replication.
* Focus first on:

  * Core board interaction
  * Analysis visualization
  * Engine configuration
* Advanced features can follow once stability is achieved.

---


### 5.7 Security and Abuse Prevention

Once exposed publicly, even a personal service is vulnerable to abuse.

**Minimum recommended safeguards**

* Token-based authentication.
* API rate limiting.
* Reverse proxy enforcement (no direct engine port exposure).
* Basic usage and latency logging.

---


## 6. Priority Roadmap

### P0 – Required for a Stable Multi-User Service

1. Session / game isolation
2. Engine-side concurrency limits
3. Timeouts and cancellation
4. Reverse proxy with same-origin API access

### P1 – Performance and Cost Optimization

5. Result caching and request deduplication
6. Streaming analysis results (WebSocket / SSE)

### P2 – Operability and Growth

7. Lightweight user or room model
8. Monitoring (latency, queue depth, GPU utilization)
9. Usage quotas or billing controls (if commercialized)

---


## 7. Recommended Reference Architecture

A robust and scalable architecture pattern:

1. **API Layer**

   * Authentication
   * Validation
   * Request intake

2. **Scheduler / Queue**

   * Backpressure
   * Fairness
   * Priority control

3. **Engine Worker Pool**

   * Fixed number of KataGo workers
   * Bound to available CPU/GPU resources

4. **Streaming Output Layer**

   * WebSocket or SSE for progressive analysis results

This design maps cleanly to both on-premise and cloud GPU deployments.

---


## 8. Open Design Questions

To further refine the system, the following questions are critical:

1. Is the engine model **single-process multi-session**, or **multi-process worker pool**?
2. Is client communication **HTTP polling** or **WebSocket/SSE streaming**?
3. What is the current dominant bottleneck: **CPU**, **GPU**, or neither?

The answers directly influence parameter tuning, scheduling strategy, and future cloud migration.

---


## 9. Summary

The current work is **architecturally correct and well-positioned** for long-term evolution.

The remaining challenges are not conceptual, but **engineering hardening tasks** required to transform a working prototype into a stable, scalable, multi-user service.

With proper session isolation, concurrency control, and resource management, this system can evolve naturally into a cloud-backed, production-grade KataGo service.

---
