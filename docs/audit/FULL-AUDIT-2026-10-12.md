# PULSAR / PUL_SKILL — ممیزی کامل، بی‌رحم و کد-محور

**تاریخ:** ۲۰۲۶-۱۰-۱۲ · **کامیت مبنا:** `76fb678` (main) · **حجم کد:** ۲۵٬۰۲۷ خط در ۹۸ فایل
**دامنه:** `api/` (FastAPI، ۷ فایل)، `contracts/` (Solidity + Foundry)، `src/` (React 19 + TS، ۴۲ فایل)، `scripts/` (۶ سوئیت تست)، CI، Firestore rules، مستندات استقرار.

> **حکم یک‌خطی:** مهندسی این پروژه از یک پروژه‌ی هابی معمولی بسیار بالاتر است (۱۱ دور ممیزی قبلی، پروتکل commit→reveal واقعی، امضای oracle با EIP-191، قرارداد escrow با تست)، **اما در وضعیت فعلی به‌عنوان یک محصول واقعیِ پول-واقعی قابل عرضه نیست.** ۴ باگ CRITICAL، ۲۰ باگ HIGH، و یک شکاف ساختاری در مدل اعتماد/انصاف/ضد-تقلب وجود دارد که رفع آن‌ها پیش‌نیاز هر انتشار جدی است.

---

## ۰. شواهد اجرایی (چه چیزی واقعاً اجرا شد)

| کار | نتیجه |
|---|---|
| `python3 scripts/test_game_server.py` | ✅ ALL SMOKE TESTS PASSED |
| `python3 scripts/test_http_e2e.py` | ✅ ALL HTTP E2E TESTS PASSED |
| `python3 scripts/probe_a5.py` | ✅ FAILURES: none |
| `python3 scripts/probe_a6.py` | ✅ FAILURES: none |
| `python3 scripts/probe_a8.py` | ✅ ALL CHECKS PASSED |
| `bun run lint` (`tsc --noEmit`) | ✅ exit 0 |
| `node contracts/test/compile_check.js` | ⏳ (solc gate) |
| `forge test` | ❌ اجرا نشد (Foundry نصب نیست — فقط در CI) |
| `scripts/test_firestore_integration.py` | ⏭️ skip (بدون credential) |

**نتیجه‌ی مهم:** همه‌ی تست‌ها سبز هستند، **و این خودش یک یافته است.** چند مورد از خطرناک‌ترین باگ‌ها (C1 و C2 پایین) دقیقاً در مسیرهایی هستند که هیچ تستی اجرا نمی‌کند، و یک تست موجود (rate limiter) به دلیل اشتباه برای دلیل درست PASS می‌شود. «سبز بودن CI» در این پروژه تضمین کیفیت نیست.

**یک نکته‌ی محیطی:** نصب `pip install -r api/requirements.txt` روی Python 3.11 یک ترکیب شکسته (`pydantic 2.10.5` + `pydantic_core 2.50.1`) تولید کرد که import سرور را می‌شکند. `--dry-run` روی venv تمیز درست resolve می‌کند، پس احتمالاً یک quirk محیطی/pip است نه باگ مخزن — **اما `pydantic-core` در requirements پین نشده و این ریسک تکرارشدنی است.** پیشنهاد: `pip-compile` و کامیت `requirements.lock`.

---

## ۱. CRITICAL — شکست کامل یا از دست رفتن پول در عملیات عادی

### C1 — محدودکننده‌ی نرخ توزیع‌شده (Firestore) کاملاً مرده است
**فایل:** `api/main.py:134-163` · **تأییدشده با خواندن سورس کتابخانه**

```python
txn = fs.db.transaction()
win = _incr(txn)          # ← اینجا ValueError می‌خورد
...
except Exception:
    pass                  # ← و بی‌صدا به limiter درون‌پروسه‌ای سقوط می‌کند
```
و داخل `_incr`:
```python
snap = doc.get(transaction=txn)   # ← INACTIVE_TXN
```

**چرا غلط است (تأیید از سورس `google-cloud-firestore==2.20.0`):**
- `Transaction.in_progress` برابر است با `self._id is not None`.
- `db.transaction()` یک `Transaction` با `_id = None` می‌سازد؛ فقط دکوراتور `@transactional` متد `_begin()` را صدا می‌زند.
- `_helpers.get_transaction_id()` اگر `in_progress` نباشد `ValueError(INACTIVE_TXN)` می‌اندازد.
- `txn.set()` فقط write را **stage** می‌کند؛ هیچ‌جا `txn.commit()` صدا زده نمی‌شود.

**نتیجه:** هر فراخوانی `_rl_check` در حالت Firestore استثنا می‌دهد، در `except Exception: pass` بلعیده می‌شود و به limiter **درون-پروسه‌ای** سقوط می‌کند. یعنی:
- روی N replica، هر replica مستقلاً `limit` را مجاز می‌کند → سقف واقعی `N × limit`.
- با هر restart پنجره صفر می‌شود.
- تمام کنترل‌های ضد-DoS روی `settle` (تراکنش Firestore + mint امضا)، `claim` (RPC پول‌دار)، `auth`/`verify` (ecrecover)، `commit`/`round` عملاً بی‌اثرند.

**چرا تست نمی‌گیردش:** `test_firestore_integration.py:89-95` فقط چک می‌کند که «بعد از N فراخوانی، ۴۲۹ می‌گیریم». مسیر in-process هم ۴۲۹ می‌دهد → تست PASS می‌شود بدون اینکه بفهمد کدام مسیر اجرا شده. ضمناً کامنت `main.py:141-145` ادعا می‌کند یک `NameError` قبلی رفع شده — در واقع کل مسیر هرگز کار نکرده.

**اصلاح:** بدنه را با `_firestore.transactional` بپیچید و `txn.commit()` را صدا بزنید؛ `except` را باریک کنید (خطای برنامه‌نویسی نباید به «fallback» تبدیل شود)؛ یک شمارنده‌ی «fallback rate» روی `/api/health` منتشر کنید.

---

### C2 — `token_decimals()` یک خطای گذرا را برای همیشه `None` کش می‌کند → void شدن دسته‌جمعی همه‌ی دوئل‌های Active
**فایل:** `api/onchain.py:76, 88-102` + `api/onchain.py:313-316` + `api/main.py:212-222`

```python
_token_decimals: int | None | str = "unread"
...
if _token_decimals != "unread":
    return _token_decimals      # ← None برای همیشه برمی‌گردد
try:
    ...
    _token_decimals = None      # ← روی هر hiccup چسبنده می‌شود
```
و در gate:
```python
if decimals is None:
    return False                # fail-closed
```
و در `main.py`:
```python
if not onchain.verify_deposit(info, m.stake, m.players):
    m.status = "void"           # ← void می‌شود، نه فقط رد
```

**سناریو:** یک blip ۵ ثانیه‌ای روی RPC در اولین بررسی یک دوئل Active. از آن لحظه به بعد، **هر** دوئل Active در `verify_deposit` رد می‌شود و به‌جای «رد کردن راند» کل ماتچ `void` می‌شود → هر دو استیک بعد از ۳۰ دقیقه refund می‌شوند و **برنده‌ی قانونی هرگز جایزه‌اش را نمی‌گیرد**. تا restart پروسه غیرقابل‌بازیابی.

**تفاوت ظریف ولی حیاتی:** «نمی‌توانم بخوانم» با «مطابقت ندارد» یکی گرفته شده. کد `_chain_ok()` یک cooldown دارد (`_CHAIN_MISMATCH_COOLDOWN`) ولی `token_decimals` ندارد.

**اصلاح:** cooldown/TTL برای کش شکست؛ و در حالت `decimals is None` به‌جای `return False` یک `409 refuse-the-round` بدهید (بدون void کردن ماتچ).

---

### C3 — بعد از اتصال EIP-6963، تراکنش‌های پول با **کیف پول اشتباه** امضا می‌شوند
**فایل:** `src/lib/realWeb3.ts:1020-1044` (`getActiveEip1193Provider`) + `:1155-1170` (`setConnectedAddress`)

```ts
const injected = typeof window !== 'undefined' ? (window as any).ethereum : null;
return injected || null;     // ← provider انتخاب‌شده‌ی کاربر برگردانده نمی‌شود
```
`connectEIP6963` فقط `currentAccount.address` را ذخیره می‌کند و **آبجکت provider را دور می‌ریزد**. `escrowFlow.requireInjected()` و امضای SIWE در `ReactionGamePage.tsx:238,252` هر دو از همین متد استفاده می‌کنند.

**سناریو:** کاربر با Coinbase/Rabby از طریق EIP-6963 وصل می‌شود در حالی که MetaMask روی `window.ethereum` است. سپس:
- `approveUsdt` / `createDuel` / `settleDuel` از **آدرس یک کیف پول دیگر** ارسال می‌شوند (یا revert می‌کنند)،
- یا `personal_sign` آدرس دیگری را recover می‌کند و سرور session را رد می‌کند (`authenticate:116`).
- اگر یک provider کهنه‌ی WalletConnect هنوز «connected» باشد، امضا به آن حساب می‌رود.

این یک مسیر واقعی «جابه‌جایی پول از کیف پول اشتباه» است.

**اصلاح:** provider فعال (یا `rdns` آن) را در `setConnectedAddress` ذخیره کنید و `getActiveEip1193Provider` دقیقاً همان را برگرداند.

---

### C4 — روی موبایل، یک تپ = دو ارسال نتیجه = **void شدن کل ماتچ**
**فایل:** `src/pages/ReactionGamePage.tsx:1153-1154` (روت)، `:1472` (دکمه‌ی هدف)، `:580-598` (`handleTargetHit`)، `:612-623` (`handleTouchEnd`)، `:978-984` (catch)

```tsx
<div onTouchStart={handleTouchStart} onTouchEnd={handleTouchEnd}>   // :1153-1154
   ...
   <button onClick={handleTargetHit}>                              // :1472
```
یک تپ روی هدف این ترتیب را می‌سازد:
1. `touchstart` → `handleTouchStart`
2. `touchend` روی روت (bubble) → **`handleTouchEnd` → `processVerification`**
3. `click` سینتتیک روی دکمه → **`handleTargetHit` → `processVerification`**

`e.stopPropagation()` در `handleTargetHit` روی رویداد `click` است و جلوی `touchend` که **قبلاً** اجرا شده را نمی‌گیرد. هر دو closure از همان render هستند (`phase === 'action'`) پس هر دو از گارد رد می‌شوند.

فراخوانی دوم `submitRoundResult` را برای همان راند می‌فرستد → سرور `409 "Result already submitted"` → `request()` throw می‌کند → catch:
```ts
setMatchResult({ outcome: 'void', ..., reason: msg });
setPhase('bot-detected');
```
**یعنی بازیکن موبایل با یک تپ، ماتچ را «void / bot-detected» می‌بیند** — درست در بازاری که تمام بازار موبایل است. (ضمناً `setInterval` دوم هم لو می‌رود.)

**اصلاح:** گارد سنکرون با ref (`verifyingRef.current`) در ابتدای `processVerification`؛ یا حذف `onTouchEnd` سطح روت و مدیریت یکپارچه‌ی touch+click.

---

## ۲. HIGH — پول، انصاف، و اعتماد

### H1 — برنده‌ی دوئل با **latency شبکه** تعیین می‌شود، نه با واکنش
**فایل:** `api/match_engine.py:419-422, 468-482`
```python
r.observed_ms = max(0.0, (now - r.revealed_at) * 1000.0 - r.target_ms)
...
if r.observed_ms is not None: return r.observed_ms   # ← مبنای رتبه‌بندی
```
`observed_ms = واکنش واقعی + RTT(reveal) + RTT(submit) + زمان رندر کلاینت`. یعنی این سیگنال **به‌طور یکنوا با تأخیر شبکه متورم می‌شود**.

**نتیجه:** دو بازیکن با واکنش یکسان، بر اساس پینگ تعیین می‌شوند. این «غیرقابل‌جعل» است ولی یک نقص تمام‌عیار در انصاف یک بازی پول-واقعی است. کامنت `main.py:54-59` این را به‌عنوان یک «fix» معرفی می‌کند؛ در واقع یک trade-off است که به قیمت انصاف خریداری شده.

**اصلاح:** رتبه‌بندی روی claim کلاینت **محدودشده** توسط observed (کد همین حالا در دو جهت cross-check می‌کند)، یا تخمین RTT و جبران آن، یا matchmaking با سقف پینگ/منطقه.

### H2 — «commitment» در commit/reveal هیچ چیزی را متعهد نمی‌کند
**فایل:** `api/match_engine.py:329-346`, `:322-326`
`commit_intent` فقط `intent_hash` کلاینت را ذخیره می‌کند و **هیچ‌چیز آن را اعتبارسنجی نمی‌کند**. `_result_proof` به `commit_hash` گره می‌خورد، ولی `commit_hash` را خود مهاجم انتخاب می‌کند (حتی `0x000…`). هیچ entropy سرور-محور، هیچ nonce، هیچ binding به زمان در commitment نیست.

**نتیجه:** آنتی‌ری‌رول واقعی از گارد «یک ارسال در هر راند» (`:401-402`) می‌آید، نه از commitment. ضمناً بعد از `COMMIT_WINDOW_SECONDS` (۳۰ ثانیه) کلاینت آزادانه می‌تواند دوباره commit کند (`:337` فقط داخل پنجره بلاک می‌کند). ادعای «prevents re-rolling results» در docstring تحقق نمی‌یابد.

**اصلاح:** سرور در لحظه‌ی commit یک salt بدهد و آن را در `_result_proof` بگنجاند؛ یا فریم‌بندی «commitment» را حذف کنید.

### H3 — دفتر اقتصاد (ledger) TOCTOU است، نه اتمیک → دو-بار شمارش
**فایل:** `api/economy.py:200-216` سپس `:243-273`
```python
existing = match_ref.get()          # ← خواندن خارج از تراکنش
if existing.exists:
    prev_id = ...get("settlementId")
    if prev_id == settlement_id: return
...
batch = db.batch(); ... ; batch.commit()
```
دو replica (یا دو مسیر فراخوانی در `main.py`: `:642` و `:727`) می‌توانند هم‌زمان `prev_id != settlement_id` ببینند و هر دو batch خود را commit کنند → `users.wins`, `users.totalMatches`, `leaderboard.earnedUSDT` دو بار افزایش می‌یابند. docstring ادعای atomic+idempotent می‌کند؛ هیچ‌کدام برقرار نیست.

**اصلاح:** خواندن + `FieldValue.increment` داخل یک تراکنش keyed روی `matches/{id}.settlementId`، یا یک سند `settlements/{settlementId}` با `create()` (insert-or-fail اتمیک) به‌عنوان گیت idempotency.

### H4 — ledger داخل یک تراکنش **commit نشده** نوشته می‌شود
**فایل:** `api/main.py:623-643`
```python
def _mutate(m, eng):
    ...
    economy.record_settlement(m)   # ← batch.commit() مستقل، داخل تراکنش بازِ ماتچ
```
`record_settlement` خودش یک `batch.commit()` واقعی انجام می‌دهد در حالی که تراکنش ماتچ هنوز باز است. اگر تراکنش بعداً abort شود (conflict/exception)، **ledger یک تسویه را ثبت کرده که هرگز persist نشده** → `users.wins` بالا رفته ولی ماتچ در Firestore هنوز `active` است.

**اصلاح:** `record_settlement` را بعد از بازگشت موفق `store.update` صدا بزنید (post-commit) و به idempotency `settlementId` تکیه کنید.

### H5 — `settlement_id_for` (تست) با id واقعی تولیدی **نمی‌خواند**
**فایل:** `api/economy.py:305-309` در مقابل `:188-198`
```python
def settlement_id_for(match_id, outcome, stake, settled_at):
    return hashlib.sha256("|".join([match_id, outcome, f"{stake:.2f}", str(settled_at), ""]).encode()).hexdigest()
```
جزء پنجم در تابع تستی **رشته‌ی خالی** است، ولی در `record_settlement` مقدار `str(sorted((k, tuple(v or ())) for k, v in validated_times.items()))` است. یعنی هر تستی که از این helper برای اثبات idempotency استفاده کند، **همیشه PASS می‌شود** در حالی که رفتار تولیدی متفاوت است. یک تست خودفریب.

**اصلاح:** یک تابع مشترک `_settlement_id(match_id, outcome, stake, settled_at, times)` و استفاده در هر دو جا.

### H6 — پیکربندی production به‌صورت **fail-open** است
**فایل:** `api/main.py:295-299`
```python
_prodlike_values = {"prod","production","main","release","staging"}
_deploy_markers = ("K_SERVICE","K_REVISION","RENDER","FLY_MACHINE_ID","DYNO")
_prod_like = _pulsar_env in _prodlike_values or _is_deployed
```
یک استقرار self-hosted (Docker روی VPS، nginx، Fly-alternative) بدون هیچ marker → `_prod_like=False` → بدون اجبار env، CORS روی `"*"` (`:357-368`)، بدون `TrustedHostMiddleware` (`:338-348`)، و `_request_domain()` به هدر `Host` اعتماد می‌کند (`:434-438`). کامنت خودِ کد می‌گوید «fail-open configuration» را دقیقاً همین رفع کرده — ولی فقط برای لیست محدودی از مارکرها.

**اصلاح:** پیش‌فرض را برعکس کنید: هر محیط production است مگر `PULSAR_ENV=dev` صریحاً ست شده باشد.

### H7 — bind دامنه‌ی SIWE از هدر `Host` کلاینت می‌آید
**فایل:** `api/main.py:434-438`
```python
return request.headers.get("host", "localhost")
```
nonce (MAC) و پیام canonical هر دو به دامنه‌ای bind می‌شوند که **مهاجم انتخاب می‌کند**. در هر پیکربندی که H6 برقرار باشد، سرور با کمال میل برای `attacker.com` nonce صادر و امضا را قبول می‌کند → تضمین ضد-فیشینگِ ادعاشده از بین می‌رود.

**اصلاح:** وقتی escrow فعال است `ALLOWED_DOMAIN` را اجباری کنید؛ در غیر این صورت به یک `PUBLIC_HOST` ثابت bind کنید.

### H8 — `sweep_expired` ماتچ‌های **Active** را در ۱۰ دقیقه void می‌کند، در حالی که escrow تا ۳۰ دقیقه قابل تسویه است
**فایل:** `api/store.py:226-230` و `:393-399`
```python
elif m.status == "active" and now - m.play_started_at() > MATCH_EXPIRY_SECONDS:  # 600s
    m.status = "void"
```
`MATCH_EXPIRY_SECONDS = 600` ولی `MATCH_TIMEOUT_SECONDS = 1800`. یک دوئل Active که از ۱۰ دقیقه بگذرد server-side `void` می‌شود؛ `settle()` بعد از آن `"Match is not active"` می‌دهد و **برنده تا ۲۰ دقیقه‌ی دیگر نمی‌تواند امضا بگیرد، هرچند escrow هنوز آماده‌ی پرداخت است**. بدتر: sweep بدون توجه به `match_completed` void می‌کند — یک ماتچ **تمام‌شده ولی تسویه‌نشده** می‌تواند void شود.

**اصلاح:** در sweep، اگر `settlement_deadline(m)` نگذشته، اول `_settle_once` (forfeit) را امتحان کنید؛ فقط در آخر void.

### H9 — sweep‌ها روی **هر** poll صف اجرا می‌شوند + ایندکس composite غایب → مسیر نجات جایزه در production مرده است
**فایل:** `api/main.py:532-535` → `api/store.py:376, 409-413, 447-453`
هر poll صف (۲۴/min/آدرس) سه collection scan فایرستور می‌زند:
- `QUEUE_DOC.stream()`
- `.where("status","==","active").stream()`
- `.where("status","==","settled").order_by("settled_at").limit(100)`

کوئری سوم به یک ایندکس composite `(status, settled_at)` نیاز دارد که **هیچ‌جا تعریف نشده**؛ و `except Exception: pass` در `store.py:465-467` خطای ایندکس غایب را می‌بلعد → **مسیر re-sign (F-12) در production بی‌صدا no-op است** — دقیقاً همان باگی که audit #11 C2 می‌خواست رفع کند — در حالی که هزینه‌ی کوئری پرداخت می‌شود.

**اصلاح:** sweep را به یک job زمان‌بندی‌شده منتقل کنید؛ ایندکس را تعریف کنید؛ خطای ایندکس را log + health-counter کنید.

### H10 — انجام I/O شبکه **داخل** قفل/تراکنش store
**فایل:** `api/main.py:581-588, 603-609, 623-645` → `onchain.duel_info` → `urlopen(timeout=5.0)`
`_verify_deposits_or_void` داخل `store.update` صدا زده می‌شود. در حالت memory، `InMemoryStore.update` یک `self._lock` **سراسری برای همه‌ی ماتچ‌ها** دارد (`store.py:210-218`) → یک `urlopen` بلاکینگ تا ۵ ثانیه، **تمام** commit/reveal/submit/settle پروسه را سریالایز می‌کند. در حالت Firestore، تراکنش باز در حین I/O شبکه نگه داشته می‌شود → ریسک `ABORTED`/contention.

**اصلاح:** وضعیت deposit را **قبل** از ورود به mutate حل کنید. هرگز socket I/O زیر قفل نکنید.

### H11 — مسیر بازیابی بعد از refresh یک **no-op** است (stale closure)
**فایل:** `src/pages/ReactionGamePage.tsx:461-499` (`useCallback(..., [])`) → `:493` `finishServerMatch`
```tsx
const restoreBo3FromServer = useCallback((view) => { ... void finishServerMatch([], userScore, opponentScore, 0, 0); ... }, []);
```
با deps خالی، این closure نسخه‌ی **render اول** `finishServerMatch` را می‌گیرد که در آن `serverSession === null && serverMatch === null` است → گارد `if (!serverSession || !serverMatch) return;` (`:697`) فوراً برمی‌گردد. `recoverServerMatch` (`:358`) هم همین مشکل را دارد.

**نتیجه:** بعد از reload یک ماتچ تعیین‌شده، مسیر تسویه‌ی خودکار هیچ کاری نمی‌کند؛ برنده هرگز `settleDuel` را submit نمی‌کند و پول تا تایم‌اوت ۳۰ دقیقه می‌ماند.

### H12 — موجودی واقعی on-chain با `vaultBalance` (همیشه صفر) بازنویسی می‌شود
**فایل:** `src/lib/realWeb3.ts:1296-1303`
```ts
if (this.currentAccount.address === data.address) {
  this.currentAccount.balanceUSDT = data.vaultBalance;   // 0.0 برای همیشه
  this.notify();
}
```
`vaultBalance` در هر پروفایل تازه `0.0` است و هرگز به‌روز نمی‌شود (P1.16 vault را حذف کرد). بعد از هر `recordMatch`/`updatePlayerTag`، کیف پولی که همین الان $25 نشان می‌داد به **$0.00 به‌عنوان یک واقعیت** می‌پرد و گیت «موجودی ناکافی» را هم تریگر می‌کند (`ReactionGamePage.tsx:1320-1323`, `LobbyPage.tsx:107`).

### H13 — اعشار توکن در مسیر نوشتن hardcode روی ۶ است، ولی مسیر خواندن `decimals()` را می‌خواند
**فایل:** `src/lib/chain.ts:51` (`USDT_DECIMALS: 6`) + `escrowFlow.ts:133,145` + `ReactionGamePage.tsx:314` در مقابل `realWeb3.ts:1100-1109`
روی rehearsal با یک MockUSDT ۱۸-اعشاری: `createDuel(..., parseUnits("1", 6))` عملاً `1e6` واحد پایه = `1e-12` USDT واریز می‌کند در حالی که UI استیک $1 را تبلیغ می‌کند. چک joiner هم با همان ثابت غلط پاس می‌شود پس هیچ‌چیز نمی‌گیرد. (سرور `decimals()` را از زنجیره می‌خواند → سرور و کلاینت بر سر «۱ USDT» اختلاف پیدا می‌کنند.)

### H14 — ریسک مسابقه‌ی تعویض حساب → داده‌ی یک کاربر زیر هویت دیگری
**فایل:** `src/store/usePulsarStore.ts:56-71`
`lastLoadedAddress` **قبل** از resolve شدن `loadUserDataAsync` ست می‌شود و `.then` بدون توجه به اینکه حساب هنوز همان است `userData` را می‌نویسد. اتصال A → تعویض سریع به B → پاسخ کندتر A آخر می‌رسد و wins/XP/history کاربر A زیر `wallet.address = B` نمایش داده می‌شود. بعد از `disconnectWallet` هم یک load در پرواز می‌تواند `userData` را پر کند.

### H15 — هیچ قفل حساب/شبکه‌ای در حین ماتچ فعال وجود ندارد
**فایل:** `realWeb3.ts:189-199`
`chainChanged → window.location.reload()` و `accountsChanged → setConnectedAddress(...)`. در میانه‌ی یک دوئل استیک‌دار، تعویض حساب/شبکه `wallet.fullAddress` را عوض می‌کند در حالی که session سرور، ماتچ و depositها متعلق به آدرس قبلی‌اند. `iWon` (`ReactionGamePage.tsx:738-739`) بعد از آن با آدرس غلط ارزیابی می‌شود و reload حافظه‌ی provider را نابود می‌کند.

### H16 — ضد-تقلب کلاینت **تزئینی** است
**فایل:** `ReactionGamePage.tsx:170-192` (handshake)، `antiCheat.ts:118-134`, `:220-229`
- `handleVerifyNodeClick` فقط یک کلیک را اندازه می‌گیرد؛ هیچ latency/entropy ثبت نمی‌شود.
- `antiCheat` هر تپ مستقیم (`trajectory.length < 2`) را `passedValidation: true` می‌داند.
- `humanEntropyScore` یک **هش** از سیگنال‌هاست، نه معیاری از «انسان‌بودن».
- در حالت سرور، `analyzeBiometrics` **اصلاً صدا زده نمی‌شود** (`:880-989`).
- هیچ تشخیص visibility/blur/devtools/`navigator.webdriver` وجود ندارد.

**نتیجه:** یک اسکریپت با واکنش ۱۳۰ms از ۹۵٪ انسان‌ها سریع‌تر است و تمام دروازه‌های plausibility را رد می‌کند. برای یک محصول پول-واقعی این یک تهدید وجودی است (کشاورزی ربات).

### H17 — قرارداد: انتقال‌های all-or-nothing → پول می‌تواند **برای همیشه** گیر کند
**فایل:** `contracts/PulsarEscrow.sol:310-313, 327, 331-332`
```solidity
SafeTransfer.safeTransfer(paymentToken, proof.winner, winnerPrize);
if (platformFee > 0) { SafeTransfer.safeTransfer(paymentToken, treasuryWallet, platformFee); }
```
USDT واقعی می‌تواند pause و blacklist کند؛ یک بازیکن می‌تواند قراردادی باشد که روی دریافت revert می‌کند. **هر** انتقال ناموفق کل تراکنش را revert می‌کند → استیک طرف مقابل هم برای همیشه قفل می‌شود. هیچ pull-payment، هیچ sweep اضطراری، هیچ payout جزئی وجود ندارد.

### H18 — قرارداد: هیچ سقف on-chain برای `proof.deadline` نیست
**فایل:** `contracts/PulsarEscrow.sol:267` در مقابل `:321`
```solidity
require(block.timestamp <= proof.deadline, "Settlement proof expired");
```
قرارداد هرگز `proof.deadline` را با `duel.createdAt + MATCH_TIMEOUT` مقایسه نمی‌کند. خاصیت «امضا قبل از باز شدن refund منقضی می‌شود» **فقط** توسط `match_engine.settlement_deadline()` و clamp در `oracle.sign_settlement()` تضمین می‌شود. اگر oracle یک deadline بلندتر امضا کند (باگ، تعویض کلید، انحراف ساعت، یا `created_at` سرور زودتر از `createdAt` زنجیره)، `settleDuel` یک proof را بعد از فعال شدن refund قبول می‌کند و دو مسیر با هم مسابقه می‌دهند.

**اصلاح (یک خط):** `require(proof.deadline <= duel.createdAt + MATCH_TIMEOUT, "deadline exceeds horizon");`

### H19 — قرارداد: refund بدون مجوز، برنده‌ی قانونی را **بی‌جایزه** می‌کند
**فایل:** `contracts/PulsarEscrow.sol:318-335`
هر آدرسی می‌تواند روی یک ماتچ `Active` بعد از `createdAt + 30min` این را صدا بزند و **هر دو** استیک را برگرداند و status را `Refunded` کند؛ بعد از آن `settleDuel` (که `Active` می‌خواهد) هرگز اجرا نمی‌شود.
**بهره‌کشی:** بازیکن بازنده راندها را رها می‌کند؛ در دقیقه‌ی ۳۰ (یا یک ربات) `refundTimeoutMatch` را صدا می‌زند؛ هر دو پولشان را پس می‌گیرند؛ برنده جایزه‌اش را از دست می‌دهد. refund متقارن است، پس تایم‌اوت یک **آپشن رایگان** برای طرف بازنده است. هیچ جریمه‌ای برای رهاکننده وجود ندارد.

### H20 — قرارداد: `joinDuel` هیچ cutoff ندارد و activation ثبت نمی‌شود
**فایل:** `contracts/PulsarEscrow.sol:240-255`
یک ماتچ `Created` در هر زمانی قابل join است. `joinDuel` هیچ timestamp فعال‌سازی ثبت نمی‌کند، پس تنها ساعت قرارداد `createdAt` (لحظه‌ی واریز) است. بازیکن می‌تواند در `T+29:59` join کند → یک ماتچ `Active` که یک ثانیه بعد قابل refund است.

### H21 — CI بخش قرارداد **شکسته** است: ۲۱ تست قرارداد هرگز اجرا نشده‌اند `[CI-1]`
**فایل:** `.github/workflows/ci.yml` در مقابل `contracts/test/MockUSDT.sol:4`
```yaml
- name: Install forge-std (test dependency)
  run: cd contracts && (test -d lib/forge-std || git clone --depth 1 .../forge-std.git lib/forge-std)
- name: forge test
  run: cd contracts && forge test -vvv
```
`MockUSDT.sol` به `openzeppelin-contracts/contracts/token/ERC20/ERC20.sol` ایمپورت می‌کند ولی workflow آن را نصب نمی‌کند:
```
Error: Unable to resolve imports: "openzeppelin-contracts/contracts/token/ERC20/ERC20.sol"
```
**نتیجه:** `forge test` کامپایل نمی‌شود → job قرارداد در CI شکست می‌خورد (یا هرگز سبز نبوده). بعد از نصب دستی OZ: **۲۱/۲۱ PASS**. یعنی تست‌ها درست‌اند ولی هیچ‌کس آن‌ها را اجرا نمی‌کند. `compile_check.js` با یک shim داخلی از این مشکل عبور می‌کند و همین موضوع را پنهان کرده.

**اصلاح:** یک خط در workflow — نصب `openzeppelin-contracts` در کنار `forge-std`.

### H22 — هیچ endpoint logout وجود ندارد؛ `revoke_session` کد مرده است
**فایل:** `api/auth.py:224-254` — `revoke_session` هیچ‌جا در `main.py` صدا زده نمی‌شود (تأیید با grep). ادعای F-06 («توکن لو رفته را می‌توان کشت») از طریق API **غیرقابل‌دسترسی** است. در عوض `_jti_is_revoked` روی **هر** درخواست احراز‌شده یک read فایرستور اضافه می‌کند.

### H24 — رها کردن مسابقه یک **آپشن رایگان** است؛ بازیکن صادق پاداش نمی‌گیرد `[کشف‌شده در فاز ۰]`
**فایل:** `api/match_engine.py:589-617` (`settle`)
```python
if va is None and vb is None:
    continue  # double forfeit: round awards nobody
```
یک راند که **هیچ‌کدام** از دو بازیکن در آن نتیجه نداده‌اند، به هیچ‌کس تعلق نمی‌گیرد. پس:

| وضعیت | نتیجه |
|---|---|
| A دو راند بازی کند، B هیچ | A ۲-۰ می‌برد ✅ |
| A **یک** راند بازی کند، B هیچ | ۱-۰ → **بدون اکثریت → void → هر دو refund** ❌ |

**نتیجه:** بازیکنی که صادقانه راند ۰ را بازی کرده و بعد منتظر حریف مانده (کاری که UI تشویق می‌کند)، در پنجره‌ی grace به **void** می‌رسد: نه جایزه می‌گیرد، نه رهاکننده جریمه می‌شود. رها کردن کاملاً بی‌هزینه است و «برنده همه را می‌برد» نقض می‌شود.

**چرا این باگ است:** نتیجه به تعداد راندهایی که بازیکن صادق *قبل از* رها شدن حریف توانسته بازی کند بستگی دارد — دلبخواهی و غیرقابل‌توضیح برای کاربر.

**تست پایه (قرمز):** `tests/unit/test_engine_protocol.py::test_grace_window_voids_when_neither_side_reaches_a_majority` — رفتار فعلی را pin می‌کند تا fix یک baseline قرمز داشته باشد.

**اصلاح (نیاز تصمیم):** راندی که یک طرف در آن *هیچ* نتیجهای نداده و طرف دیگر **حداقل یک راند دیگر بازی کرده**، باید forfeit به نفع طرف فعال شود؛ یا رهاکننده جریمه شود (هم‌راستا با H19).

### H23 — بدون matchmaking مهارت‌محور → جفت‌سازی شکارچی/شکار + کانال پول‌شویی
هیچ rating/ELO/Glicko وجود ندارد. جفت‌سازی تصادفی است. با پول واقعی:
- یک بازیکن ۱۳۰ms به‌طور سیستماتیک بازیکنان ۳۰۰ms را می‌خورد → ریزش فوری بازنده‌ها.
- **AML:** بدون KYC و بدون rating، دو حساب خودتان را به هم می‌بازید → USDT «تمیز» می‌شود. پلتفرم یک کانال پول‌شویی بی‌نقص است.

---

## ۳. MEDIUM — یک دم بلند از باگ‌ها و گپ‌ها

| # | یافته | فایل | توضیح |
|---|---|---|---|
| M1 | `verify_siwe` آدرس بازیابی‌شده را با آدرس ادعاشده مقایسه نمی‌کند | `auth.py:338-352` | API فعلاً در `main.py:520-522` نجات می‌یابد، ولی هر caller آینده یک باگ جعل هویت می‌گیرد. defense-in-depth |
| M2 | `_burn_nonce` هر خطای فایرستور را «تکرار» می‌بیند | `auth.py:186-204` | یک خطای گذرا = ورود ناموفق. TTL تعریف‌شده هم هرگز enforce نمی‌شود → collection بی‌نهایت رشد می‌کند |
| M3 | `_fresh_window` تطابق دقیق پنجره | `auth.py:137-143` | nonce صادرشده در ثانیه‌ی آخر یک پنجره‌ی ۵ دقیقه‌ای، ~۰.۱ ثانیه اعتبار دارد → درصدی از ورودها تصادفی fail می‌شود |
| M4 | `_remember_used` eviction در O(n) با `any()` | `auth.py:213-221` | روی سیل ۴۰۹۶ ورودی، ~۱۶M عمل → تقویت DoS |
| M5 | `verify_session` فرض می‌کند payload یک dict است | `auth.py:373-382` | `json.loads` روی غیر-object → `AttributeError` → 500 |
| M6 | `oracle._signature_to_low_s_bytes` با `v ^= 0x01` | `oracle.py:79-82` | برای `v∈{27,28}` غلط است (27→26). فعلاً **خفته** چون eth-account همیشه low-s با v∈{27,28} می‌دهد |
| M7 | `sign_settlement` هیچ‌چیز درباره‌ی منبع رکورد چک نمی‌کند | `oracle.py:175-242` | فقط shape check. هر مسیر آینده‌ای که یک record کلاینت-محور را فوروارد کند، امضای برنده‌ی دلخواه می‌سازد |
| M8 | `_load_signer()` در هر فراخوانی | `oracle.py:227,239` | بدون cache، بدون انتزاع KMS واقعی |
| M9 | `_settle_once` یک `HTTPException` از داخل mutate پرتاب می‌کند | `main.py:718-721` | داخل تراکنش؛ در حالت memory با rollback، در Firestore با abort |
| M10 | `match_view` نمای **قبل از** finalize را برمی‌گرداند | `main.py:556-560` | `_finalize_if_due` در Firestore یک Match تازه می‌خواند و آبجکت محلی را به‌روز نمی‌کند → divergence بین backendها |
| M11 | `claim_match` نیازی ندارد که claimer برنده باشد | `main.py:838-851` | هر شرکت‌کننده می‌تواند رکورد claim برنده را ثبت کند؛ `verify_settlement_tx` هم `receipt.from` را چک نمی‌کند |
| M12 | `username_lookup` آدرس کیف پول مالک را لو می‌دهد | `main.py:943-965` | هر کاربر با یک session می‌تواند نام‌ها را enumerate و به آدرس کیف پول نگاشت کند (۶۰/min/IP) |
| M13 | `username_claim` متن استثنای داخلی را لو می‌دهد | `main.py:939-940` | `detail=f"Username claim failed: {e}"` |
| M14 | `queue` با استیک متفاوت، ماتچ قبلی را برمی‌گرداند | `store.py:270-277`, `main.py:540-543` | بازیکن ۱۰ USDT را انتخاب می‌کند و در ماتچ ۱ USDT قبلی‌اش قرار می‌گیرد |
| M15 | `_cache` در `onchain` هرگز evict نمی‌شود | `onchain.py:71` | نشتی حافظه با هر match id جدید |
| M16 | `_rl_window` هرگز کلیدها را پاک نمی‌کند | `main.py:56` | نشتی حافظه با هر IP/آدرس جدید |
| M17 | ست‌های `_used_nonces`/`_revoked_jtis` بدون قفل، از threadpool | `auth.py:52-61` | عدم thread-safety |
| M18 | اعتماد به یک RPC واحد بدون quorum/fallback | `onchain.py:174-194, 341-357` | یک RPC آلوده می‌تواند `eth_chainId` غلط، وضعیت `Active` کاذب، یا receipt جعلی بدهد |
| M19 | `_match_id_bytes32` در oracle با id غیر-hex ۶۴ کاراکتری crash می‌کند | `oracle.py:124-130` | `bytes.fromhex` استثنا می‌دهد؛ `onchain` در همان حالت hash می‌کند → ناهم‌راستایی |
| M20 | `PLATFORM_FEE_BPS` از env قابل override است ولی قرارداد ۲۰۰ را hardcode دارد | `economy.py:88-93` | نمایش/ledger از زنجیره واگرا می‌شود |
| M21 | `prize` با گرد کردن ۲ رقم اعشار محاسبه می‌شود | `economy.py:180` | USDT ۶ اعشار است → خطای نمایش/ledger |
| M22 | `MIN_STAKE_UNITS` اعشار ۶ را hardcode می‌کند | `PulsarEscrow.sol:146` | قرارداد `decimals()` را نمی‌خواند؛ سرور می‌خواند → اختلاف |
| M23 | `MatchCreated` یک `totalPool` جعلی emit می‌کند | `PulsarEscrow.sol:237` | `received*2` در حالی که `totalPool` تا join صفر است |
| M24 | `setTreasuryWallet`/`setOracleSigner` یک‌مرحله‌ای و بدون timelock | `PulsarEscrow.sol:337-349` | یک آدرس غلط، تمام rake آینده را نابود می‌کند؛ تعویض oracle همه‌ی امضاهای در پرواز را بی‌اعتبار می‌کند |
| M25 | `usedSignatures` دفاع مرده است | `PulsarEscrow.sol:185,290-291` | replay هرگز به این گیت نمی‌رسد (status اول revert می‌کند). کامنت و تست آن را بیش از واقع می‌فروشند |
| M26 | `searchPlayers` فقط آدرس `0x…` را می‌شناسد | `realWeb3.ts:1444-1491` | جستجو با playerId همیشه «No player found» |
| M27 | «چالش دوست» یک ماتچ خصوصی نیست | `FriendChallengeModal.tsx:124-128` → `LobbyPage.tsx:654-659` | نام دوست فقط یک label نمایشی است؛ سرور یک حریف تصادفی جفت می‌کند |
| M28 | state تسویه روی rematch پاک نمی‌شود | `ReactionGamePage.tsx:1114-1128` | `onchainAction`/`settlementTxHash`/`lastProof`/`serverMatch`/`serverSession` باقی می‌مانند → لینک tx قدیمی روی ماتچ جدید |
| M29 | `setInterval` و `setTimeout` بدون cleanup | `ReactionGamePage.tsx:874-876`, `:576-579` | نشتی + setState بعد از unmount |
| M30 | `useSyncExternalStore` با `subscribe` اینلاین | `usePulsarStore.ts:318-322` | هر render هر consumer، listener را از نو می‌سازد |
| M31 | wins/XP/streak کاملاً کلاینت‌محور و قابل ویرایش | `usePulsarStore.ts:186-235` | هر کاربر `localStorage` را دستکاری می‌کند؛ `winStreak` هرگز پاس نمی‌شود → bonus مرده |
| M32 | داده‌ی ساختگی روی سطوح پولی | `realWeb3.ts:1405` (آدرس تصادفی leaderboard)، `DashboardPage.tsx:610,671` (180ms)، `LobbyPage.tsx:430,450`، `AppHeader.tsx:28-36` (latency تصادفی هر ۴ ثانیه) | برای محصولی که شعارش «اثبات رمزنگاری» است، این یک بدهی اعتمادی است |
| M33 | `isEscrowConfigured` سخت‌گیرتر از `escrowStatus` | `chain.ts:117-119` vs `escrowFlow.ts:20-40` | کاربر وارد یک دوئل استیک‌دار می‌شود و بعد از matchmaking با «Escrow is not configured» بیرون می‌افتد |
| M34 | نام شبکه/توکن hardcode شده روی Polygon Mainnet | `ConnectWallet.tsx:566,568,787,795`, `LobbyPage.tsx:329` | روی Amoy (پیش‌فرض) به کاربر گفته می‌شود روی mainnet است و کانترکت USDT mainnet نشان داده می‌شود |
| M35 | URI کهنه‌ی WalletConnect دوباره استفاده می‌شود + آستانه‌های ناهماهنگ | `ConnectWallet.tsx:323-339`, `realWeb3.ts:60-63` vs `:443` | deep link برای pairing قبلی باز می‌شود؛ `>=16` vs `>=10` |
| M36 | `cancelPendingConnect` یک provider زنده را orphan می‌کند + purge با حلقه‌ی رو-به-جلو | `realWeb3.ts:900-916`, `:431-438` | session relay بسته نمی‌شود؛ کلیدهای WC جا می‌مانند (همان باگی که `main.tsx:20-25` با حلقه‌ی معکوس اجتناب کرده) |
| M37 | تسویه فقط توسط برنده تریگر می‌شود | `ReactionGamePage.tsx:748-761` | اگر برنده تب را ببندد، بازنده نمی‌تواند تسویه را اجبار کند |
| M38 | `matchIdToBytes32` به `crypto.subtle` نیاز دارد | `gameServerClient.ts:314-320` | روی origin بدون HTTPS/localhost، `crypto.subtle` تعریف نشده → هر ماتچ استیک‌دار در مرحله‌ی deposit می‌شکند |
| M39 | `DuelCertificateModal` همیشه «NOT ON-CHAIN» نشان می‌دهد | `DuelCertificateModal.tsx:134-142,210-231` | `match.hash` هرگز توسط `recordMatch` پر نمی‌شود → ادعای «on-chain proof» غیرقابل‌دسترسی است |
| M40 | `EligibilityGate` فقط کلاینت است | `EligibilityGate.tsx:14,49` | با پاک کردن localStorage bypass می‌شود؛ هدر ادعای geo-enforcement دارد |
| M41 | گاز روی ۳۰ gwei در **همه‌ی** شبکه‌ها floor می‌شود | `escrowFlow.ts:98-111` | روی Polygon mainnet بی‌دلیل گران؛ باید فقط testnet/قابل‌تنظیم باشد |
| M42 | `subscribeGlobalMatches` وقتی feed خالی می‌شود پاک نمی‌کند | `realWeb3.ts:1349-1386` | ورودی‌های کهنه در Lobby می‌مانند |
| M43 | `LanguageContext` رجکس و replacement string می‌سازد | `LanguageContext.tsx:81-83` | مقدار حاوی `$&` جایگزینی ناخواسته می‌سازد |
| M44 | Sentry همیشه bundle می‌شود | `monitoring.ts:14` | حتی وقتی DSN ست نیست |
| M45 | `xpSystem.getLevel` و `getXPForLevel` معکوس دقیق نیستند | `xpSystem.ts:71-80` | `getLevelProgress` نزدیک آستانه‌ها کمی غلط می‌خواند |

---

## ۴. LOW — بدهی‌های کوچک

- `index.html:5` — `maximum-scale=1, user-scalable=no` → **نقض WCAG 1.4.4** (جلوگیری از zoom).
- `index.html:2` — `lang="en"` ثابت با وجود پشتیبانی fa/ar (RTL).
- دکمه‌های غیر-`<button>` بدون keyboard/role: `ReactionGamePage.tsx:1420`، `DashboardPage.tsx:426-432`، `FriendChallengeModal.tsx:142-148`، `DuelCertificateModal.tsx:90`.
- مودال‌ها بدون `role="dialog"`/`aria-modal`/focus-trap/Escape: `ConnectWallet`, `FriendChallengeModal`, `DuelCertificateModal`, `EligibilityGate`.
- آیکون-باتن‌های بدون `aria-label` (refresh/retry/refund/copy/explorer/edit-tag/remove-friend).
- `LanguageSelector.tsx:74-107` بدون `aria-expanded`/`aria-haspopup` و بدون ناوبری کلید.
- متن‌های hardcoded انگلیسی در `ReactionGamePage`, `ConnectWallet`, `DuelCertificateModal`, `FriendChallengeModal`, `AppHeader` — کلیدهای `t()` موجود استفاده نشده.
- `ClaimRequest.signature` دریافت و نادیده گرفته می‌شود (`main.py:489`).
- `.env.example` فقط ۶ متغیر دارد؛ کد به ۸+ متغیر دیگر نیاز دارد.
- `_finalize_if_due`/`_resign_stale_settlements` همه‌ی استثناها را می‌بلعند (`main.py:741-742,784-785`).
- `vite.config.ts:19` — `allowedHosts: true` (dev).
- `Deploy.s.sol:27` فقط روی chain 137 جلوی MockUSDT را می‌گیرد، نه روی سایر mainnetها.
- `compile_check.js:173-181` تست و اسکریپت deploy را کامپایل نمی‌کند → صحت `PulsarEscrow.t.sol` فقط با Foundry بررسی می‌شود.
- کد مرده: `SkillXPCompactCard.tsx`, `UserAvatar.tsx`, `escrowFlow.getUsdtBalance`/`getAllowance`, `withdrawFunds`/`depositFunds`, `antiCheat.entryFee`, `SUSPICIOUS_FAST_MS`, `utils.formatTimeAgo`, `restoreWalletConnectSession`, `connectWalletConnectTargeted`, `openPreparedWallet`, `loadUserData`.
- تکرار منطق: ریاضی جایزه در ۹ جای مختلف؛ استخراج «WC active session accounts» ۵ بار؛ initializer حالت Bo3 ۵ بار.
- هیچ linter برای TypeScript (فقط `tsc`)، هیچ linter/typecheck برای Python (نه ruff، نه mypy).
- `contracts/foundry.toml` — fuzz runs=256 (کم‌عمق).

---

## ۵. گپ‌های ساختاری (چیزهایی که **وجود ندارند**)

| گپ | اهمیت |
|---|---|
| **بدون KYC/AML** | محصول پول-واقعی بدون آن غیرقانونی است |
| **بدون age-gate سمت سرور** | `EligibilityGate` فقط کلاینت |
| **بدون ابزار مسئولانه‌بازی** (deposit limit، self-exclusion، cool-off) | الزام قانونی در اکثر حوزه‌ها |
| **بدون geo-blocking در لبه** (CDN/server) | مستندات خودش می‌گوید کلاینت کافی نیست |
| **بدون rating/ELO** | جفت‌سازی شکارچی/شکار + پول‌شویی |
| **بدون سیستم ban/velocity limit** | کشاورزی ربات مهارناپذیر |
| **بدون endpoint logout** | `revoke_session` مرده |
| **بدون dispute/appeal flow** | برنده‌ی معترض هیچ مسیری ندارد |
| **بدون admin/ops tooling** | نمی‌توان یک ماتچ را inspect یا force-settle کرد |
| **بدون metrics/alerting** | فقط Sentry؛ بدون dashboard، بدون SLO |
| **بدون public settlement log / explorer** | «non-custodial» ولی «trustless» نه |
| **بدون fiat on-ramp** | بازار آدرس‌پذیر = دارندگان USDT روی Polygon |
| **بدون growth loop** (referral/season/tournament) | بدون موتور رشد |
| **بدون progression معنادار** | XP در localStorage |
| **بدون PWA/native** | بازار موبایل |
| **بدون migration/versioning برای اسناد Firestore** | تغییر schema = شکستن داده‌ی قدیمی |
| **بدون analytics** | بدون visibility روی قیف |

---

## ۶. رودمپ تست (پیاده‌سازی کامل)

**وضعیت فعلی:** ۶ اسکریپت دست‌ساز با تابع `check()` — بدون test runner، بدون fixture، بدون coverage، بدون گزارش، بدون mock رسمی، و مسیر Firestore در CI **اجرا نمی‌شود**.

### T0 — زیرساخت تست (۱-۲ روز) — پیش‌نیاز همه‌چیز
1. مهاجرت به **pytest**: `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/adversarial/`. اسکریپت‌های فعلی به wrapper نازک تبدیل شوند تا `bun run test:*` نشکند.
2. `requirements-dev.txt`: `pytest`, `pytest-cov`, `pytest-asyncio`, `hypothesis`, `time-machine`, `respx`, `ruff`, `mypy`.
3. **تزریق ساعت (Clock injection):** موتور در ۱۲ نقطه `time.time()` صدا می‌زند. یک `match_engine.now()` معرفی کنید. امروز تست‌ها `revealed_at` را دستکاری می‌کنند — این یک hack است که باگ‌های واقعی زمان‌بندی را پنهان می‌کند.
4. **Fixture رسمی FakeRpc** (الان `urlopen` در ۳ فایل copy-paste شده).
5. **Firestore Emulator در CI** (`firebase emulators:exec`) — امروز `test_firestore_integration.py` بدون credential skip می‌شود، پس **هر باگ Firestore به production می‌رسد** (C1, C2, H3, H4 همه از همین جنس‌اند).
6. **Anvil + escrow مستقر در CI** تا digest کلاینت↔سرور↔قرارداد روی یک EVM واقعی تست شود.
7. گیت coverage با `--cov-fail-under` (از سطح فعلی شروع و ratchet شود).

### T1 — Unit (موتور، auth، oracle، economy، onchain)
- **ماتریس کامل state machine:** هر جفت (status × action) یا مجاز باشد یا یک خطای مشخص بدهد. `waiting|active|settled|void` × `commit|reveal|submit|settle|queue|match_view`.
- **تست‌های مرزی برای هر ثابت:** `MIN_HUMAN_MS`, `MAX_HUMAN_MS`, `REACTION_JITTER_MS`, `SUBMIT_LATENCY_TOLERANCE_MS`, `ROUND_EXPIRY_SECONDS`, `COMMIT_WINDOW_SECONDS`, `MATCH_SETTLE_GRACE_SECONDS`, `MATCH_EXPIRY_SECONDS`, `QUEUE_EXPIRY_SECONDS`, `MATCH_TIMEOUT_SECONDS`, `NONCE_WINDOW_SECONDS`.
- **Property-based (hypothesis):**
  - `settle()` هرگز برنده‌ای خارج از شرکت‌کنندگان برنمی‌گرداند.
  - `settle()` برای ورودی یکسان قطعی است.
  - `wins_a + wins_b <= ROUNDS` و برنده ≥۲ برد دارد.
  - اگر `status=="settled"`، `validatedTimes` هر دو طرف غیرخالی است.
  - `public_view(addr)` هرگز زمان حریف را قبل از ارسال متقابل لو نمی‌دهد.
  - برای هر دنباله‌ی اقدامات قانونی، `status` فقط در DAG جلو می‌رود.
- **جدول حقیقت `_validate_plausibility`.**
- **پاریتی `matchId`:** ۳۲-hex، ۶۴-hex، uppercase، با/بدون `0x`، غیر-hex، خالی، unicode — بین کلاینت/سرور/oracle/onchain.
- **`oracle.build_settlement_digest`** در مقابل یک mirror مستقل + یک فراخوانی واقعی `settleDuel` روی Anvil + fuzz روی رکوردهای تصادفی.
- **`oracle._signature_to_low_s_bytes` با ورودی high-s** (امروز تست نشده → باگ خفته M6 نامرئی است).
- **`economy.settlement_id_for` == id واقعی `record_settlement`** — این تست **امروز fail می‌شود** (H5).
- **auth:** مرز پنجره، tamper MAC، `parse_siwe` با پیام‌های خصمانه (چند خط Nonce، CRLF، homoglyph)، `verify_session` با payload غیر-dict/منقضی/revoke‌شده.
- **onchain:** شکست و retry `token_decimals` (C2)، `_decode_match` با payload کوتاه/زباله، `verify_deposit` با اختلاف اعشار، `verify_settlement_tx` با `to` غلط / receipt revert‌شده / log حذف‌شده / topic غلط.

### T2 — Integration
- **HTTP:** هر endpoint × (بدون auth / توکن بد / منقضی / revoke‌شده / غیر-شرکت‌کننده / معتبر).
- **Firestore Emulator:** enqueue هم‌زمان (N موازی → دقیقاً یک جفت‌سازی)، retry تعارض `update`، `player_live_match` بین دو instance، **افزایش واقعی سند `rate_limits`** (C1)، idempotency `record_settlement` با دو فراخوان هم‌زمان (H3)، مسابقه‌ی `username_claim`.
- **Deposit gate با emulator + fake RPC:** Active/Created/None/Settled/Refunded، اختلاف stake، اختلاف شرکت‌کننده، اختلاف chain، RPC down، **اعشار ناخوانا سپس خوانا** (C2).
- **قرارداد روی Anvil:** create→join→settle با امضای واقعی oracle؛ مسیرهای refund؛ مرز deadline؛ تسویه‌ی دوم؛ تسویه بعد از refund؛ refund بعد از settle.

### T3 — E2E (مرورگر)
Playwright + کیف پول mock EIP-1193 + Anvil محلی + سرور محلی.
- سناریوها: دسکتاپ connect→queue→create→join→۳ راند→settle→claim→گواهی با tx hash واقعی؛ **viewport موبایل (touch) → regression تپ دوباره (C4)**؛ refresh در میانه → resume؛ refresh بعد از تسویه → auto-settle (H11)؛ تعویض حساب/شبکه در حین ماتچ؛ رد کردن تراکنش در هر مرحله؛ شکست RPC در هر مرحله؛ refund بعد از تایم‌اوت.
- **Visual regression:** spawn هدف، انتقال راند، صفحه‌ی نتیجه، چیدمان RTL (fa/ar)، گواهی.
- **a11y:** axe-core روی هر صفحه؛ بازی فقط با کیبورد (هدف باید با کیبورد فعال شود)؛ focus trap مودال‌ها؛ `prefers-reduced-motion`.

### T4 — سوئیت خصمانه/امنیتی (رگرسیون دائمی)
یک تست به‌ازای هر یافته‌ی این گزارش، نام‌گذاری‌شده با شناسه‌ی یافته. مشخصاً: تپ دوباره، provider اشتباه، اعشار چسبنده، limiter مرده، دو-بار شمارش ledger، void شدن ماتچ تمام‌شده، مسابقه‌ی refund بی‌مجوز، claim جعلی، enumeration، تبانی/پول‌شویی.

### T5 — قرارداد
- Mockهای غایب: USDT بدون bool-return، USDT با `false`، fee-on-transfer، reentrant، blacklisting/pausing.
- **Invariant (Foundry `invariant_`):** مجموع موجودی escrow == مجموع استیک‌های فعال؛ یک ماتچ تسویه‌شده هرگز دو بار پرداخت نمی‌کند؛ `totalVolumeDistributed + totalFeesCollected == مجموع پرداخت‌ها`؛ یک ماتچ هرگز هم Settled هم Refunded نیست.
- `forge coverage` + fuzz runs 256 → 10k در nightly.
- Fork test در مقابل USDT واقعی Polygon.
- تحلیل استاتیک: `slither`/`aderyn` + `solhint`.

### T6 — گیت‌های کیفیت در CI
- coverage floor به‌ازای هر پکیج؛ mutation testing (`mutmut` روی موتور، `stryker` روی مسیرهای پولی کلاینت).
- قرارداد: `forge test` + `forge coverage` + slither.
- فرانت: `tsc` + **ESLint (وجود ندارد)** + vitest + Playwright + axe + budget حجم bundle + Lighthouse CI + snapshot RTL.
- سرور: **ruff + mypy (وجود ندارد)**.
- گیت «بدون داده‌ی ساختگی»: تستی که assert کند روی سطوح پولی `Math.random()` نیست.

### T7 — Load / Soak / Chaos
- k6/Locust: ۱۰۰۰ poller هم‌زمان؛ اندازه‌گیری read فایرستور به‌ازای هر ماتچ (امروز ۳ collection scan در هر poll → بمب هزینه).
- Chaos: کشتن RPC در میانه‌ی راند؛ کشتن Firestore؛ split کردن replica؛ تزریق تأخیر ۵ ثانیه‌ای RPC (اثبات H10).
- Soak ۲۴ ساعته: رشد حافظه (M15, M16).

---

## ۷. ممیزی محصول: آیا این یک محصول جهانی است؟

**مهندسی خوب است. محصول نیست.** به ترتیب اهمیت:

### ۷.۱ قانون‌گذاری — بلاکر شماره‌ی یک
شرط‌بندی ۱v۱ روی «مهارت» در اکثر بازارها به‌عنوان gambling/contest-of-skill **رگوله می‌شود**:
- **آمریکا:** ایالت‌به‌ایالت؛ چند ایالت مسابقات با ورودی‌پول را ممنوع می‌کنند. Skillz/WorldWinner تحت قوانین خاص ایالتی فعالیت می‌کنند.
- **اروپا/بریتانیا:** نهادهای ملی gambling؛ UK Gambling Commission بازی‌های «شانس برابر با مهارت» را licensable می‌داند.
- **الزامات:** نهاد دارای مجوز، KYC/AML، تأیید سن، ابزار مسئولانه‌بازی، geo-blocking در لبه، تیم T&S، و یک شریک پرداخت که حاضر باشد با یک اپراتور gaming کار کند.
- **هیچ‌کدام وجود ندارد.**
- **حوزه‌ی کاربر (ایران) تحت تحریم است:** hosting، banking، Tether (که آدرس‌ها را blacklist می‌کند)، Stripe/MoonPay — همه بسته. این یک آیتم «اسپرینت بعدی» نیست؛ تعیین می‌کند محصول می‌تواند وجود داشته باشد یا نه.

### ۷.۲ اعتماد — «non-custodial» ≠ «trustless»
oracle برنده را انتخاب می‌کند. بازیکن باید به اپراتور اعتماد کند. برای پول واقعی این شکاف اعتبار است. حداقل‌ها: انتشار آدرس oracle + یک settlement log عمومی و hash-chained، پنجره‌ی اعتراض، oracle چند-امضایی (2-of-3)، یا بردن محاسبه‌ی نتیجه روی زنجیره.

### ۷.۳ انصاف — latency برنده را تعیین می‌کند (H1)
دو بازیکن برابر، با پینگ تعیین می‌شوند. برای یک بازی مهارتی پول-واقعی این یک نقص طراحی است.

### ۷.۴ یکپارچگی — ربات‌ها
دوئل واکنش، قابل‌کشاورزی‌ترین ژانر ممکن است. «بیومتریک» کلاینت تزئینی است. یک اسکریپت ۱۳۰ms از ۹۵٪ انسان‌ها سریع‌تر است. **این بازی بدون یک استک جدی ضد-ربات (device attestation + anomaly detection) سودآور اجرا نمی‌شود** — و حتی با آن هم یک مسابقه‌ی تسلیحاتی است.

### ۷.۵ اقتصاد واحد
rake ۲٪ روی استیک ۱-۱۰ USDT. میانگین $2 → $0.04 در هر ماتچ. برای $10k/ماه به ۲۵۰٬۰۰۰ ماتچ در ماه نیاز دارید. rake فقط روی ماتچ‌های تسویه‌شده گرفته می‌شود (refund هیچ درآمدی ندارد). هزینه‌های سرور/RPC/Firestore/پشتیبانی/انطباق در مقیاس کوچک از این بیشتر است.

### ۷.۶ توزیع و نگهداشت
- فقط وب (اپ‌استورها gaming پول-واقعی بدون مجوز را ban می‌کنند).
- بدون fiat on-ramp → بازار آدرس‌پذیر = دارندگان USDT روی Polygon (کوچک).
- بدون referral/season/tournament → بدون موتور رشد.
- XP/level در localStorage → بدون progression معنادار.
- «چالش دوست» جعلی است.
- موبایل (بازار اصلی) با C4 شکسته است.

### ۷.۷ عملیات
بدون metrics/alerting، بدون admin tooling، بدون فرآیند dispute، بدون پشتیبانی، بدون runbook حادثه. برای یک محصول پولی این یک گپ سخت است.

### ۷.۸ صداقت رابط کاربری
آدرس‌های تصادفی در leaderboard، «network latency» جعلی، «human verification» جعلی، و گواهی‌ای که همیشه «NOT ON-CHAIN» می‌گوید چون `match.hash` هرگز پر نمی‌شود. برای محصولی که شعارش «اثبات رمزنگاری» است، فرستادن UI اثباتِ ساختگی یک بدهی اعتمادی نابودکننده است.

### ۷.۹ مسیرهای جایگزین که واقعاً می‌توانند برنده شوند
- **A. Free-to-play + تورنمنت‌های اسپانسری.** بدون ورودی‌پول → در اکثر بازارها بدون مجوز gambling → فردا می‌توانید جهانی عرضه کنید. درآمد از cosmetics، season pass، و prize pool اسپانسری. قرارداد escrow اختیاری/سازمانی می‌شود.
- **B. B2B: فروش پروتکل ضد-تقلب.** دارایی واقعاً نوآورانه‌ی این پروژه، پروتکل `commit → reveal → server-observed → oracle-signed settlement` است. آن را به‌عنوان SDK/API برای هر بازی مهارتی بفروشید (aim trainer، rhythm game، صلاحیت esports، proctoring از راه دور). بدون ریسک gambling، بدون هزینه‌ی جذب مصرف‌کننده.
- **C. پلتفرم بنچمارک/تمرین.** «چقدر واقعاً سریعی؟» — یک بنچمارک واکنش ویروسی و رایگان با نردبان صدک جهانی و نتایج قابل اشتراک. قیف بالای A/B.
- **D. پول واقعی اما مجوزدار و باریک.** یک حوزه‌ی مجوزدار انتخاب کنید، مجوز gaming بگیرید، KYC (Sumsub/Persona) + fiat (MoonPay/Transak)، مسئولانه‌بازی، و آن را به‌عنوان یک محصول رگوله اجرا کنید. گران و کند، ولی تنها مسیر به «پول واقعی در مقیاس».

**توصیه:** **C → A → B**، و D فقط اگر سرمایه و اشتهای مجوز دارید. و در هر حالت، CRITICAL/HIGHها را رفع کنید.

---

## ۸. قدم‌های بعدی برای انتشار واقعی

### مرحله ۰ — توقف خون‌ریزی (همین هفته)
1. رفع ۴ CRITICAL: C1 (limiter)، C2 (اعشار چسبنده)، C3 (provider)، C4 (تپ دوباره).
2. رفع HIGHهای مسیر پول: H3، H4، H5، H8، H10، H11، H12، H13.
3. **فریز کردن حالت پول واقعی:** `VITE_ESCROW_ADDRESS` در production unset بماند تا گیت‌ها پاس شوند (اپ همین حالا به حالت practice تنزل می‌کند — از این استفاده کنید).
4. راه‌اندازی T0 تا هر fix با یک تست رگرسیون فرود بیاید.

### مرحله ۱ — صادق و ایمن (۲-۴ هفته)
5. حذف تمام UI ساختگی (آدرس‌های leaderboard، latency، verification، ادعای on-chain گواهی) و پر کردن `match.hash`.
6. افزودن عملیات: metrics، alerting، admin view، مسیر dispute/پشتیبانی.
7. افزودن matchmaking مهارت‌محور + rating.
8. رفع موبایل (C4 + کیف پول embedded مثل Privy/Dynamic به‌جای WalletConnect).
9. انتشار آدرس oracle + یک settlement log عمومی.
10. رفع انصاف latency (H1) با جبران RTT یا سقف پینگ.

### مرحله ۲ — تبدیل به محصول (۱-۳ ماه)
11. قیف free-to-play (گزینه‌ی C)، فصل‌ها، تورنمنت‌ها، cosmetics.
12. Fiat on-ramp + KYC (فقط اگر پول واقعی).
13. تصمیم درباره‌ی نهاد حقوقی + مجوز.
14. استک ضد-ربات (attestation + anomaly detection + velocity limits).

### مرحله ۳ — مقیاس
15. سرورهای چند-منطقه‌ای، matchmaking با جبران latency.
16. Load test ۱۰۰۰ ماتچ، تمرین‌های chaos، runbook on-call.
17. **ممیزی قرارداد توسط یک شرکت واقعی** (نه AI) قبل از هر پول واقعی.

---

## پیوست الف — جدول خلاصه‌ی یافته‌ها

| شدت | تعداد | نمونه‌ها |
|---|---|---|
| CRITICAL | ۴ | limiter مرده، اعشار چسبنده، provider اشتباه، تپ دوباره‌ی موبایل |
| HIGH | ۲۳ | انصاف latency، commitment بی‌اثر، ledger TOCTOU، fail-open config، Host header، void زودهنگام، I/O زیر قفل، stale closure، موجودی صفر، اعشار، race هویت، ضد-تقلب تزئینی، گیر کردن پول، deadline، refund بی‌مجوز، join بی‌cutoff، **CI قرارداد شکسته**، بدون logout، بدون rating |
| MEDIUM | ۴۵ | جدول بخش ۳ |
| LOW | ~۲۰ | بخش ۴ |
| گپ ساختاری | ~۱۷ | جدول بخش ۵ |
| **جمع** | **~۱۰۸** | |

## پیوست ب — آنچه این پروژه **درست** انجام داده (تا از دست نرود)

- پروتکل commit→reveal→server-observed با MAC هر-بازیکن (`_result_proof`) — طراحی درست و غیرقابل‌تقلب در سطح proof.
- امضای oracle با EIP-191 روی `abi.encodePacked` با binding به `chainid` + `address(this)` + `matchId` + `deadline` + `nonce` — domain separation کافی.
- low-s enforcement در قرارداد (EIP-2) + نرمال‌سازی در سرور.
- `nonReentrant` + CEI در تمام state-changerها.
- SIWE با nonce امضاشده با HMAC (نه nonce خودساخته).
- deposit gate مستقل از زنجیره با fail-closed.
- rollback صریح روی شکست امضا (`_attach_signed_envelope`).
- پین‌های parity بین کلاینت/سرور/قرارداد (`_match_id_to_bytes32`, digest, struct layout).
- مستندات صادقانه‌ی محدودیت‌ها در README و DEPLOYMENT.
- ۱۱ دور ممیزی قبلی با یافته‌های واقعی و رفع‌شده — این یک فرهنگ مهندسی است، نه یک تصادف.
