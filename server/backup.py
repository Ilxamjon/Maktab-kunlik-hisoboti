"""Create a consistent SQLite backup without stopping the server."""
import os,sqlite3
from datetime import datetime,timezone,timedelta
from pathlib import Path

ROOT=Path(__file__).parent
SOURCE=Path(os.getenv('DATABASE_PATH',ROOT/'school.db'))
DEST=Path(os.getenv('BACKUP_DIR',ROOT/'backups'))
KEEP_DAYS=max(7,int(os.getenv('BACKUP_KEEP_DAYS','30')))

def main():
    if os.getenv('DATABASE_URL','').startswith(('postgres://','postgresql://')):
        print('Neon Postgres zaxirasi Neon history/restore orqali boshqariladi. SQLite backup o‘tkazib yuborildi.')
        return
    if not SOURCE.exists():raise SystemExit('Baza topilmadi: '+str(SOURCE))
    DEST.mkdir(parents=True,exist_ok=True)
    now=datetime.now(timezone(timedelta(hours=5)))
    target=DEST/('school-'+now.strftime('%Y%m%d-%H%M%S')+'.db')
    with sqlite3.connect(SOURCE) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    cutoff=now.timestamp()-KEEP_DAYS*86400
    for old in DEST.glob('school-*.db'):
        if old.stat().st_mtime<cutoff:old.unlink()
    print(target)

if __name__=='__main__':main()
