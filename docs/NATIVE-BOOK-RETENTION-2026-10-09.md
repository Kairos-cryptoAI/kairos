# Offline native source retention and journal reconciliation

Date: 2026-10-09 Europe/Moscow. Additive engineering after
[native byte binding](NATIVE-BOOK-BINDING-2026-10-09.md), not strategy selection,
historical economic/model replay, campaign enrollment or runtime qualification.

## Completed implementation scope

`development/adaptive_replay/adaptive_replay/book_bundle.py` adds a one-shot
offline source package for a caller-supplied complete native V2 prefix. It
accepts the unchanged explicit native parser profiles, at most 512 frames in
one tape/epoch, 32 KiB original payload per frame, 256 KiB retained record and
128 MiB package. Limits reject the whole input; nothing is sampled or truncated.
The package preserves exact UTF-8 vendor text in each native frame and separately
stores the generated research capture bytes, original and derived hashes,
clocks, policy and binding receipt. Generated BBO is never called vendor bytes.

`prepare_book_bundle` describes the supplied prefix and installed source identity;
it is not a source-authentication or admission decision. The caller-held seal
pins policy, complete count, native head, all retained records and exact installed
research/core/strategy source binding. `retain_book_bundle` writes only an
exclusive new `.native-book.research.json` file in an existing directory. Flush
and file fsync precede the returned whole-file retention receipt. Existing,
failed or interrupted attempts are never removed, overwritten, resumed or adopted.
There is no append API or repair/migration path. A missing file fails closed.
Power-loss persistence of the directory and actual external backup remain
independent; this is not an off-host storage qualification.

The receipt keeps actual modern retention time separate from the original
event/receive/persistence clocks. Native persistence later than this retention
time is refused. Retention today never asserts that this package existed at a
historical knowledge cut. All native clocks and origin are still caller-attested.

`open_book_bundle` requires **both** the independently retained caller seal and
retention receipt. It reads bounded bytes without mutation, verifies their exact
hash and encoding, reconstructs every native value and derived record, reruns
the unchanged byte/field parser and audits the full consecutive root-to-head
prefix. Wrong policy, altered bytes/metadata, missing/reordered/duplicated records,
barriers, epoch joins, unsupported source identity or implementation drift fail
closed. A restored exact copy may be audited under the same retained commitments.
Filesystem timestamps are not source/content authority: bounded regular-file
identity checks and the expected exact byte hash decide retention consistency.
Symlinks/reparse points and hard-linked aliases are refused. These checks do not
constitute security against a hostile owner concurrently replacing the filesystem.

`admit_retained_book_capture` requires one explicit sequence and expected binding
hash. It reopens the full package, preserves event-anchored TTL and original
causal boundaries and returns the complete visible prefix at that as-of clock,
including zero counts for absent symbols. It never chooses the most convenient
quote, replaces a missing frame or uses later persistence to refresh a stale event.
A successful diagnostic lookup grants no continuous-coverage or execution rights.

## Separate journal-source audit

`audit_retained_journal_sources` freshly opens the unchanged hypothesis journal
and requires an independently caller-pinned journal head **and** event count.
It therefore refuses an internally valid older journal image when the caller
still holds the later expected commitment. This is a separate receipt, not new
columns or a rewrite of the old journal format.

For this bounded quote-only engineering path, the new journal/plan source-set
commitment must equal the retained book-bundle seal. All arm source/evidence
policies must match. Every non-null journal quote must uniquely match an exact
retained native-derived quote and pass original plan/symbol/age/causal checks.
Distinct native originals producing the same generic quote are ambiguous and
refused rather than guessed. Null quotes remain null; terminal attempts cannot
be resurrected. Returned matches bind original frame sequence/binding, visible
prefix, source-file retention and the expected journal head/count.

This helper is **not** a complete bars/news/macro/model source-set manifest or
campaign acceptance. Additional source and roster qualification is still needed
before a complete-system test. It does not retroactively give old journals native
origin evidence or prove publisher authenticity, authenticated clocks, an absence
of upstream dropped messages or an episode's complete market denominator.

Caller expectations must be retained separately. Coordinated replacement of
the file **and** its seal/receipt, or of the journal **and** the expected head/count,
cannot be detected here. Local hashes are not independent signed anchors. Every
receipt remains `risk_authority=NONE`, structural-prefix coverage only and
caller-attested native times. No provider/source trust is promoted by success.

## Preserved boundaries

Existing native parser, quote/fill checks, hypothesis v2/journal, scenario and
bridge bytes are unchanged. Native contracts/producer, dependency pins/locks,
release manifest, old Trial 15/V4/V5 plans/ledgers/results remain unchanged.
Adding this research module intentionally changes future installed journal
identity; old sealed journals/packages are not resealed or adopted afterward.

Only synthetic fixtures are exercised. No real market corpus is collected,
imported or accepted. There is no recorder/socket/download process, paid API,
publisher, outbox/consumer, sizing/order/position or live execution path. No
EVEDEX/canary/LIVE, Docker PAPER or primary database/recovery/lease/cursor changes
occur. Risk caps remain 0.25% per trade and 1% aggregate. All readiness flags
remain false and `STRATEGY_POLICY=REJECT_ALL`.

## Verification

Fresh non-editable wheel environments are retained in
`D:\Kairos\runtime\raw-book-bundle-build-20261009`, with Python 3.11.15 and 3.14.7.
All **76 new synthetic cases passed in each**, with warnings treated as errors:
exact byte retention/reopen/restore, full-prefix/capacity/TTL guards, caller-seal
and receipt conflicts, malformed/tampered/truncated/reordered input, failed
persistence/no overwrite, ambiguous originals, missingness/no resurrection,
independent journal rollback commitments and LONG/SHORT retained-source to
journal to supplied simulated-fill checks. Symlink refusal is exercised where
the OS grants fixture creation; no new skipped tests were added.

Both installed module byte hashes match checkout:
`9aa55d8986a62c84af3a929f848a86bb8ad020bb0cb84d7be0b97e9a8f7c46e8`.
Ruff lint/format (126 files), unchanged lock, fresh wheel/sdist, Meta static
manifest/local Markdown/checkout identity regressions and git diff checks passed.
Previously receipted scenario/v2/journal/quote/fill/native binding byte hashes
remain unchanged. Full regression and signed-main hosted identities are
recorded separately after their completion; these fixture checks are not
historical provenance, fill/venue performance or runtime release qualification.
