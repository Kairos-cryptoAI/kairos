# Kairos: возможности торгового комплекса и согласованность проекта

Дата: 23 октября 2026, Europe/Moscow. Аудит кода и доказательств, не торговый допуск.

Позднее [подключение LIVE Risk и защитных выходов](PRODUCTION-PATH-WIRING-2026-10-23.md)
закрыло инженерный разрыв между отдельными publishers и PROD lifecycle на
изолированной PostgreSQL-проверке. Таблица исходных HEAD и выводы ниже сохраняют
свой момент аудита; они не описывают новый source set. Реальная квалификация
источников/площадки, работающий торговый сервис и прибыльность всё ещё не
подтверждены, readiness остаётся false.

## Вывод

**Нет: пока нельзя утверждать, что Kairos умеет всё необходимое для работы
самостоятельного профессионального трейдера.** Есть значительная часть
аналитических, исследовательских и защитных механизмов. Но непрерывный
production-комплекс и его положительная net-экономика не подтверждены.
«Умеет» здесь не означает «файл существует» или «один fixture прошёл».

Сравнение функциональное: наблюдать рынок, объяснять возможность, выбирать
действие или воздержание, ограничивать риск, исполнить и защитить позицию,
сверить результат. Это не универсальный стандарт профессии и не обещание
предсказаний, прибыли или доходности «супертрейдера».

## Охват и способ проверки

Инвентаризированы все **14 Git-репозиториев: 2 166 tracked-файлов**, включая
1 084 Python-файла и 215 Markdown-файлов, на исходных HEAD ниже. Три независимые
подзадачи покрыли рынок/стратегию/research, Text/Macro/models/Router/review,
Risk/Execution/Persistence/Deploy. Сопоставлены исходная концепция, living docs,
конфиги, основные обработчики, контракты, тесты и датированные результаты,
а не только последние отчёты. Root перепроверил спорные выводы по актуальным
веткам вызовов: legacy sizing нельзя выдавать за PAPER sizing, а generic
DRY_RUN decider — за CURRENT v3 arbitration.

Это **не построчное ревью всех файлов**, не exhaustive security audit и не
повторный торговый тест. Массовые архивы рынка, секреты, содержимое ключей,
игнорируемые окружения и frozen blind PnL не читались. В этом аудите не
запускались модели, стратегии, consumers, торговля или восстановление БД.
Проверки исходной идентичности и статические документационные проверки —
отдельные неэкономические результаты.

| Репозиторий | HEAD при начале аудита | Tracked | Роль в проверке |
| --- | --- | ---: | --- |
| kairos | ff16e73 | 957 | концепция, текущая композиция, orchestration и receipts |
| kairos-core | ff3af75 | 66 | contracts, clocks, identities, bus |
| kairos-quant-scouts | cbd8e60 | 48 | свечи, признаки, книга, деривативы |
| kairos-strategy-engine | 30d1315 | 70 | генераторы, adaptive, runtime parity |
| kairos-text-scouts | 23654f1 | 49 | новости, фильтры, происхождение, extraction |
| kairos-router | e7c7ddd | 24 | workload/conflict routing |
| kairos-llm | f67ca20 | 44 | модели, бюджеты, provider provenance |
| kairos-aggregator | edff2f5 | 34 | immutable candidate review |
| kairos-macro-strategist | 91af931 | 31 | allocation, доступность факторов |
| kairos-risk-manager | 4eb6de5 | 43 | sizing, лимиты, account/venue admission |
| kairos-execution-engine | 3fa6dd2 | 131 | lifecycle, custody, PROD composition |
| kairos-persistence | c677357 | 119 | journals, inbox/outbox, accounting |
| kairos-backtest | da12378 | 225 | parity, исторические исследования и ограничения |
| kairos-deploy | 626a3be | 325 | source projections, gates, recovery, operations |

Все 14 checkout были чистыми на main. Полные SHAs и правила проверки подписей/
origin/main находятся в [source manifest](../config/current-release.json).
Meta HEAD выше — начало аудита, не самоссылочная идентичность этого документа.

## Одна согласованная логика

```text
рынок 1m..1h + книга/деривативы + новости + доступный Macro
                         ↓
             причинный контекст с версиями и clocks
                         ↓
     технический кандидат       независимая LLM-гипотеза
                         ↓
             детерминированный выбор/воздержание
                         ↓
                review неизменного плана
                         ↓
      новое рыночное подтверждение + свежая котировка
                         ↓
             независимый Risk + текущий счёт
                         ↓
        исполнение → защита → выход → reconciliation
                         ↓
          журнал, издержки, пропущенные возможности
```

Это целевой процесс. CURRENT v3 реализует ограниченную SIM-проверку существенной
части этой цепочки; непрерывный PROD-сервис из схемы не следует. Macro allocation
ограничивает капитал, но не создаёт ордер. Router выбирает workload, не quantity.
Модельное ALLOW разрешает искать подтверждение, а не отправлять заявку.

### Ситуации, о которых спрашивал владелец

| Ситуация | CURRENT v3, не гипотетическое пожелание |
| --- | --- |
| Technical NO_INTENT, но есть допустимая контекстная идея | Возможен CONTEXT_ONLY; отсутствие технического кандидата не равно глобальному veto |
| Technical и context дают одну сторону | SAME_SIDE_TECHNICAL_PRIORITY, без удвоения позиции |
| Кандидаты противоположны | OPPOSITE_TECHNICAL_CONTEXT_ABSTAIN |
| Review VETO/DEFER, stale/неполные данные, невалидная геометрия | Нет исполнимого входа; LLM не меняет защиту и не обходит Risk |
| Нет подходящего повода | Ноль сделок допустим; квоты 2–3 сделки/день нет |

Проверено по [выбору origin](../development/native_campaign/kairos_native_campaign/current_plan_runner.py)
(`run_one_plan_cut`, строки 833–941 на исходном HEAD) и
[plan/review/entry authorization](../development/native_campaign/kairos_native_campaign/current_plan.py).
Различаются NO_INTENT, UNAVAILABLE, отказ review и неизвестный внешний эффект.
CONTEXT_ONLY также требует допустимых Text/event/Macro inputs, успешного mapper,
review, рыночного подтверждения и независимого Risk. Не следует менять это на
«стратегия всегда главнее LLM» или «LLM всегда может
переубедить стратегию». CURRENT v3 не является четырёхсчётным matched A/B.

## Матрица возможностей

| Функция | Что действительно есть | Что пока не доказано / не завершено |
| --- | --- | --- |
| Мульти-ТФ рынок и режим | Полные закрытые 1m, причинные агрегации, adaptive 5m/15m/1h, BULL/BEAR/RANGE/UNCERTAIN и shock defense | Универсальное понимание рынка и надёжное предсказание crash; adaptive использует конечные правила, не все собираемые Quant-факторы |
| Ликвидность и деривативы | Top-book/depth/spread, funding/OI, ограниченные forceOrder-наблюдения | Полная лента ликвидаций, институциональные намерения, перенос Binance liquidity на EVEDEX |
| Новости | RSS/GDELT и другие реализованные adapters; relevance/freshness/dedup, source provenance; Catalyst имеет версионированные события | Достаточность охвата для выбранной trading policy, сквозная отработка опровержений/ревизий до открытой позиции, качество понимания слухов и already-priced-in событий |
| Macro | Модельная allocation; CURRENT получает ограниченный официальный Fed/BLS capture с честными unavailable полями | Полный release calendar, согласованные surprise/consensus/on-chain данные и их incremental value; generic Macro bus и CURRENT capture не один путь |
| Технические и LLM-возможности | Обе ветки есть в исследовательском CURRENT; геометрия детерминирована, направление review неизменно | Одна квалифицированная production identity и непрерывный publisher/orchestrator; legacy registry остаётся пустым для торговли |
| Выбор, ожидание, конфликт | NO_INTENT, VETO/DEFER, first-trigger consumption, expiry, opposite-side abstention | Положительная экономика этих отказов и missed winners; отсутствие сделки само по себе не alpha |
| Риск | PAPER loss-at-stop sizing с fee/slippage и account/open-risk caps; SIM и PROD имеют отдельные contracts | Авторитетный deployed PROD risk/exposure/PnL producer; подтверждённое действие дневного стопа в PROD |
| Ведение позиции | Защищённый PAPER/SIM lifecycle, partial fills, SL/TP/timeout/cancel/restart механика и journals | Полный PROD lifecycle на действительной площадке; свободное LLM-ведение, произвольный trailing, пирамидинг и thesis-driven выход не допущены |
| Учёт и обучение | Durable evidence, издержки, research comparisons, allocation history, replay и recovery | Валидированное самообучение/автотюнинг или автоматический рост капитала; история решений не равна обучению модели |
| Работа без человека | Новый неторговый runtime прошёл bounded recovery/restart; Telegram delivery проверялась отдельно | Полный непрерывный trading runtime, его точные boot/alert bindings и целевой host acceptance; чужой старый notifier не покрывает нового owner |
| Финансовый результат | Есть исследования и отрицательные/неполные результаты, сохраняются контроли | Независимо доказанный устойчивый net edge всего актуального комплекса, matched A/B и принятая blind qualification |

### Не смешивать три risk-пути

| Путь | Реальная семантика | Нельзя выдавать за |
| --- | --- | --- |
| Legacy RiskPipeline / TacticalCommand | Equity/notional-budget sizing, вход не содержит stop distance | Stop-calibrated PAPER либо PROD authority |
| PaperRiskPipeline / CandidateReviewV1 | Quantity из loss budget / adverse loss-per-unit, затем account/venue/exposure caps | Квалифицированный PROD risk producer |
| SimulationRiskPolicy / native SIM | Проверка переданного research quantity и участия в записанной книге; CURRENT дополнительно ограничивает stop-risk запроса | Реальный reconciled счёт и production sizing |

Исходники: [PAPER sizing](https://github.com/Kairos-cryptoAI/kairos-risk-manager/blob/4eb6de55ee68d742b2583932c2e0d8f98b65949d/kairos_risk/paper.py#L194),
[его adverse loss-per-unit](https://github.com/Kairos-cryptoAI/kairos-risk-manager/blob/4eb6de55ee68d742b2583932c2e0d8f98b65949d/kairos_risk/paper.py#L493),
[legacy helper](https://github.com/Kairos-cryptoAI/kairos-risk-manager/blob/4eb6de55ee68d742b2583932c2e0d8f98b65949d/kairos_risk/sizing.py#L16),
[SIM policy](https://github.com/Kairos-cryptoAI/kairos-risk-manager/blob/4eb6de55ee68d742b2583932c2e0d8f98b65949d/kairos_risk/simulation.py#L40).

## Ключевые незакрытые части, без новых направлений

1. **Одна production-композиция из существующих компонентов.** LIVE пока
   отклоняется конфигом/factory. `ProductionExecutionRuntime` — один эффект;
   ответ TRANSPORT_RESPONSE_UNRECONCILED и lifecycle_complete=false не являются
   подтверждением ордера, fill или закрытия. Последующее
   [engineering-продолжение](PRODUCTION-LIFECYCLE-2026-10-23.md) связывает
   существующий lifecycle с managed-путём и terminal evidence и проверяет native
   PostgreSQL fixture. Это ещё не действительный PROD lifecycle на EVEDEX.
   [Следующее продолжение](PRODUCTION-SOURCES-ACCOUNTING-2026-10-23.md) добавляет
   транспорт закреплённого SDK, сбор исходной истории и освобождение резерва
   в отдельной свежей схеме после принятой сверки. Реальная история пока не
   доказывает exposure/settlement authority. Последующее
   [продолжение LIVE Risk](PRODUCTION-LIVE-RISK-2026-10-23.md) добавляет отдельный
   opt-in evaluator/publisher; реальный источник счёта и deployed LIVE-путь
   этим не квалифицированы.
2. **Текущий авторитетный риск и обратная связь счёта.** Реальный GET-only
   PROD read прошёл, но последовательность REST-ответов не atomic snapshot и
   не ExposureSnapshot authority. Резервации нельзя освобождать по HTTP ACK,
   локальному timeout или предположению. Дневной стоп 1% и 1x — подготовленные
   условия будущего теста, не доказательство уже работающего PROD-ограничителя.
3. **Точная production policy и её допуск.** Старые pure стратегии, новый
   adaptive control, Catalyst research и CURRENT v3 — не одна автоматически
   разрешённая стратегия. Нужен один выбранный contract/source set, без
   одновременного включения всех перебранных вариантов. Качество стратегии
   оценивается также по пользе для всего комплекса, не только standalone PnL.
4. **Доказательство работы текущего целого, а не сумма PASS компонентов.**
   Реальная CURRENT news/model/Risk/native-SIM entry и естественный полный
   lifecycle пока не приняты. Прежний owner остановил ожидание свежих новостей;
   аудит его не возобновляет и не подменяет этот пробел синтетикой.
5. **Operations того же production source/owner.** История свечей и queue
   recovery не являются recovery торговых позиций. Boot/alert/kill/restart
   должны относиться к принятому контуру, а не к соседней исторической эпохе.

Не превращаем этот список в заказ на все возможные индикаторы, новые LLM,
универсальную новостную БД или ещё один backtester. Обработка редких событий,
пересмотр тезиса и portfolio correlation требуют ровно тех правил, которые
выбраны для конкретной policy; наличие человеческого аналога не делает любое
такое расширение обязательным для первой версии.

## Согласованность документов и режимов

Исправлены living entry points: README, CURRENT_CONCEPT, ARCHITECTURE,
STATUS и READINESS. Они теперь различают:

- классический технический DEV PAPER/canary с его сохранёнными guards;
- отдельный исследовательский CURRENT v3 plan-review-first SIM;
- historical-profile неторговый runtime, не production trading runtime;
- новый single-server PROD target с ещё незавершёнными admission/lifecycle.

Ранее README называл отказ 20 октября последним runtime состоянием и ссылался
на 5 октября как на latest recovery; CURRENT_CONCEPT одновременно исключал и
требовал DEMO/off-host. Эти current-формулировки устранены. Датированные receipts,
каноническая V1 от 14 октября, старые frozen locks/ledgers/evaluators остаются
историческими документами, а не переписываются под новую картину.

В current owner scope DEMO books/campaigns, отдельный off-host backup и cloud
KMS не являются обязательными покупками/engineering gates. Это **не** отменяет
защиту локального signer, restore, реальную venue/account reconciliation и
лимиты. Full-host-loss resilience остаётся недоказанной. Старый PAPER профиль
не ослаблен; альтернативный денежный эксперимент не создаётся этим аудитом.

365 дней / 500 естественных simulated closes остаются политикой исторического
исследовательского LIVE admission. Отдельный ранний эксперимент на деньги
владельца не получил здесь новой версии договора, arm или LIVE_READY=true.
Предыдущий вопрос о таком контракте не считается автоматически отвеченным
запросом на аудит.

## Актуальные bounded доказательства

- [CURRENT v3 engineering/real-source refusal](CURRENT-PLAN-REVIEW-2026-10-23.md):
  plan-first код и fixtures есть; bootstrap отказ не полный E2E.
- [Runtime/production checkpoint](RUNTIME-PRODUCTION-2026-10-23.md): новый owner
  `1ec512799b23422190a1f3360ba60996`, fresh backup/clone restore/amcheck,
  queue qualification, drained restart; реальный account-bound PROD GET-only
  прошёл. Root-cause fix прежнего Redis отказа не заявлен.
- Read-only status в 11:56:41 МСК: RUNNING_NONTRADING, cycles=267,
  source_fresh=true, pending_outbox=unresolved_inbox=uncompleted_publications=0.
  Это один свежий статус, не торговая или длительная uptime qualification.
- Текущие модели в коде согласованы с [ADR 10](adr/0010-openai-only-current-routing.md):
  Luna low — Text, Luna medium — normal review, Sol high — conflict,
  Sol xhigh — Macro. Старые модели в исторических сметах не active defaults.
  «Самые лучшие/дешёвые» и квалифицированный экономический эффект не заявлены.

Сохраняются TECHNICAL_PAPER_READY=false, PAPER_QUALIFIED=false,
ALPHA_READY=false, LIVE_READY=false, STRATEGY_POLICY=REJECT_ALL.
Аудит не выдаёт торговых прав и не меняет ни одну исполняемую policy.
