# Operational checklist — از verify محلی تا readiness جهانی

**این سند جای `docs/USER-TODO.md` (فاز ۰–۱۱) و `scripts/verify.sh` (گیت‌ها) را در هم می‌زند** و
**وضعیت هر قدم و تست را در برابر ماشینِ واقعیِ این جلسه (۲۰۲۶-۱۱-۰۷، `arena/a9a25b53-pul-skill`)**
**نشان می‌دهد.** خروجی آن: «مرحله و قدم بعدی» + «تا محصول اماده و جهانی چی شد».

---

## ۱. وضعیت فعلی — خلاصهٔ گیت‌ها (این جلسه، روی این ماشین)

| # | Gate | وضعیت | دلیل |
|---|---|---|---|
| 1 | typecheck (tsc --noEmit) | ✅ PASS | ۰ خطا |
| 2 | frontend unit (vitest) | ❌ FAIL | worker fork crash (`STATUS_DLL_INIT_FAILED`) — environment |
| 3 | ruff | ✅ PASS | via `.venv` |
| 4 | mypy (api+scripts) | ✅ PASS | 39 file، 0 issues — via `.venv` |
| 5 | pytest hermetic + coverage (fail_under 79) | ❌ FAIL (9F+7E) / ⚠️ ۷۹٪ | 787 passed؛ coverage در کف (۷۹٪) |
| 6 | legacy protocol | ✅ PASS | |
| 7 | legacy HTTP E2E | ❌ FAIL | `Round 2 accepted for Bob` |
| 8 | probe_a5 | ❌ FAIL | UnicodeEncodeError (cp1252) — environment |
| 9 | probe_a6 / probe_a8 | ✅ PASS | |
| 10 | forge test | ✅ PASS | 101/101 |
| 11 | chain tests (anvil+escrow) | ✅ PASS | 11/11 — anvil (`0x7a69` = 31337) بالا بود |
| 12 | contract coverage (≥95%) | ✅ PASS | 98.57% lines |
| 13 | solc compile gate | ✅ PASS | solc 0.8.20 |
| 14 | browser E2E (playwright, ≥20) | ⏭ SKIP | Playwright/مرورگر در این ماشین نبود |
| 15 | live-stack integration (ranked flow) | ❌ FAIL → ✅ duel | memory store باعث skip+fail شد؛ بعد driver دستی → **DUEL_OK** |
| 16 | refund after timeout | ✅ PASS | 2/2 |
| 17 | alerting / runbook drill / chaos | ⚠️ | drill crash (`pkill` missing) |

**نتیجهٔ جعبهٔ پیوسته:** روی این workstation، لایهٔ قرارداد+رشته 🟢، لایهٔ پول (duel واقعی) 🟢،
لایهٔ سرور 🟡 (hermetic pytest + legacy E2E قرمز)، لایهٔ فرانت 🟡 (اجرا نشد).

## ۲. چک‌لیست عملیاتی — فازها ۰ تا ۱۱ و وضعیت

### فاز ۰ — پیش‌نیازها
- [ ] 0.1–0.7: مخزن + branch + node + python(3.11+ / اینجا .venv 3.12) + foundry + npm ci + forge-std + OZ + (java برای فاز ۳).
- [ ] 0.8–0.9: سنجش کامپایل: forge build ✅ اینجا.
- **وضعیت:** ⚠️ ناقص — java و browser missing؛ forge/npm/venv ✅.

### فاز ۱ — گیت‌های خودکار
- [ ] `bash scripts/verify.sh` (کل ≥ 22 gates).
- [ ] gates اجرایی این جلسه: tsc ✅، ruff ✅، mypy ✅، hermetic ❌(9F+7E)، coverage ⚠️(۷۹٪)،
  legacy ✅/❌/probe ✅/✅، forge ✅، chain ✅، coverage ✅، solc ✅، e2e ⏸، live-stack ❌→duel ✅،
  refund ✅.
- **وضعیت:** 🟡 — vitest و durable-store-dependent gates و alerting-path gates ناقص/نامکمل.

### فاز ۲ — استک محلی (anvil + API + duel)
- [ ] start_anvil → start_e2e_stack (memory) → API :8000.
- [ ] **✅ کامل و سبز:** start_anvil (31337, escrow `0xe7f1725E…`) → stack → duel → settle → DUEL_OK.

### فاز ۳ — Firestore emulator
- [ ] java 17 + firebase-tools → `bash scripts/start_emulator.sh --bg` → 17 تست pass.
- **وضعیت:** ⏸ — **blocker جدید در این جلسه**: دانلود jar (`storage.googleapis.com/firebase-preview-drop/.../cloud-firestore-emulator-v1.19.8.jar`) با `AccessDenied` («service is not available in your location») ریjected شد؛ file هر بار ۱۹۳ بایت (XML error) بود. Java نصب شد ولی network این ماشین اجازهٔ download نمی‌دهد. بعد از بررسی مجدد network، دوباره اجرا کن.

### فاز ۴ — Playwright (۳۰ تست)
- [ ] `npx playwright install --with-deps chromium` → `npm run test:e2e` → ≥20 pass.
- **وضعیت:** ⏸ — مرورگر نبود.

### فاز ۵ — دوئل کامل دستی (۹۸/۲)
- [ ] ✅ **این جلسه انجام شد** — ۳ round accepted + settle + settlement log verified (DUEL_OK).

### فاز ۶ — ۷ سناریوی شکست
- [ ] replay/forged/void/refund-after-timeout/rpc-dead/… — بخشی اجرا شد (refund ✅، probes ✅/❌env).

### فاز ۷ — Amoy: پول واقعی
- [ ] دیپلوی + دوئل واقعی — ⏸ (کلید/اوراکل/تریسری نداشتیم).

### فاز ۸ — دو گوشی واقعی — ⏸
### فاز ۹ — keeper روی staging — ⏸
### فاز ۱۰ — ممیزی بیرونی + C-02c + treasury Safe + KMS — ⏸
### فاز ۱۱ — تعریف «تمام» — شرط عبور: هر ردیف بالا وضعیت خودش را داشته باشد.

## ۳. چک‌لیست عملیاتی — دستور نهایی برای «آماده و جهانی»

برای رسیدن از این state به global readiness، ترتیب اجرایی واقعی:

1. **ردیف ۳ (Firestore)** را ببند: `winget install --id Microsoft.OpenJDK.17Community -e` + firebase-tools؛ `bash scripts/start_emulator.sh --bg`؛ سپس `bash scripts/verify.sh` (فاز ۳ و gates بعدی).
2. **ردیف ۴ (Playwright)** را ببند: `npx playwright install --with-deps`; سپس `npm run test:e2e`.
3. **ردیف ۵ (vitest)**: یا اصلاح env (Node 20+ / fork config) یا اجرا روی ماشین سازگار.
4. **ردیف ۷ (legacy E2E)**: رفع failure `Round 2 accepted for Bob`.
5. **ردیف ۵ (hermetic pytest)**: تفکیک failure واقعی در api/ از failure مربوط به scripts/.
6. **فاز ۷**: Amoy rehearsal با DEPLOYER/ORACLE/TREASURY واقعی — کلیدهای موجود در اختیار.
7. **فاز ۱۰**: audit package، C-02c، treasury Safe، KMS، alerts staging.
8. **فاز ۱۱**: go/no-go — سپس deploy staging → prod.

## ۴. Go / No-Go نهایی (از USER-TODO فاز ۱۱)

- **Go برای تست واقعی (پول کوچک)**: فازهای ۱–۹ سبز + ۱۰.۳ + ۱۰.۴.
- **Go برای پول دیگران**: همهٔ بالا + ۱۰.۱ + ۱۰.۲.
- **بدون آن دو: No-Go** — حتی اگر ۹ فاز دیگر سبز باشند.

---

## ۵. قدم بعدی — خلاصهٔ اجرایی

۱. نصب Java + Playwright → اجرای gates باقی‌مانده (۳ و ۴) روی این ماشین.
۲. تفکیک failureهای hermetic pytest (real bug vs env).
۳. رفع/تحلیل failure `Round 2 accepted for Bob`.
۴. فاز ۷ (Amoy) با کلیدهای واقعی.
۵. بازگشت به USER-TODO فاز ۱۱ و ثبت نهایی.
