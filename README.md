# Maktab Hisobot — Android, Neon va Telegram, 0.6

## Neon + bepul API hosting

Production rejimida ma‘lumotlar Neon PostgreSQL bazasida saqlanadi. Python API alohida bepul
Render Web Service’da ishlaydi. Render vaqtincha uxlaganda ham GitHub Actions har kuni 12:05
(O‘zbekiston vaqti) `/cron/noon` endpointini uyg‘otib, har bir maktab PDFini o‘z Telegramiga yuboradi.

Kerakli maxfiy qiymatlar:

- Render `DATABASE_URL`: Neon pooled connection string (`-pooler` host).
- Render `CRON_SECRET`: kamida 32 belgili tasodifiy qiymat.
- GitHub Actions `API_URL`: Render HTTPS manzili, oxirida `/` yo‘q.
- GitHub Actions `CRON_SECRET`: Render’dagi bilan aynan bir xil.

`render.yaml` Render Blueprint uchun, `.github/workflows/noon.yml` esa 12:05 yuborish uchun tayyor.
`school.db` endi production ma‘lumotlar manbai emas; u faqat lokal sinovda ishlatiladi.

## Tavsiya etilgan ommaviy tuzilma

Bu loyiha uchun **bitta markaziy, doimo ishlaydigan server kerak**. Google Drive server emas;
u Android ilovalarining login, davomat, PDF yaratish va Telegram yuborish so‘rovlarini bajara
olmaydi. Drive faqat shifrlangan zaxira nusxalarini saqlash uchun ishlatilishi mumkin.

Tizimdagi ajratish quyidagicha ishlaydi:

- `XOJ` — Xo‘jayli tumani xodimi; tumandagi maktablar holatini ko‘radi.
- `XOJ-18` — 18-maktab; uning direktor o‘rinbosari va sinf rahbarlari faqat shu maktab ma‘lumotlarini ko‘radi.
- Har maktab alohida Telegram chatiga ulanadi. `XOJ-18` hisoboti boshqa maktabga yuborilmaydi.
- O‘quvchi F.I.Sh. va manzillari tuman xodimiga ochilmaydi.

Production ma‘lumotlari Neon PostgreSQL’da doimiy saqlanadi. Shu sabab Render Free web-servisi
qayta ishga tushsa ham maktablar, o‘quvchilar va hisobotlar yo‘qolmaydi. SQLite faqat kompyuterdagi
lokal sinov uchun qoldirilgan.

Ilova sinf rahbarlarining kunlik davomatini yig'adi. **Bitta markaziy server** barcha tumanlar va maktablar uchun. Masalan Xo‘jayli tumanida 42 ta maktab bo‘lsa, ularning har biri o‘z kodi bilan kiradi; hisobotlar aralashmaydi. Har kuni soat **12:00** (O‘zbekiston vaqti) server har bir maktabning jo‘natilgan hisobotlarini jamlab, o‘sha maktab direktor o‘rinbosari Telegramiga **3 varaqli PDF** yuboradi.

Tuman kodi maktab kodidan farq qilsin: tuman `XOJ`, maktab `XOJ-09`. Boshqa tuman `NUK`, maktablari `NUK-01`. Kodlar butun tizimda yagona.

## Kim qanday kiradi

| Kim | Ilovadagi kod | Ko‘radi |
|---|---|---|
| Tuman xodimi | `XOJ` | Shu tumandagi maktablar, jo‘natish holati. Maktab qo‘shadi, direktor o‘rinbosari hisobini beradi. O‘quvchi ro‘yxati ochilmaydi. |
| Direktor o‘rinbosari | `XOJ-09` | Faqat o‘z maktabi: o‘qituvchilar, sinflar, jamlanma, PDF, Telegram. |
| Sinf rahbari | `XOJ-09` | Faqat o‘z sinfi. |

Har maktabning Telegrami alohida. 42 maktab — 42 chat. Birining PDFi ikkinchisiga tushmaydi.

Haqiqiy ishlatishda telefonlar turli Wi‑Fi da bo‘ladi. Shuning uchun server bitta HTTPS manzilda turishi kerak; har maktabga alohida LAN server qo‘yilmaydi.

## Birinchi ishga tushirish — Windows 11

1. ZIP ustiga o'ng tugma → **Извлечь всё…**. Masalan, `C:\MaktabHisobot` papkasiga chiqaring. CMD fayllarini ZIP ichidan ochmang.
2. Python 3.11 yoki yangiroq versiya kerak. `1_ORNATISH.cmd`ni oching. Avval **tuman** (masalan `XOJ`, Xo‘jayli tumani), keyin **birinchi maktab** (`XOJ-09`) kiritiladi. Qolgan maktablarni tuman xodimi ilovadan qo‘shadi yoki `server\setup_school.py` ni qayta ishlatadi.
3. `2_SERVERNI_BOSHLASH.cmd`ni oching. Server oynasi ishlash davomida ochiq tursin — 12:00 dagi avtomatik yuborish shu jarayonga bog'liq.
4. Sinov uchun: kompyuterda `ipconfig` orqali IPv4 ni aniqlang. Telefon va server bitta ishonchli Wi‑Fi da bo‘lsin. Androidga **MaktabHisobot.apk** ni o‘rnating, manzil masalan `http://192.168.1.10:8080`.
5. Doimiy ish: pastdagi **VPS va HTTPS**. Barcha telefonlar bitta manzilni yozadi, masalan `https://hisobot.example.uz`. Release APK faqat HTTPSni qabul qiladi.
6. Tuman xodimi kirib qolgan maktablarni qo‘shadi. Har maktab direktor o‘rinbosari **O‘qituvchilar va sinflar** da o‘qituvchi va sinf yaratadi.
7. Sinf rahbari o'z hisobidan kirib, o'quvchilarning F.I.Sh., jinsi va **yashash manzili**ni kiritadi. So'ng har kuni davomatni yuboradi.

Mahalliy HTTP faqat debug/sinov APKda va xususiy IP manzillar uchun ruxsat etilgan. Kompyuterning 8080-portini internetga to'g'ridan-to'g'ri ochmang.

## Doimiy server — VPS va HTTPS

Kompyuterni 24 soat yoqib qo‘ymaslik uchun kichik virtual server (VPS) olinadi. Firebase emas: shu Python dastur o‘sha mashinada ishlaydi, oldida nginx HTTPS beradi. Telefonlar `https://sizning-domen.uz` ga ulanadi.

### Nima kerak

1. **Domen** — masalan `hisobot-xojayli.uz`. A yozuvi VPS ning IP manziliga qarasin.
2. **VPS** — Ubuntu 22.04 yoki 24.04, 1 vCPU, 1–2 GB RAM, 20 GB disk yetadi. Timeweb, Beget, Hetzner yoki boshqa ijarachi.
3. SSH orqali kirish (Windows da PuTTY yoki `ssh root@IP`).

8080-port internetga ochilmaydi. Tashqaridan faqat 22 (SSH), 80 va 443 ochiq.

### Loyihani serverga qo‘yish

Windows dagi `.venv`, `school.db` va `config.json` ni yubormang (bo‘sh serverda tuman/maktab qayta yaratiladi). Agar Windows da allaqachon maktablar kiritilgan bo‘lsa, faqat `school.db` va `config.json` ni keyin alohida, xavfsiz nusxa qilib olib o‘ting.

```bash
sudo mkdir -p /opt/maktabhisobot
sudo apt-get update
sudo apt-get install -y git
sudo git clone SIZNING_GITHUB_MANZILINGIZ /opt/maktabhisobot
# yoki ZIP ni scp bilan yuklab, /opt/maktabhisobot ga oching
```

### O‘rnatish

```bash
sudo sh /opt/maktabhisobot/server/deploy/ornatish.sh
sudo nano /etc/nginx/sites-available/maktabhisobot
```

`hisobot.example.uz` o‘rniga o‘z domeningizni yozing.

```bash
sudo -u maktab /opt/maktabhisobot/server/.venv/bin/python /opt/maktabhisobot/server/setup_tuman.py
sudo -u maktab /opt/maktabhisobot/server/.venv/bin/python /opt/maktabhisobot/server/setup_school.py
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d SIZNING_DOMEN
sudo systemctl enable --now maktab-hisobot
curl https://SIZNING_DOMEN/health
```

Javobda `"version": "0.6"` va `"database": "postgres"` ko‘rinsa, Neon ulanishi ishlayapti.

Telegram: har maktab uchun serverda

```bash
sudo -u maktab /opt/maktabhisobot/server/.venv/bin/python /opt/maktabhisobot/server/connect_telegram.py
sudo systemctl restart maktab-hisobot
```

Soat 12:00 dastur ichida O‘zbekiston vaqti (UTC+5) bilan hisoblanadi. VPS qayerda tursa ham kunlik PDF shu vaqtda chiqadi.

### Zaxira

Neon production bazasi uchun Neon history/restore ishlatiladi. Quyidagi SQLite timer faqat
VPS yoki lokal SQLite rejimida kerak:

O‘rnatish skripti har kuni soat 01:30 da xavfsiz SQLite backup yaratadigan systemd timer ham
o‘rnatadi. Uni yoqish va tekshirish:

```bash
sudo systemctl enable --now maktab-hisobot-backup.timer
sudo systemctl list-timers maktab-hisobot-backup.timer
sudo systemctl start maktab-hisobot-backup.service
ls -l /opt/maktabhisobot/backup
```

Oxirgi 30 kunlik nusxalar saqlanadi. Backup papkasini serverdan tashqaridagi yopiq joyga ham
nusxalash kerak. `school.db`, backup va `config.json` ni GitHubga qo‘ymang.

Namunalar: `server/deploy/nginx.conf.example`, `server/deploy/maktab-hisobot.service`.

## Telegramni ulash

Har maktab uchun alohida ulanadi (`3_TELEGRAMNI_ULASH.cmd` — maktab kodini so‘raydi).

1. Rasmiy **@BotFather** orqali `/newbot` bilan bot yarating. Bitta botni bir nechta maktab uchun ishlatish mumkin, lekin chat har maktabda alohida.
2. `3_TELEGRAMNI_ULASH.cmd`ni oching. Bot tokenini yashirin so'rovga kiriting, maktab kodini tanlang.
3. Dastur bir martalik havola beradi. Shu maktab direktor o'rinbosari havolani **o'z akkauntidan** ochib Start bosadi.
4. Dastur topgan akkauntning ismi va IDsi ko'rsatiladi. To'g'ri odamligini tekshirib `HA` bilan tasdiqlang.
5. Serverni yoping va `2_SERVERNI_BOSHLASH.cmd` bilan qayta oching.

Token maktab yozuviga va `server/config.json`ga saqlanadi; APK ichiga kiritilmaydi. Bu fayl va `school.db`ni boshqalarga yubormang.

- Har kuni soat **12:00** (UTC+5) server **har bir** maktabning kunlik PDF ini alohida navbatga qo‘yadi: 1) jamlanma, 2) kelmaganlar, 3) hisobot jo‘natmagan sinf rahbarlari.
- Taqvimda dam olish kuni belgilangan bo‘lsa o‘sha maktab uchun 12:00 da yuborilmaydi.
- Direktor **PDFni direktor Telegramiga yuborish** tugmasi orqali qo‘lda ham yuborishi mumkin.
- Telegram ulanishi yo‘q bo‘lsa navbat bazada qoladi.

## Ilovadagi imkoniyatlar

**Tuman xodimi:** o‘z tumanidagi maktablar, kunlik jo‘natish soni, yangi maktab, direktor o‘rinbosari hisobi. Boshqa tuman va o‘quvchi ismlari ko‘rinmaydi.

**Sinf rahbari:** o'z sinflari, o'quvchi qo'shish/tahrirlash/arxivlash, davomat, 17 sababdan birini tanlash, izoh, tasdiqlash va yuborish. Parolni almashtirish.

**Direktor o'rinbosari:** barcha sinflar, o'qituvchi hisobi va sinf yaratish, o'qituvchi parolini tiklash, maktab/rahbar/ijrochi ma'lumotlari, kunlik va oylik natija, dars kunlari taqvimi, hisobotni qulflash/qayta ochish, PDF saqlash, Telegramga yuborish.

Qoralama saqlash tugmasi va ekran yopilganda avtomatik saqlash bor. Qoralama Android Keystore bilan shifrlanadi. Parol va sessiya tokeni doimiy saqlanmaydi.

O'qituvchi boshqa sinfga kira olmaydi. Bir maktab 7-A sini boshqa maktab 7-A si bilan aralashtirmaydi.

## Excel shakliga mos hisobot

`Hisobot-namuna.pdf` — faqat sun'iy ma'lumot bilan tuzilgan, ikki betlik namuna.

1. **Umumiy jadval:** t/r, maktab raqami, jami o‘quvchilar soni, davomat (%), kelmaganlar, sababli va 5 toifa, sababsiz va 12 toifa. Excel namunasidagi «Shundan» guruhlari saqlanadi. A4 albom.
2. **Batafsil ro‘yxat:** t/r, F.I.Sh., sana, sinf, **yashash manzili**, sabab, o‘g‘il, qiz, jami. Maktab nomi sarlavhada.
3. **Jo‘natmaganlar:** sinf, sinf rahbari F.I.Sh. va login.

Jins familiyadan taxmin qilinmaydi — o'quvchi kartasidan olinadi. Ism, manzil va jins hisobot yuborilgan paytdagi nusxada saqlanadi.

### Kunlik va oylik hisob

Kunlik foiz = kelganlar / hisobot topshirgan sinflardagi jami o'quvchilar × 100.
Topshirmagan sinflar bo‘lsa PDF **QISMAN HISOBOT** deb belgilanadi.

Oylik foiz = kelgan o'quvchi-kunlar / topshirilgan jami o'quvchi-kunlar × 100.

**Oylik hisobot va taqvim** bo'limida faqat dars bo'ladigan kunlarni belgilang.

## Server va manba kodi

- `android/` — native Java loyiha.
- `server/` — productionda Neon PostgreSQL, lokal sinovda SQLite; PDF, Telegram navbati va Waitress WSGI.
- APK uchun Android 8.0 (API 26) yoki yangiroq telefon kerak.
- Build: JDK 17, Gradle 8.9, Android SDK 35, Build Tools 35.0.0, AGP 8.7.3.

```powershell
cd android
.\gradlew.bat assembleDebug
```

```powershell
cd server
py -m unittest -v
```

Testlarni toza muhitda ishga tushirish uchun test dependency faylidan foydalaning:

```powershell
cd server
py -m pip install -r requirements-dev.txt
py -m unittest -v
```

GitHub Actions har bir push va Pull Requestda server testlarini hamda Android debug APK build’ini avtomatik tekshiradi.

## Zaxira

Serverni to'xtating. `server/school.db` va `server/config.json` nusxasini faqat administrator kiradigan xavfsiz joyga saqlang. Avvalgi baza birinchi ishga tushishda tuman qatlamiga yangilanadi; yangilashdan oldin zaxira oling.

## Keyingi bosqichlar

Haqiqiy telefonlar va Telegram sinovi, alohida kompyuter veb-paneli, Excel importi, to'liq oflayn rejim.

Texnik manbalar:
https://docs.pylonsproject.org/projects/waitress/en/stable/usage.html
https://developer.android.com/build/releases/agp-8-7-0-release-notes
https://core.telegram.org/bots/api#senddocument
