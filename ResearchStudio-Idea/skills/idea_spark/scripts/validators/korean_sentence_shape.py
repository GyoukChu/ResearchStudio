"""Validator: a Korean field must not stack an English sentence into one unbroken Korean run.

The plain-Korean fields are the ones a reader actually reads, and they are derived from finished
English prose one sentence at a time. The failure that survives that derivation is shape: English
relative clauses land as one long 관형절 chain in front of the noun, so the reader has to reach
the end of a long run before learning what is being described.

`derive_plain.txt` states the rule (KOREAN SENTENCE SHAPE); this check is its mechanical floor:
a run of Korean prose with no break (comma, full stop, semicolon, colon, parenthesis, dash) past a
threshold, and the polite register (-습니다 / -입니다) where the card uses the plain -다 register.
`warn` and not `fail` — a long run is a readability defect, not a broken contract, and a technical
noun phrase can legitimately run long.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

# A Korean sentence of ordinary length is 40-80 characters; a run past this with no break at all
# is a stacked clause. Kept lenient because the plain_derive record handshake refuses on it.
_MAX_RUN = 90
_BREAK = re.compile(r'[,.;:()\[\]、，。；：（）—–!?·]|\n')
_HANGUL = re.compile(r'[가-힣]')
_POLITE = re.compile(r'(?:습니다|입니다|합니다|됩니다)(?=[.\s]|$)')

# Calques whose Korean reading is a different word, so the sentence is not merely awkward.
_CALQUES = {'두 비트': '두 개의 이진 판정 (the two bits)'}

_KO_FIELDS = ('title_ko', 'plain_motivation_ko')
_KO_LISTS = ('plain_method_steps_ko', 'plain_method_modules_ko')


def _spans(doc):
    """Yield (label, text) for every Korean prose field in an expansion."""
    for k in _KO_FIELDS:
        v = doc.get(k)
        if isinstance(v, str) and v.strip():
            yield k, v
    for k in _KO_LISTS:
        for i, item in enumerate(doc.get(k) or []):
            if isinstance(item, str):
                yield f'{k}[{i}]', item
            elif isinstance(item, dict):
                for kk, vv in item.items():
                    if isinstance(vv, str) and vv.strip():
                        yield f'{k}[{i}].{kk}', vv


def validate_korean_sentence_shape(phase4_path: str) -> list[dict]:
    try:
        doc = json.loads(Path(phase4_path).read_text())
    except Exception:
        return []
    return korean_sentence_shape_findings(doc)


def korean_sentence_shape_findings(doc) -> list[dict]:
    """The same check on an in-memory document, so the plain_derive record handshake can refuse a
    derivation that breaks the rule before it is committed (the author fixes the named fields)."""
    findings: list[dict] = []
    if not isinstance(doc, dict):
        return findings

    long_hits, polite_hits, calque_hits = [], [], []
    for label, text in _spans(doc):
        # Inline code and math are identifiers, not prose; they never count toward a run.
        prose = re.sub(r'`[^`]*`|\$[^$]*\$', ' ', text)
        for run in _BREAK.split(prose):
            if len(run.strip()) > _MAX_RUN and _HANGUL.search(run):
                long_hits.append((label, run.strip()[:34]))
                break                     # one report per field is enough to act on
        if _POLITE.search(prose):
            polite_hits.append(label)
        for bad, good in _CALQUES.items():
            if bad in text:
                calque_hits.append((label, bad, good))

    if long_hits:
        shown = '; '.join(f'{lb}: 「{s}…」' for lb, s in long_hits[:3])
        findings.append({
            'validator': 'korean_sentence_shape', 'severity': 'warn',
            'message': (f'{len(long_hits)} Korean field(s) run more than {_MAX_RUN} characters with '
                        f'no break — {shown}. That is an English sentence stacked into one Korean '
                        f'관형절 chain; the reader cannot tell what is being described until the end. '
                        f'Split it: name the thing first, then describe it in its own clause (see '
                        f'KOREAN SENTENCE SHAPE in derive_plain.txt).')})
    if polite_hits:
        findings.append({
            'validator': 'korean_sentence_shape', 'severity': 'warn',
            'message': ('Polite register (-습니다/-입니다) in ' + ', '.join(polite_hits[:3])
                        + '; the cards use the plain declarative register (-다).')})
    if calque_hits:
        shown = '; '.join(f'{lb}: 「{b}」→ {g}' for lb, b, g in calque_hits[:3])
        findings.append({
            'validator': 'korean_sentence_shape', 'severity': 'warn',
            'message': f'Calqued term(s) whose Korean reading is a different word — {shown}.'})

    if not findings:
        findings.append({
            'validator': 'korean_sentence_shape', 'severity': 'pass',
            'message': 'Korean fields carry no over-long unbroken run, no polite register and no known calque.'})
    return findings
