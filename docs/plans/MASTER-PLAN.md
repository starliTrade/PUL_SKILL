# PULSAR — پلن مادر رفع اشکال و تست 🔒 LOCKED

```
╔══════════════════════════════════════════════════════════════════════════╗
║  نسخه:        1.8-CLOSED (فاز ۱ بسته)                                                 ║
║  تاریخ قفل:   2026-10-12                                                 ║
║  مبنا:        docs/audit/FULL-AUDIT-2026-10-12.md  (109 یافته)           ║
║  SHA-256:     12ced0f964a69110…88699373f6d794a1                                                   ║
║  وضعیت:       🔒 قفل‌شده — اجرا در جریان                                 ║
╚══════════════════════════════════════════════════════════════════════════╝
```

## 🔐 پروتکل تغییر پلن (بعد از قفل)

این سند **قفل** است. یعنی:

1. **دامنه (scope) ثابت است.** هیچ آیتمی بدون تأیید صریح شما حذف نمی‌شود.
2. **افزودن آیتم جدید** فقط با: (الف) کشف یافته‌ی جدید در حین کار، (ب) تأیید شما، (ج) ثبت در CHANGELOG با bump نسخه (`1.1`, `1.2`, …).
3. **تغییر ترتیب فازها** ممنوع، مگر وابستگی فنی اثبات‌شده + تأیید شما.
4. **بستن یک آیتم** فقط با: تست رگرسیون سبز + `bun run verify` سبز + تیک در همین فایل.
5. **هیچ آیتمی «رد شده» علامت نمی‌خورد** مگر با ثبت صریح `⛔ ACCEPTED-RISK` + دلیل + امضای شما.

**راهنمای وضعیت آیتم‌ها:**
`[ ]` باز · `[~]` در جریان · `[x]` تمام‌شده (تست سبز) · `[!]` بلاک‌شده · `[⛔]` ریسک پذیرفته‌شده

---

## ۰. قواعد کار (R1–R8)

| # | قاعده | چرا |
|---|---|---|
| **R1** | هیچ fix بدون تست رگرسیون. تست *قبل از* fix قرمز، *بعد از* fix سبز. **تست قرمز در یک کامیت جداگانه قبل از fix ثبت شود** تا حالت قرمز از تاریخ git بازتولیدپذیر باشد (درس فاز ۱). | وگرنه نمی‌دانیم باگ رفع شد یا پنهان |
| **R2** | هر فاز = یک برنچ + یک PR. merge با شماست. | مالکیت تصمیم |
| **R3** | پایان هر فاز: `bun run verify` کامل سبز. | جلوگیری از regression |
| **R4** | تغییر رفتار قابل‌مشاهده → تصمیم مشترک قبل از کد. | جلوگیری از کار دوباره |
| **R5** | هیچ داده‌ی ساختگی/نمایشی جدید. | بدهی اعتمادی |
| **R6** | هر تغییر قرارداد → تست Foundry + ABI کلاینت + پین parity. | یک پروتکل‌اند |
| **R7** | هر تغییر پروتکل امضا → تست روی Anvil با قرارداد واقعی. | تست واحد کافی نیست |
| **R8** | کامیت اتمیک به‌ازای هر آیتم، با ID آیتم در پیام. | ردیابی |

**Definition of Done هر آیتم:**
```
[ ] کد تغییر کرد
[ ] تست رگرسیون نوشته شد و شاهدِ قرمز بودنش ثبت شد
[ ] تست بعد از fix سبز است
[ ] تست‌های موجود همان ماژول سبزند
[ ] bun run verify سبز است
[ ] اگر رفتار عوض شد → در PR توضیح داده شد
```

---

## ۱. وضعیت زیرساخت

| ابزار | وضعیت | مسیر |
|---|---|---|
| Foundry 1.8.5 (forge/anvil/cast) | ✅ | `/root/workspace/.foundry/bin` |
| Java 21 JRE (Temurin) | ✅ | `/root/workspace/.tools/jdk-21*/` |
| Firestore Emulator 1.19.8 | ✅ | `127.0.0.1:8081` |
| Playwright + Chromium 156 | ✅ | `/root/workspace/.cache/ms-playwright` |
| Python venv | ✅ | `/root/workspace/PUL_SKILL/.venv` |
| OpenZeppelin (برای forge) | ✅ | `contracts/lib/openzeppelin-contracts` |
| node / bun / npm | ✅ | — |
| ⚠️ دیسک | ۹.۸G، ~۷۴٪ | پاک‌سازی دوره‌ای کش لازم است |

---

# فاز ۰ — دروازه‌ها (Gate 0) 🚪
**هدف:** هیچ تغییری بدون تست و بدون CI واقعی انجام نشود. **تخمین:** ۱ روز
**🚦 گیت خروج:** `bun run verify` سبز + CI سبز + Firestore Emulator و Anvil در CI + coverage گزارش شود

- [x] **0.1 · 🔴CI-1** رفع CI قرارداد — نصب `openzeppelin-contracts` در کنار `forge-std`
  `‎.github/workflows/ci.yml` · تست: اجرای محلی workflow → `forge test` باید ۲۱/۲۱ PASS بدهد
  پذیرش: job قرارداد سبز و لاگ نشان دهد ۲۱ تست اجرا شد
- [x] **0.2** اسکریپت واحد تأیید `scripts/verify.sh` + `bun run verify`
  محتوا: `tsc --noEmit` → `pytest` → `forge test` → `compile_check.js` → `vitest` → `ruff` → `mypy`
  پذیرش: یک دستور، همه‌ی گیت‌ها، exit 0
- [~] **0.3** ساختار pytest — `tests/{unit,integration,e2e,adversarial}/`, `conftest.py`, `pytest.ini`
  مهاجرت ۶ اسکریپت `scripts/test_*.py` و `probe_*.py`؛ اسکریپت‌های فعلی wrapper نازک بمانند
  پذیرش: `pytest` ≥۹۰ تست سبز (≥ تعداد `check()`های فعلی)
- [x] **0.4** `api/requirements-dev.txt` + `ruff.toml` — pytest, pytest-cov, pytest-asyncio, hypothesis, time-machine, respx, ruff, mypy, httpx
- [x] **0.5** ⚠️ **تزریق ساعت (Clock injection)** — `api/timebase.py` (`now()`/`now_ms()`) + مسیردهی **۳۳ خواندن ساعت در ۷ ماژول** (match_engine, store, main, auth, onchain, oracle, economy)
  پذیرش: ✅ هیچ `time.time()` مستقیمی بیرون از seam نماند (تست `test_no_module_reads_the_clock_directly` آن را تضمین می‌کند)؛ `clock` fixture زمان را برای کل سرور جلو می‌برد
- [x] **0.6** Fixture رسمی `tests/fixtures/fake_rpc.py` — پاسخ به `eth_chainId`/`eth_call`(paymentToken/decimals/matches)/`eth_getTransactionReceipt`؛ تزریق خطا: `fail_next(n)` و `break_call(selector)`
  پذیرش: ✅ `tests/unit/test_onchain_gate.py` — ۸ تست سبز که gate واقعی را با fake RPC می‌رانند + ۲ baseline قرمز C2
- [~] **0.7** Firestore Emulator در CI — `scripts/start_emulator.sh` + fixture `firestore_emulator`
  پذیرش: تست Firestore در CI **اجرا** شود (نه skip) و C1 را بازتولید کند
- [x] **0.8** Anvil + escrow در CI — `scripts/start_anvil.sh` (anvil + deploy خودکار + manifest)، `tests/fixtures/chain.py` (کلاینت JSON-RPC با eth_abi/eth_account، بدون web3)، `tests/integration/test_chain_smoke.py`
  پذیرش: ✅ ۷ تست سبز روی EVM واقعی — createDuel موجودی را قفل می‌کند، joinDuel استخر را دو برابر می‌کند، **تسویه با امضای واقعی `api/oracle.py` روی قرارداد مستقر پذیرفته می‌شود** (۹۸٪ برنده + ۲٪ treasury)، و امضای غیر-oracle رد می‌شود
- [x] **0.9** Vitest + jsdom — `vitest.config.ts`، `bun run test:unit`، در CI و verify
  پذیرش: ✅ `src/lib/realWeb3.provider.test.ts` (۴ تست) — زیرساخت کار می‌کند و **C3 را قرمز نشان داد** قبل از fix
- [ ] **0.10** Playwright + کیف پول mock — `e2e/`, `e2e/fixtures/mockWallet.ts`
  پذیرش: تست نمونه اپ را load کند و connect را بزند
  **یادداشت (v1.7):** تست رگرسیون C4 به‌جای Playwright با **React Testing Library** نوشته شد — صفحه‌ی واقعی را رندر می‌کند، از فاز human-verify تا action می‌رود، و جفت رویداد واقعی (touchend + click) را می‌فرستد. سریع‌تر، قطعی‌تر، و مستقیماً همان باگ را می‌گیرد. Playwright برای E2E کامل فاز ۱۰ باقی می‌ماند.
- [ ] **0.11** axe-core — `e2e/a11y.spec.ts`؛ پذیرش: axe روی صفحه‌ی اصلی اجرا شود
- [x] **0.12** گیت coverage با ratchet — `.coveragerc` (fail_under=48، فقط بالا می‌رود) + `--cov=api` در verify و CI
  پذیرش: ✅ گیت هم سبز می‌شود (۴۸٪) و هم قرمز (با floor=99 → exit 1) — گیت معتبر است، نه تشریفاتی. مسیر ratchet: ۴۸ → ۵۵ (فاز ۱) → ۶۵ (فاز ۲) → ۷۰ (فاز ۳) → ۸۰ (فاز ۷)
- [x] **0.13** CI: اجرای همه‌ی گیت‌ها — ruff + pytest(+coverage) + Firestore emulator + anvil/chain + forge + گارد «تست واقعاً اجرا شد»؛ `timeout-minutes` و `concurrency` اضافه شد
  پذیرش: ✅ `tests/unit/test_ci_workflow.py` (۱۲ تست) خودِ workflow را اعتبارسنجی می‌کند — از جمله **گارد رگرسیون CI-1** (نصب OZ) و پین بودن وابستگی‌ها. این تست یک باگ واقعی گرفت: یک دونقطه‌ی نقل‌نشده در `name:` کل فایل YAML را می‌شکست (CI بی‌صدا اجرا نمی‌شد)

---

# فاز ۱ — CRITICAL 🔴
**هدف:** بستن ۴ باگی که محصول را می‌شکنند یا پول را از دست می‌دهند. **تخمین:** ۱ روز
**🚦 گیت خروج:** ✅ **محقق شد** — ۴ تست رگرسیون قرمز→سبز + همه‌ی تست‌های قبلی سبز + `bun run verify` با ۱۳ گیت سبز

### 📋 بازبینی بستن فاز ۱ (۲۰۲۶-۱۰-۱۲)

بعد از اتمام، یک بازبینی مستقل روی کل دیف انجام شد که **۳ شکاف واقعی** پیدا کرد — همه رفع شدند:

| # | شکاف | شدت | رفع |
|---|---|---|---|
| ۱ | **C3 نیمه‌کاره بود.** فقط دو مسیر اتصال تعاملی provider را ثبت می‌کردند؛ مسیرهای **restore بعد از reload**، **accountsChanged** و **restore مربوط به WalletConnect** همچنان به `window.ethereum` سقوط می‌کردند — یعنی کاربری که با Rabby وصل می‌شد و صفحه را reload می‌کرد، دوباره با MetaMask امضا می‌کرد. | MAJOR | provider به پارامتر چهارم `setConnectedAddress` تبدیل شد تا **هر** مسیری که session می‌سازد آن را ثبت کند (۱۵ call site بازبینی شد) + تست رگرسیون روی `restoreSession()` |
| ۲ | **provider زامبی در `activeProvider` باقی می‌ماند.** وقتی سشن WalletConnect می‌مرد، فقط `wcProvider` پاک می‌شد و `activeProvider` همچنان به جسد اشاره می‌کرد → fallback همان را برمی‌گرداند. | MAJOR | پاک‌سازی `activeProvider` وقتی همان object است + تست رگرسیون |
| ۳ | **گیت coverage ۲۰ واحد کمتر از واقعیت گزارش می‌کرد** (۴۹٪ در برابر ۶۹٪) چون فقط pytest را می‌شمرد و سوئیت‌های legacy را نه. | MAJOR | گیت بازنویسی شد تا کل سوئیت سرور را زیر یک session اندازه بگیرد؛ هدف ۵۵٪ فاز ۱ **محقق شده** (۶۹٪) |

**دو باگ flakiness هم در ابزار تست پیدا و رفع شد:**
- fixture زنجیره nonce را cache می‌کرد و با هر ارسال از همان حساب drift می‌کرد → «nonce too low» مبهم. حالا nonce هر تراکنش تازه خوانده می‌شود.
- تست تسویه از حساب‌های مشترک anvil استفاده می‌کرد و چون anvil بین اجراها state را نگه می‌دارد، موجودی‌ها انباشته می‌شدند و assertion دقیق تبدیل به heisenbug می‌شد. حالا هر تست هویت تازه می‌گیرد.

**درس فرآیندی (به R1 اضافه شد):** تست قرمز باید در یک **کامیت جداگانه قبل از fix** ثبت شود تا حالت قرمز از تاریخ git قابل بازتولید باشد. الان فقط C1 این‌طور است؛ C2/C3/C4 شاهد قرمزشان فقط در لاگ اجرا هست.


- [x] **C1 · 🔴** محدودکننده‌ی نرخ توزیع‌شده کاملاً مرده است
  `api/main.py:134-163` · **شاهد بازتولید:** روی emulator → `ValueError: Transaction not in progress`
  تغییر: (۱) `@transactional` + `txn.commit()` (۲) `except` باریک: فقط خطای گذرا → fallback (۳) شمارنده‌ی `rl_fallback_total` روی `/api/health`
  تست: `tests/integration/test_ratelimit_firestore.py::test_distributed_window_persists_across_instances` + `::test_limiter_does_not_silently_fall_back`
  پذیرش: سند `rate_limits` واقعاً افزایش یابد؛ با `_rl_window` پاک‌شده هم ۴۲۹ بدهد
- [x] **C2 · 🔴** `token_decimals()` خطای گذرا را برای همیشه `None` کش می‌کند
  `api/onchain.py:76-102` + `api/main.py:209-222`
  تغییر: (۱) TTL برای کش شکست مثل `_chain_ok` (۲) تفکیک «ناخوانا» از «ناهماهنگ» (۳) `verify_deposit` سه‌حالته `True/False/None`
  تست: `tests/unit/test_onchain_decimals.py::test_transient_failure_does_not_stick` + `::test_unreadable_decimals_refuses_round_without_voiding` + `::test_mismatched_stake_still_voids`
  پذیرش: بعد از شکست و سپس موفقیت RPC، gate کار کند؛ ماتچ void نشود
- [x] **C3 · 🔴** تراکنش‌های پول با provider اشتباه امضا می‌شوند
  `src/lib/realWeb3.ts:1020-1044`, `:1155-1170`
  تغییر: ذخیره‌ی provider فعال (یا `rdns`) در `setConnectedAddress`؛ `getActiveEip1193Provider` دقیقاً همان را برگرداند؛ resolve مجدد با rdns
  تست: `src/lib/realWeb3.provider.test.ts::test_active_provider_is_the_connected_one` + `::test_wc_zombie_does_not_shadow_injected`
  پذیرش: provider برگشتی همانی باشد که کاربر انتخاب کرده
- [x] **C4 · 🔴** تپ دوباره‌ی موبایل ماتچ را void می‌کند
  `src/pages/ReactionGamePage.tsx:1153-1154, 1472, 580-598, 612-623`
  تغییر: گارد سنکرون `verifyingRef.current` در ابتدای `processVerification`؛ پاک‌سازی در پایان راند؛ ادغام یکپارچه‌ی touch+click
  تست: `e2e/mobile-tap.spec.ts::test_single_tap_submits_exactly_once` + `::test_single_tap_never_voids_the_match`
  پذیرش: یک تپ = دقیقاً یک ارسال؛ ماتچ هرگز void نشود

---

# فاز ۲ — HIGH سرور (مسیر پول) 🟠
**هدف:** یکپارچگی داده و پایداری مسیر پول. **تخمین:** ۱.۵ روز
**🚦 گیت خروج:** ۹ تست رگرسیون سبز روی Firestore Emulator + `verify` سبز

- [x] **H3** ledger اقتصاد TOCTOU است، نه اتمیک — `api/economy.py:200-216, 243-273`
  تغییر: خواندن + `increment` داخل یک تراکنش keyed روی `settlementId`؛ یا سند `settlements/{id}` با `create()` به‌عنوان گیت اتمیک
  تست: `tests/integration/test_economy_idempotency.py::test_two_concurrent_settlements_count_once`
  پذیرش: `users.wins` دقیقاً ۱ افزایش
- [x] **H4** ledger داخل تراکنش commit‌نشده نوشته می‌شود — `api/main.py:623-643`
  تغییر: `record_settlement` از داخل `_mutate` بیرون، **بعد از** بازگشت موفق `store.update`
  تست: `tests/integration/test_settle_ledger_order.py::test_aborted_transaction_leaves_no_ledger_row`
  پذیرش: با abort تراکنش، هیچ رکورد ledger ثبت نشود
- [x] **H5** `settlement_id_for` با id تولیدی نمی‌خواند — `api/economy.py:188-198, 305-309`
  تغییر: تابع مشترک `_settlement_id(match_id, outcome, stake, settled_at, times)`
  تست: `tests/unit/test_economy_id.py::test_helper_matches_production_id` — **امروز قرمز است**
- [x] **H8** `sweep_expired` ماتچ کامل‌شده را void می‌کند — `api/store.py:226-230, 393-399`
  تغییر: قبل از void، اگر `match_completed(m)` یا داخل پنجره‌ی escrow → اول `_settle_once` (forfeit)
  تست: `tests/unit/test_sweep.py::test_completed_match_is_settled_not_voided` + `::test_active_match_past_play_expiry_still_settles_within_escrow_window`
- [x] **H9** sweep روی هر poll + ایندکس composite غایب — `api/main.py:532-535`, `api/store.py:376, 409-413, 447-453`
  تغییر: sweep به job زمان‌بندی‌شده؛ `firestore.indexes.json`؛ خطای ایندکس لاگ + health-counter
  تست: `tests/integration/test_sweep_cost.py::test_queue_poll_does_not_scan_collections`
  پذیرش: هر poll صف صفر collection scan
- [ ] **H10** I/O شبکه زیر قفل/تراکنش store — `api/main.py:581-645`, `api/store.py:210-218, 348-355`
  تغییر: `_verify_deposits_or_void` **قبل** از `store.update` (snapshot → `duel_info` → mutate)
  تست: `tests/integration/test_lock_no_io.py::test_slow_rpc_does_not_block_other_matches`
  پذیرش: ماتچ دوم در <۵۰۰ms پاسخ دهد
- [ ] **H22** endpoint logout وجود ندارد — `api/main.py` (جدید), `api/auth.py:224-254`
  تغییر: `POST /api/auth/logout` که `revoke_session(jti)` را صدا بزند
  تست: `tests/integration/test_auth_logout.py::test_revoked_token_is_rejected`
- [ ] **H6** پیکربندی production fail-open — `api/main.py:295-299`
  تغییر: پیش‌فرض برعکس — هر محیط production است مگر `PULSAR_ENV=dev` صریح
  تست: `tests/unit/test_config_gate.py::test_unknown_env_is_treated_as_production`
- [ ] **H7** bind دامنه‌ی SIWE از هدر Host — `api/main.py:434-438`
  تغییر: با escrow فعال `ALLOWED_DOMAIN` اجباری؛ در غیر این صورت `PUBLIC_HOST` ثابت
  تست: `tests/integration/test_siwe_domain.py::test_foreign_host_header_cannot_pick_the_domain`

---

# فاز ۳ — HIGH قرارداد 🟠
**هدف:** بستن مسیرهای از دست رفتن/گیر کردن پول. **تخمین:** ۱.۵ روز · **وابستگی:** فاز ۰ (Anvil)
**⚠️ R6:** هر تغییر → تست Foundry + ABI کلاینت + پین parity
**🚦 گیت خروج:** `forge test` ≥۳۳ تست سبز + تست‌های جدید روی anvil + ABI به‌روز

### ۳.۱ — رفع باگ‌ها
- [ ] **H17** انتقال‌های all-or-nothing پول را برای همیشه گیر می‌کنند — `PulsarEscrow.sol:310-313, 327, 331-332`
  تغییر: pull-payment (`pendingWithdrawals[addr]` + `withdraw()`) یا جداسازی هر انتقال با credit قابل‌برداشت
  تست: `test_reverting_recipient_does_not_block_the_other` + `test_blacklisting_token_does_not_freeze_the_pool`
  پذیرش: با گیرنده‌ی revert‌کننده، طرف مقابل پولش را بگیرد
- [ ] **H18** سقف on-chain برای `proof.deadline` — `PulsarEscrow.sol:267`
  تغییر: `require(proof.deadline <= duel.createdAt + MATCH_TIMEOUT, "deadline exceeds horizon");`
  تست: `test_RevertWhen_DeadlineBeyondRefundHorizon`
- [ ] **H19** refund بدون مجوز برنده را بی‌جایزه می‌کند — `PulsarEscrow.sol:318-335` · **🛑 نیاز به D2**
  گزینه‌ها: (الف) پنجره‌ی تسویه‌ی انحصاری (ب) refund نامتقارن با جریمه‌ی رهاکننده (ج) `settleOnTimeout(proof)`
  تست: `test_LosingPlayerCannotRefundAwayTheWinnerPrize`
- [ ] **H20** `joinDuel` بدون cutoff و بدون activation — `PulsarEscrow.sol:240-255`
  تغییر: `activatedAt` در join؛ لنگر refund روی `max(createdAt, activatedAt)`؛ رد join بعد از horizon
  تست: `test_JoinAtT29m59s_RefundWindowStartsAtActivation` + `test_JoinAfterHorizon_Reverts`
- [ ] **M22** `MIN_STAKE_UNITS` اعشار ۶ را hardcode می‌کند — `PulsarEscrow.sol:146`
  تغییر: خواندن `decimals()` در constructor؛ `MIN_STAKE_UNITS = 10**decimals`
  تست: `test_MinStakeFollowsTokenDecimals` (با MockUSDT ۱۸-اعشاری)
- [ ] **M23** رویداد `MatchCreated` مقدار جعلی emit می‌کند — `PulsarEscrow.sol:237`
  تغییر: `totalPool: 0` (هم‌خوان با storage) · تست: `test_Event_MatchCreated_TotalPoolIsZero`
- [ ] **M24** `setTreasuryWallet`/`setOracleSigner` یک‌مرحله‌ای و بدون timelock — `PulsarEscrow.sol:337-349`
  تغییر: دو-مرحله‌ای + timelock برای oracle · تست: `test_OracleRotationRequiresTimelock` + `test_TreasuryRotationIsTwoStep`
- [ ] **M25** `usedSignatures` دفاع مرده — `PulsarEscrow.sol:185, 290-291` · **🛑 نیاز به D3**
  یا حذف، یا اصلاح کامنت/تست تا ادعای بیش‌ازواقع نباشد

### ۳.۲ — گپ‌های تست قرارداد (۱۲ مورد)
- [ ] **CT1** Mock USDT بدون bool-return + Mock با `false` + fee-on-transfer + reentrant + blacklisting
- [ ] **CT2** تست reentrancy با توکن خصمانه
- [ ] **CT3** تست واقعی replay (`usedSignatures`) — تست فعلی tautological است
- [ ] **CT4** تست griefing refund بی‌مجوز (H19)
- [ ] **CT5** تست cross-chain / cross-contract (دو escrow، fork chainid)
- [ ] **CT6** تست tampered proof (تغییر winner/time/nonce بعد از امضا)
- [ ] **CT7** تست‌های مرزی: `deadline == now`، `length != 65`، `v ∉ {27,28}`
- [ ] **CT8** تست `setTreasuryWallet` + گاردهای zero-address
- [ ] **CT9** assert رویدادها با `vm.expectEmit`
- [ ] **CT10** تست stuck-funds / گیرنده‌ی revert‌کننده / توکن pause‌شده
- [ ] **CT11** تست اعشار (M22)
- [ ] **CT12** تست‌های cross-state: refund بعد از settle، settle بعد از refund، refund روی None، join بعد از Active
- [ ] **CT13** `forge coverage` + invariant tests (`invariant_*`)
- [ ] **CT14** fuzz runs 256 → ۱۰k در nightly

---

# فاز ۴ — HIGH کلاینت 🟠
**هدف:** پایداری و صداقت داده در کلاینت. **تخمین:** ۲ روز · **وابستگی:** فاز ۱
**🚦 گیت خروج:** Vitest + Playwright سبز + `verify` سبز

- [ ] **H11** مسیر بازیابی بعد از refresh یک no-op است — `ReactionGamePage.tsx:461-499`
  تغییر: `serverMatch`/`serverSession` در ref؛ `finishServerMatch` از ref بخواند
  تست: `e2e/refresh-recovery.spec.ts::test_reload_after_decided_match_still_settles`
- [ ] **H12** موجودی واقعی با `vaultBalance` صفر بازنویسی می‌شود — `realWeb3.ts:1296-1303`
  تغییر: `balanceUSDT` هرگز از `vaultBalance` نوشته نشود؛ `balanceUnknown` دست‌نخورده
  تست: `src/lib/realWeb3.balance.test.ts::test_profile_save_does_not_zero_the_chain_balance`
- [ ] **H13** اعشار توکن در نوشتن hardcode است — `chain.ts:51`, `escrowFlow.ts:133,145`, `ReactionGamePage.tsx:314`
  تغییر: خواندن `decimals()` یک‌بار + cache per-token؛ همه‌ی `parseUnits` و مقایسه‌ها از آن
  تست: `src/lib/escrowFlow.decimals.test.ts::test_stake_uses_onchain_decimals`
- [ ] **H14** race تعویض حساب داده‌ی کاربر دیگر را نشان می‌دهد — `usePulsarStore.ts:56-71`
  تغییر: capture آدرس در closure؛ اعمال نتیجه فقط اگر `account.address === captured && connected`؛ generation counter
  تست: `src/store/usePulsarStore.race.test.ts::test_stale_load_is_dropped`
- [ ] **H15** قفل حساب/شبکه در حین ماتچ فعال — `realWeb3.ts:189-199`
  تغییر: هشدار + بلاک تعویض حساب/شبکه در حین ماتچ؛ `chainChanged` reload نکند
  تست: `e2e/account-switch-midmatch.spec.ts`
- [ ] **M5** state تسویه روی rematch پاک نمی‌شود — `ReactionGamePage.tsx:1114-1128`
  تغییر: ریست `onchainAction`/`settlementTxHash`/`lastProof`/`serverMatch`/`serverSession`
  تست: `e2e/rematch.spec.ts::test_rematch_clears_previous_tx_link`
- [ ] **M28** (همان M5 — ادغام شد)
- [ ] **M29** `setInterval`/`setTimeout` بدون cleanup — `ReactionGamePage.tsx:874-876, 576-579`
  تغییر: نگه‌داری در ref + پاک‌سازی در unmount و قبل از فاز جدید
  تست: `src/pages/ReactionGamePage.timers.test.ts::test_no_state_update_after_unmount`
- [ ] **M30** `useSyncExternalStore` با subscribe اینلاین — `usePulsarStore.ts:318-322`
  تغییر: `subscribe` به module scope · تست: `::test_subscribe_identity_is_stable`
- [ ] **M38** `matchIdToBytes32` به `crypto.subtle` نیاز دارد — `gameServerClient.ts:314-320`
  تغییر: feature-check + خطای صادقانه یا fallback SHA-256
  تست: `src/lib/gameServerClient.test.ts::test_clear_error_without_secure_context`

---

# فاز ۵ — انصاف و یکپارچگی ⚖️ 🛑 نیاز به D1
**هدف:** رفع نقص‌های طراحی که باگ نیستند ولی محصول را غیرقابل‌اعتماد می‌کنند. **تخمین:** ۳-۵ روز
**🛑 گیت ورود:** انتخاب مسیر محصول (A/B/C/D) — طراحی این فاز کاملاً به آن وابسته است

- [ ] **H1** برنده با latency شبکه تعیین می‌شود — `match_engine.py:419-422, 468-482`
  گزینه‌ها: (الف) رتبه روی claim محدودشده توسط observed (ب) تخمین RTT + جبران (ج) سقف پینگ + سرور منطقه‌ای
  تست: `tests/unit/test_fairness.py::test_equal_reaction_different_latency_is_a_tie`
- [ ] **H2** commitment واقعی — `match_engine.py:329-346, 322-326`
  تغییر: salt سرور در لحظه‌ی commit + گنجاندن در `_result_proof`؛ یک commit در هر (match, round, player)
  تست: `tests/unit/test_commit_binding.py::test_recommit_after_window_is_rejected`
- [ ] **H16** ضد-تقلب واقعی — `ReactionGamePage.tsx:170-192`, `antiCheat.ts:118-134, 220-229`
  حداقل: حذف ادعاهای جعلی از UI · حداکثر: device attestation + anomaly detection سمت سرور
  تست: `tests/unit/test_anticheat_honesty.py::test_no_fabricated_verification_claims`
- [ ] **H24** رها کردن مسابقه یک آپشن رایگان است (کشف‌شده در فاز ۰) — `match_engine.py:589-617`
  مشکل: راندی که هیچ‌کدام نتیجه نداده‌اند به کسی تعلق نمی‌گیرد → بازیکنی که ۱ راند بازی کرده و منتظر مانده، ۱-۰ می‌شود → بدون اکثریت → void → هر دو refund
  تست پایه (قرمز): `tests/unit/test_engine_protocol.py::test_grace_window_voids_when_neither_side_reaches_a_majority`
  اصلاح (نیاز تصمیم): forfeit به نفع طرف فعال، یا جریمه‌ی رهاکننده (هم‌راستا با H19)
- [ ] **H23 · G5** matchmaking مهارت‌محور + rating — `match_engine.py` (queue), `store.py`
  تغییر: Glicko/ELO روی `observed_ms` معتبر؛ جفت‌سازی در باند confidence
  تست: `tests/unit/test_matchmaking_rating.py::test_players_are_paired_within_rating_band`

---

# فاز ۶ — عملیات و پیکربندی 🛠️
**هدف:** قابل‌بهره‌برداری و قابل‌پایش کردن. **تخمین:** ۲ روز · **وابستگی:** فاز ۲
**🚦 گیت خروج:** `/api/health` کامل + داشبورد + runbook نوشته‌شده

- [ ] **6.1 · G10** metrics + alerting (readهای Firestore، latency هر endpoint، نرخ fallback limiter، نرخ شکست امضا)
- [ ] **6.2** گسترش `/api/health`: وضعیت RPC، decimals، ledger، sweep
- [ ] **6.3 · G9** admin tooling: inspect ماتچ، force-settle، force-void، جستجوی بازیکن
- [ ] **6.4 · G8** مسیر dispute/support: گزارش ماتچ توسط کاربر
- [ ] **6.5** `firestore.indexes.json` + مستند ایندکس‌های لازم
- [ ] **6.6** runbook حادثه (RPC down، Firestore down، oracle key compromise، stuck funds)
- [ ] **6.7 · L9** `.env.example` کامل (۸+ متغیر غایب)
- [ ] **6.8** `pip-compile` + `requirements.lock` (ریسک reproducibility)
- [ ] **6.9** M15/M16/M17: محدود کردن `onchain._cache`، پاک‌سازی `_rl_window`، قفل روی ست‌های auth
- [ ] **6.10** M12/M13/M18: حذف leak آدرس در `username_lookup`، حذف متن استثنا، quorum/fallback برای RPC
- [ ] **6.11 · G16** نسخه‌بندی/مهاجرت اسناد Firestore

---

# فاز ۷ — MEDIUM (۳۹ مورد باقی‌مانده) 📋
**تخمین:** ۳ روز · **وابستگی:** فاز ۲-۴

### ۷.۱ — امنیت و اعتبارسنجی
- [ ] **M1** `verify_siwe` آدرس بازیابی‌شده را با ادعاشده مقایسه کند — `auth.py:338-352`
- [ ] **M2** `_burn_nonce` فقط `AlreadyExists` را replay بداند؛ TTL واقعی — `auth.py:186-204`
- [ ] **M3** پنجره‌ی nonce: پذیرش پنجره‌ی قبلی برای ۳۰s (رفع fail تصادفی) — `auth.py:137-143`
- [ ] **M4** eviction در `_remember_used` از O(n) به O(1) — `auth.py:213-221`
- [ ] **M5** `verify_session` نوع payload را اعتبارسنجی کند — `auth.py:373-382`
- [ ] **M6** `_signature_to_low_s_bytes` برای `v∈{27,28}` + تست high-s — `oracle.py:79-82`
- [ ] **M7** `sign_settlement` منبع رکورد را اعتبارسنجی کند (HMAC engine-marker) — `oracle.py:175-242`
- [ ] **M8** cache کردن signer — `oracle.py:227,239`
- [ ] **M9** `_settle_once` بدون پرتاب HTTPException داخل mutate — `main.py:718-721`
- [ ] **M10** `match_view` بعد از finalize دوباره get کند — `main.py:556-560`
- [ ] **M11** `claim_match` نیاز به برنده بودن claimer + چک `receipt.from` — `main.py:838-851`
- [ ] **M14** `queue` با استیک متفاوت را رد کند — `store.py:270-277`
- [ ] **M19** `oracle._match_id_bytes32` روی id غیر-hex ۶۴ کاراکتری crash می‌کند — `oracle.py:124-130`
- [ ] **M20** حذف override `PLATFORM_FEE_BPS` از env — `economy.py:88-93`
- [ ] **M21** محاسبه‌ی prize با `Decimal` و واحد پایه — `economy.py:180`

### ۷.۲ — کلاینت
- [ ] **M26** `searchPlayers` با playerId — `realWeb3.ts:1444-1491`
- [ ] **M27** «چالش دوست» واقعی یا تغییر برچسب — `FriendChallengeModal.tsx:124-128`
- [ ] **M31** progression از ledger سرور — `usePulsarStore.ts:186-235`
- [ ] **M32** حذف داده‌ی ساختگی روی سطوح پولی (به فاز ۹ منتقل شد — ادغام)
- [ ] **M33** یک منبع حقیقت برای `isEscrowConfigured` — `chain.ts:117-119` vs `escrowFlow.ts:20-40`
- [ ] **M34** نام شبکه/توکن از `CHAIN`/`TOKENS` — `ConnectWallet.tsx:566,568,787,795`
- [ ] **M35** پاک کردن URI کهنه‌ی WC + یکسان‌سازی آستانه‌ها — `ConnectWallet.tsx:323-339`
- [ ] **M36** `disconnect()` در cancel + حلقه‌ی معکوس purge — `realWeb3.ts:900-916, 431-438`
- [ ] **M37** هر دو طرف بتوانند تسویه را اجبار کنند — `ReactionGamePage.tsx:748-761`
- [ ] **M39** پر کردن `match.hash` تا گواهی واقعی شود — `DuelCertificateModal.tsx:134-142`
- [ ] **M40** `EligibilityGate` فقط کلاینت است — `EligibilityGate.tsx:14,49`
- [ ] **M41** گاز floor ۳۰ gwei روی همه‌ی شبکه‌ها — `escrowFlow.ts:98-111`
- [ ] **M42** `subscribeGlobalMatches` پاک‌سازی ورودی‌های کهنه — `realWeb3.ts:1349-1386`
- [ ] **M43** `LanguageContext` بدون رجکس/replacement string — `LanguageContext.tsx:81-83`
- [ ] **M44** Sentry lazy load — `monitoring.ts:14`
- [ ] **M45** معکوس دقیق `getLevel`/`getXPForLevel` — `xpSystem.ts:71-80`

---

# فاز ۸ — LOW + دسترس‌پذیری + i18n ♿
**تخمین:** ۲ روز · **وابستگی:** فاز ۴
**🚦 گیت خروج:** axe صفر خطای critical/serious + تست keyboard-only سبز + snapshot RTL

- [ ] **8.1 · L1** حذف `maximum-scale=1, user-scalable=no` (WCAG 1.4.4) — `index.html:5`
- [ ] **8.2 · L2** `lang` داینامیک بر اساس زبان انتخاب‌شده — `index.html:2`
- [ ] **8.3 · L3** دکمه‌های غیر-`<button>` → عناصر معنایی با keyboard (۴ مورد)
- [ ] **8.4 · L4** `role="dialog"` + `aria-modal` + focus-trap + Escape برای ۴ مودال
- [ ] **8.5 · L5** `aria-label` برای همه‌ی آیکون-باتن‌ها
- [ ] **8.6 · L6** `LanguageSelector` با `aria-expanded`/`aria-haspopup` + ناوبری کلید
- [ ] **8.7** `<label>` برای input جستجو — `FriendChallengeModal.tsx:273-279`
- [ ] **8.8** live-region برای بازخوردهای motion-only
- [ ] **8.9 · L7** i18n: انتقال همه‌ی متن‌های hardcoded به `translations.ts`
- [ ] **8.10** RTL: حذف `dir="ltr"` از پنل‌های دارای متن ترجمه‌شده
- [ ] **8.11** بازی فقط با کیبورد (هدف با Enter/Space فعال شود)
- [ ] **8.12** `prefers-reduced-motion` رعایت شود
- [ ] **8.13** axe: صفر خطای critical/serious
- [ ] **8.14 · L8** `ClaimRequest.signature` نادیده گرفته می‌شود — حذف یا استفاده
- [ ] **8.15 · L10** `_finalize_if_due`/`_resign` استثناها را می‌بلعند — لاگ + health
- [ ] **8.16 · L11** `vite.config.ts:19` `allowedHosts: true` — محدود شود
- [ ] **8.17 · L12** `Deploy.s.sol:27` فقط chain 137 را بلاک می‌کند
- [ ] **8.18 · L13** `compile_check.js` تست‌ها را کامپایل نمی‌کند
- [ ] **8.19 · L14** حذف کد مرده (۱۵ مورد)
- [ ] **8.20 · L15** یکسان‌سازی منطق تکراری (ریاضی جایزه در ۹ جا، WC accounts در ۵ جا، Bo3 در ۵ جا)
- [ ] **8.21 · L16** ESLint + ruff + mypy در CI
- [ ] **8.22 · L17** fuzz runs افزایش (به CT14 منتقل شد — ادغام)

---

# فاز ۹ — صداقت UI 🎭
**تخمین:** ۱ روز · **وابستگی:** فاز ۸
**🚦 گیت خروج:** تست CI که هر `Math.random()` روی سطح پولی را رد کند

- [ ] **9.1 · M32** حذف آدرس‌های تصادفی leaderboard — `realWeb3.ts:1405`
- [ ] **9.2 · M32** حذف fallbackهای ساختگی 180ms/185ms — `DashboardPage.tsx:610,671`, `LobbyPage.tsx:450`
- [ ] **9.3 · M32** حذف «network latency» تصادفی — `AppHeader.tsx:28-36`
- [ ] **9.4 · M32** حذف استفاده از history کاربر به‌عنوان «LIVE arena feed» — `LobbyPage.tsx:430`
- [ ] **9.5 · H16** حذف/تغییر برچسب ادعاهای verification جعلی
- [ ] **9.6 · M39** گواهی: نمایش tx hash و امضای واقعی oracle
- [ ] **9.7** تست گیت «بدون داده‌ی ساختگی» در CI
- [ ] **9.8** بازنویسی README و DEPLOYMENT برای هم‌خوانی با واقعیت

---

# فاز ۱۰ — E2E، Load و Chaos 🧪
**تخمین:** ۳ روز · **وابستگی:** فاز ۹

### ۱۰.۱ — E2E کامل (Playwright)
- [ ] دسکتاپ: connect → queue → create → join → ۳ راند → settle → claim → گواهی با tx واقعی
- [ ] موبایل: همان مسیر با viewport لمسی (regression C4)
- [ ] refresh در میانه‌ی ماتچ → resume
- [ ] refresh بعد از تسویه → auto-settle (H11)
- [ ] رد کردن تراکنش در هر مرحله
- [ ] شکست RPC در هر مرحله
- [ ] refund بعد از تایم‌اوت
- [ ] تعویض حساب/شبکه در حین ماتچ (H15)

### ۱۰.۲ — Visual regression
- [ ] spawn هدف، انتقال راند، صفحه‌ی نتیجه
- [ ] چیدمان RTL (fa/ar) در ۳ breakpoint
- [ ] تم روشن/تیره

### ۱۰.۳ — Load
- [ ] k6/Locust: ۱۰۰۰ poller هم‌زمان روی `/api/queue`
- [ ] اندازه‌گیری read فایرستور به‌ازای هر ماتچ (هدف: <۲۰)
- [ ] latency p50/p95/p99 هر endpoint
- [ ] گزارش هزینه‌ی تخمینی در مقیاس

### ۱۰.۴ — Chaos
- [ ] کشتن RPC در میانه‌ی راند
- [ ] کشتن Firestore در میانه‌ی تراکنش
- [ ] split کردن replica (دو instance)
- [ ] تزریق تأخیر ۵s RPC (اثبات H10)
- [ ] soak ۲۴ ساعته: رشد حافظه

---

# فاز ۱۱ — دروازه‌های انتشار 🚀
**وابستگی:** همه‌ی فازها · **تصمیم نهایی با شما**

### ۱۱.۱ — گیت فنی
- [ ] `bun run verify` سبز
- [ ] coverage: سرور ≥۸۰٪، موتور ≥۹۰٪، قرارداد ≥۹۵٪
- [ ] `forge coverage` + invariant سبز
- [ ] صفر خطای critical/serious در axe
- [ ] صفر یافته‌ی CRITICAL/HIGH باز
- [ ] **ممیزی قرارداد توسط یک شرکت واقعی (نه AI)**
- [ ] pen-test روی API

### ۱۱.۲ — گیت عملیاتی
- [ ] metrics + alerting فعال
- [ ] runbook تمرین‌شده
- [ ] backup/restore Firestore تست‌شده
- [ ] rollback plan تست‌شده (`VITE_ESCROW_ADDRESS` unset)
- [ ] on-call مشخص

### ۱۱.۳ — گیت محصول و حقوقی (تصمیم شما)
- [ ] **G1** KYC/AML
- [ ] **G2** age-gate سمت سرور
- [ ] **G3** ابزار مسئولانه‌بازی (deposit limit، self-exclusion، cool-off)
- [ ] **G4** geo-blocking در لبه (CDN/server)
- [ ] **G6** سیستم ban/velocity limit
- [ ] **G11** settlement log عمومی + انتشار آدرس oracle
- [ ] **G12** fiat on-ramp
- [ ] **G13** growth loop (referral/season/tournament)
- [ ] **G14** progression معنادار
- [ ] **G15** PWA/native
- [ ] **G17** analytics
- [ ] نهاد حقوقی + حوزه‌ی قضایی + مجوز (اگر مسیر D)
- [ ] ToS/Privacy/Risk Disclosure با وکیل

### ۱۱.۴ — rehearsal نهایی روی Amoy
- [ ] approve → createDuel → joinDuel → بازی → settleDuel
- [ ] تأیید ۹۸٪ برنده و ۲٪ treasury
- [ ] `refundTimeoutMatch` بعد از ۳۰ دقیقه
- [ ] با کیف پول واقعی و پول تستی

---

## پیوست A — نقشه‌ی فایل‌های جدید

```
api/requirements-dev.txt          pytest.ini                vitest.config.ts
firestore.indexes.json            scripts/verify.sh         scripts/start_emulator.sh
scripts/start_anvil.sh            tests/conftest.py         tests/fixtures/{fake_rpc,chain,firestore}.py
tests/unit/*.py                   tests/integration/*.py    tests/adversarial/*.py
e2e/*.spec.ts                     e2e/fixtures/mockWallet.ts
src/**/*.test.ts(x)
contracts/test/mocks/{NoBoolUSDT,FalseUSDT,FeeOnTransfer,Reentrant,Blacklisting}.sol
docs/plans/MASTER-PLAN.md  ← همین فایل
```

## پیوست B — ترتیب و تخمین

| فاز | محتوا | آیتم | تخمین | گیت |
|---|---|---|---|---|
| ۰ | دروازه‌ها | ۱۳ | ۱ روز | `verify` + CI سبز |
| ۱ | CRITICAL | ۴ | ۱ روز | ۴ تست قرمز→سبز |
| ۲ | HIGH سرور | ۹ | ۱.۵ روز | ۹ تست |
| ۳ | HIGH قرارداد | ۲۲ | ۱.۵ روز | forge ≥۳۳ تست |
| ۴ | HIGH کلاینت | ۹ | ۲ روز | Vitest + Playwright |
| ۵ | انصاف (D1) | ۴ | ۳-۵ روز | تست انصاف |
| ۶ | عملیات | ۱۱ | ۲ روز | health + runbook |
| ۷ | MEDIUM | ۳۱ | ۳ روز | تست هر مورد |
| ۸ | LOW + a11y | ۲۲ | ۲ روز | axe صفر |
| ۹ | صداقت UI | ۸ | ۱ روز | تست ضد-ساختگی |
| ۱۰ | E2E/Load/Chaos | ۲۱ | ۳ روز | گزارش load |
| ۱۱ | انتشار | ۲۴ | — | همه‌ی گیت‌ها |
| | **جمع** | **~۱۷۸** | **~۲۲ روز کاری** | |

## پیوست C — ریسک‌ها

| ریسک | اثر | کاهش |
|---|---|---|
| دیسک ۹.۸G | نصب‌ها شکست می‌خورد | پاک‌سازی دوره‌ای کش؛ ابزار سنگین یکی‌یکی |
| تغییر قرارداد → ABI کلاینت | شکستن کلاینت | R6 |
| فاز ۵ منتظر D1 | بلاک شدن | تا فاز ۴ جلو می‌رویم |
| emulator ≠ production | رفتار ایندکس متفاوت | rehearsal فاز ۱۱ |
| تست‌های موجود بعد از fix می‌شکنند | کار اضافه | هر فاز: اول تست‌های موجود همان ماژول |
| یافته‌ی جدید در حین کار | تغییر scope | پروتکل تغییر: bump نسخه + تأیید شما |

## پیوست D — تصمیم‌های لازم

| # | تصمیم | کِی | وضعیت |
|---|---|---|---|
| **D1** | مسیر محصول: A free-to-play / B B2B SDK / C بنچمارک / D پول واقعی مجوزدار | قبل از فاز ۵ | ⬜ باز |
| **D2** | H19: پنجره‌ی انحصاری / refund نامتقارن / `settleOnTimeout` | فاز ۳ | ⬜ باز |
| **D3** | M25: حذف `usedSignatures` یا اصلاح کامنت | فاز ۳ | ⬜ باز |
| **D4** | کامیت `docs/audit/` و `docs/plans/` | همین حالا | ⬜ باز |
| **D5** | شروع از فاز ۰ | همین حالا | ✅ تأیید شد |

## پیوست E — ماتریس ردیابی (هر یافته → آیتم پلن)

| یافته | آیتم | یافته | آیتم | یافته | آیتم |
|---|---|---|---|---|---|
| C1 | ۱ | M1 | ۷.۱ | M31 | ۷.۲ |
| C2 | ۱ | M2 | ۷.۱ | M32 | ۹.۱-۹.۴ |
| C3 | ۱ | M3 | ۷.۱ | M33 | ۷.۲ |
| C4 | ۱ | M4 | ۷.۱ | M34 | ۷.۲ |
| H1 | ۵ | M5 | ۷.۱ | M35 | ۷.۲ |
| H2 | ۵ | M6 | ۷.۱ | M36 | ۷.۲ |
| H3 | ۲ | M7 | ۷.۱ | M37 | ۷.۲ |
| H4 | ۲ | M8 | ۷.۱ | M38 | ۴ |
| H5 | ۲ | M9 | ۷.۱ | M39 | ۷.۲ + ۹.۶ |
| H6 | ۲ | M10 | ۷.۱ | M40 | ۷.۲ |
| H7 | ۲ | M11 | ۷.۱ | M41 | ۷.۲ |
| H8 | ۲ | M12 | ۶.۱۰ | M42 | ۷.۲ |
| H9 | ۲ | M13 | ۶.۱۰ | M43 | ۷.۲ |
| H10 | ۲ | M14 | ۷.۱ | M44 | ۷.۲ |
| H11 | ۴ | M15 | ۶.۹ | M45 | ۷.۲ |
| H12 | ۴ | M16 | ۶.۹ | L1 | ۸.۱ |
| H13 | ۴ | M17 | ۶.۹ | L2 | ۸.۲ |
| H14 | ۴ | M18 | ۶.۱۰ | L3 | ۸.۳ |
| H15 | ۴ | M19 | ۷.۱ | L4 | ۸.۴ |
| H16 | ۵ + ۹.۵ | M20 | ۷.۱ | L5 | ۸.۵ |
| H17 | ۳ | M21 | ۷.۱ | L6 | ۸.۶ |
| H18 | ۳ | M22 | ۳ | L7 | ۸.۹ |
| H19 | ۳ (D2) | M23 | ۳ | L8 | ۸.۱۴ |
| H20 | ۳ | M24 | ۳ | L9 | ۶.۷ |
| H21=CI-1 | ۰.۱ | M25 | ۳ (D3) | L10 | ۸.۱۵ |
| H22 | ۲ | M26 | ۷.۲ | L11 | ۸.۱۶ |
| H23 | ۵ | M27 | ۷.۲ | L12 | ۸.۱۷ |
| H24 | ۵ | | | | |
| G1-G4 | ۱۱.۳ | M28 | ۴ | L13 | ۸.۱۸ |
| G5 | ۵ | M29 | ۴ | L14 | ۸.۱۹ |
| G6 | ۱۱.۳ | M30 | ۴ | L15 | ۸.۲۰ |
| G7 | ۲ (H22) | | | L16 | ۸.۲۱ |
| G8-G10 | ۶ | | | L17 | ۳ (CT14) |
| G11-G17 | ۱۱.۳ | | | | |

**پوشش: ۱۰۹/۱۰۹ یافته → آیتم پلن. صفر یافته‌ی بی‌آیتم.**

## CHANGELOG

| نسخه | تاریخ | تغییر | تأیید |
|---|---|---|---|
| 1.0-LOCKED | 2026-10-12 | نسخه‌ی اول، قفل‌شده | ⬜ |
| 1.1-LOCKED | 2026-10-12 | **H24 اضافه شد** (کشف‌شده در فاز ۰: رها کردن مسابقه آپشن رایگان است). دامنه ۱۰۸ → ۱۰۹ یافته. آیتم‌های 0.1/0.2/0.4 تیک خوردند. | ⬜ |
| 1.2-LOCKED | 2026-10-12 | آیتم‌های 0.5 و 0.6 تیک خوردند. | ⬜ |
| 1.3-LOCKED | 2026-10-12 | آیتم 0.8 تیک خورد (Anvil + escrow + تست تسویه واقعی). 0.9–0.11 طبق توافق به فاز ۴ موکول شد. | ⬜ |
| 1.4-LOCKED | 2026-10-12 | آیتم‌های 0.12 و 0.13 تیک خوردند. **فاز ۰ به‌جز 0.3 (مهاجرت کامل legacy) و 0.9–0.11 (موکول به فاز ۴) بسته شد.** | ⬜ |
| 2.3 | 2026-10-12 | H9 رفع شد (throttle روی sweep + ایندکس composite + شکست‌ها دیگر بی‌صدا نیستند). coverage ۷۷٪ (کاهش ۷۸→۷۷ به‌دلیل ایزوله‌شدن درست تست H4، نه regression). **فاز ۲: ۵/۹** | ⬜ |
| 2.2 | 2026-10-12 | H5 و H8 رفع شدند. coverage ۷۷ → ۷۸٪. | ⬜ |
| 2.1 | 2026-10-12 | H4 رفع شد (ledger بعد از commit تراکنش؛ همان باگ در `_settle_once` هم بود). coverage ۷۲ → ۷۷٪. fixture زنجیره در برابر فرستنده‌های همزمان مقاوم شد. | ⬜ |
| 2.0 | 2026-10-12 | **فاز ۲ شروع شد.** H3 رفع شد (گیت idempotency اتمیک شد؛ کامیت قرمز جدا قبل از fix طبق R1). coverage ۶۹ → ۷۲٪. | ⬜ |
| 1.8-CLOSED | 2026-10-12 | **فاز ۱ رسماً بسته شد.** بازبینی بستن ۳ شکاف MAJOR پیدا کرد (C3 نیمه‌کاره، زامبی WC، گیت coverage اشتباه) — همه رفع شدند. هدف coverage فاز ۱ محقق شد (۶۹٪). R1 با قاعده‌ی «کامیت قرمز اول» تقویت شد. | ⬜ |
| 1.7-LOCKED | 2026-10-12 | **C4** تیک خورد. **فاز ۱ کامل شد: هر ۴ CRITICAL رفع و با تست قرمز→سبز اثبات شدند.** تست C4 با RTL به‌جای Playwright (دقیق‌تر و سریع‌تر)؛ 0.10 برای فاز ۱۰ باقی است. | ⬜ |
| 1.6-LOCKED | 2026-10-12 | آیتم 0.9 (Vitest) و **C3** تیک خوردند. `bindActiveProvider()` در هر ۴ مسیر اتصال + disconnect صدا زده می‌شود. | ⬜ |
| 1.5-LOCKED | 2026-10-12 | **C1 و C2 رفع شدند** (تست‌های قرمز → سبز). یافته‌ی جدید در حین رفع C2: `token_decimals()` هر مقدار ۳۲-بایتی را می‌پذیرفت → `Decimal(10) ** 3.7e9` → Overflow → 500 روی مسیر پول. با سقف uint8 (۲۵۵) و tri-state verdict رفع شد. | ⬜ |
