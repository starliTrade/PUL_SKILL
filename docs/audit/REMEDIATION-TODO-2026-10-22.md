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

### ⚠️ برخورد شناسه (کشف‌شده در ۲۰۲۶-۱۰-۲۴ در ممیزی خودِ این سند)

دو شناسه در این فهرست **دو معنای متفاوت** دارند و کامیت‌های هر دو گروه هم از همین شناسه‌ها استفاده می‌کنند. این را بازنویسی نمی‌کنم (تاریخ git تغییرناپذیر است و ارجاع‌ها در کد پراکنده‌اند)، ولی صریح ثبت می‌کنم:

| شناسه | معنای اصلی (RUTHLESS-AUDIT، ۲۰۲۶-۱۰-۲۲) | معنای دوم (یافته‌های همین جلسه، ۲۰۲۶-۱۰-۲۳) |
|---|---|---|
| **H-17** | `recordMatch` پس از اولین settle می‌شکست (`history` تعریف نشده) — `usePulsarStore.ts` / `realWeb3.ts` | health: `matchStore` «پیکربندی» را با «کار می‌کند» قاطی می‌کرد؛ `store.writable` سه‌حالته + `?deep=1` |
| **H-18** | `doc_ref.create` داخل تراکنش ⇒ `tx.create` (نقص #۶ حسابرس�� اول) | حالت `memory` در همهٔ ماژول‌ها رعایت نمی‌شد |

**وقتی در کد یا کامیت `H-17`/`H-18` دیدی، از جملهٔ جملهٔ حاوی آن تشخیص بده کدام است** (کلیدواژه‌ها: `store.writable`/`probe`/`health` ⇒ معنای دوم؛ `recordMatch`/`history`/`doc_ref` ⇒ معنای اصلی). شناسه‌های بعدی از H-23 یکتا هستند و برخورد ندارند. تست `test_remediation_todo_consistency.py` حالا هر برخورد **جدید** را رد می‌کند.

### فاز ۲ — امنیت و پول (H)

- [x] **H-01** خودحذفی فقط طولانی‌تر می‌شود
- [x] **H-02** کنترل‌های مسئولیت‌پذیری در قطعی fail-closed
- [x] **H-03a** endpoint سبک `/api/ping` و استفاده‌ی کلاینت از آن
- [x] **H-03b** `rttMs` برای صف اجباری شد (کلاینت باید اندازه بگیرد)
- [x] **H-04** endpoint `/api/matches/recent` + فید کلاینت از سرور
- [x] **H-05** پروفایل/دوستان: endpoint سرور + حذف نوشتن مرده‌ی Firestore
- [x] **H-06** production بدون store پایدار بالا نمی‌آید
- [x] **H-07** لایه‌ی امضای قابل‌تعویض (env/KMS) + مستندسازی — `api/signer.py` با بک‌اندهای `local|aws-kms|gcp-kms`، امتناع از بوت با کلید داغ مگر با `PULSAR_ALLOW_LOCAL_SIGNER=1`؛ تست `test_signer.py`
- [x] **H-08** حذف ادعاهای نادرست (همراه C-02b)
- [x] **H-09** `revoke_session` fail-closed
- [x] **H-10** dispute پایدار در Firestore
- [x] **H-11** کاهش فشار صف: ایندکس ورودی + حذف scan تکراری — تست `test_queue_read_cost.py`
- [x] **H-12** sweep امضاها با cursor و معیار deadline — تست `test_sweep_paging.py`
- [x] **H-13** probe A6 هرمتیک
- [x] **H-14** لجر: شمارنده‌ی خطا + هشدار health + **outbox پایدار** (از «فاز بعد» جلوتر رفت: هر settlement شکست‌خورده در `pulsar_ledger_outbox` صف می‌شود و sweep آن را تخلیه می‌کند) — تست `test_ledger_outbox.py`
- [x] **H-15** میانگین زمان واکنش با شمارنده‌ی نمونه
- [x] **H-16** CSP + هدرهای امنیتی
- [x] **H-17** (یافتهٔ جدید، ۲۰۲۶-۱۰-۲۳) health: تفکیک «پیکربندی» از «ذخیره‌سازی کار می‌کند» — شمارندهٔ نوشتن + `store.writable` سه‌حالته + `?deep=1` با مهلت واقعی — تست `test_health_store_signal.py` (۱۳)
- [x] **H-18** (یافتهٔ جدید) حالت memory در همهٔ ماژول‌ها رعایت می‌شود: `PULSAR_MATCH_STORE=memory` دیگر در `abuse`/`eligibility`/`limits` نادیده گرفته نمی‌شود؛ استور هم در محیط production-like آن را بی‌صدا نمی‌پذیرد؛ لانچر بدون emulator «REFUSING» می‌دهد نه هنگ — تست `test_memory_mode_is_honoured.py` (۹) + `test_e2e_stack_script.py` (۸)
- [x] **H-19** (یافتهٔ جدید) مسیرهای مطلق sandbox (`/root/workspace/.foundry/bin/cast`) از ۴ نقطه حذف شد؛ `scripts/foundry_bin.py` با اولویت PATH → `~/.foundry/bin` → مسیر قدیمی — تست `test_no_sandbox_paths.py` (۶)
- [x] **H-20** (یافتهٔ جدید) `chaos_suite.py` به `/api/queue` بدون `rttMs` می‌فرستاد (۴۲۲) و آن را «pairing failed» گزارش می‌کرد؛ سناریوی fail-closed هیچ‌وقت اجرا نمی‌شد — اجرای دوباره: ۲۰ pass / ۴ fail (همه emulator)
- [x] **H-21** (یافتهٔ جدید) `load/locustfile.py` همان ۴۲۲ را **موفقیت** می‌شمرد؛ ردیف queue در `docs/LOAD-REPORT.md` نامعتبر بود و اکنون با اندازه‌گیری واقعی (p50 ۴ms) جایگزین شد — تست `test_harness_matches_api_contract.py` (۲)
- [x] **H-22** (یافتهٔ جدید) گیت‌های زندهٔ SIWE با محدودیت ۱۰ nonce در دقیقه برخورد می‌کردند و «assert token is not None» می‌دادند (محدودیت نرخ، با لباس باگ محصول). حالا `Retry-After` را رعایت می‌کنند (تا ۳ تلاش) و ۴۲۹ واقعی بلند شکست می‌خورد — تست `test_rate_limit_is_not_a_failure.py` (۸)
- [x] **FUZZ-NIGHTLY** (محور مستقل، ۲۰۲۶-۱۰-۲۳) پروفایل `nightly` از CT14 در فایل بود و **هرگز اجرا نشده بود** (همهٔ گیت‌ها `default`/`ci` بودند). اجرا شد: `FOUNDRY_PROFILE=nightly forge test` → **۱۰۴ تست، ۰ شکست، ۲۱ دقیقه و ۴ ثانیه**؛ ۵ تست fuzz × ۱۰٬۰۰۰ اجرا = **۵۰٬۰۰۰ ورودی تولیدشده** بدون نمونهٔ نقض؛ ۶ invariant × ۱٬۰۲۴ ران × عمق ۵۰۰ = **۳٬۰۷۲٬۰۰۰ فراخوانی** روی پنج کنش handler و هر شش ویژگی پول سبز. **اما گزارش صادق است که این سبزی از آنچه به‌نظر می‌رسد ضعیف‌تر است:** با `fail_on_revert = false`، ۲۸٬۸۵۶ از ۱۰۲٬۳۶۶ فراخوانی `join` (۲۸٫۲٪) و ۲٬۳۱۵ از ۱۰۲٬۷۱۱ `settle` (۲٫۳٪) revert شدند و **طبقه‌بندی نشدند** — علت شناسایی شد (کنش `refund` زمان را با `vm.warp` جلو می‌برد و `joinDuel` با «Match expired» رد می‌کند)، ولی سازوکاری وجود ندارد که یک revert **جدید** را از این نویز پس‌زمینه تشخیص دهد؛ یک‌چهارم بودجهٔ کمپین صرف فراخوانی‌هایی می‌شود که از قبل نامعتبرند. مسیر رفع + برآورد در §۴ گزارش. تست: `test_nightly_profile_doc.py` (۴) — بودجه‌ها، حساب ۵۱۲٬۰۰۰ و ۳٬۰۷۲٬۰۰۰، و اینکه سند این ضعف را اقرار می‌کند
- [x] **H-27** (یافتهٔ جدید، مسیر پول — ۲۰۲۶-۱۰-۲۴) موجودی روی‌زنجیره با `Math.round(...)` به دو رقم **گرد می‌شد، از جمله به بالا** (`realWeb3.fetchLiveOnChainBalances`)، و همان عدد درِ ورود به دوئل شرطی است (`LobbyPage: balance < selectedStake` → بلاک). یعنی کیف پولی با ۴٫۹۹۶ USDT مقدار **۵٫۰۰** نشان می‌داد و از درِ استیک ۵ رد می‌شد؛ بازیکن تراکنشی را امضا می‌کرد که قرارداد ناچاراً رد می‌کرد («execution reverted» در والت، بعد از تعهد به دوئل). همان کلاس نقص H-17: صفحه دربارهٔ پول بازیکن چیزی را ادعا می‌کرد که درست نبود. اکنون `floorToDecimals` (فایل `src/lib/money.ts`) به‌جای گرد کردن **می‌بُرد**؛ برای مقدار نامتناهی/NaN صفر برمی‌گرداند چون `NaN < stake` نادرست است و درِ ورود را **باز** می‌گذاشت. تست `balanceRounding.test.ts` (۶) — جهت گرد کردن، نه پیاده‌سازی: ۴٫۹۹۶ هرگز نباید ۵٫۰۰ دیده شود
- [x] **I18N-AUDIT** (محور مستقل، ۲۰۲۶-۱۰-۲۳) ممیزی پنج‌زبانه با ابزار، نه با ادعا: **۴۲ رشتهٔ قابل‌مشاهده هیچ‌وقت به دیکشنری نرسیده بودند** — «Loading…»، «Duels»، «Network/Token»، «Sync/Syncing…»، «Copy/Copied»، «Connected»، «Detected/Popular»، «1-Tap Mobile Testing»، جملهٔ کامل کد اتصال، بنرهای راند بازی («ROUND 3 WON!»)، پیام‌های پول («Payout confirmed…»، «Wallet action cancelled — no funds moved.»)، پیام‌های بازگشت وجه، عنوان گواهی، برچسب‌های سطح شرط و نام جایگزین حریف؛ همه به کلید تبدیل شدند (‏en ۴۶۰→۵۰۲). **صفحهٔ اتصال کیف پول کل خودش `direction: ltr` داشت** روی ~۲۵ رشتهٔ ترجمه‌شده (فارسی/عربی با ترتیب کلمات انگلیسی). **اعداد با locale مرورگر قالب می‌شدند** — ۵ مورد `toLocaleString()` و یک `toLocaleTimeString([])`؛ یعنی همان عدد برای یک کاربر `1,234` و برای کاربر دیگر `۱٬۲۳۴` (و AM/PM انگلیسی خارج از هر دیکشنری) — اکنون یک قالب‌کنندهٔ واحد (`src/lib/localeFormat.ts`) با سیاست «همهٔ ارقام لاتین»، و ۳۳ رشتهٔ ترجمه که ارقام فارسی/عربی داشتند هم‌سان شدند. تاریخچهٔ مسابقه شناسهٔ ذخیره‌شده را خام چاپ می‌کرد (`Reaction Duel (Ranked · Bo3)`) — نقشه‌برداری در لایهٔ نمایش (`src/lib/matchLabel.ts`)، شناسه دست‌نخورده. ۹ جای `text-left/text-right` در محتوای صفحه → logical. تست: `i18nAudit.test.ts` (۱۱) + `i18nAuditDoc.test.ts` (۴) + `matchLabel.test.ts` (۴). گزارش کامل با «هنوز باز» و هزینه: `docs/I18N-AUDIT.md`
- [x] **H-26** (یافتهٔ جدید، مسیر پول) `onchain.verify_settlement_tx` — تابعی که تعیین می‌کند آیا tx ارائه‌شده واقعاً **همان** مچ را برای **همان** مدعی تسویه کرده — **صفر** تست مستقیم داشت: هر دو تستی که endpoint کلایم را می‌زدند آن را با `lambda *a, **k: True` جای‌گذاری می‌کردند (`test_claim_and_queue.py:101,133`). یعنی «کلایم تأیید می‌شود» اثبات شده بود و خودِ تأیید فقط فرض. ۱۵ تست مستقیم روی RPC جعلی، هر شرط قرارداد را می‌شکند: tx برگشتی (revert)، `to` غلط، لاگ از قرارداد دیگر، مچ اشتباه، برندهٔ اشتباه، رسید بدون event، topic بریده، هش بدشکل (بدون هیچ فراخوانی RPC)، رسید ناخوانا، قطعی RPC، زنجیرهٔ اشتباه، escrow تنظیم‌نشده، و «هرگز raise نمی‌کند». **همین تست یک نقص واقعی پیدا کرد:** اگر `logs` یک عضو غیر-دیکشنری داشت (رشته، `null`، عادت پرووایدر)، `log.get` استثنا می‌داد و endpoint کلایم **۵۰۰** برمی‌گرداند به بازیکنی که جایزه‌اش روی زنجیره پرداخت شده بود — گارد `isinstance(log, dict)` اضافه شد. نتیجهٔ پوشش: `onchain.py` ۸۱٪ → **۹۰٪**، کل ۷۷٪ → **۷۸٪**، و کف گیت هرمتیک در همان کامیت از ۷۴ به **۷۷** رفت (طبق قاعدهٔ خودِ فایل). گزارش تفصیلی: `docs/COVERAGE-REPORT.md`. تست `test_claim_verification.py` (۱۵) + `test_coverage_report_is_true.py` (۵)
- [x] **H-25** (یافتهٔ جدید، مسیر پول) `settlement_deadline` برای مچِ بدون timestamp مقدار **۱۸۰۰** (۱۹۷۰) برمی‌گرداند؛ نتیجه: (۱) اوراکل با پیام دروغین «MATCH_TIMEOUT گذشته» از امضا امتناع می‌کرد و جایزهٔ برنده قفل می‌شد، (۲) sweep امضای مجدد آن مچ را **برای همیشه بی‌صدا** رد می‌کرد. حالا `settlement_deadline_or_none` صریحاً None می‌دهد، `settlement_deadline` با پیام گویا raise می‌کند، اوراکل بدون clamp امضا می‌کند (۵ دقیقه/۱۰ دقیقه کماکان محدود) و sweep دوباره تلاش می‌کند — تست `test_settlement_horizon.py` (۹)
- [x] **H-24** (یافتهٔ جدید) سوئیت‌های زنده در هر اجرا ۶+ handshake می‌زدند در حالی که سقف ۱۰/دقیقه per IP است؛ دو اجرای پشت‌سرهم به ۴۲۹ می‌خورد و «assert None is not None» می‌داد. حالا هر هویت یک بار per run ساخته و کش می‌شود (۲ به‌جای ۶ در eligibility، کل handshake یک run کامل: ۴) — تست `test_live_sessions_are_minted_once.py` (۵)
- [x] **H-23** (نقص در رفعِ خودِ H-17، با ممیزی دوباره پیدا شد) `?deep=1` بدون احراز هویت، بدون محدودیت، و هر درخواست یک read **پول‌دار** + یک thread — یک آمپلی‌فایر هزینه. حالا: کش ۵ ثانیه‌ای + ۱۲/دقیقه per IP؛ `/api/health` ساده همچنان آزاد (وگرنه orchestrator کانتینر سالم را ری‌استارت می‌کند). همچنین `probe.ok` در حالت «بررسی نشده» `null` است نه `true` — همان قاعدهٔ H-17، یک فیلد آن‌طرف‌تر — تست `test_health_store_signal.py` (۱۷)
- [x] **H-17** نرمال‌سازی سند کاربر + `.catch` روی `recordMatch`
- [x] **H-18** `doc_ref.create` داخل تراکنش ⇒ `tx.create` (نقص #۶ حسابرسی اول)

### فاز ۳ — متوسط/پایین (M/L)

- [x] **M-01** `limits.state()` بدون نوشتن
- [x] **M-03** بن fail-closed (قطع دیتابیس تحریم را برنمی‌دارد) — `test_ban_velocity.py`
- [x] **M-04** جدول امتیازات از سرور؛ حذف خواندن `users` از مرورگر — `test_leaderboard_api.py`
- [x] **M-06** دوئل تصمیم‌نگرفته «pending» است نه «باخت» — `ReactionGamePage.pending.test.tsx`
- [x] **M-07** یک پرامپت واریز برای هر دوئل + تحمل تکرار — `test_deposit_lock.py`
- [x] **M-02** نام‌گذاری صریح: سقف هر دوئل (نه سقف تجمعی)
- [x] **M-05** حذف نام حریف تخیلی در رنکد
- [x] **M-08** تشخیص prod با نشانه‌های پلتفرم (`K_SERVICE`/`RENDER`/`FLY_MACHINE_ID`/`DYNO`) — تست `test_prod_detection.py`
- [x] **M-14** آمار رنکدِ تأییدنشده به‌جای عدد محلی «—» نمایش داده می‌شود — منشأ آمار (`progressionSource: server|local|unknown`) در `UserWalletData`، ست‌شدن در `recordMatch`/`loadUserData`، اکشن `refreshProgression()`، بنر + دکمه‌ی بررسی دوباره در `ProfilePage`، ۵ زبان؛ تست: `usePulsarStore.progression.test.tsx` (۵ جدید) + `ProfilePage.progression.test.tsx` (۴)
- [x] **M-10** لاگ تصمیم‌های ادمین (`auditlog`) — تست `test_admin_audit.py`
- [x] **M-15** coverage: دو گیت جدا — `.coveragerc-hermetic` (بدون emulator/anvil، همانی که باید همیشه سبز باشد) و گیت کامل — تست `test_coverage_gate.py`
- [x] **M-17** اعداد README از خروجی واقعی — `scripts/test_counts.py` اکنون forge را هم واقعاً اندازه می‌گیرد و اگر Foundry نبود دلیلش را می‌نویسد؛ جدول README با خروجی ۲۰۲۶-۱۰-۲۳ به‌روز شد (vitest ۲۸۳/۶۱، pytest ۴۸۸/۳۱، forge ۱۰۴/۹، coverage قرارداد ۹۸.۵۷٪)
- [x] **M-20 (باقی‌مانده)** حذف رانتایم بیگانه از `index.html` — بلوک `BLINK_PICKER_RUNTIME_V2` (۶۹۰ خط، از قالب اولیه، در `365396d`) پاک شد: یک overlay ویرایشگر بصری با `addEventListener('message')` **بدون بررسی origin** که `SET_ELEMENT_ATTRS` را می‌پذیرفت و `textContent`/`className`/`style` هر عنصری را با selector دلخواه بازنویسی می‌کرد (یعنی یک فریم والد می‌توانست برچسبِ stake یا دکمه را عوض کند)، به‌علاوه MutationObserver روی کل سند و ‏`postMessage(…,'*')` به والد. اسکریپت purge کلیدهای WalletConnect و کامنت viewport دست‌نخورده ماندند (اسکریپت‌های خودمان). همچنین رجیستری `@blink` از `components.json` حذف شد: هیچ‌چیز استفاده نمی‌کرد، اما `npx shadcn add @blink/...` کدِ داورده‌نشده از یک Cloudflare Worker ناشناس می‌آورد. `dist/index.html` بعد از build: بدون هیچ ارجاعی به آن و ۵٫۷KB. تست `no-foreign-runtime.test.ts` (۸)
- [x] **M-23** اجرای واقعی suite قرارداد و گزارش خروجی — `forge test` (۹ suite، ۱۰۴ تست) و `FOUNDRY_PROFILE=ci` (invariant با ۵۱٬۲۰۰ فراخوانی) هر دو سبز؛ سقف گارد CI از ۷۵ به ۱۰۰ رسید تا حذف ۴ تست را بگیرد؛ `PyYAML` به `requirements-dev` اضافه شد چون بدون آن ۱۸ تست «قرارداد CI» بی‌صدا skip می‌شدند
- [x] **M-19/M-21/M-22** حریم خصوصی (export/erase + بستن کلکسیون‌ها به کلاینت)، LICENSE و SECURITY.md — تست `test_privacy.py` + `test_docs_honesty.py`
- [x] **M-24** خطای ذخیره‌سازی قابل‌مشاهده — `saveStatus` + بنر با دکمهٔ تلاش دوباره — تست `SaveStatusBanner.test.tsx` + `realWeb3.profileSync.test.ts`
- [x] **L-09** چرخه‌ی عمر گزارش تخلف — `status` واقعی (`open`/`resolved`/`dismissed`) به‌جای هم‌نام‌شدن با وضعیت مسابقه، شناسه‌ی گزارش برای کاربر، `GET /api/dispute/{match}` (فقط شرکت‌کننده، ۴۰۴ برای غریبه)، `POST /api/admin/dispute/{match}/{id}` با ثبت در audit trail، ۵۰۳ به‌جای «ثبت شد» وقتی ذخیره شکست بخورد؛ کلاینت: وضعیت + دکمه‌ی بررسی دوباره در ۵ زبان؛ تست: `test_dispute_lifecycle.py` (۱۵)، `test_dispute_persistence.py` (۷)، کامپوننت (۴)
- [x] **L-05** «۵۳ یافته» در `docs/HOW-IT-WORKS.md` — عدد از مقدمه حذف شد (ممیزی خودش آن را «تأییدنشده» ثبت کرده بود و هیچ شاهد بازتولیدی نداشت)؛ جایش ارجاع به همین جدول آیتم‌به‌آیتم و به جدول README که با `scripts/test_counts.py` تولید می‌شود. تست `test_docs_honesty.py` (`test_how_it_works_does_not_claim_an_unverifiable_finding_count`)
- [x] **L-14** `lang`/`dir` قبل از اولین paint — `<html lang="en">` ثابت بود و `dir` فقط در `LanguageProvider` (بعد از mount) ست می‌شد، پس کاربر فارسی/عربی کل اپ را LTR می‌دید و بعد یک reflow سراسری به RTL. اکنون یک اسکریپت inline با شناسهٔ `pulsar-lang-preboot` از همان کلید `pulsar_lang` (و در نبود آن از `navigator.languages`) قبل از هر ماژول `lang`/`dir`/کلاس `rtl` را می‌گذارد؛ `dir="ltr"` ثابت هم برای no-JS/کراولر اضافه شد. تست `lang-preboot.test.ts` (۱۱) که **همان اسکریپت منتشرشده** را اجرا می‌کند (fa/ar → rtl، زبان نامعتبر → en، localStorage مسدود → fail-safe، هم‌خوانی کلید با provider).
- [x] **L-12** «حریف تخیلی» در UI تمرینی — overlay آماده‌سازی *فقط* برای حالت تمرین است (`handleStartMatchmaking` برای حالت واقعی early-return می‌کند و سرور خودش جفت می‌کند)، اما می‌نوشت «OPPONENT READY» و «Starting duel vs ShadowStrike…» و هیچ‌جا نمی‌گفت ربات است. سه کلید جدید در ۵ زبان (`practicePartnerReady`، `practiceDuelVs`، `practiceBotNotice`) و یک خطِ صریح روی همان صفحه: «حریف شما اینجا ربات تمرینی است، نه بازیکن دیگر — بدون شرط، بدون جایزه، بدون رتبه». دو کلید گمراه‌کننده ‏(`opponentSecured`، `lockingEscrowAgainst`) از هر ۵ زبان حذف شدند. تست `LobbyPage.practice.test.tsx` (۳)
- [x] **L-06** `docs/LOAD-REPORT.md` بازنویسی شد با شرایط هر عدد — ماشین (۲ vCPU)، یک worker، store، تعداد کاربر، و اینکه **generator روی همان CPU است**. اندازه‌گیری‌های امروز (memory store): ۲۰۰ کاربر → ۱۵۷ req/s با p50 سمت سرور ≈۱ms و p95 ≤۳۵ms؛ ۱۰۰۰ کاربر → ۳۴۳ req/s و ۰ خطا، اما p50 همان `/api/health` که هیچ کاری نمی‌کند ۱٬۷ ثانیه است ⇒ امضای گرسنگی CPU، نه هزینهٔ کد. اعداد emulator با تاریخ و برچسب «اینجا بازتولیدپذیر نیست» (java/firebase CLI موجود نیست). یک ادعای پوشیده («app گلوگاه نیست») به دو ادعای دقیق شکسته شد. تست `test_load_report_scope.py` (۷).
  **دو نقص واقعی در همین مسیر:** (۱) پروفایل بار وارد صف می‌شد بدون attestation صلاحیت ⇒ هر join ‏403 و اندازه‌گیریِ دروازه نه صف؛ (۲) با host اشتباه، listener آماده‌سازی می‌مرد، اجرا با **صفر** session ادامه می‌داد و خروجی سبز نشان می‌داد — الان صریحاً abort می‌کند. `scripts/load_sessions.py` (توکن با همان `auth.issue_session`، چون `/api/auth/verify` سقف ۳۰/دقیقه/IP دارد) + تست (۴)
- [x] **L-04** ادعای «Playwright همیشه SKIP می‌شود» — حذف شد و با وضعیت واقعی جایگزین شد (۳۰ تست / ۶ فایل / دو پروژه، هارنس واقعی را بالا می‌آورد). سه باگ واقعی زیر همین آیتم پیدا و رفع شد:
  ‏(۱) `scripts/start_e2e_stack.sh` با `exit 1# --- 0. the manifest…` — یک newline گم‌شده کل انتهای فایل را کامنت کرده بود؛ اسکریپت با «numeric argument required» (کد ۲) می‌مرد و گارد «manifest با زنجیره نمی‌خواند» **هرگز یک‌بار هم اجرا نشده بود** (همان حالتی که برای جلوگیری ازش نوشته شده بود). گارد به جای درست (قبل از بالا آوردن API) منتقل شد؛ تست `test_e2e_stack_script.py` (۵).
  ‏(۲) `/api/health` با Firestore در دسترس‌نبودن **بی‌نهایت** هنگ می‌کرد (بیش از ۱۲۰ ثانیه اندازه‌گیری شد؛ `stream(timeout=…)` و حتی `retry=None` هم آن را حل نکرد). یک liveness probe باعث restart loop می‌شد. اکنون health هیچ خواندی انجام نمی‌دهد: یک ترد daemon (حداکثر یکی) می‌خواند و پاسخ cache‌شده با `readStatus`/`readError` برمی‌گردد؛ تست `test_health_is_bounded.py` (۴). پس از رفع: health در ۳ میلی‌ثانیه.
  ‏(۳) بدون `bun` هیچ‌چیز اجرا نمی‌شد (`bun: not found` در webServer و `verify.sh`): هر دو به npm برمی‌گردند؛ `verify.sh` هم دیگر به bun گره نخورده.
  همچنین: `PULSAR_E2E_API_PORT` در سه spec نادیده گرفته می‌شد (ECONNREFUSED روی ۸۰۰۰) → `API_ORIGIN` مشترک؛ و `.env.example` برای سه متغیر جدید به‌روز شد.
  **محدودیت محیط (ادعا نمی‌شود):** در این sandbox `npx playwright install` به هاست دانلود دسترسی ندارد، پس مرورگر نصب نشد؛ suite هارنس واقعی را بالا می‌آورد و سپس در `browserType.launch` شکست می‌خورد. اجرای واقعی ۳۰ تست E2E روی ماشین شما ممکن است (چک‌لیست دستی، بخش ۰).
- [x] **L-02** `savedFriends` — API سروری از قبل وجود داشت (`GET`/`PUT /api/profile` + `pulsar_profiles`) و تست HTTP داشت، اما دو گپ واقعی مانده بود: (۱) `getSavedFriendsList` همگام و فقط از localStorage می‌خواند، پس فهرستی که فقط روی سرور بود (دستگاه تازه، کش پاک‌شده، ذخیره پیش از ورود) در UI «هیچ دوستی» نشان می‌داد؛ اکنون `refreshSavedFriends()` هنگام باز شدن مودال از سرور می‌خواند و کش می‌کند و در خطا فهرست محلی را پاک نمی‌کند؛ (۲) ذخیره بدون session فقط محلی بود و «ذخیره شد» می‌گفت — اکنون پیام «فقط در همین مرورگر» در ۵ زبان. تست: `realWeb3.savedFriends.test.ts` (۵) + `test_profile_durable.py` (۷، مسیر واقعی Firestore با کلاینت تقلبی — قبلاً فقط `_memory` تست می‌شد)
- [x] **L-07** analytics «نفر» را می‌شمارد نه «درخواست» — `note_person()` روی چهار قدم (`arrived` در nonce، `connected` بعد از ecrecover، `queued`، `settled`) مجموعه‌ی سقف‌دار آدرس (`_MAX_PEOPLE_PER_STEP = 5000`) نگه می‌دارد؛ خروجی `people` با `scope` («این پروسه»)، `capPerStep` و `truncated` (اگر سقف خورد، صریحاً «کران پایین» است نه شمارش)؛ بلوک PII هم می‌گوید کلید در حافظه چیست و ذخیره نمی‌شود. تست: `test_analytics_people.py` (۷)
- [x] **L-08** metrics با سقف ۶۴ route و per-process — رفتار سقف حفظ شد (dict بی‌کران نشتی است) اما دیگر خاموش نیست: `requestsObserved`، `routesDropped`، `routesTracked`، `routesCap`، `complete` و `scope` در payload؛ «۱٬۴۱۲ درخواست، ۳۰۰ رهاشده» خوانده می‌شود به‌جای عددی که کامل به‌نظر می‌رسد و نیست. تجمیع چند replica عمداً انجام نشد (نیازمند Redis/متریک سرور است) و همین در payload نوشته شده. تست: `test_metrics_bounds_honest.py` (۵)
- [x] **L-01** خطاهای حساس فقط در کنسول نمانند — خواندن موجودی، عدم دسترسی به لجر پیشرفت و قطع فید حالا به `monitoring.reportError` هم می‌روند (no-op بدون Sentry)؛ تست `telemetry-sensitive.test.ts` (۶)
- [x] **M-11** قرارداد نسخه‌دار + پنجره‌ی مهاجرت (proxy رد شد، با دلیل مستند) — `PulsarEscrow.VERSION/VERSION_CODE`، `freeze/unfreeze`، دفتر `totalLocked`/`residualBalance`/`sweepResidual`؛ `api/onchain.escrow_version()` + `escrowVersionProblem` در `/api/health`؛ `docs/UPGRADE-PATH.md`؛ تست: `contracts/test/PulsarEscrowMigration.t.sol` (۱۸)، دو invariant جدید در `PulsarEscrowInvariants.t.sol`، `tests/unit/test_contract_version.py` (۱۲)
- [x] **M-12** پارامتر کارمزد ثابت و treasury — تصمیم محصولی در `docs/ECONOMICS.md` ثبت شد (مدل، مثال‌های عددی، ردِ `setFeeBps`، الزام multisig برای treasury، و تحلیل واحد-اقتصاد که می‌گوید L1 با این نردبان استیک توجیه ندارد)؛ تست: `tests/unit/test_economics_doc.py` (۹)
- [x] **M-18** نسخه‌بندی service worker — `CACHE` از `VERSION` نسخه می‌گیرد، `install` هیچ‌وقت `skipWaiting()` صدا نمی‌زند و سوئیچ فقط با پیام صفحه انجام می‌شود؛ ۱۱ تست در `src/test/pwa.service-worker.test.ts` خود worker را با scope جعلی بارگذاری و fetch handler را اجرا می‌کنند. **باقی‌مانده (خارج از این محیط):** تأیید واقعی «دهانه‌ی خالی بعد از deploy» در مرورگر
- [x] **M-20** متادیتای PWA/OG و تصویر واقعی — `og:image` واقعی ۱۲۰۰×۶۳۰ (`public/og-image.png`)، `twitter:card=summary_large_image`، `og:url`/`og:type`/`og:site_name`/`image:alt`، آیکون‌های PNG ۱۹۲/۵۱۲ + maskable + apple-touch، `id`/`lang`/`categories` در manifest، جای‌گذاری `__SITE_URL__` در build با `vite-plugin-seo.ts` (هشدار وقتی `VITE_SITE_URL` ست نشده)، `<noscript>`؛ تست: `src/seo/metadata.test.ts` (۱۴)

### فاز ۴ — نیازمند محیط/انسان (در این سند فقط برنامه)

- [x] اجرای `forge test` + invariant (Foundry) — ۱۰۴ تست در ۹ suite، همه سبز (اجرای واقعی ۲۰۲۶-۱۰-۲۳)
- [x] اجرای `forge coverage` — forge 1.7.1 این زیرفرمان را دارد: `PulsarEscrow.sol` = ۹۸.۵۷٪ خطوط، ۹۸.۴۸٪ دستورها، ۸۶.۷۳٪ شاخه‌ها، ۱۰۰٪ توابع (۳۱/۳۱)
- [ ] اجرای Playwright روی مرورگر واقعی
- [ ] emulator Firestore + تست integration
- [x] anvil + تست chain — `scripts/start_anvil.sh --bg` + `pytest -m chain`: ۱۱ تست سبز (مسیر پول با امضای واقعی oracle روی EVM واقعی)
- [ ] ممیزی قرارداد توسط firm
- [ ] KYC/AML + ژئوبلاک + مجوز
- [ ] تست Amoy با دو گوشی واقعی

---

## ۲. گزارش اجرا (این دور)

| گیت | نتیجه (آخرین اجرا: `8907ac3` + این دور) |
|---|---|
| `pytest -q` | **۶۲۳ passed، ۲۵ skipped** (anvil + API بالا)؛ ۵۷۸ / ۴۱ با همه‌چیز خاموش |
| `forge test` | **۱۰۴ passed / ۹ سوئیت** (Foundry 1.7.1 نصب شد؛ پیش از این در این محیط اجرا نشده بود) |
| `pytest -m chain` | **۱۱ passed** روی anvil واقعی |
| `vitest run` | **۳۳۲ passed** (۶۷ فایل) |
| `tsc --noEmit` | ۰ خطا |
| `eslint .` | ۰ خطا |
| `ruff` / `mypy` | پاک / پاک (۲۲ فایل) |
| `chaos_suite.py` | ۲۰ pass / ۴ fail — هر ۴ سناریوی emulator/replica (Java نداریم) |
| `npx playwright test --list` | ۳۰ تست / ۶ فایل — **اجرا نشده** (دانلود مرورگر مسدود) |

> این جدول قبلاً «۳۶۰ passed / ۲۳۴ vitest» را نشان می‌داد در حالی که کد سه کامیت جلوتر بود؛
> یک سند وضعیت که در جهت امن اشتباه باشد هم همان ضرر را دارد.

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
| H-07 | `32c05a6` | لایه‌ی امضا: `local`/`aws-kms`/`gcp-kms`؛ بوت در حالت production فقط با انتخاب صریح | `test_signer.py` | ✅ سمت کد؛ اعتبارنامه‌ی واقعی KMS = محیط |
| H-11 + H-12 + H-14 | `32c05a6` | ایندکس صف + حذف scan تکراری؛ sweep صفحه‌بندی‌شده با deadline؛ outbox پایدار لجر | `test_queue_read_cost.py`, `test_sweep_paging.py`, `test_ledger_outbox.py` | ✅ رفع‌شده |
| M-08 + M-09 + M-10 + M-13 + M-19 + M-21 | `8d45d5e` | نشانه‌های پلتفرم برای prod؛ XFF فقط با flag؛ audit trail ادمین؛ رویدادهای ساختاریافته؛ export/erase؛ بستن کلکسیون‌ها به کلاینت | `test_prod_detection.py`, `test_admin_audit.py`, `test_privacy.py` | ✅ رفع‌شده |
| M-17 + M-22 | `6966104` | اعداد README از اجرای واقعی + LICENSE + SECURITY.md | `test_docs_honesty.py` | ✅ رفع‌شده |
| M-18 + M-24 | `f734fd1` | بنر خطای ذخیره با تلاش دوباره؛ سرویس‌ورکر «منتظر» تا وقتی تب بسته نشود | `SaveStatusBanner.test.tsx`, `realWeb3.profileSync.test.ts` | ✅ رفع‌شده |
| M-15 | `88c33d9` | دو گیت coverage: هرمتیک (همیشه سبز) و کامل (emulator+anvil) | `test_coverage_gate.py` | ✅ رفع‌شده |
| C-02c | `eda82a1` | تصمیم مکتوب: KYC/سقف برداشت/تأخیر پرداخت، و اینکه چرا دو کنترل امروز ممکن نیست | `test_compliance_doc.py` | ✅ تصمیم ثبت شد؛ اجرا = کسب‌وکار |
| M-03 | `bbd1c93` | بن باید fail-closed باشد؛ قطع دیتابیس نباید تحریم را بردارد | `test_ban_velocity.py` | ✅ رفع‌شده |
| M-04 | `223500d` | جدول امتیازات از سرور؛ حذف خواندن `users` از مرورگر | `test_leaderboard_api.py` | ✅ رفع‌شده |
| M-06 | `5c83b6f` | دوئل تصمیم‌نگرفته «pending» است، نه «باخت» | `ReactionGamePage.pending.test.tsx` | ✅ رفع‌شده |
| M-07 | `0c7850d` | یک پرامپت واریز برای هر دوئل، تحمل تکرار | `test_deposit_lock.py` | ✅ رفع‌شده |
| M-11 + M-12 | `2e42dc2` | escrow نسخه‌دار + پنجرهٔ مهاجرت + سند تصمیم کارمزد | `PulsarEscrowMigration.t.sol`, `test_contract_version.py` | ✅ (نیازمند redeploy روی anvil) |
| M-14 | `cd13104` | آمار تأییدنشده «—» با منبع مشخص، نه حدس محلی | `usePulsarStore.progression.test.tsx` (۵), `ProfilePage.progression.test.tsx` (۴) | ✅ رفع‌شده |
| M-20 | `e1050ae` + `d87f96b` | OG/Twitter/PWA + آیکون‌های PNG؛ سپس حذف کامل رانتایم بیگانهٔ قالب از `index.html` و رجیستری `@blink` | `metadata.test.ts` (۱۴), `no-foreign-runtime.test.ts` (۸) | ✅ رفع‌شده |
| M-23 + M-17 | `cdce885` | اجرای واقعی forge (۱۰۴ تست / ۹ suite) و coverage قرارداد؛ سقف گارد CI ۷۵→۱۰۰ | `test_ci_workflow.py` | ✅ رفع‌شده |
| L-01 + L-09 | `f93b50f` | چرخهٔ عمر گزارش تخلف + تلمتری خطاهای حساس | `test_dispute_lifecycle.py` (۱۵), `test_dispute_persistence.py` (۷), `DisputeReportButton.test.tsx` (۴), `telemetry-sensitive.test.ts` (۶) | ✅ رفع‌شده |
| L-02 | `b80cece` | `savedFriends` از سرور خوانده و کش می‌شود؛ هشدار «فقط همین مرورگر» | `realWeb3.savedFriends.test.ts` (۵), `test_profile_durable.py` (۷) | ✅ رفع‌شده |
| L-04 | `8e62779` | ادعای «Playwright همیشه SKIP» حذف؛ + سه باگ واقعی: اسکریپت E2E مرده، health بی‌نهایت، وابستگی به bun | `test_e2e_stack_script.py` (۵), `test_health_is_bounded.py` (۴) | ✅ رفع‌شده؛ اجرای مرورگر = محیط |
| L-05 | `6488a1c` | حذف عدد بی‌شاهد از `HOW-IT-WORKS` + ارجاع به شاهد | `test_docs_honesty.py` (۱ جدید) | ✅ رفع‌شده |
| L-06 | `ad13fc0` | بازنویسی `LOAD-REPORT` با شرایط هر عدد + سنجش واقعی ۲۰۰/۱۰۰۰ کاربر + `load_sessions.py` | `test_load_report_scope.py` (۷), `test_load_sessions_tool.py` (۴) | ✅ رفع‌شده؛ capacity production = محیط |
| L-07 + L-08 | `63bd35e` | شمارش «نفر» با سقف و برچسب truncation؛ metrics رهاشده‌ها را اعتراف می‌کند | `test_analytics_people.py` (۷), `test_metrics_bounds_honest.py` (۵) | ✅ رفع‌شده |
| L-12 | `ba634e8` | bot به‌عنوان bot نامیده می‌شود، با شرایط، در ۵ زبان | `LobbyPage.practice.test.tsx` (۳) | ✅ رفع‌شده |
| L-14 | `f56a139` | `lang`/`dir` قبل از اولین paint + `dir="ltr"` ثابت برای no-JS | `lang-preboot.test.ts` (۱۱) | ✅ رفع‌شده |
| H-17 | (این کامیت) | `matchStore` فقط پیکربندی است؛ شاهدِ واقعی `store.writable`/`store.probe` | `test_health_store_signal.py` (۱۳) + `test_go_live_runbook.py` (۸) | ✅ رفع‌شده |
| H-18 | (کامیت H-18) | حالت memory در abuse/eligibility/limits و در استور رعایت می‌شود؛ لانچر بدون DB بالا نمی‌آید | `test_memory_mode_is_honoured.py` (۹) | ✅ رفع‌شده |
| H-19 | (کامیت H-19) | کشف cast/forge/anvil از PATH و `~/.foundry/bin`، نه مسیر sandbox | `test_no_sandbox_paths.py` (۶) | ✅ رفع‌شده |
| H-20 | (کامیت H-20) | chaos: `rttMs` در ۴ فراخوانی queue؛ سناریوی fail-closed دوباره اجرا می‌شود | اجرای `chaos_suite.py`: ۲۰ pass / ۴ fail (emulator) | ✅ رفع‌شده |
| H-21 | (کامیت H-21) | locust: فقط 200 = موفق؛ 422 = شکست؛ 429 جدا شمرده می‌شود + تصحیح `LOAD-REPORT` | `test_harness_matches_api_contract.py` (۲) | ✅ رفع‌شده |
| H-22 | (کامیت H-22) | گیت‌های زنده `Retry-After` را رعایت می‌کنند، بدون تضعیف محدودیت نرخ | `test_rate_limit_is_not_a_failure.py` (۸) + دو اجرای متوالی زنده (۰٫۲۴s و ۶۰٫۳۳s، هر دو سبز) | ✅ رفع‌شده |
| H-23 | (کامیت H-23) | deep health: کش ۵ ثانیه + ۱۲/دقیقه per IP؛ `probe.ok` سه‌حالته | `test_health_store_signal.py` (۱۷) | ✅ رفع‌شده |
| H-24 | (کامیت H-24) | گیت‌های زنده هر هویت را یک بار per run می‌سازند: ۶ → ۲ handshake | `test_live_sessions_are_minted_once.py` (۵) + سه اجرای متوالی eligibility (۰٫۱۴s هرکدام) | ✅ رفع‌شده |
| H-25 | (کامیت H-25) | فقدان timestamp ≠ ۱۹۷۰: horizon «نامعلوم»، sweep دیگر برنده را رها نمی‌کند | `test_settlement_horizon.py` (۹) + `test_escrow_timing_parity.py` (۶، حالا رفتاری) | ✅ رفع‌شده |
| H-26 | (کامیت H-26) | تأیید تسویه واقعاً تست شد (۱۵ حالت) و یک ۵۰۰ واقعی روی مسیر کلایم بسته شد؛ پوشش ۷۷→۷۸٪ | `test_claim_verification.py` (۱۵) + `test_coverage_report_is_true.py` (۵) + `docs/COVERAGE-REPORT.md` | ✅ رفع‌شده |
| I18N | (کامیت i18n) | ۴۲ رشتهٔ ترجمه‌نشده، ۲ قفل جهت روی متن ترجمه‌شده، اعداد وابسته به locale مرورگر، ۳۳ رشته با ارقام غیرلاتین — همه بسته شد و رچت شد | `i18nAudit.test.ts` (۱۱) + `i18nAuditDoc.test.ts` (۴) + `matchLabel.test.ts` (۴) + `docs/I18N-AUDIT.md` | ✅ بسته (۲ مورد باز با هزینه در §۶) |
| H-27 | (کامیت H-27) | موجودی به بالا گرد می‌شد و درِ استیک را با پول ناکافی باز می‌کرد؛ حالا به پایین می‌بُرد و NaN صفر می‌شود | `balanceRounding.test.ts` (۶) | ✅ رفع‌شده |
| FUZZ | (کامیت nightly) | پروفایل nightly اولین اجرا: ۱۰۴ تست / ۰ شکست / ۲۱ دقیقه؛ ۵۰٬۰۰۰ ورودی fuzz و ۳٬۰۷۲٬۰۰۰ فراخوانی invariant — با اقرار صریح به revertهای طبقه‌بندی‌نشده | `test_nightly_profile_doc.py` (۴) + `docs/CONTRACT-FUZZ-REPORT.md` | ✅ اجرا و ثبت شد (بهبود کمپین باز، ~۱٫۵ ساعت) |

**مشاهدهٔ باز (صادقانه، حل‌نشده):** در یکی از اجراهای کامل،
`test_chain_smoke.py::test_settlement_with_a_real_oracle_signature_pays_the_winner`
یک بار شکست خورد و **سه اجرای کامل بعدی سبز بودند** (۶۲۳ pass). علت تأیید نشده است؛
فرضیهٔ محتمل `deadline` امضای اوراکل است که به زمان **زنجیره** لنگر می‌اندازد و در آن اجرا
۶۰ ثانیه انتظارِ محدودیت نرخ در همان نشست رخ داده بود — اما این فرضیه اثبات نشده و
بنابراین به‌عنوان «رفع‌شده» ثبت نمی‌شود. برای بستن آن: اجرای این تست ۲۰ بار پشت‌سرهم روی
زنجیرهٔ تازه (`for i in $(seq 20); do pytest tests/integration/test_chain_smoke.py; done`).
اگر تکرار شد، لاگ تراکنش (revert reason + `block.timestamp` در مقابل `proof.deadline`) پاسخ را می‌دهد.
**بروز سوم + ابزار تشخیص (۲۰۲۶-۱۰-۲۳):** یک بار دیگر در اجرای کامل دیده شد (سوئیت ۶۶۴ تستی، پیش از افزودن ۴ تست مستندسازی nightly) و **۹ اجرای کامل بعدی سبز** بودند؛ در مجموع ۳ بروز در ~۳۵ اجرای کامل و ۰ بروز در ~۳۰ اجرای تک‌فایلی — یعنی احتمالاً وابسته به ترتیب/فرآیند است، نه به خود تست. به‌جای فرضیه‌سازی، خودِ تست اکنون در صورت شکست `deadline` پاکت، `chain_now()`، تایم‌استمپ آخرین بلاک، مقدار `expired_by` و nonce را چاپ می‌کند (`pytest.fail` با `pytrace=True`) تا بروز بعدی مدرک تولید کند نه حدس. این خودش تست را عوض نمی‌کند: مسیر موفق دقیقاً همان قبلی است.

**تلاش بازتولید (جلسهٔ قبل):** ۱۵ اجرای پشت‌سرهم `test_chain_smoke.py` → **۰ شکست**،
به‌علاوهٔ ۴ اجرای کامل سوئیت → ۲۶ اجرای متوالی سبز. بازتولید نشد. وضعیت: «یک شکست دیدم،
نتوانستم تکرار کنم» — نه «رفع شد»، نه «بی‌اهمیت». اگر در CI یک بار دیگر دیده شد،
دستور بالا و لاگ revert پاسخ را می‌دهد.

**آیتم‌های باز (به‌ترتیب اجرا):** فقط **`C-02c`** (KYC/سقف برداشت/ژئوبلاک — تصمیم حقوقی، خارج از کد، سند: `docs/COMPLIANCE-C-02c.md`). بقیهٔ نیازها محیطی/انسانی‌اند و در `docs/FINAL-REPORT.md §5` فهرست شده‌اند. شمارش دقیق: **۶۲ شناسهٔ یکتا، ۶۱ بسته، ۱ باز** (۶۳ خط تیک‌خورده چون `H-17` و `H-18` دو خط دارند — به یادداشت برخورد شناسه بالا نگاه کن).

**دو یافته‌ی جدید در جریان رفع:**
- **C-04** (مسدودکننده): `POST /api/username/claim` در production همیشه ۴۰۹ برمی‌گرداند — نه به‌خاطر تکراری بودن نام، بلکه چون import دکوراتور تراکنش در نسخه‌ی pin‌شده شکست می‌خورد و استثنا در یک `except` عمومی به ۴۰۹ تبدیل می‌شد.
- **H-16 (دامنه):** CSP سمت API فقط پاسخ‌های API را می‌پوشاند؛ HTML کلاینت را هاست استاتیک سرو می‌کند و در این مخزن کانفیگ هاست وجود ندارد. سیاست دقیق در `docs/DEPLOYMENT.md §4b` آمده و مالک آن «کانفیگ هاست» است، نه کد.
- **H-17 (پیدا شده با اجرای واقعی استک، نه با خواندن کد):** `matchStore: "firestore"` که همه‌جا — از جمله `DEPLOYMENT §2/§6` و `INCIDENT-RUNBOOK` — به‌عنوان «durable است» خوانده می‌شد، فقط یعنی «کلاینت ساخته شد». کلاینت Firestore در سازنده I/O ندارد؛ با endpoint مرده هم همان مقدار را برمی‌گرداند (اندازه‌گیری ۲۰۲۶-۱۰-۲۳: `matchStore: firestore`، سپس ۶۰ ثانیه hang در اولین خواندن، چون `get(timeout=3)` مهلت واقعی نیست — retry policy از آن طولانی‌تر است). سه چیز اضافه شد: شمارندهٔ نوشتن/شکست، `store.writable` سه‌حالته (`null` = هرگز آزمایش نشده، نه «سالم»)، و `?deep=1` با مهلت wall-clock در thread. مستندسازی هر سه سند اصلاح شد.

- **H-18…H-21 (همان جلسه، با اجرای واقعی):** (۱۸) حالت memory فقط در استور رعایت می‌شد و سه ماژول کلاینت خودشان را می‌ساختند — نتیجه: ۶۰ ثانیه هنگ در گیت زنده و گزارش «تست خراب است». (۱۹) چهار نقطه مسیر مطلق sandbox داشتند، پس سه گیت روی ماشین تو FileNotFoundError می‌دادند. (۲۰) و (۲۱) دو هارنس به `/api/queue` بدون `rttMs` می‌فرستادند: chaos آن را «pairing failed» می‌خواند و locust آن را **موفقیت** — یعنی ردیف queue در گزارش بار، یک خطای اعتبارسنجی را زمان‌بندی می‌کرد.
