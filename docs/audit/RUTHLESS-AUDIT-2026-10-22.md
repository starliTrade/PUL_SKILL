# حسابرسی بی‌رحمانه‌ی PULSAR

**تاریخ:** ۲۰۲۶-۱۰-۲۲ · **شاخه:** `arena/a9a25b53-pul-skill` · **کامیت مبنا:** `365396d`
**دامنه:** قرارداد `PulsarEscrow.sol`، سرور FastAPI، کلاینت React/Web3، اوراکل، احراز هویت، ذخیره‌سازی، اقتصاد، ضدتقلب، تست‌ها، گیت‌ها و مستندات.
**اصل حاکم بر این گزارش:** هیچ ادعایی «به نفع پروژه» تفسیر نشده است. هر جمله یا با کد/اجرا اثبات شده یا صریحاً «تأییدنشده» علامت خورده است. جایی که کد درست است، گفته شده؛ جایی که ادعا دروغ است، با شماره خط گفته شده.

---

## ۰. حکم اجرایی

PULSAR یک **نمونه‌ی مهندسی‌شده‌ی بسیار بالاتر از میانگین** است: قرارداد بدون وابستگی، تست‌های سرور سبز، تایپ‌چک تمیز، معماری commit/reveal، لجر ایدمپوتنت، و فرهنگی از کامنت‌های حسابرسی که خودش نقص‌های قبلی را ثبت کرده است. این را نمی‌شود انکار کرد.

اما در وضعیت فعلی، این پروژه **یک محصول پول‌واقعیِ قابل‌عرضه به دنیا نیست** — و حتی «بتای بسته» هم نیست، چون سه نقص ساختاری دارد که هر کدام به‌تنهایی کافی‌اند:

| # | نقص وجودی | چرا کشنده است |
|---|---|---|
| **۱** | **بازی با اسکریپت به‌راحتی برنده می‌شود و هیچ دفاع سرورسمت مؤثری وجود ندارد** | یک بات ۵۰ خطی با `sleep(targetMs + 110)` هر راند را با ۱۱۰ms می‌برد؛ انسان‌ها ۱۸۰–۳۰۰ms هستند. با ۲٪ کارمزد، هر ۱۰۰ دوئل ۱۰ دلاری ≈ +۹۴۰ دلار سود خالص. حساب/کیف پول رایگان است و KYC فقط یک تیک «من ۱۸ سال دارم» است. این یک ماشین پول‌چاپ برای اولین اسکریپتر است. |
| **۲** | **ضدسوءاستفاده، بازیکن عادی را بیرون می‌اندازد** | هر `POST /api/queue` — از جمله pollهای صف — به‌عنوان «شروع دوئل» شمرده می‌شود. سقف ۲۰ در ۱۰ دقیقه. کلاینت هر ۲.۵–۱۰ ثانیه poll می‌زند؛ یعنی تقریباً **بعد از دو جست‌وجوی صف، بازیکن ۱۵ دقیقه قفل می‌شود** (اثبات اجرایی در §4.C-01). |
| **۳** | **پول می‌تواند بدون keeper برای همیشه در escrow بماند** | برنده باید در ۳۰ دقیقه‌ی پس از فعال‌سازی، خودش تراکنش `settleDuel` را با گس خودش بفرستد. اگر تب را ببندد، جایزه‌اش سوخته و فقط stake برمی‌گردد. هیچ relayer/keeper‌ای وجود ندارد. |

به این‌ها اضافه کنید: **فید «LIVE ARENA» هرگز چیزی نشان نمی‌دهد** (کلاینت فیلد `entryFee` را می‌خواند که سرور هرگز نمی‌نویسد)، **پروفایل و لیست دوستان هرگز ذخیره نمی‌شود** (قوانین Firestore همه‌ی نوشتن‌های کلاینت را رد می‌کند و خطا بلعیده می‌شود)، و **از اولین مسابقه‌ی رنکد، ثبت نتیجه/XP در کلاینت می‌شکند** چون سند لجر فیلد `history` ندارد (H-17)، و **محدودیت «خودحذفی» را می‌توان با یک درخواست از ۳۶۵ روز به ۱ روز کاهش داد** در حالی که UI می‌گوید «قابل لغو زودهنگام نیست».

### کارت امتیاز بلوغ

| محور | امتیاز (۰–۱۰) | توضیح کوتاه |
|---|---:|---|
| قرارداد و مسیر پول | ۸ | مستحکم، غیرامانی، ضدتکرار؛ اما غیرقابل‌ارتقا، بدون keeper و بدون audit بیرونی. |
| منطق مسابقه | ۷ | Bo3، forfeit غایب، زمان سرورمحور؛ اما «انسانیت» را کلاینت تعیین می‌کند. |
| ضدتقلب | ۲ | تزئینی. تله‌متری کلاینت هیچ‌گاه به سرور نمی‌رسد و اثری ندارد. |
| اقتصاد/لجر | ۶ | ایدمپوتنت و اتمیک؛ اما خطاها بلعیده می‌شوند و آمار می‌تواند از زنجیره واگرا شود. |
| احراز هویت | ۶ | nonce با MAC، burn دائمی، jti؛ اما توکن در localStorage و revoke بی‌صدا. |
| مقیاس‌پذیری | ۲ | صف روی یک سند داغ، poll نوشتنی، محدودیت‌ها per-process در قطعی. |
| انطباق/حقوقی | ۱ | خودحذفی قابل دور زدن، بدون ژئوبلاک/KYC/سن، بدون حذف حساب، بدون CSP. |
| صداقت ادعاها | ۴ | مستندات خودانتقادی کم‌نظیر، اما اعداد کهنه و یک ادعای «بیومتریک» در UI. |
| تست/گیت | ۶ | ۲۹۴ تست سبز واقعی؛ اما coverage ادعایی بازتولید نشد و forge/E2E اجرا نشد. |
| UX/محصول | ۵ | فید مرده، دوستان ازدست‌رفته، خطاهای بی‌بازگشت در مسیر پول. |

**نتیجه:** ✔️ «دموی مهندسی قابل‌تحسین» — ✖️ «محصول جهانی با پول واقعی» (فاصله: ≈۱۰–۱۲ نفر-ماه برای production در یک حوزه، ≈۱۸–۲۲ نفر-ماه برای جهانی + ۳ تا ۶ ماه تقویمی برای audit/حقوقی + مجوز حوزه‌های قضایی).

### ۰.۱ فهرست سریع یافته‌های بحرانی و بالا

| شناسه | عنوان | محل کلیدی |
|---|---|---|
| C-01 | velocity، pollهای صف را می‌شمارد ⇒ قفل ۱۵ دقیقه‌ای بازیکن | `main.py:1395` · `abuse.py:29–33` |
| C-02 | بات با `sleep(target+110)` برنده است؛ ضدتقلب تزئینی | `match_engine.py:449–470` · `antiCheat.ts` |
| C-03 | بدون keeper: جایزه می‌سوزد، پول قفل می‌ماند | `PulsarEscrow.sol:375,452` |
| H-01 | خودحذفی با درخواست دوم کوتاه می‌شود | `limits.py:139–148` |
| H-02 | در قطعی Firestore کنترل‌ها fail-open می‌شوند | `limits.py:69–90` |
| H-03 | سقف پینگ اختیاری + اندازه‌گیری با RPC | `main.py:1120` · `gameServerClient.ts:458` |
| H-04 | فید زنده هرگز چیزی نشان نمی‌دهد (`entryFee`) | `realWeb3.ts:1499–1525` |
| H-05 | پروفایل/دوستان ذخیره نمی‌شود و پاک می‌شود | `realWeb3.ts:1470–1494` · `firestore.rules:41` |
| H-06 | production می‌تواند بی‌صدا memory اجرا شود | `store.py:965–978` · `main.py:577` |
| H-07 | کلید اوراکل در env، کنترل کامل نتیجه | `oracle.py:43,71–84` |
| H-08 | ادعای «بیومتریک»/«۱۰۰٪ ضدبات» در UI | `translations.ts:460,885` |
| H-09 | logout/revoke خطا را می‌بلعد (fail-open) | `auth.py:320–350` |
| H-10 | dispute فقط در حافظه | `store.py:1009–1016` |
| H-11 | صف: سند داغ + scan کامل | `store.py:417–470` |
| H-12 | sweep امضاها: limit 100 بدون cursor | `main.py:1712–1760` |
| H-13 | probe A6 هرمتیک نیست (خطای کاذب) | `probe_a6.py:8,47` |
| H-14 | خطای لجر بلعیده می‌شود | `economy.py:400–431` |
| H-15 | میانگین زمان واکنش اشتباه وزن‌دهی می‌شود | `economy.py:473` |
| H-16 | بدون CSP/هدرهای امنیتی | `index.html` · `main.py` |
| H-17 | پس از اولین settle، `recordMatch` می‌شکند (history تعریف نشده) | `usePulsarStore.ts:266` · `realWeb3.ts:1353` |



---

## ۱. روش، محیط و محدودیت‌ها

### چه چیزی واقعاً اجرا شد

| بررسی | دستور | نتیجه‌ی خام |
|---|---|---|
| تست سرور | `ORACLE_SIGNING_SECRET=… PULSAR_ENV=dev .venv/bin/python -m pytest -q` | **۲۹۴ passed، ۴۲ skipped، ۱ warning، ۷.۵s** |
| Coverage (همان ترکیب گیت) | `coverage run -m pytest` + `--append` برای `scripts/test_game_server.py` و `scripts/test_http_e2e.py` | **۷۲٪ — زیر floor ۷۹ ⇒ گیت قرمز** |
| لینت | `ruff check api scripts tests` | All checks passed |
| تایپ | `.venv/bin/python -m mypy` | Success: 14 source files |
| کلاینت (تایپ) | `npx tsc --noEmit` | exit 0 |
| کلاینت (تست) | `npx vitest run` | **۵۱ فایل / ۲۱۶ تست پاس** |
| اسموک پروتکل | `scripts/test_game_server.py` | ALL SMOKE TESTS PASSED |
| E2E HTTP | `scripts/test_http_e2e.py` | ALL HTTP E2E TESTS PASSED (rollback، retry، 429+Retry-After) |
| کامپایل قرارداد | `node contracts/test/compile_check.js` | PASSED — solc 0.8.20، paris+shanghai |
| پروب A5/A8 | `scripts/probe_a5.py` / `probe_a8.py` | همه PASS |
| پروب A6 | `scripts/probe_a6.py` | در محیط تمیز PASS؛ با `ORACLE_SIGNING_SECRET` ازپیش‌تنظیم **FAIL کاذب** (باگ خودِ پروب، §H-13) |
| مهاجرت/پایداری | — | اجرا نشد (نیازمند emulator) |

### چه چیزی اجرا **نشد** و بنابراین تأیید نمی‌شود

- `forge test`، `forge coverage` و تست‌های invariant: **Foundry نصب نیست** و دانلود باینری از `release-assets.githubusercontent.com` در این سندباکس مسدود است. عدد «۸۱ تست قرارداد» فقط از روی شمارش `function test` (که **۸۰** است) و فایل‌ها تأیید می‌شود، نه از اجرا.
- Playwright/E2E مرورگر: مرورگرها نصب نیستند.
- Firestore emulator / anvil / تست‌های chain: زیرساخت محلی موجود نیست.
- `scripts/verify.sh` و `chaos_suite.py`: به همین زیرساخت‌ها وابسته‌اند (`chaos` صریحاً exit 2 می‌دهد: «API up نیست»).

**قاعده‌ی گزارش:** هر جا نوشته «سبز»، یعنی اجرا شده. هر جا «ادعا»، یعنی فقط کد خوانده شده. هیچ‌کدام را قاطی نمی‌کنم.

### روش

۱. خواندن کامل/جزئیِ خط‌به‌خطِ ۱۴ فایل سرور، قرارداد ۶۱۳ خطی، `chain.ts`، `escrowFlow.ts`، `gameServerClient.ts`، `antiCheat.ts` و بخش‌های حساس `ReactionGamePage.tsx`/`realWeb3.ts`/`usePulsarStore.ts`.
۲. اجرای واقعی سناریوهای حمله روی موتور (بات، poll صف، ۱-۱، void).
۳. مقایسه‌ی هر ادعای README/HOW-IT-WORKS با کد.
۴. بازتولید عددهای ادعایی (تست/coverage) با دستور خودشان.

---

## ۲. نقشه‌ی سیستم و جریان پول (خط‌به‌خط)

### ۲.۱ قرارداد — `contracts/PulsarEscrow.sol` (۶۱۳ خط)

| تابع | خط | کاری که واقعاً می‌کند |
|---|---|---|
| `createDuel` | 320 | `transferFrom` با اندازه‌گیری اختلاف موجودی و ثبت **مبلغ واقعی دریافتی** (`received`) به‌جای مبلغ اسمی؛ ثبت `createdAt` و `player1`. |
| `joinDuel` | 349 | همان اندازه‌گیری؛ `player2`، `status=Active`، `activatedAt`. |
| `settleDuel(proof)` | ۳۷۵ | `winner` باید یکی از دو بازیکن باشد؛ `block.timestamp ≤ deadline`؛ `deadline ≤ clockOrigin + MATCH_TIMEOUT`؛ digest شامل `chainid` و `address(this)`؛ `usedSignatures` قبل از `ecrecover`؛ کارمزد **۲۰۰bps = ۲٪**؛ `_pay` به `pendingWithdrawals` (بدون revert اگر توکن بلاک کند). |
| `refundTimeoutMatch(matchId)` | ۴۵۲ | permissionless؛ فقط پس از `clockOrigin + 30min + 10min`؛ `Created ⇒ Cancelled`، `Active ⇒ Refunded`؛ هر دو stake. |
| `withdraw()` | 528 | برداشت اعتبار داخلی؛ برای توکن‌های بلاک‌شده مسیر نجات دارد. |
| `transferOwnership/acceptOwnership` | 124 / 132 | دو مرحله‌ای. **بدون pause، بدون upgrade، بدون تغییر کارمزد.** |

**نکات مثبت اثبات‌شده:** هیچ‌جا کلید خصوصی/user key نگه‌داری نمی‌شود؛ مبلغ جایزه از `totalPool` محاسبه می‌شود نه از ورودی امضا؛ امضا به chain/contract مقید است؛ `usedSignatures` قبل از `ecrecover` ست می‌شود (ضدّ replay)؛ `nonReentrant`؛ low-s اجباری.

**نکات منفی:** قرارداد **غیرقابل‌ارتقا** است؛ `PLATFORM_FEE_BPS` ثابت و ۲٪ است (خوب برای اعتماد، بد برای تغییر مدل کسب‌وکار)؛ **keeper ندارد**؛ treasury یک آدرس ثابت است؛ و اگر برای یک match هرگز `settleDuel` یا `refundTimeoutMatch` صدا زده نشود، پول تا ابد قفل می‌ماند (هیچ `forceRefund`/`sweep` وجود ندارد).

### ۲.۲ سرور — از SIWE تا امضا

```
POST /api/auth/nonce      → nonce = b64(domain|addr|window|rand).HMAC   (auth.py:122)
POST /api/auth/verify     → personal_sign(message) → ecrecover → burn nonce
                            (create اتمیک در Firestore) → session token
POST /api/queue           → _auth_staked: eligibility.require + limits.require
                            + abuse.require + abuse.note_start + ALLOWED_STAKES
                            → enqueue (سند صف per-stake) → matchId
POST /api/round/commit    → commit_hash + commit_salt (سرور) 
POST /api/round/target    → target_ms ∈ [1200,2700] + resultProof = HMAC(...)
POST /api/round/result    → proof check + plausibility + observed_ms = elapsed − target_ms
POST /api/match/{id}/settle → store.update(_settle_once) → engine.settle → oracle.sign
POST /api/match/{id}/claim  → verify_settlement_tx (receipt + event + winner) → ledger
```

**لایه‌ی احراز هویت** (`auth.py`) از بسیاری از پروژه‌های مشابه بهتر است: nonce با MAC، پنجره‌ی زمانی، burn دائمی، `jti` revocation، TTL توکن ۲ ساعت، `compare_digest`. یک ایراد: **`revoke_session` استثناها را می‌بلعد** (fail-open) و توکن در `localStorage` است (هر XSS = دزدی نشست).

**لایه‌ی ذخیره‌سازی** (`store.py`): دو بک‌اند، `SCHEMA_VERSION`، `SchemaVersionError`، `_mirror_idempotent`، sweepها. اما:
- `PULSAR_MATCH_STORE=auto` (پیش‌فرض) در صورت خطای Firestore **به memory سقوط می‌کند** و فقط یک `print` می‌دهد (`store.py:971–977`). `REQUIRED_PRODUCTION_ENV` (`main.py:577`) شامل `PULSAR_MATCH_STORE` یا `FIRESTORE_PROJECT_ID` **نیست**. یعنی یک production با کلیدهای escrow اما بدون Firestore سالم بالا می‌آید و «هیچ مسابقه‌ای پایدار نیست» — همان چیزی که پول به آن تکیه دارد.
- `DurableMatchStore.update` در هر اقدام راند یک `get` اضافه برای mirror می‌زند.

**لایه‌ی اقتصاد** (`economy.py`): یک تراکنش اتمیک شامل gate، match، شمارنده‌های هر دو کاربر و leaderboard؛ `settlementId = sha256(matchId|outcome|stake|settled_at|times)`؛ تضاد claim محافظت‌شده. اما **هر استثنا بلعیده می‌شود** (`except Exception: _log_ledger_error`) — یعنی XP/آمار می‌تواند بی‌صدا از زنجیره واگرا شود و تنها سیگنال، شمارنده‌ی `failures` در health است.

### ۲.۳ کلاینت — از tap تا claim

```
tap → startServerMatch (serverStartRef) 
    → ensureSession (personal_sign، fallback signMessage روی -32601/-32602)
    → confirmEligibility (best-effort)
    → measureServerRttMs  ← این هم RTT را از /api/health می‌گیرد که RPC زنجیره می‌زند!
    → queueForMatch + poll تا ۹۰s
    → approveUsdt → creator: skip createDuel اگر status≠0 ؛ joiner: poll تا ۱۲۰s و
      بررسی stakeAmount on-chain
    → commit → reveal → setTimeout(targetMs) → submit(resultProof, rtt)
    → waitForOpponentDisclosure (۱۲۰s موازی) → settleMatch (ایدمپوتنت)
    → winner: claimMatch → findSettlementTx → recordMatch
```

**نقاط قوت:** بررسی `stakeAmount` توسط joiner (ضدّ حمله‌ی «کرئیتور ۰.۰۰۰۰۰۱ واریز کند»)؛ عدم واریز مجدد creator؛ retry برای settle؛ refund در UI.

**نقاط ضعف:** تصمیم «انسان/بات» در `AntiCheat` مرورگر گرفته می‌شود و هرگز به سرور نمی‌رود؛ `waitForOpponentDisclosure` یک حلقه‌ی موازی است که ممکن است ۱۲۰ ثانیه بعد پیام «حریف جواب نداد» بدهد در حالی که سرور بعداً settle می‌کند؛ و **`measureServerRttMs` روی endpoint‌ای است که I/O زنجیره دارد** (پایین).

### ۲.۴ مدل اعتماد (آنچه README نمی‌گوید)

| دارایی/تصمیم | چه کسی کنترل می‌کند | قابل‌تغییر؟ |
|---|---|---|
| پول | قرارداد | فقط با امضای اوراکل یا refund پس از ۴۰ دقیقه |
| **برنده** | سرور (اوراکل) | **کاملاً** — هر شرکت‌کننده‌ای را می‌تواند برنده کند |
| جفت‌شدن | سرور | کاملاً (می‌تواند قربانی را به هم‌دست خودش برساند) |
| انسان‌بودن | کلاینت | ادعایی، بدون اثبات |
| آمار/XP | سرور | لجر shadow؛ در خطا واگرا |

**جمله‌ی صادقانه:** PULSAR «non-custodial» است (پول را نگه نمی‌دارد) اما **trustless نیست**. اپراتور می‌تواند نتیجه‌ی هر مسابقه‌ی فعال را تعیین کند. برای یک محصول واقعی، این باید در ToS و صفحه‌ی «چطور کار می‌کند» صریح باشد، و بهتر است با کمیته‌ی امضا/تأخیر پرداخت/گزارش شفافیت مهار شود.

---

## ۳. جدول ادعا در برابر واقعیت

| # | ادعا (منبع) | شاهد در کد | حکم |
|---|---|---|---|
| ۱ | «کلاینت by design غیرقابل‌اعتماد است» (README:3) | منطق راند/تسویه سمت سرور؛ اما امتیاز «انسان» سمت کلاینت | **نسبی — نیمه‌درست** |
| ۲ | «هر نتیجه از commit/reveal عبور می‌کند» (README:4) | `match_engine.py:331–396`؛ proof سمت سرور | **درست، اما بی‌اثر برای بات** |
| ۳ | «تسویه با امضای اوراکل» | `oracle.py` + `settleDuel` | **درست** |
| ۴ | «هیچ کیف پول امانی» | `_pay→pendingWithdrawals` | **درست** |
| ۵ | «۹۸٪ برنده / ۲٪ خزانه» | `PLATFORM_FEE_BPS=200` | **درست** |
| ۶ | «گیت‌های انصاف سمت سرور: ping cap، rating band، نزدیک‌ترین اتصال» | `rttMs` **اختیاری** (`main.py:1120`)؛ rating در memory | **اغراق — قابل دور زدن با حذف فیلد** |
| ۷ | «هیچ داده‌ی ساختگی» (README:61) | گیت lint وجود دارد؛ اما فید زنده مرده و `getRandomOpponent` نام حریف می‌سازد | **نیمه‌درست** |
| ۸ | «گیت eligibility فقط self-declaration است و سرور هیچ اجرایی ندارد» (README:64) | `eligibility.py` + `_auth_staked` **سرور را الزام می‌کند** | **کهنه/کم‌گویی — غلط** |
| ۹ | «۲۰۲ تست/۴۸ فایل فرانت» | واقعیت: **۲۱۶/۵۱** | **کهنه (به نفع پروژه نیست، فقط قدیمی)** |
| ۱۰ | «۲۷۸ تست سرور» | واقعیت: **۲۹۴ passed + ۴۲ skipped** | **کهنه** |
| ۱۱ | «۸۱ تست قرارداد» | ۸۰ `function test` در فایل‌ها؛ اجرا نشد | **تأییدنشده** |
| ۱۲ | «coverage ratchet 84٪ (floor 79)» | اندازه‌گیری با همان ترکیب: **۷۲٪** (بدون emulator) | **بازتولید نشد** |
| ۱۳ | «`bun run verify` = ۱۵ چک، ۰ خطا؛ Playwright همیشه SKIP» | `verify.sh` الان Playwright را با گارد «حداقل ۲۰ پاس» اجرا می‌کند | **کهنه/متناقض** |
| ۱۴ | «CI همان گیت‌ها را اجرا می‌کند» | `ci.yml:231–235` واقعاً `verify.sh` را اجرا می‌کند؛ ولی هدر خود `verify.sh:18–25` می‌گوید اجرا نمی‌کند | **درست در عمل، متناقض در مستند** |
| ۱۵ | «Persistence: Firestore … با fallback حافظه» | در `auto` حتی در production به memory سقوط می‌کند | **درست، اما خطرناک** |
| ۱۶ | «قرارداد dependency-free» | فقط interfaceهای داخلی | **درست** |
| ۱۷ | «ratings process-local» (README:72) | `store.py:1018–1030` | **درست (خودافشا)** |
| ۱۸ | «اسناد حقوقی فقط انگلیسی» | `translations.ts` | **درست** |
| ۱۹ | «کنتراست WCAG AA را رد می‌کند» | خودافشا | **درست** |
| ۲۰ | «no real-money deployment authorized» | گیت env + `DEPLOYMENT.md` | **درست** |
| ۲۱ | UI: «Zero-Bot Handshake» / «احراز بیومتریک ضد ربات» / «Biometric Analysis» | `translations.ts:460,885` — هیچ داده‌ی بیومتریکی جمع نمی‌شود؛ فقط tap روی یک node | **دروغ محصولی** |
| ۲۲ | UI: «۱۰۰٪ Anti-Bot» (کامنت `ReactionGamePage.tsx:1755`) | تله‌متری کلاینت هرگز ارسال نمی‌شود | **دروغ** |
| ۲۳ | «سرور RTT کلاینت را کم نمی‌کند» (README:57) | `_rank_time` فقط `observed_ms` | **درست** |
| ۲۴ | LOAD-REPORT: «۳۵ read/match در برابر هدف <۲۰» | خودافشا | **درست (هدف محقق نشده)** |
| ۲۵ | «۵۳ یافته رفع شد» (HOW-IT-WORKS) | قابل راستی‌آزمایی نیست | **تأییدنشده** |

**جمع‌بندی این جدول:** الگوی غالب «کهنه‌شدن» است، نه فریب عامدانه — به‌جز دو مورد UI («بیومتریک» و «۱۰۰٪ Anti-Bot») که برای یک محصول پول‌واقعی ریسک حقوقی واقعی هستند (FTC/CPC-style deceptive claim).

---

## ۴. یافته‌ها — بحرانی

> هر یافته: محل، مشاهده، اثر، بازتولید، اصلاح. «اثبات‌شده» یعنی اجرا کردم.

### C-01 · محدودیت velocity، pollهای صف را «شروع دوئل» می‌شمارد و بازیکن عادی را ۱۵ دقیقه قفل می‌کند
**محل:** `api/main.py:1395` (`abuse.note_start(address)` بدون قید، پیش از اعتبارسنجی stake و پیش از return زودهنگام «match زنده») · `api/abuse.py:29–33,130–139` · `src/pages/ReactionGamePage.tsx:336–340`

**مشاهده:** هر درخواست `POST /api/queue` یک ورودی به `recentStarts` اضافه می‌کند. سقف `VELOCITY_MAX_MATCHES=20` در پنجره‌ی ۶۰۰ ثانیه؛ با رسیدن به ۲۰، `velocityCooldownUntil = now+900`. کلاینت در انتظار حریف، همان endpoint را با backoff ۲.۵→۵→۷.۵→۱۰ ثانیه صدا می‌زند؛ یک جست‌وجوی ۹۰ ثانیه‌ای ≈ ۱۰–۱۱ درخواست. **دو جست‌وجو = ۲۰+ ⇒ درخواست بعدی 403 با پیام «Too many duels started in a short window»**.

**اثر:** بازیکن عادی بعد از دو تلاش (یا یک انتظار طولانی + یک retry) از بازی بیرون می‌افتد؛ در حالی که مهاجم واقعی (اسکریپت) با یک match در ثانیه هم زیر ۲۰ در ۱۰ دقیقه نمی‌ماند؟ نه — او هم محدود می‌شود، اما او می‌تواند هزار کیف پول بسازد. یعنی این کنترل **دقیقاً علیه بازیکن عادی کار می‌کند و علیه بات سیبیل هیچ**.

**بازتولید (اجرا شد):**
```python
for i in range(19): abuse.note_start(addr)
abuse.require(addr)          # OK
abuse.note_start(addr)       # 20th
abuse.require(addr)          # → AbuseError: 15-minute cooldown
```
خروجی: `after 19 polls: allowed` / `after 20 polls: BLOCKED -> Too many duels started…`

**اصلاح:** `note_start` فقط وقتی صدا زده شود که یک match **جدید** ساخته می‌شود (خروجی `enqueue` با `created=True`)، یا صراحتاً pollها را از شمارش خارج کند (flag `is_poll`). سقف را به «دوئل‌های کامل‌شده/شروع‌شده‌ی یکتا» گره بزنید، نه به درخواست HTTP. تست رگرسیون: ۴۰ poll پشت‌سرهم نباید بلاک شود.

---

### C-02 · بازی با اسکریپت برنده می‌شود؛ «ضدتقلب» فقط تزئینی است
**محل:** `api/match_engine.py:449–470` (`_validate_plausibility`) · `api/match_engine.py:105` (`MIN_HUMAN_MS=105`) · `src/lib/antiCheat.ts` (کل فایل) · `src/pages/ReactionGamePage.tsx:1755`

**مشاهده:** سرور فقط سه چیز را بررسی می‌کند: (۱) زمان ادعاشده ≥۱۰۵ms باشد، (۲) ادعا از observed سرور سریع‌تر نباشد، (۳) ادعا بیش از ۴۰۰ms کندتر از observed نباشد. «observed» = `(now - revealed_at) − target_ms` است؛ یعنی **زمانی که کلاینت تصمیم می‌گیرد submit کند**. یک اسکریپت، `target_ms` را از پاسخ `/api/round/target` می‌خواند، دقیقاً `target_ms + 110ms` صبر می‌کند و `110` را submit می‌کند. نتیجه: `observed ≈ 110` و ادعا ۱۱۰ → **پذیرفته**.

**اثبات (اجرا شد):**
```
accepted: True | reason:
observed_ms: 110.00000003073364 | claimed: 110.0
=> a bot that waits targetMs+110 and claims 110 is a VALID 110ms round
```
در همین اجرا، اسکریپت **هیچ‌گاه هدفی ندید** — فقط از API خواند و خوابید.

**اثر اقتصادی:** انسان میانه ~۲۵۰ms است. بات ۱۱۰ms. در Bo3، بات تقریباً همیشه ۲–۰ می‌برد. با stake=10: سود خالص هر مسابقه ≈ `0.98×20 − 10 = 9.6 USDT` (کارمزد ۲٪ از pool). ۱۰۰ مسابقه ≈ **+۹۶۰ USDT**، بدون KYC (فقط self-attestation)، با کیف پول‌های رایگان. این یک **بازار آربیتراژ یک‌طرفه** است تا وقتی موجودی قربانی‌ها تمام شود.

**چرا commit/reveal کمک نمی‌کند:** تعهد به یک `intent_hash` است که هیچ اطلاعاتی درباره‌ی واکنش ندارد؛ هدف توسط سرور بعد از commit تولید می‌شود، اما بات به آن دسترسی دارد. `result_proof` فقط از ارسال توسط **دیگران** جلوگیری می‌کند، نه از خودکارسازی توسط **صاحب حساب**.

**اصلاح (به‌ترتیب اثر):**
1. **KYC در لحظه‌ی برداشت + تأخیر پرداخت** (مثلاً ۲۴–۷۲ ساعت) — گران‌ترین کار برای بات، ارزان‌ترین برای شما.
2. **سقف stake روزانه/کل** و velocity واقعی روی «بردهای متوالی با زمان زیر آستانه».
3. **تشخیص آماری سمت سرور**: توزیع واکنش هر حساب؛ بات‌ها واریانس نزدیک صفر و میانگین ~۱۰۵–۱۳۰ دارند. با ۲۰ راند می‌شود با دقت بالا تشخیص داد. (این تنها دفاع فنی واقعی است.)
4. **حذف ادعای «بیومتریک»** از UI تا زمانی که واقعاً چیزی جمع می‌شود.
5. اگر می‌خواهید «اثبات انسانیت» واقعی باشد: WebAuthn/passkey + attestation دستگاه + محدودیت یک دستگاه/حساب. (هزینه‌بر، و باز هم صددرصد نیست.)

**نکته‌ی انصاف:** هیچ بازی واکنشیِ سمت‌سرور در برابر بات مصون نیست. مسئله این است که پروژه **ادعا می‌کند** مصون است و **مدل اقتصادی‌اش** (stake واقعی، برد ۹۸٪) این حمله را پرسود می‌کند.

---

### C-03 · هیچ keeper/relayer وجود ندارد: جایزه می‌تواند بسوزد و پول می‌تواند قفل بماند
**محل:** `contracts/PulsarEscrow.sol:375–450` (`settleDuel`) و `:452–479` (`refundTimeoutMatch`) · `src/pages/ReactionGamePage.tsx` (تنها فراخوان‌های `settleDuelOnChain`/`refundTimeoutMatch`)

**مشاهده:** تسویه **permissionless** است (هر کسی با امضا می‌تواند `settleDuel` را بفرستد)، اما هیچ سرویسی این کار را نمی‌کند. مسیر تنها: کلاینت برنده، در همان نشست، با گس خودش. امضا فقط ۱۰ دقیقه اعتبار دارد و حداکثر تا `activation+30min` تمدید می‌شود (`oracle.py:29–41`). بازپرداخت هم فقط با `refundTimeoutMatch` پس از `30+10` دقیقه و **با گس کاربر** ممکن است.

**اثر:**
- برنده‌ای که تب را می‌بندد/گس ندارد/شبکه‌اش قطع است، **جایزه را از دست می‌دهد** و فقط stake برمی‌گردد؛ لجر اما «win + prize» ثبت کرده — یعنی آمار دروغ می‌شود.
- بازنده/برنده‌ای که برنمی‌گردد، پول را تا ابد در escrow نگه می‌دارد (هیچ sweep سراسری نیست).
- روی Polygon، کاربر بدون MATIC نمی‌تواند حتی refund کند. برای بسیاری از بازیکنان، این «پول گم‌شده» است.

**اصلاح:** یک keeper سمت اپراتور (cron/worker) که (۱) امضاهای معتبر ذخیره‌شده را قبل از deadline روی زنجیره submit کند (گس را اپراتور بدهد؛ غیرامانی است چون جایزه به برنده می‌رود)، و (۲) پس از `timeout+grace` برای matchهای رهاشده refund بزند. این یک سرویس کوچک است (۲–۳ نفر-هفته) با اثر بسیار بزرگ بر اعتماد.

---

### C-04 · ثبت نام کاربری (username claim) در production **همیشه** شکست می‌خورد — با پیام گمراه‌کننده‌ی «نام تکراری»
**محل:** `api/main.py` (`username_claim`)، نسخه‌ی pin‌شده `api/requirements.txt:6` (`google-cloud-firestore==2.20.0`)

**مشاهده:** تابع داخل تراکنش `from google.cloud.firestore_v1.base_transaction import transactional` می‌کند. در نسخه‌ی ۲.۲۰.۰ این نام در `base_transaction` **وجود ندارد** (در `firestore_v1.transaction` است). `ImportError` داخل یک `try` بزرگ رخ می‌دهد و در `except Exception` به `HTTPException(409, "Username claim failed: …")` تبدیل می‌شود. نتیجه: هر درخواست ثبت نام — برای هر بازیکن، هر نام، هر بار — با ۴۰۹ برمی‌گردد و در UI به‌صورت «این نام قبلاً گرفته شده» دیده می‌شود.

**اثر:** ثبت نام کاربری به‌کل غیرقابل استفاده است؛ بازیکن نام دیگری را امتحان می‌کند و باز ۴۰۹ می‌گیرد؛ تیم پشتیبانی دنبال «نام تکراری» می‌گردد در حالی که باگ در import است. هیچ تستی این مسیر را نمی‌پوشاند: تست موجود فقط با emulator اجرا می‌شود (skip در CI پیش‌فرض).

**اصلاح (انجام شد):** import از ماژول درست + fallback؛ هر خطای سرور ۵۰۳ می‌شود نه ۴۰۹؛ سه تست با Firestore جعلی که هر نوشتن خارج از تراکنش را رد می‌کند (`fe8916e`).

**درس (چرا پیدا نشد):** `except Exception` که خطای برنامه‌نویسی را به کد وضعیت «قابل‌انتظار» تبدیل می‌کند، باگ را از «۵۰۰ با traceback» به «۴۰۹ بی‌معنی» تغییر می‌دهد — دومی هیچ‌وقت alert نمی‌دهد.

---

## ۵. یافته‌ها — بالا

### H-01 · «خودحذفی» را می‌توان زودهنگام کوتاه کرد (نقض صریح وعده‌ی UI)
**محل:** `api/limits.py:139–148` · `api/main.py:1285–1293`
`self_exclude` مقدار `excludedUntil` را **بازنویسی** می‌کند (`data["excludedUntil"] = now + seconds`) و هیچ بررسی‌ای برای «فقط طولانی‌تر» ندارد. بازیکنی که ۳۶۵ روز خودحذفی کرده، با یک درخواست `{"seconds":86400}` آن را به ۲۴ ساعت کاهش می‌دهد. در حالی که docstring و پاسخ endpoint می‌گویند «قابل لغو زودهنگام نیست». **اثر:** کنترل مسئولیت‌پذیری در حساس‌ترین لحظه (وقتی بازیکن می‌خواهد ادامه دهد) بی‌اثر می‌شود؛ ریسک انطباقی مستقیم.
**اصلاح:** `newUntil = max(existingUntil, now+seconds)`؛ تست: self-exclude ۳۰ روز سپس ۱ روز ⇒ همچنان ۳۰ روز.

### H-02 · کنترل‌های مسئولیت‌پذیری در قطعیِ Firestore **باز** می‌شوند
**محل:** `api/limits.py:69–90`
`_load` در خطای Firestore به `_memory` سقوط می‌کند؛ برای کاربری که در این پروسه سند ندارد، نتیجه `{}` است ⇒ «unlimited». یعنی در یک قطعی موقت Firestore، **self-exclusion و deposit limit بی‌صدا برداشته می‌شوند** و بازیکن می‌تواند stake کند. (`eligibility` برعکس، fail-closed است — ناسازگاری عمدی/غیرعمدی.)
**اثر:** نقض انطباق + risk مالی/حقوقی. **اصلاح:** در حالت prod-like، خطای خواندن = رد درخواست (503)؛ هرگز به «unlimited» برنگرد. کش محلی با TTL کوتاه فقط برای کارایی، نه به‌عنوان منبع حقیقت.

### H-03 · سقف پینگ هم اختیاری است هم اشتباه اندازه‌گیری می‌شود
**محل:** `api/main.py:1120` (`rttMs: float | None = None`) · `src/lib/gameServerClient.ts:458–472` · `api/main.py:1009–1014` (health → RPC)
- **اختیاری:** کلاینت می‌تواند `rttMs` را حذف کند (یا `undefined` برگرداند وقتی health خطا می‌دهد) ⇒ `check_ping_cap` هیچ‌گاه اجرا نمی‌شود. «لیار درباره‌ی پینگ پایین هیچ سودی ندارد» درست است، اما **حذف کامل فیلد سود دارد**: بازیکن پرت می‌تواند وارد شود و بازی را خراب کند؛ و بات‌ها همیشه حذفش می‌کنند.
- **اشتباه:** RTT با `GET /api/health` اندازه‌گیری می‌شود؛ این endpoint در `main.py:985+` مقدار `rpc.reachable`, `chainId`, `tokenDecimals` را برمی‌گرداند که می‌تواند RPC زنجیره بزند. پس «پینگ بازیکن» شامل I/O بلاکچین است. روی کولد کش، یک بازیکن با اتصال عالی می‌تواند >۴۰۰ms ببیند و **رد شود**.
**اصلاح:** یک endpoint سبک `/api/ping` (بدون I/O، فقط `{"t":...}`)؛ سقف را از روی نمونه‌های متعدد سرورسمت (زمان بین commit و result منهای محاسبه) بسنجید، نه از ادعای کلاینت.

### H-04 · ردیف «LIVE ARENA» هرگز چیزی نشان نمی‌دهد
**محل:** `src/lib/realWeb3.ts:1499–1525` · `api/economy.py` (فیلدهای `doc`: `stake`, `players`, `winner`, `prize`, `status`, `timestamp`, …) · `src/pages/LobbyPage.tsx:523–534`
کلاینت `d.entryFee` را می‌خواند و `if (fee > 0)` فیلتر می‌کند؛ سرور هرگز `entryFee` نمی‌نویسد (grep در `api/*.py`: صفر مورد). نتیجه: `matchesToDisplay` همیشه خالی ⇒ «No live duels». حتی اگر فیلد وجود داشت، مدل داده اشتباه است: سرور یک سند **per-match** با دو بازیکن می‌نویسد، کلاینت انتظار سند **per-player** با `result/yourTime/opponentTime` دارد و `result` را پیش‌فرض `'win'` می‌گذارد.
**اثر:** اصلی‌ترین اثبات اجتماعی محصول (فید زنده) مرده است؛ و اگر روزی روشن شود، همه را «برنده» نشان می‌دهد.
**اصلاح:** endpoint سرور `GET /api/matches/recent?limit=15` با شکل صریح per-player (یا حداقل `stake` به‌جای `entryFee` و حذف پیش‌فرض `'win'`).

### H-05 · پروفایل و لیست دوستان هرگز ذخیره نمی‌شوند؛ و با اولین تسویه پاک می‌شوند
**محل:** `src/lib/realWeb3.ts:1470–1494` (`setDoc(users/{addr}, {playerId, savedFriends, updatedAt})`) · `firestore.rules:41–46` (`allow create: if false; allow update: if false`)
نوشتن کلاینت **همیشه** `permission-denied` می‌شود و در `catch` فقط `console.warn` است. بدتر: `loadUserDataAsync` اگر سند سروری `users/{addr}` وجود داشته باشد (بعد از اولین تسویه، لجر می‌نویسد)، آن را `saveToLocal` می‌کند و برمی‌گرداند — سندی که `savedFriends` ندارد. پس **لیست دوستان محلی با اولین بارگذاری پس از یک مسابقه پاک می‌شود**.
**اثر:** داده‌ی کاربر از دست می‌رود؛ feature «دوستان» در عمل وجود ندارد؛ تگ بازیکن فقط در همان مرورگر می‌ماند.
**اصلاح:** endpoint سرور برای `playerId`/`savedFriends` (با احراز هویت)، یا اصلاح rules با ownership اثبات‌شده؛ و merge کردن سند ابری با داده‌ی محلی به‌جای جایگزینی.

### H-06 · production می‌تواند بی‌صدا غیرپایدار اجرا شود
**محل:** `api/store.py:965–978` · `api/main.py:577–590`
`PULSAR_MATCH_STORE=auto` + نبود اعتبارنامه ⇒ سقوط به memory با یک پیام stderr. `REQUIRED_PRODUCTION_ENV` شامل `PULSAR_MATCH_STORE`/`FIRESTORE_PROJECT_ID` نیست. در یک deployment چندreplica، هر replica صف/مسابقه‌ی خودش را دارد: بازیکن A روی replica 1 صف می‌رود، poll بعدی روی replica 2 ⇒ «match not found»؛ پول در escrow، مسابقه گم‌شده.
**اصلاح:** در prod-like، اگر `store.durable` نیست ⇒ `RuntimeError` در boot (fail-closed)؛ و `PULSAR_MATCH_STORE=firestore` را اجباری کنید.

### H-07 · اوراکل یک کلید داغ در env است؛ کنترل نتیجه کاملاً متمرکز است
**محل:** `api/oracle.py:43,71–84` · `docs/DEPLOYMENT.md:65–66`
کلید خصوصی در `ORACLE_PRIVATE_KEY`، بدون KMS/HSM، بدون multi-sig/committee، بدون rate-anomaly. هر کسی که سرور را compromise کند می‌تواند برای هر مسابقه‌ی فعال، هر یک از دو بازیکن را برنده کند. (قرارداد نمی‌گذارد پول به غیرِ بازیکن برود، اما می‌گذارد بین دو بازیکن انتخاب شود — و با سیبیل، قربانی را با هم‌دست خودش جفت می‌کند.)
**اثر:** ریسک سرقت در مقیاس «همه‌ی مسابقات فعال». **اصلاح:** KMS/HSM، چرخش کلید، تأیید چندنفره برای مبالغ بالا، تأخیر پرداخت، گزارش شفافیت، و در نهایت fraud proof یا کمیته.

### H-08 · «بیومتریک» و «۱۰۰٪ Anti-Bot» ادعاهای نادرست در UI هستند
**محل:** `src/i18n/translations.ts:460,885` (`Zero-Bot Handshake` / `احراز بیومتریک ضد ربات`) · `:474–476` (`Input Physics Analysis`, `Validating human kinematic curve…`) · `src/pages/ReactionGamePage.tsx:1755`
هیچ داده‌ی بیومتریکی (اثر انگشت، چهره، ضربان، ژیروسکوپ) جمع یا ارسال نمی‌شود. «Biometric Analysis» فقط یک انیمیشن پیشرفت است. برای محصولی که پول واقعی می‌گیرد، این می‌تواند تبلیغ گمراه‌کننده تلقی شود.
**اصلاح:** تغییر کپی به «بررسی واکنش» و حذف واژه‌ی بیومتریک؛ یا پیاده‌سازی واقعی WebAuthn و اثبات دستگاه.

### H-09 · `revoke_session` خطا را می‌بلعد ⇒ logout می‌تواند بی‌صدا شکست بخورد
**محل:** `api/auth.py:320–350`
اگر نوشتن در Firestore شکست بخورد، توکن تا انقضای ۲ ساعته معتبر می‌ماند. برای «توکن دزدیده‌شده» این خطای امنیتی است. **اصلاح:** خطا را به caller برگردانید؛ در عدم دسترسی، کش محلی revocation را fail-closed اعمال کنید.

### H-10 · گزارش تخلف (dispute) فقط در حافظه است
**محل:** `api/store.py:1009–1016` · `api/main.py:913–944`
با ری‌استارت یا در replica دیگر گم می‌شود. **اثر:** در یک اختلاف پولی، شواهد کاربر وجود ندارد. **اصلاح:** collection `pulsar_disputes` با TTL/بازبینی اپراتور + هشدار.

### H-11 · صف matchmaking روی یک سند داغ و با scan کامل
**محل:** `api/store.py:417–470` (memory) و معادل Firestore
هر stake یک bucket/سند؛ `enqueue` تراکنشی همه‌ی waiting‌ها را می‌خواند و `choose_opponent` را صدا می‌زند. با ۱۰۰۰ poller، هر poll یک تراکنش روی همان سند ⇒ contention و 503 (LOAD-REPORT خودش ۱۰۰٪ شکست `/api/queue` روی emulator را نشان می‌دهد). **اصلاح:** صف per-player (doc per queued address) + ایندکس، یا صف خارجی (Redis Streams)؛ حداقل bucket‌بندی بر اساس rating/stake و shard.

### H-12 · sweep بازنشانی امضاها محدود و بدون cursor است
**محل:** `api/main.py:1712–1760` (`_resign_stale_settlements`) · `api/store.py` (sweep)
`status=='settled'` + `order_by(settled_at)` + `limit(100)` بدون صفحه‌بندی؛ ۱۰۰ مسابقه‌ی un-resignable می‌تواند پنجره را برای همیشه ببندد. **اصلاح:** cursor + معیار «deadline منقضی» + ایندکس ترکیبی (که وجود دارد) + متریک backlog.

### H-13 · پروب A6 هرمتیک نیست (خطای کاذب در محیط واقعی)
**محل:** `scripts/probe_a6.py:8,13` (`os.environ.setdefault`) در برابر `:47` (secret هاردکد)
اگر `ORACLE_SIGNING_SECRET` از قبل در محیط export شده باشد، `setdefault` آن را عوض نمی‌کند و مقایسه با `"probe-a6-secret"` شکست می‌خورد — دقیقاً همان چیزی که در اجرای اول دیدم (`FAIL C4`) و در محیط تمیز PASS شد. **اثر:** یک گیت می‌تواند بی‌دلیل قرمز/سبز شود؛ در CI با env تنظیم‌شده، همیشه قرمز است. **اصلاح:** مقادیر را صریحاً `os.environ[...] = "..."` کنید یا قبل از import پاک کنید.

### H-14 · لجر خطاها را می‌بلعد؛ آمار می‌تواند از زنجیره واگرا شود
**محل:** `api/economy.py:400–431` (بلعیدن در 427)
settle روی زنجیره موفق است، اما XP/برد/لیدربورد ثبت نمی‌شود. تنها سیگنال `failures` در `/api/health` است. **اصلاح:** صف بازپخش (outbox) + هشدار خودکار + ابزار reconcile با رویدادهای `MatchSettled`.

### H-15 · میانگین زمان واکنش اشتباه وزن‌دهی می‌شود
**محل:** `api/economy.py:433–480` (فرمول در 473)
```
avg = (avg_before * matches_before + sample) / (matches_before + 1)
```
`totalMatches` برای مسابقه‌های forfeit/void هم یک واحد بالا می‌رود، اما `sample` وقتی `real_times` خالی است اضافه نمی‌شود؛ پس دفعه‌ی بعد مخرج بزرگ‌تر از تعداد نمونه‌هاست و میانگین به سمت صفر کشیده می‌شود. **اصلاح:** شمارنده‌ی جدا `reactionSamples` یا محاسبه از مجموع/تعداد.

### H-16 · هیچ هدر امنیتی/CSP وجود ندارد
**محل:** `index.html` (بدون `Content-Security-Policy`) · `api/main.py` (بدون middleware امنیتی)
برای اپی که توکن نشست در `localStorage` دارد و پول جابه‌جا می‌کند، نبود CSP یعنی هر XSS (کتابخانه‌ی ترجمه، widget، dependency) به دزدی نشست منجر می‌شود. **اصلاح:** CSP سخت (nonce-based)، `X-Frame-Options: DENY`، `Referrer-Policy: no-referrer`، `Permissions-Policy`، HSTS.


### H-17 · پس از اولین تسویه، `recordMatch` می‌شکند و خلاصه‌ی XP هرگز نمایش داده نمی‌شود
**محل:** `src/store/usePulsarStore.ts:245,266` · `src/lib/realWeb3.ts:1353–1372` · `api/economy.py:380–425`

`loadUserDataAsync` اگر سند `users/{addr}` را در Firestore ببیند، آن را **بدون هیچ default** cast و return می‌کند. این سند را لجر می‌نویسد و فیلد `history` ندارد. بلافاصله در `recordMatch`:

```ts
const updatedHistory = [match, ...data.history].slice(0, 50);   // data.history === undefined
```

⇒ `TypeError: data.history is not iterable`. در مسیر رنکد، `recordMatch(...).then(...)` **بدون `.catch`** است (`ReactionGamePage.tsx:1332–1341`) ⇒ rejection بی‌صدا، `xpSummary` هرگز set نمی‌شود.

**اثر:** از همان اولین مسابقه‌ی رنکد در production (چون `settle_match` قبل از `recordMatch` سند لجر را می‌سازد)، صفحه‌ی نتیجه XP نشان نمی‌دهد و تاریخچه/آمار محلی ثبت نمی‌شود. این با H-05 یک ریشه دارد: **پروفایل محلی و سند لجر در یک collection و یک شیء قاطی شده‌اند**.

**اصلاح:** نرمال‌سازی در مرز I/O (`history: cloudData.history ?? []`, `savedFriends: cloudData.savedFriends ?? []`) + جدا کردن collection لجر از پروفایل + `.catch` روی `recordMatch` با بازخورد قابل‌بازیابی + تست واحد با سند ناقص.

---

## ۶. یافته‌ها — متوسط (فشرده)

| # | یافته | محل | اثر | اصلاح |
|---|---|---|---|---|
| M-01 | `limits.state()` روی GET می‌نویسد (ماتریال‌شدن pending) | `limits.py:93–115` | یک read، side-effect پایدار؛ در دو replica مسابقه‌ی نوشتن | محاسبه‌ی effective بدون persist؛ persist فقط در write endpoint |
| M-02 | «deposit limit» در واقع «سقف هر stake» است، نه سقف تجمعی واریز | `limits.py:161–180` | کنترل مسئولیت‌پذیری گمراه‌کننده | تغییر نام به `maxStakePerDuel` یا پیاده‌سازی سقف تجمعی روزانه |
| M-03 | `abuse`/`limits` fallback حافظه، در قطعی، پنجره‌ها را per-process می‌کند | `abuse.py:80–90` | ban/velocity در قطعی ضعیف می‌شود | fail-closed برای ban، کش کوتاه با TTL |
| M-04 | فید/لیدربورد کلاینت مستقیماً Firestore می‌خواند | `realWeb3.ts:1499,1538` | وابستگی به rules + هزینه‌ی read کلاینت + نبود نسخه‌بندی API | endpoint سرور با کش |
| M-05 | `getRandomOpponent()` در حالت رنکد پیش از جفت‌شدن نام حریف می‌سازد | `ReactionGamePage.tsx:49` | نمایش «حریف» تخیلی در UI پولی | نام حریف تا جفت‌شدن خالی/«در حال جست‌وجو» |
| M-06 | `waitForOpponentDisclosure` موازی ۱۲۰s ممکن است پیام اشتباه بدهد | `ReactionGamePage.tsx:760–830` | کاربر فکر می‌کند مسابقه لغو شد، در حالی که سرور settle می‌کند | وضعیت را از `getMatch` بگیر، نه تایمر محلی |
| M-07 | رویداد `touchend`+`click` با `verifyingRef` مهار شده، اما سایر double-tapها (approve/create) فقط با refهای محلی‌اند | `ReactionGamePage.tsx:190` | ریسک دوبار approve در دستگاه کند | idempotency key سمت سرور + قفل per-action |
| M-08 | `PULSAR_ENV` تنها معیار prod-like است؛ یک deployment واقعی که آن را ست نکند محافظت نمی‌شود | `main.py:593–597` | پیش‌فرض «insecure» روی محیط ناشناخته | تشخیص خودکار (K_SERVICE / NODE_ENV) + fail-closed |
| M-09 | `X-Forwarded-For` وقتی socket خصوصی است به‌طور خودکار trusted است | `main.py:143–149` | اگر LB هدر را overwrite نکند، محدودیت per-IP با جعل XFF دور می‌خورد | فقط با `TRUST_PROXY_HEADERS=1` و مستندسازی سخت |
| M-10 | admin با یک secret مشترک در هدر، بدون IP allowlist/audit log/2FA | `main.py:778–784` | نشت یک env = کنترل کامل اپراتور | mTLS/2FA + allowlist + لاگ تصمیمات ادمین |
| M-11 | قرارداد قابل ارتقا نیست و مسیر مهاجرت ندارد | `PulsarEscrow.sol` | هر باگ = استقرار قرارداد جدید + پول قفل‌شده در قدیمی | الگوی proxy یا قرارداد «versioned + migration window» |
| M-12 | `PLATFORM_FEE_BPS` ثابت است و treasury هم ثابت | `PulsarEscrow.sol:165` | تغییر مدل کسب‌وکار بدون redeploy ممکن نیست | پذیرفتنی؛ اما در سند محصول صریح شود |
| M-13 | هیچ رویداد/لاگ ساخت‌یافته‌ای برای تصمیم‌های پولی وجود ندارد (فقط print) | `main.py` متعدد | forensic در اختلاف/نفوذ سخت است | structured logging + correlation id + immutable audit trail |
| M-14 | `economy.player_stats` در نبود ردیف `None` برمی‌گرداند (خوب) اما کلاینت به آمار محلی fallback می‌کند | `usePulsarStore.ts:301–321` | می‌تواند محلی و سروری را قاطی کند | نمایش «نامشخص» به‌جای عدد محلی وقتی ranked است |
| M-15 | تست‌های Firestore/chain در نبود emulator/anvil skip می‌شوند و coverage gate به آن‌ها وابسته است | `.coveragerc` + `verify.sh:121–129` | گیت «سبز» بسته به محیط؛ عدد coverage نوسانی | coverage با `--fail-under` روی source مشخص و بدون وابستگی به external؛ یا split gate |
| M-16 | `verify.sh` هدرش با CI در تناقض است | `verify.sh:18–25` vs `ci.yml:231` | اپراتور نمی‌داند چه چیزی واقعاً اجرا می‌شود | یک منبع حقیقت (CI) و حذف ادعای متناقض |
| M-17 | README اعداد تست/coverage را دستی نگه می‌دارد | `README.md:38–44` | کهنه می‌شود (همین حالا کهنه است) | تولید جدول از خروجی CI |
| M-18 | `service worker` با `skipWaiting` + کش نسخه‌دار نشده | `public/sw.js:23–30` | پس از deploy، HTML جدید با چانک قدیمی = صفحه‌ی سفید | versioned cache + prompt-to-update |
| M-19 | `users` برای همه قابل خواندن است (شامل شمارنده‌های اقتصادی) | `firestore.rules:24` | افشای پروفایل wallet-linked؛ ریسک GDPR | فقط فیلدهای لیدربورد در یک collection عمومی جدا |
| M-20 | PWA/OG متادیتا ثابت و بدون تصویر واقعی | `index.html` | اشتراک‌گذاری ضعیف | متادیتای پویا و تصویر واقعی |
| M-21 | هیچ ابزار «حذف حساب/داده» وجود ندارد | جست‌وجو: صفر | نقض حق حذف در GDPR/CCPA | endpoint حذف/بی‌نام‌سازی + سیاست نگهداری |
| M-22 | هیچ `LICENSE`/`SECURITY.md`/`CONTRIBUTING` نیست | ریشه‌ی مخزن | محصول قابل عرضه/همکاری نیست | مجوز صریح + سیاست افشای آسیب‌پذیری |
| M-23 | تست‌های قرارداد هرگز در این محیط اجرا نشدند؛ عدد ۸۱ = ۸۰ تابع | `contracts/test/*` | ادعای «۷۹ تست سبز» تأییدنشده | اجرای forge در CI + گزارش خروجی در README |
| M-24 | `error`های Firestore در `syncToFirestore`/`loadUserData` فقط warn هستند | `realWeb3.ts:1373,1492` | شکست بی‌صدا در مسیر داده‌ی کاربر | شمارنده + UI «ذخیره نشد» |

---

## ۷. یافته‌ها — پایین

| # | یافته | محل |
|---|---|---|
| L-01 | `console.warn` در مسیرهای حساس (بدون telemetry) | `realWeb3.ts` |
| L-02 | نام `savedFriends` بدون هیچ API سروری | `realWeb3.ts:1486` |
| L-03 | کپی «Biometric» در ۵ زبان تکرار شده | `translations.ts` |
| L-04 | `README` می‌گوید Playwright همیشه SKIP؛ دیگر درست نیست | `README.md:27` |
| L-05 | `HOW-IT-WORKS` به «۵۳ یافته» ارجاع می‌دهد بدون لینک به شواهد | `docs/HOW-IT-WORKS.md` |
| L-06 | `docs/LOAD-REPORT.md` بار را روی ۵۰ کاربر و emulator اندازه گرفته، نه ۱۰۰۰ و production | `docs/LOAD-REPORT.md` |
| L-07 | `analytics` شمارش درخواست است نه نفر (خودش گفته) | `analytics.py:70–100` |
| L-08 | `metrics` per-process و با سقف ۶۴ route | `metrics.py` |
| L-09 | `dispute` هیچ وضعیت/پاسخ به کاربر ندارد | `main.py:913` |
| L-10 | پیام خطای «Ping too high» با 409 برمی‌گردد (کد وضعیت نامناسب) | `store.py:109` + endpoint |
| L-11 | `ALLOWED_STAKES` بعد از `note_start` بررسی می‌شود (شمارش stake نامعتبر) | `main.py:1395–1397` |
| L-12 | `getRandomOpponent` و `Math.random` در UI تمرینی (خودافشا) | `antiCheat.ts` |
| L-13 | اعداد/زمان‌های ثابت در کپی (مثلاً «+۵۰ XP») اصلاح شده اما الگو باقی است | `LobbyPage.tsx:54–57` |
| L-14 | `index.html` بدون `<html lang>` داینامیک در SSR (CSR است، مشکلی نیست) | `index.html` |

---

## ۸. تحلیل لایه‌به‌لایه: چه چیزی درست است

انصاف حکم می‌کند خوبی‌ها هم ثبت شوند؛ وگرنه گزارش برای تصمیم‌گیری بی‌فایده است.

### ۸.۱ قرارداد (بهترین لایه)
- اندازه‌گیری `balanceOf` قبل/بعد از `transferFrom` ⇒ پشتیبانی از USDT با کارمزد/ریباس.
- `usedSignatures` پیش از `ecrecover` ⇒ جلوگیری از malleability/replay.
- digest با `chainid` + `address(this)` ⇒ امضا بین شبکه/قراردادها قابل استفاده نیست (تست‌شده در `probe`ها؟ حداقل کد چنین است).
- `_pay` با `pendingWithdrawals` ⇒ توکن بلاک‌شده باعث قفل کل مسابقه نمی‌شود.
- `refundTimeoutMatch` permissionless + `REFUND_GRACE` ⇒ برنده‌ی قربانی‌شده در پنجره‌ی امن settle می‌کند.
- دو مرحله‌ای بودن ownership و timelock.

### ۸.۲ موتور مسابقه
- سقف/کف زمان، `CLOCK_TOLERANCE`، `ROUND_EXPIRY`، `COMMIT_WINDOW`، `MATCH_EXPIRY`، `SETTLE_GRACE` — همه در یک جدول و importشده در `oracle.py`.
- `observed_ms` سرورمحور؛ حذف جبران RTT کلاینت (اصلاح درست).
- H24: absent player forfeits the match — **منطق درست است** و من با اجرا تأیید کردم که ۱-۰ به نفع حاضر می‌شود، نه void.
- ۱-۱ با راند سومِ unplayed ⇒ void (هر دو refund). این ریسک «توقف دوطرفه» است؛ اگر فقط یک نفر توقف کند، به او باخت می‌خورد. **اثبات:** در کد `vb is None ⇒ wins_a += 1`؛ پس stalling یک‌طرفه خودکشی است.
- `result_proof` با `commit_salt` سرور ⇒ commit قابل تعویض بعد از دیدن target نیست.

### ۸.۳ احراز هویت
- nonce دارای MAC، پنجره‌ی زمانی + grace مرزی، burn دائمی با `create` اتمیک، revocation با `jti`، TTL دو ساعته.
- `_auth_staked` هم eligibility و هم limits را اعمال می‌کند.

### ۸.۴ اقتصاد
- یک تراکنش برای gate + match + دو کاربر + leaderboard؛ idempotency از **واقعیت‌ها** (`settlementId`) نه از یک UUID تصادفی؛ تضاد claim.
- `xp.py` با `_js_round` و parity test با کلاینت (این جزئیات، نشانه‌ی بلوغ است).

### ۸.۵ تست و ابزار
- ۲۹۴ تست پایتون در ۷.۵ ثانیه، ۲۱۶ تست vitest، ruff/mypy تمیز، `probe_a5/a8` سبز، `test_http_e2e` شامل rollback/retry/429.
- `compile_check.js` واقعاً solc 0.8.20 را روی paris و shanghai اجرا می‌کند.
- `verify.sh` گیت‌های واقعی دارد (نه تشریفاتی): min-20 Playwright، coverage ratchet، solc، forge، anvil.
- هیچ `dangerouslySetInnerHTML`/`innerHTML`/`eval(` در `src/` نیست (grep) — سطح XSS کلاینت باریک است؛ اما نبود CSP (H-16) یعنی یک dependency آلوده همچنان می‌تواند توکن `localStorage` را بدزدد.

---

## ۹. گپ‌های «اصلاً وجود ندارد» (برای محصول جهانی)

اینها باگ نیستند؛ **قطعات غایب** هستند. هر یک می‌تواند به‌تنهایی عرضه را متوقف کند.

### انطباق و حقوقی
1. **KYC/AML** — هیچ‌جا نیست. فقط self-attestation. برای پول واقعی، در بیشتر حوزه‌ی قضایی‌ها الزامی است.
2. **ژئوبلاک و بررسی منطقه** — هیچ lookup جغرافیایی، هیچ deny list. (README خودش می‌گوید.)
3. **اثبات سن** — فقط تیک. برای «کازینوی مهارتی» معمولاً insufficient.
4. **مسئولیت‌پذیری حرفه‌ای** — self-exclusion قابل کوتاه‌شدن (H-01)، بدون ثبت ملی، بدون cool-off خودکار پس از ضرر متوالی.
5. **ToS/Privacy/Risk** فقط انگلیسی و بدون پذیرش نسخه‌دار در ثبت‌نام.
6. **مالیات/گزارش‌دهی** — هیچ ردی از برد/باخت قابل صدور نیست (لجر shadow است).
7. **حذف حساب/داده** — وجود ندارد.
8. **مجوز** — برای بازی مهارتی با جایزه‌ی نقدی، بسته به کشور نیاز به مجوز/ثبت است؛ در برخی کشورها ممنوع مطلق.

### امنیت و عملیات
9. **CSP/هدرهای امنیتی** (H-16).
10. **KMS/HSM برای اوراکل** (H-07).
11. **WAF/DDoS** و rate limit توزیع‌شده‌ی واقعی (فعلاً Firestore-based، با fallback per-process).
12. **مانیتورینگ/هشدار** — metrics per-process، بدون exporter (Prometheus/OTel)، بدون alert (ledger failures، sweep backlog، RPC down).
13. **on-call و runbook drill** — سند وجود دارد، تمرین نشده.
14. **backup/restore drill** — اسکریپت هست، اثبات بازیابی نیست.
15. **staging واقعی** — فقط local stack.
16. **ممیزی قرارداد بیرونی و pen-test API** — صفر.
17. **ثبت رخداد امنیتی/شفافیت** — ندارد.

### محصول
18. **Keeper/relayer** (C-03).
19. **پشتیبانی درون‌محصول و وضعیت dispute**.
20. **اعلان‌ها** (نوبت حریف، نتیجه، جایزه).
21. **تاریخچه‌ی قابل‌اعتماد per-player** (الان فید مرده و لیدربورد فقط از Firestore).
22. **onboarding و آموزش** — «هدف را بزن» ساده است، اما توضیح پول/ریسک/گس نیست.
23. **دسترس‌پذیری کامل** — خودافشا: کنتراست AA رد می‌شود.
24. **اپ موبایل/کیف پول موبایل** — WalletConnect دارد، اما تجربه‌ی موبایل تست نشده.
25. **چند-zبانانه‌ی حقوقی** و RTL کامل (فارسی/عربی) — رشته‌ها ترجمه شده‌اند اما اسناد حقوقی نه.

---

## ۱۰. برآورد کار تا «محصول بی‌نقص و قابل‌عرضه‌ی جهانی»

### ۱۰.۱ تعریف سه سطح

| سطح | معنی | پول واقعی؟ | مخاطب |
|---|---|---|---|
| **A — بتای بسته** | یک حوزه‌ی قضایی، سقف stake کوچک، KYC دستی، keeper ساده | بله، محدود | ۵۰–۵۰۰ کاربر دعوت‌شده |
| **B — production** | چند کشور، KYC خودکار، audit بیرونی، on-call، پشتیبانی | بله | عمومی |
| **C — جهانی** | چند حوزه‌ی قضایی، مجوز، تیم عملیات ۲۴/۷، مدل درآمدی پایدار | بله | بازار جهانی |

### ۱۰.۲ برآورد نفر-روز (تیم ۲–۴ نفره‌ی سنیور)

| Workstream | A | B | C | توضیح |
|---|---:|---:|---:|---|
| رفع باگ‌های بحرانی (C-01…C-03، H-01…H-06) | ۸ | ۱۲ | ۱۵ | کد مشخص است؛ تست رگرسیون هم لازم است |
| ضدتقلب/تشخیص آماری + محدودیت برداشت | ۱۰ | ۲۵ | ۴۵ | مدل، داده، false-positive، بازبینی دستی |
| Keeper/relayer + گس‌لس (paymaster) | ۵ | ۱۲ | ۲۰ | سرویس کوچک اما حیاتی |
| مقیاس‌پذیری (صف، Firestore، load test 1k–10k) | ۵ | ۲۰ | ۴۰ | بازطراحی داده + تست بار واقعی |
| امنیت (CSP، KMS، WAF، 2FA ادمین، audit trail) | ۵ | ۲۰ | ۳۵ | + pen-test بیرونی |
| انطباق (KYC، ژئوبلاک، سن، حذف داده، گزارش مالیاتی) | ۵ | ۳۰ | ۶۰+ | وابسته به وندور و حوزه‌ی قضایی |
| تست/QA (E2E کامل، موبایل، chaos، mutation) | ۵ | ۲۰ | ۳۵ | گیت فعلی خوب است، اما شکاف دارد |
| محصول/UX (onboarding، خطاها، پشتیبانی، اعلان) | ۸ | ۲۵ | ۴۰ | |
| SRE (IaC، staging، observability، DR، on-call) | ۳ | ۲۰ | ۳۵ | |
| i18n/a11y (AA، اسناد حقوقی) | ۳ | ۱۰ | ۱۸ | |
| قرارداد (ممیزی، ارتقا/مهاجرت، multisig) | ۲ | ۱۰ | ۲۰ | + هزینه‌ی audit |
| **جمع مهندسی** | **~۵۹** | **~۲۰۴** | **~۳۶۳** | |

**تبدیل:** A ≈ ۳ نفر-ماه (۶–۸ هفته با تیم ۲–۳ نفره). B ≈ ۱۰–۱۲ نفر-ماه (۶–۸ ماه تقویمی با تیم ۳–۴ نفره). C ≈ ۱۸–۲۲ نفر-ماه مهندسی + تیم عملیات/انطباق جدا.

### ۱۰.۳ هزینه‌های بیرونی (تقریبی، دلار آمریکا)

| قلم | بازه | توضیح |
|---|---:|---|
| ممیزی قرارداد (firm) | ۳۰٬۰۰۰–۸۰٬۰۰۰ | ۳–۶ هفته؛ برای قرارداد ۶۱۳ خطی معمولاً ۲–۴ هفته + remediation |
| Pen-test API/کلاینت | ۱۵٬۰۰۰–۴۰٬۰۰۰ | سالانه |
| مشاوره‌ی حقوقی (ToS/Privacy/Risk + ساختار) | ۳۰٬۰۰۰–۱۰۰٬۰۰۰ | بسته به حوزه‌ی قضایی |
| KYC/AML وندور | ۱–۳ دلار به ازای هر بررسی + قرارداد | حداقل ماهانه |
| مجوز بازی (اگر لازم) | ۵۰٬۰۰۰–۵۰۰٬۰۰۰+ | ۶–۱۸ ماه؛ در برخی کشورها غیرممکن |
| تیم عملیات/پشتیبانی | ۲–۴ نفر | ۲۴/۷ در سطح C |

### ۱۰.۴ مسیر بحرانی (critical path)

```
[هفته ۱–۲]  رفع C-01/C-02/C-03 + H-01/H-02 + تست رگرسیون
[هفته ۳–۴]  keeper + ping endpoint + CSP + KMS + fail-closed store
[هفته ۵–۸]  بازطراحی صف + load test 1k + تشخیص آماری بات
[هفته ۶–۱۰] ممیزی قرارداد (موازی) + pen-test
[هفته ۸–۱۶] KYC/ژئوبلاک/سن/حذف داده + اسناد حقوقی
[هفته ۱۲–۲۰] بتای بسته با سقف stake و KYC دستی
[ماه ۶–۹]   production در یک حوزه‌ی قضایی
[ماه ۱۲–۲۴] گسترش جهانی (اگر مجوز بگیرید)
```

### ۱۰.۵ چه چیزی را پول نمی‌خرد
- **مجوز حوزه‌های قضایی** (زمان تقویمی، نه نفر-روز).
- **اعتماد بازار** پس از یک حادثه‌ی امنیتی؛ یک بار از دست برود، سال‌ها طول می‌کشد.
- **اثبات «مهارت» بودن** در برابر رگولاتور: باید نشان دهید نتیجه به مهارت بازیکن وابسته است، نه شانس. طراحی فعلی (زمان واکنش) از این نظر قابل دفاع است، اما **بات‌ها** این استدلال را ضعیف می‌کنند.
- **رفتار انسانی در برابر اسکریپت** — هیچ راه‌حل کاملی وجود ندارد؛ فقط هزینه‌ی حمله را بالا می‌برید.

### ۱۰.۶ برآورد نهایی در یک جمله

> برای رسیدن به **بتای بسته‌ی پول‌واقعی** حدود **۶۰–۸۰ نفر-روز (۶–۸ هفته)**؛ برای **محصول production در یک حوزه‌ی قضایی** حدود **۲۰۰–۲۵۰ نفر-روز (۶–۸ ماه تقویمی)** به‌همراه **۷۵–۲۰۰ هزار دلار** هزینه‌ی ممیزی/حقوقی؛ و برای **عرضه‌ی جهانی با پول واقعی** **۱۸–۲۴ نفر-ماه مهندسی + ۱–۲ سال مجوز/انطباق** — اگر اصلاً مجاز باشید.
>
> مسیر عاقلانه‌تر: ابتدا **free-to-play با جوایز غیرنقدی** (بدون KYC/مجوز) برای اثبات retention، و سپس پول واقعی با سقف‌های کوچک در یک حوزه‌ی قضایی مشخص.

---

## ۱۱. ۱۴ روز اول — فهرست اقدام مشخص

| روز | کار | معیار پذیرش |
|---|---|---|
| ۱ | `note_start` فقط برای match جدید؛ تست ۴۰ poll | بازیکن ۱۰ دقیقه poll کند و بلاک نشود |
| ۲ | `/api/ping` سبک؛ حذف RPC از مسیر RTT؛ اجباری‌کردن سقف پینگ یا حذف ادعا | health دیگر روی مسیر queue نیست |
| ۳ | فید: `stake` به‌جای `entryFee`؛ حذف `result: 'win'` پیش‌فرض؛ endpoint سرور | فید با ۵ مسابقه‌ی واقعی پر می‌شود |
| ۴ | پروفایل: endpoint سرور یا rules امن؛ merge به‌جای overwrite؛ `history/savedFriends` را در مرز I/O نرمال کن (H-17) | رفرش صفحه دوستان را پاک نمی‌کند و XP نتیجه نمایش داده می‌شود |
| ۵ | H-01 self-exclusion فقط طولانی‌تر؛ H-02 fail-closed | تست: ۳۰ روز → ۱ روز ⇒ ۳۰ روز |
| ۶ | `PULSAR_MATCH_STORE=firestore` اجباری در prod + boot check | بوت بدون Firestore = شکست صریح |
| ۷ | `revoke_session` fail-closed + تست | logout با خطای store، توکن را باطل می‌کند |
| ۸ | Keeper اولیه (settle + refund پس از timeout) | برنده‌ی offline جایزه‌اش را می‌گیرد |
| ۹ | CSP + هدرهای امنیتی + تست | اسکنر، CSP را تأیید می‌کند |
| ۱۰ | حذف کلمه‌ی «بیومتریک»/«۱۰۰٪» از UI | grep صفر |
| ۱۱ | `probe_a6` هرمتیک + اجرای forge در CI | گیت در env تمیز قطعی |
| ۱۲ | coverage: اندازه‌گیری پایدار بدون emulator یا split | گیت بدون emulator هم معنا داشته باشد |
| ۱۳ | dispute پایدار + هشدار | گزارش در replica دیگر دیده می‌شود |
| ۱۴ | بازبینی README/اعداد از CI | هیچ عددی دستی نماند |

---

## ۱۲. پیوست A — دستورها و خروجی‌های خام

```text
$ ORACLE_SIGNING_SECRET=testsecret123 PULSAR_ENV=dev .venv/bin/python -m pytest -q
294 passed, 42 skipped, 1 warning in 7.53s

$ coverage run --source=api -m pytest -q  (+ append: test_game_server, test_http_e2e)
TOTAL  2997  829  72%
Coverage failure: total of 72 is less than fail-under=79

$ ruff check api scripts tests
All checks passed!

$ .venv/bin/python -m mypy
Success: no issues found in 14 source files

$ npx vitest run
Test Files  51 passed (51)
     Tests  216 passed (216)

$ node contracts/test/compile_check.js
COMPILE CHECK PASSED
  solc 0.8.20; PulsarEscrow OK (evm=paris, shanghai); MockUSDT OK; Deploy.s.sol present
  test-file compile SKIPPED (contracts/lib/forge-std absent)

$ scripts/test_game_server.py
ALL SMOKE TESTS PASSED
$ scripts/test_http_e2e.py
ALL HTTP E2E TESTS PASSED

$ scripts/probe_a5.py      → all pass
$ scripts/probe_a8.py      → ALL CHECKS PASSED
$ scripts/probe_a6.py      → (clean env) FAILURES: none
                            (env with ORACLE_SIGNING_SECRET set) FAIL C4 — probe bug
```

**اثبات C-01 (اجرا):**
```
for i in range(19): abuse.note_start(addr)
abuse.require(addr)     → allowed
abuse.note_start(addr)  → 20th
abuse.require(addr)     → BLOCKED: 15-minute cooldown
```

**اثبات C-02 (اجرا):**
```
accepted: True | reason:
observed_ms: 110.00000003073364 | claimed: 110.0
```

---

## ۱۳. پیوست B — فایل‌های کلیدی خوانده‌شده

| فایل | خطوط | وضعیت |
|---|---:|---|
| `contracts/PulsarEscrow.sol` | ۶۱۳ | کامل |
| `api/main.py` | ۲۰۰۳ | کامل (بخش‌به‌بخش) |
| `api/match_engine.py` | ۸۳۱ | کامل (منطق راند/تسویه) |
| `api/store.py` | ۱۳۰۶ | کامل |
| `api/auth.py` | ۵۲۹ | کامل |
| `api/onchain.py` | ۶۳۹ | کامل |
| `api/oracle.py` | ۳۵۲ | کامل |
| `api/economy.py` | ۵۵۶ | کامل |
| `api/eligibility.py` / `limits.py` / `abuse.py` | ۱۰۵ / ۲۰۰ / ۱۷۵ | کامل |
| `api/metrics.py` / `analytics.py` / `xp.py` | — | کامل |
| `src/lib/chain.ts` / `escrowFlow.ts` / `gameServerClient.ts` / `antiCheat.ts` | — | کامل/بحرانی |
| `src/pages/ReactionGamePage.tsx` | ۲۲۷۲ | بخش‌های مسیر پول و راند |
| `src/lib/realWeb3.ts` / `src/store/usePulsarStore.ts` | — | بخش‌های داده/اقتصاد |
| `firestore.rules` / `firestore.indexes.json` / `ci.yml` / `verify.sh` | — | کامل |

---

## ۱۴. پیوست C — یافته‌های پیشین که هنوز باز هستند

از `docs/audit/FULL-AUDIT-2026-10-12.md` و `docs/audits/PHASE-10-AUDIT-RUTHLESS.md`:

- **C1 (limiter مرده)** — در کد فعلی با `@transactional` اصلاح شده (تأیید خوانش)؛ اما fallback در قطعی هنوز per-process است.
- **C2 (کش `token_decimals` منفی)** — با `DepositVerdict.UNKNOWN` مهار شده، مشروط به اینکه همه‌ی callerها آن را رعایت کنند.
- **C3 (کیف پول اشتباه)** — `getActiveEip1193Provider` اضافه شده؛ ظاهراً رفع شده.
- **C4 (double-submit موبایل)** — `verifyingRef` اضافه شده؛ رفع شده (کد را دیدم).
- **H1 (برنده بر اساس latency)** — با `observed_ms` رفع شده.
- **H2 (commit بی‌معنا)** — با `commit_salt` و proof سرور رفع شده.
- **refund test** — هنوز در هیچ گیتی اجرا نمی‌شود مگر با `PULSAR_TEST_TIME_TRAVEL=1`.
- **chaos suite / ranked E2E** — در `verify.sh` نیستند؛ فقط دستی.
- **light/dark theme** — وجود ندارد (در فاز ۱۰ اعتراف شده).

---

## ۱۵. سخن آخر

این پروژه را نمی‌شود با «کد خوبی است» یا «کد بدی است» جمع کرد. این یک **سیستم پول** است که مثل یک پروژه‌ی نمایشی تست شده: ۲۹۴ تست سبز، اما هیچ‌کدام یک بات واقعی را امتحان نکرده‌اند؛ قراردادی که با دقت طراحی شده، اما هیچ‌کس بیرون از تیم آن را ندیده؛ و ادعاهایی که بخشی‌شان (بیومتریک، ۱۰۰٪ ضدبات، «eligibility فقط کلاینت») درست نیستند.

سه کار، به‌ترتیب بازده، از همه مهم‌ترند:

۱. **C-01 را همین امروز درست کنید.** این تنها باگی است که بازیکن عادی را در دقیقه‌ی سوم بیرون می‌اندازد.
۲. **C-02 را به‌عنوان یک تصمیم محصولی بپذیرید، نه یک باگ.** تا وقتی پول واقعی با برد ۹۸٪ و بدون KYC وجود دارد، بات‌ها سود می‌برند. یا KYC/تأخیر/سقف اضافه کنید، یا ادعای ضدبات را بردارید.
۳. **C-03 (keeper) را بسازید.** بدون آن، «برنده شدی» در لجر ثبت می‌شود ولی در کیف پول نه — و این بدترین تجربه‌ای است که یک محصول پولی می‌تواند بسازد.

بقیه، مهندسی است. این سه، **اعتماد** است.

---

*این گزارش با اجرای واقعی تست‌ها و سناریوهای حمله در سندباکس تهیه شده است. جاهایی که زیرساخت (Foundry/Playwright/emulator/anvil) موجود نبود، صریحاً «اجرا نشد» علامت خورده‌اند و به‌عنوان نتیجه گزارش نشده‌اند.*
