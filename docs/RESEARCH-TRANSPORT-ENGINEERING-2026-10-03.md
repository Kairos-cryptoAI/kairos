# Kairos: короткий инженерный этап 3 октября 2026

Source-bound отчёт завершённого короткого инженерного этапа. Manifest
`engineering-main-20261003T072035Z` записывает тот же опубликованный source set;
meta использует `SELF`, поэтому его собственный будущий commit не встраивается.
Ни один результат ниже не является доказательством alpha, PAPER-квалификации,
допуска к LIVE или успешного восстановления первичной runtime-БД.

## Подтверждённые изменения

### Канонический arm digest в LLM coordinator

Подписан и опубликован `kairos-llm`
[`0f803a693a103102f1c8d039e59ee73cfcbfd0fd`](https://github.com/Kairos-cryptoAI/kairos-llm/commit/0f803a693a103102f1c8d039e59ee73cfcbfd0fd).
`ResearchProposalCoordinator.replay_sample()` теперь привязывает sample к
`protocol.arm_digest(context.arm_id)` и заново выводит канонический
`sample_record_id` через новый immutable объект. Caller object/identity не
мутируются; остальные независимые causal/source/evaluation проверки сохранены.

Регрессия strict journal отвергает отсутствующий/неверный arm digest и проверяет
полный идемпотентный replay без нового ответа/резервирования. Подтверждены
23 focused-теста и 164 unit-теста; выполнен Windows gate на Python 3.11 и
3.14 — по восемь проверок на каждой версии. Это исправление связывания
инженерных receipt, а не новая стратегия, выбор лучшей модели или scientific pass.

### Опубликованный каскад трёх потребителей

Изменены только Git revision источника LLM и соответствующий lock; постороннего
third-party drift нет. Проверки используют реально установленные опубликованные
Git-пакеты, не подмену через `PYTHONPATH`.

| Репозиторий | Подписанный опубликованный SHA | Windows unit 3.11 / 3.14 |
|---|---|---|
| Aggregator | `e3da76b723435520a5a0198057ca7c1b72cedfb7` | 50 / 50 PASS |
| Macro | `0feecabc6f9d2befeb82e7edc70305efbaf9c2bd` | 79 / 79 PASS; по одному skip |
| Text Scouts | `0022a2e86112cae4c3e641b5a68eca11648603b6` | 90 / 90 PASS |

Для каждого потребителя также прошли uv lock, fresh locked sync, installed Git
identity, Ruff, format, mypy, Bandit и build на обеих версиях Python.
Локальные доказательства:

- Aggregator receipt: `D:/Kairos/runtime/llm-arm-digest-cascade-20261003/gate-kairos-aggregator-0146ce8cbc304a10a630667da2a98053/receipt.json`.
- Macro receipt: `D:/Kairos/runtime/llm-arm-digest-cascade-20261003/gate-kairos-macro-strategist-0f70dcd30954413da2f302d589f333f4/receipt.json`.
- Text receipt: `D:/Kairos/runtime/llm-arm-digest-cascade-20261003/gate-kairos-text-scouts-b9a5fa02073448f48933576d19882301/receipt.json`.

CI audit подтверждает `completed/success` для этих же точных HEAD:

- Aggregator: [CI 37103760468](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/37103760468), [CodeQL 37103760550](https://github.com/Kairos-cryptoAI/kairos-aggregator/actions/runs/37103760550).
- Macro: [CI 37103765044](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/37103765044), [CodeQL 37103764582](https://github.com/Kairos-cryptoAI/kairos-macro-strategist/actions/runs/37103764582).
- Text: [CI 37103769017](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/37103769017), [CodeQL 37103768943](https://github.com/Kairos-cryptoAI/kairos-text-scouts/actions/runs/37103768943).

CodeQL audit относится к Push on main для каждого указанного commit, с Python/
Actions analysis без ошибки. Это не утверждение, что все исторические workflows
зелёные или что весь проект не имеет security findings. Для точного LLM HEAD
`0f803a6…` root также подтвердил green [CI 37102564052](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37102564052)
и [CodeQL 37102563808](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37102563808).

### Пять новых composed full-path cases

В `tests/sim_full_path_gate/test_full_path.py` добавлены:

- Два сценария независимого replay: реальные DB-replayed synthetic Strategy bars
  приводят к `NO_INTENT` против локального LONG bias либо к LONG против SHORT
  bias. Использованы существующие независимые source/evaluation/START/terminal
  receipt API, настоящий coordinator и source-qualified seal. Unknown/late
  sources и чужой evaluator отвергаются; restart не вызывает новый ответ или
  reservation. Другие arms честно `NOT_CALLED`. Никаких risk admission/orders.
- Три durable exit-сценария: TARGET, TIMEOUT и отсутствие свежей exit book.
  PREPARED command сохраняется до логического исполнения, восстанавливается
  после reconnect, а duplicate delivery/recovery не создают повторный fill.
  TIMEOUT сохраняет исходные 72 часа плана и использует синтетический replay
  clock. Без свежей книги старый entry book является stale: нулевая exit fill
  и честный `UNRESOLVED`, без выдуманного закрытия.

Подтверждены 19 pure cases, Ruff/format для затронутых файлов и 28 native
Windows Docker cases, включая девять PostgreSQL-сценариев:
**28 passed in 44.80s**. Hosted full-path gate на том же финальном Deploy
HEAD также завершён success. Во всех случаях gateway локальный/synthetic.

Source-qualified seal имеет только смысл `INDEPENDENT_SOURCE_REPLAY_ONLY`:
это синтетическая инженерная композиция, не production scheduler/feed recorder,
не matched A/B итог, не sealed scientific pass. Local gateway и token/cost
fixture не обращаются к провайдеру и не меняют реальный spend ledger.

### Нативная несовместимость COPY callback и узкое исправление

Малый synthetic native запуск обнаружил фактический `bytearray` от asyncpg:
первый chunk 14 265 bytes был отвергнут до первого завершённого ряда, потому
что `OrderedTextDigest.write()` принимал только точный `bytes`. Это ошибка
предположения в прежнем mock, не доказательство повреждения runtime-данных.

Узкое исправление принимает только точные `bytes`/`bytearray`, проверяет
8 MiB chunk cap до копирования и немедленно замораживает mutable chunk в bytes.
Сохранены framing, UTF-8, C-order, length-prefix digest, row/total/time budgets,
строгий trailer/count, cancellation и rollback semantics. Добавлены split/reuse
и oversized regressions, а mock worker теперь передаёт реальный тип callback.

Границы tiny proof не расширены: только fresh synthetic namespace; по одному
контейнеру БД и worker, 1 CPU и 512 MiB RAM каждому, PID cap 64, DB data tmpfs
256 MiB и temp tmpfs 64 MiB, native deadline 180 секунд и отдельный cleanup
deadline 10 секунд. Никакой скорости полного recovery отсюда не выводится.
Fresh tiny native receipt `run-e937e4…` имеет `PASS_SYNTHETIC_ONLY`: asyncpg
0.31.0, шесть cursor16/COPY equivalence cases и два fault cases — sink failure
и cancellation во время настоящего COPY sink wait. Для обоих fault cases
подтверждён rollback acknowledgment и fresh read-only history, совпадающая с
baseline; final history также совпадает. Owned cleanup и lease release PASS.
Baseline/final SHA256: `d98ed355c242aadad0668460ee2943d7b7062f6ce2bf08974b6547bd91e6216c`.
Всего 16.515 секунды; запрещённых сетевых/провайдерских вызовов — ноль.

Прежний полный runtime proof остаётся failed/непринятым. Frozen runner, старый
RUNTIME17 и исторические receipts не переписываются; SIM25/controlled026 не
подменяют production qualification. Synthetic COPY golden не восстанавливает
primary, не запускает consumers и не принимает legacy quarantine/recovery.

## Принятые инженерные проверки

| Проверка | Статус | Доказательство |
|---|---|---|
| Свежая Deploy unit matrix после bytearray fix | PASS | 323 tests на каждой Python 3.11/3.14, по два существующих skip; source-bound receipt |
| Tiny cursor16/COPY golden | PASS_SYNTHETIC_ONLY | шесть native equivalence cases, два acknowledged fault rollback, свежая read-only history, cleanup и lease release |
| Current-source REJECT_ALL | PASS | семь native cases, 2.31 s, финальный dependency set и owned cleanup |
| Full-path SIM | PASS | 28 native Docker cases, 44.80 s; zero providers/venue; owned cleanup |
| Текущие 13 Deploy проекций | PASS | 27 checks; 11 revision-only changes, две неизменённые PAPER проекции, before/after bytes unchanged |
| Финальный Deploy | PASS | подписан и опубликован `d2f24d198cdbb3f7fdab60a11a57b6cd7cad16c9`; четыре required exact-HEAD hosted runs success |
| Manifest/meta | Source identity only | Manifest привязан к тому же source set; static/source checks проверяются при подписанной публикации, не являются торговым допуском |

Transport commit: `d6dd9fc7ba059d3cefb457373d7d254738d28427`.
Итоговый Deploy commit: `d2f24d198cdbb3f7fdab60a11a57b6cd7cad16c9`.

Принятые локальные receipts и SHA256:

Все пути ниже — локальные файлы под `D:/Kairos/runtime/runtime-transport-20261003/`,
не portable репозиторные ссылки; hosted evidence доступно по CI URL ниже.

- Deploy unit matrix: `20261003T071438Z.deploy-unittest/receipt.json`, SHA256 `9082e905b2e4b96a50964a46bc54dcf876a90302501323f6120d1b07fc499a22`.
- Tiny native: `run-e937e4c03acc43afa6c689f30b8afee1/receipt.json`, SHA256 `3e4a37667147d40346f187ee2ad33a3cc07c52d4286e3ad53da32287f24420be`.
- 27-check projection preparation: `projection-gate-20261003T071716Z-d51cba8ae0544b6fa25e2a54907bca93/receipt.json`, SHA256 `1a75b026c144dabb0d3ce0affc16deca17efb601e9b51c0064738f04f8172bed`.
- Current-source native Docker: `docker-current-20261003T072016Z-847322ed/receipt.json`, SHA256 `e8adbe276e6a2098cb45d5a9a94529076f4f9013d9ebdeb2b8987f60aefa9c18`.
- Full-path native Docker: `docker-fullpath-20261003T072134Z-bb31408e/receipt.json`, SHA256 `1e2260cefdc24e86bb0bce450d624078444a0b80e5961cb07173b9ec0c876b88`.

Для финального Deploy root/CI audit подтвердил `completed/success`:
[CI 37105945534](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37105945534),
[current-release-gate 37105945520](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37105945520),
[simulator-full-path-gate 37105945566](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37105945566),
[CodeQL 37105945587](https://github.com/Kairos-cryptoAI/kairos-deploy/actions/runs/37105945587).
Exact-main CodeQL Python/Actions/JS-TS analysis metadata без ошибки; это не
global security-clean claim. Native current receipt отдельно честно отмечает,
что hard CPU limit BuildKit server и его cancellation не доказаны: serial build
и Windows CLI-tree timeout не подменяют такую ресурсную квалификацию.
Full-path dump содержит только synthetic данные (31 870 082 bytes,
SHA256 `d12d27013da02aff1d04b0ad3f20c43e3c761ef70da4631ba8771bc0ae8c6394`);
его restore **не проверен** и не засчитывается runtime recovery.

Ранние helper/native failures сохранены отдельными receipts; успешный поздний
прогон их не переписывает. Удаление только owned temporary resources подтверждено
для завершённых failed native attempts. Случай до создания ресурсов закрыт
отдельным once-only before-create resolution/lease-release proof, а не общим
заявлением, что первоначальный helper успешно завершил cleanup.

Пример retained failed native receipt:
`run-381e6b5fa02542e9b88ed4702cbd4736/receipt.json` под тем же локальным каталогом.
Отдельный before-create resolution:
`resolution-d4bac0e3535b4a0e834d84f9a0c5d2ec-f15fd5417cc546a186776086a18c54fb/resolution-receipt.json`
и его `lease-release-ack.json` не заменяют старый failure receipt.

Новых paid/provider/venue вызовов, UI-работы, primary/shadow mutations,
перезапусков PAPER, реальных ордеров или раннего раскрытия blind PnL в этом
этапе нет. Trial 15/V4/V5 и frozen исследовательские identities остаются
неизменными. Итоговые `TECHNICAL_PAPER_READY`, `PAPER_QUALIFIED`, `ALPHA_READY`
и `LIVE_READY` остаются false, `STRATEGY_POLICY=REJECT_ALL`.
