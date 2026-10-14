# Kairos: один конкретный исследовательский профиль

Дата: 14 октября 2026, Europe/Moscow.
Identity: `adaptive-context-epochs.research.v1`.
Статус: **RESEARCH_PREPARATION_ONLY**, не выбранный экономический чемпион,
не production policy, не campaign freeze/enrollment и не разрешение торговли.

После [единой концепции](CANONICAL-TRADING-SPEC-2026-10-14.md) четыре развилки
конкретизированы в одном opt-in engineering-кандидате. Это не перебор параметров:
исторические доходности и blind-результаты при выборе правил не использовались.
Профиль определён [в отдельном модуле](../development/adaptive_replay/adaptive_replay/research_profile_v1.py)
и проверяется [синтетическими контрактными тестами](../development/adaptive_replay/tests/test_research_profile_v1.py).
Он не входит в service registry и не способен вызвать модель, Risk или биржу.

## Выбранный пакет P1–P4

| пункт | точное решение для этого engineering-кандидата |
| --- | --- |
| P1 — техническая часть | Только неизменённый `adaptive_pullback_range_v1`; прямой `evaluate_adaptive`, не прежний `evaluate_complex` с дополнительным breakout |
| P1 — контекстная часть | Неизменённый `context_atr_proposal_v1` задаёт геометрию; новая finite epoch/reset policy определяет, когда независимая идея может рассматриваться |
| P2 — расписание | Полный пятиинструментный знаменатель на исходных UTC 5m cuts; один symbol-level generation consideration на структурный epoch; без дополнительных news-event вызовов |
| P3 — сроки | Hypothesis validity 15 минут от origin cut; maximum quote age 2 секунды; параметры явно исследовательские, не автоматически production defaults |
| P3 — новые возможности | Замороженная mean/range геометрия → позже наблюдённый reset → другой, более поздний price event; смена ID/cut/context/ответа не является reset |
| P4 — порядок | Подготовительные слоты: `(cut, lexical symbol)`; уже выданный единый entry batch: `(actual issue, lexical symbol, original cut, parent)` |

Референсные символы остаются BTCUSDT, ETHUSDT, SOLUSDT, BNBUSDT, XRPUSDT.
Лексикографический порядок BNB/BTC/ETH/SOL/XRP выбран явно: это технический
tie-break, не рейтинг ожидаемой прибыли. Количество сделок не нормируется.
Расписание слотов не равно расписанию платных вызовов.

## P1: реальные границы каталога

У technical origin сохраняются исходные trend-pullback/reclaim и range-edge
правила, parent, stop/target/timeout и native config. Проверяется точный installed
adaptive code/config fingerprint, ранее зафиксированный в
[engineering receipt](ADAPTIVE-STRATEGY-2026-10-06.md). Старый V2 technical bridge
не используется: он делегирует двухсемейному complex, а не одному adaptive.

Context-origin остаётся самостоятельным: native `NO_INTENT` не блокирует его.
Но его ATR template **не называется native pullback или range-edge pattern**.
Новые названия `CONTEXT_FROZEN_MEAN_RECLAIM` и
`CONTEXT_FROZEN_RANGE_EXCURSION` относятся к eligibility/reset, не меняют формулу
stop/target и не доказывают, что модель обнаружила профессиональную alpha.

Поддерживаются BULL/LONG, BEAR/SHORT, RANGE/LONG|SHORT при NORMAL defense.
CRASH, post-shock cooldown, UNCERTAIN, CHOP, warmup и недоступная история не
превращаются в quiet slot. Native optional crash retest остаётся вне этого
профиля; CRASH не переименовывается в BEAR.

Все слоты требуют ровно 3 240 полных последовательных 1m баров. Source
identity и rolling-window bytes сохраняются; пересечение соседних окон должно
совпадать. Ревизия уже наблюдённых баров — integrity conflict, не новая попытка.

## P2–P3: точный контекстный latch

Сессия, source set, model-config hash, отдельный quote source и по одному
MARKET/NEWS/MACRO source ID задаются явно до её первого cut. Horizon ограничен
пятью сутками для bounded engineering preparation. Это ограничение тестового
профиля, не длительность будущего blind gate. Отсутствующие bindings не
дополняются секретами, ENV, текущими документами или «нейтральными» источниками.
TTL самих source receipts остаются явными caller/source declarations; это не
доказательство их аутентичности или допустимости для реального эксперимента.

На первом заранее объявленном пригодном слоте символ получает один initial
epoch. В RANGE он допускает обе стороны, но первый consideration расходует
обе: `NONE`, error, UNKNOWN, отсутствие бюджета или обязательного контекста не
дают повторную попытку с другой стороной. Source/budget state здесь проверяется
как caller-supplied preflight; модуль не резервирует реальный ledger и не даёт
разрешения API-вызова. Для будущего dispatch обязательны действующие budget
gates и прежние cumulative limits.

Геометрия замораживается по полным 15m барам, закрывшимся **до открытия** 5m
event bar:

- BULL/BEAR: конечная SMA20 закрытий 15m;
- RANGE: lower/upper extrema последних 16 закрытых 15m баров.

Это отдельные context reset bounds, а не новая настройка native strategy.
После consideration:

- BULL: более поздний наблюдённый 5m close `<= frozen mean` отмечает reset;
  другой последующий close `> frozen mean` допускает один LONG epoch.
- BEAR: зеркально `>= mean`, затем на другом баре `< mean` допускает SHORT.
- RANGE: поздний close в замороженной middle half `[L+.25W, U-.25W]`
  отмечает общий reset. На другом позднем баре close в `[L,L+.25W)` допускает
  LONG, а в `(U-.25W,U]` — SHORT. Уход за frozen L/U не считается edge event.

Reset bar не может одновременно быть event bar. Его close должен постдатировать
**фактический clock consumption**, не только старый cut. Старые bounds проверяют
событие; только после него новая геометрия замораживается по предшествующим
event bar данным. Её изменение не может квалифицировать собственное событие
задним числом. Свидетельство reset сохраняется до event внутри этой сессии,
а не превращается в таймер повторной попытки.

Выбрана строгая ограничительная версия: смена исходного режима, missing/late
price cell, unsupported defense или overlap conflict терминально блокируют
символ **до конца данной сессии**. Это не идеальная непрерывная adaptive policy
и не доказательство её экономической пригодности. Нельзя автоматически
открыть новую сессию после отказа: будущий полный roster/identity задаётся
отдельно заранее. Цена этой простоты должна оцениваться в новом исследовании,
а не скрываться под заявлением «runtime закончен».

Каждый исходный symbol/cut сохраняет receipt, в том числе NO_CALL, unavailable
и structural suppression. Missing symbol/cut, catch-up, поздняя инициализация
или потерянный latch не заполняются переизданием старого события.

## Actual-clock гипотеза и один оригинальный исход

Используется отдельная V3 модель времени: `origin_cut_ms` не подменяется
`created_ms`. В creation передаются фактические request/completion/capture
clocks и связанный оригинальный model response. Создание после первой уже
закрывшейся post-anchor минуты запрещено; более поздний ответ не backdate'ится.

15-минутная validity отсчитывается от origin cut, не от задержанного создания.
Original parent не продлевается. Native entry duration остаётся 60 секунд для
adaptive и 300 секунд для ATR mapper. Fresh entry ограничивается исходной
duration, hypothesis deadline, quote и context deadlines. Все исходные protection
bytes сохраняются. Первый trigger потребляется действующей V3 механикой даже
при VETO/DEFER, cost/Risk refusal или отсутствии fill.

Фабрика материализации проверяет весь canonical five-symbol receipt set по
сохранённому checkpoint. Замена `NO_CALL` на `ELIGIBLE` не принимается отдельно
от него. В retained materialization fold одному epoch соответствует один
original outcome — DIRECTION, NONE, FAILED или UNKNOWN. Второй ответ, другая
сторона, timestamp или status под этим epoch отклоняются. Exact redelivery
возвращает тот же plan без нового binding. Один physical outcome можно явно
разделить между treatment arms, но это не ещё один provider request.

Это **pure retained-state consistency**, не durable/global exactly-once.
Хэши не аутентифицируют источники, preregistration или предыдущую историю.
Пересоздание пустого state/нового session после отказа не является разрешённым
recovery; полноценный durable publisher и его accepted checkpoint adoption
остаются отдельной интеграционной задачей.

## Review, арбитраж и отсутствие обхода Risk

Профиль явно содержит strategy-only control и три LLM treatments: technical
review, independent proposals и combined. Все три treatment entry paths требуют
quote/context-bound review; strategy-only не получает искусственный LLM review.
Оригинал генерации и оригинал review — разные операции и расходы.

Combined целево сохраняет технический приоритет, abstention при противоположных
допущенных направлениях, отсутствие fallback после VETO/DEFER и отсутствие
позднего арбитража. Однако этот модуль не исполняет combined/economics.

**Профиль нельзя автоматически передать принятому V3 four-arm evaluator.**
У него COMPLETE creation требуется даже для quiet peer, а independent_proposals
не требует дополнительного review. У нового профиля разреженные NO_CALL и
review в independent treatment. Для совместимости нужна отдельная версия
evaluator/driver с собственным source-pinned допуском — не фальшивый COMPLETE,
не скрытое изменение старой V3 и не переписывание её принятой квитанции.

Entry ordering работает только с уже выданными в один actual-issue момент
кандидатами после origin arbitration. Он не ждёт будущих peers, не requote'ит,
не выбирает quantity и не переносит entry после expiry. Кандидат не равен
`RiskTradeDecision` или ордеру. Downstream ceilings 0,25% и 1% не изменены.

## Проверки и следующие реальные гейты

Локальные результаты и точные артефакты зафиксированы в
[engineering receipt](../reports/research-profile/2026-10-14/engineering-receipt.json)
для подписанного source commit `77fadff6ef487b2442f4e34a7c7e2eacbfd94026`:

- в каждом свежем non-editable окружении Python 3.11.15/3.14.7 совпали все 95
  source files; Python `-I` исключает working-tree импорт;
- по 26 новых тестов и по 132 прежних lifecycle/mapper regression tests,
  zero failures/errors/skips;
- Ruff lint/format, unchanged offline lock, wheel/sdist, Meta static/local links
  и checkout/source-projection regressions — PASS;
- полный collection — 2 319 cases; hosted CI ещё проверяет exact disjoint union
  2 318 regular + один полный пятидневный synthetic horizon, а не sampled subset.

Первый cache-stale wheel и неудачный managed-Python link attempt не выданы за
PASS и сохранены как диагностика. CI теперь принудительно переустанавливает
local replay package и сверяет imported profile bytes с checkout, чтобы свежий
venv сам по себе не считался доказательством свежего wheel.

Синтетический
quiet RANGE, mock BULL/BEAR и finite native-parent cases — контрактные проверки,
не историческая торговля и не benchmark моделей. Fee/funding/spread/slippage,
delay/model/feed costs и TCA этой работой не измеряются; прежние planning
assumptions не объявляются venue facts.

Следующее для экономического исследования: проверить настоящий NEWS/MACRO/BBO
corpus и availability, source-пин нового driver/evaluator и полного roster,
реальный provider budget/admission и изолированное matched сравнение. Никакой
длительный blind campaign сейчас не зарегистрирован; будущей системе нужны
свои 365 дней и 500 естественных closes, остальные прежние гейты и sealed pass.

Trial 15, V2/V4/V5 frozen evidence, primary/legacy/R7 DB/queue, runtime consumers,
source/dependency pins и бюджеты не меняются. Нет paid API, exchange request,
canary, PAPER/LIVE и UI/UX. Все четыре readiness-флага false,
`STRATEGY_POLICY=REJECT_ALL`.
