# Доступные данные: стратегия против market-only LLM-review

Статус: **исследовательский прогон завершён, преимущества LLM не доказаны**.
Это не тест всего Kairos и не квалификация PAPER/ALPHA/LIVE.

## Что действительно выполнено

Сравнение зафиксировано до API-запросов в отдельном [плане](../development/market_review/plan.json).
Использованы все 12 кандидатов неизменённой `adaptive_pullback_range_v1` из полного
прежнего roster: 17 280 слотов, пять инструментов, четыре фиксированных трёхдневных окна.
SHA-256 исходных tapes проверены; все кандидаты повторно воспроизведены native evaluator
из свечей, закрытых до решения. ZIP/CHECKSUM, непрерывность FULL_KLINE и архивного funding
повторно проверены до и после model-worker. Native стратегия, конфигурация и зависимости
не изменялись. Текущий tracked replay engine используется для учёта затрат/времени;
все 16 baseline-сценариев совпали с исходным завершённым прогоном по сделкам и equity.

Получены **12 настоящих ответов GPT-6 Luna medium** через native `BudgetedLLMGateway`,
без injected client, повторов и изменения общего бюджета. Решения: **ALLOW 9, DEFER 3,
VETO 0**. Учтённая стоимость по usage и зарегистрированной тарифной таблице:
**$0.008804**, включая DEFER. Это не независимая сверка с итоговым invoice провайдера.
Median полного измеренного review pipeline — 10.2945 s, min — 7.633 s,
p95 nearest-rank/max — 17.892 s; выборка 12 слишком мала для SLA.

Существующий cumulative ledger не обнулён: committed OpenAI $0.049374,
historical hold $0.001984, прежние unresolved reservations $0.154624;
остаток общего $12 envelope — $11.794018. Новых неизвестных расходов/резервов нет.
Запись в отдельный существующий shadow budget ledger — единственная DB-мутация;
primary runtime, consumers, leases, venue и trading services не запускались.

## Результаты при условном внутриминутном исполнении

Каждое окно имеет собственный SIM-счёт $10 000. Возврат за окно — не месячный
или годовой процент; несмежные окна не компаундируются. В таблице net включает
торговые комиссии, funding и фактическую учтённую стоимость review для LLM-ветви.
Infrastructure/feed acquisition costs неизвестны и в эти числа не включены.

| Окно UTC, конец не включён | Без LLM: сделки / net | С market-only LLM: сделки / net | Без LLM: stress | С LLM: stress |
|---|---:|---:|---:|---:|
| 07–10.11.2021 | 0 / 0% | 0 / 0% | 0% | 0% |
| 05–08.02.2022 | 0 / 0% | 0 / 0% | 0% | 0% |
| 09–12.05.2022 | 5 / −0.4731% | 5 / −0.5829% | −0.8376% (4 сделки) | −0.7078% (3 сделки) |
| 13–16.06.2022 | 5 / −0.2634% | 3 / −0.3204% | −0.3436% (3 сделки) | −0.3437% (3 сделки) |

Дополнительный `latency_cost_control` сохраняет все кандидаты, но применяет ту же
измеренную задержку и все те же API-cost debits, что и LLM-ветвь. Его base net:
май −0.4730984%, июнь −0.2634125%. В этом candle proxy задержка не меняет набор
fills; отличие от baseline практически целиком от API-cost. Дельта review против
этого контроля: май −0.1098412 п.п., июнь −0.0569579 п.п. В более строгом сценарии
costs эффект непостоянный: май лучше, июнь не лучше. Это не устойчивый положительный
эффект и не основание выбрать модель по доходности.

Base closed-minute MTM drawdown: май 0.9911% → 1.0225%, июнь 0.9240% → 0.5784%.
Риски остались 0.25% на сделку / 1% совокупно / 1× gross leverage; квот сделок нет.
Отсев нельзя оценивать просто вычитанием проигрышной сделки: в мае DEFER удалил
XRP-кандидат (его baseline net −$12.51), но освободившийся risk budget допустил BNB
(net около −$23.55). Поэтому общий портфель стал хуже, хотя удалённый кандидат
сам по себе был убыточным. Это описание ex post, не правило отбора для нового прогона.

## Строгая проверка времени исполнения

В `STRICT_MINUTE_OPEN` **ни одна сделка не исполнилась** во всех четырёх окнах
и обоих cost-сценариях, для всех трёх ветвей. При 60-секундной жизни intent и
ненулевой задержке следующий наблюдаемый minute open уже после expiration.
Без LLM net 0%; с LLM остаются расходы: май −$0.004560, июнь −$0.004244.

`INTRABAR_OPEN_PROXY` использует цену открытия той же минуты после смоделированной
задержки. Это **не котировка, реально наблюдавшаяся после ответа LLM**, и может
ошибаться оптимистично. Таблица выше — условная оценка на свечах, не доказательство
исполняемости. Intent lifetime не продлевался и план не оптимизировался после результата.

## Допущения и ограничения

- Проверен только price-only LLM `ALLOW/VETO/DEFER`, а не Text Scouts → NEWS →
  Router → Macro → review всей системы; новости и внешний macro-архив **недоступны,
  а не доказанно пусты**. Не проверены LLM-generated предложения и слоты NO_INTENT.
- Модели показывались закрытые 1m/5m/15m/1h бары и неизменная геометрия intent.
  Даты, имена активов и абсолютные цены скрыты; результаты и будущие бары не
  передавались. Но современная модель могла обучаться на этих исторических событиях;
  masking не доказывает отсутствия latent hindsight.
- Реальные даты API-запросов сохранены как современные наблюдения. Измеренная
  длительность плюс baseline 100ms отображается на исторический clock только
  для симуляции; это не исторический receipt и не backdating.
- Base: fee 4.5 bps/side, spread 2, slippage 1/side, latency penalty 2 round-trip,
  uncertainty 2, planning adverse carry 3. Stress: 9/side, 4, 2/side, 2, 2, 3.
  Это предположения, не EVEDEX TCA. Архивный funding начислен на `calc_time`
  с candle-open price proxy; внутриминутный путь, depth/queue/partial fills,
  фактические SL/TP задержки и площадочная ликвидность не доказаны.
- 12 кандидатов и 12 календарных дней фиксированных development windows —
  малый, уже известный исторический набор, не independent holdout. Нет доказательства
  годовой доходности, распределения месячных результатов или эффективности всех режимов.
- Все 48 финансовых вариантов сверились с журналами: максимальная абсолютная
  ledger reconciliation error < $0.00000000001, unresolved open positions проверяются
  в исходных reports. 24 новых offline/evidence tests и 8 существующих service-cost tests прошли.

## Артефакты и продолжение

- [Полный result: 48 window/mode/cost/arm вариантов](../development/market_review/evidence/2026-10-10/result.json)
- [Настоящие ответы и usage](../development/market_review/evidence/2026-10-10/reviews.jsonl)
- [План и seal](../development/market_review/evidence/2026-10-10/seal.json)
- [До/после cumulative budget](../development/market_review/evidence/2026-10-10/gateway-source.json)
  и [завершение worker](../development/market_review/evidence/2026-10-10/worker-result.json)
- [Полный список опубликованных SHA-256](../development/market_review/evidence/2026-10-10/public-receipt-files.json)
- Exact pre-format исходники сохранены в `evidence/2026-10-10/sealed-sources/*.py.txt`;
  subsequent style-only formatting не переопределяет source identity выполненного прогона.

Следующий доказательный шаг — не увеличивать число LLM-проб по этому результату,
а выбрать пригодный causal quote/trade replay для нынешнего intent lifetime и собрать
point-in-time NEWS/MACRO-контекст для отдельного предобъявленного full-system теста.
Ни параметры стратегии, ни production composition этим экспериментом не изменены.

`TECHNICAL_PAPER_READY=false`, `PAPER_QUALIFIED=false`, `ALPHA_READY=false`,
`LIVE_READY=false`, `STRATEGY_POLICY=REJECT_ALL`. Trial 15 и frozen V2/V4/V5
evidence не изменялись; blind campaign credit — 0.
