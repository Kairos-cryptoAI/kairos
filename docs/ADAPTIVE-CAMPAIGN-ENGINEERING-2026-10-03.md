# Adaptive/LLM campaign: инженерная приёмка, 3 октября 2026

## Статус и границы документа

Это отдельная приёмка инженерного контура заранее зарегистрированного matched A/B,
а не приёмка всей системы Kairos или доказательство торговой эффективности.
Публикация документа не обновляет release manifest и не разрешает запуск PAPER,
платных моделей или LIVE. Прежние исследовательские планы и отчёты не изменяются.
Current-release manifest намеренно не обновлён в этом узком scope; приёмка
полного release source set остаётся отдельным незавершённым этапом.

Подтверждены подписанные опубликованные Persistence и окончательный LLM source
`ea00b56…`, включая v2 reconcile guard и изоляцию input evaluator, и свежая QA
матрица Python 3.11/3.14. Exact CI окончательного LLM прошёл, включая фактически
выполненный native target без skip. Оба локальных PostgreSQL targets выполнены
на окончательных installed wheels без skip; source/wheel/OCI/override binding
и cleanup независимо проверены. **Scoped инженерная приёмка ACCEPTED.**
Сама экономическая Adaptive/LLM matched A/B-кампания **NOT COMPLETE**: этот PASS
закрывает инженерную предпосылку, а не её торговую квалификацию.

| Доказательство | Зафиксированное состояние |
| --- | --- |
| Persistence, подписанный `main` | `f82b405646498c246c04e2633c53355f3d9adc03`, опубликован |
| Persistence GitHub CI | [run 37126845678](https://github.com/Kairos-cryptoAI/kairos-persistence/actions/runs/37126845678), PASS; campaign native test выполнен, не пропущен |
| LLM, подписанный опубликованный окончательный source | `ea00b560b21d8afa1c956d9b76ff7c60e4f11d75`, зависимость Persistence `f82b405…` |
| Exact LLM GitHub CI | [run 37128676741](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37128676741), PASS; Ubuntu 3.11/3.14, Windows 3.11 и native job `111219167171` прошли |
| Свежий автономный Windows QA | Python 3.11: 246 PASS / 6 skip; Python 3.14: 246 PASS / 6 skip; Ruff, format, mypy, Bandit, lock и build PASS |
| Локальный нативный target Persistence | **ACCEPTED**: collected 1 / passed 1 / failed 0 / skipped 0; окончательный source/wheel binding и cleanup проверены |
| Локальный нативный target LLM | **ACCEPTED**: collected 1 / passed 1 / failed 0 / skipped 0; окончательный source/wheel binding и cleanup проверены |
| Ограниченная инженерная приёмка campaign | **ACCEPTED**, без полномочий PAPER/LIVE |
| Экономическая Adaptive/LLM matched A/B-кампания | **NOT COMPLETE / NOT QUALIFIED** |
| Общая торговая квалификация и полный production release | **NOT QUALIFIED** |

CI target Persistence:
`tests/test_research_campaign.py::test_native_campaign_preregistration_actual_capture_claim_race_and_immutable_denominator`.
Для него в существующем отдельном PostgreSQL job создаётся campaign-БД с UUID4;
проверка JUnit требует ровно один непропущенный успешный результат этого target.
Успех других integration-тестов не заменяет эту проверку.

В новом LLM CI job предусмотрены отдельный PostgreSQL 16 service, точный immutable
image digest и только target
`tests/test_campaign.py::test_native_three_arm_scheduler_and_restart_on_explicit_disposable_campaign_db`.
Helper проверяет явную локальную UUID4-БД, фактическое имя/роль/версию и отсутствие
public-объектов до миграций; применяется только `RESEARCH_CAMPAIGN` profile.
Один PASS без skip проверяется отдельно. Exact CI `ea00b56…` подтвердил успешную
подготовку schema, `1 passed` этого target и `CAMPAIGN_NATIVE_CI_PASS` финального
guard. Отдельный локальный source-bound proof принят ниже; hosted CI и локальная
приёмка остаются самостоятельными доказательствами.

Свежий автономный QA receipt с обеими поправками:
`D:/Kairos/runtime/adaptive-campaign-20261003/llm-input-isolation-qa-20261003T140816Z.json`,
SHA256 `3810f4799fb6955122dfe872ab6f87a0a42834aa8e1a7fe82a1cc7d2187dc2a3`.
Проверенный в этой QA LLM module SHA256:
`90631aee5eeb019c6a9c4015daa54105062b588380f37d3d94be6fcd0344aba9`;
test SHA256: `89a6ef68b61fb0891df1c6562de645ab391761419631272552f3bf7ed976d627`.
В обеих средах реально установлен Git Persistence `f82b405…`; LLM установлен
non-editable current-source wheel без development `PYTHONPATH`. Во время этой
QA он имел `file://` provenance: это не receipt установки опубликованного Git
`ea00b56…`. Публикация и окончательный hosted/native proof являются отдельными
доказательствами. Шесть skip в каждой автономной матрице не выдаются за native
PASS. Canonicalization установленного module — только CRLF → LF.

## Что обеспечивает обновлённая инженерная политика v2

Три ветви одного зарегистрированного окна сохраняют общий причинно допустимый
source bundle и один независимо сохранённый результат baseline evaluator:

- `strategy-only` — результат стратегии либо `NO_INTENT`;
- `strategy-review` — отдельный review `ALLOW` / `VETO` / `DEFER`; при отсутствии
  strategy intent review не вызывается;
- `llm-proposal-research` — отдельное предложение кандидата, в том числе когда
  стратегия не выдала intent. Предложение не становится ордером.

Замороженные plan, schedule, candidate protocol, prompt, route и идентичности
источников проверяются на границах типизированного repository API. В частности:

1. Review и proposal должны использовать точный замороженный backend:
   `resolved_model` равен зарегистрированному `requested_model`; непустое имя
   произвольной другой модели больше не считается достаточным соответствием.
2. Завершение связывается с независимо сохранённым durable `START`, его route,
   prompt, reservation и причинными данными. Локальный completion clock ограничен
   заранее заданным допуском `maximum_clock_skew_ms`. Это допуск ±skew, а не
   обещание нулевого расхождения часов.
3. Для своевременности результата авторитетен фактический PostgreSQL
   `recorded_at_ts_ms`. Если запись completion произошла после frozen pairing
   cutoff, более ранний локальный timestamp не превращает её в своевременную.
   Поздние фактические completion/cost receipts не теряются и не переписывают
   уже сохранённый arm outcome.
4. После independently stored `START` неизвестный исход не разрешает повторный
   provider dispatch. При cutoff reconciliation фиксирует неопределённость,
   включая удержанный reservation, вместо фабрикации успеха или повторной попытки.
5. Denominator включает каждое зарегистрированное окно и все три arms, в том
   числе `NO_INTENT`, пропуски, ошибки и `UNKNOWN`. При replay сохранённого seal
   повторно проверяются plan/mode, полный roster, count, digest outcome receipts,
   status counts и число UNKNOWN. Несовпадение отклоняется без reseal или dispatch.
6. Прямой `reconcile` проверяет точный preregistered v2 scheduler fingerprint
   до чтения часов/pending claims и финализации. Три отрицательные регрессии
   проверяют чужую identity, прежнюю v1 и настоящий offline CLI handler:
   нет outcome/writer mutation, evaluator, budget или provider calls.
   Чужая/v1-кампания не принимается и не переписывается.
7. Evaluator получает независимые deep copies source receipts. Review сохраняет
   originals, proposal независимо загружает saved bundle из PG. Регрессия
   evaluator меняет top-level значение и nested list во всех receipts:
   оба model prompts сохраняют original content/canonical hashes, общий
   bundle/evaluation и три denominator outcomes. Shallow freezing не считается
   защитой nested JSON от mutation.

Обозначение v2 относится к политике scheduler/repository и её acceptance
регрессиям. Оно не означает переписывание миграции 027 или принятие прежних
результатов исследований в новую кампанию.

## Принятое локальное PostgreSQL-доказательство

Окончательный двухцелевой native proof выполнен один раз на отдельной disposable
test-БД, без реальных feeds, provider/venue calls, торговых сервисов и первичных
runtime-данных. Оба targets дали collected 1 / passed 1 / failed 0 / skipped 0.
Подтверждены точные опубликованные source revisions, test hashes, фактически
установленные signed-archive wheels, immutable OCI и reviewed launcher.

Созданные receipts сохраняются отдельно и не переписывают промежуточные отказы:

- Outer Windows Job receipt:
  `D:/Kairos/runtime/short-engineering-20261003/wheel-campaign-outer-3bb5a82020254dfba7f7a87716d8ceb2/receipt.json`,
  SHA256 `f7200b6ded5955158ec24fce655c85ae3c5d1ea81e0e4dd81e7fcf4ab4c70c63`.
  PASS, 73,64 секунды при максимуме 248; нет timeout, overflow или automatic retry;
  Windows owned processes после завершения — 0.
- Child receipt:
  `D:/Kairos/runtime/isolated-wheel-client-20261003/run-604f72990c4f48f794559e8afcdb78e1/receipt.json`,
  SHA256 `5a843d77fe1f39160792f9d2f5b012ab76d93f7554f78d4d8a2ac58e0828a5d2`.
  PASS, `cleanup_verified=true`; bundle SHA до/после совпадает.
- Worker result:
  `D:/Kairos/runtime/isolated-wheel-client-20261003/run-604f72990c4f48f794559e8afcdb78e1/worker.result.json`,
  SHA256 `eeb38a2778a786143ca35f0fa3b11101a56b14e2b04df3e906cdb343f0ea73f7`.
  PASS обоих targets; неправильный пароль отклонён, credentials не сохранены,
  provider/venue calls — 0.
- Окончательный source lock:
  `D:/Kairos/runtime/isolated-wheel-client-20261003/bundle-a810c8a9a2264eb58eb2f3b7220e74ad/source-lock.json`,
  SHA256 `9ab019348f40a702bada885f3375a9d354ced45283672d542e008c3e755b6d68`.

Установлены четыре пакета с provenance
`SIGNED_GIT_ARCHIVE_TO_HASH_BOUND_PURE_WHEEL`: Persistence
`f82b405646498c246c04e2633c53355f3d9adc03`, LLM
`ea00b560b21d8afa1c956d9b76ff7c60e4f11d75`, Core
`56df50787eff83c898aa2aeefb426c6ee8482820` и Execution
`79d6cd8d38c5e30f5354a6f6be224f68351a25aa`.
Persistence campaign module canonical SHA256:
`4816ad432b3fd99d54fa2add3364e75a042c084f4b54a805a47eab4722bb3a4d`;
его native test SHA256:
`5ee8d40db01183010fd76ddbb2508562e2d880f4cae37221b28bba7e3f415612`.
LLM module/test hashes совпадают с указанными в окончательной QA выше.

PostgreSQL image:
`timescale/timescaledb:2.29.1-pg16@sha256:252a443e2936039b83dd8da1373d01e59e932d1054fa6adf1bc061f1d56ae60a`;
client runner digest:
`sha256:2e10e9e936eae3a4a411f65d8b0bd14670ba808368eeff94b4e24021aa291077`.
Фактические image IDs совпали. Baked OCI source label runner остаётся прежним
`1ca8bf…`: здесь image предоставляет OS/runtime, а provenance окончательного
business code обеспечивают подписанные архивы и фактически установленные
hash-bound wheels. Новый OCI image в этой приёмке не собирался.

Для этого локального four-wheel engineering closure явно записан task-only
override Persistence к `f82b405…`: опубликованный Execution `79d6cd8…` сохраняет
production pin `7170cd0…`. Override не меняет production Execution pin и не
принимает полный release source set. Его pure guards и metadata checks не
подменяют отдельный фактически выполненный native proof.

Cleanup проверен также независимо: owned Docker containers/networks отсутствуют,
execution lease отсутствует; primary PostgreSQL и Redis оставались остановлены
до и после proof. Это не receipt восстановления primary runtime.

Persistence target проверяет реальную регистрацию и capture, PostgreSQL claim
race, shared causal provenance, три outcomes и append-only/denominator поведение.
LLM target фактически подтвердил:

- matched baseline/review/proposal с реальными PG receipts;
- настоящего закрытия и открытия нового подключения, нового repository,
  scheduler, evaluator и gateway; replay sealed результата без новых calls;
- `NO_INTENT` у baseline/review при сохранённой отдельной proposal-ветви;
- durable незавершённого `START`, его сохранности после reconnect, ожидания
  реального DB cutoff и UNKNOWN reconciliation без resend.

Несмотря на native PASS, ответы модели, baseline evaluator и budget в этом acceptance
target остаются синтетическими doubles. Закрытие/открытие подключения не является
доказательством OS process kill, сбоя питания или восстановления primary runtime.
Оно также не квалифицирует общий реальный durable monthly budget.

## Граница доверия SQL и стоимость seal

Семантические/provenance проверки выше относятся к типизированному application
writer API. Native PostgreSQL triggers и constraints дают свои once-claim,
append-only и связующие ограничения, но не доказывают полную эквивалентность
прямого SQL INSERT всем repository-проверкам.

Пользователь БД с правом произвольного INSERT остаётся доверенным writer. Receipt
не делает такие полномочия безопасными для недоверенного клиента и не доказывает
защиту от сфабрикованной этим writer научной истории. Новый privilege profile или
расширение SQL semantic guards не входят в данную приёмку; миграция 027 здесь не
меняется. Browser/provider не получают прямого writer-доступа через этот контур.

Cost totals сохранённого denominator — **point-in-time snapshot**. Поздние
реальные cost/completion receipts могут добавляться после seal, поэтому нельзя
выдавать текущую сумму ledger за точную реконструкцию первоначального снимка.
Повторная проверка неизменных outcomes не переписывает эту историческую стоимость
и не снимает удержания неопределённых попыток.

## Что остаётся неквалифицированным

- Production evaluator с зафиксированной стратегией и реальными inputs:
  фактические Text/Macro/Router producers ещё не приняты как полный production
  input path этой campaign. Отдельные contract proofs не заменяют такой hookup.
- Заморозка конкретного нового baseline/evaluator, всех research routes/prompts,
  источников и evaluator до собственной blind-кампании.
- Реальный общий durable budget, фактические provider costs/latency/availability
  и приёмка модельных маршрутов на matched сигналах.
- Полная торговая simulation с комиссиями, funding, spread, slippage, задержками
  и естественным закрытием сделок; переход кандидата через обязательные risk и
  venue gates, а не предоставление LLM особых торговых полномочий.
- Собственная экономическая matched A/B-квалификация новой линии: не менее
  365 blind-дней и 500 естественно закрытых simulated trades, существующие
  drawdown/profit-factor gates и заранее замороженный bearish/crash gate.
  Нативные acceptance fixtures не дают blind-дней, сделок или crash PASS.

Наличие engineering PASS не обещает предсказание любого обвала или фиксированную
доходность. Blind performance в этом документе отсутствует. Risk ceilings не
повышаются: максимум 0,25% риска на сделку и 1% совокупного открытого риска.

`PAPER_QUALIFIED=false`, `ALPHA_READY=false`, `LIVE_READY=false`,
`STRATEGY_POLICY=REJECT_ALL` сохраняются. Этот документ сам по себе не принимает
общий release source set, не завершает runtime recovery и не разрешает LIVE.

## Завершение ограниченного scope и дальнейшая работа

Scoped инженерная приёмка двух targets завершена: окончательные source identities,
installed wheels, hosted/native tests, task-only override и cleanup подтверждены.
Документ подлежит отдельной пропорциональной подписанной публикации; она не
обновляет current-release manifest и не вооружает торговлю.

Далее остаются production input/evaluator integration, фиксация конкретной новой
системы и её собственная экономическая matched A/B-кампания с перечисленными
гейтами. Они **NOT COMPLETE / NOT QUALIFIED**, а не автоматически выполненные
следствия короткого инженерного proof.

## Сохранённые промежуточные доказательства и отказы

Промежуточные source sets не переписываются и не принимаются за окончательный
`ea00b56…`:

- `e478e70dfe9b8cf21d0b30cb0950ef6340239b31`: [CI 37127672823](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37127672823) PASS, native job `111216207099` PASS; QA 242 PASS / 6 skip на каждой версии.
- `eb04b08d0368624074eab9019844a77ff736f8f6`: [CI 37128244768](https://github.com/Kairos-cryptoAI/kairos-llm/actions/runs/37128244768) PASS, native job `111217886624` PASS; QA 245 PASS / 6 skip на каждой версии.

Оба прежних QA receipt сохранены в `D:/Kairos/runtime/adaptive-campaign-20261003/`:
`llm-campaign-v2-qa-20261003T134426Z.json`, SHA256
`eefa194b9f408220ca07993e71d038829b19773246a1ee4a89deda8099db48d4`;
`llm-reconcile-guard-qa-20261003T140029Z.json`, SHA256
`fe15203cc0f60ae646a5c11bdaad1a0907b05ee0d9c2491b321bd4a0f7684013`.
Первый local closure prepare fail-closed отклонил прежний Persistence pin в
Execution до архива/БД/native execution. Этот отказ и промежуточные preparations
с override сохраняются как свои source-specific факты, а не окончательный PASS.
