#!/bin/sh
# Ubuntu 22.04/24.04 — loyiha /opt/maktabhisobot da bo'lishi kerak.
# Root bilan: sudo sh /opt/maktabhisobot/server/deploy/ornatish.sh
set -e
ROOT=/opt/maktabhisobot
SRV="$ROOT/server"
if [ ! -f "$SRV/app.py" ]; then
  echo "Avval loyihani $ROOT ga qo'ying."
  exit 1
fi
apt-get update
DEBIAN_FRONTEND=noninteractive apt-get install -y python3 python3-venv python3-pip nginx certbot python3-certbot-nginx ufw
id maktab >/dev/null 2>&1 || useradd --system --home "$ROOT" --shell /usr/sbin/nologin maktab
python3 -m venv "$SRV/.venv"
"$SRV/.venv/bin/pip" install -U pip
"$SRV/.venv/bin/pip" install -r "$SRV/requirements.txt"
install -m 644 "$SRV/deploy/maktab-hisobot.service" /etc/systemd/system/maktab-hisobot.service
if [ ! -f /etc/nginx/sites-available/maktabhisobot ]; then
  install -m 644 "$SRV/deploy/nginx.conf.example" /etc/nginx/sites-available/maktabhisobot
  echo "Nginx da server_name ni o'z domeningizga o'zgartiring: /etc/nginx/sites-available/maktabhisobot"
fi
ln -sfn /etc/nginx/sites-available/maktabhisobot /etc/nginx/sites-enabled/maktabhisobot
rm -f /etc/nginx/sites-enabled/default
chown -R maktab:maktab "$ROOT"
chmod 700 "$SRV"
ufw allow OpenSSH
ufw allow 'Nginx Full'
ufw --force enable
systemctl daemon-reload
echo "Keyin:"
echo "  1) sudo nano /etc/nginx/sites-available/maktabhisobot   # domen"
echo "  2) sudo -u maktab $SRV/.venv/bin/python $SRV/setup_tuman.py"
echo "  3) sudo -u maktab $SRV/.venv/bin/python $SRV/setup_school.py"
echo "  4) sudo nginx -t && sudo systemctl reload nginx"
echo "  5) sudo certbot --nginx -d SIZNING_DOMEN"
echo "  6) sudo systemctl enable --now maktab-hisobot"
