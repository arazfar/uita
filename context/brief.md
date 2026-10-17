# Up in the Air

## Hackathon product brief

**An autonomous AI air traffic controller that directs arriving aircraft, talks to pilots, and improves its own control policy through repeated simulation.**

### Product and demo

Build our own SFO arrival simulator and agent system with coding agents. Recreate **August 3–9, 2026, in SFO local time**, using real recorded arrival demand and available observed flight paths. The agent sequences aircraft, assigns headings, altitudes and speeds, manages holds and go-arounds, and coordinates landing clearance.

The demo follows arrivals through an approximately 80-nautical-mile SFO area to landing and simplified runway clearance. A radar display shows aircraft, intentions, clearances and conflicts. Visitors can listen to the controller and simulated pilots or speak as a pilot. An agent task tree and incident replay explain decisions; before/after results show whether the controller improves.

### Recommended data

Use **DataSF's arrival-operation roster plus SFO Museum's available flight paths**. I downloaded the August archive and extracted this starter week:

| Input | Source and verified extraction |
| --- | --- |
| Arrival demand and identity | [DataSF SFO Flight Operations](https://data.sf.gov/d/43zc-xw3x): **4,220 unique recorded runway-arrival operations**, including time, callsign, registration, aircraft type, origin and runway. |
| Observed aircraft paths | [SFO Museum August 2026 GeoParquet](https://static.sfomuseum.org/parquet/sfomuseum-data-flights-2026-08.parquet): **2,164 matched paths**, with **60,535 points** retained within 80 NM. |
| Missing-path handling | **2,056 roster arrivals lack a matched path in this extraction.** Generate explicitly labeled entry states and routes for these flights from patterns fitted on development days; optionally investigate [ADSB.lol](https://github.com/adsblol/globe_history_2026) for additional observations. |
| Weather and airport layout | Add [IEM historical METAR observations](https://mesonet.agron.iastate.edu/request/download.phtml) for KSFO and date-matched [FAA runway/aeronautical data](https://www.faa.gov/air_traffic/flight_info/aeronav/Aero_Data/NASR_Subscription/). These additions are not in the starter bundle. |

These are our extraction counts, not source-published coverage guarantees. The bundle contains raw historical observations. Before simulation, filter noisy position samples, normalize altitude/speed fields and reconstruct missing paths. DataSF operation times are retained and interpreted as SFO local time, rather than treated as precise touchdown times. The dataset README documents matching, timestamps and coverage.

### Key build components

| Component | What we build |
| --- | --- |
| **Data adapter and shared state** | Python/DuckDB ingestion cleans tracks and produces a frozen JSON scenario pack. A single simulation clock drives aircraft positions, velocity, current clearance, weather and runway state. The controller sees only information available at that moment. |
| **Custom simulator** | A deterministic TypeScript core runs in both the browser and a headless batch runner. Implement bounded turns, climbs, speeds, approach paths, holding, landing and runway occupancy. Historical data seeds traffic; the simulator computes new motion after instructions. |
| **ATC agent and pilot actors** | A supervisor delegates conflict analysis and sequencing, then issues structured commands through a small simulator API. Pilot actors execute accepted clearances and return readbacks. A fixed checker validates commands, predicted separation and runway occupancy. |
| **Voice interface** | Connect [GPT-Live](https://developers.openai.com/api/docs/guides/live) to the reasoning controller for full-duplex speech. Tie each spoken clearance and readback to an aircraft and action record. Run the week without audio; enable real-time voice for selected encounters. |
| **Recursive improvement** | An improvement agent reviews failures, delegates coding experiments, and revises controller prompts, memory or bounded policy code. Run candidates against fixed scenarios and retain measured improvements. Keep the simulator, checker, scoring and final test days outside its editable scope. |
| **Demo and evaluation UI** | React/TypeScript radar, aircraft inspector, radio transcript, agent task tree, incident replay and performance charts. Label observed inputs, inferred inputs and simulated outcomes. |

**Recommended stack:** TypeScript simulation and React UI; Python/DuckDB for offline data preparation; reasoning agents on the hackathon's available model infrastructure; GPT-Live as the voice interface. References below are optional reading, with no required simulator or agent-code dependency.

### Demonstrating improvement

Use August 3–7 for development and validation; freeze the winning controller before evaluating August 8–9. Fit gap-filling patterns on development days and freeze them too. Compare a scripted baseline, the initial agent and the improved agent with identical traffic and disturbance seeds.

Measure completed arrivals, remaining backlog, delay, holding, separation/runway violations, readback errors, decision latency and model cost. The result to demonstrate is improvement on unseen scenarios without weakening the checks. Use a short arrival rush for the live presentation and accelerated runs for week-level results.

**Simulation boundary:** this is a controllable reconstruction of historical arrivals. The source bundle does not include authentic ATC commands, radio transcripts or full pilot intent. Dialogue, missing approach segments and the consequences of new clearances are simulated.

### References — optional inspiration

- [ChatATC: University of Michigan/FAA collaboration](https://arxiv.org/abs/2402.14850) — conversational decision support and historical ground-delay-program retrieval, including SFO experiments.
- [Project Bluebird: NATS, Alan Turing Institute and Exeter](https://www.turing.ac.uk/science-innovation/defence-and-national-security/project-bluebird) · [BluebirdATC](https://github.com/project-bluebird/BluebirdATC) — digital twins and ATC-agent research.
- [TU Delft language-model ATC agents](https://arxiv.org/html/2409.09717v1) — agent roles and learning from prior experience.
- [ATC-Bench](https://github.com/kkoppenhaver/ATC-Bench) — simulated pilots, replay and controller evaluation.
- [BlueSky-Gym](https://github.com/TUDelft-CNS-ATM/bluesky-gym) — an example of an ATC simulation interface for agents.
- [DLR ATC-LLM-Interface](https://github.com/DLR-KI/ATC-LLM-Interface) — LLM-assisted selection of conflict resolutions.
- [Strategic-DCB-RL](https://github.com/Orbolato/Strategic-DCB-RL) — demand/capacity management research.
- [FAA SMART overview](https://www.faa.gov/newsroom/SMART_One-Pager.pdf) — the strategic airspace-planning context behind the original inspiration.
