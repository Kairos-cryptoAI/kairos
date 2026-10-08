"""Bounded SQLite research evidence, not a runtime outbox or trading publisher.

Every operation verifies a frozen local source identity and replays the exact
typed v2 fold. A committed terminal attempt cannot be rescued on restart. Hash
links detect accidental edits/truncation, not an owner's full rewrite/rollback.
"""

from __future__ import annotations

import hashlib
import sqlite3
import stat
from contextlib import contextmanager
from dataclasses import asdict, dataclass, fields, replace
from pathlib import Path
from typing import Any

import kairos_core
import kairos_strategy
from kairos_core.enums import Side
from kairos_strategy.adaptive.config import DEFAULT_CONFIG
from kairos_strategy.candles import Candle
from kairos_strategy.models import ExitPlan, SleeveIntent

from .historical_context import _clock, _json, _name, _sha, canonical, digest
from .hypothesis_v2 import (
    MECHANICS,
    EntryQuote,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    evaluate_hypothesis,
)
from .scenarios import (
    CAPABILITIES,
    MAX_OBSERVATIONS,
    ScenarioEvaluation,
    ScenarioEvidence,
    ScenarioObservation,
    ScenarioReview,
)

SCHEMA = "kairos.development.hypothesis-journal.v1"
MAX_JSON_BYTES = 65_536
MAX_DATABASE_BYTES = 512 * 1024 * 1024
DDL = {
    "meta": "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), schema_id TEXT NOT NULL, "
    "seal_json TEXT NOT NULL, implementation_json TEXT NOT NULL, event_count INTEGER NOT NULL, "
    "head_sha256 TEXT NOT NULL)",
    "parents": "CREATE TABLE parents (arm_id TEXT NOT NULL, parent_id TEXT NOT NULL, "
    "plan_json TEXT NOT NULL, PRIMARY KEY(arm_id,parent_id))",
    "events": "CREATE TABLE events (sequence INTEGER PRIMARY KEY, arm_id TEXT NOT NULL, "
    "parent_id TEXT NOT NULL, minute_ms INTEGER, observation_json TEXT, evaluation_json TEXT NOT NULL, "
    "previous_sha256 TEXT NOT NULL, chain_sha256 TEXT NOT NULL, UNIQUE(arm_id,parent_id,minute_ms), "
    "FOREIGN KEY(arm_id,parent_id) REFERENCES parents(arm_id,parent_id))",
}


@dataclass(frozen=True)
class JournalArm:
    arm_id: str
    policy: HypothesisPolicy

    def __post_init__(self) -> None:
        _name(self.arm_id)
        if type(self.policy) is not HypothesisPolicy:
            raise ValueError("typed frozen journal arm policy required")
        HypothesisPolicy(**asdict(self.policy))


@dataclass(frozen=True)
class JournalSeal:
    """All allowed arms declared before observations; no automatic enrolment."""

    experiment_id: str
    sealed_ms: int
    source_set_sha256: str
    arms: tuple[JournalArm, ...]
    maximum_parents: int

    def __post_init__(self) -> None:
        _name(self.experiment_id)
        _clock(self.sealed_ms)
        _sha(self.source_set_sha256)
        if (
            type(self.maximum_parents) is not int
            or not 1 <= self.maximum_parents <= 128
            or type(self.arms) is not tuple
            or not 1 <= len(self.arms) <= 8
            or any(type(arm) is not JournalArm for arm in self.arms)
        ):
            raise ValueError("explicit bounded immutable journal roster required")
        ids = tuple(arm.arm_id for arm in self.arms)
        if ids != tuple(sorted(set(ids))):
            raise ValueError("canonical unique arm identities required")
        for arm in self.arms:
            JournalArm(arm.arm_id, arm.policy)
            if arm.policy.sealed_ms != self.sealed_ms:
                raise ValueError("all arm policies must be fixed at the journal seal")


@dataclass(frozen=True)
class JournalReceipt:
    new_event: bool
    sequence: int
    chain_sha256: str
    arm_id: str
    parent_id: str
    evaluation: ScenarioEvaluation


@dataclass(frozen=True)
class RecordedHypothesis:
    arm_id: str
    plan: HypothesisPlan
    observations: tuple[HypothesisObservation, ...]
    receipts: tuple[JournalReceipt, ...]


@dataclass(frozen=True)
class JournalSnapshot:
    seal_sha256: str
    head_sha256: str
    event_count: int
    hypotheses: tuple[RecordedHypothesis, ...]


def _object(cls: type, raw: Any, *, all_fields: bool = False) -> dict[str, Any]:
    expected = {f.name for f in fields(cls) if f.init or all_fields}
    if type(raw) is not dict or set(raw) != expected:
        raise ValueError("exact journal contract fields required")
    return dict(raw)


def _pairs(raw: Any) -> tuple[tuple[str, str], ...]:
    if type(raw) is not list or any(
        type(pair) is not list or len(pair) != 2 or any(type(v) is not str for v in pair) for pair in raw
    ):
        raise ValueError("exact JSON string pairs required")
    return tuple(tuple(pair) for pair in raw)


def _load(encoded: str) -> Any:
    if type(encoded) is not str or len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("bounded canonical journal JSON required")
    raw = _json(encoded)
    if canonical(raw) != encoded:
        raise ValueError("journal JSON cannot normalize or discard bytes")
    return raw


def _encode(value: Any) -> str:
    encoded = canonical(asdict(value))
    _load(encoded)
    return encoded


def _intent(raw: Any) -> SleeveIntent:
    values = _object(SleeveIntent, raw, all_fields=True)
    identity = values.pop("intent_id")
    values["side"] = Side(values["side"])
    values["metadata"] = _pairs(values["metadata"])
    values["exit_plan"] = ExitPlan(**_object(ExitPlan, values["exit_plan"]))
    result = SleeveIntent(**values)
    if result.intent_id != identity or canonical(asdict(result)) != canonical(raw):
        raise ValueError("stored original intent identity or exact protection changed")
    return result


def _plan(encoded: str) -> HypothesisPlan:
    values = _object(HypothesisPlan, _load(encoded))
    values["template"] = _intent(values["template"])
    values["policy"] = HypothesisPolicy(**_object(HypothesisPolicy, values["policy"]))
    values["anchor"] = Candle(**_object(Candle, values["anchor"]))
    values["creation_evidence"] = _sources(values["creation_evidence"])
    values["required_sources"] = _pairs(values["required_sources"])
    result = HypothesisPlan(**values)
    if _encode(result) != encoded:
        raise ValueError("stored hypothesis must round-trip without normalization")
    return result


def _sources(raw: Any) -> tuple[ScenarioEvidence, ...]:
    if type(raw) is not list or len(raw) > 32:
        raise ValueError("bounded JSON sources required")
    return tuple(ScenarioEvidence(**_object(ScenarioEvidence, item)) for item in raw)


def _observation(encoded: str) -> HypothesisObservation:
    values = _object(HypothesisObservation, _load(encoded))
    market = _object(ScenarioObservation, values["market"])
    market["candle"] = Candle(**_object(Candle, market["candle"]))
    market["sources"] = _sources(market["sources"])
    if market["review"] is not None:
        review = _object(ScenarioReview, market["review"])
        review["side"] = Side(review["side"])
        market["review"] = ScenarioReview(**review)
    values["market"] = ScenarioObservation(**market)
    if values["quote"] is not None:
        values["quote"] = EntryQuote(**_object(EntryQuote, values["quote"]))
    result = HypothesisObservation(**values)
    if _encode(result) != encoded:
        raise ValueError("stored observation must round-trip without normalization")
    return result


def _seal(encoded: str) -> JournalSeal:
    values = _object(JournalSeal, _load(encoded))
    raw_arms = values["arms"]
    if type(raw_arms) is not list or not 1 <= len(raw_arms) <= 8:
        raise ValueError("bounded frozen arm list required")
    arms = []
    for raw in raw_arms:
        arm = _object(JournalArm, raw)
        arm["policy"] = HypothesisPolicy(**_object(HypothesisPolicy, arm["policy"]))
        arms.append(JournalArm(**arm))
    values["arms"] = tuple(arms)
    result = JournalSeal(**values)
    if _encode(result) != encoded:
        raise ValueError("exact frozen seal required")
    return result


def _regular_path(path: Path, *, exists: bool) -> Path:
    path = Path(path).absolute()
    if not path.name.endswith(".research.sqlite3"):
        raise ValueError("separate .research.sqlite3 evidence file required")
    for item in (*reversed(path.parents), path):
        if not item.exists() and item == path and not exists:
            continue
        info = item.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise ValueError("journal paths cannot traverse symlinks or reparse points")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing dedicated parent directory required")
        if item == path and (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_DATABASE_BYTES
        ):
            raise ValueError("bounded unaliased regular research journal required")
    return path


def implementation_binding() -> str:
    """Exact installed research/native contract bytes, not package version labels."""
    sources = {}
    for name, root in (
        ("adaptive_replay", Path(__file__).parent),
        ("kairos_strategy", Path(kairos_strategy.__file__).parent),
        ("kairos_core", Path(kairos_core.__file__).parent),
    ):
        paths = sorted(root.rglob("*.py"))
        if not paths or len(paths) > 512:
            raise ValueError("bounded readable installed source identity required")
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError("unaliased implementation sources required")
            sources[f"{name}/{path.relative_to(root).as_posix()}"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    encoded = canonical(
        {
            "schema": SCHEMA,
            "sources": sources,
            "mechanics": MECHANICS,
            "planning": asdict(DEFAULT_CONFIG),
            "capabilities": {k: sorted(s.value for s in sides) for k, sides in CAPABILITIES.items()},
        }
    )
    _load(encoded)
    return encoded


class HypothesisJournal:
    """Opt-in evidence only. Never delete/recreate a missing or invalid journal.

    new_event=False is redelivery of an already recorded receipt, not another
    candidate publication. No automatic repair, migration, retry or reset.
    """

    def __init__(self, path: Path, seal: JournalSeal):
        if type(seal) is not JournalSeal:
            raise ValueError("caller-retained frozen seal required")
        self.path = Path(path).absolute()
        self._seal_json = _encode(seal)
        self._seal = _seal(self._seal_json)
        self._implementation_json = implementation_binding()
        self._genesis = digest(
            {
                "schema": SCHEMA,
                "seal": _load(self._seal_json),
                "implementation": _load(self._implementation_json),
            }
        )

    @classmethod
    def create(cls, path: Path, seal: JournalSeal) -> HypothesisJournal:
        instance = cls(_regular_path(path, exists=False), seal)
        # Exclusive reservation; interrupted/failed creation stays an invalid
        # preserved attempt rather than being automatically removed or reused.
        with instance.path.open("xb"):
            pass
        with instance._transaction(create=True) as connection:
            for sql in DDL.values():
                connection.execute(sql)
            connection.execute("PRAGMA user_version=1")
            connection.execute(
                "INSERT INTO meta VALUES(1,?,?,?,?,?)",
                (SCHEMA, instance._seal_json, instance._implementation_json, 0, instance._genesis),
            )
            instance._audit(connection)
        return instance

    @classmethod
    def open(cls, path: Path, seal: JournalSeal) -> HypothesisJournal:
        instance = cls(_regular_path(path, exists=True), seal)
        instance.snapshot()
        return instance

    @contextmanager
    def _transaction(self, *, create: bool = False):
        _regular_path(self.path, exists=True)
        if implementation_binding() != self._implementation_json:
            raise ValueError("installed implementation or planning identity changed")
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if create:
                connection.execute("PRAGMA journal_mode=DELETE")
            elif connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("unsupported research journal mode; no automatic repair")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _check_plan(self, arm_id: str, plan: HypothesisPlan) -> None:
        arms = {arm.arm_id: arm.policy for arm in self._seal.arms}
        if (
            arm_id not in arms
            or plan.policy != arms[arm_id]
            or plan.created_ms < self._seal.sealed_ms
            or plan.source_set_sha256 != self._seal.source_set_sha256
        ):
            raise ValueError("plan differs from frozen journal arm/source/seal")

    def _audit(self, connection: sqlite3.Connection) -> JournalSnapshot:
        objects = connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
        expected = {name: ("table", sql) for name, sql in DDL.items()}
        expected.update(
            {"sqlite_autoindex_parents_1": ("index", None), "sqlite_autoindex_events_1": ("index", None)}
        )
        if {r["name"]: (r["type"], r["sql"]) for r in objects} != expected or (
            connection.execute("PRAGMA user_version").fetchone()[0] != 1
        ):
            raise ValueError("exact research schema required; no migrations")
        meta = connection.execute("SELECT * FROM meta LIMIT 2").fetchall()
        if len(meta) != 1 or tuple(meta[0])[:4] != (1, SCHEMA, self._seal_json, self._implementation_json):
            raise ValueError("frozen journal seal or implementation binding conflict")
        parents = connection.execute("SELECT * FROM parents ORDER BY arm_id,parent_id LIMIT 129").fetchall()
        if len(parents) > self._seal.maximum_parents:
            raise ValueError("journal parent capacity exceeded")
        groups, bases = {}, {}
        for row in parents:
            plan = _plan(row["plan_json"])
            self._check_plan(row["arm_id"], plan)
            key = row["arm_id"], row["parent_id"]
            if plan.template.intent_id != row["parent_id"]:
                raise ValueError("journal parent identity conflict")
            base = _load(row["plan_json"])
            base.pop("policy")
            if row["parent_id"] in bases and bases[row["parent_id"]] != base:
                raise ValueError("matched arms cannot alter original hypothesis evidence")
            bases[row["parent_id"]] = base
            groups[key] = (plan, [], [])
        maximum_events = self._seal.maximum_parents * (MAX_OBSERVATIONS + 1)
        events = connection.execute(
            "SELECT * FROM events ORDER BY sequence LIMIT ?", (maximum_events + 1,)
        ).fetchall()
        if len(events) > maximum_events or meta[0]["event_count"] != len(events):
            raise ValueError("bounded journal count or truncation conflict")
        observed_parents = set()
        for row in events:
            key = row["arm_id"], row["parent_id"]
            if key not in groups:
                raise ValueError("event has no exact registered parent")
            plan, observations, rows = groups[key]
            if row["observation_json"] is None:
                if rows or row["minute_ms"] is not None or row["parent_id"] in observed_parents:
                    raise ValueError("duplicate or outcome-dependent late arm enrolment")
            else:
                if not rows or len(observations) >= MAX_OBSERVATIONS:
                    raise ValueError("observation without registration or beyond bound")
                observation = _observation(row["observation_json"])
                if row["minute_ms"] != observation.market.candle.open_time_ms or any(
                    o.market.candle.open_time_ms == row["minute_ms"] for o in observations
                ):
                    raise ValueError("observation minute key or duplicate conflict")
                observations.append(observation)
                observed_parents.add(row["parent_id"])
            rows.append(row)
        receipts = {}
        for key, (plan, observations, rows) in groups.items():
            if not rows:
                raise ValueError("registered parent lost its initial receipt")
            evaluations = evaluate_hypothesis(plan, tuple(observations))
            if len(evaluations) != len(rows):
                raise ValueError("stored fold cannot collapse or discard observations")
            for row, evaluation in zip(rows, evaluations, strict=True):
                if _encode(evaluation) != row["evaluation_json"]:
                    raise ValueError("stored evaluation differs from exact native replay")
                receipts[row["sequence"]] = JournalReceipt(
                    False, row["sequence"], row["chain_sha256"], *key, evaluation
                )
        previous = self._genesis
        for sequence, row in enumerate(events, 1):
            if row["sequence"] != sequence or row["previous_sha256"] != previous:
                raise ValueError("journal global sequence or hash-link conflict")
            if self._event_sha(row, groups[row["arm_id"], row["parent_id"]][0]) != row["chain_sha256"]:
                raise ValueError("journal event bytes or chain digest conflict")
            previous = row["chain_sha256"]
        if previous != meta[0]["head_sha256"]:
            raise ValueError("journal head or truncation conflict")
        return JournalSnapshot(
            digest(_load(self._seal_json)),
            previous,
            len(events),
            tuple(
                RecordedHypothesis(arm, plan, tuple(obs), tuple(receipts[r["sequence"]] for r in rows))
                for (arm, _), (plan, obs, rows) in sorted(groups.items())
            ),
        )

    def _event_sha(self, row: Any, plan: HypothesisPlan) -> str:
        return digest(
            {
                "seal_sha256": digest(_load(self._seal_json)),
                "sequence": row["sequence"],
                "arm_id": row["arm_id"],
                "parent_id": row["parent_id"],
                "plan_sha256": digest(asdict(plan)),
                "minute_ms": row["minute_ms"],
                "observation": None if row["observation_json"] is None else _load(row["observation_json"]),
                "evaluation": _load(row["evaluation_json"]),
                "previous_sha256": row["previous_sha256"],
            }
        )

    def _append_event(self, connection, snapshot, arm_id, plan, observation, evaluation):
        row = {
            "sequence": snapshot.event_count + 1,
            "arm_id": arm_id,
            "parent_id": plan.template.intent_id,
            "minute_ms": None if observation is None else observation.market.candle.open_time_ms,
            "observation_json": None if observation is None else _encode(observation),
            "evaluation_json": _encode(evaluation),
            "previous_sha256": snapshot.head_sha256,
        }
        row["chain_sha256"] = self._event_sha(row, plan)
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?)", tuple(row.values()))
        connection.execute(
            "UPDATE meta SET event_count=?,head_sha256=? WHERE id=1", (row["sequence"], row["chain_sha256"])
        )
        return JournalReceipt(
            True, row["sequence"], row["chain_sha256"], arm_id, plan.template.intent_id, evaluation
        )

    def snapshot(self) -> JournalSnapshot:
        with self._transaction() as connection:
            return self._audit(connection)

    def register(self, arm_id: str, plan: HypothesisPlan) -> JournalReceipt:
        _name(arm_id)
        if type(plan) is not HypothesisPlan:
            raise ValueError("typed original hypothesis required")
        plan = _plan(_encode(plan))
        self._check_plan(arm_id, plan)
        with self._transaction() as connection:
            snapshot = self._audit(connection)
            for existing in snapshot.hypotheses:
                if existing.plan.template.intent_id != plan.template.intent_id:
                    continue
                if existing.arm_id == arm_id:
                    if _encode(existing.plan) != _encode(plan):
                        raise ValueError("parent cannot be resealed or rescued under changed plan")
                    return existing.receipts[0]
                old, new = _load(_encode(existing.plan)), _load(_encode(plan))
                old.pop("policy")
                new.pop("policy")
                if old != new or existing.observations:
                    raise ValueError("matched arm must enrol exact same parent before any observation")
            if len(snapshot.hypotheses) >= self._seal.maximum_parents:
                raise ValueError("journal parent capacity exhausted")
            connection.execute(
                "INSERT INTO parents VALUES(?,?,?)", (arm_id, plan.template.intent_id, _encode(plan))
            )
            receipt = self._append_event(
                connection, snapshot, arm_id, plan, None, evaluate_hypothesis(plan, ())[-1]
            )
            self._audit(connection)
            return receipt

    def append(self, arm_id: str, parent_id: str, observation: HypothesisObservation) -> JournalReceipt:
        _name(arm_id)
        _sha(parent_id)
        if type(observation) is not HypothesisObservation:
            raise ValueError("typed exact hypothesis observation required")
        observation = _observation(_encode(observation))
        with self._transaction() as connection:
            snapshot = self._audit(connection)
            existing = next(
                (
                    h
                    for h in snapshot.hypotheses
                    if h.arm_id == arm_id and h.plan.template.intent_id == parent_id
                ),
                None,
            )
            if existing is None:
                raise ValueError("exact pre-registered hypothesis required")
            for prior, receipt in zip(existing.observations, existing.receipts[1:], strict=True):
                if prior.market.candle.open_time_ms == observation.market.candle.open_time_ms:
                    if _encode(prior) != _encode(observation):
                        raise ValueError("conflicting redelivery cannot replace original quote/review")
                    return replace(receipt, new_event=False)
            if len(existing.observations) >= MAX_OBSERVATIONS:
                raise ValueError("journal observation capacity exhausted")
            result = evaluate_hypothesis(existing.plan, (*existing.observations, observation))[-1]
            receipt = self._append_event(connection, snapshot, arm_id, existing.plan, observation, result)
            self._audit(connection)
            return receipt
