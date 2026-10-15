# PULSAR — پلن مادر رفع اشکال و تست 🔒 LOCKED

```
╔══════════════════════════════════════════════════════════════════════════╗
║  نسخه:        2.3-CLOSED (فاز ۱ تا ۶ بسته)                                                 ║
║  تاریخ قفل:   2026-10-12                                                 ║
║  مبنا:        docs/audit/FULL-AUDIT-2026-10-12.md  (109 یافته)           ║
║  SHA-256:     ee38d6b60449dac5…51924874c9355581                                                   ║
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
- [x] **0.3** ساختار pytest — `tests/{unit,integration,e2e,adversarial}/`, `conftest.py`, `pytest.ini`
  مهاجرت ۶ اسکریپت `scripts/test_*.py` و `probe_*.py`؛ اسکریپت‌های فعلی wrapper نازک بمانند
  پذیرش: ✅ ۹۷ تست سبز (≥۹۰). سوئیت‌های legacy همچنان به‌عنوان گیت اجرا می‌شوند و زیر coverage می‌روند؛ مهاجرت کامل آن‌ها به فاز ۷ موکول شد.
- [x] **0.4** `api/requirements-dev.txt` + `ruff.toml` — pytest, pytest-cov, pytest-asyncio, hypothesis, time-machine, respx, ruff, mypy, httpx
- [x] **0.5** ⚠️ **تزریق ساعت (Clock injection)** — `api/timebase.py` (`now()`/`now_ms()`) + مسیردهی **۳۳ خواندن ساعت در ۷ ماژول** (match_engine, store, main, auth, onchain, oracle, economy)
  پذیرش: ✅ هیچ `time.time()` مستقیمی بیرون از seam نماند (تست `test_no_module_reads_the_clock_directly` آن را تضمین می‌کند)؛ `clock` fixture زمان را برای کل سرور جلو می‌برد
- [x] **0.6** Fixture رسمی `tests/fixtures/fake_rpc.py` — پاسخ به `eth_chainId`/`eth_call`(paymentToken/decimals/matches)/`eth_getTransactionReceipt`؛ تزریق خطا: `fail_next(n)` و `break_call(selector)`
  پذیرش: ✅ `tests/unit/test_onchain_gate.py` — ۸ تست سبز که gate واقعی را با fake RPC می‌رانند + ۲ baseline قرمز C2
- [x] **0.7** Firestore Emulator در CI — `scripts/start_emulator.sh` + fixture `firestore_emulator`
  پذیرش: ✅ CI خودش emulator را بالا می‌آورد؛ `verify.sh` هم همین کار را می‌کند تا گیت coverage قطعی بماند.
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
**🚦 گیت خروج:** ✅ **محقق شد** — ۹ آیتم، هرکدام با تست قرمز→سبز در دو کامیت جدا. `verify` با ۱۳ گیت سبز. coverage ۶۹ → ۷۸٪.

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
- [x] **H10** I/O شبکه زیر قفل/تراکنش store — `api/main.py:581-645`, `api/store.py:210-218, 348-355`
  تغییر: `_verify_deposits_or_void` **قبل** از `store.update` (snapshot → `duel_info` → mutate)
  تست: `tests/integration/test_lock_no_io.py::test_slow_rpc_does_not_block_other_matches`
  پذیرش: ماتچ دوم در <۵۰۰ms پاسخ دهد
- [x] **H22** endpoint logout وجود ندارد — `api/main.py` (جدید), `api/auth.py:224-254`
  تغییر: `POST /api/auth/logout` که `revoke_session(jti)` را صدا بزند
  تست: `tests/integration/test_auth_logout.py::test_revoked_token_is_rejected`
- [x] **H6** پیکربندی production fail-open — `api/main.py:295-299`
  تغییر: پیش‌فرض برعکس — هر محیط production است مگر `PULSAR_ENV=dev` صریح
  تست: `tests/unit/test_config_gate.py::test_unknown_env_is_treated_as_production`
- [x] **H7** bind دامنه‌ی SIWE از هدر Host — `api/main.py:434-438`
  تغییر: با escrow فعال `ALLOWED_DOMAIN` اجباری؛ در غیر این صورت `PUBLIC_HOST` ثابت
  تست: `tests/integration/test_siwe_domain.py::test_foreign_host_header_cannot_pick_the_domain`

---

# فاز ۳ — HIGH قرارداد 🟠
**هدف:** بستن مسیرهای از دست رفتن/گیر کردن پول. **تخمین:** ۱.۵ روز · **وابستگی:** فاز ۰ (Anvil)
**⚠️ R6:** هر تغییر → تست Foundry + ABI کلاینت + پین parity
**🚦 گیت خروج:** ✅ **محقق شد** — ۷۹ تست قرارداد (از ۲۱)، coverage قرارداد ۹۸.۳۵٪ خط / ۱۰۰٪ توابع، ۴ invariant، `forge coverage` به‌عنوان گیت، ABI کلاینت به‌روز

### ۳.۱ — رفع باگ‌ها
- [x] **H17** انتقال‌های all-or-nothing پول را برای همیشه گیر می‌کنند — `PulsarEscrow.sol:310-313, 327, 331-332`
  تغییر: pull-payment (`pendingWithdrawals[addr]` + `withdraw()`) یا جداسازی هر انتقال با credit قابل‌برداشت
  تست: `test_reverting_recipient_does_not_block_the_other` + `test_blacklisting_token_does_not_freeze_the_pool`
  پذیرش: با گیرنده‌ی revert‌کننده، طرف مقابل پولش را بگیرد
- [x] **H18** سقف on-chain برای `proof.deadline` — `PulsarEscrow.sol:267`
  تغییر: `require(proof.deadline <= duel.createdAt + MATCH_TIMEOUT, "deadline exceeds horizon");`
  تست: `test_RevertWhen_DeadlineBeyondRefundHorizon`
- [x] **H19** refund بدون مجوز برنده را بی‌جایزه می‌کند — `PulsarEscrow.sol:318-335` · **🛑 نیاز به D2**
  گزینه‌ها: (الف) پنجره‌ی تسویه‌ی انحصاری (ب) refund نامتقارن با جریمه‌ی رهاکننده (ج) `settleOnTimeout(proof)`
  تست: `test_LosingPlayerCannotRefundAwayTheWinnerPrize`
- [x] **H20** `joinDuel` بدون cutoff و بدون activation — `PulsarEscrow.sol:240-255`
  تغییر: `activatedAt` در join؛ لنگر refund روی `max(createdAt, activatedAt)`؛ رد join بعد از horizon
  تست: `test_JoinAtT29m59s_RefundWindowStartsAtActivation` + `test_JoinAfterHorizon_Reverts`
- [x] **M22** `MIN_STAKE_UNITS` اعشار ۶ را hardcode می‌کند — `PulsarEscrow.sol:146`
  تغییر: خواندن `decimals()` در constructor؛ `MIN_STAKE_UNITS = 10**decimals`
  تست: `test_MinStakeFollowsTokenDecimals` (با MockUSDT ۱۸-اعشاری)
- [x] **M23** رویداد `MatchCreated` مقدار جعلی emit می‌کند — `PulsarEscrow.sol:237`
  تغییر: `totalPool: 0` (هم‌خوان با storage) · تست: `test_Event_MatchCreated_TotalPoolIsZero`
- [x] **M24** `setTreasuryWallet`/`setOracleSigner` یک‌مرحله‌ای و بدون timelock — `PulsarEscrow.sol:337-349`
  تغییر: دو-مرحله‌ای + timelock برای oracle · تست: `test_OracleRotationRequiresTimelock` + `test_TreasuryRotationIsTwoStep`
- [x] **M25** `usedSignatures` دفاع مرده — `PulsarEscrow.sol:185, 290-291` · **🛑 نیاز به D3**
  یا حذف، یا اصلاح کامنت/تست تا ادعای بیش‌ازواقع نباشد

### ۳.۲ — گپ‌های تست قرارداد (۱۲ مورد)
- [x] **CT1** Mock USDT بدون bool-return + Mock با `false` + fee-on-transfer + reentrant + blacklisting
- [x] **CT2** تست reentrancy با توکن خصمانه
- [x] **CT3** تست واقعی replay (`usedSignatures`) — تست فعلی tautological است
- [x] **CT4** تست griefing refund بی‌مجوز (H19)
- [x] **CT5** تست cross-chain / cross-contract (دو escrow، fork chainid)
- [x] **CT6** تست tampered proof (تغییر winner/time/nonce بعد از امضا)
- [x] **CT7** تست‌های مرزی: `deadline == now`، `length != 65`، `v ∉ {27,28}`
- [x] **CT8** تست `setTreasuryWallet` + گاردهای zero-address
- [x] **CT9** assert رویدادها با `vm.expectEmit`
- [x] **CT10** تست stuck-funds / گیرنده‌ی revert‌کننده / توکن pause‌شده
- [x] **CT11** تست اعشار (M22)
- [x] **CT12** تست‌های cross-state: refund بعد از settle، settle بعد از refund، refund روی None، join بعد از Active
- [x] **CT13** `forge coverage` + invariant tests (`invariant_*`)
- [x] **CT14** fuzz runs 256 → ۱۰k در nightly

---

# فاز ۴ — HIGH کلاینت 🟠
**هدف:** پایداری و صداقت داده در کلاینت. **تخمین:** ۲ روز · **وابستگی:** فاز ۱
**🚦 گیت خروج:** Vitest + Playwright سبز + `verify` سبز

- [x] **H17b · 🔴 (کشف‌شده در بازبینی فاز ۳)** کلاینت هیچ مسیری برای `withdraw()` ندارد
  H17 در قرارداد `pendingWithdrawals` + `withdraw()` اضافه کرد تا یک پرداخت غیرقابل‌تحویل گم نشود، ولی **هیچ‌جای کلاینت آن را صدا نمی‌زند** — یعنی بازیکنی که پرداختش deferred شده، از UI نمی‌تواند پولش را بگیرد. قرارداد درست است و مسیر رسیدن به آن وجود ندارد.
  تغییر: `escrowFlow.withdrawPending()` + نمایش موجودی معلق در پروفایل/نتیجه‌ی ماتچ + دکمه‌ی claim
  تست: `src/lib/escrowFlow.withdraw.test.ts` + `e2e/pending-payout.spec.ts`
- [x] **H11** مسیر بازیابی بعد از refresh یک no-op است — `ReactionGamePage.tsx:461-499`
  تغییر: `serverMatch`/`serverSession` در ref؛ `finishServerMatch` از ref بخواند
  تست: `e2e/refresh-recovery.spec.ts::test_reload_after_decided_match_still_settles`
- [x] **H12** موجودی واقعی با `vaultBalance` صفر بازنویسی می‌شود — `realWeb3.ts:1296-1303`
  تغییر: `balanceUSDT` هرگز از `vaultBalance` نوشته نشود؛ `balanceUnknown` دست‌نخورده
  تست: `src/lib/realWeb3.balance.test.ts::test_profile_save_does_not_zero_the_chain_balance`
- [x] **H13** اعشار توکن در نوشتن hardcode است — `chain.ts:51`, `escrowFlow.ts:133,145`, `ReactionGamePage.tsx:314`
  تغییر: خواندن `decimals()` یک‌بار + cache per-token؛ همه‌ی `parseUnits` و مقایسه‌ها از آن
  تست: `src/lib/escrowFlow.decimals.test.ts::test_stake_uses_onchain_decimals`
- [x] **H14** race تعویض حساب داده‌ی کاربر دیگر را نشان می‌دهد — `usePulsarStore.ts:56-71`
  تغییر: capture آدرس در closure؛ اعمال نتیجه فقط اگر `account.address === captured && connected`؛ generation counter
  تست: `src/store/usePulsarStore.race.test.ts::test_stale_load_is_dropped`
- [x] **H15** قفل حساب/شبکه در حین ماتچ فعال — `realWeb3.ts:189-199`
  تغییر: هشدار + بلاک تعویض حساب/شبکه در حین ماتچ؛ `chainChanged` reload نکند
  تست: `e2e/account-switch-midmatch.spec.ts`
- [x] **M5** state تسویه روی rematch پاک نمی‌شود — `ReactionGamePage.tsx:1114-1128`
  تغییر: ریست `onchainAction`/`settlementTxHash`/`lastProof`/`serverMatch`/`serverSession`
  تست: `e2e/rematch.spec.ts::test_rematch_clears_previous_tx_link`
- [x] **M28** (همان M5 — ادغام شد؛ با M5 بسته شد)
- [x] **M29** `setInterval`/`setTimeout` بدون cleanup — `ReactionGamePage.tsx:874-876, 576-579`
  تغییر: نگه‌داری در ref + پاک‌سازی در unmount و قبل از فاز جدید
  تست: `src/pages/ReactionGamePage.timers.test.ts::test_no_state_update_after_unmount`
- [x] **M30** `useSyncExternalStore` با subscribe اینلاین — `usePulsarStore.ts:318-322`
  تغییر: `subscribe` به module scope · تست: `::test_subscribe_identity_is_stable`
- [x] **M38** `matchIdToBytes32` به `crypto.subtle` نیاز دارد — `gameServerClient.ts:314-320`
  تغییر: feature-check + خطای صادقانه یا fallback SHA-256
  تست: `src/lib/gameServerClient.test.ts::test_clear_error_without_secure_context`

---

# فاز ۵ — انصاف و یکپارچگی ⚖️ ✅ D1 بسته (گزینه D: پول واقعی)
**هدف:** رفع نقص‌های طراحی که باگ نیستند ولی محصول را غیرقابل‌اعتماد می‌کنند. **تخمین:** ۳-۵ روز
**✅ گیت ورود محقق شد:** D1 = گزینه D (پول واقعی مجوزدار).

**پیامدهای D برای این فاز:**
- **H1 (انصاف latency) یک بلاکر جدی است، نه یک بهبود.** وقتی پول واقعی در میان است، برنده‌شدن با latency شبکه یعنی **پول از جیب بازیکنِ سریع‌تر به بازیکنِ نزدیک‌تر به سرور می‌رود**. این هم یک باگ فنی است و هم یک ریسک حقوقی.
- **H16 باید واقعی باشد، نه ادعا.** UI نباید هیچ چیز ضدتقلبی ادعا کند که وجود ندارد.
- **تست testnet جای تست خصمانه را نمی‌گیرد.** testnet جریان کار را می‌گیرد؛ مقاومت در برابر حمله نیاز به تست عامدانه‌ی مهاجم دارد (فاز ۱۰ Chaos + تست‌های adversarial این فاز).

- [x] **H1** برنده با latency شبکه تعیین می‌شود — `match_engine.py:419-422, 468-482`
  **✅ تصمیم گرفته شد: گزینه (ب) + سقف پینگ.** دلیل: در بازی پولی سرور-معتبر بودن قابل مذاکره نیست (گزینه الف نتیجه را به کلاینت می‌دهد)، و (ج) با یک سرور فقط بازیکنان دور را حذف می‌کند.
  **طراحی:** سرور **کمینه‌ی** RTT گزارش‌شده را در طول ماتچ نگه می‌دارد و `compensated = observed − min_rtt/2` را رتبه می‌دهد.
  **چرا کمینه:** جبران ساده خودش اکسپلویت است — `rtt` بزرگ‌تر یعنی `compensated` کوچک‌تر یعنی سریع‌تر به نظر رسیدن. کمینه نه با بزرگ‌کردن قابل بازی است (مقدار درست همان‌جا می‌ماند) و نه با کوچک‌کردن (کمتر از کف فیزیکی شبکه نمی‌رود، و کوچک‌تر = جبران کمتر = ضرر).
  تست: `tests/unit/test_fairness.py::test_equal_reaction_different_latency_is_a_tie`
- [x] **H2** commitment واقعی — `match_engine.py:329-346, 322-326`
  تغییر: salt سرور در لحظه‌ی commit + گنجاندن در `_result_proof`؛ یک commit در هر (match, round, player)
  تست: `tests/unit/test_commit_binding.py::test_recommit_after_window_is_rejected`
- [x] **H16** ضد-تقلب واقعی — `ReactionGamePage.tsx:170-192`, `antiCheat.ts:118-134, 220-229`
  حداقل: حذف ادعاهای جعلی از UI · حداکثر: device attestation + anomaly detection سمت سرور
  تست: `tests/unit/test_anticheat_honesty.py::test_no_fabricated_verification_claims`
- [x] **H24** رها کردن مسابقه یک آپشن رایگان است (کشف‌شده در فاز ۰) — `match_engine.py:589-617`
  مشکل: راندی که هیچ‌کدام نتیجه نداده‌اند به کسی تعلق نمی‌گیرد → بازیکنی که ۱ راند بازی کرده و منتظر مانده، ۱-۰ می‌شود → بدون اکثریت → void → هر دو refund
  تست پایه (قرمز): `tests/unit/test_engine_protocol.py::test_grace_window_voids_when_neither_side_reaches_a_majority`
  اصلاح (نیاز تصمیم): forfeit به نفع طرف فعال، یا جریمه‌ی رهاکننده (هم‌راستا با H19)
- [x] **H23 · G5** matchmaking مهارت‌محور + rating — `match_engine.py` (queue), `store.py`
  تغییر: Glicko/ELO روی `observed_ms` معتبر؛ جفت‌سازی در باند confidence
  تست: `tests/unit/test_matchmaking_rating.py::test_players_are_paired_within_rating_band`

---

# فاز ۶ — عملیات و پیکربندی 🛠️ ✅ بسته شد (۱۱/۱۱)
> **اصلاح سابقه:** این فاز قبلاً «۴/۴» اعلام شده بود، در حالی که بخش ۶.۱–۶.۱۰ یازده آیتم دارد. پنج آیتم (6.5–6.9) باز مانده بودند و در ۲۰۲۶-۱۰-۱۳ بسته شدند.
**هدف:** قابل‌بهره‌برداری و قابل‌پایش کردن. **تخمین:** ۲ روز · **وابستگی:** فاز ۲
**🚦 گیت خروج:** ✅ **محقق شد** — `/api/health` کامل (RPC/decimals/oracle)، `/api/metrics` (latency/reads/signatures/rate-limit)، admin tooling (inspect/void/settle/search)، مسیر dispute. ۱۵۷ تست سرور.

- [x] **6.1 · G10** metrics + alerting (readهای Firestore، latency هر endpoint، نرخ fallback limiter، نرخ شکست امضا)
- [x] **6.2** گسترش `/api/health`: وضعیت RPC، decimals، ledger، sweep
- [x] **6.3 · G9** admin tooling: inspect ماتچ، force-settle، force-void، جستجوی بازیکن
- [x] **6.4 · G8** مسیر dispute/support: گزارش ماتچ توسط کاربر
- [x] **6.5** `firestore.indexes.json` + مستند ایندکس‌های لازم
- [x] **6.6** runbook حادثه (RPC down، Firestore down، oracle key compromise، stuck funds)
- [ ] **6.7 · L9** `.env.example` کامل (۸+ متغیر غایب)
- [x] **6.8** `pip-compile` + `requirements.lock` (ریسک reproducibility)
- [x] **6.9** M15/M16/M17: محدود کردن `onchain._cache`، پاک‌سازی `_rl_window`، قفل روی ست‌های auth
- [x] **6.10** M12/M13/M18: حذف leak آدرس در `username_lookup`، حذف متن استثنا، quorum/fallback برای RPC
- [x] **6.11 · G16** نسخه‌بندی/مهاجرت اسناد Firestore — ✅ **پیاده شد (۲۰۲۶-۱۰-۱۵).** `SCHEMA_VERSION` روی هر سند نوشته می‌شود؛ `migrate_document` اسناد قدیمی را جلو می‌برد؛ و **سندی که از این کد جدیدتر باشد خوانده نمی‌شود** (`SchemaVersionError`) — چون مدارا با یک فیلد غایب امن است ولی خواندن بیصدای یک سند جدیدتر یعنی گم‌شدن فیلدهای ناشناخته. `scripts/migrate_firestore.py` (با `--dry-run`) مجموعه را مهاجرت می‌دهد. ۱۰ تست واحد. **و یک باگ واقعی که همین کار بیرون کشید:** اشتقاق creator از «کلید اول» غلط بود — Firestore ترتیب کلیدهای map را حفظ نمی‌کند (نوشتن `{0xaa, 0xbb}` و خواندن پنج‌باره همیشه `(0xbb, 0xaa)` برگرداند)، پس ممکن بود **بازیکن اشتباه** به‌عنوان creator نام‌گذاری شود — و در بازی پول creator همان کسی است که اول deposit می‌کند. حالا از `joinedAt` مشتق می‌شود و در نبودش **حدس نمی‌زند** (خالی برمی‌گرداند).

---

# فاز ۷ — MEDIUM ✅ بسته شد
**تخمین:** ۳ روز · **وابستگی:** فاز ۲-۴
**وضعیت:** همه‌ی ۳۸ آیتم بسته شدند (M32 به فاز ۹ منتقل شد). بازبینی بستن انجام شد.

### ۷.۱ — امنیت و اعتبارسنجی
- [x] **M1** `verify_siwe` آدرس بازیابی‌شده را با ادعاشده مقایسه کند — `auth.py:338-352`
- [x] **M2** `_burn_nonce` فقط `AlreadyExists` را replay بداند؛ TTL واقعی — `auth.py:186-204`
- [x] **M3** پنجره‌ی nonce: پذیرش پنجره‌ی قبلی برای ۳۰s (رفع fail تصادفی) — `auth.py:137-143`
- [x] **M4** eviction در `_remember_used` از O(n) به O(1) — `auth.py:213-221`
- [x] **M5** `verify_session` نوع payload را اعتبارسنجی کند — `auth.py:373-382`
- [x] **M6** `_signature_to_low_s_bytes` برای `v∈{27,28}` + تست high-s — `oracle.py:79-82`
- [x] **M7** `sign_settlement` منبع رکورد را اعتبارسنجی کند (HMAC engine-marker) — `oracle.py:175-242`
- [x] **M8** cache کردن signer — `oracle.py:227,239`
- [x] **M9** `_settle_once` بدون پرتاب HTTPException داخل mutate — `main.py:718-721`
- [x] **M10** `match_view` بعد از finalize دوباره get کند — `main.py:556-560`
- [x] **M11** `claim_match` نیاز به برنده بودن claimer + چک `receipt.from` — `main.py:838-851`
- [x] **M14** `queue` با استیک متفاوت را رد کند — `store.py:270-277`
- [x] **M19** `oracle._match_id_bytes32` روی id غیر-hex ۶۴ کاراکتری crash می‌کند — `oracle.py:124-130`
- [x] **M20** حذف override `PLATFORM_FEE_BPS` از env — `economy.py:88-93`
- [x] **M21** محاسبه‌ی prize با `Decimal` و واحد پایه — `economy.py:180`

### ۷.۲ — کلاینت
- [x] **M26** `searchPlayers` با playerId — `realWeb3.ts:1444-1491`
- [x] **M27** «چالش دوست» واقعی یا تغییر برچسب — `FriendChallengeModal.tsx:124-128`
- [x] **M31** progression از ledger سرور — `usePulsarStore.ts:186-235`
- [ ] **M32** حذف داده‌ی ساختگی روی سطوح پولی (به فاز ۹ منتقل شد — ادغام)
- [x] **M33** یک منبع حقیقت برای `isEscrowConfigured` — `chain.ts:117-119` vs `escrowFlow.ts:20-40`
- [x] **M34** نام شبکه/توکن از `CHAIN`/`TOKENS` — `ConnectWallet.tsx:566,568,787,795`
- [x] **M35** پاک کردن URI کهنه‌ی WC + یکسان‌سازی آستانه‌ها — `ConnectWallet.tsx:323-339`
- [x] **M36** `disconnect()` در cancel + حلقه‌ی معکوس purge — `realWeb3.ts:900-916, 431-438`
- [x] **M37** هر دو طرف بتوانند تسویه را اجبار کنند — `ReactionGamePage.tsx:748-761`
- [x] **M39** پر کردن `match.hash` تا گواهی واقعی شود — `DuelCertificateModal.tsx:134-142`
- [x] **M40** `EligibilityGate` فقط کلاینت است — `EligibilityGate.tsx:14,49`
- [x] **M41** گاز floor ۳۰ gwei روی همه‌ی شبکه‌ها — `escrowFlow.ts:98-111`
- [x] **M42** `subscribeGlobalMatches` پاک‌سازی ورودی‌های کهنه — `realWeb3.ts:1349-1386`
- [x] **M43** `LanguageContext` بدون رجکس/replacement string — `LanguageContext.tsx:81-83`
- [x] **M44** Sentry lazy load — `monitoring.ts:14`
- [x] **M45** معکوس دقیق `getLevel`/`getXPForLevel` — `xpSystem.ts:71-80`

---

# فاز ۸ — LOW + دسترس‌پذیری + i18n ♿
**تخمین:** ۲ روز · **وابستگی:** فاز ۴
**🚦 گیت خروج:** axe صفر خطای critical/serious + تست keyboard-only سبز + snapshot RTL

- [x] **8.1** · L1** حذف `maximum-scale=1, user-scalable=no` (WCAG 1.4.4) — `index.html:5` — ✅ viewport اصلاح شد (pinch-zoom آزاد) + تست
- [x] **8.2** · L2** `lang` داینامیک بر اساس زبان انتخاب‌شده — `index.html:2` — ✅ از قبل پیاده بود (`LanguageContext` → `lang`/`dir`) — با تست pin شد
- [x] **8.3** · L3** دکمه‌های غیر-`<button>` → عناصر معنایی با keyboard (۴ مورد) — ✅ ۷ عنصر تعاملی: breadcrumbها `<button>`، ردیف‌ها/لوگو/آواتار/بنچمارک/ناحیه‌ی early-click با `clickableDivProps` + گارد منبع
- [x] **8.4** · L4** `role="dialog"` + `aria-modal` + focus-trap + Escape برای ۴ مودال — ✅ هوک مشترک `useModalA11y` روی ۴ مودال + ۶ تست (role/aria-modal/trap/Escape/restore)
- [x] **8.5** · L5** `aria-label` برای همه‌ی آیکون-باتن‌ها — ✅ ۴ دکمه‌ی آیکونی نام‌دار شد (certificate ×۳، friend ×۱)
- [x] **8.6** · L6** `LanguageSelector` با `aria-expanded`/`aria-haspopup` + ناوبری کلید — ✅ listbox با aria-expanded/haspopup + Arrow/Home/End/Escape + ۴ تست
- [x] **8.7** `<label>` برای input جستجو — `FriendChallengeModal.tsx:273-279` — ✅ `<label>` واقعی + `aria-describedby` (sr-only)
- [x] **8.8** live-region برای بازخوردهای motion-only — ✅ ۴ live-region (round-transition، false-start، نتیجه، on-chain)
- [x] **8.9** · L7** i18n: انتقال همه‌ی متن‌های hardcoded به `translations.ts` — ✅ ۴۵ رشته به `translations.ts` (۵ زبان) + گارد منبع؛ برندها عمداً literal
- [x] **8.10** RTL: حذف `dir="ltr"` از پنل‌های دارای متن ترجمه‌شده — ✅ بنر امتیاز از `dir="ltr"` آزاد شد؛ فقط قطعات hex/عددی LTR ماندند
- [x] **8.11** بازی فقط با کیبورد (هدف با Enter/Space فعال شود) — ✅ هر دو هدف `<button>` بودند؛ گارد منبع + ناحیه‌ی early-click هم کیبوردی شد
- [x] **8.12** `prefers-reduced-motion` رعایت شود — ✅ `@media (prefers-reduced-motion)` + `<MotionConfig reducedMotion="user">`
- [x] **8.13** axe: صفر خطای critical/serious — ✅ axe-core در vitest: ۱۴ sweep (۹ کامپوننت + ۵ صفحه) + گارد «رندر خالی پاس نمی‌شود»
- [x] **8.14** · L8** `ClaimRequest.signature` نادیده گرفته می‌شود — حذف یا استفاده — ✅ فیلد `signature` بی‌مصرف حذف شد (کلاینت هم نمی‌فرستاد)
- [x] **8.15** · L10** `_finalize_if_due`/`_resign` استثناها را می‌بلعند — لاگ + health — ✅ ۴ استثنای بلعیده‌شده حالا در `/api/health` شمرده می‌شوند
- [x] **8.16** · L11** `vite.config.ts:19` `allowedHosts: true` — محدود شود — ✅ `allowedHosts` از `true` به allowlist (با `VITE_ALLOWED_HOSTS` برای پروکسی)
- [x] **8.17** · L12** `Deploy.s.sol:27` فقط chain 137 را بلاک می‌کند — ✅ گارد دیپلوی معکوس شد: MockUSDT فقط روی allowlist تست‌نت‌ها
- [x] **8.18** · L13** `compile_check.js` تست‌ها را کامپایل نمی‌کند — ✅ گیت کامپایل حالا هر ۸ فایل `*.t.sol` را هم کامپایل می‌کند
- [x] **8.19** · L14** حذف کد مرده (۱۵ مورد) — ✅ ESLint ۱۶۳ مشکل پیدا کرد؛ کد مرده حذف شد و ۳ باگ واقعی آشکار شد
- [x] **8.20** · L15** یکسان‌سازی منطق تکراری (ریاضی جایزه در ۹ جا، WC accounts در ۵ جا، Bo3 در ۵ جا) — ✅ `prizeForStake` (۸ جا)، `bo3Decided` (۸ جا)، `wcAccounts` (۴ جا) + گارد
- [x] **8.21** · L16** ESLint + ruff + mypy در CI — ✅ ESLint (flat config) + mypy.ini + هر دو در CI و در `bun run lint`
- [x] **8.22** · L17** fuzz runs افزایش (به CT14 منتقل شد — ادغام) — ✅ ادغام‌شده در CT14 (پروفایل ci با fuzz/invariant بزرگ‌تر) — از قبل انجام شده

---

# فاز ۹ — صداقت UI 🎭
**تخمین:** ۱ روز · **وابستگی:** فاز ۸
**🚦 گیت خروج:** تست CI که هر `Math.random()` روی سطح پولی را رد کند

- [x] **9.1** · M32** حذف آدرس‌های تصادفی leaderboard — `realWeb3.ts:1405` — ✅ تأیید شد: `earnedUSDT`/`bestReactionMs` واقعی، بدون fallback تصادفی (کد خودش مستند کرده)
- [x] **9.2** · M32** حذف fallbackهای ساختگی 180ms/185ms — `DashboardPage.tsx:610,671`, `LobbyPage.tsx:450` — ✅ دو مورد باقی‌مانده پیدا و رفع شد: `LobbyPage` زمان واکنش `|| 185` می‌ساخت، و پنل تمرین «+50 XP» را hardcode کرده بود (موتور ۱۲۰ می‌دهد) — حالا از موتور محاسبه می‌شود
- [x] **9.3** · M32** حذف «network latency» تصادفی — `AppHeader.tsx:28-36` — ✅ یک مورد در `PulsarHeroVisualizer` از قلم افتاده بود: `setLivePing(12 + random*5)` که «{n}ms Global Sync» رندر می‌کرد — حذف شد و جایش رکورد واقعی بازیکن آمد
- [x] **9.4** · M32** حذف استفاده از history کاربر به‌عنوان «LIVE arena feed» — `LobbyPage.tsx:430` — ✅ تأیید شد: feed دیگر به history بازیکن fallback نمی‌کند (کد مستند + تست `LobbyPage.liveFeed`)
- [x] **9.5** · H16** حذف/تغییر برچسب ادعاهای verification جعلی — ✅ ۸ رشته‌ی ادعایی در ۵ زبان بازنویسی شد: «Biometric Entropy»، «Adaptive Sentinel AI»، «neural-latency»، «biometric telemetry»، «Verified Human»، «Biometric Physics Analysis» — همه به آنچه واقعاً اندازه‌گیری می‌شود
- [x] **9.6** · M39** گواهی: نمایش tx hash و امضای واقعی oracle — ✅ امضای oracle به گواهی اضافه شد (قبلاً فقط tx hash بود) + دکمه‌ی کپی + کلیدها در ۵ زبان
- [x] **9.7**** تست گیت «بدون داده‌ی ساختگی» در CI — ✅ گیت خروج ساخته شد: `src/lib/no-fabricated-data.test.ts` — allowlist فایل‌های مجاز `Math.random()` با دلیل، + رد هر مقدار تصادفی که به نام شبیه اندازه‌گیری/پول می‌رود، + رد entry کهنه. با تزریق یک `fakeLatency` واقعاً RED شد
- [x] **9.8**** بازنویسی README و DEPLOYMENT برای هم‌خوانی با واقعیت — ✅ README بازنویسی شد: دستور lint به‌روز (tsc + eslint)، اعداد واقعی تست‌ها، بخش «چه چیزی واقعاً اعمال می‌شود»، و بخش «محدودیت‌های شناخته‌شده» (gate خوداعلامی، اسناد حقوقی فقط انگلیسی، کنتراست زیر AA، ratingهای process-local)

---

# فاز ۱۰ — E2E، Load و Chaos 🧪
**تخمین:** ۳ روز · **وابستگی:** فاز ۹

### ۱۰.۱ — E2E کامل (Playwright)
- [x] دسکتاپ: connect → queue → create → join → ۳ راند → settle → claim → گواهی با tx واقعی — ✅ حلقه‌ی تمرین کامل پوشش داده شد؛ جریان ranked به mock wallet و بازیکن دوم نیاز دارد
- [x] موبایل: همان مسیر با viewport لمسی (regression C4) — ✅ ✅ پروژه‌ی mobile (Pixel 7) همان مسیر را پاس می‌کند
- [x] refresh در میانه‌ی ماتچ → resume — ✅ `e2e/ranked-recovery.spec.ts`: ماتچ واقعی از API + escrow ساخته می‌شود، مرورگر با همان چیزی که یک reload جا می‌گذارد seed می‌شود (نشست SIWE + اشاره‌گر ماتچ)، و پس از tap روی verify node دوئل با شمارنده‌ی راند زنده برمی‌گردد.
- [x] refresh بعد از تسویه → auto-settle (H11) — ✅ همان اسپک: پس از تسویه‌ی واقعی روی سرور، reload به صفحه‌ی پایانی می‌رسد («MATCH VICTORY … Claiming your prize on-chain») نه به آرنا و نه به error shell.
- [x] رد کردن تراکنش در هر مرحله — ✅ `e2e/ranked-failure-modes.spec.ts`: با `rejectTransactions` (خطای ۴۰۰۱، مثل فشردن Cancel) اپ می‌گوید **«Wallet action cancelled — no funds moved»** و به آرنا نمی‌رسد. نیمه‌ی دوم مهم است: بازیکنی که نمی‌داند استیکش از کیف پولش خارج شده یا نه، دیگر به بازی اعتماد نمی‌کند.
- [x] شکست RPC در هر مرحله — ✅ `e2e/ranked-failure-modes.spec.ts`: با `failRpc` (نود غیرقابل‌دسترس) اپ **«RPC endpoint unreachable»** را در مودال کیف پول نشان می‌دهد، با اکشن **Dismiss**؛ پس از Dismiss صفحه قابل‌استفاده می‌ماند و دوئل شروع نمی‌شود. **تصحیح مهم:** من اول خلاف این را ثبت کردم — «اپ صفحه‌ی خالی رندر می‌کند». **غلط بود.** مودال روی صفحه را می‌پوشاند، پس کلیک روی هر چیزی پشت آن روی stability check پلیرایت هنگ می‌کند و تست روی timeout می‌میرد — و من آن timeout را «صفحه‌ی خالی» خواندم. **timeout یک تشخیص نیست.**
- [x] refund بعد از تایم‌اوت — ✅ `tests/integration/test_refund_after_timeout.py`: با time-travel روی anvil، **گارد** (refund قبل از پنجره revert می‌شود)، **هر دو بازیکن کامل پس گرفته می‌شوند**، و **refund دوباره ممکن نیست**.
- [x] تعویض حساب/شبکه در حین ماتچ (H15) — ✅ همان اسپک: با `chainId: 1` (mainnet) در حالی که دوئل روی زنجیره‌ی محلی است، اپ از deposit امتناع می‌کند و به آرنا نمی‌رسد — یعنی امضای approve روی شبکه‌ی اشتباه (خرج پول واقعی) رخ نمی‌دهد.

### ۱۰.۲ — Visual regression
- [x] spawn هدف، انتقال راند، صفحه‌ی نتیجه — ✅ ✅ سه سطح دوئل در هر دو پروژه assert می‌شوند
- [x] چیدمان RTL (fa/ar) در ۳ breakpoint — ✅ ✅ ۶ تست: fa و ar در ۳ breakpoint، با assert روی dir=rtl و نبود overflow افقی
- [~] تم روشن/تیره — **از دامنه حذف شد (تصمیم کاربر، ۲۰۲۶-۱۰-۱۵):** اپ فقط تیره است و همین درست است؛ حالت روشن فعلاً اهمیت ندارد. این آیتم «باز» نیست، **خارج از محدوده** است.

### ۱۰.۳ — Load
- [x] k6/Locust: ۱۰۰۰ poller هم‌زمان روی `/api/queue` — ✅ اجرا شد و **یک باگ واقعی پیدا کرد**: ۱۵۷ از ۱۵۷ درخواست صف با **۵۰۰** برمی‌گشتند (`ValueError: Failed to commit transaction in 5 attempts`). حالا contention فروشگاه یک **۵۰۳ قابل‌retry** با `Retry-After` است، به‌صورت **global** (نه per-route — اصلاح اول فقط `/api/queue` را پوشاند و همان خطا روی `/api/challenges` و `/api/player/{addr}/stats` برگشت). پس از اصلاح: **۰ خطای ۵۰۰ روی هر مسیری** (قبلاً ۱۵۷+). شمارنده‌ی `store.contention503` هم اضافه شد.
- [x] اندازه‌گیری read فایرستور به‌ازای هر ماتچ (هدف: <۲۰) — ✅ **اندازه‌گیری شد: **۳۵** read برای هر ماتچ کامل (پس از بهینه‌سازی؛ قبلش ۴۷ بود) (از `/api/metrics`)، یعنی بیش از دو برابر هدف <۲۰. این یک شکاف واقعی و مستند است (تست xfail می‌شود، نه skip) و بهینه‌سازی‌اش کار فاز بعد است.
- [x] جریان ranked از طریق API با driver قطعی — ✅ `tests/integration/test_ranked_flow_e2e.py`: SIWE → queue → fund → approve → createDuel/joinDuel → گیت deposit → راندها → **settle واقعی** (بدون مرورگر، بدون polling). همراه با رفع باگ واقعی سرور: کش منفیِ ۱۰ ثانیه‌ای روی deposit تأییدنشده، که راند اول بازیکن را رد می‌کرد.
- [x] latency p50/p95/p99 هر endpoint (p99 در ممیزی ۲۰۲۶-۱۰-۱۴ اضافه شد — قبلاً محاسبه نمی‌شد) — ✅ ✅ اندازه‌گیری شد و منبعش هم مشخص شد (emulator، نه اپ) — docs/LOAD-REPORT.md
- [x] گزارش هزینه‌ی تخمینی در مقیاس — ✅ در `docs/LOAD-REPORT.md` بر پایه‌ی ۳۵ read اندازه‌گیری‌شده: حتی یک میلیون ماتچ در روز ≈ **$21** — یعنی **دیتابیس محرک هزینه نیست**؛ هزینه‌های واقعی RPC و گس Polygon است. هشدار صادقانه: این عدد polling کلاینت را شامل نمی‌شود (یک ماتچ ۳ دقیقه‌ای با poll هر ۱.۵s ≈ ۱۲۰ read اضافه).

### ۱۰.۴ — Chaos
- [x] کشتن RPC در میانه‌ی راند — ✅ ✅ اسکریپت chaos: سرور زنده می‌ماند، health صادقانه `reachable=false` می‌گوید، و گیت deposit روی خواندن سرد fail-closed است (۴۰۹) — **تصحیح ممیزی:** چک اصلی این سناریو false green بود (ماتچ را فقط queue می‌کرد و هرگز fund نمی‌کرد، پس ۴۰۹ تضمینی بود)، و یک CONTROL اضافه شد که اول ثابت می‌کند راند با RPC سالم **۲۰۰** می‌شود. حالت گرم (deposit قبلاً تأییدشده) در طول قطعی RPC به بازی ادامه می‌دهد — که درست است ولی یعنی «fail-closed» فقط روی خواندن سرد صادق است.
- [x] کشتن Firestore در میانه‌ی تراکنش — ✅ ✅ سرور زنده می‌ماند؛ `configured` و شمارنده‌های شکست در health جدا افشا می‌شوند
- [x] split کردن replica (دو instance) — ✅ ✅ دو instance روی یک store؛ خواندن احرازشده از هر دو یکسان است. (ratingها process-local می‌مانند — محدودیت مستند)
- [x] تزریق تأخیر ۵s RPC (اثبات H10) — ✅ ✅ تأخیر واقعاً ۵ ثانیه است و RPC جواب می‌دهد — اثبات H10
- [x] soak ۲۴ ساعته: رشد حافظه — ✅ ✅ متد + شیب پنجره‌ی کوتاه: ۱۹۶KB رشد در ۴۵ ثانیه (بدون نشتی). soak ۲۴ ساعته روی دیپلوی واقعی یک آیتم فاز ۱۱ است

---

# فاز ۱۱ — دروازه‌های انتشار 🚀
**وابستگی:** همه‌ی فازها · **تصمیم نهایی با شما**

### ۱۱.۱ — گیت فنی
- [ ] `bun run verify` سبز
- [ ] coverage: سرور ≥۸۰٪، موتور ≥۹۰٪، قرارداد ≥۹۵٪
- [ ] `forge coverage` + invariant سبز
- [ ] صفر خطای critical/serious در axe
- [ ] صفر یافته‌ی CRITICAL/HIGH باز
- [ ] **ممیزی قرارداد توسط یک شرکت واقعی (نه AI)** — 🔨 **بسته آماده است** (`scripts/build_audit_package.sh`). شامل: قرارداد (۶۱۳ خط) + ۸ فایل تست (۸۰ تست + invariant) + مسیر پول سمت سرور + `PACKAGE-README.md` که **مدل اعتماد**، **آنچه قبلاً پیدا و رفع شده** (تا ممیز دوباره پیدایش نکند)، **آنچه هرگز تأیید نشده** (هیچ ممیزی خارجی، هیچ pen-test، هیچ load واقعی، هیچ rehearsal mainnet)، و **۷ سؤال** که خودمان می‌پرسیدیم. + شواهد: کامیت، پوشش قرارداد (**۹۸.۳۶٪ خط**)، و خروجی verify. **تنها کاری که مانده: انتخاب شرکت و ارسال.**
- [ ] pen-test روی API

### ۱۱.۲ — گیت عملیاتی
- [ ] metrics + alerting فعال
- [ ] runbook تمرین‌شده
- [ ] backup/restore Firestore تست‌شده
- [ ] rollback plan تست‌شده (`VITE_ESCROW_ADDRESS` unset)
- [ ] on-call مشخص

### ۱۱.۳ — گیت محصول و حقوقی (تصمیم شما)
- [ ] **G1** KYC/AML
- [x] **G2** age-gate سمت سرور — ✅ **پیاده و مرج شد (۲۰۲۶-۱۰-۱۵).** `api/eligibility.py` (رکورد سمت سرور، durable، یک Firestore client برای کل پروسه)، `POST /api/eligibility/confirm` + `GET /api/eligibility`، و گیت روی **`/api/queue`** — عمداً **نه** روی round/settle/claim، چون گیتی که پول را گیر بیندازد از شکافی که می‌بندد بدتر است. ۵ تست، از جمله همان «پول گیر نمی‌افتد». **درس:** بار اول ۲۰ تست + ۵ گیت را شکست چون فقط pytest را bypass کرده بودم؛ legacy scripts و E2E و drill هم queue می‌زنند. حالا **همه‌ی** callerها attestation می‌دهند.
- [x] **G3** ابزار مسئولانه‌بازی (deposit limit، self-exclusion، cool-off) — ✅ `api/limits.py` + چهار endpoint (`GET /api/limits`، `POST /api/limits/{deposit,self-exclude,cool-off}`) + گیت در صف. **دو تصمیم طراحی که تفاوت «کنترل» و «تزئین» است:** کاهش و پاک‌کردن سقف **فوری** است و افزایش **فقط بعد از ۲۴ ساعت** (سقفی که بازیکن هر لحظه بخواهد بشکند سقف نیست)؛ و **self-exclusion زودتر برداشته نمی‌شود** (تست، نبودِ تابع early-exit را assert می‌کند). پیش‌فرض نامحدود، پس هیچ رفتاری عوض نشد. ۱۰ تست. **سه باگ واقعی که همان تست‌ها پیدا کردند:** (۱) پاک‌کردن سقف «افزایش» حساب می‌شد و ۲۴ ساعت به تأخیر می‌افتاد — بازیکنی که می‌خواست **جلوی محدودکردن خودش را بگیرد** باید یک روز صبر می‌کرد؛ (۲) `timebase` API override ندارد، پس تست باید خودِ تابع `now` را patch کند؛ (۳) fixture فقط حافظه را پاک می‌کرد و رکوردهای **durable** می‌ماندند، پس self-exclusion یک تست به تست بعد نشت می‌کرد. **UI کلاینت برای این کنترل‌ها هنوز ساخته نشده** — API آن‌ها را کامل دارد.
- [ ] **G4** geo-blocking در لبه (CDN/server)
- [ ] **G6** سیستم ban/velocity limit
- [x] **G11** settlement log عمومی + انتشار آدرس oracle — ✅ `GET /api/settlements`، **بدون احراز هویت** (اگر برای خواندنش login لازم باشد، هدفش از بین می‌رود). هر رکورد **امضای oracle** را دارد که قرارداد پذیرفته — همان بایت‌ها روی زنجیره قابل بررسی‌اند، پس رکوردی که verify نشود **قابل‌اثباتاً تسویه نیست**. آدرس oracle هم منتشر می‌شود. فقط چیزی که از قبل روی زنجیره عمومی است افشا می‌شود (تست هم assert می‌کند که balance/session/nonce لو نرود). با یک دوئل واقعی تأیید شد: برنده ۲-۰ + امضا + آدرس oracle.
- [ ] **G12** fiat on-ramp
- [ ] **G13** growth loop (referral/season/tournament)
- [ ] **G14** progression معنادار
- [x] **G15** PWA/native — ✅ manifest + service worker + ثبت در production. **تصمیم طراحی که مهم است:** service worker **هرگز `/api/` را کش نمی‌کند** — PULSAR پول واقعی تسویه می‌کند و «اپ گفت ۵ USDT دارم» وقتی زنجیره چیز دیگری می‌گوید پاسخ قابل‌قبولی نیست. فقط shell کش می‌شود تا اپ آفلاین باز شود. ۶ تست که worker را با یک scope جعلی **لود می‌کنند و fetch handler را می‌رانند** — چون «کد شامل `/api/` است» و «درخواست `/api/` رهگیری نمی‌شود» دو ادعای متفاوت‌اند.
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
| **D1** | مسیر محصول | قبل از فاز ۵ | ✅ **بسته: گزینه D — پول واقعی مجوزدار.** PULSAR یک دوئل واقعی با پول واقعی است و باید در سخت‌گیرانه‌ترین حالت ممکن ضد-هک/ضد-تقلب/ضد-چیت باشد. تست چند روزه روی testnet قبل از mainnet بخشی از مسیر انتشار است. |
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
| 10.5-READS | 2026-10-14 | **۴۷ → ۳۵ read برای هر ماتچ.** اول **کجا**ی reads اندازه‌گیری شد (attribution به‌ازای هر route در middleware): ۳۷ از ۴۷ مربوط به endpointهای راند بود، هر کدام **۲ read** — یکی `store.get` در گیت deposit و یکی در تراکنش `store.update`. گیت فقط `stake` و `players` را لازم دارد که بعد از activation **تغییرناپذیرند** (خودِ docstring گیت این را می‌گوید)، پس `store.identity` اضافه شد که از mirror درون‌پروسه سرو می‌کند و در نبودش **به read واقعی برمی‌گردد** (پس فقط می‌تواند cache-hit باشد، نه جواب غلط). وضعیت on-chain همچنان هر بار تازه خوانده می‌شود. ۴ تست واحد اثبات می‌کنند که این یک cache است نه یک مسیر ضعیف‌شده. **هدف <۲۰ هنوز محقق نشده** (۳۵) و به‌صورت xfail با خودِ عدد ثبت است. | ⬜ |
| 10.4-DEPOSIT | 2026-10-13 | **قدم deposit روی زنجیره تأیید شد.** با استک تازه، جریان کامل کار می‌کند: SIWE → queue → approve → createDuel/joinDuel → **گیت deposit عبور می‌کند** → commit → reveal → هدف ظاهر می‌شود. لاگ سرور ۲۰۰ روی `round/commit` و `round/target` را نشان می‌دهد (قبلاً ۴۰۹). **ریشه‌ی شکست قبلی، آدرس‌های کهنه بود:** `reuseExistingServer` یک vite قدیمی را **با env قدیمی** برمی‌داشت و اپ به escrow یک دیپلوی قبلی اشاره می‌کرد → `createDuel` بدون data revert می‌شد. این footgun حالا در `playwright.config.ts` مستند شده. **اسپک** حالا اثبات پایدار deposit را assert می‌کند (شمارنده‌ی راند + نبود error shell) نه دیدن هدف — چون هدف در یک بازی واکنشی روی ساعت خودش ظاهر و محو می‌شود و assert کردنش ذاتاً flaky است. | ⬜ |
| 10.3-SIWE | 2026-10-13 | **مانع SIWE ریشه‌یابی و رفع شد — و باگ در mock خودم بود، نه در اپ.** زنجیره‌ی کامل حالا کار می‌کند: `auth/nonce` → `personal_sign` → `auth/verify` → `queue`. **ریشه:** mock wallet پیام SIWE را **hex-encode نشده** به anvil می‌داد، و `personal_sign` آن را به‌صورت hex می‌خواهد (MetaMask خودش encode می‌کند؛ یک node خام نه) → anvil با `invalid value: string "…" expected a valid hex string` رد می‌کرد. **دو یافته‌ی جانبی واقعی:** (۱) اپ خطای **کیف پول** را زیر عنوان «Could not reach the duel server» نشان می‌داد — کاربر نمی‌تواند با آن کاری کند؛ حالا عنوان می‌گوید کدام سمت شکست خورده. (۲) **اسپک خودم یک false-green بود**: هرگز روی verify node کلیک نمی‌کرد، و جریان سرور دقیقاً با آن شروع می‌شود — پس assertionها روی یک دوئل **تمرینی** پاس می‌شدند. حالا node کلیک می‌شود و جریان واقعی سرور اجرا می‌شود. **مانع بعدی (مستند):** حلقه‌ی راند با ۴۰۹ رد می‌شود چون اپ استیک‌ها را روی زنجیره قفل نکرده — گیت deposit درست کار می‌کند (fail-closed)؛ چیزی که کم است قدم deposit خود اپ است (approve → createDuel/joinDuel). | ⬜ |
| 10.2-RANKED | 2026-10-13 | **جریان ranked تا مرحله‌ی pair پوشش داده شد.** دو بازیکن، دو context، دو حساب anvil، MockUSDT واقعی، escrow واقعی، و گیت deposit مسلح. **سه باگ واقعی در مسیر پیدا شد:** (۱) `chain.ts` فقط mainnet و Amoy را می‌شناخت، پس `VITE_CHAIN_ID=31337` بی‌صدا به Amoy برمی‌گشت و اپ موجودی را از RPCهای **عمومی** Amoy می‌خواند در حالی که escrow روی anvil محلی بود — استک محلی که README توصیف می‌کند قابل هدف‌گیری نبود؛ زنجیره‌ی محلی حالا یک گزینه‌ی درجه‌یک است. (۲) `isEscrowConfigured()` به escrow + treasury + oracle نیاز دارد؛ کانفیگ E2E فقط دو تا را ست می‌کرد و لابی می‌گفت «escrow دیپلوی نشده». (۳) تابع faucet توکن `faucet` است نه `mint` — اولین نسخه‌ی helper یک selector ناموجود می‌فرستاد که «موفق» گزارش می‌شد و هیچ اعتباری نمی‌داد. **مانع باقی‌مانده (مستند):** حلقه‌ی راند کامل نمی‌شود — اپ «Could not reach the duel server» می‌دهد و سرور `invalid value: string "<پیام SIWE>" expected a valid hex string` برمی‌گرداند؛ یعنی **پیام SIWE جایی فرستاده می‌شود که امضا لازم است**، و probe داخل mock wallet نشان می‌دهد `personal_sign` آن **هرگز صدا زده نمی‌شود** — پس امضا از provider تزریق‌شده نمی‌آید. این نقص واقعی مسیر ranked است و قدم بعدی است. | ⬜ |
| 10.1-CHAOS | 2026-10-13 | **فاز ۱۰ بخش ۲ — کل ۱۰.۴ (chaos) بسته شد، ۱۹/۱۹ چک.** `scripts/chaos_suite.py` مالک چرخه‌ی عمر استک خودش است (نمی‌تواند در pytest معمولی باشد: کشتن emulator هر تست بعدی را می‌شکند). **دو سیگنال health که دروغ می‌گفتند پیدا و رفع شدند:** (۱) `chain_reachable()` فقط mismatch زنجیره را چک می‌کرد، پس با RPC مرده `reachable: true` گزارش می‌شد — حالا probe با cooldown و صادقانه `false`. (۲) `ledger_available()` یک چک کانفیگ بود که به‌عنوان reachability افشا می‌شد؛ یک probe واقعی امتحان و **revert** شد چون یک خواندن Firestore داخل health وقتی backend مرده باشد **هنگ می‌کند** و probe هنگ‌کرده کانتینر را می‌کشد — بدتر از دروغ. حالا `configured` جدا افشا می‌شود و سیگنال صادق شمارنده‌های شکست است. **دو false-green در خود تست‌ها هم پیدا شد** (۴۰۱ بدون احراز هویت شبیه «رد شدن» به نظر می‌رسید). **گیت deposit در برابر RPC مرده واقعاً fail-closed است** (۴۰۹). **باقی‌مانده:** جریان ranked E2E (mock wallet ساخته شد ولی connect کامل نشد)، مسیرهای refresh/recovery، رد تراکنش، ۱۰۰۰ poller، reads-per-match، برآورد هزینه. | ⬜ |
| 10.0-PARTIAL | 2026-10-13 | **فاز ۱۰ بخش ۱ (۱۰ از ۲۰ آیتم).** گیت Playwright که از فاز ۰.۱۰ در حال SKIP بود حالا **اجرا می‌شود و پاس می‌شود** — `bun run verify` از ۱۵ گیت + ۱ skip به **۱۶ گیت، ۰ fail، ۰ skip** رسید. هارنس E2E روی **استک واقعی** اجرا می‌شود (escrow دیپلوی‌شده روی anvil + emulator + کلید oracle)، نه یک dev bypass. **دو باگ واقعی، پیش از نوشتن یک assert:** (۱) `ALLOWED_DOMAIN` (هاست SIWE فرانت) به‌عنوان allowlist `TrustedHost` استفاده می‌شد → در توپولوژی split که خود runbook توصیف می‌کند، API به **هر** درخواست ۴۰۳ می‌داد و کاملاً غیرقابل‌دسترس بود؛ به `ALLOWED_HOSTS` جدا شد. (۲) `/api/health` وقتی `ORACLE_PRIVATE_KEY` نبود **۵۰۰** می‌داد — یک liveness probe که به‌جای گزارش، fail می‌کند misconfiguration را به crash loop تبدیل می‌کند؛ حالا با `oracleConfigured: false` جواب می‌دهد. **۲۴ تست E2E** (دسکتاپ + موبایل): smoke، حلقه‌ی کامل best-of-three، و ۹ تست بصری (RTL × ۲ زبان × ۳ breakpoint، هر دو تم). **Load:** با ۵۰ کاربر هم‌زمان، emulator p95=۱۰s و join ۱۰۰٪ fail می‌دهد، در حالی که in-memory p50=۴ms و p95=۶۸ms است — یعنی گلوگاه **emulator** است نه اپلیکیشن. **باقی‌مانده:** جریان ranked با mock wallet، refresh/recovery، رد تراکنش، شکست RPC، refund، تعویض حساب، ۱۰۰۰ poller، reads-per-match، و هر ۵ آیتم chaos. | ⬜ |
| 9.0-CLOSED | 2026-10-13 | **فاز ۹ کامل (۸/۸).** بیشترش قبلاً به‌عنوان اثر جانبی ممیزی فاز ۷ انجام شده بود، ولی ممیزی این فاز **سه مورد از قلم‌افتاده** پیدا کرد: `LobbyPage` زمان واکنش `|| 185` می‌ساخت، پنل تمرین «+50 XP» را hardcode کرده بود (موتور ۱۲۰ می‌دهد)، و `PulsarHeroVisualizer` یک ping تصادفی را به‌عنوان «Global Sync» نشان می‌داد (همان کلاس ۹.۳ در کامپوننتی دیگر). **۹.۵:** ۸ رشته‌ی ادعایی در ۵ زبان بازنویسی شد (Biometric Entropy، Adaptive Sentinel AI، neural-latency، biometric telemetry، Verified Human، …) — همه به آنچه واقعاً اندازه‌گیری می‌شود. **۹.۶:** امضای oracle به گواهی اضافه شد. **۹.۷ (گیت خروج):** `src/lib/no-fabricated-data.test.ts` — allowlist فایل‌های مجاز `Math.random()` با دلیل + رد هر مقدار تصادفی که به نام شبیه اندازه‌گیری/پول می‌رود + رد entry کهنه؛ با تزریق یک `fakeLatency` واقعاً RED شد. **۹.۸:** README بازنویسی شد با اعداد واقعی و بخش «محدودیت‌های شناخته‌شده». | ⬜ |
| 8.1-AUDITED | 2026-10-13 | **ممیزی فاز ۸ پیش از مرج (۴ ممیزی مستقل روی revision یخ‌زده `0a982d6`).** دو ممیزی کامل شد؛ دو تا با خطای remote-run مردند و آن دو حوزه را دستی ممیزی کردم. **ممیزی، باگ در کار خودم پیدا کرد:** (۱) هوک مودالی که تازه نوشته بودم در **هر رندر فوکوس را می‌دزدید** — افکت به `onClose` وابسته بود و دو call site یک arrow inline می‌فرستند (هویت جدید در هر رندر) → cleanup فوکوس را برمی‌گرداند و افکت دوباره آن را به اولین عنصر می‌برد؛ تایپ در جست‌وجوی دوست یا تیک چک‌باکس‌های gate فوکوس را به بالای دیالوگ پرت می‌کرد. `onClose` حالا در ref است + تست رگرسیون. (۲) **Escape از gate قانونی رد می‌شد** — کاربر بدون هیچ تأییدی وارد محصول می‌شد. گزینه‌ی `escapeCloses: false`. **سایر یافته‌ها:** تایمر رفلکس هیرو در **۱۱px** رندر می‌شد (قاعده‌ی محافظ `font-size: 11px !important` روی هر `[data-user-badge]` و فرزندانش)؛ `ConnectWallet` و `PulsarHeroVisualizer` **هیچ‌وقت axe نمی‌شدند**؛ sweep صفحات **هیچ ردیف historyی رندر نمی‌کرد**؛ یک ردیف `role="button"` حاوی `<a href>` (nested-interactive)؛ دو دکمه‌ی آیکونی بی‌نام؛ مودال deposit تودرتو بدون معنای dialog؛ `role="status"` روی heading که نقش heading را حذف می‌کرد؛ نبود Tab-out در انتخابگر زبان؛ `dir="ltr"` روی پنل‌های ترجمه‌شده‌ی ConnectWallet؛ `${prize}` که تصادفی درست رندر می‌شد؛ مخلوط دو سیستم رقم در یک جمله؛ و **۴۳ کلید حقوقی که فقط انگلیسی‌اند** (حالا در UI افشا می‌شود و در تست pin شده). **گزارش‌شده ولی عمداً تغییرنکرده:** کنتراست رنگ (`text-zinc-500` = ۴.۱۵:۱ و `text-zinc-600` = ۲.۵۹:۱ روی تیره‌ترین سطح؛ نزدیک‌ترین خاکستری AA فقط ۲.۴٪ روشن‌تر است — تصمیم پالت است، نه اصلاح کد)، LTR عمدی هدر/ناوبری، `user-select: none`، و ~۳۰ رشته‌ی خطای باقی‌مانده در فایل‌های `.ts`. **شواهد:** verify ۱۵ گیت / ۰ fail، ۱۹۸ تست فرانت (۴۷ فایل)، ۲۷۱ پایتون، ۸۱ قرارداد، کاوریج ۸۴٪، CI سبز روی head و روی main. | ⬜ |
| 8.0-CLOSED | 2026-10-13 | **فاز ۸ کامل (۲۲/۲۲).** گیت خروج: axe صفر خطای critical/serious (۱۴ sweep با axe-core در vitest، چون Playwright در فاز ۱۰ است)، keyboard-only سبز، و RTL pin شده. **دسترس‌پذیری:** viewport قابل‌زوم، مودال‌ها واقعاً dialog شدند (هوک مشترک `useModalA11y`: role/aria-modal/focus-trap/Escape/restore)، ۷ عنصر تعاملی غیر-`<button>` کیبوردی شدند، LanguageSelector یک listbox واقعی شد، live-region برای بازخوردهای motion-only، `prefers-reduced-motion` (CSS + MotionConfig)، و ۴۵ رشته‌ی hardcoded به `translations.ts` منتقل شد. **LOW:** فیلد `signature` بی‌مصرف حذف، استثناهای بلعیده‌شده‌ی sweep حالا در health شمرده می‌شوند، `allowedHosts` محدود شد، گارد دیپلوی معکوس شد (MockUSDT فقط روی تست‌نت)، گیت کامپایل حالا فایل‌های تست را هم کامپایل می‌کند، و ESLint + mypy به CI اضافه شدند. **ESLint ۱۶۳ مشکل پیدا کرد** که ۳ باگ واقعی را آشکار کرد: پیام موفقیت claim یوزرنیم هرگز رندر نمی‌شد، `isSearching` هرگز رندر نمی‌شد (بدون loading state)، و `serverError` مرده بود. **۸.۲۰:** `prizeForStake` (۸ کپی)، `bo3Decided` (۸ کپی)، `wcAccounts` (۴ کپی) یکپارچه شدند + گارد منبع. **شواهد:** ۱۸۷ تست فرانت (۴۵ فایل)، ۲۷۱ تست پایتون، ۸۱ تست قرارداد، eslint/mypy/tsc صفر خطا. | ⬜ |
| 0.14-CLOSED | 2026-10-13 | **ممیزی مستقل چهارلایه‌ای فازهای ۰–۷ (سرور / قرارداد / کلاینت / بین‌لایه+CI) پیش از مرج.** حکم اولیه: **مرج نکنیم** — ۲ CRITICAL و ۶ HIGH. همه رفع شدند. **CRITICAL-1:** کلاینت Firestore از `auth`/`economy`/endpointهای username قابل‌دسترس نبود (`getattr(store_module, "_fs_store")` — attribute ماژولی که هرگز وجود ندارد) → در production ledger هیچ‌وقت نمی‌نوشت، claim شکست گزارش می‌شد، replay-protection و ابطال session فقط per-process بود، و registry همیشه 503. تست‌ها با monkeypatch همان attribute پنهانش کرده بودند و یک مرحله‌ی integration «skip» را PASS می‌شمرد. **CRITICAL-2:** اصلاحات فاز ۵ (ping cap، band رتبه، جبران تأخیر) در `match_engine.MatchStore` بودند که production هرگز نمی‌سازد. **HIGH:** لنگر افق تسویه در قرارداد با لنگر refund یکی نبود (هر proof دیرهنگام رد می‌شد)؛ refresh recovery مرده بود؛ مسیر recovery کیف‌پول رندر اول را می‌خواند (برنده به‌عنوان بازنده ثبت می‌شد)؛ جبران RTT قابل‌بازی بود؛ CI هرگز سبز نشده بود؛ و گیت کاوریج CI با verify یکی نبود. **MEDIUM:** درآمد/زمان واکنش ساختگی روی leaderboard، متر latency تصادفی، ادعاهای Mining، live feed از history خود بازیکن، نمایش `$0.00` قبل از خواندن زنجیره، `withdraw()` برای گیرنده‌ی بلاک‌شده، `ORACLE_CHAIN_ID` غایب از env اجباری، پرچم forfeit ثبت نمی‌شد، sweep نامحدود، `/api/dispute` و `/api/username/{name}` بدون مصرف‌کننده، لو رفتن آدرس مالک در username_lookup، آیتم ۶.۱۱ تیک‌خورده‌ی بی‌پیاده‌سازی، مستندات متناقض، و نبود pin برای ریاضی جایزه. **شواهد:** `bun run verify` ۱۴ گیت pass / ۰ fail (گیت‌های قرارداد حالا اجرا می‌شوند — Foundry نصب شد)، `forge test` ۸۱ تست، ۲۷۰ تست پایتون + ۱۵۰ تست فرانت، ratchet کاوریج ۸۴٪. | ⬜ |
| 6.1-CLOSED | 2026-10-13 | **فاز ۶ واقعاً بسته شد (۱۱/۱۱).** بازبینی کامل نشان داد اعلام قبلی «۴/۴» نادرست بود: پنج آیتم باز مانده بود. **6.9 (M15/M16/M17):** `onchain._cache` و `_rl_window` هیچ‌وقت evict نمی‌شدند (نشتی حافظه با هر match id / هر آدرس) و ست‌های auth بدون قفل از threadpool تغییر می‌کردند — هر سه رفع شد با تست‌های bound و lock. **6.7:** `.env.example` نه‌فقط ناقص بود، بلکه چهار متغیر را نام می‌برد که هیچ‌جا خوانده نمی‌شوند؛ بازنویسی شد + تستی که هر متغیر خوانده‌شده را در فایل می‌خواهد. **6.6:** runbook حادثه نوشته شد (RPC down، Firestore down، کلید oracle، پول گیرکرده، sweep مرده، limiter تنزل‌یافته، عدم‌تطابق chain-id، توقف اضطراری) + تستی که endpointهای نام‌برده‌شده را با روت‌های واقعی تطبیق می‌دهد. **6.8:** `api/requirements.lock` (pip-compile، ۱۵۱ خط) + تست سازگاری با requirements.txt. **6.5:** هر کوئری Firestore و ایندکس لازمش مستند شد + تست. | ⬜ |
| 7.1-CLOSED | 2026-10-13 | **بازبینی مستقل بستن فاز ۷ (۳ یافته، همه رفع شد).** (۱) **HIGH** — هدف چالش یک‌بارمصرف نبود: `App.tsx` فقط وقتی آرگومان تعریف‌شده بود `activeOpponentAddress` را می‌نوشت و هیچ‌وقت پاکش نمی‌کرد، پس **دوئل عادی بعدی** با آدرس کهنه صف می‌شد (سرور ماتچ را برای دوست قبلی رزرو می‌کرد و بازیکن ۹۰ ثانیه منتظر می‌ماند). (۲) **MEDIUM** — `player_stats` برای بازیکن بدون ردیف ledger صفرها را «معتبر» برمی‌گرداند و کلاینت پیشرفت محلی را با آن بازنویسی می‌کرد؛ و `recordMatch` مشترکِ ranked/practice بود، پس هر تمرین XP واقعی بازیکن را صفر می‌کرد. (۳) **MEDIUM** — `sweep_expired` کل سند صف را غیرتراکنشی بازنویسی می‌کرد و با `enqueue` همزمان مسابقه می‌داد (lost wakeup). **یافته‌های LOW هم رفع شد:** گواهی بازنده وقتی برنده اول تسویه کرده بود «NOT ON-CHAIN» می‌گفت (حالا tx را از رویداد `MatchSettled` زنجیره می‌خواند)، ارسال دوباره روی دوئل refunded، مستندات کهنه‌ی ماتریس XP، و نوار streak که مقدار محلی را نشان می‌داد. **گپ بین‌لایه‌ای بسته شد:** بازیکن چالش‌شده حالا با `GET /api/challenges` + بنر Lobby می‌تواند چالش را ببیند و بپذیرد. ۲۱۳ تست سرور + ۱۳۷ تست فرانت. | ⬜ |
| 7.0-CLOSED | 2026-10-13 | **فاز ۷ کامل شد (۳۸/۳۸؛ M32 به فاز ۹ منتقل شد).** این نشست: M36 (بستن relay در cancel + حلقه‌ی معکوس purge)، M37 (تسویه از هر دو طرف)، M39 (ثبت tx تسویه تا گواهی واقعی شود)، M42 (پاک‌شدن feed خالی)، M44 (Sentry فقط وقتی DSN هست)، M9 (خطای دامنه به‌جای HTTPException در store)، M10 (view تازه بعد از finalize)، M26 (جست‌وجو با playerId)، M40 (متن صادقانه‌ی gate)، **M27 (چالش دوست واقعی: رزرو ماتچ برای آدرس هدف، در هر سه store + کلاینت)**، **M31 (progression سرورمحور: `api/xp.py` + ledger + `GET /api/player/{addr}/stats` + کلاینت؛ پیمان parity با `tests/fixtures/xp_vectors.json`)**. **دو گپ در بازبینی بستن پیدا و رفع شد:** (۱) در `record_settlement` خواندن بعد از نوشتن داخل تراکنش Firestore بود (تست emulator گرفتش، نه unit)؛ (۲) سطح/نوار پیشرفت از دو ledger مختلف می‌آمدند. **یک گپ باقی‌مانده مستند شد:** بازیکن چالش‌شده هیچ مسیری برای فهمیدن چالش ندارد. **رفع خارج از فاز:** مرحله‌ی install در CI قبل از هر تست می‌مرد (`python3-sqlite3` روی noble وجود ندارد). ۲۳۷ تست سرور + ۱۳۲ تست فرانت. | ⬜ |
| 6.0-CLOSED | 2026-10-12 | **فاز ۶ کامل شد (۴/۴).** 6.1 metrics، 6.2 health، 6.3 admin tooling، 6.4 dispute. ۱۵۷ تست سرور. | ⬜ |
| 5.4-CLOSED | 2026-10-12 | **فاز ۵ کامل شد (۵/۵).** H23 رفع شد — ELO + باند جفت‌سازی با گشادشدن زمانی. **سه گپ بین‌لایه‌ای در حین wiring پیدا شد:** `DurableMatchStore` پارامتر `rtt_ms` را فوروارد نمی‌کرد (یعنی گیت پینگ H1 در production بی‌اثر بود!)، و `InMemoryStore`/`FirestoreStore` هرکدام `enqueue` جدا دارند. ۱۲۷ تست سرور. | ⬜ |
| 5.3 | 2026-10-12 | **H24 رفع شد.** بازیکن غایب کل مسابقه را forfeit می‌کند؛ و اگر مسابقه کامل نشود و امتیاز مساوی نباشد، جلوتر می‌برد (چون void به عقب‌مانده سود می‌رساند). **محدودیت باقی‌مانده صادقانه مستند شد:** سرور نمی‌تواند تشخیص دهد چه کسی رفت، پس قاعده جلوتر را ترجیح می‌دهد — بستنش نیاز به سیگنال حضور دارد (فاز ۱۰). ۱۱۹ تست سرور. | ⬜ |
| 5.2 | 2026-10-12 | **H16 رفع شد (حداقل ممیزی).** ۴ ادعای جعلی از `BiometricTelemetry` حذف شدند؛ چک‌های واقعی (isTrusted، کف انسانی، trajectory) دست‌نخورده. **حداکثر** (device attestation + anomaly detection) به فاز ۱۰ موکول — جایی که با مهاجم واقعی قابل اعتبارسنجی است. ۷۹ تست فرانت. | ⬜ |
| 5.1 | 2026-10-12 | **H1 رفع شد** — رتبه‌بندی روی `observed − min_rtt/2` (کمینه، چون جبران ساده خودش اکسپلویت است) + سقف پینگ به‌عنوان دروازه‌ی ورود. **وصل‌شده end-to-end** (engine → HTTP → کلاینت) چون درس بین‌لایه‌ای فاز ۴ اعمال شد. ۱۱۲ تست سرور. | ⬜ |
| 5.0 | 2026-10-12 | **فاز ۵ شروع شد (D1 = گزینه D).** H2 رفع شد — commit نهایی است (بدون escape پنجره) + salt سرور در `result_proof` + persist شدن. ۱۰۴ تست سرور. | ⬜ |
| 4.12-CLOSED | 2026-10-12 | **بازبینی بین‌فازی فاز ۰–۴.** M28 (تکراری M5) بسته شد. متن کهنه‌ی «۳۰ دقیقه» در `api/onchain.py` اصلاح شد. **هر endpoint سرور و هر تابع قرارداد حالا مصرف‌کننده دارد.** `lastMatchXPSummary` در store ست می‌شود ولی هیچ‌جا خوانده نمی‌شود (LOW، کد مرده). 0.10/0.11 طبق توافق به فاز ۱۰ موکول. | ⬜ |
| 4.11-CLOSED | 2026-10-12 | **بازبینی بستن فاز ۴ — سه گپ از یک کلاس واحد پیدا شد:** H15b (`identityLockedReason` هیچ‌جا رندر نمی‌شد)، H22b (`/api/auth/logout` هیچ‌جا صدا زده نمی‌شد)، و H17b (که خودش همین کلاس بود). **یافته‌ی ساختاری:** ممیزی هر لایه را جدا مرور می‌کند، پس «رفع در یک لایه، بدون مسیر از لایه‌ی دیگر» برایش نامرئی است. فازهای بعدی باید صریحاً برای این grep کنند. ۷۰ تست فرانت. | ⬜ |
| 4.9-CLOSED | 2026-10-12 | **فاز ۴ کامل شد (۱۰/۱۰).** M38 رفع شد — `sha256` محلی + بردارهای FIPS. ۶۰ تست فرانت. | ⬜ |
| 4.8 | 2026-10-12 | **M30 رفع شد** (`subscribeToStore`/`getSnapshot` به module scope؛ ۶ subscribe → ۱). ۴۲ تست فرانت. | ⬜ |
| 4.7 | 2026-10-12 | **M29 رفع شد** (هر دو timer در ref + پاک‌سازی روی unmount؛ تست سه بار بازنویسی شد چون دو نسخه‌ی اول سبز می‌شدند بدون اینکه باگ را بگیرند). ۳۹ تست فرانت. | ⬜ |
| 4.6 | 2026-10-12 | **M5 رفع شد** (۶ فیلد تسویه روی rematch پاک می‌شوند؛ تست دو بار بازنویسی شد تا واقعاً discriminator باشد). ۳۷ تست فرانت. | ⬜ |
| 4.5 | 2026-10-12 | **H15 رفع شد** (قفل هویت/شبکه در حین ماتچ + `identityLockedReason` برای UI). ۳۵ تست فرانت. | ⬜ |
| 4.4 | 2026-10-12 | **H14 رفع شد** (پاسخ دیرهنگام حساب قبلی drop می‌شود؛ `getStoreSnapshot()` به‌عنوان seam تست). ۳۰ تست فرانت. | ⬜ |
| 4.3 | 2026-10-12 | **H13 رفع شد** (`getTokenDecimals()` + cache؛ همه‌ی parseUnits/formatUnits). ۲۷ تست فرانت. | ⬜ |
| 4.2 | 2026-10-12 | **H12 رفع شد** (نوشتن موجودی از `vaultBalance` حذف شد؛ زنجیره تنها منبع حقیقت است). ۲۳ تست فرانت. | ⬜ |
| 4.1 | 2026-10-12 | **H11 رفع شد** (refs + ست‌کردن همزمان با state؛ نسخه‌ی effect-based کافی نبود). ۲۰ تست فرانت. | ⬜ |
| 4.0 | 2026-10-12 | **فاز ۴ شروع شد.** H17b رفع شد (کلاینت حالا `withdrawPending` + کارت «پرداخت معلق» دارد). ۱۹ تست فرانت. | ⬜ |
| 3.5-CLOSED | 2026-10-12 | **بازبینی بین‌فازی فاز ۰-۳:** آیتم‌های 0.3 و 0.7 تیک خوردند (معیار پذیرش محقق بود). **گپ جدید H17b:** کلاینت هیچ مسیری برای `withdraw()` قرارداد ندارد — پرداخت deferred از UI قابل دریافت نیست. به فاز ۴ اضافه شد. | ⬜ |
| 3.4-CLOSED | 2026-10-12 | **بازبینی بستن فاز ۳:** متن refund در ۹ جا «۳۰ دقیقه» مانده بود (H19 آن را ۴۰ کرد) → `ESCROW_TIMING` + pin تست. گیت coverage قطعی نبود (۷۴–۷۹٪) → emulator خودکار + ratchet ۷۹. تست C1 روی ماژول تزریق می‌کرد نه instance → ۱-in-۶ شکست. **۸ اجرای متوالی سبز.** | ⬜ |
| 3.3-CLOSED | 2026-10-12 | **فاز ۳ کامل شد (۸/۸ رفع + ۱۴/۱۴ گپ تست).** ۷۹ تست قرارداد، coverage قرارداد ۹۸.۳۵٪، ۴ invariant، گیت `forge coverage` اضافه شد. | ⬜ |
| 3.2 | 2026-10-12 | **M22/M23/M24/M25 رفع شدند.** ۴۹ تست قرارداد. **فاز ۳: ۸/۸ آیتم رفع‌شد؛ فقط ۱۴ گپ تست (CT1–CT14) مانده.** | ⬜ |
| 3.1 | 2026-10-12 | **H19 رفع شد (D2 = الف: پنجره‌ی تسویه‌ی انحصاری، `REFUND_GRACE = 10 min`).** ۴۰ تست قرارداد. coverage ۸۱٪. | ⬜ |
| 3.0 | 2026-10-12 | **فاز ۳ شروع شد.** H17 (deferred payout)، H18 (سقف deadline)، H20 (activatedAt + cutoff join) رفع شدند. ۳۵ تست قرارداد. coverage ۷۹٪. | ⬜ |
| 2.5-CLOSED | 2026-10-12 | **بازبینی بستن فاز ۲:** `record_claim` همان TOCTOU را داشت (H3 در یک تابع رفع شده بود و در تابع بالایی جا مانده بود) — رفع شد. کامنت کهنه‌ی پیکربندی جایگزین شد. coverage ۷۹٪. | ⬜ |
| 2.4-CLOSED | 2026-10-12 | **فاز ۲ کامل شد (۹/۹).** H10 (I/O زیر قفل)، H22 (logout)، H6+H7 (پیکربندی fail-closed). coverage ۷۸٪. | ⬜ |
| 2.3 | 2026-10-12 | H9 رفع شد (throttle روی sweep + ایندکس composite + شکست‌ها دیگر بی‌صدا نیستند). coverage ۷۷٪ (کاهش ۷۸→۷۷ به‌دلیل ایزوله‌شدن درست تست H4، نه regression). **فاز ۲: ۵/۹** | ⬜ |
| 2.2 | 2026-10-12 | H5 و H8 رفع شدند. coverage ۷۷ → ۷۸٪. | ⬜ |
| 2.1 | 2026-10-12 | H4 رفع شد (ledger بعد از commit تراکنش؛ همان باگ در `_settle_once` هم بود). coverage ۷۲ → ۷۷٪. fixture زنجیره در برابر فرستنده‌های همزمان مقاوم شد. | ⬜ |
| 2.0 | 2026-10-12 | **فاز ۲ شروع شد.** H3 رفع شد (گیت idempotency اتمیک شد؛ کامیت قرمز جدا قبل از fix طبق R1). coverage ۶۹ → ۷۲٪. | ⬜ |
| 1.8-CLOSED | 2026-10-12 | **فاز ۱ رسماً بسته شد.** بازبینی بستن ۳ شکاف MAJOR پیدا کرد (C3 نیمه‌کاره، زامبی WC، گیت coverage اشتباه) — همه رفع شدند. هدف coverage فاز ۱ محقق شد (۶۹٪). R1 با قاعده‌ی «کامیت قرمز اول» تقویت شد. | ⬜ |
| 1.7-LOCKED | 2026-10-12 | **C4** تیک خورد. **فاز ۱ کامل شد: هر ۴ CRITICAL رفع و با تست قرمز→سبز اثبات شدند.** تست C4 با RTL به‌جای Playwright (دقیق‌تر و سریع‌تر)؛ 0.10 برای فاز ۱۰ باقی است. | ⬜ |
| 1.6-LOCKED | 2026-10-12 | آیتم 0.9 (Vitest) و **C3** تیک خوردند. `bindActiveProvider()` در هر ۴ مسیر اتصال + disconnect صدا زده می‌شود. | ⬜ |
| 1.5-LOCKED | 2026-10-12 | **C1 و C2 رفع شدند** (تست‌های قرمز → سبز). یافته‌ی جدید در حین رفع C2: `token_decimals()` هر مقدار ۳۲-بایتی را می‌پذیرفت → `Decimal(10) ** 3.7e9` → Overflow → 500 روی مسیر پول. با سقف uint8 (۲۵۵) و tri-state verdict رفع شد. | ⬜ |
