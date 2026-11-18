"""Equibase late-changes XML (one file, every track racing that day) read into the same per-track shape as the
saved HTML page, so scratches, conditions, rail, jockey changes, off-turf and pools not offered flow through unchanged."""
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
os.environ["RACEDESK_WEATHER"] = "off"; os.environ["RACEDESK_TOTE"] = "off"

from synthetic_card import build_card                                                        # noqa: E402
from brisnet_pp.changes import changes_for_track, is_late_changes_xml, load_changes_file, parse_late_changes_xml, scratch_spec, summary   # noqa: E402
from handicapper.engine import load_config                                                   # noqa: E402
from handicapper.pipeline import run_card                                                    # noqa: E402

FIX = os.path.join(HERE, "fixtures", "late_changes_sample.xml")
CFG_PATH = os.path.join(ROOT, "rules_config.json")


class TestXml(unittest.TestCase):
    def setUp(self):
        self.data = open(FIX, "rb").read()
        self.doc = parse_late_changes_xml(self.data)

    def test_parse_two_tracks(self):
        self.assertTrue(is_late_changes_xml(self.data)); self.assertFalse(is_late_changes_xml(b"<html><body>x</body></html>"))
        self.assertEqual(self.doc["race_date"], "2026-11-06")
        self.assertEqual([t["id"] for t in self.doc["tracks"]], ["DMR", "CD"])
        dmr = changes_for_track(self.doc, "DMR")
        self.assertEqual(dmr["track"], "DEL MAR"); self.assertEqual(dmr["updated"], "2026-11-06 10:25:00")
        self.assertEqual(scratch_spec(dmr), "1:4, 3:9")
        r1 = dmr["races"][1]
        self.assertEqual(r1["horses"][0]["changes"][0], {"text": "Scratched - Vet", "time": "2026-11-06 10:20:00"})
        self.assertEqual(r1["horses"][1]["changes"][0]["text"], "Jockey - J. Rider changed to K. Kidd")
        r3 = dmr["races"][3]
        self.assertIn("Off Turf: race moved from Turf to Dirt", r3["notes"]); self.assertEqual(r3["pools_not_offered"], ["Superfecta"])
        self.assertEqual(dmr["conditions"], {"dirt": "Good"})
        s = summary(dmr)
        self.assertEqual(s["races"]["1"]["jockey_changes"][0]["to"], "K. Kidd"); self.assertEqual(s["races"]["3"]["pools_not_offered"], ["Superfecta"])
        cd = changes_for_track(self.doc, None, "Churchill Downs", load_config(CFG_PATH))    # matched by name through the aliases
        self.assertEqual(cd["track_id"], "CD"); self.assertEqual(cd["races"][2]["rail"], 18.0); self.assertEqual(scratch_spec(cd), "2:1A")
        self.assertIsNone(changes_for_track(self.doc, "GP"))
        self.assertEqual(len(dmr["raw"]), 6)
        with self.assertRaises(ValueError):
            parse_late_changes_xml(b"<other/>")

    def test_us_date_in_the_file_becomes_iso_and_a_safe_file_name(self):
        from brisnet_pp.changes import iso_date
        self.assertEqual([iso_date(x) for x in ("11/18/2026", "2026-11-18", "November 18, 2026", "11-18-2026", "garbage", None)],
                         ["2026-11-18", "2026-11-18", "2026-11-18", "2026-11-18", None, None])
        doc = parse_late_changes_xml(self.data.replace(b"<race_date>2026-11-06</race_date>", b"<race_date>11/06/2026</race_date>"))
        self.assertEqual((doc["race_date"], doc["race_date_text"]), ("2026-11-06", "11/06/2026"))
        from ui.server import Desk
        tmp = tempfile.mkdtemp(prefix="racedesk-xmldate-")
        try:
            shutil.copy(CFG_PATH, os.path.join(tmp, "rules_config.json")); os.makedirs(os.path.join(tmp, "data", "out"))
            with open(os.path.join(tmp, "data", "out", "dmr1106y.card.json"), "w", encoding="utf-8") as fh:
                json.dump(build_card(), fh)
            desk = Desk(tmp); desk.run("dmr1106y")
            res = desk.save_upload("dmr1106y", "changes", "x.xml", self.data.replace(b"<race_date>2026-11-06</race_date>", b"<race_date>11/06/2026</race_date>"))
            self.assertEqual(res["saved"], os.path.join("data", "pps", "latechanges_2026-11-06.xml"))
            self.assertEqual(res["applied"][0]["scratches"], "1:4, 3:9")
            self.assertTrue(desk.files("dmr1106y")["changes"].endswith("latechanges_2026-11-06.xml"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_load_changes_file_handles_html_and_xml(self):
        self.assertEqual(load_changes_file(FIX, "CD")["track"], "CHURCHILL DOWNS")
        html = os.path.join(HERE, "fixtures", "changes_cd_20261111.html")
        self.assertEqual(load_changes_file(html, "CD")["track"], "Churchill Downs")

    def test_pipeline_off_turf_and_pools_from_the_xml(self):
        chg = changes_for_track(self.doc, "DMR")
        out = run_card(build_card(), config_path=CFG_PATH, multirace=False, changes=chg, scratch=scratch_spec(chg))
        r3 = next(r for r in out["result"]["races"] if r["race_no"] == 3)
        self.assertEqual(r3["surface"], "dirt"); self.assertEqual(r3["surface_switch"]["from"], "turf")
        self.assertEqual(r3["inputs"]["pools_not_offered"], ["Superfecta"]); self.assertEqual(r3["inputs"]["track_condition_morning"], "Good")
        self.assertNotIn("9", [s["pgm"] for s in r3["sheets"]])                                 # scratched off the turf
        self.assertNotIn("4", [s["pgm"] for s in out["result"]["races"][0]["sheets"]])
        self.assertTrue(any("Off Turf" in n for n in r3["inputs"]["notes"]))


class TestDeskXml(unittest.TestCase):
    def test_one_upload_applies_to_every_card_of_the_day(self):
        from ui.server import Desk
        tmp = tempfile.mkdtemp(prefix="racedesk-xml-")
        try:
            shutil.copy(CFG_PATH, os.path.join(tmp, "rules_config.json"))
            os.makedirs(os.path.join(tmp, "data", "out"))
            a = build_card(); b = json.loads(json.dumps(a)); b["track"], b["track_code"] = "Churchill Downs", "CD"
            for name, card in (("dmr1106y", a), ("cdx1106y", b)):
                with open(os.path.join(tmp, "data", "out", f"{name}.card.json"), "w", encoding="utf-8") as fh:
                    json.dump(card, fh)
            desk = Desk(tmp)
            desk.run("dmr1106y"); desk.run("cdx1106y")
            res = desk.save_upload("dmr1106y", "changes", "late_changes.xml", open(FIX, "rb").read())
            self.assertEqual(res["saved"], os.path.join("data", "pps", "latechanges_2026-11-06.xml"))
            self.assertEqual({x["card"]: x["scratches"] for x in res["applied"]}, {"dmr1106y": "1:4, 3:9", "cdx1106y": "2:1A"})
            self.assertTrue(desk.files("cdx1106y")["changes"].endswith("latechanges_2026-11-06.xml"))
            d = desk.run("dmr1106y")
            self.assertEqual(d["state"]["scratches"], "1:4, 3:9")
            self.assertEqual(d["state"]["changes"]["track"], "DEL MAR")
            r3 = next(r for r in d["picks"]["races"] if r["race_no"] == 3)
            self.assertEqual(r3["surface_switch"]["to"], "dirt")
            d2 = desk.run("cdx1106y")
            self.assertEqual(d2["state"]["scratches"], "2:1A"); self.assertEqual(d2["state"]["changes"]["track"], "CHURCHILL DOWNS")
            self.assertEqual(d2["picks"]["races"][1]["inputs"]["rail"], 18.0)
            # a per-track HTML page still works and wins for its card
            html = open(os.path.join(HERE, "fixtures", "changes_cd_20261111.html"), "rb").read()
            desk.save_upload("cdx1106y", "changes", "page.html", html)
            self.assertTrue(desk.files("cdx1106y")["changes"].endswith("cdx1106y.changes.html"))
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
