"""Durable, bounded research evidence for the distinct prospective V3 fold.

This module is deliberately additive: it never imports or calls the V2 plan,
fold, journal, migration, or serializer. A frozen pre-cut seal fixes the
experiment arms, policies, and source profile. Each actual parent materializes
only after its origin cut, is enrolled identically across those arms, and must
be complete before the first observation. This SQLite file is a local
research fixture, not an outbox, runtime authority, or source authenticator.
Source-set identity and receipt bytes are caller-attested commitments only:
they prove neither source authenticity nor exhaustive market/news coverage.
The exact V3 fold's missing-source `UNAVAILABLE` result is persisted as-is.
Matched market/quote bytes are shared, not arm-specific review identities or
decision clocks. Without a caller-retained checkpoint, a self-consistent
older database copy cannot be distinguished from the latest committed state.
"""

from __future__ import annotations

import hashlib
import sqlite3
import stat
import threading
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
from .hypothesis_v3 import (
    MECHANICS,
    POLICY_ID,
    CreationAssessment,
    EntryQuote,
    HypothesisEvaluation,
    HypothesisObservation,
    HypothesisPlan,
    HypothesisPolicy,
    evaluate_hypothesis,
)
from .scenarios import (
    CAPABILITIES,
    MAX_OBSERVATIONS,
    ScenarioEvidence,
    ScenarioObservation,
    ScenarioReview,
)

SCHEMA = "kairos.development.hypothesis-journal.v3"
MAX_JSON_BYTES = 65_536
MAX_DATABASE_BYTES = 512 * 1024 * 1024
MAX_PARENTS = 128
MAX_ARMS = 8
DDL = {
    "meta": (
        "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), schema_id TEXT NOT NULL, "
        "seal_json TEXT NOT NULL, implementation_json TEXT NOT NULL, event_count INTEGER NOT NULL, "
        "head_sha256 TEXT NOT NULL)"
    ),
    "parents": (
        "CREATE TABLE parents (arm_id TEXT NOT NULL, parent_id TEXT NOT NULL, "
        "plan_json TEXT NOT NULL, PRIMARY KEY(arm_id,parent_id))"
    ),
    "events": (
        "CREATE TABLE events (sequence INTEGER PRIMARY KEY, arm_id TEXT NOT NULL, "
        "parent_id TEXT NOT NULL, minute_ms INTEGER, observation_json TEXT, review_receipt_json TEXT, "
        "evaluation_json TEXT NOT NULL, previous_sha256 TEXT NOT NULL, chain_sha256 TEXT NOT NULL, "
        "UNIQUE(arm_id,parent_id,minute_ms), FOREIGN KEY(arm_id,parent_id) "
        "REFERENCES parents(arm_id,parent_id))"
    ),
}


@dataclass(frozen=True)
class JournalArmV3:
    arm_id: str
    policy: HypothesisPolicy
    review_model_config_sha256: str | None = None

    def __post_init__(self) -> None:
        _name(self.arm_id)
        if type(self.policy) is not HypothesisPolicy:
            raise ValueError("typed frozen V3 arm policy required")
        HypothesisPolicy(**asdict(self.policy))
        if self.policy.require_review:
            _sha(self.review_model_config_sha256)
        elif self.review_model_config_sha256 is not None:
            raise ValueError("no-review arm cannot enroll a model review configuration")


@dataclass(frozen=True)
class JournalSealV3:
    experiment_id: str
    sealed_ms: int
    source_set_sha256: str
    arms: tuple[JournalArmV3, ...]
    maximum_parents: int

    def __post_init__(self) -> None:
        _name(self.experiment_id)
        _clock(self.sealed_ms)
        _sha(self.source_set_sha256)
        if (
            type(self.arms) is not tuple
            or not 1 <= len(self.arms) <= MAX_ARMS
            or any(type(arm) is not JournalArmV3 for arm in self.arms)
            or tuple(a.arm_id for a in self.arms) != tuple(sorted({a.arm_id for a in self.arms}))
            or type(self.maximum_parents) is not int
            or not 1 <= self.maximum_parents <= MAX_PARENTS
        ):
            raise ValueError("explicit bounded immutable V3 arm and parent roster required")
        for arm in self.arms:
            JournalArmV3(**asdict(arm) | {"policy": arm.policy})
            if arm.policy.sealed_ms > self.sealed_ms:
                raise ValueError("V3 arm policy must be fixed no later than the pre-cut seal")


@dataclass(frozen=True)
class ArmReviewReceiptV3:
    """Actual arm completion against supplied inputs, never an ID/time rewrite.

    A missing review records an explicit decision clock with no invented call.
    Model expense and original response authentication belong to the separate
    admitted provider ledger, not to this caller-attested research receipt.
    """

    arm_id: str
    observed_ms: int
    shared_observed_ms: int
    review: ScenarioReview | None = None
    model_config_sha256: str | None = None
    actual_requested_ms: int | None = None
    actual_captured_ms: int | None = None

    def __post_init__(self) -> None:
        _name(self.arm_id)
        _clock(self.observed_ms)
        _clock(self.shared_observed_ms)
        if self.observed_ms < self.shared_observed_ms:
            raise ValueError("arm decision cannot predate shared observation")
        if self.review is None:
            if any(
                value is not None
                for value in (self.model_config_sha256, self.actual_requested_ms, self.actual_captured_ms)
            ):
                raise ValueError("missing review cannot invent a model call receipt")
        else:
            if type(self.review) is not ScenarioReview:
                raise ValueError("exact typed arm review receipt required")
            ScenarioReview(**asdict(self.review))
            _sha(self.model_config_sha256)
            _clock(self.actual_requested_ms)
            _clock(self.actual_captured_ms)
            if (
                not self.actual_requested_ms
                <= self.review.completed_ms
                <= (self.actual_captured_ms)
                <= self.observed_ms
            ):
                raise ValueError("ordered actual request/completion/capture/decision clocks required")


@dataclass(frozen=True)
class MatchedObservationV3:
    observation: HypothesisObservation
    arms: tuple[ArmReviewReceiptV3, ...]

    def __post_init__(self) -> None:
        if type(self.observation) is not HypothesisObservation:
            raise ValueError("typed shared V3 market/quote observation required")
        HypothesisObservation(self.observation.market, self.observation.quote)
        if self.observation.market.review is not None:
            raise ValueError("shared observation cannot impersonate an arm-bound review")
        if any(e.captured_ms > self.observation.market.observed_ms for e in self.observation.market.sources):
            raise ValueError("shared source denominator cannot contain later captured knowledge")
        if self.observation.quote is not None and (
            self.observation.quote.captured_ms > self.observation.market.observed_ms
        ):
            raise ValueError("shared quote cannot be captured after shared availability")
        if (
            type(self.arms) is not tuple
            or not 1 <= len(self.arms) <= MAX_ARMS
            or any(type(arm) is not ArmReviewReceiptV3 for arm in self.arms)
            or tuple(arm.arm_id for arm in self.arms) != tuple(sorted({arm.arm_id for arm in self.arms}))
        ):
            raise ValueError("exact canonical matched arm completion roster required")
        for arm in self.arms:
            ArmReviewReceiptV3(**asdict(arm) | {"review": arm.review})
            if arm.shared_observed_ms != self.observation.market.observed_ms:
                raise ValueError("matched arm must retain exact shared observation clock")
            if arm.review is not None and arm.actual_requested_ms < self.observation.market.observed_ms:
                raise ValueError("review request cannot predate supplied shared market/quote inputs")


@dataclass(frozen=True)
class JournalCheckpointV3:
    seal_sha256: str
    sequence: int
    head_sha256: str

    def __post_init__(self) -> None:
        _sha(self.seal_sha256)
        _clock(self.sequence)
        _sha(self.head_sha256)


@dataclass(frozen=True)
class JournalReceiptV3:
    new_event: bool
    sequence: int
    chain_sha256: str
    arm_id: str
    parent_id: str
    evaluation: HypothesisEvaluation


@dataclass(frozen=True)
class RecordedHypothesisV3:
    arm_id: str
    plan: HypothesisPlan
    observations: tuple[HypothesisObservation, ...]
    receipts: tuple[JournalReceiptV3, ...]
    review_receipts: tuple[ArmReviewReceiptV3, ...]


@dataclass(frozen=True)
class JournalSnapshotV3:
    seal_sha256: str
    head_sha256: str
    event_count: int
    hypotheses: tuple[RecordedHypothesisV3, ...]

    @property
    def checkpoint(self) -> JournalCheckpointV3:
        return JournalCheckpointV3(self.seal_sha256, self.event_count, self.head_sha256)


def _object(cls: type, raw: Any) -> dict[str, Any]:
    expected = {field.name for field in fields(cls) if field.init}
    if type(raw) is not dict or set(raw) != expected:
        raise ValueError("exact V3 journal contract fields required")
    return dict(raw)


def _load(encoded: str) -> Any:
    if type(encoded) is not str or len(encoded.encode("utf-8")) > MAX_JSON_BYTES:
        raise ValueError("bounded canonical V3 journal JSON required")
    value = _json(encoded)  # duplicate keys and non-finite values are rejected
    if canonical(value) != encoded:
        raise ValueError("V3 journal JSON cannot normalize or discard bytes")
    return value


def _encode(value: Any) -> str:
    encoded = canonical(asdict(value))
    _load(encoded)
    return encoded


def _pairs(raw: Any) -> tuple[tuple[str, str], ...]:
    if type(raw) is not list or any(
        type(pair) is not list or len(pair) != 2 or any(type(x) is not str for x in pair) for pair in raw
    ):
        raise ValueError("exact V3 JSON string pairs required")
    return tuple(tuple(pair) for pair in raw)


def _intent(raw: Any) -> SleeveIntent:
    expected = {field.name for field in fields(SleeveIntent)}
    if type(raw) is not dict or set(raw) != expected:
        raise ValueError("exact full V3 parent/candidate fields required")
    values = dict(raw)
    identity = values.pop("intent_id")
    values["side"] = Side(values["side"])
    values["metadata"] = _pairs(values["metadata"])
    values["exit_plan"] = ExitPlan(**_object(ExitPlan, values["exit_plan"]))
    result = SleeveIntent(**values)
    if result.intent_id != identity or canonical(asdict(result)) != canonical(raw):
        raise ValueError("stored V3 parent identity or unchanged full protection conflict")
    return result


def _evidence(raw: Any) -> tuple[ScenarioEvidence, ...]:
    if type(raw) is not list or len(raw) > 32:
        raise ValueError("bounded exact V3 evidence list required")
    return tuple(ScenarioEvidence(**_object(ScenarioEvidence, value)) for value in raw)


def _plan(encoded: str) -> HypothesisPlan:
    values = _object(HypothesisPlan, _load(encoded))
    values["template"] = _intent(values["template"])
    values["policy"] = HypothesisPolicy(**_object(HypothesisPolicy, values["policy"]))
    values["anchor"] = Candle(**_object(Candle, values["anchor"]))
    values["creation_evidence"] = _evidence(values["creation_evidence"])
    values["required_sources"] = _pairs(values["required_sources"])
    if values["creation_assessment"] is not None:
        values["creation_assessment"] = CreationAssessment(
            **_object(CreationAssessment, values["creation_assessment"])
        )
    result = HypothesisPlan(**values)
    if _encode(result) != encoded:
        raise ValueError("stored V3 plan must round-trip without normalization")
    return result


def _observation(encoded: str) -> HypothesisObservation:
    values = _object(HypothesisObservation, _load(encoded))
    market = _object(ScenarioObservation, values["market"])
    market["candle"] = Candle(**_object(Candle, market["candle"]))
    market["sources"] = _evidence(market["sources"])
    if market["review"] is not None:
        review = _object(ScenarioReview, market["review"])
        review["side"] = Side(review["side"])
        market["review"] = ScenarioReview(**review)
    values["market"] = ScenarioObservation(**market)
    if values["quote"] is not None:
        values["quote"] = EntryQuote(**_object(EntryQuote, values["quote"]))
    result = HypothesisObservation(**values)
    if _encode(result) != encoded:
        raise ValueError("stored V3 observation must round-trip without normalization")
    return result


def _review_receipt(encoded: str) -> ArmReviewReceiptV3:
    values = _object(ArmReviewReceiptV3, _load(encoded))
    if values["review"] is not None:
        review = _object(ScenarioReview, values["review"])
        review["side"] = Side(review["side"])
        values["review"] = ScenarioReview(**review)
    result = ArmReviewReceiptV3(**values)
    if _encode(result) != encoded:
        raise ValueError("exact arm review receipt must round-trip without normalization")
    return result


def _shared_observation(
    observation: HypothesisObservation, receipt: ArmReviewReceiptV3
) -> HypothesisObservation:
    return replace(
        observation,
        market=replace(observation.market, observed_ms=receipt.shared_observed_ms, review=None),
    )


def _plan_projection(plan: HypothesisPlan) -> Any:
    values = _load(_encode(plan))
    values.pop("policy")
    return values


def _evaluation(encoded: str) -> HypothesisEvaluation:
    values = _object(HypothesisEvaluation, _load(encoded))
    if values["candidate"] is not None:
        values["candidate"] = _intent(values["candidate"])
    result = HypothesisEvaluation(**values)
    if _encode(result) != encoded:
        raise ValueError("stored V3 evaluation must round-trip without normalization")
    return result


def _seal(encoded: str) -> JournalSealV3:
    values = _object(JournalSealV3, _load(encoded))
    if type(values["arms"]) is not list:
        raise ValueError("exact V3 arm roster required")
    arms = []
    for value in values["arms"]:
        arm = _object(JournalArmV3, value)
        arm["policy"] = HypothesisPolicy(**_object(HypothesisPolicy, arm["policy"]))
        arms.append(JournalArmV3(**arm))
    values["arms"] = tuple(arms)
    result = JournalSealV3(**values)
    if _encode(result) != encoded:
        raise ValueError("exact frozen V3 seal required")
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
            raise ValueError("V3 journal paths cannot traverse symlinks or reparse points")
        if item != path and not stat.S_ISDIR(info.st_mode):
            raise ValueError("existing dedicated parent directory required")
        if item == path and (
            not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > MAX_DATABASE_BYTES
        ):
            raise ValueError("bounded unaliased regular V3 research journal required")
    return path


def implementation_binding_v3() -> str:
    """V3 mechanics identity with conservative whole-installed-package drift checks."""
    sources: dict[str, str] = {}
    for name, root in (
        ("adaptive_replay", Path(__file__).parent),
        ("kairos_strategy", Path(kairos_strategy.__file__).parent),
        ("kairos_core", Path(kairos_core.__file__).parent),
    ):
        paths = sorted(root.rglob("*.py"))
        if not paths or len(paths) > 512:
            raise ValueError("bounded readable V3 implementation identity required")
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise ValueError("unaliased V3 implementation sources required")
            sources[f"{name}/{path.relative_to(root).as_posix()}"] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
    encoded = canonical(
        {
            "schema": SCHEMA,
            "sources": sources,
            "policy_id": POLICY_ID,
            "mechanics": MECHANICS,
            "planning": asdict(DEFAULT_CONFIG),
            "capabilities": {k: sorted(s.value for s in sides) for k, sides in CAPABILITIES.items()},
        }
    )
    _load(encoded)
    return encoded


class HypothesisJournalV3:
    """Crash-safe local evidence; no repair, migration, retry or authority promotion."""

    def __init__(self, path: Path, seal: JournalSealV3):
        if type(seal) is not JournalSealV3:
            raise ValueError("caller-retained frozen pre-cut V3 seal required")
        self.path = Path(path).absolute()
        self._seal_json = _encode(seal)
        self._seal = _seal(self._seal_json)
        self._implementation_json = implementation_binding_v3()
        self._genesis = digest(
            {
                "schema": SCHEMA,
                "seal": _load(self._seal_json),
                "implementation": _load(self._implementation_json),
            }
        )
        self._minimum_checkpoint = JournalCheckpointV3(digest(_load(self._seal_json)), 0, self._genesis)
        self._operation_lock = threading.RLock()

    @classmethod
    def create(cls, path: Path, seal: JournalSealV3) -> HypothesisJournalV3:
        instance = cls(_regular_path(path, exists=False), seal)
        with instance.path.open("xb"):
            pass  # exclusive reservation; interrupted create is preserved and rejected
        with instance._transaction(create=True) as connection:
            for sql in DDL.values():
                connection.execute(sql)
            connection.execute("PRAGMA user_version=3")
            connection.execute(
                "INSERT INTO meta VALUES(1,?,?,?,?,?)",
                (SCHEMA, instance._seal_json, instance._implementation_json, 0, instance._genesis),
            )
            instance._audit(connection)
        return instance

    @classmethod
    def open(
        cls, path: Path, seal: JournalSealV3, *, minimum_checkpoint: JournalCheckpointV3
    ) -> HypothesisJournalV3:
        instance = cls(_regular_path(path, exists=True), seal)
        if type(minimum_checkpoint) is not JournalCheckpointV3:
            raise ValueError("caller-retained typed V3 restart checkpoint required")
        JournalCheckpointV3(**asdict(minimum_checkpoint))
        if minimum_checkpoint.seal_sha256 != instance._minimum_checkpoint.seal_sha256:
            raise ValueError("frozen V3 checkpoint/seal identity conflict")
        instance._minimum_checkpoint = minimum_checkpoint
        instance.snapshot()
        return instance

    @contextmanager
    def _transaction(self, *, create: bool = False):
        # Preserve checkpoint handoff after SQLite releases its writer lock.
        # A slower older transaction must not downgrade the same instance.
        with self._operation_lock, self._locked_transaction(create=create) as connection:
            yield connection

    @contextmanager
    def _locked_transaction(self, *, create: bool = False):
        _regular_path(self.path, exists=True)
        if implementation_binding_v3() != self._implementation_json:
            raise ValueError("installed V3 implementation or planning identity changed")
        connection = sqlite3.connect(
            self.path.as_uri() + "?mode=rw", uri=True, timeout=5, isolation_level=None
        )
        connection.row_factory = sqlite3.Row
        try:
            connection.execute("PRAGMA foreign_keys=ON")
            if create:
                connection.execute("PRAGMA journal_mode=DELETE")
            elif connection.execute("PRAGMA journal_mode").fetchone()[0] != "delete":
                raise ValueError("unsupported V3 journal mode; no automatic repair")
            connection.execute("PRAGMA synchronous=FULL")
            page_size = connection.execute("PRAGMA page_size").fetchone()[0]
            connection.execute(f"PRAGMA max_page_count={MAX_DATABASE_BYTES // page_size}")
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            accepted = self._audit(connection)
            if connection.execute("PRAGMA page_count").fetchone()[0] * page_size > MAX_DATABASE_BYTES:
                raise ValueError("V3 journal byte capacity exceeded before commit")
            connection.commit()
            self._minimum_checkpoint = accepted.checkpoint
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
            or plan.source_set_sha256 != self._seal.source_set_sha256
            or plan.origin_cut_ms < self._seal.sealed_ms
        ):
            raise ValueError("V3 plan conflicts with pre-cut arm/policy/source seal")

    def _check_review(self, receipt: ArmReviewReceiptV3, shared: HypothesisObservation) -> None:
        arm = next((arm for arm in self._seal.arms if arm.arm_id == receipt.arm_id), None)
        if arm is None:
            raise ValueError("arm completion is outside frozen V3 roster")
        MatchedObservationV3(shared, (receipt,))
        if not arm.policy.require_review:
            if receipt.review is not None or receipt.observed_ms != receipt.shared_observed_ms:
                raise ValueError("no-review arm cannot acquire review or inherit model latency")
        elif receipt.review is not None and (receipt.model_config_sha256 != arm.review_model_config_sha256):
            raise ValueError("review model configuration differs from pre-cut V3 arm seal")

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
                "review_receipt": None
                if row["review_receipt_json"] is None
                else _load(row["review_receipt_json"]),
                "evaluation": _load(row["evaluation_json"]),
                "previous_sha256": row["previous_sha256"],
            }
        )

    def _audit(self, connection: sqlite3.Connection) -> JournalSnapshotV3:
        objects = connection.execute("SELECT type,name,sql FROM sqlite_master ORDER BY name").fetchall()
        expected = {name: ("table", sql) for name, sql in DDL.items()}
        expected.update(
            {"sqlite_autoindex_parents_1": ("index", None), "sqlite_autoindex_events_1": ("index", None)}
        )
        if {r["name"]: (r["type"], r["sql"]) for r in objects} != expected or connection.execute(
            "PRAGMA user_version"
        ).fetchone()[0] != 3:
            raise ValueError("exact V3 research schema required; no migrations")
        meta = connection.execute("SELECT * FROM meta LIMIT 2").fetchall()
        if len(meta) != 1 or tuple(meta[0])[:4] != (1, SCHEMA, self._seal_json, self._implementation_json):
            raise ValueError("frozen V3 enrollment/seal or implementation conflict")
        parents = connection.execute(
            "SELECT * FROM parents ORDER BY arm_id,parent_id LIMIT ?",
            (self._seal.maximum_parents * MAX_ARMS + 1,),
        ).fetchall()
        if len(parents) > self._seal.maximum_parents * MAX_ARMS:
            raise ValueError("V3 registered parent capacity exceeded")
        if len({row["parent_id"] for row in parents}) > self._seal.maximum_parents:
            raise ValueError("V3 distinct parent capacity exceeded")
        groups: dict[tuple[str, str], tuple[HypothesisPlan, list[HypothesisObservation], list[Any]]] = {}
        for row in parents:
            plan = _plan(row["plan_json"])
            self._check_plan(row["arm_id"], plan)
            if row["parent_id"] != plan.template.intent_id:
                raise ValueError("V3 parent identity conflict")
            key = row["arm_id"], row["parent_id"]
            groups[key] = (plan, [], [])
        max_events = self._seal.maximum_parents * MAX_ARMS * (MAX_OBSERVATIONS + 1)
        events = connection.execute(
            "SELECT * FROM events ORDER BY sequence LIMIT ?", (max_events + 1,)
        ).fetchall()
        if len(events) > max_events or meta[0]["event_count"] != len(events):
            raise ValueError("bounded V3 event count or truncation conflict")
        for row in events:
            key = row["arm_id"], row["parent_id"]
            if key not in groups:
                raise ValueError("V3 event has no registered parent")
            plan, observations, rows = groups[key]
            if row["observation_json"] is None:
                if rows or row["minute_ms"] is not None or row["review_receipt_json"] is not None:
                    raise ValueError("duplicate V3 initial receipt")
            else:
                if not rows or len(observations) >= MAX_OBSERVATIONS:
                    raise ValueError("V3 observation without initial receipt or beyond bound")
                observation = _observation(row["observation_json"])
                receipt = _review_receipt(row["review_receipt_json"])
                if (
                    receipt.arm_id != row["arm_id"]
                    or receipt.observed_ms != observation.market.observed_ms
                    or receipt.review != observation.market.review
                ):
                    raise ValueError("V3 stored arm review/decision receipt conflict")
                self._check_review(receipt, _shared_observation(observation, receipt))
                if row["minute_ms"] != observation.market.candle.open_time_ms or any(
                    o.market.candle.open_time_ms == row["minute_ms"] for o in observations
                ):
                    raise ValueError("duplicate or conflicting V3 observation minute")
                observations.append(observation)
            rows.append(row)
        by_parent: dict[str, list[tuple[str, HypothesisPlan, list[HypothesisObservation], list[Any]]]] = {}
        for (arm_id, parent_id), (plan, observations, rows) in groups.items():
            by_parent.setdefault(parent_id, []).append((arm_id, plan, observations, rows))
        expected_arms = {arm.arm_id for arm in self._seal.arms}
        for streams in by_parent.values():
            reference_plan = _plan_projection(streams[0][1])
            if any(_plan_projection(plan) != reference_plan for _, plan, _, _ in streams[1:]):
                raise ValueError("V3 peer plans must preserve exact parent, anchor and full ExitPlan")
            if not any(stream for _, _, stream, _ in streams):
                continue
            if {arm_id for arm_id, _, _, _ in streams} != expected_arms:
                raise ValueError("V3 matched observations require the full sealed arm roster")
            lengths = {len(stream) for _, _, stream, _ in streams}
            if len(lengths) != 1:
                raise ValueError("V3 matched arms cannot have different observation coverage")
            if max(rows[0]["sequence"] for _, _, _, rows in streams) >= min(
                rows[1]["sequence"] for _, _, _, rows in streams
            ):
                raise ValueError("every V3 arm must enroll before the first matched observation")
            for index in range(next(iter(lengths))):
                shared = []
                sequences = []
                for arm_id, _, observations, rows in streams:
                    row = rows[index + 1]
                    receipt = _review_receipt(row["review_receipt_json"])
                    shared.append(_encode(_shared_observation(observations[index], receipt)))
                    sequences.append((row["sequence"], arm_id))
                if len(set(shared)) != 1:
                    raise ValueError("V3 matched arms must preserve identical shared market/quote receipts")
                ordered = sorted(sequences)
                if [arm for _, arm in ordered] != sorted(expected_arms) or [
                    seq for seq, _ in ordered
                ] != list(range(ordered[0][0], ordered[0][0] + len(ordered))):
                    raise ValueError("V3 matched arm observation must be a complete atomic sequence block")
        receipts: dict[int, JournalReceiptV3] = {}
        for key, (plan, observations, rows) in groups.items():
            if not rows:
                raise ValueError("registered V3 parent lost its initial receipt")
            evaluations = evaluate_hypothesis(plan, tuple(observations))
            if len(evaluations) != len(rows):
                raise ValueError("stored V3 fold cannot collapse or discard observations")
            for row, evaluation in zip(rows, evaluations, strict=True):
                if (
                    _encode(evaluation) != row["evaluation_json"]
                    or _evaluation(row["evaluation_json"]) != evaluation
                ):
                    raise ValueError("stored V3 evaluation differs from exact native V3 replay")
                receipts[row["sequence"]] = JournalReceiptV3(
                    False, row["sequence"], row["chain_sha256"], *key, evaluation
                )
        previous = self._genesis
        for sequence, row in enumerate(events, 1):
            if row["sequence"] != sequence or row["previous_sha256"] != previous:
                raise ValueError("V3 global sequence or hash-link conflict")
            if self._event_sha(row, groups[row["arm_id"], row["parent_id"]][0]) != row["chain_sha256"]:
                raise ValueError("V3 event bytes or chain digest conflict")
            previous = row["chain_sha256"]
        if previous != meta[0]["head_sha256"]:
            raise ValueError("V3 head or truncation conflict")
        checkpoint = self._minimum_checkpoint
        if (
            len(events) < checkpoint.sequence
            or (
                self._genesis if checkpoint.sequence == 0 else events[checkpoint.sequence - 1]["chain_sha256"]
            )
            != checkpoint.head_sha256
        ):
            raise ValueError("V3 journal rolled back or diverged from caller-retained checkpoint")
        return JournalSnapshotV3(
            digest(_load(self._seal_json)),
            previous,
            len(events),
            tuple(
                RecordedHypothesisV3(
                    arm,
                    plan,
                    tuple(obs),
                    tuple(receipts[row["sequence"]] for row in rows),
                    tuple(_review_receipt(row["review_receipt_json"]) for row in rows[1:]),
                )
                for (arm, _), (plan, obs, rows) in sorted(groups.items())
            ),
        )

    def _append_event(self, connection, snapshot, arm_id, plan, observation, evaluation, review_receipt=None):
        row = {
            "sequence": snapshot.event_count + 1,
            "arm_id": arm_id,
            "parent_id": plan.template.intent_id,
            "minute_ms": None if observation is None else observation.market.candle.open_time_ms,
            "observation_json": None if observation is None else _encode(observation),
            "review_receipt_json": None if review_receipt is None else _encode(review_receipt),
            "evaluation_json": _encode(evaluation),
            "previous_sha256": snapshot.head_sha256,
        }
        row["chain_sha256"] = self._event_sha(row, plan)
        connection.execute("INSERT INTO events VALUES(?,?,?,?,?,?,?,?,?)", tuple(row.values()))
        connection.execute(
            "UPDATE meta SET event_count=?,head_sha256=? WHERE id=1", (row["sequence"], row["chain_sha256"])
        )
        return JournalReceiptV3(
            True, row["sequence"], row["chain_sha256"], arm_id, plan.template.intent_id, evaluation
        )

    def snapshot(self) -> JournalSnapshotV3:
        with self._transaction() as connection:
            return self._audit(connection)

    def register(self, arm_id: str, plan: HypothesisPlan) -> JournalReceiptV3:
        _name(arm_id)
        if type(plan) is not HypothesisPlan:
            raise ValueError("typed original V3 hypothesis required")
        plan = _plan(_encode(plan))
        self._check_plan(arm_id, plan)
        with self._transaction() as connection:
            snapshot = self._audit(connection)
            existing = next(
                (
                    h
                    for h in snapshot.hypotheses
                    if h.arm_id == arm_id and h.plan.template.intent_id == plan.template.intent_id
                ),
                None,
            )
            if existing is not None:
                if _encode(existing.plan) != _encode(plan):
                    raise ValueError("V3 parent cannot be resealed or rescued under changed plan")
                return existing.receipts[0]
            peers = [h for h in snapshot.hypotheses if h.plan.template.intent_id == plan.template.intent_id]
            if any(h.observations for h in peers):
                raise ValueError("all immutable V3 matched arms must enroll before first observation")
            new_base = _load(_encode(plan))
            new_base.pop("policy")
            for peer in peers:
                peer_base = _load(_encode(peer.plan))
                peer_base.pop("policy")
                if peer_base != new_base:
                    raise ValueError(
                        "matched V3 arms must preserve exact plan, parent, anchor and full ExitPlan"
                    )
            registered_parent_ids = {h.plan.template.intent_id for h in snapshot.hypotheses}
            if (
                plan.template.intent_id not in registered_parent_ids
                and len(registered_parent_ids) >= self._seal.maximum_parents
            ):
                raise ValueError("V3 journal parent capacity exhausted")
            connection.execute(
                "INSERT INTO parents VALUES(?,?,?)", (arm_id, plan.template.intent_id, _encode(plan))
            )
            receipt = self._append_event(
                connection, snapshot, arm_id, plan, None, evaluate_hypothesis(plan, ())[0]
            )
            self._audit(connection)
            return receipt

    def append(self, parent_id: str, batch: MatchedObservationV3) -> tuple[JournalReceiptV3, ...]:
        _sha(parent_id)
        if type(batch) is not MatchedObservationV3:
            raise ValueError("typed complete matched V3 observation required")
        MatchedObservationV3(batch.observation, batch.arms)
        observation = _observation(_encode(batch.observation))
        completions = {arm.arm_id: _review_receipt(_encode(arm)) for arm in batch.arms}
        assigned = {arm.arm_id for arm in self._seal.arms}
        if set(completions) != assigned:
            raise ValueError("matched observation must include the exact full presealed arm roster")
        arm_observations = {}
        for arm_id, receipt in completions.items():
            self._check_review(receipt, observation)
            arm_observations[arm_id] = replace(
                observation,
                market=replace(observation.market, observed_ms=receipt.observed_ms, review=receipt.review),
            )
        with self._transaction() as connection:
            snapshot = self._audit(connection)
            peers = [h for h in snapshot.hypotheses if h.plan.template.intent_id == parent_id]
            if {h.arm_id for h in peers} != assigned or any(not h.receipts for h in peers):
                raise ValueError(
                    "every preassigned V3 matched arm needs immutable initial enrollment before observations"
                )
            if not peers:
                raise ValueError("exact pre-registered V3 hypothesis required")
            prior_stream = peers[0].observations
            for index, prior in enumerate(prior_stream):
                if prior.market.candle.open_time_ms == observation.market.candle.open_time_ms:
                    if any(
                        _encode(peer.observations[index]) != _encode(arm_observations[peer.arm_id])
                        or _encode(peer.review_receipts[index]) != _encode(completions[peer.arm_id])
                        for peer in peers
                    ):
                        raise ValueError(
                            "conflicting V3 redelivery cannot replace original quote/review receipt"
                        )
                    return tuple(
                        replace(
                            next(peer for peer in peers if peer.arm_id == arm_id).receipts[index + 1],
                            new_event=False,
                        )
                        for arm_id in sorted(assigned)
                    )
            if len(prior_stream) >= MAX_OBSERVATIONS:
                raise ValueError("V3 journal observation capacity exhausted")
            working = snapshot
            appended = []
            for existing in sorted(peers, key=lambda item: item.arm_id):
                arm_observation = arm_observations[existing.arm_id]
                result = evaluate_hypothesis(existing.plan, (*existing.observations, arm_observation))[-1]
                receipt = self._append_event(
                    connection,
                    working,
                    existing.arm_id,
                    existing.plan,
                    arm_observation,
                    result,
                    completions[existing.arm_id],
                )
                appended.append(receipt)
                working = replace(working, event_count=receipt.sequence, head_sha256=receipt.chain_sha256)
            self._audit(connection)
            return tuple(appended)
