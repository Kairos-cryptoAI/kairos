# Kairos — controlled current-runtime transition, 2026-10-10

## Scope and authority

The owner separately authorized the primary database transition after an
accepted fresh isolated-clone check, without trading. This is not permission
to replay ambiguous outbox entries, reset leases/cursors, start consumers or
publishers, contact EVEDEX, or use paid model/feed APIs. Strategy, orders,
PAPER/LIVE and canary remain OFF. All readiness flags remain false and the
strategy policy remains `REJECT_ALL`.

This continuation is separate from the accepted legacy-schema
[fresh backup/restore receipt](RECOVERY-2026-10-10.md). That historical receipt
and the frozen research ledgers are not rewritten.

## Published primary source and later observer revisions

The admitted complete clone and primary mutation bind signed Deploy
`889a15ed2e6af138c7b9634a771f23389b2e4ab4`. Later restore-only and
cold-observer fixes bind their own revisions, documented below; the final
source manifest pins Deploy `188e23c4bce159b8e6265fef56ce421c2add577a`
without changing that historical mutation identity. The offline current
Core/Persistence wheel manifest SHA-256 is
`9541970c3c61347d45f2bf790760e80f33c9c05d1e3c01c5324b18e03deb0a66`.
Persistence is signed `0f416ee70a451f8d2a32a7dd403d7a02bce071c9`.

Nine service dependency projections now pin this Persistence revision: Router,
Strategy, Risk, Execution, Quant, LLM, Aggregator, Macro and Text. The current
atomic runtime profile is `001`–`016`, `018`, `026`; it is not the archived
`001`–`012` long-gap runner profile. The Meta manifest records the new exact
source pins, without declaring the preserved adaptive working tree accepted.

At `889a15e`, Windows Python 3.11 and 3.14 suites each ran 591 tests: 585 pass, six
explicit skips, zero failures. Seventeen focused delivery-fixture tests pass
against the current Core/Persistence APIs, with no skips. Ruff and formatting
checks pass. The five exact-source hosted gates on `889a15e` are green:

- [CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38086169132).
- [Installed Text/Macro/Router/review/Risk composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38086169058).
- [CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38086169031).
- [Current-release gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38086180331).
- [Full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38086182399).

## Integrity and delivery changes

The native current-source workflow uses a fresh official backup, complete
independent restores, a byte-bound offline operator/wheel snapshot, one outer
migration transaction and nine full-history rollback checkpoints. Ordinary and
primary worker limits remain 330 seconds; only the repeated clone rehearsal has
a separate 930-second bound. The outer supervisor remains bounded and owns its
process tree before execution resumes. Lost-COMMIT outcomes are inspected
read-only, never retried automatically.

The runtime login must be new and least-privileged; an existing or unknown
`kairos_runtime` role blocks admission rather than being silently reused or
changed. Startup checks require the actual database grants and reject forbidden
capabilities. Before Redis publication, durable outbox state records
`PUBLISHING` and a reconciliation identity. Ambiguous acknowledgement stays
`UNKNOWN`; unresolved producer-head entries block later FIFO publication.

Redis acknowledgement evidence is a separate bounded, payload-free contract.
Its database-only resolver accepts only an exact positive witness, is
idempotent, rejects conflicts, and does not call Redis or increment publication
attempts. This API alone is not production backlog-reconciliation authority.

The actual empty isolated PG/Redis fixture passed after fixing probe SQL grant
tokens, required wire metadata, asyncpg JSONB canonicalization, the two-message
audit cardinality and explicit runtime settings. It proves two durable
synthetic message identities, one handler invocation under redelivery, audit
commit before acknowledgement, `UNKNOWN` preservation through a new bus
instance, exact positive resolution and conflict refusal. It creates zero
execution orders. This is a bus-instance restart in one process, not proof of
an operating-system process crash. The successful small fixture is not a
substitute for the complete fresh-runtime clone gate.

All failed attempts, their private diagnostic artifacts and failed owner leases
are retained. No failed attempt is promoted to acceptance.

Primary temporary files now have create-only owner/path/source-bound intents
recorded before copy or dump. Cleanup verifies owned full or exact partial bytes,
refuses foreign files and links, attempts all remaining owned paths after one
failure, and stops the primary. Pending intents independently prohibit supervisor
acceptance. Thirteen local regression tests pass, including portable path
metadata and link/reparse rejection. A disposable filesystem-only
fixture also passed all six actual copy/fault/partial/foreign/link cases, with
verified container cleanup and no database server or original database contact.

## Native acceptance state

The sixth complete fresh clone passed at 19:35:07 UTC, with all nine rollback
checks, current-source atomic rehearsal, permissions, idempotence, actual
isolated PG/Redis delivery, backup-after independent restore, and amcheck. Its
supervisor passed with zero surviving owned processes; original primary/Redis
remained stopped and unchanged. That receipt binds `8089491`; both its clone
and supervisor receipts were detached-signed and verified. Primary admission
then failed closed in public-key signature import: MSYS attempted an agent socket
whose full Windows path exceeded its bound, despite `--no-autostart`. This was
before starting PostgreSQL or creating a primary mutation lease. No primary
mutation is claimed. The earlier path-normalization failure is also retained.

The new verifier dearmors only the hash-pinned public key into a new private
keyring, then runs agentless `gpgv` against that explicit keyring and requires
the exact trusted primary fingerprint. An actual long-path isolated check passes
both signed receipts and rejects a changed receipt, without database access.
Cold Redis Git admission now uses pinned Git/GPG executables
and one exact-checkout `safe.directory`, not a global ownership exception; its
actual signed-source-only preflight also passes. The new revision requires a
fresh complete clone before any primary transition; old evidence is not rebound.
The seventh fresh clone, binding `e458d0e`, started at 19:55:07 UTC and passed
at 20:17:17 UTC. Its 1,330.25-second supervisor passed with all 698 owned
processes completed, no surviving owned processes, nine complete rollback
checks, the actual isolated delivery fixture, backup-after restore and amcheck.
Both original containers were stopped and unchanged during this clone; both
receipts were subsequently detached-signed and verified without alteration.

The third primary attempt then passed signature and stopped-source preflight,
but failed closed immediately after starting PostgreSQL, before provisioning
the temporary login or invoking the migration/quarantine worker. Its guard
compared the short ID from `docker ps -q` with a full inspected container ID,
mistaking its own source for a forbidden protected service. The independent
supervisor verified zero remote-create intents, no primary schema/quarantine
or role mutation, zero surviving owned processes and PostgreSQL stopped again.
Redis was never started or contacted. The failed primary receipt and owner
lease remain retained. Because PostgreSQL did start, the preceding cold bytes
are not claimed current, and this owner is not retried.

The guard now compares independently inspected full IDs. Three regression
tests cover accepting the exact source despite short CLI output, refusing a
separate protected service and refusing a foreign mount of the primary volume.
The eighth fresh clone, binding `3135bc7`, started at 20:27:28 UTC and passed
after 1,206.27 seconds, with all nine rollback checks, exact atomic rehearsal,
actual isolated PG/Redis delivery, backup-after restore and amcheck. Its fresh
legacy backup matches all 27 earlier public-table histories, schema, sequences
and twelve legacy migrations, verifying preserved data after the earlier brief
primary start rather than claiming the old cold bytes remained current. Both
receipts were detached-signed without alteration and both containers remained
stopped during the clone.

The fourth primary attempt failed closed in private SQL file preparation.
Two bounded calls failed at `chown` with `Operation not permitted`; the source
container drops all capabilities, including `CHOWN`, even for UID 0. The
provisioning `psql` call was not reached. The immutable child conservatively
records temporary-role outcome `UNKNOWN` and schema/quarantine `NOT_ATTEMPTED`;
its diagnostic call order independently establishes that role SQL was not
invoked. The supervisor verifies both remote create/remove intents completed,
zero surviving owned processes and PostgreSQL stopped. Redis was not started.
That failed receipt/lease remains intact and is not retried.

The new signed controller retains root-owned mode-0600 SQL, verifies its hash,
and uses a bounded UID-0 file reader while keeping database identity explicitly
`kairos`. The private pg_dump writer has the same UID as its hash reader; no
capability, primary container setting or database authority is expanded. A
synthetic isolated PostgreSQL probe passes actual SQL reading, private dump
copy/hash and owned cleanup under `CapDrop ALL`, with neither original data
volume mounted nor either original server contacted. This narrow proof is not
a substitute for a new complete exact-source clone and primary acceptance.

The ninth fresh clone binds `889a15e` and started at 21:07:02 UTC. Its official
backup is 78,948,828 bytes. It passed after 1,705.891 seconds. The independent
full restores match the entire baseline, all nine injected-fault rollback
histories match, exact COMMIT inspection and idempotence pass, and the actual
empty isolated PG/Redis delivery fixture, backup-after independent restore and
all three heap/B-tree integrity checks pass. Both original containers remain
stopped and unchanged; the supervisor verifies zero surviving owned processes.
The clone and supervisor receipts were detached-signed at 21:35 UTC, verified
against the exact trusted signer and left byte-unchanged. Their SHA-256 values
are `5ebc3e288762c4b8e94ec2302b7ccf6ce6e20ec3e2892e21748765ecaf48eed8`
and `9de9c383ca816678927be991082e3ba61a837cf6fc9a064acddd29775dbffc1e`.

An earlier cold-Redis attempt failed while preparing a new empty snapshot volume;
it did not copy, start, query or read credentials from the original Redis. The
verified owned snapshot resources were removed, while its failed receipt/lease
was retained. Preparation now rejects existing-volume name collisions, foreign
labels/options and nonempty targets before any writable mount or ownership
change. Only the empty new target initializer runs as root with all capabilities
dropped except `CHOWN`; it transfers the target at mode `0700` to UID/GID 999.
The source copy and observers remain unprivileged and isolated. Unit tests and
independent read-only review pass. The next actual cold attempt verifies target
preparation but fails closed inside the unprivileged copy/hash worker. Its
original-source metadata remains unchanged and both owned copy containers and
snapshot volume are removed; its failed revision lease is retained. The new
diagnostic uses only allowlisted worker stage and exception-class tokens, never
exception messages, file paths or payloads. A nonzero worker exit always
rejects admission, even if its output resembles success. Source size/file/time
bounds, no-atime reads and unprivileged source access are unchanged. Real cold
acceptance is still pending. The actual `889a15e` attempt verifies new-target
preparation and source manifest access, but refuses persistence-lineage
qualification before copying: `WORKER_REJECTED:copy_persistence_before:ColdRedisError`.
This safe stage/class token is not proof of corruption or of an absent stream
entry. No accepted Redis observation exists. Original Redis metadata remains
unchanged, all owned containers and the new snapshot volume are removed, and
no original server command, database contact, credential read or publication
occurred. Its immutable receipt SHA-256 is
`edada2d762b7d792781a5620118a2702e1bbd0793f262ee6b41fc43f166d0703`;
that script revision/owner is not retried.

After verifying that cleanup, the fifth primary attempt was admitted against
the ninth signed complete clone and started at 21:37:45 UTC. Its scope is only
current schema and exact expired-row quarantine; consumer starts, publishers,
Redis commands and trading remain forbidden. The actual primary transaction is
`COMMITTED_ACKNOWLEDGED`; the current profile `001`–`016`, `018`, `026` and all
39 public-table histories pass read-only verification. The newly provisioned
runtime login/permissions are verified, and the temporary login is removed.
The exact expired row is quarantined as outcome-unknown, not replayed.

The final child remains `FAILED_CLOSED`: after making and restoring its
79,126,336-byte backup-after, the controller attempted to create its already
existing `plan.json` again. Create-only evidence protection correctly raised
`FileExistsError` in `BACKUP_AFTER_AND_RESTORED_HISTORY_ONLY`. The original plan
and failed receipt are retained byte-unchanged. Schema/quarantine outcome is
`COMMITTED`, temporary-role outcome is `CREATED_AND_DROPPED`, and cleanup is
verified. The supervisor independently verifies PostgreSQL stopped, all three
remote create/remove intents completed and zero surviving owned processes.
Redis was never started or contacted. The backup-after SHA-256 is
`2408db1335dc856122750e4604f14a436184f54a7f4ffab22bc35eb69747a7bc`;
the immutable failed child and supervisor hashes are
`ff272d696f7ebed409950cab705c61183719195af7a98b497bba46284b508e5b` and
`a768de1a6bff990d04680412f53c12723d2a5dcdeeb0649838d895685c37fb1a`.
The failed primary lease is never retried and its result is not rewritten as
a pass.

The later signed fixes preserve a phase-local restore plan, separate create-only
before/after fingerprint checkpoints and accept canonical optional Redis AOF
offset fields. The first restore-only supplement passed its restored history
and integrity checks, but failed on its final repeated checkpoint log name;
that failed receipt is also retained rather than relabelled.

A new create-only restore-only supplement binds Deploy
`563bdf2b0ee5916284f63184531c9034c4045eae` and the exact unchanged signed
backup-after. It finishes `PASS_POSTCOMMIT_ISOLATED_RESTORE`: all 39 current
public-table histories match the independently verified primary state, whole
restored-cluster heap/B-tree integrity verification exits zero, the original
primary remains stopped and unchanged during this supplement, and every owned
resource/process is removed. It performs zero primary mutations, consumer
starts, publications, Redis contacts or credential reads. It deliberately
uses the prior actual primary login/privilege verification, not a claim that
the restored cluster rechecked runtime credentials. Its exact receipt SHA-256 is
`afda95f2d7b250f3dbc114a8bf07b84e7a62f4fa08c102b1ceb82441b01cf546`,
with detached signature SHA-256
`c5daebcf624ebb020eb598ebba8d5d21cc1d57e7bf5fb97ac5d5ec6b1bffe40f`.
Both signature and unchanged bytes are verified against the exact trusted signer.
The original primary controller failure is not overwritten or treated as PASS;
the separate accepted supplement closes only its outstanding restore contour.

The Redis format diagnostic establishes a supported incremental manifest with
optional `startoffset` and `endoffset`, not corruption. Redis's official
[8.2.2 AOF source](https://github.com/redis/redis/blob/8.2.2/src/aof.c)
emits these fields. The new strict parser accepts canonical bounded offsets
while preserving raw-manifest/component hashes and rejecting unsupported shapes.

The actual cold Redis clone at Deploy `563bdf2` loads the complete unchanged
74,200,674-byte, four-file RDB/multipart-AOF image. Its read-only search examines
20,000 stream entries / 15,997,572 response bytes and returns
`INCONCLUSIVE_SCAN_LIMIT`, not evidence of non-publication: the scan is not
complete. Source hashes remain unchanged and the owned server, observers and
snapshot volume are removed. No original Redis server command, primary contact,
credential read, publication or automatic resolution occurs. The signed
immutable receipt SHA-256 is
`b807a0daefb864ee40f814f33eb21d329bcfded2e0d0b24ed4790e5dc2b3e858`.

The next signed observer revision is
`188e23c4bce159b8e6265fef56ce421c2add577a`. Both Windows Python 3.11/3.14
suites run 602 tests: 596 pass, six explicit skips, zero failures. It raises
only the isolated read-only stream-search limits to 120,000 entries / 128 MiB;
500-entry pages, the total 240-second bound, source bounds, isolation and
resource/cleanup limits stay unchanged. A capped scan can never admit a positive
witness, even if it has already seen one match. The exact-source hosted
[Windows/Linux CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38091405395),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38091405391),
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38091404476),
[current-source Docker gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38091415594)
and [full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38091417791)
are green. The new create-only observation finishes
`INCONCLUSIVE_ZERO_MATCH`: the complete preserved stream contains 23,976
entries / 19,190,730 response bytes, with zero exact matches. This result does
not establish that the historical event was never accepted: stream trimming or
deletion can remove acceptance evidence. The exact primary row remains
`PUBLISH_OUTCOME_UNKNOWN`; it is not acknowledged, replayed, skipped,
dead-lettered or used as permission to drain its FIFO successors.

All source hashes remain unchanged through copy and probe. The isolated Redis
loads the same complete 74,200,674-byte persistence image; all owned containers
and its snapshot volume are removed, and both original data containers remain
stopped. The exact receipt SHA-256 is
`21f39518dcd37d08ee906fd6ca3563ef0323159e0455b2676c9c23d79f5f185d`,
with detached signature SHA-256
`cca13a2cfe40e48d9465dae4e172c86f070b295eaa14b2807bf923b06f2b5b02`.
The signature is verified against the exact trusted signer. Both original
Redis commands and primary contacts are zero, as are credential reads and
publications. This observer revision/lease is not retried.

The [curated evidence summary](receipts/runtime-current-transition-20261010.json)
contains only source identities, result/limit/count metadata and exact hashes;
private dumps, row identities, stream payloads and credentials are not uploaded.

## Separate historical root-RDB observation — 2026-10-11

The root `dump.rdb` is an independently selected historical snapshot, not
the current multipart-AOF Redis state. The explicit historical-only mode
binds signed Deploy `801d97c4b2414fa755e40e63873b2e21f774b002` and implementation
SHA-256 `118dba68690f30a271268c4cceaeeeed3cc8aaba4bf167d003b9f6bfe2956232`.
It is never a fallback from a failed AOF load or permission to alter the legacy
queue. It verifies a bounded plain root RDB, its exact file hash and source
immutability, then loads it only on the owned clone with AOF disabled, saves
disabled and the copied data volume mounted read-only. No original Redis
server starts or commands, primary contacts, credential reads or publications
occur. Even a positive historical observation omits resolver-shaped acceptance
evidence and cannot automatically acknowledge an original row.

The actual single create-only run finishes
`HISTORICAL_RDB_INCONCLUSIVE_ZERO_MATCH`: all 23,976 preserved stream entries /
19,190,730 response bytes are examined, with zero exact matches. The root RDB
is 15,782,907 bytes with SHA-256
`0150fe15427e333550f7257611c1f8dc1433deb9a61b7e908206dd5a2507f409`.
The copied four-file persistence image remains 74,200,674 bytes; all source
manifest/content/volume hashes are unchanged before and after observation.
Owned containers and the snapshot volume are removed; both original data
containers remain stopped. This implementation lease is not retried.

The exact private historical receipt SHA-256 is
`789186e7a75ff43d8ec21d7418298c06b8b57d08fca04cf9e25585f38878f08b`;
its detached signature SHA-256 is
`e58302016f0923ad73c6609cdc7436997b1bef6c6585f90761755b2a05af259b`.
The exact trusted signer and unchanged bytes are verified. The new
[curated historical supplement](receipts/runtime-historical-rdb-20261011.json)
is separately signed; the earlier
[primary/current-Redis summary](receipts/runtime-current-transition-20261010.json)
and every failed/successful private receipt remain unchanged.

Windows Python 3.11/3.14 each run 607 tests: 601 pass, six explicit skips,
zero failures; all 31 focused cold-observer tests and scoped Ruff/format checks
pass. The exact-source hosted
[CI](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38092775830),
[installed composition](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38092775813),
[CodeQL](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38092775943),
[current-source Docker gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38092775946)
and [full-path SIM gate](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/38092777865)
are green. They qualify this observer engineering source, not legacy FIFO drain,
catch-up, consumers, a whole clean release or trading.

Both available direct cold persistence observations have now been exhausted.
Neither proves non-publication, resolves the original `UNKNOWN`, nor permits
replay/acknowledgement/skipping/dead-lettering. The owner has been asked to
choose between waiting for new exact evidence and a separately isolated,
non-trading runtime epoch that preserves the legacy DB/Redis/queue unchanged.
That new epoch would require a data-only `CLOSED_BAR` history seed, exact
separate source/target identities, bounded catch-up, a current-schema bounded
drain and a dispatcher-off consumer-only profile with independent publication
denial. None of these new-epoch admissions is implied or performed by this
historical observation.

## Still separate from a working runtime

The accepted schema/quarantine and separate restore verification do not by
themselves complete the working runtime. The remaining ordered steps are
exact Redis acceptance evidence binding to the primary `UNKNOWN` row and FIFO prefix, a signed bounded
publication/drain workflow, current-source closed-bar catch-up, and separately
admitted non-trading consumers. Missing/zero/conflicting Redis evidence is not
replay permission. The reviewed Quant catch-up entry point has a 150,000-bar
total cap; a larger gap must not silently widen it or use the legacy runner.

A read-only source audit identifies concrete engineering gaps, not completed
runtime admissions:

- The DB resolver accepts typed exact Redis acceptance metadata, but no primary
  operator currently verifies and binds a signed cold-clone observation to the
  real quarantined row. Only the synthetic delivery fixture does that composition.
- The archived signed FIFO-drain lock requires migration `017` and lacks `026`;
  it is not the current controlled profile. It also refuses global ambiguous
  unpublished reconciliation. A correctly resolved `ACKNOWLEDGED` entry has
  `published_at` set by the resolver and is excluded from that ambiguity count;
  no ambiguity-count defect is inferred. The source profile/dependency lock must
  be updated and requalified without widening the 100-row/300-second limits.
  The archived runner must not be applied or relaxed against the current primary.
- `DurableMessageBus.start()`/`subscribe()` unconditionally start the outbox
  dispatcher after schema checks. There is no accepted consumer-only admission;
  even `verify_schema_only` is not a dispatcher-off switch. Ordinary service
  startup can therefore publish preserved backlog and is outside this authority.
  An eventual consumer-only mode must also refuse consumer-side publication,
  not merely avoid constructing a dispatcher task. Independent database outbox
  write denial and Redis `XADD` denial are also needed. Existing strategy service
  startup is not a passive ingest path: even an empty strategy allowlist emits
  a disabled-evaluation event. A separate non-strategy ingest handler is required;
  the `REJECT_ALL` manifest string is not a substitute for these runtime guards.
- Quant's current offline writer avoids Redis/dispatch, but its
  `--offline-consumers-confirmed` flag is a required argparse assertion, not
  independent host attestation. A reviewed bounded host admission and separately
  approved exact finality/range/append budget are still required for catch-up.

The continuity-preserving path would require an exact positive witness, a
reviewed signed primary acknowledgement admission, an updated exact-profile
signed bounded drain, and separate catch-up/consumer admissions. No positive
witness was obtained, and no code-level API or isolated fixture automatically
grants any of these primary actions. Continuing from this legacy FIFO therefore
requires new evidence or an explicit owner decision on historical continuity.
An alternative is to preserve the unresolved legacy queue unchanged and
qualify a separate fresh non-trading runtime epoch; that is a separate recovery
choice, not an implicit lease reset, historical skip or replay approval.

Off-host backup/restore, actual alert delivery, venue qualification, adaptive
campaign/economic gates and production security/arming remain separate. The
unfinished adaptive source changes are preserved, not included in this
runtime acceptance. No performance result or LIVE readiness follows from the
engineering checks above.
