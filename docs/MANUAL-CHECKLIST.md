# چک‌لیست دستی — از صفر تا «اپ آمادهٔ تست واقعی»

**هدف این سند:** هر کاری که در sandbox انجام نشد (یا نمی‌شد) و فقط روی ماشین تو معنا دارد، به‌صورت
**گام‌به‌گام، با دستور دقیق، خروجی مورد انتظار، و معنای شکست**. هر گام یک چک‌باکس دارد.

> **نسخهٔ عملیاتی:** همین مسیر، ولی ریزتر و با چک‌باکسِ هر قدم، در **`docs/USER-TODO.md`** است
> (۱۲ فاز، ۸۰ قدم، با «شرط عبور» برای هر فاز). اگر فقط یکی را می‌خوانی، آن یکی.

**قاعده:** اگر خروجی با «انتظار» یکی نبود، **متوقف شو** و به بخش ۱۰ برو. عدد را عوض نکن تا سبز شود؛
عددِ متفاوت یعنی محیط تو با این محیط فرق دارد و باید بفهمی کدام.

**زمان کل:** ۲ تا ۳ ساعت برای گام‌های ۰ تا ۶ (استک محلی) + نیم‌روز برای Amoy + یک روز برای دو گوشی.

---

## گام ۰ — پیش‌نیازها (۱۵ دقیقه) ⬜

| # | دستور | انتظار |
|---|---|---|
| 0.1 | `node -v` | `v20.x` یا بالاتر (این مخزن با v22 آزمایش شده) |
| 0.2 | `python3 -V` | `3.11.x` |
| 0.3 | `forge --version` | `forge 1.7.1` یا بالاتر. اگر نبود: `curl -L https://foundry.paradigm.xyz \| bash && foundryup` |
| 0.4 | `java -version` | `17+` — **فقط** اگر Firestore emulator می‌خواهی (گام ۳) |
| 0.5 | `firebase --version` | `13.x` — همان شرط. `npm i -g firebase-tools` |
| 0.6 | `git clone … && cd PUL_SKILL` | شاخهٔ `arena/a9a25b53-pul-skill` |

```bash
cd PUL_SKILL
npm ci
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.lock -r api/requirements-dev.txt
cd contracts && git clone --depth 1 -b v1.9.7 https://github.com/foundry-rs/forge-std lib/forge-std \
  && git clone --depth 1 -b v5.7.0 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts && cd ..
```

> **اگر شکست خورد:** `npm ci` به `package-lock.json` وفادار است؛ اگر خطای شبکه داد تکرار کن.
> `solc` ۰٫۸٫۲۰ از `node_modules/solc` می‌آید و forge خودش آن را پیدا می‌کند؛ اگر پیدا نکرد،
> `FOUNDRY_SOLC=$(which solc)` را ست کن.

---

## گام ۱ — گیت‌های اتوماتیک روی ماشین تو (۲۰ دقیقه) ⬜

```bash
bash scripts/verify.sh
```

این اسکریپت **۲۲ گیت** را به ترتیب اجرا می‌کند (و ۱۶ جای دیگر `skip_gate` با دلیل دارد). جدول انتظار (اعداد امروز، روی همین کامیت):

| گیت | انتظار | اگر شکست |
|---|---|---|
| `tsc --noEmit` | ۰ خطا | خطای تایپ = تغییرِ ناتمام در کد؛ خروجی را بخوان |
| `vitest run` | **۳۵۷ تست / ۷۱ فایل** | تست شکسته یعنی رفتار عوض شده؛ عدد را پایین نیاور |
| `ruff check` / `mypy` (api + scripts) | پاک / `no issues in 39 files` | خطای تایپ در پایتون = قرارداد شکسته |
| `pytest` (coverage هرمتیک) | **≥ ۷۸٪** (امروز **۷۹٪**، ۴۳۱۸ statement) | افت پوشش = کد جدید بدون تست |
| `pytest` کامل | **۷۰۶ pass / ۲۵ skip** با anvil و API؛ ۷۰۱/۳۰ بدون | skip بیشتر از ۳۰ = سرویس لازم بالا نیست |
| `forge test` | **۱۰۷ تست / ۱۰ سوئیت** | اگر کامپایل نشد، `lib/` را چک کن (گام ۰) |
| contract coverage | **≥ ۹۵٪** خطوط (امروز ۹۸٫۵۷٪) | — |
| Playwright | **≥ ۲۰ تست** | اگر مرورگر نصب نیست، گام ۴ را اول بزن |
| live-stack | سبز (API روی ۸۰۰۰) | پورت اشغال است — `start_e2e_stack.sh --stop` |

> گیت‌هایی که سرویس لازم دارند (emulator، time-travel، Playwright) اگر سرویس نباشد **SKIP با دلیل**
> می‌دهند، نه سبزِ بی‌صدا. اگر `verify.sh` با کد ۰ تمام شد ولی یکی از این‌ها SKIP بود، آن گیت هنوز
> اجرا نشده — گام‌های ۳ و ۴ همان‌ها را می‌بندند.
>
> **عدد مرجع (اندازه‌گیری‌شده ۲۰۲۶-۱۰-۲۴):** در محیطی بدون Java و بدون مرورگر، با
> `PULSAR_E2E_STORE=memory bash scripts/verify.sh` نتیجه **۱۷ pass / ۴ fail / ۱ skip** بود و هر چهار
> شکست یک علت داشتند: نبودِ Firestore emulator (که `live-stack`، `chaos` و `runbook drill` را هم
> می‌خواباند) و نبودِ مرورگر Playwright. روی ماشین تو با گام ۳ و ۴، همهٔ ۲۲ گیت باید سبز شود.
>
> **بهبود بعدی:** گیتِ `chaos` دیگر «اجرا نشد» را با «غلط است» یکی نمی‌کند — پنج سناریو با دلیل `SKIP`
> می‌شوند و `verify.sh` آن را `⏭ SKIP` می‌نویسد، نه `PASS`. پس بعد از گام ۳ اگر `chaos` هنوز `SKIP`
> بود یعنی emulator بالا نیامده؛ اگر `FAIL` بود، واقعاً یک نقص است.

---

## گام ۲ — استک محلی با پول شبیه‌سازی‌شده (۱۵ دقیقه) ⬜

```bash
bash scripts/start_anvil.sh --bg          # ترمینال ۱
# خروجی: token=0x…  escrow=0x…  manifest=contracts/deployments/local.json

PULSAR_MATCH_STORE=memory bash scripts/start_e2e_stack.sh   # ترمینال ۲
```

| بررسی | دستور | انتظار |
|---|---|---|
| API زنده | `curl -s localhost:8000/api/health \| jq '{ok,chainId,escrowConfigured,rpc}'` | `ok:true`, `chainId:31337`, `escrowConfigured:true`, `rpc.reachable:true` |
| مسیر پول روی EVM واقعی | `.venv/bin/python -m pytest -q -m chain` | **۱۱ passed** |
| کلاینت | مرورگر → `http://localhost:3000` | صفحهٔ اصلی؛ هیچ خطای کنسولِ قرمز |

کیف پول برای anvil: شبکهٔ `http://127.0.0.1:8545` با chainId `31337`؛ یکی از کلیدهای چاپ‌شدهٔ anvil را
import کن (پول تستی دارد).

> **اگر `escrowConfigured:false` شد:** manifest پیدا نشده — `start_anvil.sh` را دوباره بزن و خروجی
> `escrow=` را در `ESCROW_ADDRESS` بگذار.

---

## گام ۳ — Firestore emulator: تنها گیتی که این محیط هرگز اجرا نکرد (۳۰ دقیقه) ⬜

این گام مهم‌ترین گامِ «انجام‌نشده» است: ۱۰ تست `-m firestore` و کل مسیر `store.py` که در production
استفاده می‌شود، در sandbox به‌خاطر نبود Java اجرا نشدند.

```bash
bash scripts/start_emulator.sh --bg
curl -s localhost:8081 | head -c 80          # پاسخ emulator

FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 GCLOUD_PROJECT=demo-pulsar \
  .venv/bin/python -m pytest -q -m "emulator or firestore"
```

| بررسی | انتظار | اگر شکست |
|---|---|---|
| تست‌های emulator | **۱۷ passed، ۰ skip** | هر شکست یک باگ واقعی در مسیر production است — گزارش کن |
| store پایدار بالا می‌آید | `PULSAR_MATCH_STORE=firestore` + restart استک | اگر «REFUSING» داد، env ناقص است نه کد |
| `store.writable` | `curl -s 'localhost:8000/api/health?deep=1' \| jq .probe.store` | بعد از یک دوئل: `{ok:true, writable:true}`؛ هرگز `null` در production |
| سناریوهای chaos | `.venv/bin/python scripts/chaos_suite.py` (نام‌ها: `rpc_kill`, `firestore_kill`, `rpc_delay`, `replica_split`, `soak`) | سناریوهای RPC سبز؛ `firestore_kill` **فقط با emulator بالا** معنا دارد |

---

## گام ۴ — Playwright: ۳۰ تستی که هرگز اجرا نشدند (۲۰ دقیقه) ⬜

```bash
npx playwright install --with-deps chromium
npm run test:e2e
```

| انتظار | معنی |
|---|---|
| **۳۰ passed، ۰ skipped** | مسیرهای واقعی مرورگر (اتصال، دوئل، بنرها) سالم‌اند |
| `< 20 passed` | `verify.sh` خودش این را شکست می‌دهد — skip پوشش نیست |
| خطای `browserType.launch` | فقط اگر `install` ناقص مانده باشد |

> اگر روی موبایل واقعی هم می‌خواهی: `npx playwright test --project=mobile` (پروژهٔ `mobile` در `playwright.config.ts` تعریف شده).

---

## گام ۵ — یک دوئل کامل دستی با پول (۴۵ دقیقه) ⬜

دو پروفایل مرورگر (یا دو دستگاه) با دو کیف پول. هر دو ≥ ۱۰ USDT و کمی POL برای گس.

| # | کار | انتظار |
|---|---|---|
| 5.1 | اتصال کیف پول | آدرس کوتاه‌شده در هدر؛ `balanceUnknown:false` |
| 5.2 | انتخاب استیک ۵ | دکمهٔ ورود فعال؛ اگر موجودی < ۵ باشد **بلاک** با پیام «موجودی ناکافی» (H-27) |
| 5.3 | تأیید approve | تراکنش approve در کیف پول؛ بعد از آن `allowance ≥ stake` |
| 5.4 | هر دو وارد صف | شمارش معکوس؛ سرور حریف را جفت می‌کند |
| 5.5 | ۳ راند | برندهٔ هر راند سمت سرور تعیین می‌شود (نه کلاینت) |
| 5.6 | settle | تراکنش `settleDuel` با امضای اوراکل؛ در explorer رویداد `MatchSettled` |
| 5.7 | موجودی برنده | **+۹۸٪ از کل استخر** (۹٫۸ از ۱۰ برای استیک ۵) |
| 5.8 | treasury | **+۲٪** (۰٫۲) |
| 5.9 | claim در سرور | `/api/health` → `ledger.failures.total == 0` |
| 5.10 | تاریخچه | یک ردیف، با هش واقعی؛ XP و لیدربورد به‌روز |

> **عدد ۹۸/۲ را از قرارداد بخوان، نه از UI:** `cast call $ESCROW "PLATFORM_FEE_BPS()(uint256)"`.

---

## گام ۶ — سناریوهای شکست (۳۰ دقیقه) ⬜

| # | سناریو | چگونه | انتظار |
|---|---|---|---|
| 6.1 | رد کردن تراکنش در کیف پول | در مودال کیف پول «Reject» | پیام «لغو شد — هیچ پولی جابه‌جا نشد»؛ **هیچ** ردیفی در تاریخچه (H-22/H-26) |
| 6.2 | RPC مرده | `ESCROW_RPC_URL=http://127.0.0.1:9` و restart API | `health.rpc.reachable:false`؛ کلایم ۵۰۳/۵۰۴ می‌دهد نه ۵۰۰؛ هیچ پرداخت نصفه‌ای |
| 6.3 | کیف پول بدون گس | POL صفر کن | پیام روشن «گس کافی نیست»؛ استیک قفل نمی‌شود |
| 6.4 | بستن تب برنده | بعد از settle، تب را ببند | `.venv/bin/python scripts/keeper.py --once` (dry-run) تراکنش را نشان می‌دهد؛ با `--execute` جایزه پرداخت می‌شود |
| 6.5 | timeout | ۳۰ دقیقه + ۱۰ دقیقهٔ گریس صبر (یا `vm.warp` روی anvil) | `refundTimeoutMatch` هر دو طرف را برمی‌گرداند |
| 6.6 | replay امضا | همان هش settle را دوباره بفرست | revert؛ هیچ پرداخت دومی |
| 6.7 | کلایم با هش جعلی | `POST /api/claim` با tx هش تصادفی | ۴۰۰/۴۲۲؛ ردیف ساخته نمی‌شود (H-26) |

---

## گام ۷ — Amoy: اولین تراکنش واقعی (نیم‌روز) ⬜

```bash
# ۷.۱ دیپلوی — سه نام env که Deploy.s.sol واقعاً می‌خواند:
cd contracts
DEPLOYER_PRIVATE_KEY=0x… TREASURY_ADDRESS=0x… ORACLE_SIGNER_ADDRESS=0x… \
  forge script script/Deploy.s.sol --rpc-url "$AMOY_RPC" --broadcast
# خروجی: آدرس PulsarEscrow و MockUSDT را بردار
# توجه: سرور همین آدرس را با نام ORACLE_ADDRESS می‌خواند — همان آدرس، دو اسم.

# ۷.۲ env سرور (لیست کامل در .env.example)
PULSAR_ENV=production PULSAR_MATCH_STORE=firestore \
ESCROW_ADDRESS=0x… ESCROW_RPC_URL=https://rpc-amoy… ORACLE_CHAIN_ID=80002 \
ORACLE_SIGNING_SECRET=… ADMIN_SECRET=… ALLOWED_HOSTS=… CORS_ALLOW_ORIGINS=… \
  .venv/bin/uvicorn main:app --app-dir api --host 0.0.0.0 --port 8000

# ۷.۳ env کلاینت
VITE_CHAIN_ID=80002 VITE_ESCROW_ADDRESS=0x… VITE_PAYMENT_TOKEN_ADDRESS=0x… \
VITE_GAME_SERVER_URL=https://api.example.com VITE_WALLETCONNECT_PROJECT_ID=… npm run build
```

| # | بررسی | انتظار |
|---|---|---|
| 7.4 | `curl /api/health` | `escrowConfigured:true`, `rpc.reachable:true`, `chainId:80002`, `escrowVersion:"2.0.0"` |
| 7.5 | `curl '/api/health?deep=1'` | `probe.store.writable:true` (نه `null`) |
| 7.6 | faucet | دو کیف پول ≥ ۱۰ USDT تستی + ۰٫۵ POL |
| 7.7 | یک دوئل کامل روی Amoy با دو گوشی | همان جدول گام ۵ |
| 7.8 | Explorer | `MatchSettled` + انتقال ۹۸/۲ |
| 7.9 | keeper | `.venv/bin/python scripts/keeper.py --once --execute` روی staging (env: `ESCROW_RPC_URL`, `KEEPER_PRIVATE_KEY`) |

> **دام واقعی:** کیف پول موبایل روی HTTP کار نمی‌کند. دامنه + HTTPS اجباری است (گام ۸.۱).

---

## گام ۸ — دو گوشی واقعی: iOS + Android (یک روز) ⬜

| # | بررسی | انتظار | اگر شکست |
|---|---|---|---|
| 8.1 | باز کردن دامنهٔ HTTPS روی هر دو | بدون هشدار گواهی | گواهی/دامنه |
| 8.2 | اتصال WalletConnect | کیف پول باز می‌شود، برمی‌گردد، آدرس نمایش داده می‌شود | Project ID یا deep link |
| 8.3 | سوئیچ شبکه به Amoy | `chainId 80002` در هدر | افزودن شبکه |
| 8.4 | approve USDT | تراکنش تأیید در اپ کیف پول | allowance |
| 8.5 | دوئل کامل دو نفره | ۳ راند، settle، claim | — |
| 8.6 | چرخش صفحه و صفحه‌کلید | چیدمان نمی‌شکند | CSS |
| 8.7 | فارسی/عربی (RTL) | کل متن راست‌به‌چپ؛ اعداد لاتین یکسان (حسابرسی i18n) | — |
| 8.8 | ترک اپ وسط دوئل | بازگشت: وضعیت بازیابی می‌شود یا void اعلام می‌شود | — |
| 8.9 | قطع اینترنت در راند ۲ | پیام روشن؛ پول در escrow می‌ماند | — |
| 8.10 | حالت تاریک/روشن و فونت | خوانا | — |
| 8.11 | نصب PWA (Add to Home) | آیکون و splash | manifest |
| 8.12 | اعلان‌ها (اگر فعال) | — | — |
| 8.13 | کیف پول بدون گس | پیام روشن، بدون قفل پول | — |
| 8.14 | دو گوشی هم‌زمان، یک دوئل | مسابقهٔ هم‌زمان درست جفت می‌شود | — |

---

## گام ۹ — Keeper روی staging ⬜

```bash
.venv/bin/python scripts/keeper.py --once    # dry-run: فقط نشان می‌دهد چه می‌فرستد
# بعد از تأیید:
KEEPER_PRIVATE_KEY=0x… .venv/bin/python scripts/keeper.py --once --execute
```

| بررسی | انتظار |
|---|---|
| جایزهٔ تب‌بسته | خودکار settle می‌شود، پول به برنده می‌رود |
| دوئل رهاشده | بعد از ۳۰+۱۰ دقیقه refund هر دو |
| اجرای دوباره | چیزی نمی‌فرستد (idempotent) |
| کیف پول keeper | فقط گس خرج می‌کند، هرگز پول بازیکن نمی‌گیرد |

---

## گام ۱۰ — معیار Go / No-Go ⬜

| شرط | حداقل |
|---|---|
| گام ۱ (همهٔ گیت‌ها) | سبز، بدون SKIP در گیت‌های الزامی |
| گام ۳ (emulator) | ۱۷ تست pass + `store.writable:true` |
| گام ۴ (Playwright) | ۳۰ تست pass |
| گام ۵ (دوئل دستی) | ۹۸/۲ دقیق، بدون اختلاف یک واحد |
| گام ۶ (شکست‌ها) | هر ۷ سناریو رفتار مشخص |
| گام ۷ (Amoy) | یک دوئل واقعی با دو گوشی |
| گام ۸ | ۱۴ مورد، بدون مورد باز |
| ممیزی بیرونی قرارداد | **گزارش امضا شده** |
| KYC/ژئوبلاک/سقف برداشت | تصمیم مستند (`docs/COMPLIANCE-C-02c.md`) |

**اگر یکی از دو مورد آخر نبود = No-Go برای پول واقعی.** با تست‌نت می‌توانی ادامه بدهی.

---

## ۱۱. اگر چیزی خراب شد

| نشانه | معنی | کار |
|---|---|---|
| `pytest` عدد کمتری از ۶۶۵ داد | سرویس بالا نیست یا محیط فرق دارد | `-rs` بزن و دلیل skip‌ها را بخوان |
| `coverage` زیر ۷۷ | کد جدید بدون تست | تست بنویس، کLOOR را پایین نیاور |
| `execution reverted` در settle | deadline گذشته یا chainId/escrow غلط | `docs/CONTRACT-FUZZ-REPORT.md §4` و لاگ تست `chain_smoke` |
| `escrowConfigured:false` | manifest/env | `start_anvil.sh` یا `ESCROW_ADDRESS` |
| کلایم ۵۰۰ می‌دهد | RPC یا رسید بدشکل | `docs/INCIDENT-RUNBOOK.md` |
| گوشی وصل نمی‌شود | HTTP یا Project ID | HTTPS + `VITE_WALLETCONNECT_PROJECT_ID` |

منابع: `docs/INCIDENT-RUNBOOK.md` · `docs/GO-LIVE-RUNBOOK.md` · `docs/COVERAGE-REPORT.md` ·
`docs/I18N-AUDIT.md` · `docs/CONTRACT-FUZZ-REPORT.md` · `docs/audit/REMEDIATION-TODO-2026-10-22.md`
