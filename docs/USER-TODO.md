# تودوی تو — از این کامیت تا «آمادهٔ تست واقعی»، ریز به ریز

**این سند فقط یک کار دارد:** هر چیزی که **من نمی‌توانم انجام بدهم** (چون به ماشین، کیف پول، گوشی،
حساب ابری یا تصمیم حقوقی تو وابسته است) را به قدم‌های کوچکِ قابل اجرا بشکند، به‌ترتیب وابستگی،
با دستور دقیق، خروجی مورد انتظار، و معنای شکست.

**قاعده‌های این سند (لطفاً نشکن):**

1. از بالا به پایین. هر فاز به فاز قبلی وابسته است؛ پرش = خطای گمراه‌کننده.
2. هر آیتم `[ ]` یا `[x]` است. اگر نیمه‌کاره ماند، `[ ]` بماند.
3. **اگر خروجی با «انتظار» یکی نبود، همان‌جا بایست.** عدد را عوض نکن تا سبز شود؛ عددِ متفاوت یعنی
   محیط تو با این محیط فرق دارد و باید بفهمی کدام. جدول تریاژ: ضمیمهٔ ب.
4. هر فاز یک **شرط عبور** دارد. تا آن شرط برقرار نشود، فاز بعد را شروع نکن.
5. هرچه اجرا شد، خروجی‌اش را نگه دار (لاگ یا اسکرین‌شات). ضمیمهٔ ج می‌گوید چه چیزی را به من بده.

**مسیر زمانی (واقع‌بینانه، برای یک نفر):**

| فاز | خروجی | زمان |
|---|---|---|
| ۰ | ابزار نصب، مخزن بالا | ۱۵ دقیقه |
| ۱ | ۲۲ گیت خودکار سبز روی ماشین تو | ۲۰ تا ۳۰ دقیقه |
| ۲ | استک محلی + ۱۱ تست زنجیره | ۱۵ دقیقه |
| ۳ | Firestore emulator + ۱۷ تستی که هرگز اجرا نشد | ۳۰ دقیقه |
| ۴ | ۳۰ تست مرورگر | ۲۰ دقیقه |
| ۵ | یک دوئل کامل دستی با تقسیم ۹۸/۲ | ۴۵ دقیقه |
| ۶ | ۷ سناریوی شکست | ۳۰ دقیقه |
| ۷ | Amoy: دیپلوی + اولین دوئل واقعی | نیم‌روز |
| ۸ | ۱۴ مورد روی دو گوشی واقعی | یک روز |
| ۹ | keeper روی staging | ۱ ساعت |
| ۱۰ | ممیزی بیرونی + تصمیم C-02c | هفته‌ها (بیرون از کنترل تو و من) |

---

## فاز ۰ — پیش‌نیازها

> این فاز را **یک بار** انجام می‌دهی. اگر ماشینی داری که قبلاً این مخزن رویش بود، از 0.6 شروع کن.

- [ ] **0.1** مخزن را بگیر و روی همان شاخه بمان:
  ```bash
  git clone <repo-url> PUL_SKILL && cd PUL_SKILL
  git branch --show-current          # انتظار: arena/a9a25b53-pul-skill
  git log --oneline -1               # انتظار: کامیت آخرِ همین کار
  ```
- [ ] **0.2** `node -v` → `v20.x` یا بالاتر (با `v22` تست شده). اگر قدیمی‌تر است، Node را عوض کن؛
  `vite 7` روی `v18` بالا نمی‌آید.
- [ ] **0.3** `python3 -V` → `3.11.x`. روی `3.12` هم تست شده؛ روی `3.9` نه.
- [ ] **0.4** Foundry:
  ```bash
  curl -L https://foundry.paradigm.xyz | bash && foundryup
  forge --version                     # انتظار: forge 1.7.1 یا بالاتر
  ```
- [ ] **0.5** وابستگی‌های Node: `npm ci` (به `package-lock.json` وفادار است؛ چیزی را ارتقا نمی‌دهد).
- [ ] **0.6** محیط پایتون:
  ```bash
  python3 -m venv .venv
  .venv/bin/pip install -r api/requirements.lock -r api/requirements-dev.txt
  ```
- [ ] **0.7** کتابخانه‌های قرارداد (در مخزن نیستند، عمداً):
  ```bash
  cd contracts
  git clone --depth 1 -b v1.9.7 https://github.com/foundry-rs/forge-std lib/forge-std
  git clone --depth 1 -b v5.7.0 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts
  ```
- [ ] **0.8** برای فاز ۳ لازم است (اگر نداری، فاز ۳ را بعداً بزن — بقیهٔ سند بدون آن هم اجرا می‌شود):
  `java -version` → `17+` و `firebase --version` → `13.x` (`npm i -g firebase-tools`).
- [ ] **0.9** سنجش سریع کامپایل:
  ```bash
  cd contracts && forge build            # انتظار: بدون error (warnهای lint اشکالی ندارند)
  forge test --match-path test/PulsarEscrow.t.sol   # انتظار: 21 passed
  ```

**شرط عبور فاز ۰:** `forge build` بدون خطا + `npm ci` بدون خطا + `.venv/bin/python -c "import fastapi"` بی‌صدا.

---

## فاز ۱ — گیت‌های خودکار (اولین نقطهٔ حقیقت)

- [ ] **1.1** اجرا: `bash scripts/verify.sh`
- [ ] **1.2** جدول انتظار (اعداد همین کامیت، روی ماشینی مثل ماشین تو):

| گیت | انتظار | اگر نبود یعنی |
|---|---|---|
| `tsc --noEmit` | ۰ خطا | تغییرِ ناتمام در کد؛ خروجی را بخوان |
| `eslint` | ۰ warning (با `--max-warnings 0`) | — |
| `vitest run` | **۳۵۷ تست / ۷۱ فایل** | رفتار کلاینت عوض شده؛ عدد را پایین نیاور |
| `ruff check` | پاک | — |
| `mypy` (api + scripts) | `no issues` (۳۹ فایل) | قرارداد تایپ شکسته |
| `pytest` هرمتیک + coverage | ≥ **۷۷٪** (امروز **۷۸٪**) | کد جدید بدون تست |
| `pytest` کامل | **۷۰۶ pass / ۲۵ skip** با anvil و API · **۷۰۱ / ۳۰** بدون | skip بیشتر از ۳۰ = سرویس بالا نیست |
| `forge test` | **۱۰۷ تست / ۱۰ سوئیت** | `lib/` ناقص است (0.7) |
| contract coverage | ≥ ۹۵٪ خط (امروز ۹۸٪) | — |
| Playwright | **≥ ۲۰** (کامل: ۳۰) | مرورگر نصب نیست → فاز ۴ |
| live-stack | سبز | پورت اشغال → `bash scripts/start_e2e_stack.sh --stop` |

- [ ] **1.3** شمارش گیت‌ها را خودت ببین: `grep -c 'run_gate "' scripts/verify.sh` → **22**.
- [ ] **1.4** ببین کدام گیت‌ها `skip_gate` خوردند (۱۹ جای ممکن). یک گیتِ **SKIP سبز نیست**.

- [ ] **1.5** **این عدد را با من مقایسه کن.** در محیطی که Firestore و مرورگر ندارد (دقیقاً همین sandbox)،
  `bash scripts/verify.sh` با `PULSAR_E2E_STORE=memory` پیش از اصلاحِ امروز این را می‌داد:

  ```
  passed: 17   failed: 4   skipped: 1
  failed: playwright · live-stack · runbook drill · chaos
  ```

  اندازه‌گیریِ دوباره انجام نشد (toolchain این محیط پاک شد)، ولی با تغییر امروز گیتِ `chaos` به‌جای
  چهار خط قرمزِ بی‌معنا، **`⏭ SKIP` با دلیل** می‌دهد:

  ```
  chaos summary: 0 passed, 0 failed, 5 skipped (environment)
  SKIPPED (environment): 5 scenario(s)
    - rpc_kill — needs a local anvil … (needs foundry: forge --version)
    - firestore_kill — needs the Firestore emulator … (needs a JRE: java -version)
  ```

  یعنی روی ماشین تو، سه قرمزِ باقی‌مانده (`playwright`، `live-stack`، `runbook drill`) و پنج SKIPِ
  chaos همه **یک** معنا دارند: سرویس یا مرورگر نیست.
  **نکتهٔ مهم:** بعد از فاز ۳ و ۴، اگر `chaos` باز هم `SKIP` داد، یعنی emulator/anvil بالا نیامده —
  و اگر `FAIL` داد، آن یک باگ واقعی است، چون این ابزار دیگر محیط را با نقص قاطی نمی‌کند.

**شرط عبور فاز ۱:** `verify.sh` با کد ۰ تمام شود **و** بدانی کدام گیت‌ها skip شدند (لیست را بنویس).
اگر در محیطی هستی که Firestore و Playwright دارد و باز هم قرمز شد، آن قرمز **مالِ توست**، نه محیط.

---

## فاز ۲ — استک محلی با پول شبیه‌سازی‌شده

- [ ] **2.1** ترمینال ۱:
  ```bash
  bash scripts/start_anvil.sh --bg
  # انتظار: token=0x…  escrow=0x…  manifest=contracts/deployments/local.json
  ```
- [ ] **2.2** ترمینال ۲:
  ```bash
  PULSAR_MATCH_STORE=memory bash scripts/start_e2e_stack.sh
  ```
- [ ] **2.3** سلامت API:
  ```bash
  curl -s localhost:8000/api/health | jq '{ok,chainId,escrowConfigured,rpc}'
  # انتظار: ok:true · chainId:31337 · escrowConfigured:true · rpc.reachable:true
  ```
- [ ] **2.4** مسیر پول روی EVM واقعی (۱۱ تست):
  ```bash
  .venv/bin/python -m pytest -q -m chain      # انتظار: 11 passed
  ```
- [ ] **2.5** کلاینت: مرورگر → `http://localhost:3000`؛ صفحهٔ اصلی بالا بیاید، کنسول خطای قرمز نداشته باشد.
- [ ] **2.6** کیف پول برای anvil: شبکهٔ `http://127.0.0.1:8545` با `chainId 31337`؛ یکی از کلیدهای
  چاپ‌شدهٔ anvil را import کن.

**شرط عبور فاز ۲:** `escrowConfigured:true` + `rpc.reachable:true` + ۱۱ تست زنجیره سبز + صفحهٔ اصلی بدون خطا.

---

## فاز ۳ — Firestore emulator (گیتی که در sandbox هرگز اجرا نشد)

> این مهم‌ترین گامِ «انجام‌نشده» است: کل مسیر `store.py` که در production استفاده می‌شود، و ۱۵ تست
> `emulator` + ۲ تست `firestore`، در sandbox به دلیل نبود Java اجرا نشدند.

- [ ] **3.1** `bash scripts/start_emulator.sh --bg` سپس `curl -s localhost:8081 | head -c 80` (پاسخ emulator).
- [ ] **3.2** تست‌ها:
  ```bash
  FIRESTORE_EMULATOR_HOST=127.0.0.1:8081 GCLOUD_PROJECT=demo-pulsar \
    .venv/bin/python -m pytest -q -m "emulator or firestore"
  # انتظار: 17 passed, 0 skipped
  ```
- [ ] **3.3** استک را روی store پایدار بالا بیاور: `PULSAR_MATCH_STORE=firestore` + restart، بعد:
  ```bash
  curl -s 'localhost:8000/api/health?deep=1' | jq .probe.store
  # انتظار بعد از یک دوئل: {ok:true, writable:true} — هرگز null در production
  ```
- [ ] **3.4** سناریوهای chaos (نام‌ها از `scripts/chaos_suite.py`):
  ```bash
  .venv/bin/python scripts/chaos_suite.py rpc_kill firestore_kill rpc_delay replica_split soak
  ```
  `firestore_kill` فقط با emulator بالا معنا دارد. بدون آرگومان، همهٔ سناریوها اجرا می‌شوند.

**شرط عبور فاز ۳:** ۱۷ تست pass + `probe.store.writable:true` + سناریوهای `rpc_*` سبز.

---

## فاز ۴ — ۳۰ تست مرورگر (Playwright)

- [ ] **4.1** `npx playwright install --with-deps chromium`
- [ ] **4.2** `npm run test:e2e` → انتظار **۳۰ passed / ۰ skipped** (دو پروژهٔ `desktop` و `mobile`).
- [ ] **4.3** اگر روی موبایل واقعی می‌خواهی: `npx playwright test --project=mobile`.

**شرط عبور فاز ۴:** ۳۰ pass، ۰ skip. (`verify.sh` خودش زیر ۲۰ را رد می‌کند، ولی ۲۱ هم کافی نیست.)

---

## فاز ۵ — یک دوئل کامل دستی (تقسیم ۹۸/۲)

> دو پروفایل مرورگر (یا دو دستگاه) با دو کیف پول. هر دو ≥ ۱۰ USDT و کمی POL برای گس.

- [ ] **5.1** اتصال کیف پول: آدرس کوتاه در هدر، بدون `balanceUnknown`.
- [ ] **5.2** استیک ۵: اگر موجودی < ۵ باشد دکمه **باید** بلاک شود با پیام روشن (قاعدهٔ H-27).
- [ ] **5.3** approve: تراکنش در کیف پول؛ بعد `cast call $USDT "allowance(address,address)(uint256)" $P1 $ESCROW` ≥ استیک.
- [ ] **5.4** هر دو وارد صف: شمارش معکوس، جفت‌شدن سمت **سرور** (نه کلاینت).
- [ ] **5.5** سه راند: برندهٔ هر راند سمت سرور تعیین می‌شود.
- [ ] **5.6** settle: تراکنش `settleDuel` با امضای اوراکل؛ رویداد `MatchSettled` در explorer.
- [ ] **5.7** موجودی برنده: **+۹۸٪ کل استخر** (برای استیک ۵ = ۹٫۸ از ۱۰).
- [ ] **5.8** treasury: **+۲٪** (۰٫۲).
- [ ] **5.9** `curl -s localhost:8000/api/health | jq .ledger.failures.total` → **0**.
- [ ] **5.10** تاریخچه: یک ردیف با هش واقعی؛ XP و لیدربورد به‌روز.
- [ ] **5.11** عدد ۹۸/۲ را از قرارداد بخوان، نه از UI:
  `cast call $ESCROW "PLATFORM_FEE_BPS()(uint256)" --rpc-url …` → **200**.

**شرط عبور فاز ۵:** ۹٫۸ و ۰٫۲ **دقیق** (اختلاف یک واحد هم شکست است)، `ledger.failures.total == 0`.

---

## فاز ۶ — هفت سناریوی شکست (این‌ها همان‌جایی هستند که پول گم می‌شود)

- [ ] **6.1** رد کردن تراکنش در کیف پول → پیام «لغو شد — هیچ پولی جابه‌جا نشد»، **هیچ** ردیفی در تاریخچه.
- [ ] **6.2** RPC مرده (`ESCROW_RPC_URL=http://127.0.0.1:9` + restart API) → `health.rpc.reachable:false`؛
  کلایم ۵۰۳/۵۰۴ می‌دهد نه ۵۰۰؛ هیچ پرداخت نصفه‌ای.
- [ ] **6.3** کیف پول بدون گس → پیام «گس کافی نیست»؛ استیک قفل نمی‌شود.
- [ ] **6.4** بستن تب برنده بعد از settle → `keeper.py --once` (dry-run) تراکنش را نشان می‌دهد؛ با `--execute` پرداخت می‌شود.
- [ ] **6.5** timeout: ۳۰ دقیقه + ۱۰ دقیقه گریس (روی anvil می‌توانی جلو ببری) → `refundTimeoutMatch` هر دو طرف را برمی‌گرداند.
- [ ] **6.6** replay امضا: همان settle را دوباره بفرست → revert، هیچ پرداخت دومی.
- [ ] **6.7** کلایم با هش جعلی → ۴۰۰/۴۲۲، ردیفی ساخته نمی‌شود (H-26).

**شرط عبور فاز ۶:** هر ۷ مورد رفتار مشخص و مستند داشته باشد — نه «هیچ‌کدام خراب نشد»، بلکه «هر کدام
همان کاری را کرد که انتظار داشتیم».

---

## فاز ۷ — Amoy: اولین پول واقعیِ تست‌نت

> **دامِ نام‌ها:** `Deploy.s.sol` فقط سه env می‌خواند: `DEPLOYER_PRIVATE_KEY`، `TREASURY_ADDRESS`،
> `ORACLE_SIGNER_ADDRESS` (اختیاری: `PAYMENT_TOKEN_ADDRESS`). متغیر `ORACLE_ADDRESS` که سرور
> می‌خواند **همان آدرس** است با اسم دیگر؛ برای دیپلوی از `ORACLE_SIGNER_ADDRESS` استفاده کن.

- [ ] **7.1** دیپلوی:
  ```bash
  cd contracts
  export AMOY_RPC=https://rpc-amoy.polygon.technology
  export DEPLOYER_PRIVATE_KEY=0x…        # کیف گس؛ هرگز همان کلید اوراکل نباشد
  export TREASURY_ADDRESS=0x…            # ۲٪ به اینجا می‌رود (بهتر: آدرس Safe)
  export ORACLE_SIGNER_ADDRESS=0x…       # آدرس عمومی کلید امضا
  forge script script/Deploy.s.sol --rpc-url "$AMOY_RPC" --broadcast
  # انتظار: آدرس MockUSDT و PulsarEscrow در خروجی
  ```
- [ ] **7.2** تأیید قرارداد:
  ```bash
  cast call $ESCROW "VERSION()(string)" --rpc-url "$AMOY_RPC"          # 2.0.0
  cast call $ESCROW "PLATFORM_FEE_BPS()(uint256)" --rpc-url "$AMOY_RPC" # 200
  cast call $ESCROW "oracleSigner()(address)" --rpc-url "$AMOY_RPC"     # == ORACLE_SIGNER_ADDRESS
  cast call $ESCROW "treasuryWallet()(address)" --rpc-url "$AMOY_RPC"   # == TREASURY_ADDRESS
  ```
- [ ] **7.3** faucet: دو کیف پول، هرکدام ≥ ۱۰ USDT تستی + ۰٫۵ POL.
- [ ] **7.4** env سرور (لیست کامل: `.env.example`؛ در حالت production بدون این‌ها **بالا نمی‌آید**):
  ```bash
  PULSAR_ENV=production PULSAR_MATCH_STORE=firestore PULSAR_REQUIRE_DURABLE_STORE=1 \
  ESCROW_ADDRESS=0x… ESCROW_RPC_URL=$AMOY_RPC ORACLE_CHAIN_ID=80002 \
  ORACLE_ADDRESS=0x…  ORACLE_SIGNER=… ORACLE_PUBLIC_KEY=0x04… \
  ALLOWED_DOMAIN=… ADMIN_SECRET=… \
    .venv/bin/uvicorn main:app --app-dir api --host 0.0.0.0 --port 8000
  ```
  `ORACLE_SIGNER=local` در production **رد می‌شود** مگر `PULSAR_ALLOW_LOCAL_SIGNER=1` — و آن هم فقط
  برای staging. برای هر چیز جدی: `aws-kms` یا `gcp-kms` (H-07).
- [ ] **7.5** سلامت:
  ```bash
  curl -s https://api.…/api/health | jq '{ok,chainId,escrowConfigured,rpc,escrowVersion}'
  # انتظار: chainId:80002 · escrowConfigured:true · escrowVersion:"2.0.0"
  curl -s 'https://api.…/api/health?deep=1' | jq .probe.store     # writable:true
  ```
- [ ] **7.6** کلاینت:
  ```bash
  VITE_CHAIN_ID=80002 VITE_ESCROW_ADDRESS=0x… VITE_PAYMENT_TOKEN_ADDRESS=0x… \
  VITE_GAME_SERVER_URL=https://api.… VITE_WALLETCONNECT_PROJECT_ID=… npm run build
  ```
- [ ] **7.7** یک دوئل کامل روی Amoy با دو گوشی، همان جدول فاز ۵.
- [ ] **7.8** explorer: رویداد `MatchSettled` + انتقال ۹۸/۲.

**شرط عبور فاز ۷:** یک دوئل واقعی، ۹۸/۲ دقیق، `escrowVersion:"2.0.0"`، `probe.store.writable:true`.

---

## فاز ۸ — دو گوشی واقعی: iOS و Android

- [ ] **8.1** دامنهٔ HTTPS روی هر دو گوشی، بدون هشدار گواهی (کیف پول موبایل روی HTTP کار **نمی‌کند**).
- [ ] **8.2** اتصال WalletConnect: کیف پول باز می‌شود، برمی‌گردد، آدرس نشان داده می‌شود.
- [ ] **8.3** سوئیچ/افزودن شبکهٔ Amoy (`chainId 80002` در هدر).
- [ ] **8.4** approve USDT در اپ کیف پول.
- [ ] **8.5** دوئل کامل دو نفره: ۳ راند، settle، claim.
- [ ] **8.6** چرخش صفحه و صفحه‌کلید: چیدمان نمی‌شکند.
- [ ] **8.7** فارسی و عربی: کل متن RTL؛ اعداد لاتین و در هر دو زبان یکسان (حسابرسی i18n).
- [ ] **8.8** ترک اپ وسط دوئل: بازگشت → وضعیت بازیابی می‌شود یا void اعلام می‌شود.
- [ ] **8.9** قطع اینترنت در راند ۲: پیام روشن؛ پول در escrow می‌ماند.
- [ ] **8.10** حالت تاریک/روشن و اندازهٔ فونت.
- [ ] **8.11** نصب PWA (Add to Home Screen): آیکون و splash.
- [ ] **8.12** اعلان‌ها (اگر فعال است).
- [ ] **8.13** کیف پول بدون گس: پیام روشن، بدون قفل پول.
- [ ] **8.14** دو گوشی هم‌زمان در یک دوئل: جفت‌شدن درست.

**شرط عبور فاز ۸:** ۱۴ مورد بسته، و هیچ موردی «بعداً» نشده باشد.

---

## فاز ۹ — Keeper روی staging (پول کسی گم نمی‌شود، حتی اگر تب بسته شود)

- [ ] **9.1** dry-run: `ESCROW_RPC_URL=… .venv/bin/python scripts/keeper.py --once`
- [ ] **9.2** اجرای واقعی: `KEEPER_PRIVATE_KEY=0x… ORACLE_PRIVATE_KEY=0x… .venv/bin/python scripts/keeper.py --once --execute`
- [ ] **9.3** جایزهٔ تب‌بسته خودکار settle می‌شود و به برنده می‌رود.
- [ ] **9.4** دوئل رهاشده بعد از ۳۰+۱۰ دقیقه refund می‌شود (هر دو طرف).
- [ ] **9.5** اجرای دوباره چیزی نمی‌فرستد (idempotent).
- [ ] **9.6** کیف پول keeper فقط گس خرج می‌کند و هرگز پول بازیکن را نمی‌گیرد.
- [ ] **9.7** سرویس را با `--interval` (مثلاً ۶۰) بالا بگذار و ۲۴ ساعت لاگ را ببین.

**شرط عبور فاز ۹:** یک چرخهٔ کامل بدون دخالت دستی، و لاگ بدون خطای تکراری.

---

## فاز ۱۰ — چیزهایی که نه با کد حل می‌شوند نه با تست

- [ ] **10.1** **ممیزی بیرونی قرارداد.** یکی از سه گزینه: (الف) یک firm با تجربهٔ Solidity audit؛
  (ب) contest (Code4rena / Sherlock / Cantina)؛ (ج) حداقل دو داور مستقل با گزارش امضاشده.
  بودجهٔ واقع‌بینانه: چند هزار تا چند ده هزار دلار؛ زمان: ۲ تا ۶ هفته. تا گزارش نیامده، **پول واقعی ممنوع**.
  بستهٔ تحویلی را با `bash scripts/build_audit_package.sh /tmp/audit` بساز: کل `api/`، کل تست‌های پایتون،
  قفلِ وابستگی، کل قرارداد با mock tokenها و اسکریپت deploy، سندهای ممیزی، و `SHA256SUMS` + `PROVENANCE.md`
  با هش کامیت و **وضعیت working tree**. اگر با `AUDIT_PACKAGE_FAST=1` ساختی، خودش روی جلد می‌نویسد
  «INCOMPLETE» — آن نسخه برای ارسال نیست.
- [ ] **10.2** **تصمیم C-02c** (`docs/COMPLIANCE-C-02c.md` — تنها آیتم باز فهرست رفع): KYC، سقف
  برداشت، ژئوبلاک. این تصمیم حقوقی است، نه فنی. تا مستند نشود، No-Go.
- [ ] **10.3** **treasury = Safe multisig** (نه یک EOA). یک کلید تنها یعنی یک فیشینگ = ۲٪ همهٔ دوئل‌ها.
- [ ] **10.4** **کلید اوراکل در KMS** (`ORACLE_SIGNER=aws-kms|gcp-kms`)، نه در env سرور.
- [ ] **10.5** پایش: `scripts/check_alerts.py --url https://api.…` را روی staging امتحان کن؛ باید با کد
  ۰ (سالم) برگردد، و اگر یک سرویس را عمداً خواباندی، کد **۲** بدهد. `PULSAR_ALERT_WEBHOOK` را هم ست کن
  تا هشدار واقعاً جایی برسد (فقط exit code کافی نیست).
- [ ] **10.6** بکاپ Firestore + تست restore (بکاپی که restore نشده، بکاپ نیست).

**شرط عبور فاز ۱۰:** گزارش ممیزی امضاشده + سند تصمیم C-02c + treasury روی Safe.

---

## فاز ۱۱ — تعریف «تمام»

| شرط | حداقل | وضعیت در sandbox |
|---|---|---|
| فاز ۱ | `verify.sh` سبز، بدون SKIP در گیت‌های الزامی | ✅ اجرا شد |
| فاز ۳ (Firestore emulator) | ۱۷ تست pass + `store.writable:true` | ❌ هرگز اجرا نشد (Java نبود) |
| فاز ۴ (Playwright) | ۳۰ تست pass | ❌ هرگز اجرا نشد (دانلود مرورگر مسدود) |
| فاز ۵ | دوئل دستی، ۹۸/۲ دقیق | ❌ نیاز به دو کیف پول |
| فاز ۶ | ۷ سناریو با رفتار مشخص | ❌ نیاز به کیف پول |
| فاز ۷ (Amoy) | یک دوئل واقعی | ❌ کلید/faucet دست توست |
| فاز ۸ | ۱۴ مورد موبایل | ❌ — |
| فاز ۹ | keeper در staging | ❌ کیف پول گس |
| فاز ۱۰ (ممیزی بیرونی + C-02c) | گزارش امضاشده + تصمیم مستند | ❌ حقوقی/بیرونی |

**شرط عبور فاز ۱۱:** هر ردیفِ جدول بالا وضعیت خودش را داشته باشد (سبز یا «اجرا نشد» با دلیل) —
جدولِ نیمه‌پر یعنی نمی‌دانی کجا ایستاده‌ای.

**Go برای تست واقعی (پول کوچک، دوستان):** فازهای ۱ تا ۹ سبز + ۱۰.۳ و ۱۰.۴.
**Go برای پول دیگران:** همهٔ بالا **به‌علاوهٔ** ۱۰.۱ و ۱۰.۲. بدون آن دو: **No-Go** — حتی اگر ۹ فاز
دیگر سبز باشند.

---

## ضمیمهٔ الف — بلوک کپی-پیست فازهای ۰ تا ۲

```bash
# 0 — پیش‌نیازها
git clone <repo-url> PUL_SKILL && cd PUL_SKILL
npm ci
python3 -m venv .venv
.venv/bin/pip install -r api/requirements.lock -r api/requirements-dev.txt
(cd contracts && git clone --depth 1 -b v1.9.7 https://github.com/foundry-rs/forge-std lib/forge-std \
  && git clone --depth 1 -b v5.7.0 https://github.com/OpenZeppelin/openzeppelin-contracts lib/openzeppelin-contracts)

# 1 — گیت‌ها (چند دقیقه)
bash scripts/verify.sh

# 2 — استک محلی (دو ترمینال)
bash scripts/start_anvil.sh --bg
PULSAR_MATCH_STORE=memory bash scripts/start_e2e_stack.sh
# در ترمینال سوم:
curl -s localhost:8000/api/health | jq '{ok,chainId,escrowConfigured,rpc}'
.venv/bin/python -m pytest -q -m chain
```

## ضمیمهٔ ب — تریاژ: اگر خراب شد

| نشانه | معنی | کار |
|---|---|---|
| `pytest` کمتر از ۷۰۱ | یا محیط فرق دارد یا سرویس بالا نیست | `-rs` بزن و دلیل skip‌ها را بخوان |
| coverage زیر ۷۷ | کد جدید بدون تست | تست بنویس؛ کف را پایین نیاور |
| `forge test` کامپایل نمی‌شود | `lib/` ناقص یا نسخهٔ solc | فاز ۰.۷ و ۰.۴ |
| `execution reverted` در settle | deadline گذشته، یا chainId/escrow غلط | `docs/CONTRACT-FUZZ-REPORT.md §4`؛ لاگ `chain_smoke` |
| `escrowConfigured:false` | manifest یا env | `start_anvil.sh --bg` یا `ESCROW_ADDRESS` |
| کلایم ۵۰۰ می‌دهد | RPC یا رسید بدشکل | `docs/INCIDENT-RUNBOOK.md` |
| گوشی وصل نمی‌شود | HTTP یا Project ID | HTTPS + `VITE_WALLETCONNECT_PROJECT_ID` |
| دیپلوی: `environment variable not found` | اسم env غلط | فاز ۷.۱ — سه نام درست |

## ضمیمهٔ ج — چه چیزی را به من بده

برای این‌که در دور بعدی بتوانم واقعاً کمک کنم (و دوباره حدس نزنم):

1. خروجی `bash scripts/verify.sh` (فقط ۴۰ خط آخر) + لیست گیت‌هایی که SKIP شدند.
2. خروجی `pytest -m "emulator or firestore" -q` و `npm run test:e2e` (فقط خط `N passed`).
3. آدرس escrow روی Amoy + خروجی چهار `cast call` فاز ۷.۲.
4. `curl -s https://…/api/health | jq` و `?deep=1 | jq .probe.store`.
5. اگر چیزی شکست: **متن کامل خطا**، نه خلاصه.

منابع: `docs/MANUAL-CHECKLIST.md` (همان مسیر با توضیح «چرا») · `docs/GO-LIVE-RUNBOOK.md` ·
`docs/DEPLOYMENT.md` · `docs/INCIDENT-RUNBOOK.md` · `scripts/check_alerts.py` · `docs/COMPLIANCE-C-02c.md` ·
`docs/CONTRACT-FUZZ-REPORT.md` · `docs/FINAL-REPORT.md`
