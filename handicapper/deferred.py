"""Interfaces for the models the data watch defers (Phase E).  None of them fits anything today: each `fit` first
asks the data watch whether its gate is met and raises DeferredNotEnoughProspectiveData otherwise, with the count
and the threshold in the message.  When a gate is met the owner decides; the code does not start fitting on its own.

  Hierarchy for every model below: global parameters first (the only thing validated at the 300-race gate), then
  circuit effects (rules_config.json -> circuits: tracks sharing a horse population), then track effects, each level
  a random effect shrunk toward the level above in proportion to its data. Never a separate fit per circuit or track.
  Surface and distance enter as features before any place effect: the frozen week showed that gap is the large one.

  HierarchicalFigureCorrection   gate global_calibration   figure adjustments by surface / distance, then circuit, then
                                                           track, with partial pooling, replacing fixed bias tables
  ConditionalLogitRaceModel      gate global_calibration   a race-level conditional-logit (softmax) model of the win
                                                           probability from the engine's features and the market,
                                                           replacing the hand-set logit_scale and ml_blend
  OddsDriftForecast              gate odds_drift           forecast of the final odds from the board 5 / 2 / 0 minutes
                                                           out, from complete tote histories
  ConstrainedKelly               gate global_calibration   stake sizing from a validated probability and a quote,
                                                           capped per race and per day (needs VALIDATED model status)
  JointFinishingOrderPricer      gate global_calibration   exacta / trifecta pricing from a joint finishing-order
                                                           model (Harville and alternatives), checked against probables
  TimeformIncrementalValue       gate timeform_value       whether Timeform figures add information to the Brisnet set
"""
from __future__ import annotations


class DeferredNotEnoughProspectiveData(Exception):
    def __init__(self, gate: str, have: int, threshold: int, capability: str):
        super().__init__(f"{capability}: DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA ({have} of {threshold} {gate} races)")
        self.gate, self.have, self.threshold, self.capability = gate, have, threshold, capability


class DeferredModel:
    gate = "global_calibration"
    name = "deferred model"

    def __init__(self, watch: dict):
        """watch: handicapper.evaluation.data_watch(...) output."""
        self.watch = watch

    def status(self) -> dict:
        g = (self.watch.get("gates") or {}).get(self.gate) or {}
        return {"model": self.name, "gate": self.gate, "have": g.get("have", 0), "threshold": g.get("threshold"), "status": g.get("status", "DEFERRED_NOT_ENOUGH_PROSPECTIVE_DATA")}

    def _check(self) -> None:
        s = self.status()
        if s["status"] != "GATE_MET_AWAITING_OWNER_REVIEW":
            raise DeferredNotEnoughProspectiveData(self.gate, s["have"], s["threshold"] or 0, self.name)

    def fit(self, records: list[dict]):
        self._check()
        raise NotImplementedError(f"{self.name}: the gate is met; fitting is an owner decision and is not implemented yet")

    def predict(self, *a, **k):
        raise NotImplementedError(f"{self.name}: no fitted model")


class HierarchicalFigureCorrection(DeferredModel):
    name = "hierarchical figure correction"
    levels = ("global", "surface x distance", "circuit", "track")


class ConditionalLogitRaceModel(DeferredModel):
    name = "conditional-logit race model"
    levels = ("global", "circuit", "track")   # random effects on the scale and the market weight, shrunk toward the level above


class OddsDriftForecast(DeferredModel):
    gate = "odds_drift"
    name = "late-odds drift forecast"


class ConstrainedKelly(DeferredModel):
    name = "constrained Kelly staking"


class JointFinishingOrderPricer(DeferredModel):
    name = "joint finishing-order exotic pricing"


class TimeformIncrementalValue(DeferredModel):
    gate = "timeform_value"
    name = "Timeform incremental value"


class RacingDudesIncrementalValue(DeferredModel):
    gate = "racing_dudes_value"
    name = "Racing Dudes incremental value"


ALL = (HierarchicalFigureCorrection, ConditionalLogitRaceModel, OddsDriftForecast, ConstrainedKelly, JointFinishingOrderPricer, TimeformIncrementalValue,
       RacingDudesIncrementalValue)


def statuses(watch: dict) -> list[dict]:
    return [cls(watch).status() for cls in ALL]
