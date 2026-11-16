"""Phase F: plain English on every horse-facing string (ASD-STE100 style).  No glossary abbreviation appears without
its expansion; the rule id stays as a bracketed reference; quoted chart comments are left as printed."""
from __future__ import annotations

import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)
os.environ["RACEDESK_WEATHER"] = "off"; os.environ["RACEDESK_TOTE"] = "off"

from synthetic_card import build_card                                  # noqa: E402
from handicapper.plain import GLOSSARY, expand, plain, violations      # noqa: E402
from handicapper.engine import format_report, load_config, score_card  # noqa: E402

CFG_PATH = os.path.join(ROOT, "rules_config.json")


def horse_facing(res) -> list[str]:
    out = []
    for r in res["races"]:
        out += [r.get("bet_structure") or "", r.get("selection_note") or ""] + list(r.get("other_wagers", []))
        out += [w.get("label") or "" for w in r.get("wagers", [])]
        out += (r.get("policy") or {}).get("notes", [])
        for s in r["sheets"]:
            out += [h["note"] for h in s["hits"]] + list(s["flags"])
    return [x for x in out if x]


class TestPlain(unittest.TestCase):
    def test_expansion_once_and_shorthand(self):
        self.assertEqual(plain("best E2 92 vs par 88"), "Best second-call pace (E2) 92 against par 88")
        self.assertEqual(plain("ITM 60% (10 starts)"), "In the money (ITM) 60% (10 starts)")
        self.assertEqual(plain("ML 8/5 vs fair 2.1-1; ML short"), "Morning line (ML) 8/5 against fair 2.1-1; ML short")
        self.assertEqual(plain("beaten 12.0L but ran 86 vs par 84"), "Beaten 12.0 lengths but ran a 86 against a par of 84")
        self.assertEqual(plain("trouble: '4w turn, weakened'"), "Had trouble last time: '4w turn, weakened'")   # the chart's words stay
        self.assertEqual(plain("ELIMINATED: avg last-3 64 is 13 below par 77"), "Eliminated: average last three 64 is 13 below par 77")
        self.assertEqual(plain("AE - needs a scratch to run"), "Also-eligible (AE) - needs a scratch to run")
        self.assertEqual(plain(plain("E1 90 vs E1 80")), plain("E1 90 vs E1 80"))                            # idempotent
        self.assertIsNone(plain(None)); self.assertEqual(plain(""), "")
        self.assertEqual(expand("early pace (E1) 90 and E1 80"), "early pace (E1) 90 and E1 80")    # already expanded

    def test_violations_detector(self):
        self.assertEqual(violations(["Morning line (ML) 8/5", "the 'ML' in a comment stays", "no abbreviation here"]), [])
        bad = violations(["ML 8/5 is short", "ITM 60%"])
        self.assertEqual(len(bad), 2); self.assertIn("'ML'", bad[0])
        self.assertIn("AE", GLOSSARY); self.assertIn("MTO", GLOSSARY)

    def test_every_horse_facing_string_on_the_synthetic_card(self):
        res = score_card(build_card(), load_config(CFG_PATH, "DMR"), multirace=True)
        strings = horse_facing(res)
        self.assertGreater(len(strings), 200)
        self.assertEqual(violations(strings), [])
        notes = [h["note"] for r in res["races"] for s in r["sheets"] for h in s["hits"]]
        self.assertTrue(all(n[0].isupper() or not n[0].isalpha() for n in notes))
        self.assertFalse(any(" avg " in n or " vs " in n or "jky" in n for n in notes))
        txt = format_report(res, detail=2)
        self.assertIn("Morning line (ML)", txt); self.assertNotIn("| ML |", txt)
        self.assertRegex(txt, r"\(S\d+, [+-]\d+\.\d\)")                                     # note first, rule id and points in brackets
        self.assertEqual(violations([ln for ln in txt.splitlines() if ln.startswith("- ") or ln.startswith("| ")]), [])


if __name__ == "__main__":
    unittest.main()
