# Uita
<!-- impeccable:product-schema 1 -->

## Platform
web

## Stack
User recommended FastAPI/Pydantic, PostgreSQL, OR-Tools CP-SAT, React/TypeScript/Vite, and required Three.js, Blender, Rapier, Crusoe/Nemotron. Implementation details delegated explicitly by the user. GPT-6 Astra develops the application. Local SQLite is an implementation assumption for credential-free startup; PostgreSQL deployment remains supported.

## Product Purpose
A dependable, reproducible simulation and research application for self-improving air traffic orchestration at SFO. Understand traffic, inject disruptions, inspect independently verified plans, run bounded program evolution, compare matched baselines, replay and export evidence.

## Users
Assumption: aviation simulation researchers and technical evaluators examining the proposed workflow. Operational controller deployment is excluded.

## Operating Context
Seeded SFO West Plan, arrivals on 28L/R, departures on 01L/R, simplified connecting surface network. All outputs remain in simulation. No FAA certification or operational clearance connection.

## Capabilities and Constraints
Server authoritative deterministic state; relational persistence; immutable snapshot/rule-bound plans and evidence. Hard constraints precede normalized operational/environmental/fairness objectives. Unfinished traffic counts. Independent verification passes, fails, or remains unresolved. Bounded declarative observation-policy evolution cannot change rules, evaluator, thresholds, permissions, or held-out cases. Offline fixture and live Crusoe modes are explicitly distinct; no substitution of providers. Candidate lineage persists and later proposals build on accepted versions.

## Brand Commitments
Precise aviation instrument. Large recognizable 3D SFO scene, Bay shoreline and correct runway orientation; dark navy, cyan, amber, readable typography; compact reservation timeline and evidence drawer rather than metric-card wall.

## Evidence on Hand
User's brief is the contract. Existing context/air-traffic-controller-role-overview.md is background, not an authoritative rule pack. Current primary FAA/SFO/NASA/Crusoe sources and effective dates are recorded in docs/research/SOURCES.md. Synthetic scenario data and proxy estimates are labeled. The user supplied a Crusoe credential for local verification; two bounded live calls completed, with estimated aggregate inference cost $0.00006250. Credentials remain outside source and client assets. The live candidate was rejected; no improvement is claimed.

## Accessibility & Inclusion
Keyboard access, reduced motion, readable table alternative to essential 3D information, responsive desktop/narrow layouts, clear offline/loading/stale/error/unresolved states.
