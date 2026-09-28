# ARCHIFY PRODUCTION OPERATIONAL RUNBOOK

**System:** JESSYCA PC  
**Module:** Archify Integration & Capability Provider  
**Status:** Certified for Production (`ARCHIFY_MODE=ACTIVE`)  
**Authority:** JESSYCA Decision Engine (JDE)  
**Date:** September 2026  

---

## 1. Executive Summary

This document specifies the operational standards, configuration parameters, deployment guidelines, and emergency procedures for running **Archify** in production within JESSYCA PC.

Archify operates strictly as a **Capability Provider** subordinated to the **JESSYCA Decision Engine (JDE)**. It possesses no autonomous decision-making power, cannot bypass security verifiers or permission managers, and writes exclusively to a sandboxed directory.

---

## 2. Modes of Operation

Archify behavior is governed by the environment variable `ARCHIFY_MODE`.

| Mode | Allowed Invocations | JDE Governance | Filesystem Writes | Description |
| :--- | :--- | :--- | :--- | :--- |
| `ACTIVE` | Certified capabilities only | **Mandatory** | `data/archify/` | Full production mode. Generates verified interactive SVG/HTML artifacts. |
| `CONTROLLED` | Staging / testing | **Mandatory** | `data/archify/` | Safe validation mode. Validates IR and permissions, generates artifacts under controlled gating. |
| `SHADOW` | Dry-run / telemetry | **Mandatory** | None | Evaluates requests and simulates execution without writing disk artifacts. |
| `OFF` | None | N/A | None | Complete shutdown. All diagram requests fall back to Mermaid/Text. |

### Setting Production Mode

```powershell
# In production environment or .env:
ARCHIFY_MODE=ACTIVE
```

---

## 3. Certified Capability Inventory

Only capabilities that have passed formal verification are enabled in production. All other capabilities are hard-disabled in `core/jde/capabilities.py`.

| Capability Identifier | Status | Renderer | Default Direction | Max Nodes | Max Edges |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `diagram_generation.architecture` | **ENABLED** | `architecture` | `TB` | 200 | 400 |
| `diagram_generation.workflow` | **ENABLED** | `workflow` | `LR` | 200 | 400 |
| `diagram_generation.sequence` | **ENABLED** | `sequence` | `LR` | 200 | 400 |
| `diagram_generation.dataflow` | **ENABLED** | `dataflow` | `LR` | 200 | 400 |
| `diagram_generation.lifecycle` | **ENABLED** | `lifecycle` | `LR` | 200 | 400 |
| `diagram_generation.generic` | **DISABLED** | N/A | N/A | N/A | N/A |
| `diagram_generation.skill` | **DISABLED** | N/A | N/A | N/A | N/A |

Any attempt to invoke a disabled capability results in an immediate `JDE DENY` or `SkillExecutionResult.error("Capability ... is not enabled in capability registry")`.

---

## 4. Architectural Inviolability & Execution Flow

Archify must never be called directly by external clients. The execution pipeline is strictly linear and gated:

```text
[USER PROMPT]
      ↓
[JESSYCA CORE]
      ↓
[JDE (Decision Engine)] ── (Analyzes intent, verifies capability is certified)
      ↓
[RiskEngine] ───────────── (Evaluates blast radius, confirms read/write scope)
      ↓
[PermissionManager] ────── (Validates target path is strictly inside data/archify/)
      ↓
[IdempotencyGuard] ─────── (Checks SHA-256 fingerprint; returns CACHE_HIT if exists)
      ↓
[Archify Skill] ────────── (Validates spec, checks CapabilityRegistry status)
      ↓
[Archify Adapter] ──────── (Sanitizes HTML/JS, redacts secrets, confines paths)
      ↓
[Archify Engine] ───────── (Renders deterministic SVG & HTML document)
      ↓
[Artifact on Disk] ─────── (Written with secure file permissions)
      ↓
[ExecutionVerifier] ────── (6-point physical verification & SHA-256 integrity check)
      ↓
[JDE Receipt] ──────────── (Signed telemetry receipt with audit trail)
      ↓
[JESSYCA RESPONSE] ─────── (User receives verified artifact link)
```

---

## 5. Security & Isolation Constraints

### 5.1 Sandbox & Output Confinement
- Artifacts are confined strictly to `data/archify/` (or configured base directory).
- Target file paths are resolved using canonical normalization (`os.path.realpath` / `os.path.commonpath`).
- Any path containing `..`, `%2e%2e`, null bytes (`\x00`), absolute drive letters (`C:\`), or system directories (`Windows`, `System32`, `etc`) is immediately rejected with `ValueError("Path traversal attempt detected")`.

### 5.2 Secret Redaction
- All node labels, descriptions, and edge labels pass through regex redaction before IR compilation.
- The following patterns are automatically stripped and replaced with `[REDACTED]`:
  - Bearer tokens, JWT tokens (`ey...`)
  - OpenAI / Anthropic / GitHub API keys (`sk-...`, `ghp_...`, `gho_...`)
  - Passwords and connection strings (`postgres://`, `mysql://`, `mongodb://`)
  - PEM Private Keys (`-----BEGIN ... PRIVATE KEY-----`)
  - AWS Secret Access Keys (`aws_secret_access_key=...`)

### 5.3 Anti-XSS & Anti-Injection
- All node titles, labels, edge descriptions, and groups are HTML-escaped via `html.escape(quote=True)`.
- `<script>`, `onerror=`, `onload=`, `javascript:`, `<iframe>`, and SVG script tags are converted into harmless text literals.
- Embedded JSON script blocks escape `</` as `\u003c/` to prevent DOM script breakout.

---

## 6. Verification & Anti-False-Success Policy

Under no circumstances may Archify report `SUCCESS` without physical verification:

1. **Existence:** File must exist on physical disk (`os.path.isfile(path) == True`).
2. **File Size:** File size must be strictly greater than 0 bytes.
3. **Format:** File must be valid UTF-8 HTML containing both `<svg` and `</svg>`.
4. **Sanity Check:** File must be free of unescaped executable script tags.
5. **Identity Matching:** The receipt must match the requested `artifact_id`, `decision_id`, and `operation_id`.
6. **Checksum Integrity:** If post-generation tampering occurs or the file checksum differs from the rendered output, `ExecutionVerifier` rejects the artifact with `VERIFICATION_FAILED`.

---

## 7. Performance & Resource Benchmarks

Production telemetry established the following operational baselines (AMD Ryzen / Windows 11):

| Metric | Target | Observed Production Value |
| :--- | :--- | :--- |
| Cold Generation Latency | < 50 ms | **1.52 ms** |
| Cache-Hit Latency | < 5 ms | **0.408 ms** |
| Execution Verification Latency | < 5 ms | **0.312 ms** |
| False-Success Rate | **0.0%** | **0.0%** (0 / 33 test cases) |
| Memory Overhead per Diagram | < 5 MB | **< 120 KB** |
| GPU / VRAM Overhead | **0.0 MB** | **0.0 MB** (Pure CPU/DOM rendering) |
| High Concurrency (20 workers) | Zero corruption | **PASS** (Zero collisions/deadlocks) |

---

## 8. Rollback Procedures

If an anomaly, regression, or emergency occurs in production, operators must follow this zero-code rollback procedure.

### Instant Rollback to Controlled Mode
To freeze production generation while keeping tests and diagnostics accessible:
```powershell
# Set environment variable
$env:ARCHIFY_MODE="CONTROLLED"
# Or update production .env:
# ARCHIFY_MODE=CONTROLLED
```
**Effect:** Only gated staging workflows can generate diagrams; user requests fall back cleanly to Mermaid or structured text.

### Emergency Kill-Switch (Complete Shutdown)
To immediately disable all Archify execution:
```powershell
# Set environment variable
$env:ARCHIFY_MODE="OFF"
# Or update production .env:
# ARCHIFY_MODE=OFF
```
**Effect:** `archify_skill` returns an immediate bypass, routing all diagram generation to standard text or Mermaid without throwing runtime errors or leaving orphan processes.

---

## 9. Troubleshooting Guide

| Symptom | Probable Cause | Corrective Action |
| :--- | :--- | :--- |
| `SkillExecutionResult.error("Capability ... is not enabled")` | Attempt to use `generic` or `skill` diagram type. | Request one of the 5 certified types: `architecture`, `workflow`, `sequence`, `dataflow`, or `lifecycle`. |
| `ValueError("Path traversal attempt detected")` | Invalid output path supplied or path escape attempted. | Verify that output path remains inside `data/archify/`. Do not pass parent `..` segments. |
| `Verification failed: File checksum mismatch` | File was modified on disk between rendering and verification. | Check for background antivirus or filesystem sync processes altering file contents. |
| `DecisionEngine returns ALLOW but executor yields Mermaid` | `ARCHIFY_MODE=OFF` or Archify adapter encountered a rendering error. | Check `ARCHIFY_MODE` setting in environment and inspect exception logs. |
| `PermissionError: Target outside data/archify/` | Caller attempted writing outside canonical data dir. | Ensure `PermissionManager` and adapter use default output directory. |

---

## 10. Audit & Compliance Sign-Off

- **Lead Architecture Authority:** JESSYCA Decision Engine (JDE)
- **Phase 3 Certification Suite:** 294 / 294 Tests Passing (100%)
- **Zero VRAM Footprint:** Verified
- **Deterministic Receipts:** Enabled & Enforced
