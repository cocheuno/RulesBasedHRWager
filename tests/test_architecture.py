"""Regression coverage for recommendation, field and prediction-history boundaries."""
import copy
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from synthetic_card import build_card
from handicapper.engine import load_config, score_card, score_race, other_wagers, win_price
from handicapper.multirace import leg_summary
from handicapper.pipeline import run_card
from handicapper.snapshot import (write_snapshot, list_snapshots, latest_snapshot,
                                   evaluation_basis, timing_evidence, prediction_kind)
from handicapper.wagering import evaluate_card
from ui.server import Desk

ROOT = Path(__file__).resolve().parents[1]
NOW = datetime(2026, 11, 10, 16, tzinfo=timezone.utc)


def timed(card=None):
    card = copy.deepcopy(card or build_card())
    card['date'] = NOW.date().isoformat()
    for r in card['races']:
        r['post_at_utc'] = (NOW + timedelta(hours=r['race_no'])).isoformat()
    return card


def with_evidence(result, card):
    result = copy.deepcopy(result)
    result['run'] = {'at_utc': NOW.isoformat(), 'results_known': [],
                     'timing': timing_evidence(card, NOW, [])}
    return result


class TestRecommendations(unittest.TestCase):
    def test_every_recommendation_meets_one_price_gate(self):
        cfg = load_config(None)
        # Include unusually strict margin/floor settings that V1 alone cannot enforce.
        for margin in (0.15, 5.0):
            cfg['selection']['win_margin'] = margin
            result = score_card(build_card(), cfg)
            for r in result['races']:
                names = {s['pgm']: s for s in r['sheets']}
                for w in r['wagers']:
                    self.assertEqual(w['type'], 'WIN')
                    for k in w['legs'][0]:
                        self.assertIs(win_price(names[k], cfg['selection'])['ok'], True)
                        self.assertEqual(w['min_odds_by'][k], win_price(names[k], cfg['selection'])['min_odds'])
                for w in r['wager_options']:
                    self.assertTrue(w['advisory'])
                    self.assertNotEqual(w['type'], 'WIN')

    def test_secondary_overlay_below_floor_or_margin_is_not_recommended(self):
        cfg = load_config(None)
        r = score_card(build_card(), cfg)['races'][0]
        r['confidence'] = 'medium'
        for s in r['sheets']:
            s['hits'] = [h for h in s['hits'] if h['rule'] != 'V1']
        top = next(s for s in r['sheets'] if not s['eliminated'] and not s['flags'])
        top.update(fair_odds=1.0, ml_decimal=1.4, ml_odds='7/5')
        top['hits'].append({'rule': 'V1', 'points': 3})
        ws = []
        other_wagers(r, None, cfg['selection'], ws)
        self.assertFalse([w for w in ws if w['type'] == 'WIN'])
        top.update(fair_odds=10.0, ml_decimal=14.0, ml_odds='14/1')
        ws = []
        other_wagers(r, None, dict(cfg['selection'], win_margin=1), ws)
        self.assertFalse([w for w in ws if w['type'] == 'WIN'])

    def test_no_value_pass_retains_rankings_and_optional_scenarios(self):
        card = build_card()
        for r in card['races']:
            for h in r['horses']:
                h.update(ml_decimal=0.1, ml_odds='1/10')
        result = score_card(card, load_config(None))
        for r in result['races']:
            self.assertTrue(r['picks'])
            self.assertEqual(r['wager_status'], 'PASS')
            self.assertEqual(r['wagers'], [])
            self.assertIn('PASS', r['bet_structure'])
            self.assertTrue(r['wager_options'])

    def test_saved_stakes_and_policy_ignore_later_config(self):
        result = score_card(build_card(), load_config(None))
        results = {'races': [{'race_no': r['race_no'], 'finish': [r['picks'][0]], 'win': 6.0}
                             for r in result['races']]}
        original = evaluate_card(result, results)
        changed = evaluate_card(result, results, {'units': {'WIN': 999}, 'count_other_wagers': False,
                                                  'count_multirace': True})
        self.assertEqual(original, changed)
        self.assertEqual(changed['policy_basis'], 'saved')
        legacy = copy.deepcopy(result)
        legacy.pop('evaluation_policy')
        self.assertEqual(evaluate_card(legacy, results)['policy_basis'], 'legacy-current-settings')


class TestFields(unittest.TestCase):
    def test_conditional_field_matches_actual_activation_for_ae_and_mto(self):
        cfg = load_config(None)
        for status in ('AE', 'MTO'):
            race = build_card()['races'][0]
            alt = next(h for h in race['horses'] if h['entry_status'])
            alt['entry_status'] = status
            conditional = score_race(race, cfg)
            alt_sheet = next(s for s in conditional['sheets'] if s['pgm'] == alt['pgm'])
            active_race = copy.deepcopy(race)
            next(h for h in active_race['horses'] if h['pgm'] == alt['pgm'])['entry_status'] = None
            drawn_in = score_race(active_race, cfg)
            actual = next(s for s in drawn_in['sheets'] if s['pgm'] == alt['pgm'])
            self.assertEqual((alt_sheet['score'], alt_sheet['conditional_rank']), (actual['score'], actual['rank']))
            self.assertEqual(alt_sheet['conditional']['rankings'],
                             [{'pgm': s['pgm'], 'score': s['score'], 'rank': s['rank']} for s in drawn_in['sheets']])
            self.assertEqual(alt_sheet['win_prob'], 0)
            self.assertTrue(alt_sheet['flags'])

    def test_disabling_a_scoring_rule_cannot_activate_an_alternate(self):
        cfg = load_config(None)
        cfg['disabled'] = ['X3']
        result = score_race(build_card()['races'][0], cfg)
        alt = next(s for s in result['sheets'] if s['pgm'] in result['alternates'])
        self.assertTrue(alt['flags'])
        self.assertEqual(alt['win_prob'], 0)
        self.assertNotIn(alt['pgm'], result['picks'])

    def test_eliminated_inactive_alternate_does_not_change_pricing(self):
        cfg = load_config(None)
        race = build_card()['races'][0]
        race['horses'] = [h for h in race['horses'] if not h['entry_status']]
        before = score_race(race, cfg)
        bad = copy.deepcopy(next(h for h in build_card()['races'][1]['horses'] if h['name'] == 'Out Of Sorts'))
        bad.update(pgm='99', entry_status='AE', days_since_last=400, workouts=[])
        race['horses'].append(bad)
        after = score_race(race, cfg)
        self.assertTrue(next(s for s in after['sheets'] if s['pgm'] == '99')['eliminated'])
        self.assertEqual(leg_summary(before, cfg['multirace'])['price_factor'],
                         leg_summary(after, cfg['multirace'])['price_factor'])
        self.assertEqual([(s['pgm'], s['score'], s['win_prob']) for s in before['sheets']],
                         [(s['pgm'], s['score'], s['win_prob']) for s in after['sheets'] if not s['flags']])


class TestHistory(unittest.TestCase):
    def test_timing_requires_aware_future_posts_on_every_race(self):
        c = timed()
        t = timing_evidence(c, NOW, [])
        self.assertEqual(t['status'], 'verified-before-post')
        c['races'][0]['post_at_utc'] = '2026-11-10T18:00:00'  # naive, not trusted
        self.assertEqual(timing_evidence(c, NOW, [])['status'], 'unverified')
        c['races'][0]['post_at_utc'] = NOW.isoformat()
        self.assertEqual(timing_evidence(c, NOW, [])['status'], 'retrospective')
        self.assertEqual(timing_evidence(timed(), NOW, [1])['status'], 'retrospective')
        old = build_card(); old['date'] = '2001-01-01'
        self.assertEqual(timing_evidence(old, NOW, [])['status'], 'retrospective')

    def test_legacy_prerace_label_does_not_verify_timing(self):
        result = {'snapshot': {'kind': 'pre-race'}, 'run': {'at_utc': NOW.isoformat()}, 'races': [{'race_no': 1}]}
        self.assertEqual(evaluation_basis(result), 'timing-unverified')
        good = with_evidence(score_card(timed(), load_config(None)), timed())
        self.assertEqual(evaluation_basis(good), 'verified-pre-race')
        good['run']['results_known'] = [1]
        self.assertEqual(evaluation_basis(good), 'retrospective')

    def test_concurrent_same_second_snapshots_are_unique_and_ordered(self):
        with tempfile.TemporaryDirectory() as d:
            result = {'run': {'at_utc': NOW.isoformat()}, 'races': []}
            def write(n):
                return write_snapshot(d, 'synth', dict(result, marker=n), 'pre-race')
            with ThreadPoolExecutor(max_workers=6) as pool:
                paths = list(pool.map(write, range(14)))
            self.assertEqual(len(set(paths)), 14)
            snaps = list_snapshots(d, 'synth')
            self.assertEqual([s['sequence'] for s in snaps], list(range(1, 15)))
            latest = latest_snapshot(d, 'synth', None)
            self.assertEqual(latest['snapshot']['sequence'], 14)
            self.assertEqual(latest['snapshot']['kind'], 'timing-unverified')
            for p in paths:
                with open(p) as f:
                    self.assertIn('marker', json.load(f))

    def test_pipeline_accepts_explicit_posts_and_freezes_config(self):
        c = timed()
        posts = {str(r['race_no']): r.pop('post_at_utc') for r in c['races']}
        out = run_card(c, post_times=posts)
        self.assertIn('effective_config', out['result']['run'])
        self.assertEqual(out['result']['run']['effective_config'], out['cfg'])
        self.assertEqual(out['result']['run']['kind'], 'pre-race')
        with self.assertRaises(ValueError):
            run_card(c, post_times={'1': '10:00'})
        with self.assertRaises(ValueError):
            run_card(c, post_times={'999': '2030-01-01T12:00:00Z'})

    def test_ui_aggregates_evidence_separately(self):
        with tempfile.TemporaryDirectory() as d:
            shutil.copy(ROOT / 'rules_config.json', Path(d) / 'rules_config.json')
            out = Path(d) / 'data/out'; out.mkdir(parents=True)
            desk = Desk(d)
            for name in ('verified', 'legacy', 'history'):
                card = timed()
                if name != 'verified':
                    for r in card['races']:
                        r.pop('post_at_utc')
                if name == 'history':
                    card['date'] = '2001-01-01'
                (out / (name + '.card.json')).write_text(json.dumps(card))
                desk.run(name)
                desk.save_result(name, {'race_no': 2, 'finish': ['1', '3'], 'win': 8})
            analysis = desk.analysis()
            self.assertEqual({c['basis'] for c in analysis['cards']},
                             {'verified-pre-race', 'timing-unverified', 'retrospective'})
            self.assertTrue(analysis['rows'])
            self.assertTrue(all(r['basis'] == 'verified-pre-race' for r in analysis['rows']))
            self.assertEqual(analysis['rollup'], analysis['rollups_by_basis']['verified-pre-race'])
            for basis, rows in analysis['rows_by_basis'].items():
                self.assertTrue(rows)
                self.assertTrue(all(r['basis'] == basis for r in rows))
