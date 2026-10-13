# PULSAR — پلن اجرایی رفع اشکال و تست (از صفر تا انتشار)

**نسخه:** ۱.۰ · **تاریخ:** ۲۰۲۶-۱۰-۱۲ · **مبنا:** `FULL-AUDIT-2026-10-12.md` (۱۰۸ یافته)
**وضعیت:** 🟡 در انتظار تأیید شروع

> این سند **چک‌لیست اجرایی** است. هر آیتم یک ID، یک دلیل، یک فایل، یک تغییر مشخص، یک تست رگرسیون و یک معیار پذیرش دارد.
> هر آیتم وقتی تیک می‌خورد که **تستش سبز شده باشد** — نه وقتی کدش نوشته شده باشد.

---

## ۰. قواعد کار (Working Agreements)

این قواعد بر همه‌ی فازها حاکم‌اند. تخطی از آن‌ها = آیتم رد شده.

| # | قاعده | دلیل |
|---|---|---|
| **R1** | **هیچ fix بدون تست رگرسیون.** تست باید *قبل از* fix قرمز باشد و *بعد از* fix سبز. | وگرنه نمی‌دانیم باگ واقعاً رفع شده یا فقط پنهان شده |
| **R2** | هر فاز = یک برنچ + یک PR. شما review و merge می‌کنید. | مالکیت تصمیم‌های کلیدی مال شماست |
| **R3** | در پایان هر فاز، `bun run verify` باید کامل سبز باشد. | جلوگیری از regression بین فازها |
| **R4** | اگر fix نیاز به تغییر رفتار قابل‌مشاهده دارد → قبل از کد، تصمیم مشترک. | جلوگیری از کار دوباره |
| **R5** | هیچ داده‌ی ساختگی/نمایشی جدید اضافه نمی‌شود. | بدهی اعتمادی |
| **R6** | هر تغییر در قرارداد → تست Foundry + به‌روزرسانی ABI کلاینت + پین‌های parity. | قرارداد/کلاینت/سرور یک پروتکل‌اند |
| **R7** | هر تغییر در پروتکل امضا → تست روی Anvil با قرارداد واقعی. | تست واحد کافی نیست |
| **R8** | کامیت‌ها اتمیک و به‌ازای هر آیتم. پیام کامیت شامل ID آیتم. | ردیابی |

**Definition of Done برای هر آیتم:**
```
[ ] کد تغییر کرد
[ ] تست رگرسیون نوشته شد و قبل از fix قرمز بود (شاهد ثبت شد)
[ ] تست بعد از fix سبز است
[ ] تست‌های موجود همان ماژول همچنان سبزند
[ ] bun run verify سبز است
[ ] اگر رفتار قابل‌مشاهده تغییر کرد → در PR توضیح داده شد
```

---

## ۱. وضعیت زیرساخت (انجام‌شده ✅ / باقی‌مانده ⬜)

| ابزار | وضعیت | یادداشت |
|---|---|---|
| Foundry 1.8.5 (forge/anvil/cast) | ✅ | `/root/workspace/.foundry/bin` |
| Java 21 JRE (Temurin) | ✅ | برای Firestore Emulator |
| Firestore Emulator 1.19.8 | ✅ | `127.0.0.1:8081` — **C1 بازتولید شد** |
| Playwright + Chromium 156 | ✅ | `/root/workspace/.cache/ms-playwright` |
| Python venv + deps | ✅ | `/root/workspace/PUL_SKILL/.venv` |
| node / bun / npm | ✅ | typecheck سبز |
| OpenZeppelin (برای forge) | ✅ | `contracts/lib/openzeppelin-contracts` |
| **محدودیت:** دیسک ۹.۸G | ⚠️ | الان ۷۴٪ — باید دوره‌ای کش پاک شود |

---

## فاز ۰ — دروازه‌ها (Gate 0) 🚪

**هدف:** هیچ تغییری بدون تست و بدون اجرای واقعی CI انجام نشود.
**تخمین:** ۱ روز · **وابستگی:** ندارد (اولین فاز)

### 0.1 — رفع CI قرارداد (نصب OpenZeppelin) `[CI-1]`
- **چرا:** `contracts/test/MockUSDT.sol:4` به OZ ایمپورت می‌کند ولی workflow فقط `forge-std` را نصب می‌کند → `forge test` کامپایل نمی‌شود → **۲۱ تست قرارداد هرگز در CI اجرا نشده‌اند**.
- **فایل:** `.github/workflows/ci.yml`
- **تغییر:** در استپ نصب، `openzeppelin-contracts` هم clone شود (مثل forge-std).
- **تست:** اجرای محلی workflow معادل → `forge test` باید ۲۱/۲۱ PASS بدهد.
- **معیار پذیرش:** CI job قرارداد سبز، و لاگ نشان دهد ۲۱ تست اجرا شد.

### 0.2 — اسکریپت واحد تأیید `bun run verify`
- **چرا:** امروز ۷ دستور پراکنده است و هیچ‌کس همه را اجرا نمی‌کند.
- **فایل جدید:** `scripts/verify.sh` + `package.json`
- **محتوا:** `tsc --noEmit` → `pytest` → `forge test` → `compile_check.js` → `vitest` → `ruff` → `mypy`
- **معیار پذیرش:** یک دستور، همه‌ی گیت‌ها، خروجی صفر.

### 0.3 — ساختار pytest
- **فایل جدید:** `tests/{unit,integration,e2e,adversarial}/`, `tests/conftest.py`, `pytest.ini`
- **تغییر:** ۶ اسکریپت `scripts/test_*.py` و `probe_*.py` به تست‌های pytest تبدیل شوند؛ اسکریپت‌های فعلی wrapper نازک بمانند تا `bun run test:server` نشکند.
- **معیار پذیرش:** `pytest` همه‌ی تست‌های مهاجرت‌کرده را سبز اجرا کند؛ تعداد تست‌ها ≥ تعداد `check()`های فعلی (≥۹۰).

### 0.4 — ابزار توسعه
- **فایل جدید:** `api/requirements-dev.txt`
- **محتوا:** `pytest`, `pytest-cov`, `pytest-asyncio`, `hypothesis`, `time-machine`, `respx`, `ruff`, `mypy`, `httpx`
- **معیار پذیرش:** نصب و اجرا روی venv تمیز.

### 0.5 — تزریق ساعت (Clock injection) ⚠️ پایه‌ای
- **چرا:** موتور در ۱۲ نقطه `time.time()` را مستقیم صدا می‌زند. تست‌های فعلی `revealed_at` را دستکاری می‌کنند — این یک hack است که باگ‌های واقعی زمان‌بندی را پنهان می‌کند.
- **فایل:** `api/match_engine.py`
- **تغییر:** `def now() -> float: return time.time()` و جایگزینی همه‌ی فراخوانی‌ها؛ در تست با `monkeypatch` جایگزین شود.
- **معیار پذیرش:** هیچ `time.time()` مستقیمی در موتور نماند؛ تست‌ها بتوانند زمان را جلو ببرند بدون دست‌کاری state.

### 0.6 — Fixture رسمی FakeRpc
- **چرا:** `urlopen` در ۳ فایل به‌صورت copy-paste mock شده.
- **فایل جدید:** `tests/fixtures/fake_rpc.py`
- **قابلیت:** پاسخ به `eth_chainId`, `eth_call` (matches/decimals/paymentToken), `eth_getTransactionReceipt`؛ قابل‌تنظیم برای timeout/error/payload خراب.
- **معیار پذیرش:** `probe_a5` بازنویسی‌شده روی این fixture کار کند.

### 0.7 — Firestore Emulator در CI و تست‌ها
- **چرا:** `test_firestore_integration.py` بدون credential skip می‌شود → **هر باگ Firestore به production می‌رسد** (C1, H3, H4 همه از این جنس‌اند).
- **فایل جدید:** `scripts/start_emulator.sh`, `tests/conftest.py` (fixture `firestore_emulator`)
- **تغییر:** emulator jar + JRE در CI نصب و با `FIRESTORE_EMULATOR_HOST` اجرا شود.
- **معیار پذیرش:** تست Firestore در CI اجرا شود (نه skip) و C1 را بازتولید کند.

### 0.8 — Anvil + escrow در CI
- **فایل جدید:** `tests/fixtures/chain.py`, `scripts/start_anvil.sh`
- **قابلیت:** anvil را بالا بیاورد، MockUSDT + PulsarEscrow را deploy کند، آدرس‌ها را به تست بدهد.
- **معیار پذیرش:** یک تست نمونه `createDuel` را روی anvil اجرا کند و موجودی را تأیید کند.

### 0.9 — Vitest + React Testing Library
- **فایل جدید:** `vitest.config.ts`, `src/**/*.test.ts(x)`
- **معیار پذیرش:** یک تست نمونه روی `xpSystem.ts` سبز شود.

### 0.10 — Playwright + کیف پول mock
- **فایل جدید:** `e2e/`, `e2e/fixtures/mockWallet.ts`
- **قابلیت:** یک EIP-1193 mock که `eth_requestAccounts`, `personal_sign`, `eth_sendTransaction` را پاسخ دهد + anvil پشت آن.
- **معیار پذیرش:** یک تست نمونه اپ را load کند و دکمه‌ی connect را بزند.

### 0.11 — axe-core
- **فایل جدید:** `e2e/a11y.spec.ts`
- **معیار پذیرش:** axe روی صفحه‌ی اصلی اجرا شود (حتی اگر الان خطا بدهد — خطاها به فاز ۸ منتقل می‌شوند).

### 0.12 — گیت coverage با ratchet
- **فایل:** `pytest.ini`, `vitest.config.ts`, `forge` config
- **تغییر:** `--cov-fail-under` از سطح فعلی شروع شود و در هر فاز بالا برود.
- **معیار پذیرش:** کاهش coverage باعث شکست CI شود.

### 0.13 — CI: اجرای همه‌ی گیت‌ها
- **فایل:** `.github/workflows/ci.yml`
- **معیار پذیرش:** CI همان چیزی را اجرا کند که `bun run verify` اجرا می‌کند.

> ### 🚦 گیت فاز ۰
> `bun run verify` سبز + CI سبز + Firestore emulator و Anvil در CI اجرا می‌شوند + coverage گزارش می‌شود.
> **تا این گیت سبز نشود، فاز ۱ شروع نمی‌شود.**

---

## فاز ۱ — CRITICAL 🔴

**هدف:** بستن ۴ باگی که محصول را می‌شکنند یا پول را از دست می‌دهند.
**تخمین:** ۱ روز · **وابستگی:** فاز ۰

### [ ] C1 — محدودکننده‌ی نرخ توزیع‌شده کاملاً مرده است
- **چرا:** `doc.get(transaction=txn)` روی تراکنش شروع‌نشده `ValueError(INACTIVE_TXN)` می‌دهد؛ `except Exception: pass` آن را می‌بلعد → سقوط به limiter درون‌پروسه‌ای → سقف واقعی `N × limit` روی N replica، صفر شدن با هر restart. تمام کنترل‌های ضد-DoS روی `settle`/`claim`/`auth`/`verify`/`commit` بی‌اثرند.
- **شاهد:** روی Firestore Emulator بازتولید شد → `ValueError: Transaction not in progress, cannot be used in API requests.`
- **فایل:** `api/main.py:134-163`
- **تغییر:**
  1. بدنه با `_firestore.transactional` بپیچیده شود و `txn.commit()` صدا زده شود.
  2. `except` باریک شود: فقط خطای گذرا → fallback؛ خطای برنامه‌نویسی → propagate + log.
  3. شمارنده‌ی `rl_fallback_total` روی `/api/health` منتشر شود.
- **تست (قرمز→سبز):** `tests/integration/test_ratelimit_firestore.py`
  - `test_distributed_window_persists_across_instances`: دو `FirestoreStore` جدا، N فراخوانی → سند `rate_limits` باید افزایش یابد و ۴۲۹ بدهد.
  - `test_limiter_does_not_silently_fall_back`: assert که fallback صفر است.
- **معیار پذیرش:** سند واقعاً در emulator افزایش می‌یابد؛ تست روی `main._rl_window` پاک‌شده هم ۴۲۹ می‌دهد.

### [ ] C2 — `token_decimals()` خطای گذرا را برای همیشه `None` کش می‌کند
- **چرا:** یک blip ۵ ثانیه‌ای روی RPC → `_token_decimals = None` چسبنده → هر دوئل Active در `verify_deposit` رد و در `main.py:213` **void** می‌شود → برنده‌ی قانونی هرگز جایزه نمی‌گیرد تا restart.
- **فایل:** `api/onchain.py:76-102`, `api/main.py:209-222`
- **تغییر:**
  1. کش شکست با TTL (مثل `_chain_ok`): `_token_decimals_until` + `_NEGATIVE_TTL`.
  2. تفکیک «ناخوانا» از «ناهماهنگ»: در حالت ناخوانا `409 refuse-the-round` بده، **void نکن**.
  3. `verify_deposit` سه‌حالته شود: `True / False / None(unknown)`.
- **تست (قرمز→سبز):** `tests/unit/test_onchain_decimals.py`
  - `test_transient_failure_does_not_stick`
  - `test_unreadable_decimals_refuses_round_without_voiding`
  - `test_mismatched_stake_still_voids`
- **معیار پذیرش:** بعد از یک شکست و سپس موفقیت RPC، gate دوباره کار کند؛ ماتچ void نشود.

### [ ] C3 — تراکنش‌های پول با provider اشتباه امضا می‌شوند
- **چرا:** `getActiveEip1193Provider` همیشه `window.ethereum` را برمی‌گرداند، نه provider انتخاب‌شده‌ی EIP-6963 → پول می‌تواند از کیف پول دیگری برود.
- **فایل:** `src/lib/realWeb3.ts:1020-1044`, `:1155-1170`
- **تغییر:** provider فعال (یا `rdns`) در `setConnectedAddress` ذخیره شود؛ `getActiveEip1193Provider` دقیقاً همان را برگرداند؛ در صورت نبود، از `eip6963Manager` با rdns دوباره resolve کند.
- **تست (قرمز→سبز):** `src/lib/realWeb3.provider.test.ts` (Vitest)
  - `test_active_provider_is_the_connected_one` (دو provider جعلی، MetaMask + Coinbase)
  - `test_wc_zombie_does_not_shadow_injected`
- **معیار پذیرش:** تست نشان دهد provider برگشتی همانی است که کاربر انتخاب کرده.

### [ ] C4 — تپ دوباره‌ی موبایل ماتچ را void می‌کند
- **چرا:** `touchend` روی روت + `click` روی دکمه، هر دو `processVerification` را صدا می‌زنند → ارسال دوم ۴۰۹ → catch → `outcome:'void'` + `phase:'bot-detected'`.
- **فایل:** `src/pages/ReactionGamePage.tsx:1153-1154, 1472, 580-598, 612-623`
- **تغییر:** گارد سنکرون `verifyingRef.current` در ابتدای `processVerification`؛ پاک شدن در پایان هر راند؛ حذف `onTouchEnd` سطح روت یا ادغام یکپارچه‌ی touch+click.
- **تست (قرمز→سبز):** `e2e/mobile-tap.spec.ts` (Playwright، viewport موبایل)
  - `test_single_tap_submits_exactly_once` (شمارش درخواست‌های `/api/round/result` = ۱)
  - `test_single_tap_never_voids_the_match`
- **معیار پذیرش:** یک تپ = دقیقاً یک ارسال؛ ماتچ هرگز void نشود.

> ### 🚦 گیت فاز ۱
> ۴ تست رگرسیون قرمز→سبز + همه‌ی تست‌های قبلی سبز + `bun run verify` سبز.

---

## فاز ۲ — HIGH سرور (مسیر پول) 🟠

**هدف:** یکپارچگی داده و پایداری مسیر پول. **تخمین:** ۱.۵ روز · **وابستگی:** فاز ۱

### [ ] H3 — ledger اقتصاد TOCTOU است، نه اتمیک
- **فایل:** `api/economy.py:200-216, 243-273`
- **تغییر:** خواندن + `FieldValue.increment` داخل یک تراکنش keyed روی `matches/{id}.settlementId`؛ یا سند `settlements/{settlementId}` با `create()` به‌عنوان گیت idempotency اتمیک.
- **تست:** `tests/integration/test_economy_idempotency.py::test_two_concurrent_settlements_count_once` (دو thread روی emulator)
- **معیار:** `users.wins` دقیقاً ۱ افزایش یابد.

### [ ] H4 — ledger داخل تراکنش commit‌نشده نوشته می‌شود
- **فایل:** `api/main.py:623-643`
- **تغییر:** `economy.record_settlement` از داخل `_mutate` بیرون بیاید و **بعد از** بازگشت موفق `store.update` اجرا شود؛ idempotency با `settlementId` پوشش داده شود.
- **تست:** `tests/integration/test_settle_ledger_order.py::test_aborted_transaction_leaves_no_ledger_row`
- **معیار:** با abort کردن تراکنش، هیچ رکورد ledger ثبت نشود.

### [ ] H5 — `settlement_id_for` با id تولیدی نمی‌خواند
- **فایل:** `api/economy.py:188-198, 305-309`
- **تغییر:** یک تابع مشترک `_settlement_id(match_id, outcome, stake, settled_at, times)`؛ هر دو مسیر از آن استفاده کنند.
- **تست:** `tests/unit/test_economy_id.py::test_helper_matches_production_id` — **امروز قرمز است**
- **معیار:** تست سبز + helper در `__all__` بماند.

### [ ] H8 — `sweep_expired` ماتچ کامل‌شده را void می‌کند
- **فایل:** `api/store.py:226-230, 393-399`
- **تغییر:** قبل از void، اگر `match_completed(m)` یا `settlement_deadline(m)` نگذشته → اول `_settle_once` (forfeit) را امتحان کن.
- **تست:** `tests/unit/test_sweep.py::test_completed_match_is_settled_not_voided`, `::test_active_match_past_play_expiry_still_settles_within_escrow_window`
- **معیار:** ماتچ کامل‌شده هرگز void نشود.

### [ ] H9 — sweep روی هر poll + ایندکس غایب
- **فایل:** `api/main.py:532-535`, `api/store.py:376, 409-413, 447-453`
- **تغییر:** sweep به job زمان‌بندی‌شده منتقل شود (endpoint محافظت‌شده یا cron)؛ ایندکس composite `(status, settled_at)` در مستندات + `firestore.indexes.json`؛ خطای ایندکس لاگ + health-counter شود.
- **تست:** `tests/integration/test_sweep_cost.py::test_queue_poll_does_not_scan_collections` (شمارش readهای emulator)
- **معیار:** هر poll صف صفر collection scan بزند.

### [ ] H10 — I/O شبکه زیر قفل/تراکنش store
- **فایل:** `api/main.py:581-645`, `api/store.py:210-218, 348-355`
- **تغییر:** `_verify_deposits_or_void` **قبل** از ورود به `store.update` اجرا شود (snapshot ماتچ → `duel_info` → سپس mutate).
- **تست:** `tests/integration/test_lock_no_io.py::test_slow_rpc_does_not_block_other_matches` (RPC با تأخیر ۳s + یک ماتچ دوم که باید فوراً پاسخ دهد)
- **معیار:** ماتچ دوم در < ۵۰۰ms پاسخ دهد.

### [ ] H21 — endpoint logout وجود ندارد
- **فایل:** `api/main.py` (جدید), `api/auth.py:224-254`
- **تغییر:** `POST /api/auth/logout` که `revoke_session(jti)` را صدا بزند؛ jti از توکن استخراج شود.
- **تست:** `tests/integration/test_auth_logout.py::test_revoked_token_is_rejected`
- **معیار:** بعد از logout، همان توکن ۴۰۱ بدهد.

### [ ] H6 — پیکربندی production fail-open
- **فایل:** `api/main.py:295-299`
- **تغییر:** پیش‌فرض برعکس شود: هر محیط production است مگر `PULSAR_ENV=dev` صریحاً ست شده باشد.
- **تست:** `tests/unit/test_config_gate.py::test_unknown_env_is_treated_as_production`
- **معیار:** بدون `PULSAR_ENV=dev`، نبود envهای اجباری باعث شکست startup شود.

### [ ] H7 — bind دامنه‌ی SIWE از هدر Host
- **فایل:** `api/main.py:434-438`
- **تغییر:** وقتی escrow فعال است `ALLOWED_DOMAIN` اجباری؛ در غیر این صورت `PUBLIC_HOST` ثابت.
- **تست:** `tests/integration/test_siwe_domain.py::test_foreign_host_header_cannot_pick_the_domain`
- **معیار:** درخواست با `Host: attacker.com` رد شود.

> ### 🚦 گیت فاز ۲
> ۸ تست رگرسیون سبز + تست Firestore روی emulator + `bun run verify` سبز.

---

## فاز ۳ — HIGH قرارداد 🟠

**هدف:** بستن مسیرهای از دست رفتن/گیر کردن پول. **تخمین:** ۱.۵ روز · **وابستگی:** فاز ۰ (Anvil)
**⚠️ توجه:** هر تغییر این فاز نیاز به به‌روزرسانی ABI کلاینت + پین‌های parity دارد (R6).

### [ ] H17 — انتقال‌های all-or-nothing پول را برای همیشه گیر می‌کنند
- **فایل:** `contracts/PulsarEscrow.sol:310-313, 327, 331-332`
- **تغییر:** الگوی pull-payment: `pendingWithdrawals[address]` + `withdraw()`؛ یا حداقل جداسازی هر انتقال در try/catch با credit قابل‌برداشت.
- **تست:** `contracts/test/PulsarEscrow.t.sol`
  - `test_reverting_recipient_does_not_block_the_other`
  - `test_blacklisting_token_does_not_freeze_the_pool`
- **معیار:** با یک گیرنده‌ی revert‌کننده، طرف مقابل پولش را می‌گیرد.

### [ ] H18 — سقف on-chain برای `proof.deadline`
- **فایل:** `contracts/PulsarEscrow.sol:267`
- **تغییر:** `require(proof.deadline <= duel.createdAt + MATCH_TIMEOUT, "deadline exceeds horizon");`
- **تست:** `test_RevertWhen_DeadlineBeyondRefundHorizon`
- **معیار:** امضای با deadline بلند رد شود — حتی اگر oracle معتبر باشد.

### [ ] H19 — refund بدون مجوز برنده را بی‌جایزه می‌کند
- **فایل:** `contracts/PulsarEscrow.sol:318-335`
- **تغییر (نیاز تصمیم — R4):** گزینه‌ها:
  - (الف) پنجره‌ی تسویه‌ی انحصاری: تا `MATCH_TIMEOUT` فقط settle مجاز، refund از `MATCH_TIMEOUT + grace`.
  - (ب) refund نامتقارن: در حالت Active، بخشی از استیک رهاکننده به طرف مقابل.
  - (ج) `settleOnTimeout(proof)` که به برنده اجازه دهد بعد از تایم‌اوت تسویه کند.
- **تست:** `test_LosingPlayerCannotRefundAwayTheWinnerPrize`
- **معیار:** برنده‌ی دارای امضای معتبر همیشه بتواند پولش را بگیرد.

### [ ] H20 — `joinDuel` بدون cutoff و بدون activation
- **فایل:** `contracts/PulsarEscrow.sol:240-255`
- **تغییر:** `activatedAt` در `joinDuel` ثبت شود؛ `refundTimeoutMatch` روی `max(createdAt, activatedAt)` لنگر شود؛ join بعد از `createdAt + MATCH_TIMEOUT` رد شود.
- **تست:** `test_JoinAtT29m59s_RefundWindowStartsAtActivation`, `test_JoinAfterHorizon_Reverts`
- **معیار:** یک ماتچ Active حداقل پنجره‌ی بازی کامل داشته باشد.

### [ ] M22 — `MIN_STAKE_UNITS` اعشار ۶ را hardcode می‌کند
- **فایل:** `contracts/PulsarEscrow.sol:146`
- **تغییر:** `decimals()` در constructor خوانده شود و `MIN_STAKE_UNITS = 10**decimals`.
- **تست:** `test_MinStakeFollowsTokenDecimals` (با MockUSDT ۱۸-اعشاری)
- **معیار:** با توکن ۱۸-اعشاری، حداقل استیک درست محاسبه شود.

### [ ] M23 — رویداد `MatchCreated` مقدار جعلی emit می‌کند
- **فایل:** `contracts/PulsarEscrow.sol:237`
- **تغییر:** `totalPool: 0` emit شود (هم‌خوان با storage) یا رویداد بعد از join.
- **تست:** `test_Event_MatchCreated_TotalPoolIsZero`
- **معیار:** ایندکسرها عدد غلط نبینند.

### [ ] M24 — `setTreasuryWallet`/`setOracleSigner` یک‌مرحله‌ای و بدون timelock
- **فایل:** `contracts/PulsarEscrow.sol:337-349`
- **تغییر:** دو-مرحله‌ای (pending + accept) + timelock برای oracle.
- **تست:** `test_OracleRotationRequiresTimelock`, `test_TreasuryRotationIsTwoStep`
- **معیار:** تعویض oracle فوری ممکن نباشد.

### [ ] M25 — `usedSignatures` دفاع مرده
- **فایل:** `contracts/PulsarEscrow.sol:185, 290-291`
- **تغییر (نیاز تصمیم):** یا حذف شود (چون غیرقابل‌دسترسی است) یا کامنت/تست اصلاح شود تا ادعای بیش‌ازواقع نباشد.
- **معیار:** کامنت و تست با واقعیت کد هم‌خوان باشند.

> ### 🚦 گیت فاز ۳
> `forge test` سبز (≥۳۰ تست) + تست‌های جدید روی anvil + ABI کلاینت به‌روز + `bun run verify` سبز.

---

## فاز ۴ — HIGH کلاینت 🟠

**هدف:** پایداری و صداقت داده در کلاینت. **تخمین:** ۲ روز · **وابستگی:** فاز ۱ (C3, C4)

### [ ] H11 — مسیر بازیابی بعد از refresh یک no-op است
- **فایل:** `src/pages/ReactionGamePage.tsx:461-499`
- **تغییر:** `serverMatch`/`serverSession` در ref نگه داشته شوند و `finishServerMatch` از ref بخواند؛ یا به‌عنوان پارامتر پاس شوند.
- **تست:** `e2e/refresh-recovery.spec.ts::test_reload_after_decided_match_still_settles`
- **معیار:** بعد از reload، `settleDuel` واقعاً submit شود.

### [ ] H12 — موجودی واقعی با `vaultBalance` صفر بازنویسی می‌شود
- **فایل:** `src/lib/realWeb3.ts:1296-1303`
- **تغییر:** `balanceUSDT` هرگز از `vaultBalance` نوشته نشود؛ مقدار زنجیره و `balanceUnknown` دست‌نخورده بماند.
- **تست:** `src/lib/realWeb3.balance.test.ts::test_profile_save_does_not_zero_the_chain_balance`
- **معیار:** بعد از `recordMatch`، موجودی همان مقدار واقعی بماند.

### [ ] H13 — اعشار توکن در نوشتن hardcode است
- **فایل:** `src/lib/chain.ts:51`, `src/lib/escrowFlow.ts:133,145`, `src/pages/ReactionGamePage.tsx:314`
- **تغییر:** `decimals()` یک‌بار خوانده و per-token cache شود؛ همه‌ی `parseUnits` و مقایسه‌ها از آن استفاده کنند.
- **تست:** `src/lib/escrowFlow.decimals.test.ts::test_stake_uses_onchain_decimals` (با MockUSDT ۱۸-اعشاری)
- **معیار:** مقدار واریزی با مقدار نمایش‌داده‌شده یکی باشد.

### [ ] H14 — race تعویض حساب داده‌ی کاربر دیگر را نشان می‌دهد
- **فایل:** `src/store/usePulsarStore.ts:56-71`
- **تغییر:** آدرس در closure capture شود؛ نتیجه فقط اگر `account.address === captured && account.connected` باشد اعمال شود؛ generation counter برای disconnect.
- **تست:** `src/store/usePulsarStore.race.test.ts::test_stale_load_is_dropped`
- **معیار:** داده‌ی کاربر A زیر هویت B ظاهر نشود.

### [ ] H15 — قفل حساب/شبکه در حین ماتچ فعال
- **فایل:** `src/lib/realWeb3.ts:189-199`
- **تغییر:** در حین ماتچ فعال، تعویض حساب/شبکه هشدار + بلاک شود؛ `chainChanged` در حین بازی reload نکند.
- **تست:** `e2e/account-switch-midmatch.spec.ts`
- **معیار:** کاربر نتواند در میانه‌ی ماتچ هویت را عوض کند.

### [ ] M5 — state تسویه روی rematch پاک نمی‌شود
- **فایل:** `src/pages/ReactionGamePage.tsx:1114-1128`
- **تغییر:** `onchainAction`/`settlementTxHash`/`lastProof`/`serverMatch`/`serverSession` در `handleRematch` ریست شوند.
- **تست:** `e2e/rematch.spec.ts::test_rematch_clears_previous_tx_link`

### [ ] M29 — `setInterval`/`setTimeout` بدون cleanup
- **فایل:** `src/pages/ReactionGamePage.tsx:874-876, 576-579`
- **تغییر:** نگه‌داشتن در ref و پاک کردن در unmount + قبل از شروع فاز جدید.
- **تست:** `src/pages/ReactionGamePage.timers.test.ts::test_no_state_update_after_unmount`

### [ ] M30 — `useSyncExternalStore` با subscribe اینلاین
- **فایل:** `src/store/usePulsarStore.ts:318-322`
- **تغییر:** `subscribe` به module scope منتقل شود.
- **تست:** `src/store/usePulsarStore.subscribe.test.ts::test_subscribe_identity_is_stable`

### [ ] M38 — `matchIdToBytes32` به `crypto.subtle` نیاز دارد
- **فایل:** `src/lib/gameServerClient.ts:314-320`
- **تغییر:** feature-check + خطای صادقانه، یا fallback SHA-256.
- **تست:** `src/lib/gameServerClient.test.ts::test_clear_error_without_secure_context`

> ### 🚦 گیت فاز ۴
> تست‌های Vitest + Playwright سبز + `bun run verify` سبز.

---

## فاز ۵ — انصاف و یکپارچگی ⚖️ (نیاز تصمیم شما)

**هدف:** رفع نقص‌های طراحی که باگ نیستند ولی محصول را غیرقابل‌اعتماد می‌کنند.
**تخمین:** ۳-۵ روز · **وابستگی:** 🛑 **تصمیم مسیر محصول (A/B/C/D) لازم است**

### [ ] H1 — برنده با latency شبکه تعیین می‌شود
- **فایل:** `api/match_engine.py:419-422, 468-482`
- **گزینه‌ها:**
  - (الف) رتبه‌بندی روی claim کلاینت **محدودشده** توسط observed (کد همین حالا دو طرفه cross-check می‌کند).
  - (ب) تخمین RTT per-player (probe در ابتدای هر راند) و جبران آن.
  - (ج) matchmaking با سقف پینگ + سرورهای منطقه‌ای.
- **تست:** `tests/unit/test_fairness.py::test_equal_reaction_different_latency_is_a_tie`
- **معیار:** دو بازیکن با واکنش یکسان و پینگ متفاوت، مساوی شوند.

### [ ] H2 — commitment واقعی
- **فایل:** `api/match_engine.py:329-346, 322-326`
- **تغییر:** سرور در لحظه‌ی commit یک salt بدهد و آن را در `_result_proof` بگنجاند؛ یک commit در هر (match, round, player) اجبار شود.
- **تست:** `tests/unit/test_commit_binding.py::test_recommit_after_window_is_rejected`
- **معیار:** کلاینت نتواند بعد از دیدن هدف دوباره commit کند.

### [ ] H16 — ضد-تقلب واقعی
- **فایل:** `src/pages/ReactionGamePage.tsx:170-192`, `src/lib/antiCheat.ts:118-134, 220-229`
- **تغییر:** تصمیم طراحی لازم است. حداقل: حذف ادعاهای جعلی از UI؛ حداکثر: device attestation + anomaly detection سمت سرور.
- **تست:** `tests/unit/test_anticheat_honesty.py::test_no_fabricated_verification_claims`

### [ ] H22 — matchmaking مهارت‌محور + rating
- **فایل:** `api/match_engine.py` (queue), `api/store.py`
- **تغییر:** Glicko/ELO روی `observed_ms` معتبر؛ جفت‌سازی در باند confidence.
- **تست:** `tests/unit/test_matchmaking_rating.py::test_players_are_paired_within_rating_band`
- **معیار:** بازیکن تازه‌کار با بازیکن حرفه‌ای جفت نشود.

> ### 🛑 گیت تصمیم فاز ۵
> قبل از شروع: انتخاب مسیر محصول (A free-to-play / B B2B SDK / C بنچمارک / D پول واقعی مجوزدار).
> این انتخاب طراحی H1، H16 و H22 را کاملاً تغییر می‌دهد.

---

## فاز ۶ — عملیات و پیکربندی 🛠️

**تخمین:** ۲ روز · **وابستگی:** فاز ۲

- [ ] **6.1** metrics + alerting (readهای Firestore، latency هر endpoint، نرخ fallback limiter، نرخ شکست امضا)
- [ ] **6.2** گسترش `/api/health`: وضعیت RPC، وضعیت decimals، وضعیت ledger، وضعیت sweep
- [ ] **6.3** admin tooling: inspect یک ماتچ، force-settle، force-void، جستجوی بازیکن
- [ ] **6.4** مسیر dispute/support: کاربر بتواند یک ماتچ را گزارش کند
- [ ] **6.5** `firestore.indexes.json` + مستند ایندکس‌های لازم
- [ ] **6.6** runbook حادثه (RPC down، Firestore down، oracle key compromise، stuck funds)
- [ ] **6.7** `.env.example` کامل (۸+ متغیر غایب)
- [ ] **6.8** `pip-compile` + `requirements.lock` (ریسک reproducibility)
- [ ] **6.9** M15/M16/M17: محدود کردن `onchain._cache`، پاک‌سازی `_rl_window`، قفل روی ست‌های auth
- [ ] **6.10** M12/M13/M18: حذف leak آدرس در `username_lookup`، حذف متن استثنا، quorum/fallback برای RPC

**معیار پذیرش:** `/api/health` کامل + داشبورد + runbook نوشته‌شده.

---

## فاز ۷ — MEDIUM (۴۵ مورد) 📋

**تخمین:** ۳ روز · **وابستگی:** فاز ۲-۴ · دسته‌بندی‌شده در ۵ دسته

### ۷.۱ — امنیت و اعتبارسنجی (۸ مورد)
- [ ] M1 — `verify_siwe` آدرس بازیابی‌شده را با ادعاشده مقایسه کند
- [ ] M2 — `_burn_nonce` فقط `AlreadyExists` را replay بداند؛ TTL واقعی تعریف شود
- [ ] M3 — پنجره‌ی nonce: پذیرش پنجره‌ی قبلی برای ۳۰ ثانیه (رفع fail تصادفی)
- [ ] M4 — eviction در `_remember_used` از O(n) به O(1)
- [ ] M5 — `verify_session` نوع payload را اعتبارسنجی کند
- [ ] M6 — `_signature_to_low_s_bytes` برای `v∈{27,28}` درست شود + تست high-s
- [ ] M7 — `sign_settlement` منبع رکورد را اعتبارسنجی کند (HMAC engine-marker)
- [ ] M11 — `claim_match` نیاز به برنده بودن claimer + چک `receipt.from`

### ۷.۲ — صحت داده و اقتصاد (۶ مورد)
- [ ] M8 — cache کردن signer در oracle
- [ ] M9 — `_settle_once` بدون پرتاب HTTPException داخل mutate
- [ ] M10 — `match_view` بعد از finalize دوباره get کند
- [ ] M20 — حذف override `PLATFORM_FEE_BPS` از env
- [ ] M21 — محاسبه‌ی prize با `Decimal` و واحد پایه
- [ ] M14 — `queue` با استیک متفاوت را رد کند

### ۷.۳ — کلاینت (۱۰ مورد)
- [ ] M26 — `searchPlayers` با playerId
- [ ] M27 — «چالش دوست» واقعی یا تغییر برچسب
- [ ] M28 — (در فاز ۴ انجام شد)
- [ ] M31 — progression از ledger سرور
- [ ] M33 — یک منبع حقیقت برای `isEscrowConfigured`
- [ ] M34 — نام شبکه/توکن از `CHAIN`/`TOKENS`
- [ ] M35 — پاک کردن URI کهنه‌ی WC + یکسان‌سازی آستانه‌ها
- [ ] M36 — `disconnect()` در cancel + حلقه‌ی معکوس purge
- [ ] M37 — هر دو طرف بتوانند تسویه را اجبار کنند
- [ ] M39 — پر کردن `match.hash` تا گواهی واقعی شود

### ۷.۴ — قرارداد (۴ مورد)
- [ ] M25 — (در فاز ۳ انجام شد)
- [ ] M42 — `subscribeGlobalMatches` پاک‌سازی ورودی‌های کهنه
- [ ] M43 — `LanguageContext` بدون رجکس/replacement string
- [ ] M44 — Sentry lazy load
- [ ] M45 — معکوس دقیق `getLevel`/`getXPForLevel`

### ۷.۵ — تست‌های قرارداد (۱۲ گپ)
- [ ] Mock USDT بدون bool-return + Mock با `false` + fee-on-transfer + reentrant + blacklisting
- [ ] تست reentrancy
- [ ] تست replay واقعی (`usedSignatures`)
- [ ] تست griefing refund بی‌مجوز
- [ ] تست cross-chain / cross-contract
- [ ] تست tampered proof
- [ ] تست‌های مرزی (deadline == now، length ≠ 65، v نامعتبر)
- [ ] تست `setTreasuryWallet`
- [ ] assert رویدادها (`vm.expectEmit`)
- [ ] تست stuck-funds
- [ ] تست decimals
- [ ] تست‌های cross-state (refund بعد از settle، …)
- [ ] `forge coverage` + invariant tests

---

## فاز ۸ — LOW + دسترس‌پذیری + i18n ♿

**تخمین:** ۲ روز · **وابستگی:** فاز ۴

- [ ] **8.1** حذف `maximum-scale=1, user-scalable=no` (WCAG 1.4.4)
- [ ] **8.2** `lang` داینامیک بر اساس زبان انتخاب‌شده
- [ ] **8.3** دکمه‌های غیر-`<button>` → عناصر معنایی با keyboard
- [ ] **8.4** `role="dialog"` + `aria-modal` + focus-trap + Escape برای ۴ مودال
- [ ] **8.5** `aria-label` برای همه‌ی آیکون-باتن‌ها
- [ ] **8.6** `LanguageSelector` با `aria-expanded`/`aria-haspopup` + ناوبری کلید
- [ ] **8.7** `<label>` برای input جستجو
- [ ] **8.8** live-region برای بازخوردهای motion-only
- [ ] **8.9** i18n: انتقال همه‌ی متن‌های hardcoded به `translations.ts`
- [ ] **8.10** RTL: حذف `dir="ltr"` از پنل‌های دارای متن ترجمه‌شده
- [ ] **8.11** بازی فقط با کیبورد (هدف با Enter/Space فعال شود)
- [ ] **8.12** `prefers-reduced-motion` رعایت شود
- [ ] **8.13** axe: صفر خطای critical/serious
- [ ] **8.14** L1..L20 باقی‌مانده (کد مرده، linter، کامنت‌های نادرست)
- [ ] **8.15** ESLint + ruff + mypy در CI (اگر در فاز ۰ نبود)

**معیار پذیرش:** axe صفر خطای critical/serious + تست keyboard-only سبز + snapshot RTL.

---

## فاز ۹ — صداقت UI 🎭

**تخمین:** ۱ روز · **وابستگی:** فاز ۸

- [ ] **9.1** حذف آدرس‌های تصادفی leaderboard (`realWeb3.ts:1405`) → `—` یا حذف
- [ ] **9.2** حذف fallbackهای ساختگی 180ms/185ms
- [ ] **9.3** حذف «network latency» تصادفی از `AppHeader`
- [ ] **9.4** حذف استفاده از history کاربر به‌عنوان «LIVE arena feed»
- [ ] **9.5** حذف/تغییر برچسب ادعاهای verification جعلی
- [ ] **9.6** گواهی: نمایش tx hash و امضای واقعی oracle (وابسته به M39)
- [ ] **9.7** تست گیت «بدون داده‌ی ساختگی» در CI
- [ ] **9.8** بازنویسی README و DEPLOYMENT برای هم‌خوانی با واقعیت

**معیار پذیرش:** تست CI که هر `Math.random()` روی سطح پولی را رد کند.

---

## فاز ۱۰ — E2E، Load و Chaos 🧪

**تخمین:** ۳ روز · **وابستگی:** فاز ۹

### ۱۰.۱ — E2E کامل (Playwright)
- [ ] دسکتاپ: connect → queue → create → join → ۳ راند → settle → claim → گواهی با tx واقعی
- [ ] موبایل: همان مسیر با viewport لمسی (regression C4)
- [ ] refresh در میانه‌ی ماتچ → resume
- [ ] refresh بعد از تسویه → auto-settle
- [ ] رد کردن تراکنش در هر مرحله
- [ ] شکست RPC در هر مرحله
- [ ] refund بعد از تایم‌اوت
- [ ] تعویض حساب/شبکه در حین ماتچ

### ۱۰.۲ — Visual regression
- [ ] spawn هدف، انتقال راند، صفحه‌ی نتیجه
- [ ] چیدمان RTL (fa/ar) در ۳ breakpoint
- [ ] تم روشن/تیره

### ۱۰.۳ — Load
- [ ] k6/Locust: ۱۰۰۰ poller هم‌زمان روی `/api/queue`
- [ ] اندازه‌گیری read فایرستور به‌ازای هر ماتچ (هدف: < ۲۰)
- [ ] اندازه‌گیری latency p50/p95/p99 هر endpoint
- [ ] گزارش هزینه‌ی تخمینی در مقیاس

### ۱۰.۴ — Chaos
- [ ] کشتن RPC در میانه‌ی راند
- [ ] کشتن Firestore در میانه‌ی تراکنش
- [ ] split کردن replica (دو instance)
- [ ] تزریق تأخیر ۵s RPC (اثبات H10)
- [ ] soak ۲۴ ساعته: رشد حافظه

**معیار پذیرش:** گزارش load + همه‌ی سناریوهای chaos با رفتار تعریف‌شده (fail-closed برای پول، fail-open برای دسترس‌پذیری).

---

## فاز ۱۱ — دروازه‌های انتشار 🚀

**وابستگی:** همه‌ی فازهای قبل · **تصمیم نهایی با شما**

### ۱۱.۱ — گیت فنی
- [ ] `bun run verify` سبز
- [ ] coverage سرور ≥ ۸۰٪، موتور ≥ ۹۰٪، قرارداد ≥ ۹۵٪
- [ ] `forge coverage` + invariant سبز
- [ ] صفر خطای critical/serious در axe
- [ ] صفر یافته‌ی CRITICAL/HIGH باز
- [ ] **ممیزی قرارداد توسط یک شرکت واقعی (نه AI)** — قبل از هر پول واقعی
- [ ] تست نفوذ (pen-test) روی API

### ۱۱.۲ — گیت عملیاتی
- [ ] metrics + alerting فعال
- [ ] runbook حادثه تمرین‌شده
- [ ] backup/restore Firestore تست‌شده
- [ ] rollback plan تست‌شده (`VITE_ESCROW_ADDRESS` unset)
- [ ] on-call مشخص

### ۱۱.۳ — گیت حقوقی/محصول (تصمیم شما)
- [ ] انتخاب مسیر محصول (A/B/C/D)
- [ ] نهاد حقوقی + حوزه‌ی قضایی
- [ ] مجوز (اگر مسیر D)
- [ ] KYC/AML (اگر پول واقعی)
- [ ] ToS/Privacy/Risk Disclosure با وکیل
- [ ] geo-blocking در لبه
- [ ] ابزار مسئولانه‌بازی

### ۱۱.۴ — rehearsal نهایی روی Amoy
- [ ] approve → createDuel → joinDuel → بازی → settleDuel
- [ ] تأیید دریافت ۹۸٪ توسط برنده و ۲٪ توسط treasury
- [ ] `refundTimeoutMatch` بعد از ۳۰ دقیقه
- [ ] با کیف پول واقعی و پول تستی

---

## پیوست A — نقشه‌ی فایل‌های جدید

```
api/requirements-dev.txt
pytest.ini
vitest.config.ts
firestore.indexes.json
scripts/verify.sh
scripts/start_emulator.sh
scripts/start_anvil.sh
tests/conftest.py
tests/fixtures/fake_rpc.py
tests/fixtures/chain.py
tests/fixtures/firestore.py
tests/unit/*.py
tests/integration/*.py
tests/adversarial/*.py
e2e/*.spec.ts
e2e/fixtures/mockWallet.ts
src/**/*.test.ts(x)
contracts/test/mocks/{NoBoolUSDT,FalseUSDT,FeeOnTransfer,Reentrant,Blacklisting}.sol
docs/plans/REMEDIATION-PLAN.md   ← همین فایل
```

## پیوست B — ترتیب اجرا و تخمین

| فاز | محتوا | تخمین | گیت |
|---|---|---|---|
| ۰ | دروازه‌ها | ۱ روز | `verify` + CI سبز |
| ۱ | ۴ CRITICAL | ۱ روز | ۴ تست قرمز→سبز |
| ۲ | HIGH سرور | ۱.۵ روز | ۸ تست |
| ۳ | HIGH قرارداد | ۱.۵ روز | forge ≥۳۰ تست |
| ۴ | HIGH کلاینت | ۲ روز | Vitest + Playwright |
| ۵ | انصاف (تصمیم) | ۳-۵ روز | تست انصاف |
| ۶ | عملیات | ۲ روز | health + runbook |
| ۷ | MEDIUM (۴۵) | ۳ روز | تست به‌ازای هر مورد |
| ۸ | LOW + a11y | ۲ روز | axe صفر |
| ۹ | صداقت UI | ۱ روز | تست ضد-داده‌ی-ساختگی |
| ۱۰ | E2E/Load/Chaos | ۳ روز | گزارش load |
| ۱۱ | دروازه‌های انتشار | — | همه‌ی گیت‌ها |
| | **جمع** | **~۲۲ روز کاری** | |

## پیوست C — ریسک‌ها

| ریسک | اثر | کاهش |
|---|---|---|
| دیسک سندباکس ۹.۸G | نصب‌ها شکست می‌خورد | پاک‌سازی دوره‌ای کش؛ ابزارهای سنگین یکی‌یکی |
| تغییر قرارداد → ABI کلاینت | شکستن کلاینت | R6: هر تغییر قرارداد = به‌روزرسانی ABI + پین |
| فاز ۵ نیاز به تصمیم دارد | بلاک شدن | تا فاز ۴ جلو می‌رویم؛ فاز ۵ منتظر تصمیم |
| Firestore emulator ≠ production | رفتار ایندکس متفاوت | rehearsal نهایی روی Firebase واقعی در فاز ۱۱ |
| تست‌های موجود ممکن است بعد از fix بشکنند | کار اضافه | هر فاز: تست‌های موجود همان ماژول اول اجرا شوند |

## پیوست D — تصمیم‌های لازم از شما

| # | تصمیم | کجا لازم است |
|---|---|---|
| **D1** | مسیر محصول: A (free-to-play) / B (B2B SDK) / C (بنچمارک) / D (پول واقعی مجوزدار) | قبل از فاز ۵ |
| **D2** | H19: کدام راهکار refund؟ (پنجره‌ی انحصاری / نامتقارن / settleOnTimeout) | فاز ۳ |
| **D3** | M25: `usedSignatures` حذف شود یا کامنت اصلاح شود؟ | فاز ۳ |
| **D4** | آیا `docs/audit/` و `docs/plans/` در مخزن کامیت شوند؟ | همین حالا |
| **D5** | آیا از فاز ۰ شروع کنم؟ | همین حالا |
