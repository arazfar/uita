"""Sourced applicability register. Conservative research envelopes are not FAA minima."""

from .contracts import AirportRulePack

VERSION = "sfo-august-research-2"
ATC = "https://www.faa.gov/air_traffic/publications/atpubs/atc_html/"
RULES = [
    {
        "id": "separation",
        "paragraph": "5-5-4; 4-5-1",
        "source": ATC + "chap5_section_5.html",
        "implementation": "verification.verify_motion",
        "test": "test_research_domain.py",
        "applicability": "Terminal surveillance and validated altitude required",
        "classification": "research_envelope",
        "assumption": "5 NM / 1000 ft conservative airborne envelope; no reduced separation authority",
    },
    {
        "id": "wake",
        "paragraph": "5-5-4; 3-9-6",
        "source": ATC + "chap5_section_5.html",
        "implementation": "verification.verify_motion",
        "test": "test_research_domain.py",
        "applicability": "Runway and same-stream arrival/departure interactions",
        "classification": "research_envelope",
        "assumption": "8 NM airborne in-trail envelope and 180 seconds dependent runway spacing; not a RECAT matrix",
    },
    {
        "id": "speed",
        "paragraph": "5-7-1",
        "source": ATC + "chap5_section_7.html",
        "implementation": "verification.verify_clearance",
        "test": "test_research_domain.py",
        "applicability": "IAS speed instruction, outside final restriction, not holding",
        "classification": "implemented_subset",
    },
    {
        "id": "vectoring",
        "paragraph": "5-6-1",
        "source": ATC + "chap5_section_6.html",
        "implementation": "verification.verify_clearance",
        "test": "test_research_domain.py",
        "applicability": "Requires independently loaded minimum-altitude coverage and jurisdiction",
        "classification": "unsupported_without_evidence",
    },
    {
        "id": "readback",
        "paragraph": "2-4-3",
        "source": ATC + "chap2_section_4.html",
        "implementation": "dynamics.pilot_responses",
        "test": "test_research_domain.py",
        "applicability": "All issued instructions; structured pilot acknowledgment",
        "classification": "implemented_subset",
    },
    {
        "id": "runway",
        "paragraph": "3-9; 3-10",
        "source": ATC + "chap3_section_10.html",
        "implementation": "verification.verify_clearance",
        "test": "test_research_domain.py",
        "applicability": "Both 28 runways share one dependent resource",
        "classification": "research_envelope",
    },
    {
        "id": "construction",
        "paragraph": "2026 construction configuration",
        "source": "https://www.flysfo.com/fil/node/15803",
        "implementation": "dynamics.initial_state",
        "test": "test_research_domain.py",
        "applicability": "August 2026 scenarios; announcement, not verified NOTAM history",
        "classification": "historical_configuration_assumption",
    },
]
PACK = AirportRulePack(
    id=VERSION,
    effective_from="2026-08-01",
    effective_until="2026-09-01",
    rules=RULES,
    limitations=[
        "Research simulation; passing checks does not establish FAA compliance.",
        "No local parallel-approach authorization, RECAT approval, or facility letters of agreement.",
        "MVA-dependent commands and unsupported procedure legs remain unresolved.",
        "Surface paths, pilot delays, aircraft performance and contingency routes are synthetic.",
        "The construction configuration is based on a published announcement; exact operational intervals require further evidence.",
    ],
)


def rule(identifier):
    return next(r for r in RULES if r["id"] == identifier)
