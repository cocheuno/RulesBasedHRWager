"""Equibase race-day-changes page reader and its data-only integration (scratch list, run block, Desk upload)."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
sys.path.insert(0, HERE)

from synthetic_card import build_card                                              # noqa: E402
from brisnet_pp.changes import merge_scratch_specs, parse_changes, scratch_spec, summary   # noqa: E402

FIX = os.path.join(HERE, "fixtures", "changes_cd_20261111.html")


class TestParse(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = parse_changes(open(FIX, encoding="utf-8").read())

    def test_header(self):
        c = self.c
        self.assertEqual(c["track"], "Churchill Downs")
        self.assertEqual(c["updated"], "November 11, 11:51 AM ET")
        self.assertEqual(c["first_post"], "1:00 PM ET")
        self.assertEqual(c["conditions"], {"dirt": "Fast", "turf": "Firm"})

    def test_rows(self):
        c = self.c
        self.assertEqual(sorted(c["races"]), [1, 4, 5, 6, 7, 8, 9])
        self.assertEqual(c["races"][1]["pools_not_offered"], ["Superfecta", "Odd", "Even", "Super High Five"])
        self.assertEqual(c["races"][5]["rail"], 24.0)
        h14 = next(h for h in c["races"][5]["horses"] if h["pgm"] == "14")
        self.assertEqual(h14["name"], "Code of Arms")
        self.assertEqual([x["text"][:14] for x in h14["changes"]], ["Scratched - Re", "Scratch Reason"], "continuation row joins its horse")
        self.assertEqual(h14["changes"][1]["time"], "11:51 AM ET")
        jc = summary(c)["races"]["8"]["jockey_changes"]
        self.assertEqual(jc, [{"pgm": "14", "name": "Just Buy It", "from": "Luis Saez", "to": "Mario Gutierrez"}])
        self.assertEqual([x["pgm"] for x in summary(c)["races"]["7"]["horse_notes"]], ["1", "10"])

    def test_scratch_spec_matches_the_card_as_run(self):
        # the list the engine would have been given, identical to what was ticked on the Desk on 11/11
        self.assertEqual(scratch_spec(self.c), "1:1, 1:3, 4:5, 5:8, 5:14, 5:15, 5:16, 6:3, 6:10, 8:9, 8:13, 8:15, 8:16")
        self.assertEqual(merge_scratch_specs("5:+14, 9:7", scratch_spec(self.c), None),
                         "1:1, 1:3, 4:5, 5:+14, 5:8, 5:14, 5:15, 5:16, 6:3, 6:10, 8:9, 8:13, 8:15, 8:16, 9:7")


class TestIntegration(unittest.TestCase):
    def test_run_card_records_changes_without_touching_scores(self):
        from handicapper.pipeline import run_card
        card = build_card()
        base = run_card(card, multirace=False)["result"]
        chg = parse_changes(open(FIX, encoding="utf-8").read())
        out = run_card(build_card(), multirace=False, changes=chg)
        res = out["result"]
        self.assertEqual(res["run"]["changes"]["conditions"], {"dirt": "Fast", "turf": "Firm"})
        self.assertEqual(res["run"]["changes"]["races"]["8"]["jockey_changes"][0]["to"], "Mario Gutierrez")
        self.assertTrue(any(n.startswith("changes: Churchill Downs") for n in out["notes"]))
        for r0, r1 in zip(base["races"], res["races"]):
            self.assertEqual([(s["pgm"], s["score"]) for s in r0["sheets"]], [(s["pgm"], s["score"]) for s in r1["sheets"]], "data only: no score moves")
            self.assertEqual(r0["picks"], r1["picks"]); self.assertEqual(r0["wagers"], r1["wagers"])

    def test_desk_upload_fills_scratches_and_run_block(self):
        from ui.server import Desk
        tmp = tempfile.mkdtemp(prefix="racedesk-chg-"); self.addCleanup(shutil.rmtree, tmp, True)
        shutil.copy(os.path.join(ROOT, "rules_config.json"), os.path.join(tmp, "rules_config.json"))
        os.makedirs(os.path.join(tmp, "data", "out"))
        with open(os.path.join(tmp, "data", "out", "synth.card.json"), "w", encoding="utf-8") as fh:
            json.dump(build_card(), fh)
        d = Desk(tmp)
        out = d.save_upload("synth", "changes", "changes.html", open(FIX, "rb").read())
        self.assertTrue(out["saved"].endswith("synth.changes.html"))
        self.assertEqual(out["conditions"], {"dirt": "Fast", "turf": "Firm"})
        pl = d.run("synth", "2:1")                      # the typed scratch and the page's scratches are merged
        self.assertTrue(pl["state"]["scratches"].startswith("1:1, 1:3, 2:1, 4:5"))
        self.assertEqual(pl["picks"]["run"]["changes"]["track"], "Churchill Downs")
        self.assertTrue(any(a["step"] == "Changes page" for a in pl["state"]["activity"]))
        self.assertEqual(pl["files"]["changes"], True)


if __name__ == "__main__":
    unittest.main()
