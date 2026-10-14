"""Read-only sealed-bar resolution and immutable native composition journaling."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Annotated, Literal, Self
from uuid import UUID

from kairos_core import ClosedBarEventV1, canonical_sha256
from kairos_core.contracts.base import (
    StrictKairosMessage,
    StrictValueModel,
    canonical_json_bytes,
    datetime_from_unix_ms,
)
from kairos_persistence import Database
from kairos_persistence.causal_campaign import campaign_bar_window_sha256
from kairos_persistence.database import MigrationProfile
from kairos_persistence.database_target import require_database_target_url
from kairos_persistence.repository import AuditRepository, MessageIdentityConflict
from kairos_persistence.simulation_repository import SimulationRepository
from pydantic import Field, StrictInt, StrictStr, model_validator

from .contracts import (
    NativeReviewRiskReceiptV1,
    canonical_receipt_json,
    native_review_risk_message_id,
)

_TARGET_PREFIX = "kairos_sim_test_campaign_"
_TARGET_SUFFIX = re.compile(r"[0-9a-f]{32}\Z")
_PREPARED_TARGET_TOPIC = "native.target-prepared.v1"
_PREPARED_TARGET_DOMAIN = "kairos.native-target-prepared.message.v1"
_MAX_BARS = 50_000
_PAGE_SIZE = 1_000
_SHA = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
_ID = Annotated[StrictStr, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:-]*$")]
_MS = Annotated[StrictInt, Field(ge=0, le=253_402_300_799_999)]


class PreparedNativeTargetV1(StrictKairosMessage):
    """Strict receipt that a native SIM target passed the preparation gate."""

    schema_version: Literal["1.0"] = "1.0"
    contract_version: Literal["native-target-prepared.v1"] = "native-target-prepared.v1"
    authority: Literal["PREPARATION_EVIDENCE_ONLY"] = "PREPARATION_EVIDENCE_ONLY"
    source: Literal["native-campaign-preparation"] = "native-campaign-preparation"
    message_id: _SHA | None = None
    database_name: _ID
    current_user: Literal["kairos"] = "kairos"
    server_version_num: Annotated[StrictInt, Field(ge=160_000, lt=170_000)]
    migration_profile: Literal["research-campaign"] = "research-campaign"
    storage_module_sha256: _SHA
    classification: Literal["OFFLINE_ENGINEERING_FIXTURE"] = "OFFLINE_ENGINEERING_FIXTURE"
    observed_at_ts_ms: _MS
    receipt_sha256: _SHA | None = None

    def identity_payload(self) -> dict[str, object]:
        return self.model_dump(mode="json", exclude={"receipt_sha256"})

    @model_validator(mode="after")
    def stable_and_canonical_identity(self) -> Self:
        expected_id = canonical_sha256(
            {"domain": _PREPARED_TARGET_DOMAIN, "database_name": self.database_name}
        )
        if self.message_id is not None and self.message_id != expected_id:
            raise ValueError("prepared target message ID differs from its exact database identity")
        object.__setattr__(self, "message_id", expected_id)
        if self.correlation_id is None:
            object.__setattr__(self, "correlation_id", expected_id)
        expected_produced_at = datetime_from_unix_ms(self.observed_at_ts_ms)
        if "produced_at" not in self.model_fields_set:
            object.__setattr__(self, "produced_at", expected_produced_at)
        elif (
            self.produced_at.tzinfo is None
            or self.produced_at.utcoffset() is None
            or int(self.produced_at.timestamp() * 1_000) != self.observed_at_ts_ms
        ):
            raise ValueError("prepared target envelope clock must equal its database-observed time")
        expected_receipt_sha256 = canonical_sha256(self.identity_payload())
        if self.receipt_sha256 is not None and self.receipt_sha256 != expected_receipt_sha256:
            raise ValueError("prepared target receipt hash differs from canonical payload")
        object.__setattr__(self, "receipt_sha256", expected_receipt_sha256)
        return self

    def sanitized_metadata(self) -> dict[str, str | int]:
        """Return only closed target facts; never include a DSN or credential."""
        return {
            "database_name": self.database_name,
            "current_user": self.current_user,
            "server_version_num": self.server_version_num,
            "migration_profile": self.migration_profile,
            "storage_module_sha256": self.storage_module_sha256,
            "classification": self.classification,
            "observed_at_ts_ms": self.observed_at_ts_ms,
            "receipt_sha256": self.receipt_sha256 or "",
        }


def _native_storage_module_sha256() -> str:
    source = Path(__file__).read_text(encoding="utf-8").replace("\r\n", "\n").replace("\r", "\n")
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _prepared_native_target_message_id(database_name: str) -> str:
    return canonical_sha256({"domain": _PREPARED_TARGET_DOMAIN, "database_name": database_name})


async def _live_prepared_target_facts(database: Database) -> dict[str, object]:
    row = await database.pool.fetchrow(
        "SELECT current_database() AS database_name, current_user AS current_user, "
        "current_setting('server_version_num')::integer AS server_version_num, "
        "ceil(extract(epoch FROM clock_timestamp())*1000)::bigint AS observed_at_ts_ms"
    )
    if row is None:
        raise ValueError("prepared target database facts are unavailable")
    facts = {
        "database_name": str(row["database_name"]),
        "current_user": str(row["current_user"]),
        "server_version_num": int(row["server_version_num"]),
        "observed_at_ts_ms": int(row["observed_at_ts_ms"]),
    }
    if (
        facts["database_name"] != database.database_name
        or facts["current_user"] != "kairos"
        or not 160_000 <= facts["server_version_num"] < 170_000
        or database.migration_profile is not MigrationProfile.RESEARCH_CAMPAIGN
    ):
        raise ValueError("live database identity differs from the prepared native target contract")
    return facts


async def record_prepared_native_target(database: Database) -> None:
    """Append prep evidence after native_gate proves a fresh PG16 target and verifies schema."""
    database_name = require_disposable_campaign_database(database)
    await database.verify_schema()
    facts = await _live_prepared_target_facts(database)
    storage_sha256 = _native_storage_module_sha256()
    message_id = _prepared_native_target_message_id(database_name)
    receipt = PreparedNativeTargetV1(
        source="native-campaign-preparation",
        correlation_id=message_id,
        message_id=message_id,
        database_name=database_name,
        current_user=facts["current_user"],
        server_version_num=facts["server_version_num"],
        migration_profile=database.migration_profile.value,
        storage_module_sha256=storage_sha256,
        classification="OFFLINE_ENGINEERING_FIXTURE",
        observed_at_ts_ms=facts["observed_at_ts_ms"],
        produced_at=datetime_from_unix_ms(facts["observed_at_ts_ms"]),
    )
    payload = receipt.model_dump(mode="json")
    canonical = canonical_json_bytes(payload).decode("utf-8")
    payload_sha256 = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    audit = AuditRepository(database.pool)
    async with database.transaction() as connection:
        await connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            f"native-target-prepared:{database_name}",
        )
        await audit.append_payload_strict(
            _PREPARED_TARGET_TOPIC,
            payload,
            canonical,
            payload_sha256,
            connection=connection,
        )


async def require_prepared_native_target(database: Database) -> dict[str, str | int]:
    """Require one exact preparation marker and revalidate its source/schema/live target."""
    database_name = require_disposable_campaign_database(database)
    await database.verify_schema()
    expected_message_id = _prepared_native_target_message_id(database_name)
    async with (
        database.pool.acquire() as connection,
        connection.transaction(readonly=True),
    ):
        rows = await connection.fetch(
            "SELECT topic, payload FROM event_audit WHERE message_id=$1",
            expected_message_id,
        )
        live_row = await connection.fetchrow(
            "SELECT current_database() AS database_name, current_user AS current_user, "
            "current_setting('server_version_num')::integer AS server_version_num"
        )
    if len(rows) != 1 or live_row is None:
        raise MessageIdentityConflict("exactly one prepared native target marker is required")
    raw = rows[0]["payload"]
    try:
        payload = json.loads(raw) if isinstance(raw, (str, bytes, bytearray)) else dict(raw)
        receipt = PreparedNativeTargetV1.model_validate(payload)
        canonical_payload = receipt.model_dump(mode="json")
        canonical = canonical_json_bytes(canonical_payload).decode("utf-8")
        receipt_round_trip = PreparedNativeTargetV1.model_validate_json(canonical)
    except (TypeError, ValueError, json.JSONDecodeError) as exc:
        raise MessageIdentityConflict(
            "prepared native target marker is not a strict canonical receipt"
        ) from exc
    live_database_name = str(live_row["database_name"])
    live_user = str(live_row["current_user"])
    live_version = int(live_row["server_version_num"])
    if (
        rows[0]["topic"] != _PREPARED_TARGET_TOPIC
        or receipt.message_id != expected_message_id
        or receipt.database_name != database_name
        or receipt.current_user != live_user
        or receipt.server_version_num != live_version
        or receipt.migration_profile != database.migration_profile.value
        or receipt.storage_module_sha256 != _native_storage_module_sha256()
        or receipt.classification != "OFFLINE_ENGINEERING_FIXTURE"
        or receipt_round_trip.model_dump(mode="json") != canonical_payload
        or canonical != canonical_json_bytes(payload).decode("utf-8")
        or live_database_name != database_name
        or live_user != "kairos"
        or not 160_000 <= live_version < 170_000
    ):
        raise MessageIdentityConflict(
            "prepared target marker conflicts with source, schema or live database identity"
        )
    return receipt.sanitized_metadata()


def require_disposable_campaign_database(database: Database) -> str:
    """Validate the exact local UUID4 RESEARCH_CAMPAIGN target without connecting."""
    if not isinstance(database, Database):
        raise TypeError("an explicit Persistence Database object is required")
    if database.migration_profile is not MigrationProfile.RESEARCH_CAMPAIGN or database.read_only:
        raise ValueError("native campaign storage requires a writable RESEARCH_CAMPAIGN database profile")
    name = database.database_name
    if not isinstance(name, str) or not name.startswith(_TARGET_PREFIX):
        raise ValueError("native campaign writes require a disposable UUID4 campaign database")
    suffix = name.removeprefix(_TARGET_PREFIX)
    if _TARGET_SUFFIX.fullmatch(suffix) is None:
        raise ValueError("native campaign database name must end with an exact lowercase UUID4 hex")
    namespace = UUID(hex=suffix)
    if namespace.version != 4 or namespace.hex != suffix:
        raise ValueError("native campaign database name must contain a version-4 UUID")
    require_database_target_url(database.settings.database_url, name, local_only=True)
    # Keep the allowed disposable target narrower than other internal local
    # PostgreSQL helpers: no container DNS name or remote host is accepted.
    from urllib.parse import urlsplit

    host = urlsplit(database.settings.database_url).hostname
    if host not in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("native campaign target must be explicitly loopback-local")
    return name


class SealedBarWindowV1(StrictValueModel):
    """Exact immutable reference to a contiguous one-minute slice of a sealed tape."""

    tape_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    tape_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    symbol: Literal["BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT"]
    first_open_ms: Annotated[StrictInt, Field(ge=0)]
    last_open_ms: Annotated[StrictInt, Field(ge=0)]
    bar_count: Annotated[StrictInt, Field(ge=1, le=_MAX_BARS)]
    window_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]

    @model_validator(mode="after")
    def exact_window_geometry(self) -> Self:
        if (
            self.first_open_ms % 60_000
            or self.last_open_ms % 60_000
            or self.last_open_ms < self.first_open_ms
            or self.first_open_ms + (self.bar_count - 1) * 60_000 != self.last_open_ms
        ):
            raise ValueError("sealed bar window must be one exact contiguous one-minute range")
        return self


class ReadOnlySealedBarWindowResolver:
    """Resolve registered window references from an already-sealed SIM tape."""

    def __init__(self, database: Database, windows: Mapping[str, SealedBarWindowV1]) -> None:
        require_disposable_campaign_database(database)
        if not isinstance(windows, Mapping) or not windows:
            raise ValueError("an explicit non-empty sealed-window reference mapping is required")
        validated: dict[str, SealedBarWindowV1] = {}
        for reference, window in windows.items():
            if not isinstance(reference, str) or not reference.strip() or reference != reference.strip():
                raise ValueError("bar-window references must be normalized non-empty strings")
            if type(window) is not SealedBarWindowV1:
                raise TypeError("bar-window mapping values must be exact SealedBarWindowV1 objects")
            validated[reference] = SealedBarWindowV1(
                tape_id=window.tape_id,
                tape_sha256=window.tape_sha256,
                symbol=window.symbol,
                first_open_ms=window.first_open_ms,
                last_open_ms=window.last_open_ms,
                bar_count=window.bar_count,
                window_sha256=window.window_sha256,
            )
        self._database = database
        self._windows = MappingProxyType(validated)
        self._repository = SimulationRepository(database.pool)

    async def load(self, reference: str) -> tuple[ClosedBarEventV1, ...]:
        """Load only registered originals; perform no HTTP fetch or database write."""
        if not isinstance(reference, str) or reference not in self._windows:
            raise KeyError("unknown sealed bar-window reference")
        window = self._windows[reference]
        if not await self._repository.verify_tape(window.tape_id):
            raise MessageIdentityConflict("sealed simulation tape failed its full immutable-chain audit")
        async with (
            self._database.pool.acquire() as connection,
            connection.transaction(readonly=True),
        ):
            tape = await connection.fetchrow(
                "SELECT state, tape_sha256 FROM sim_tapes WHERE tape_id=$1",
                window.tape_id,
            )
            if (
                tape is None
                or tape["state"] != "SEALED"
                or tape["tape_sha256"] is None
                or str(tape["tape_sha256"]) != window.tape_sha256
            ):
                raise MessageIdentityConflict("registered tape identity differs from its sealed database row")
            predecessor = await connection.fetchrow(
                """SELECT open_time_ms FROM sim_closed_bars
                   WHERE tape_id=$1 AND symbol=$2 AND open_time_ms < $3
                   ORDER BY open_time_ms DESC LIMIT 1""",
                window.tape_id,
                window.symbol,
                window.first_open_ms,
            )
            cursor = None if predecessor is None else int(predecessor["open_time_ms"])

        bars: list[ClosedBarEventV1] = []
        while len(bars) < window.bar_count:
            page = await self._repository.load_closed_bar_page(
                window.tape_id,
                window.symbol,
                after_open_time_ms=cursor,
                limit=min(_PAGE_SIZE, window.bar_count - len(bars)),
            )
            if not page:
                break
            if not bars and page[0].open_time_ms != window.first_open_ms:
                raise MessageIdentityConflict("stored tape does not begin at the registered window boundary")
            if any(bar.symbol != window.symbol for bar in page):
                raise MessageIdentityConflict("stored bar page escaped the registered symbol")
            bars.extend(page)
            cursor = page[-1].open_time_ms

        result = tuple(bars)
        if (
            len(result) != window.bar_count
            or result[0].open_time_ms != window.first_open_ms
            or result[-1].open_time_ms != window.last_open_ms
            or campaign_bar_window_sha256(result) != window.window_sha256
        ):
            raise MessageIdentityConflict("stored canonical bars differ from the exact registered window")
        return result


class NativeReviewRiskJournal:
    """Append/load strict binding receipts; this is not the SIM risk authority."""

    TOPIC = "native.review-risk.v1"

    def __init__(self, database: Database) -> None:
        require_disposable_campaign_database(database)
        self._database = database
        self._audit = AuditRepository(database.pool)

    async def save(self, receipt: NativeReviewRiskReceiptV1) -> bool:
        payload, canonical, payload_sha256 = canonical_receipt_json(receipt)
        async with self._database.transaction() as connection:
            await connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
                f"native-review-risk:{receipt.message_id}",
            )
            return await self._audit.append_payload_strict(
                self.TOPIC,
                payload,
                canonical,
                payload_sha256,
                connection=connection,
            )

    async def load(self, campaign_id: str, sample_id: str) -> NativeReviewRiskReceiptV1 | None:
        expected_message_id = native_review_risk_message_id(campaign_id, sample_id)
        async with (
            self._database.pool.acquire() as connection,
            connection.transaction(readonly=True),
        ):
            rows = await connection.fetch(
                "SELECT topic, payload FROM event_audit WHERE message_id=$1",
                expected_message_id,
            )
        if not rows:
            return None
        if len(rows) != 1:
            raise MessageIdentityConflict("native receipt message ID has multiple audit rows")
        row = rows[0]
        raw = row["payload"]
        try:
            payload = json.loads(raw) if isinstance(raw, str) else dict(raw)
            receipt = NativeReviewRiskReceiptV1.model_validate(payload)
            canonical_payload, canonical, _digest = canonical_receipt_json(receipt)
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MessageIdentityConflict("stored native review/risk receipt is not canonical") from exc
        if (
            row["topic"] != self.TOPIC
            or receipt.message_id != expected_message_id
            or receipt.campaign_id != campaign_id
            or receipt.sample_id != sample_id
            or canonical
            != json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
            or canonical_payload != payload
        ):
            raise MessageIdentityConflict(
                "stored native review/risk receipt conflicts with its stable identity"
            )
        return receipt
