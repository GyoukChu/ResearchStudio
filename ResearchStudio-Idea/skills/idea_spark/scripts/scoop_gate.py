"""Phase 3.4 — the scoop gate: the scoop-check skill run on the FINAL method, as a pass/fail novelty gate.

Why: the Phase 3 collision audit abandons only on exact-mechanism overlap; every other prior-art
finding is advisory, so a candidate whose closest prior work shares its mechanism on a neighbouring
problem still reaches a card. The gate runs the full scoop-check procedure (search, recall, triage,
full-text deep dive) on the method that Phase 3 settled — Phase 4 may not change the mechanism, so
this is the method the card will carry — and refuses a candidate below the novelty bar. A refused
candidate goes through the existing bounded retry (a new cycle, at most three, with the closest
prior work carried as a threat lesson); when the budget runs out, the cycle with the best novelty
level is printed as a card marked FAILED VALIDATION.

The level arithmetic is the program's, never the reviewer's: the reviewer records, per prior work,
which of the four scoop-check axes match (match | differ), and this module computes the levels.

Gate rule (`gate_level`): scoop-check's raw level is `5 − matching axes`, worst case over prior works.
idea-spark always generates for the user's own research problem, so any paper on that problem matches
on problem framing and application domain by construction — the raw level of a fresh method on a
studied problem is capped at 3. The gate therefore excuses those two axes when they are the ONLY
match: a prior work whose matches lie within {problem_framing, application_domain} scores gate level
5 (the method axes are clean); any other prior work scores its raw level. A candidate passes when
every prior work's gate level is at least the run's minimum (default 4).
"""
from __future__ import annotations
import os
import re
from pathlib import Path

SCOOP = 'phase3_scoop/scoop_verdict.json'
SCOOP_REPORT = 'phase3_scoop/scoop_report.json'
REPORT_MD = {'en': 'phase3_scoop/scoop_report.en.md', 'ko': 'phase3_scoop/scoop_report.ko.md'}
AXES = ('problem_framing', 'core_mechanism', 'key_insight', 'application_domain')
EXCUSED = frozenset(('problem_framing', 'application_domain'))
LABELS = {5: 'No Overlap', 4: 'Low Overlap', 3: 'Medium Overlap', 2: 'High Overlap', 1: 'Full Overlap'}
MIN_PRIOR_WORKS = 3          # scoop-check Step 4 deep-dives 3-7 candidates; fewer is not a comparison


def scoop_from_env():
    """Fixed at init (like depth): IDEASPARK_SCOOP=off disables the gate; IDEASPARK_SCOOP_MIN_LEVEL sets
    the bar (1-5, default 4 = Low Overlap)."""
    enabled = os.environ.get('IDEASPARK_SCOOP', 'on').strip().lower() not in ('off', '0', 'false')
    try:
        level = int(os.environ.get('IDEASPARK_SCOOP_MIN_LEVEL', '4'))
    except ValueError:
        level = 4
    return {'enabled': enabled, 'min_level': min(5, max(1, level))}


def run_scoop(contract):
    """The run's gate setting. A contract written before the gate existed ran without it and keeps
    running without it (like `run_depth`), so no run gains a heavy call partway through."""
    s = contract.get('scoop') if isinstance(contract, dict) else None
    return s if isinstance(s, dict) and 'enabled' in s and 'min_level' in s else {'enabled': False, 'min_level': 4}


def _matches(pw):
    axes = pw.get('axes') if isinstance(pw, dict) else None
    if not isinstance(axes, dict):
        return None
    vals = {a: str(axes.get(a, '')).strip().lower() for a in AXES}
    if any(v not in ('match', 'differ') for v in vals.values()):
        return None
    return {a for a, v in vals.items() if v == 'match'}


def evaluate(verdict, min_level=4):
    """Levels computed from the recorded axes. None when the verdict is not a usable comparison."""
    pws = verdict.get('prior_works') if isinstance(verdict, dict) else None
    if not isinstance(pws, list) or not pws:
        return None
    rows = []
    for pw in pws:
        m = _matches(pw)
        if m is None:
            return None
        raw = 5 - len(m)
        rows.append({'title': str(pw.get('title', ''))[:200], 'source': str(pw.get('source', ''))[:200],
                     'matched': sorted(m), 'raw_level': raw, 'gate_level': 5 if m <= EXCUSED else raw})
    worst = min(rows, key=lambda r: (r['gate_level'], r['raw_level']))
    raw_level = min(r['raw_level'] for r in rows)
    return {'raw_level': raw_level, 'raw_label': LABELS[raw_level],
            'gate_level': worst['gate_level'], 'gate_label': LABELS[worst['gate_level']],
            'min_level': min_level, 'passed': worst['gate_level'] >= min_level,
            'closest': worst, 'prior_works': rows}


def summary(ev):
    """One line for cards, failure reports and the host."""
    c = ev['closest']
    return (f"novelty gate Level {ev['gate_level']} — {ev['gate_label']} (scoop-check raw Level {ev['raw_level']} — "
            f"{ev['raw_label']}; bar Level {ev['min_level']}); closest prior work: {c['title']} "
            f"(matching axes: {', '.join(c['matched']) or 'none'})")


def summary_ko(ev):
    c = ev['closest']
    return (f"게이트 Level {ev['gate_level']} — {ev['gate_label']} (scoop-check 원 판정 Level {ev['raw_level']} — "
            f"{ev['raw_label']}; 기준 Level {ev['min_level']}); 가장 가까운 선행 연구: {c['title']} "
            f"(일치 축: {', '.join(c['matched']) or '없음'})")


def contract_findings(payloads):
    """Rules the reviewer can satisfy in the result itself; checked before commit (record handshake)."""
    from scripts.quality_contract import finding
    out = []
    verdict = next((p for r, p in payloads.items() if r.endswith('scoop_verdict.json')), None)
    report = next((p for r, p in payloads.items() if r.endswith('scoop_report.json')), None)
    if verdict is not None:
        pws = verdict.get('prior_works')
        if not isinstance(pws, list) or len(pws) < MIN_PRIOR_WORKS:
            out.append(finding('scoop_contract', f'prior_works must list every Step 4 deep-dive candidate '
                               f'(at least {MIN_PRIOR_WORKS}); lower the triage threshold as scoop-check Step 4 says.'))
        else:
            for i, pw in enumerate(pws):
                if _matches(pw) is None:
                    out.append(finding('scoop_contract', f'prior_works[{i}].axes must give each of {", ".join(AXES)} '
                                       'as exactly "match" or "differ" (resolve a partial to one of them).'))
                    continue
                try:
                    declared = None if pw.get('level') is None else int(pw.get('level'))
                except (TypeError, ValueError):
                    declared = -1
                if declared is not None and declared != 5 - len(_matches(pw)):
                    out.append(finding('scoop_contract', f'prior_works[{i}].level {declared} != 5 - matching axes '
                                       f'({5 - len(_matches(pw))}); the level follows the axes.'))
                if not str(pw.get('title', '')).strip() or not str(pw.get('evidence', '')).strip():
                    out.append(finding('scoop_contract', f'prior_works[{i}] needs title and evidence (a closest passage '
                                       'or section reference from the deep dive).'))
        for k in ('research_problem', 'novelty_claim', 'delta'):
            if not str(verdict.get(k, '')).strip():
                out.append(finding('scoop_contract', f'scoop_verdict.json is missing {k}.'))
    if report is not None:
        en, ko = str(report.get('report_en', '')), str(report.get('report_ko', ''))
        if len(en.strip()) < 200:
            out.append(finding('scoop_contract', 'scoop_report.json report_en must be the full scoop-check Report (English).'))
        if len(ko.strip()) < 200 or not re.search(r'[가-힣]', ko):
            out.append(finding('scoop_contract', 'scoop_report.json report_ko must be the full Korean version of the Report.'))
    return out


def write_reports(run, min_level=4):
    """The two Markdown reports the reader keeps, from the committed report payload, each headed by the
    gate's own computed result (the reviewer's prose never states whether the gate passed)."""
    from scripts.quality_contract import read
    report = read(Path(run) / SCOOP_REPORT)
    ev = evaluate(read(Path(run) / SCOOP), min_level)
    head = {'en': '> **Novelty gate (idea-spark): ' + ('PASS' if ev and ev['passed'] else 'FAIL') + '** — ',
            'ko': '> **새로움 게이트 (idea-spark): ' + ('통과' if ev and ev['passed'] else '미달') + '** — '}
    for lang, rel in REPORT_MD.items():
        line = head[lang] + ((summary_ko(ev) if lang == 'ko' else summary(ev)) if ev else
                             'verdict not computable from the recorded axes')
        (Path(run) / rel).write_text(line + '\n\n' + str(report.get('report_' + lang, '')).rstrip() + '\n')
    return list(REPORT_MD.values())
