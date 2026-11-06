# Maktab Hisobot — Telegram bot

Mobil ilova yo‘q. Sinf rahbari va direktor o‘rinbosari faqat Telegram bot orqali ishlaydi.

## Kim nima qiladi

Direktor o‘rinbosari botni ochib, ism, familiya va maktab nomini yozadi. Bot 6 xonali kod beradi.

Sinf rahbari shu kodni yozadi, ism, familiya va sinfini kiritadi (masalan `7B`). Keyin o‘z sinfining o‘quvchilar ro‘yxatini tuzadi.

Har kuni botda davomat yuboradi. Kelmagan o‘quvchining sababi tanlanadi. Jo‘natilgan davomat shu maktab bo‘yicha jamlanib, faqat o‘sha direktor o‘rinbosariga PDF bo‘lib boradi. Boshqa maktabga tushmaydi.

## Ishga tushirish

1. @BotFather da `/newbot` bilan bot yarating.
2. Render’dagi `maktab-hisobot-api` servisiga `TELEGRAM_BOT_TOKEN` qo‘ying.
3. `TELEGRAM_SET_WEBHOOK` qiymati `1` bo‘lsin. `PUBLIC_URL` esa `https://maktab-hisobot-api.onrender.com`.
4. Kod yangilangach, direktor o‘rinbosari botda `/start` bosadi.

Ma’lumotlar Neon PostgreSQL’da saqlanadi. `DATABASE_URL` va `CRON_SECRET` Render’da qoladi. `.env`, `school.db` va bot tokenini GitHubga qo‘ymang.

## Tekshirish

```powershell
cd server
py -m pip install -r requirements-dev.txt
py -m unittest -v
```
