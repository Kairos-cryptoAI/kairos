# Adaptive/LLM: causal hookup, 3 октября 2026

## Итог и область приёмки

**Scoped инженерное подключение ACCEPTED.** Реализован отдельный opt-in путь:
типизированные сообщения Text/Macro/Market → независимо сохранённый input bundle
→ настоящий зарегистрированный Strategy evaluator → контекст реального Router
→ matched strategy-only / review / proposal → durable outcomes и отдельный causal pair.

Приёмка подтверждает исполняемую связку алгоритмов на инженерных данных, а не
непрерывный production feed, квалификацию платных моделей или доходность.
Экономическая Adaptive/LLM-кампания **NOT COMPLETE / NOT QUALIFIED**.
Новая LIVE-стратегия не выбрана и не заморожена; дни Trial 15 ей не засчитываются.

Точный пятикомпонентный набор находится в
[scoped source identity](../config/adaptive-causal-source-set.json).
Этот документ дополняет, но не переписывает
[прежнюю инженерную приёмку](ADAPTIVE-CAMPAIGN-ENGINEERING-2026-10-03.md).

## Что подключено

1. `CampaignInputCaptureBridge` принимает оригинальные существующие контракты
   `SentimentSignal`, `StrategicAllocation` и `MarketSnapshot`. Сохраняет явные
   source/message/schema/clock и полные canonical bytes, связывает их с конкретным
   заранее зарегистрированным окном. Независимые часы PostgreSQL определяют
   фактическую доступность источника. Будущее, stale, изменённые дубликаты и
   несоответствие scope/hash отклоняются. Никакой подписки или worker по умолчанию.
2. `CausalStrategyEvaluator` независимо загружает полный заявленный immutable
   window и вызывает неизменённый настоящий `generate_runtime_strategy_intents`.
   Результат на anchor close должен быть единственным и byte-identical исходному
   intent, включая bar hashes, config/source provenance, decision clock и expiry.
   Отсутствие достаточного прогрева — ошибка подготовки, а не `NO_INTENT`.
3. Readiness нового адаптера проверяет реальные полные UTC frames и конкретные
   finite lookbacks шести поддерживаемых sleeves. Orderflow считает прогрев после
   последнего zero-volume reset. QuarterHour и RegimeRetest явно неподдерживаемы
   этим адаптером до отдельной reviewed policy. Registered минимум RegimeAligned
   `48060` сохранён. Это не утверждение EMA convergence или эквивалентности любой
   более длинной истории; текущие registry/config/generators не меняются.
4. `CausalReviewContextProjector` использует настоящий pure `SignalWindow` и
   `classify_candidate`. Сохраняет news IDs, confidence/bias, macro и conflict tier
   на позднем context cutoff. Не создаёт backdated `CandidateRoute`, не выбирает
   незарегистрированную модель. Новости другого обязательного актива не становятся
   BTC conflict; specific neutral/low-confidence evidence не заменяется broadcast.
5. `CausalAdaptiveCampaignScheduler` связывает общий frozen bundle и один evaluation
   с тремя arms. При `NO_INTENT` review не вызывается, но отдельное LLM-предложение
   может наблюдаться. Оно остаётся исследовательским кандидатом, не ордером или
   `RiskTradeDecision`. Все зарегистрированные окна остаются в denominator,
   включая missing, late, errors и unknown.
6. Новый repository opt-in требует точного собственного scheduler artifact.
   Отдельные `ResearchCausalStrategyEvaluationReceiptV1` и
   `ResearchCausalPairReceiptV1` сохраняют три разных времени: настоящий bar close,
   более поздний context cutoff и фактическую DB-запись. Последний bar hash не
   подменяется hash всего контекста. Новой паре не присваивается legacy Core V1
   sample/seal identity; старый replay явно отвергает другую clock family.

## Гейты, бюджет и изоляция

Новое семейство использует conservative `CEIL` миллисекунд фактической DB-записи;
старое default поведение `FLOOR` не меняется. Late evaluation отслеживается и до
provider dispatch, и при финализации. `START` фиксируется до вызова модели;
после него неопределённый исход не разрешает resend. Completion/pair проверяются
по independently stored source/evaluation/attempt/terminal и фактическим DB clocks.

Нужен существующий `CampaignLLMUsageBudget` над общим qualification ledger;
новая связка не создаёт, не обнуляет и не повышает исторический бюджет. OpenAI-only
и exact preregistered backend сохраняются. В коротких acceptance fixtures
underlying budget I/O подменён явно и **не квалифицирует реальные накопленные
расходы**. Платные вызовы здесь отсутствовали.

PostgreSQL skill повлиял на границы реализации: короткие repository transactions,
явный отдельный disposable target и отсутствие DB-доступа у provider/browser.
Новый native test лишь проверяет заранее подготовленный schema; CI helper
допускает только свежую локальную UUID4-БД PostgreSQL 16 и campaign-only profile.
Миграции primary и прежние SQL migration files не изменяются.

Typed writer API проверяет provenance, но произвольный SQL writer остаётся
доверенным. Reconnect не выдаётся за OS process kill, сбой питания или runtime
recovery. Fixtures не дают blind-дней, естественно закрытых сделок или alpha PASS.

## Проверенное доказательство

| Компонент | Подписанный опубликованный main | Exact CI |
| --- | --- | --- |
| Persistence | `695fcc22515bc73d7ac92e6c593ec8f08ceb9605` | [37133909687](https://github.com/Kairos-cryptoAI/kairos-persistence/actions/runs/37133909687), PASS |
| Strategy | `4b06f78750aacc838a16c96cc6038faf5ba3599b` | [37134512694](https://github.com/Kairos-cryptoAI/kairos-strategy-engine/actions/runs/37134512694), PASS |
| Router, только dependency pin | `6025cd1ce7e818181e51be000198db477b0395d4` | [37135086487](https://github.com/Kairos-cryptoAI/kairos-router/actions/runs/37135086487), PASS |
| LLM | `e4781813105a5a43096e6c6b6c07808a4d1748d1` | [37135523483](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37135523483), PASS |

Core остаётся `56df50787eff83c898aa2aeefb426c6ee8482820`; новый Core contract или
миграция не добавлялись. Четыре изменения опубликованы отдельными GPG-signed
коммитами с exact fingerprint `40AF365C6682B73D056A6A274DBFF6B65BE9F827`.
LLM lock закрепляет именно эти Persistence/Strategy/Router Git revisions.
Router pin согласован из-за настоящего transitive Git URL conflict; Router logic
не менялась. Type check теперь явно использует соответствующую Python matrix
version, включая валидные для 3.14 NumPy stubs; проверка 3.11 остаётся отдельной.

Свежая Windows QA Python 3.11 / 3.14:

- Persistence: на каждой версии 504 PASS / 1 skip / 34 integration deselected;
  causal-focused 58 PASS, producer-focused 96 PASS.
- Strategy: на каждой версии 409 PASS / 0 skip.
- Router: на каждой версии 55 PASS / 0 skip.
- LLM: на каждой версии 272 PASS / 6 skip. Эти шесть opt-in DB skips **не** native PASS.
- Ruff, format, mypy, Bandit, locked check и wheel/sdist build прошли.

QA Strategy/Router/LLM выполнена в свежих task-owned locked non-editable
окружениях; опубликованные Git dependency revisions и canonical hashes
установленных LLM modules проверены отдельно. Это current-source QA, не полный
production release. Receipt:
`D:/Kairos/runtime/causal-hookup-20261003/windows-qa.json`, SHA256
`c5cc83e816f4401196f03509dec1a86db08120c1d7bb36bec921c3b20d400bd6`.
Persistence QA относится к своему final source slice; installed dependency
cascade дополнительно проверена downstream Strategy/Router/LLM и exact CI.

Новый target:
`tests/test_causal_campaign_native.py::test_native_causal_producer_strategy_router_pair_and_restart_on_explicit_disposable_campaign_db`.
Точный test SHA256:
`dc7a79fa0bd4e6e89ea93a69c2f28acc8f10bb0a4a4853f7dac574a035ee1128`.

[Новый native job 111239162854](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37135523483/job/111239162854)
подтвердил `1 passed in 8.71s`, separate exact-result guard
`CAMPAIGN_NATIVE_CI_PASS` и успешный Stop containers. Другой
[legacy native job 111239162825](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37135523483/job/111239162825)
также прошёл независимо; его target/result guard не заменяет новый.

Новый native proof использует отдельный fresh test DB и immutable image
`timescale/timescaledb:2.29.1-pg16@sha256:252a443e2936039b83dd8da1373d01e59e932d1054fa6adf1bc061f1d56ae60a`.
В нём реальные Strategy/Router/capture/repository/pairing algorithms и фактическое
закрытие/повторное открытие PG connection. OHLC, provider и budget I/O явно
fixture-only. Проверены positive и quiet anchors, неизменённые intent bytes,
один bundle/evaluation для трёх arms, START до dispatch, replay без новых calls,
reserves или history evaluations, `NO_INTENT` + advisory proposal и denominator.
Общий timeout 45 секунд; fixture-only ожидание свежего bar boundary до регистрации
ограничено 16 секундами, без retry, изменения TTL или scientific campaign.

Это новый hosted proof, а не повторное использование прежних local native
receipts. В рамках этого подключения local native/торговые сервисы не запускались.

## Что остаётся открытым

1. Dedicated production read-only resolver полного immutable bar window;
   engineering in-memory history не является runtime history recovery.
2. End-to-end provenance raw news/macro inputs и upstream model completion:
   в нынешних derived producer envelopes эти доказательства явно `UNAVAILABLE`,
   не выдумываются. Capture требует исходный aware exact-millisecond clock;
   sub-ms публикации отклоняются, не округляются назад. Требуется отдельный
   versioned producer envelope для непрерывной реальной приёмки этого пути.
3. Выбор и preregistration одной новой adaptive стратегии, evaluator, routes,
   prompts, источников, matched simulation/cost/exit/crash policies. Test-only
   RangeMeanReversion конфигурация не выбрана LIVE-кандидатом.
4. Реальная отдельная provider/feed/budget shadow qualification и экономическая
   blind A/B с не менее 365 собственных дней и 500 естественно закрытых simulated
   trades, заранее заданными drawdown/profit-factor и bearish/crash gates.
5. Общий release dependency cascade и Windows/Docker/CI acceptance всех profiles.
   [Текущий четырнадцатикомпонентный manifest](../config/current-release.json)
   и historical Deploy locks не обновлены частично: shared runtime/PAPER projection
   требует согласованных consumer pins, не только новых gate hashes. **FULL_RELEASE_NOT_ACCEPTED**.

Trial 15, V4/V5 frozen plans/ledgers, прежние receipts и первичный runtime не
переписывались. Providers не получают прав обойти Risk Manager; ceilings 0,25%
на сделку и 1% совокупного риска не повышаются.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`. Нет новых слепых результатов,
PnL-раскрытия, paid API calls, EVEDEX/PAPER/LIVE или обещания доходности.
