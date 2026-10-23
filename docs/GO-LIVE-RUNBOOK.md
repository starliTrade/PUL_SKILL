# PULSAR — اجرای واقعی و اولین تست انسانی

**این سند برای چه کسی است؟** دو ستون دارد: کارهایی که **در همین مخزن انجام و تأیید شده‌اند**
(با نام تست و کامیت) و کارهایی که **فقط تو می‌توانی انجام بدهی** (دسترسی به هاست، مرورگر واقعی،
دو گوشی، شبکهٔ Amoy). هدفش یک جمله است: **رساندن اپ به حالتی که بتوانی با پول واقعی تستش کنی.**

> **قاعده‌ای که این سند رعایت می‌کند:** هیچ‌جا نمی‌نویسد «تست شد» مگر خروجی‌اش در همین مخزن
> گرفته شده باشد. آنچه با مرورگر/گوشی/Amoy سنجیده می‌شود، صریحاً «انجام نشده در این محیط»
> علامت خورده — چون ادعای تست‌نشده، بدترین بدهی فنی است.

---

## ۰. تصویر کلی: کجاییم؟

| لایه | وضعیت | شاهد |
|---|---|---|
| قرارداد `PulsarEscrow` | نسخه‌دار، ۱۰۴ تست، ۹۸٫۵۷٪ خطوط | `forge test`, `docs/UPGRADE-PATH.md` |
| سرور FastAPI | ۵۵۷ تست سبز (۴۱ skip: زنجیره/emulator خاموش)، هدرهای امنیتی، fail-closed | `pytest -q` |
| کلاینت React | ۳۳۲ تست / ۶۷ فایل، tsc + eslint پاک | `npm run lint`, `vitest` |
| مسیر پول (ranked) | تست یکپارچه + anvil واقعی | `pytest -m chain` |
| مرورگر واقعی (E2E) | **انجام نشده در این محیط** | `npx playwright install` در sandbox مسدود است |
| Amoy با دو گوشی | **انجام نشده** | نیاز به کلید/شبکهٔ تو |
| Firestore واقعی | **انجام نشده** | فقط emulator در دسترس بود |

---

## ۱. پیش‌نیازهای ماشین تو (۱۰ دقیقه)

```bash
# 1) Node 20+ و npm
node -v            # باید >= 20 باشد
# 2) Python 3.11+
python3 -V
# 3) Foundry (forge/cast/anvil)
curl -L https://foundry.paradigm.xyz | bash && foundryup
forge --version    # 1.x
# 4) Java 17+ و Firebase CLI (فقط اگر می‌خواهی emulator را اجرا کنی)
java -version
npm i -g firebase-tools
# 5) مرورگرهای Playwright (این خط در sandbox من اجرا نشد)
npx playwright install --with-deps chromium
```

بعد، وابستگی‌ها:

```bash
cd PUL_SKILL
npm ci
python3 -m venv .venv
.venv/bin/pip install -r api/requirements-dev.txt
.venv/bin/pip install locust          # فقط برای تست بار
```

---

## ۲. گیت کامل روی ماشین خودت (۵ دقیقه) — «آیا سالم است؟»

```bash
npm ci
bash scripts/verify.sh
```

چه چیزی باید ببینی: خط `✅ VERIFY PASSED` با شمارش `passed / failed / skipped`. **skip با دلیل
گزارش می‌شود؛ skip را «سبز» حساب نکن.** اگر می‌خواهی هیچ skip‌ای تحمل نشود:

```bash
bash scripts/verify.sh --strict
```

معادل‌های جداگانه (اگر verify را نمی‌خواهی):

```bash
npm run lint                                   # tsc + eslint .
npx vitest run                                 # انتظار: ~332 تست / 67 فایل
.venv/bin/python -m pytest -q                  # انتظار: ~557 passed
.venv/bin/python -m py.test -q -m chain        # فقط با anvil بالا
```

---

## ۳. استک کامل محلی با پول واقعیِ شبیه‌سازی‌شده (۱۵ دقیقه)

این همان مسیری است که تست مرورگری و تست دستی رویش اجرا می‌شود: API با **همان** پیکربندی
production بالا می‌آید (آدرس escrow، RPC، کلید اوراکل، chain id) — نه یک bypass.

```bash
# ترمینال ۱ — زنجیرهٔ محلی + دیپلوی escrow (هر بار آدرس جدید می‌سازد)
bash scripts/start_anvil.sh --bg
curl -s localhost:8545 -X POST -H 'content-type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"eth_chainId","params":[]}'   # 0x7a69

# ترمینال ۲ — Firestore emulator (اختیاری ولی توصیه‌شده)
bash scripts/start_emulator.sh --bg

# ترمینال ۳ — API روی :8000 با store پایدار
bash scripts/start_e2e_stack.sh
curl -s localhost:8000/api/health | python3 -m json.tool | head -20

# ترمینال ۴ — کلاینت
npm run dev -- --port 3000
```

نکته‌های واقعی که وقت می‌گیرند:

* **`start_anvil.sh` هر بار redeploy می‌کند** و آدرس escrow عوض می‌شود. اگر ترتیب را رعایت
  نکنی، API به آدرسی اشاره می‌کند که کد ندارد؛ `/api/health` می‌گوید `escrowConfigured: true`
  ولی هر دوئل با پیام مبهم شکست می‌خورد. اسکریپت استک این را **قبل از بالا آمدن** چک می‌کند
  (پس از رفع L-04؛ قبلاً آن گارد کد مرده بود).
* کلاینت باید env را بگیرد (`VITE_GAME_SERVER_URL`, `VITE_ESCROW_ADDRESS`, `VITE_CHAIN_ID`...).
  `playwright.config.ts` این‌ها را از `contracts/deployments/local.json` می‌سازد؛ برای اجرای
  دستی، همان‌ها را در `.env.local` بگذار.
* اگر vite قبلی باز است، آن را ببند: `reuseExistingServer` یک vite با env قدیمی را قبول می‌کند
  و علائمش شبیه باگ اپ است.

---

## ۴. تست مرورگری (E2E) — روی ماشین تو (۳۰ تست)

```bash
npx playwright test                 # ۳۰ تست / ۶ فایل / دسکتاپ + Pixel 7
npx playwright test --project=desktop e2e/smoke.spec.ts   # اول این یکی
npx playwright show-report
```

اگر شکست خورد، ترتیب تشخیص: (۱) anvil بالا و escrow دیپلوی‌شده؟ (۲) API روی `:8000` سالم؟
(۳) vite روی `:3000`؟ (۴) `npx playwright install` انجام شده؟ چیز دیگری لازم نیست.

**آنچه من نتوانستم:** در این sandbox دانلود مرورگر مسدود است، پس سوئیت استک واقعی را بالا می‌آورد
و در `browserType.launch` شکست می‌خورد. یعنی «کد» و «هارنس» تست شده، «اجرای مرورگر» نه.

---

## ۵. دستی: یک دوئل کامل با شرط واقعی روی استک محلی

این چک‌لیستِ «آیا اپ برای تست واقعی آماده است» است. هر مرحله یک مشاهدهٔ مشخص دارد:

| # | کار | چه چیزی باید ببینی |
|---|---|---|
| ۱ | `http://127.0.0.1:3000` را باز کن | لندینگ رندر می‌شود؛ در کنسول هیچ خطای قرمز بلاک‌کننده نیست |
| ۲ | زبان را به فارسی ببر | کل صفحه RTL می‌شود **و بعد از رفرش هم** RTL می‌ماند؛ متن انگلیسی باقی نمی‌ماند |
| ۳ | Connect Wallet → MetaMask → شبکهٔ «Localhost 31337» | آدرس نمایش داده می‌شود؛ تراز USDT خوانده می‌شود (نه صفرِ جعلی) |
| ۴ | امتیاز صفر: بدون approve، Join را بزن | پیام روشن «موجودی کافی نیست» — نه خطای مبهم |
| ۵ | approve + واریز ۵ USDT (faucet) | تراز به ۵ تغییر می‌کند؛ در Etherscan/Anvil انتقال ثبت است |
| ۶ | Practice → Start | **قبل از شروع** پیام «این ربات تمرینی است، بدون شرط» دیده می‌شود |
| ۷ | Real mode، شرط ۱، Join | صف → هر دو بازیکن (دو تب/دو کیف) → ۳ راند |
| ۸ | راندها را بزن | هر راند commit → reveal → نتیجه؛ تایمرها منطقی‌اند |
| ۹ | مسابقه تمام | نتیجه + امضای اوراکل + مبلغ جایزه (۹۸٪) درست |
| ۱۰ | Claim/Settle | تراکنش در anvil ماین می‌شود؛ ۲٪ به treasury |
| ۱۱ | رفرش وسط مسابقه | مسابقه از سرور بازیابی می‌شود، نه «باخت» |
| ۱۲ | Report a problem | گزارش ثبت می‌شود، شناسه دارد، و با «بررسی وضعیت» قابل پیگیری است |
| ۱۳ | قطع اینترنت در راند ۲ | خطای روشن؛ بعد از وصل شدن، مسیر ادامه پیدا می‌کند |

---

## ۶. Amoy: تمرین با دو گوشی واقعی (نیم‌روز تا دو روز)

این جدی‌ترین مرحله است؛ همه‌چیز قبلش «تمرین» است.

### ۶.۱. دیپلوی

```bash
export DEPLOYER_PRIVATE_KEY=0x...     # کیف گس؛ هرگز همان کلید اوراکل نباشد
export TREASURY_ADDRESS=0x...         # ۲٪ به اینجا می‌رود
export ORACLE_ADDRESS=0x...           # آدرس عمومیِ کلید امضا
forge script script/Deploy.s.sol --rpc-url https://rpc-amoy.polygon.technology --broadcast
# خروجی: آدرس MockUSDT و PulsarEscrow را بردار
cast call $ESCROW "VERSION()(string)" --rpc-url https://rpc-amoy.polygon.technology   # باید 2.0.0
```

### ۶.۲. سرور

متغیرهای الزامی (سرور در حالت production بدون این‌ها **بالا نمی‌آید** — این fail-closed است):

```
PULSAR_ENV=production
PULSAR_MATCH_STORE=firestore        PULSAR_REQUIRE_DURABLE_STORE=1
ESCROW_ADDRESS=0x...                ESCROW_RPC_URL=https://rpc-amoy.polygon.technology
ORACLE_CHAIN_ID=80002               ORACLE_SIGNING_SECRET=0x...
ORACLE_SIGNER=local                 PULSAR_ALLOW_LOCAL_SIGNER=1   # یا aws-kms/gcp-kms
PULSAR_ADMIN_SECRET=...             ALLOWED_DOMAIN=your-frontend-host
CORS_ALLOW_ORIGINS=https://your-frontend  ALLOWED_HOSTS=your-api-host
```

`ORACLE_SIGNER=local` بدون `PULSAR_ALLOW_LOCAL_SIGNER=1` عمداً بوت را رد می‌کند (H-07). برای
Amoy قابل قبول است؛ برای mainnet نه — آنجا KMS.

### ۶.۳. کلاینت

```
VITE_CHAIN_ID=80002
VITE_ESCROW_ADDRESS=0x...      VITE_PAYMENT_TOKEN_ADDRESS=0x...
VITE_TREASURY_WALLET_ADDRESS=0x...  VITE_ORACLE_WALLET_ADDRESS=0x...
VITE_GAME_SERVER_URL=https://your-api-host
VITE_SITE_URL=https://your-frontend      # برای og:image و PWA
VITE_WALLETCONNECT_PROJECT_ID=...
```

### ۶.۴. سالم بودن، قبل از هر دوئل

```bash
curl -s https://your-api-host/api/health | python3 -m json.tool
```

باید ببینی: `"matchStore": "firestore"`، `"prodLike": true`، `"chainId": 80002`،
`"escrowConfigured": true`، `"rpc": {"reachable": true}`، `"escrowVersionProblem": null`،
`"oracleConfigured": true`، و `"rateLimit": {"backend": "firestore"}`.

### ۶.۵. بدون مرورگر، مسیر پول را از خط فرمان بسنج

```bash
REHEARSE_SERVER=https://your-api-host \
REHEARSE_RPC=https://rpc-amoy.polygon.technology \
PLAYER1_KEY=0x... PLAYER2_KEY=0x... \
ESCROW_ADDRESS=0x... MOCK_USDT=0x... STAKE_USDT=1 \
.venv/bin/python scripts/rehearse_amoy_e2e.py settle
```

این همان دوئل کامل است (SIWE → صف → approve/create/join → ۳ راند → settle → ۹۸٪/۲٪) و برای
سناریوی refund: `... refund` (حدود ۳۱ دقیقه، خودکار).

### ۶.۶. دو گوشی (چیزی که هیچ تستی جانشینش نیست)

۱. کیف پول موبایل (MetaMask/Trust) + شبکهٔ Amoy + دو حساب با USDT تستی.
۲. هر دو گوشی صفحهٔ اپ را باز کنند، وارد شوند، و **هم‌زمان** Join بزنند.
۳. یک نفر راند ۲ را قطع کند (Wi‑Fi خاموش) و برگرداند.
۴. یک نفر تب را ببندد؛ keeper باید مسابقه را settle کند (اگر روشن است) و جایزه به برنده برسد.
۵. timeout را واقعاً صبر کن و refund را ببین.

---

## ۷. کارهایی که فقط تو می‌توانی — به ترتیب

| # | کار | چرا من نمی‌توانم | معیار پذیرش |
|---|---|---|---|
| ۱ | `npx playwright install` و اجرای ۳۰ تست | دانلود مرورگر در sandbox مسدود | ۳۰ تست، ۰ skip |
| ۲ | اجرای `npx vitest run` روی Node 20 | نسخهٔ Node من ۲۲ است (کار می‌کند ولی نسخهٔ هدف نیست) | ۳۳۲/۶۷ |
| ۳ | emulator + `pytest -m firestore` | Java و firebase CLI نصب نیست | skip‌ها صفر شوند |
| ۴ | دیپلوی Amoy | کلید و faucet دست توست | `VERSION()==2.0.0` |
| ۵ | دو گوشی واقعی | — | چک‌لیست ۶.۶ |
| ۶ | Keeper روی staging | کیف پول گس | جایزهٔ تب‌بسته settle شود |
| ۷ | KYC/سقف برداشت/ژئوبلاک | تصمیم حقوقی | `docs/COMPLIANCE-C-02c.md` |
| ۸ | ممیزی بیرونی قرارداد | firm | گزارش امضا شده |

---

## ۸. واگر چیزی خراب شد

* `docs/INCIDENT-RUNBOOK.md` — مسیرهای واقعی، آستانه‌ها، دستورهای تشخیص (تست تضمین می‌کند
  هر endpoint که نام می‌برد واقعاً وجود داشته باشد).
* `/api/health` → `ledger`, `sweep`, `integrity`, `rateLimit.fallbacks`, `escrowVersionProblem`.
* `/api/metrics` → `requestsObserved` / `routesDropped` / `complete`؛ اگر `complete:false` یعنی
  جدول route پر شده و شمارش‌ها ناقص‌اند.
* لاگ رویدادهای ساختاریافته روی stderr (`PULSAR_EVENT_LOG=1`).

---

## ۹. محدودیت‌هایی که باید بدانی (بدون تعارف)

* **بدون ممیزی بیرونی و بدون KYC، این اپ برای پول واقعیِ دیگران آماده نیست.** کد تا حد زیادی
  بسته شده؛ مجوز و ممیزی نه.
* نردبان شرط روی L1 توجیه اقتصادی ندارد (سر‌به‌سر ≈ $337 در ۳۰ gwei)؛ L2/relayer لازم است.
* ضدتقلب **تشخیص** است نه اثبات؛ امتیاز مشکوک به صف بازبینی انسانی می‌رود و هیچ پرداختی را
  خودکار تغییر نمی‌دهد.
* treasury باید Safe چندامضایی باشد؛ کلید تکی روی سرور ممنوع.
* هیچ setter کارمزدی در قرارداد نیست: ۲٪ ثابت و تغییرش نیاز به دیپلوی نسخهٔ جدید دارد
  (`docs/UPGRADE-PATH.md`).
