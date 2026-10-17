"""Versioned conservative envelope, never authorizes independent parallel operations."""
RULE_VERSION = 'sfo-research-envelope-1.0'
RUNWAYS = [
    {'id':'28L','start':[.75,-.28],'end':[-.919,.570],'length_ft':11381},
    {'id':'28R','start':[.806,-.170],'end':[-.935,.717],'length_ft':11870},
    {'id':'01L','start':[-.65,-.75],'end':[-.078,.372],'length_ft':7650},
    {'id':'01R','start':[-.540,-.806],'end':[.106,.462],'length_ft':8650},
]
SOURCES = [
 {'id':'faa-7110','title':'FAA Order JO 7110.65BB — Change 3','url':'https://www.faa.gov/documentLibrary/media/Order/7110.65BB_Chg_3_dtd_7-9-26_FINAL.pdf','effective':'2026-07-09','scope':'Reference only. Research rules below are deliberately conservative approximations.'},
 {'id':'sfo-west','title':'SFO — West Plan runway constraints','url':'https://www.flysfo.com/about/airport-operations/policies-regulations/runway-constraints','effective':'accessed 2026-10-17','scope':'West Plan arrivals 28L/R, departures 01L/R; 750ft parallel pairs and intersecting dependencies.'},
 {'id':'faa-diagram','title':'FAA SFO airport diagram — cycle 2610','url':'https://aeronav.faa.gov/d-tpp/2610/00375AD.PDF','effective':'2026-10-01 to 2026-10-29','scope':'Lengths and magnetic bearings transcribed. Local coordinates are approximate; 297/027 true bearings are a research rotation.'},
 {'id':'faa-notice-805','title':'FAA N JO 7110.805 — Approaches to multiple runways','url':'https://www.faa.gov/documentLibrary/media/Notice/2026-02-24_Notice_7110.805_Apchs_to_Multiple_Runways_FINAL_Updated.pdf','effective':'2026-06-19 to 2026-12-24','scope':'Context only; visual-separation procedure is not implemented or authorized.'},
]
LIMITATIONS = [
 'Research simulation only. Not operational ATC, a clearance system, or FAA certification.',
 'Local NM frame centered near SFO; approximate geometry, altitude MSL feet. Routes are hypothetical, not published procedures.',
 'All runways share one conservative conflict resource. No independent parallel arrival authorization.',
 'Terminal airborne check: 3 NM or 1,000 ft above 1,000 ft MSL; the near-runway region uses a serialized protected occupancy interval. This simplified transition is not an FAA procedure.',
 'Waiting traffic outside the modeled terminal is admission-controlled. Routine replanning preserves admitted motion. Runway closure may trigger an explicit synthetic climb-and-exit diversion; it is not a published procedure and still requires conflict review.',
 'Fuel, emissions, relative noise and workload are illustrative proxies, not measured aircraft performance, decibels, CNEL or staffing guidance.',
]

def runway(identifier):
    return next(r for r in RUNWAYS if r['id']==identifier)
