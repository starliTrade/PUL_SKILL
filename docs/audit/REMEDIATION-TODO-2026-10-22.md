# PULSAR — برنامه‌ی رفع، وضعیت و مسیر آماده‌سازی Amoy

**تاریخ:** ۲۰۲۶-۱۰-۲۲ · **مبنا:** `docs/audit/RUTHLESS-AUDIT-2026-10-22.md`
**قاعده:** هر آیتم فقط وقتی «انجام شد» علامت می‌خورد که (۱) کد اصلاح شده باشد، (۲) تست رگرسیون داشته باشد، (۳) در همین مخزن اجرا و سبز شده باشد. آیتم‌هایی که اثبات‌شان به زیرساخت بیرونی نیاز دارد (Foundry، emulator، anvil، مرورگر، زنجیره) صریحاً «نیازمند محیط» می‌مانند.

---

## ۰. پاسخ کوتاه به «چقدرش از دست تو برمی‌آید؟»

| دسته | سهم | توضیح |
|---|---:|---|
| **قابل رفع کامل و تست در این مخزن** | ~۸۵٪ یافته‌های کد | همه‌ی C/H/M که به منطق سرور، قرارداد (بدون redeploy)، کلاینت، مستندات و تست مربوط‌اند |
| **قابل رفع جزئی** | ~۱۰٪ | ضدتقلب (تشخیص آماری، نه اثبات انسانیت)، KMS (لایه‌ی انتزاع + adapter، بدون اعتبارنامه‌ی واقعی)، صف (بهبود، نه بازطراحی کامل) |
| **خارج از دسترس این محیط** | ~۵٪ | ممیزی بیرونی قرارداد، KYC/مجوز/حقوقی، تست دو گوشی واقعی، تراکنش واقعی Amoy، اجرای forge/Playwright/emulator/anvil |

**نکته‌ی صادقانه:** «رفع کامل و بی‌نقص» برای یک محصول پول واقعی با ۹۰٪ کد ممکن نیست و ادعای آن دروغ است. چیزی که ممکن است: **بستن همه‌ی نقص‌های کد که در این مخزن قابل اثبات‌اند، و تبدیل بقیه از «باگ پنهان» به «کار مشخص با مالک و معیار پذیرش»**. همین کار در این سند انجام می‌شود.

---

## ۱. تودوی اجرایی (با شناسه‌ی یافته)

### فاز ۱ — مسدودکننده‌های عرضه (C)

- [x] **C-01** شمارش velocity فقط برای دوئل جدید (نه poll صف) — `api/main.py`, تست `test_queue_polls_do_not_trip_velocity`
- [x] **C-02a** تشخیص آماری رفتار غیرانسانی سمت سرور (انحراف/کف) + فلگ بازبینی — `api/integrity.py`
- [x] **C-02b** حذف ادعاهای «بیومتریک»/«۱۰۰٪ ضدبات» از UI (۵ زبان) — `src/i18n/translations.ts`
- [x] **C-03** سرویس keeper برای settle/refund خودکار — `scripts/keeper.py` + تست
- [ ] **C-02c** (باقی‌مانده، خارج از کد) KYC/تأخیر پرداخت/سقف برداشت — تصمیم محصولی، در §4 مستند شده
- [x] **C-04** *(یافته‌ی جدید، ۲۰۲۶-۱۰-۲۲)* `transactional` از ماژول اشتباه import می‌شد ⇒ **هر** claim نام کاربری در production با ۴۰۹ «نام تکراری» شکست می‌خورد — `api/main.py`, تست `test_username_atomic.py`

### فاز ۲ — امنیت و پول (H)

- [x] **H-01** خودحذفی فقط طولانی‌تر می‌شود
- [x] **H-02** کنترل‌های مسئولیت‌پذیری در قطعی fail-closed
- [x] **H-03a** endpoint سبک `/api/ping` و استفاده‌ی کلاینت از آن
- [x] **H-03b** `rttMs` برای صف اجباری شد (کلاینت باید اندازه بگیرد)
- [x] **H-04** endpoint `/api/matches/recent` + فید کلاینت از سرور
- [x] **H-05** پروفایل/دوستان: endpoint سرور + حذف نوشتن مرده‌ی Firestore
- [x] **H-06** production بدون store پایدار بالا نمی‌آید
- [ ] **H-07** لایه‌ی امضای قابل‌تعویض (env/KMS) + مستندسازی
- [x] **H-08** حذف ادعاهای نادرست (همراه C-02b)
- [x] **H-09** `revoke_session` fail-closed
- [x] **H-10** dispute پایدار در Firestore
- [ ] **H-11** کاهش فشار صف: ایندکس ورودی + حذف scan تکراری (بهبود، نه بازطراحی)
- [ ] **H-12** sweep امضاها با cursor و معیار deadline
- [x] **H-13** probe A6 هرمتیک
- [ ] **H-14** لجر: شمارنده‌ی خطا + هشدار health (outbox کامل در فاز بعد)
- [x] **H-15** میانگین زمان واکنش با شمارنده‌ی نمونه
- [x] **H-16** CSP + هدرهای امنیتی
- [x] **H-17** نرمال‌سازی سند کاربر + `.catch` روی `recordMatch`
- [x] **H-18** `doc_ref.create` داخل تراکنش ⇒ `tx.create` (نقص #۶ حسابرسی اول)

### فاز ۳ — متوسط/پایین (M/L)

- [x] **M-01** `limits.state()` بدون نوشتن
- [x] **M-02** نام‌گذاری صریح: سقف هر دوئل (نه سقف تجمعی)
- [x] **M-05** حذف نام حریف تخیلی در رنکد
- [ ] **M-08** تشخیص prod با نشانه‌های پلتفرم
- [ ] **M-10** لاگ تصمیم‌های ادمین
- [ ] **M-15** coverage: اندازه‌گیری پایدار (بدون وابستگی به emulator)
- [ ] **M-17** اعداد README از خروجی واقعی
- [ ] **M-19/M-21/M-22** حریم خصوصی کاربران، حذف داده، LICENSE/SECURITY
- [ ] **M-24** خطای ذخیره‌سازی قابل‌مشاهده
- [x] **M-11** قرارداد نسخه‌دار + پنجره‌ی مهاجرت (proxy رد شد، با دلیل مستند) — `PulsarEscrow.VERSION/VERSION_CODE`، `freeze/unfreeze`، دفتر `totalLocked`/`residualBalance`/`sweepResidual`؛ `api/onchain.escrow_version()` + `escrowVersionProblem` در `/api/health`؛ `docs/UPGRADE-PATH.md`؛ تست: `contracts/test/PulsarEscrowMigration.t.sol` (۱۸)، دو invariant جدید در `PulsarEscrowInvariants.t.sol`، `tests/unit/test_contract_version.py` (۱۲)
- [x] **M-12** پارامتر کارمزد ثابت و treasury — تصمیم محصولی در `docs/ECONOMICS.md` ثبت شد (مدل، مثال‌های عددی، ردِ `setFeeBps`، الزام multisig برای treasury، و تحلیل واحد-اقتصاد که می‌گوید L1 با این نردبان استیک توجیه ندارد)؛ تست: `tests/unit/test_economics_doc.py` (۹)
- [ ] **M-18** نسخه‌بندی service worker — نیازمند تست مرورگر

### فاز ۴ — نیازمند محیط/انسان (در این سند فقط برنامه)

- [x] اجرای `forge test` + invariant (Foundry) — ۱۰۴ تست در ۹ suite، همه سبز (اجرای واقعی ۲۰۲۶-۱۰-۲۳)
- [ ] اجرای `forge coverage` — forge 1.7.1 این زیرفرمان را حذف کرده؛ نیاز به `--ir-minimum`/ابزار جایگزین
- [ ] اجرای Playwright روی مرورگر واقعی
- [ ] emulator Firestore + تست integration
- [x] anvil + تست chain — `scripts/start_anvil.sh --bg` + `pytest -m chain`: ۱۱ تست سبز (مسیر پول با امضای واقعی oracle روی EVM واقعی)
- [ ] ممیزی قرارداد توسط firm
- [ ] KYC/AML + ژئوبلاک + مجوز
- [ ] تست Amoy با دو گوشی واقعی

---

## ۲. گزارش اجرا (این دور)

| گیت | نتیجه (آخرین اجرا: `8c2b724`) |
|---|---|
| `pytest -q` | **۳۶۰ passed، ۴۲ skipped** |
| `vitest run` | **۲۳۴ passed** (۵۴ فایل) |
| `tsc --noEmit` | ۰ خطا |
| `eslint src` | ۰ خطا |
| `ruff` / `mypy` | پاک / پاک |
| coverage | ~۷۲٪ (گیت ۷۹٪) — بدون emulator/anvil قابل‌رسیدن نیست |

---

## ۳. مسیر Amoy با دو گوشی واقعی — چه چیزی مانده؟

### ۳.۱ پیش‌نیازهای غیرکدی (باید تهیه شود)

| # | قلم | زمان | هزینه |
|---|---|---|---|
| A1 | دامنه + HTTPS (گواهی معتبر؛ کیف پول موبایل روی HTTP کار نمی‌کند) | ۱ روز | ~۱۵ دلار/سال |
| A2 | WalletConnect Project ID (برای iOS/Android) | ۱ ساعت | رایگان |
| A3 | RPC پایدار Amoy (Alchemy/Infura/QuickNode) | ۱ ساعت | رایگان تا سقف |
| A4 | دو کیف پول با MATIC تستی (faucet) | ۱ ساعت | رایگان |
| A5 | توکن USDT تستی روی Amoy (MockUSDT یا توکن faucet) | ۱ روز | رایگان |
| A6 | Firestore واقعی + سرویس‌اکانت | ۱ روز | ~۰–۵ دلار/ماه |
| A7 | استقرار API (Cloud Run/Fly/Render) با HTTPS | ۱ روز | ~۵–۲۰ دلار/ماه |
| A8 | دو گوشی واقعی (iOS + Android) و دو نفر | ۱ روز | — |

### ۳.۲ پیش‌نیازهای کدی (بعد از این دور)

| # | قلم | وضعیت (این سند به‌روزرسانی می‌شود) |
|---|---|---|
| B1 | keeper برای settle/refund | ✅ انجام شد (C-03) — نیازمند اجرای واقعی روی Amoy |
| B2 | `/api/ping` و RTT واقعی | ✅ انجام شد (H-03) |
| B3 | prod fail-closed (store/env) | ✅ انجام شد (H-06 + گیت env قبلی) |
| B4 | پروفایل/فید زنده از سرور | ✅ انجام شد (H-04 + H-05) |
| B5 | CSP/هدرهای امنیتی | ✅ سمت API؛ هدرهای هاست استاتیک در §4b سند deploy |
| B6 | مسیر «refund» در UI برای بازنده/برنده‌ی رهاشده | ⏳ نیازمند تأیید در dry-run |
| B7 | تست end-to-end روی زنجیره با امضای واقعی | ❌ نیازمند anvil/Amoy |
| B8 | Playwright روی موبایل واقعی | ❌ نیازمند دستگاه/مرورگر |
| B9 | KYC/ژئوبلاک (اگر پول واقعی) | ❌ تصمیم محصولی |

### ۳.۳ برآورد «حداقل تا اولین تراکنش واقعی Amoy با دو گوشی»

| سناریو | زمان تقویمی | فرض |
|---|---:|---|
| **خوش‌بینانه (همه‌چیز آماده)** | **۳–۵ روز کاری** | دامنه، RPC، Firestore، WalletConnect ID و MATIC از قبل؛ فقط deploy + دو گوشی |
| **واقع‌بینانه** | **۲–۳ هفته** | شامل تهیه‌ی زیرساخت، رفع باگ‌های اولین اجرای واقعی، تست iOS/Android |
| **با پول واقعی (نه تست‌نت)** | **۶–۱۲ ماه** | KYC، حقوقی، ممیزی، مجوز، پشتیبانی |

**گلوگاه واقعی، کد نیست:** بعد از این دور، بزرگ‌ترین ریسک اجرای Amoy «پیدا کردن باگ‌های یکپارچگی» است (WalletConnect روی iOS، تأیید USDT، گس، timeout کیف پول). برای همین، یک **dry-run با دو گوشی روی Amoy** باید حداقل ۲ هفته با فرض رفع سریع در نظر گرفته شود.

### ۳.۴ چک‌لیست اجرای Amoy (به‌ترتیب)

1. `forge script script/Deploy.s.sol --rpc-url $AMOY_RPC --broadcast` (با `ORACLE_ADDRESS` و `TREASURY`).
2. توکن USDT تستی را deploy یا از faucet بگیر؛ `VITE_USDT_ADDRESS` را ست کن.
3. env سرور: `PULSAR_ENV=production`, `PULSAR_MATCH_STORE=firestore`, `ESCROW_ADDRESS`, `ESCROW_RPC_URL`, `ORACLE_PRIVATE_KEY`, `ORACLE_CHAIN_ID=80002`, `ORACLE_SIGNING_SECRET`, `ALLOWED_DOMAIN`, `CORS_ALLOW_ORIGINS`, `ALLOWED_HOSTS`, `ADMIN_SECRET`.
4. env کلاینت: `VITE_CHAIN_ID=80002`, `VITE_ESCROW_ADDRESS`, `VITE_USDT_ADDRESS`, `VITE_GAME_SERVER_URL`, `VITE_WALLETCONNECT_PROJECT_ID`.
5. `curl /api/health` ⇒ `escrowConfigured: true`, `rpc.reachable: true`, `chainId: 80002`, `matchStore: firestore`.
6. دو گوشی: اتصال کیف پول، دریافت USDT تستی، approve، create/join، ۳ راند، settle، claim.
7. در Explorer: رویداد `MatchSettled` + انتقال ۹۸٪ به برنده و ۲٪ به treasury.
8. سناریوهای شکست: قطع شبکه در راند ۲، بستن تب برنده، timeout ۳۰+۱۰ دقیقه ⇒ refund.
9. keeper را روی staging روشن کن و تأیید کن که جایزه‌ی رهاشده را خودش settle می‌کند.

---

## ۴. گزارش اجرای آیتم‌به‌آیتم (کامیت‌ها روی `arena/a9a25b53-pul-skill`)

قاعده: هر ردیف = یک کامیت (یا گروه هم‌موضوع) + تست رگرسیون سبز در همین مخزن. «اثبات» یعنی نام تست‌هایی که بدون اصلاح، شکست می‌خوردند.

| آیتم | کامیت | تغییر | تست | وضعیت |
|---|---|---|---|---|
| C-01 + L-11 | `393fa13` | `note_start` فقط پس از دوئل واقعی؛ stake قبل از poll | `test_queue_velocity.py` (۳) | ✅ رفع‌شده |
| H-01 + H-02 + M-01 + M-02 | `d204d91` | خودحذفی فقط طولانی‌تر؛ کنترل‌ها fail-closed؛ `state()` بدون نوشتن | `test_responsible_gaming.py` (۴) | ✅ رفع‌شده |
| H-03 + L-10 | `178ba0d` | `/api/ping`، `rttMs` اجباری، RTT واقعی سمت کلاینت | `test_ping_rtt.py` (۴) | ✅ رفع‌شده |
| H-04 | `6382c37` | فید زنده از لاگ settlement سرور | `liveFeed.test.ts` (۴) + `test_public_settlement_log.py` (۲) | ✅ رفع‌شده |
| H-09 + M-05 | `d36dc91` | `revoke_session` بولین؛ ۵۰۳ روی revocation غیرپایدار؛ حذف حریف تخیلی | `test_logout_fail_closed.py` (۲) | ✅ رفع‌شده |
| H-05 + H-17 | `28e4310` | `pulsar_profiles` + `GET/PUT /api/profile`؛ حذف نوشتن مرده‌ی کلاینت؛ `normalizeUserData` + `.catch` روی `recordMatch` | `test_profile.py` (۶) + `userData.normalize.test.ts` (۵) | ✅ رفع‌شده |
| H-18 + **C-04** | `fe8916e` | کل claim نام داخل تراکنش؛ import درست `transactional`؛ خطای سرور ۵۰۳ نه ۴۰۹ | `test_username_atomic.py` (۳) | ✅ رفع‌شده |
| H-06 | `9e3acdb` | production بدون store پایدار بالا نمی‌آید | `test_store_fail_closed.py` (۹) | ✅ رفع‌شده |
| H-15 | `4dedb8c` | میانگین واکنش با شمارنده‌ی نمونه، نه `totalMatches` | ۲ تست در `test_progression_ledger.py` | ✅ رفع‌شده |
| H-13 | `8740d3b` | probe هرمتیک؛ محیط شل دیگر نتیجه را عوض نمی‌کند | اجرای probe با env متناقض | ✅ رفع‌شده |
| H-10 | `5185ff3` | dispute پایدار در `pulsar_disputes` + شمارنده‌ی خطا در health | `test_dispute_persistence.py` (۴) | ✅ رفع‌شده |
| H-16 | `a013308` | CSP + nosniff + frame-deny + COOP + HSTS تولیدی | `test_security_headers.py` (۴) | ✅ سمت API؛ هدرهای هاست استاتیک = کار deploy (§4b) |
| — | `2f4bc6d` | جدول ایندکس مستندات (شامل کوئری‌ای که وجود نداشت) | `test_firestore_indexes.py` | ✅ |
| C-02b + H-08 | `6a5add9` | حذف ادعاهای «بیومتریک/ضدربات/کلاک سخت‌افزاری» در ۵ زبان | `translations.honesty.test.ts` (۹) | ✅ رفع‌شده |
| C-02a | `e77af15` | امتیازدهی آماری به شکل زمان‌ها + صف بازبینی ادمین (بدون جریمه‌ی خودکار) | `test_integrity.py` (۱۱) | ✅ رفع‌شده (تشخیص، نه اثبات) |
| C-03 | `35ca34e` | keeper برای settle/refund + ABI/امضای EIP-155 + dry-run پیش‌فرض | `test_keeper.py` (۱۱) | ✅ ساخته و تست شد؛ اجرا روی Amoy لازم است |

**آیتم‌های باز (به‌ترتیب اجرا):** C-02c (تصمیم محصولی)، H-07، H-11، H-12، H-14، M-03/M-04/M-06…M-24، L-series.

**دو یافته‌ی جدید در جریان رفع:**
- **C-04** (مسدودکننده): `POST /api/username/claim` در production همیشه ۴۰۹ برمی‌گرداند — نه به‌خاطر تکراری بودن نام، بلکه چون import دکوراتور تراکنش در نسخه‌ی pin‌شده شکست می‌خورد و استثنا در یک `except` عمومی به ۴۰۹ تبدیل می‌شد.
- **H-16 (دامنه):** CSP سمت API فقط پاسخ‌های API را می‌پوشاند؛ HTML کلاینت را هاست استاتیک سرو می‌کند و در این مخزن کانفیگ هاست وجود ندارد. سیاست دقیق در `docs/DEPLOYMENT.md §4b` آمده و مالک آن «کانفیگ هاست» است، نه کد.
