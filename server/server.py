"""School-scoped attendance API. Serve behind HTTPS for device access."""
from contextlib import contextmanager
import os, json, sqlite3, hashlib, secrets, hmac, time, threading, argparse, getpass, re, logging
import database
from datetime import date, datetime, timedelta, timezone
from catalog import REASONS, COLUMN_ORDER
from pathlib import Path
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlsplit, parse_qs
from urllib.request import Request, urlopen
ROOT=Path(__file__).parent
LOG=logging.getLogger('maktab-hisobot.worker')
DB=os.getenv('DATABASE_PATH', str(ROOT/'school.db'))
TZ=timezone(timedelta(hours=5))
def now_uz():
    return datetime.now(TZ)
def today():
    return now_uz().date()
class ApiError(Exception):
    def __init__(self, message, status=400): self.message,self.status=message,status

@contextmanager
def connect():
    if database.is_postgres():c=database.postgres_connect()
    else:
        c=sqlite3.connect(DB, timeout=30); c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON');c.execute('PRAGMA journal_mode=WAL');c.execute('PRAGMA busy_timeout=8000')
    try:
        with c:yield c
    finally:c.close()

def _table_exists(c,name):
    return c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",(name,)).fetchone() is not None
def _columns(c,table):
    return {r['name'] for r in c.execute('PRAGMA table_info('+table+')')}

def migrate_v2(c):
    version=c.execute('PRAGMA user_version').fetchone()[0]
    if version>=2:return
    for table in ('reports','audit'):
        if not _table_exists(c,table):continue
        for row in c.execute('SELECT rowid AS rid,payload FROM '+table).fetchall():
            entries=json.loads(row['payload'])
            for e in entries:
                if e.get('status')==3:
                    e['status']=5
                    e['note']=('Oldingi yozuv: Ruxsatli. '+e.get('note',''))[:300]
            c.execute('UPDATE '+table+' SET payload=? WHERE rowid=?',(json.dumps(entries,ensure_ascii=False),row['rid']))
    if 'active' not in _columns(c,'students'):c.execute('ALTER TABLE students ADD COLUMN active INTEGER NOT NULL DEFAULT 1')
    if 'locked' not in _columns(c,'reports'):c.execute('ALTER TABLE reports ADD COLUMN locked INTEGER NOT NULL DEFAULT 0')
    if _table_exists(c,'outbox') and 'claimed' not in _columns(c,'outbox'):c.execute('ALTER TABLE outbox ADD COLUMN claimed REAL DEFAULT 0')
    c.execute('CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS calendar(day TEXT PRIMARY KEY,teaching INTEGER NOT NULL)')
    c.execute('CREATE TABLE IF NOT EXISTS changes(id INTEGER PRIMARY KEY,user_id INTEGER,action TEXT,created REAL)')
    if _table_exists(c,'outbox'):c.execute("UPDATE outbox SET state='superseded' WHERE state='pending'")
    c.execute('PRAGMA user_version=2')

def migrate_v3(c):
    version=c.execute('PRAGMA user_version').fetchone()[0]
    if version>=3:return
    c.execute('PRAGMA foreign_keys=OFF')
    c.executescript('''
        CREATE TABLE IF NOT EXISTS schools(
            id INTEGER PRIMARY KEY,
            code TEXT NOT NULL UNIQUE,
            name TEXT NOT NULL DEFAULT '',
            director TEXT NOT NULL DEFAULT '',
            executor TEXT NOT NULL DEFAULT '',
            telegram_bot_token TEXT NOT NULL DEFAULT '',
            telegram_chat_id TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS digests(
            school_id INTEGER NOT NULL,
            day TEXT NOT NULL,
            kind TEXT NOT NULL,
            created REAL NOT NULL,
            PRIMARY KEY(school_id,day,kind)
        );
    ''')
    settings={}
    if _table_exists(c,'settings'):
        settings={r['key']:r['value'] for r in c.execute('SELECT * FROM settings')}
    if not c.execute('SELECT 1 FROM schools').fetchone():
        c.execute('INSERT INTO schools(code,name,director,executor,telegram_bot_token,telegram_chat_id) VALUES(?,?,?,?,?,?)',(
            (os.getenv('SCHOOL_CODE') or 'MAKTAB').upper(),
            settings.get('name') or os.getenv('SCHOOL_NAME') or 'Maktab',
            settings.get('director') or os.getenv('DIRECTOR_NAME') or '',
            settings.get('executor') or os.getenv('EXECUTOR_NAME') or '',
            os.getenv('TELEGRAM_BOT_TOKEN') or '',
            os.getenv('TELEGRAM_CHAT_ID') or ''))
    sid=c.execute('SELECT id FROM schools ORDER BY id').fetchone()[0]
    if 'school_id' not in _columns(c,'users'):
        c.executescript('''
            CREATE TABLE users_v3(
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL REFERENCES schools(id),
                login TEXT NOT NULL,
                password TEXT,
                role TEXT CHECK(role IN ('admin','teacher')),
                name TEXT NOT NULL DEFAULT '',
                UNIQUE(school_id,login));
            INSERT INTO users_v3(id,school_id,login,password,role,name)
                SELECT id, %d, login, password, role, login FROM users;
            DROP TABLE users;
            ALTER TABLE users_v3 RENAME TO users;
        '''%sid)
    if 'school_id' not in _columns(c,'classes'):
        c.executescript('''
            CREATE TABLE classes_v3(
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL REFERENCES schools(id),
                name TEXT NOT NULL,
                teacher INTEGER REFERENCES users(id),
                UNIQUE(school_id,name));
            INSERT INTO classes_v3(id,school_id,name,teacher)
                SELECT id, %d, name, teacher FROM classes;
            DROP TABLE classes;
            ALTER TABLE classes_v3 RENAME TO classes;
        '''%sid)
    if _table_exists(c,'calendar') and 'school_id' not in _columns(c,'calendar'):
        c.executescript('''
            CREATE TABLE calendar_v3(
                school_id INTEGER NOT NULL REFERENCES schools(id),
                day TEXT NOT NULL,
                teaching INTEGER NOT NULL,
                PRIMARY KEY(school_id,day));
            INSERT INTO calendar_v3(school_id,day,teaching)
                SELECT %d, day, teaching FROM calendar;
            DROP TABLE calendar;
            ALTER TABLE calendar_v3 RENAME TO calendar;
        '''%sid)
    if _table_exists(c,'reports') and 'school_id' not in _columns(c,'reports'):
        c.executescript('''
            CREATE TABLE reports_v3(
                school_id INTEGER NOT NULL REFERENCES schools(id),
                day TEXT NOT NULL,
                class_id INTEGER NOT NULL REFERENCES classes(id),
                revision INTEGER,
                payload TEXT,
                updated REAL,
                locked INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY(day,class_id));
            INSERT INTO reports_v3(school_id,day,class_id,revision,payload,updated,locked)
                SELECT %d, day, class_id, revision, payload, updated, locked FROM reports;
            DROP TABLE reports;
            ALTER TABLE reports_v3 RENAME TO reports;
        '''%sid)
    if _table_exists(c,'outbox') and 'school_id' not in _columns(c,'outbox'):
        c.executescript('''
            CREATE TABLE outbox_v3(
                id INTEGER PRIMARY KEY,
                school_id INTEGER NOT NULL REFERENCES schools(id),
                day TEXT,
                kind TEXT NOT NULL DEFAULT 'manual',
                fingerprint TEXT NOT NULL,
                pdf BLOB,
                state TEXT DEFAULT 'pending',
                attempts INTEGER DEFAULT 0,
                next_try REAL DEFAULT 0,
                claimed REAL DEFAULT 0,
                UNIQUE(school_id,fingerprint));
            INSERT INTO outbox_v3(id,school_id,day,kind,fingerprint,pdf,state,attempts,next_try,claimed)
                SELECT id, %d, day, 'manual', fingerprint, pdf, state, attempts, next_try, claimed FROM outbox;
            DROP TABLE outbox;
            ALTER TABLE outbox_v3 RENAME TO outbox;
        '''%sid)
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA user_version=3')

def migrate_v4(c):
    version=c.execute('PRAGMA user_version').fetchone()[0]
    if version>=4:return
    c.execute('PRAGMA foreign_keys=OFF')
    c.execute('''CREATE TABLE IF NOT EXISTS districts(
        id INTEGER PRIMARY KEY, code TEXT NOT NULL UNIQUE, name TEXT NOT NULL)''')
    if not c.execute('SELECT 1 FROM districts').fetchone():
        c.execute('INSERT INTO districts(code,name) VALUES(?,?)',((os.getenv('DISTRICT_CODE') or 'TUMAN').upper(), os.getenv('DISTRICT_NAME') or 'Tuman'))
    did=c.execute('SELECT id FROM districts ORDER BY id').fetchone()[0]
    if 'district_id' not in _columns(c,'schools'):
        c.execute('ALTER TABLE schools ADD COLUMN district_id INTEGER')
        c.execute('UPDATE schools SET district_id=?',(did,))
    if 'district_id' not in _columns(c,'users'):
        c.executescript('''
            CREATE TABLE users_v4(
                id INTEGER PRIMARY KEY,
                district_id INTEGER NOT NULL,
                school_id INTEGER,
                login TEXT NOT NULL,
                password TEXT,
                role TEXT CHECK(role IN ('district','admin','teacher')),
                name TEXT NOT NULL DEFAULT '');
            INSERT INTO users_v4(id,district_id,school_id,login,password,role,name)
                SELECT u.id, s.district_id, u.school_id, u.login, u.password, u.role, u.name
                FROM users u JOIN schools s ON s.id=u.school_id;
            DROP TABLE users;
            ALTER TABLE users_v4 RENAME TO users;
            CREATE UNIQUE INDEX IF NOT EXISTS users_school_login ON users(school_id, login) WHERE school_id IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS users_district_login ON users(district_id, login) WHERE school_id IS NULL;
        ''')
    c.execute('CREATE INDEX IF NOT EXISTS reports_school_day ON reports(school_id,day)')
    c.execute('CREATE INDEX IF NOT EXISTS classes_school ON classes(school_id)')
    c.execute('CREATE INDEX IF NOT EXISTS schools_district ON schools(district_id)')
    c.execute('PRAGMA foreign_keys=ON')
    c.execute('PRAGMA user_version=4')

def init():
    if database.is_postgres():
        schema=(ROOT/'schema_postgres.sql').read_text(encoding='utf-8')
        with connect() as c:
            for statement in schema.split(';'):
                if statement.strip():c.execute(statement)
            if not c.execute('SELECT 1 FROM districts LIMIT 1').fetchone():
                c.execute('INSERT INTO districts(code,name) VALUES(?,?)',((os.getenv('DISTRICT_CODE') or 'TUMAN').upper(),os.getenv('DISTRICT_NAME') or 'Tuman'))
            if not c.execute('SELECT 1 FROM schools LIMIT 1').fetchone():
                did=c.execute('SELECT id FROM districts ORDER BY id LIMIT 1').fetchone()[0]
                c.execute('INSERT INTO schools(district_id,code,name) VALUES(?,?,?)',(did,(os.getenv('SCHOOL_CODE') or 'MAKTAB').upper(),os.getenv('SCHOOL_NAME') or 'Maktab'))
        return
    with connect() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, login TEXT UNIQUE, password TEXT, role TEXT CHECK(role IN ('admin','teacher')));
        CREATE TABLE IF NOT EXISTS classes(id INTEGER PRIMARY KEY,name TEXT UNIQUE,teacher INTEGER REFERENCES users(id));
        CREATE TABLE IF NOT EXISTS students(id INTEGER PRIMARY KEY,class_id INTEGER REFERENCES classes(id),name TEXT,gender TEXT,address TEXT);
        CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY,user_id INTEGER REFERENCES users(id),expires REAL);
        CREATE TABLE IF NOT EXISTS reports(day TEXT,class_id INTEGER REFERENCES classes(id),revision INTEGER,payload TEXT,updated REAL,PRIMARY KEY(day,class_id));
        CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY,day TEXT,class_id INTEGER,user_id INTEGER,payload TEXT,created REAL);
        CREATE TABLE IF NOT EXISTS outbox(id INTEGER PRIMARY KEY,day TEXT,fingerprint TEXT UNIQUE,pdf BLOB,state TEXT DEFAULT 'pending',attempts INTEGER DEFAULT 0,next_try REAL DEFAULT 0);
        ''')
        migrate_v2(c);migrate_v3(c);migrate_v4(c)

def org_code_value(raw):
    s=(raw or '').strip().upper().replace(' ','')
    if not re.fullmatch(r'[A-Z0-9]{2,12}(-[A-Z0-9]{1,8})?', s): raise ApiError('Kod noto‘g‘ri. Masalan XOJ yoki XOJ-09')
    return s
school_code_value=org_code_value

def school_row(c,school_id):
    row=c.execute('SELECT * FROM schools WHERE id=?',(school_id,)).fetchone()
    if not row: raise ApiError('Maktab topilmadi',404)
    return dict(row)

def school_settings(c,school_id):
    row=school_row(c,school_id)
    return {'id':row['id'],'code':row['code'],'name':row['name'],'director':row['director'],'executor':row['executor']}

def telegram_for(school):
    token=school.get('telegram_bot_token') or os.getenv('TELEGRAM_BOT_TOKEN') or ''
    chat=school.get('telegram_chat_id') or os.getenv('TELEGRAM_CHAT_ID') or ''
    return token,chat

def month_value(s):
    try:
        if len(s)!=7 or date.fromisoformat(s+'-01').strftime('%Y-%m')!=s:raise ValueError()
    except (TypeError,ValueError):raise ApiError('Oy YYYY-MM formatida bo‘lsin')
    return s

def monthly_summary(c,month,school_id):
    month_value(month)
    days=[r[0] for r in c.execute('SELECT day FROM calendar WHERE school_id=? AND day LIKE ? AND teaching=1 ORDER BY day',(school_id,month+'-%'))]
    configured=c.execute('SELECT count(*) FROM calendar WHERE school_id=? AND day LIKE ?',(school_id,month+'-%')).fetchone()[0]>0
    reported=[r[0] for r in c.execute('SELECT DISTINCT day FROM reports WHERE school_id=? AND day LIKE ? ORDER BY day',(school_id,month+'-%'))]
    all_days=sorted(set(days+reported)); result=[]
    for day in all_days:result.extend(summary(c,day,school_id))
    return {'rows':result,'month':month,'calendar_configured':configured,'teaching_days':days,'report_dates':reported}

def password_hash(p, salt=None):
    salt=salt or secrets.token_hex(16)
    return salt+':'+hashlib.pbkdf2_hmac('sha256',p.encode(),salt.encode(),250000).hex()

def text_value(data,key,maxlen=150):
    s=data.get(key,'')
    if not isinstance(s,str) or not s.strip() or len(s)>maxlen: raise ApiError(key+': qiymatni tekshiring')
    return s.strip()

def day_value(s):
    try:
        if date.fromisoformat(s).isoformat()!=s: raise ValueError()
    except (ValueError,TypeError): raise ApiError('Sana YYYY-MM-DD formatida bo‘lsin')
    return s

def authenticate(c,token):
    u=c.execute('SELECT u.* FROM users u JOIN sessions s ON u.id=s.user_id WHERE s.token=? AND s.expires>?',(hashlib.sha256(token.encode()).hexdigest(),time.time())).fetchone()
    if not u: raise ApiError('Qayta kiring',401)
    return dict(u)

def authorize_class(c,u,cid):
    row=c.execute('SELECT * FROM classes WHERE id=? AND school_id=?',(cid,u['school_id'])).fetchone()
    if not row or (u['role']!='admin' and row['teacher']!=u['id']): raise ApiError('Ruxsat yo‘q',403)
    return dict(row)

def summary(c,day,school_id):
    result=[]
    for cl in c.execute('SELECT cl.*,u.login AS teacher_login,u.name AS teacher_name FROM classes cl LEFT JOIN users u ON u.id=cl.teacher WHERE cl.school_id=? ORDER BY cl.name',(school_id,)):
        r=c.execute('SELECT * FROM reports WHERE school_id=? AND day=? AND class_id=?',(school_id,day,cl['id'])).fetchone()
        entries=json.loads(r['payload']) if r else []
        result.append({'id':cl['id'],'class':cl['name'],'submitted':bool(r),'revision':r['revision'] if r else 0,'entries':entries,'total':len(entries) if r else c.execute('SELECT count(*) FROM students WHERE class_id=? AND active=1',(cl['id'],)).fetchone()[0],'day':day,'locked':bool(r['locked']) if r else False,'counts':[sum(e['status']==n for e in entries) for n in range(len(REASONS))],'teacher_login':cl['teacher_login'] or '','teacher_name':cl['teacher_name'] or cl['teacher_login'] or ''})
    return result

from reports import make_pdf

def enqueue(c,day,require_complete,school_id,kind='manual'):
    rows=summary(c,day,school_id)
    if not rows or (require_complete and any(not r['submitted'] for r in rows)): return
    info=school_settings(c,school_id)
    key=hashlib.sha256(json.dumps([kind,school_id,day,rows,info],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    c.execute("UPDATE outbox SET state='superseded' WHERE school_id=? AND day=? AND kind=? AND state='pending' AND fingerprint<>?",(school_id,day,kind,key))
    c.execute('INSERT OR IGNORE INTO outbox(school_id,day,kind,fingerprint,pdf) VALUES(?,?,?,?,?)',(school_id,day,kind,key,make_pdf(rows,day,info)))

def code_taken(c,code,ignore_school=None,ignore_district=None):
    school=c.execute('SELECT id FROM schools WHERE code=?',(code,)).fetchone()
    district=c.execute('SELECT id FROM districts WHERE code=?',(code,)).fetchone()
    if school and school['id']!=ignore_school:return True
    if district and district['id']!=ignore_district:return True
    return False

def find_login_target(c,data):
    raw=(data.get('school') or '').strip()
    if raw:
        code=org_code_value(raw)
        school=c.execute('SELECT * FROM schools WHERE code=?',(code,)).fetchone()
        if school:return 'school',dict(school)
        district=c.execute('SELECT * FROM districts WHERE code=?',(code,)).fetchone()
        if district:return 'district',dict(district)
        raise ApiError('Maktab yoki tuman kodi topilmadi',401)
    schools=list(c.execute('SELECT * FROM schools ORDER BY id'))
    if len(schools)==1:return 'school',dict(schools[0])
    raise ApiError('Maktab yoki tuman kodini kiriting',401)

def find_school_for_login(c,data):
    kind,org=find_login_target(c,data)
    if kind!='school':raise ApiError('Maktab kodini kiriting',401)
    return org

def district_status(c,district_id,day):
    day=day_value(day);rows=[]
    for school in c.execute('SELECT * FROM schools WHERE district_id=? ORDER BY code',(district_id,)):
        total=c.execute('SELECT count(*) FROM classes WHERE school_id=?',(school['id'],)).fetchone()[0]
        submitted=c.execute('SELECT count(*) FROM reports WHERE school_id=? AND day=?',(school['id'],day)).fetchone()[0]
        admin=c.execute("SELECT name,login FROM users WHERE school_id=? AND role='admin'",(school['id'],)).fetchone()
        token,chat=telegram_for(dict(school))
        rows.append({'id':school['id'],'code':school['code'],'name':school['name'],'classes':total,'submitted':submitted,'admin':dict(admin) if admin else None,'telegram_configured':bool(token and chat)})
    district=c.execute('SELECT code,name FROM districts WHERE id=?',(district_id,)).fetchone()
    return {'role':'district','kind':'district','district':dict(district),'schools':rows,'today':day,'day':day,'classes':[],'reasons':REASONS,'school':{'code':district['code'],'name':district['name']}}

def dispatch_district(c,u,method,route,query,data,token=''):
    did=u['district_id']
    if route=='/password' and method=='POST':
        current=text_value(data,'current',256);new=text_value(data,'password',256)
        if not hmac.compare_digest(password_hash(current,u['password'].split(':')[0]),u['password']):raise ApiError('Joriy parol xato',403)
        if len(new)<10:raise ApiError('Yangi parol kamida 10 belgi bo‘lsin')
        c.execute('UPDATE users SET password=? WHERE id=?',(password_hash(new),u['id']))
        c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],));return {'ok':True}
    if route=='/logout' and method=='POST':
        c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),))
        return {'ok':True}
    if route in ('/classes','/district/status') and method=='GET':
        day=(query.get('day') or [today().isoformat()])[0]
        return district_status(c,did,day)
    if route=='/schools' and method=='POST':
        code=org_code_value(text_value(data,'code',16));name=text_value(data,'name',150)
        director=data.get('director','') or '';executor=data.get('executor','') or ''
        if not isinstance(director,str) or not isinstance(executor,str) or len(director)>150 or len(executor)>150:raise ApiError('Ma’lumotni tekshiring')
        if code_taken(c,code):raise ApiError('Bu kod band. Tuman XOJ, maktab XOJ-09 kabi bo‘lsin',409)
        c.execute('INSERT INTO schools(district_id,code,name,director,executor) VALUES(?,?,?,?,?)',(did,code,name.strip(),director.strip(),executor.strip()))
        return district_status(c,did,today().isoformat())
    if route=='/schools/admin' and method=='POST':
        school_id=data.get('school_id')
        school=c.execute('SELECT * FROM schools WHERE id=? AND district_id=?',(school_id,did)).fetchone()
        if not school:raise ApiError('Maktab topilmadi',404)
        login=text_value(data,'login',80);pw=text_value(data,'password',256);full=text_value(data,'name',150)
        if len(pw)<10:raise ApiError('Parol kamida 10 belgidan iborat bo‘lsin')
        existing=c.execute("SELECT id FROM users WHERE school_id=? AND role='admin'",(school_id,)).fetchone()
        if existing:
            c.execute('UPDATE users SET login=?,password=?,name=? WHERE id=?',(login,password_hash(pw),full,existing['id']))
            c.execute('DELETE FROM sessions WHERE user_id=?',(existing['id'],))
        else:
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'admin',?)",(did,school_id,login,password_hash(pw),full))
        return district_status(c,did,today().isoformat())
    raise ApiError('Bu amal tuman xodimi uchun emas',403)

def dispatch(method,path,data,token=''):
    split=urlsplit(path);route=split.path;query=parse_qs(split.query)
    with connect() as c:
        if route=='/login' and method=='POST':
            kind,org=find_login_target(c,data)
            if kind=='district':
                u=c.execute('SELECT * FROM users WHERE district_id=? AND school_id IS NULL AND login=?',(org['id'],data.get('login'))).fetchone()
            else:
                u=c.execute('SELECT * FROM users WHERE school_id=? AND login=?',(org['id'],data.get('login'))).fetchone()
            pw=data.get('password','')
            if not isinstance(pw,str) or len(pw)>256: raise ApiError('Login yoki parol xato',401)
            candidate=password_hash(pw,u['password'].split(':')[0] if u else 'dummy')
            if not u or not hmac.compare_digest(candidate,u['password']): raise ApiError('Login yoki parol xato',401)
            raw=secrets.token_urlsafe(32)
            c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
            c.execute('INSERT INTO sessions VALUES(?,?,?)',(hashlib.sha256(raw.encode()).hexdigest(),u['id'],time.time()+43200))
            return {'token':raw,'role':u['role'],'kind':kind,'school':org['code'],'school_name':org['name'],'name':u['name']}
        u=authenticate(c,token);sid=u['school_id']
        if u['role']=='district':return dispatch_district(c,u,method,route,query,data,token)
        if not sid:raise ApiError('Qayta kiring',401)
        if route=='/password' and method=='POST':
            current=text_value(data,'current',256);new=text_value(data,'password',256)
            if not hmac.compare_digest(password_hash(current,u['password'].split(':')[0]),u['password']):raise ApiError('Joriy parol xato',403)
            if len(new)<10:raise ApiError('Yangi parol kamida 10 belgi bo‘lsin')
            c.execute('UPDATE users SET password=? WHERE id=? AND school_id=?',(password_hash(new),u['id'],sid))
            c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],));return {'ok':True}
        if route=='/logout' and method=='POST':
            c.execute('DELETE FROM sessions WHERE token=?',(hashlib.sha256(token.encode()).hexdigest(),));return {'ok':True}
        if route=='/classes' and method=='GET':
            sql='SELECT id,name FROM classes WHERE school_id=?';args=(sid,)
            if u['role']!='admin': sql+=' AND teacher=?';args=(sid,u['id'])
            return {'kind':'school','classes':[dict(r) for r in c.execute(sql+' ORDER BY name',args)],'reasons':REASONS,'today':today().isoformat(),'school':school_settings(c,sid),'user_id':u['id'],'name':u['name']}
        if route in ('/students/update','/students/archive') and method=='POST':
            student=c.execute('SELECT s.* FROM students s JOIN classes cl ON cl.id=s.class_id WHERE s.id=? AND cl.school_id=?',(data.get('id'),sid)).fetchone()
            if not student:raise ApiError('O‘quvchi topilmadi',404)
            authorize_class(c,u,student['class_id'])
            if route.endswith('archive'):
                c.execute('UPDATE students SET active=0 WHERE id=?',(student['id'],))
            else:
                if data.get('gender') not in ('M','F'):raise ApiError('Jinsni tanlang')
                c.execute('UPDATE students SET name=?,gender=?,address=? WHERE id=?',(text_value(data,'name'),data['gender'],text_value(data,'address',300),student['id']))
            c.execute('INSERT INTO changes(user_id,action,created) VALUES(?,?,?)',(u['id'],route+':'+str(student['id']),time.time()))
            return {'ok':True}
        if route=='/students':
            cid=data.get('class_id') if method=='POST' else query.get('class_id',[''])[0]
            authorize_class(c,u,cid)
            if method=='GET': return {'students':[dict(r) for r in c.execute('SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY name',(cid,))]}
            if method=='POST':
                gender=data.get('gender')
                if gender not in ('M','F'): raise ApiError('Jinsni tanlang')
                c.execute('INSERT INTO students(class_id,name,gender,address) VALUES(?,?,?,?)',(cid,text_value(data,'name'),gender,text_value(data,'address',300)));return {'ok':True}
        if route=='/report':
            cid=data.get('class_id') if method=='POST' else query.get('class_id',[''])[0]
            authorize_class(c,u,cid)
            day=day_value(data.get('day') if method=='POST' else query.get('day',[''])[0])
            old=c.execute('SELECT * FROM reports WHERE school_id=? AND day=? AND class_id=?',(sid,day,cid)).fetchone()
            if method=='GET':return {'locked':bool(old['locked']) if old else False,'revision':old['revision'] if old else 0,'entries':json.loads(old['payload']) if old else []}
            if method=='POST':
                if date.fromisoformat(day)>today():raise ApiError('Kelajak sana uchun hisobot berilmaydi')
                c.execute('BEGIN IMMEDIATE')
                old=c.execute('SELECT * FROM reports WHERE school_id=? AND day=? AND class_id=?',(sid,day,cid)).fetchone()
                if old and old['locked']:raise ApiError('Hisobot tasdiqlangan. Direktor qayta ochishi kerak.',409)
                cal=c.execute('SELECT teaching FROM calendar WHERE school_id=? AND day=?',(sid,day)).fetchone()
                if cal and not cal['teaching']:raise ApiError('Bu sana taqvimda dam olish kuni')
                rev=old['revision'] if old else 0
                if data.get('revision')!=rev:raise ApiError('Hisobot boshqa qurilmada yangilangan. Qayta oching.',409)
                entries=data.get('entries')
                if not isinstance(entries,list):raise ApiError('Ro‘yxat xato')
                pupils=[{k:v for k,v in e.items() if k not in ('status','note')} for e in json.loads(old['payload'])] if old else [dict(r) for r in c.execute('SELECT * FROM students WHERE class_id=? AND active=1',(cid,))]
                if not pupils:raise ApiError('Avval o‘quvchilarni kiriting')
                ids=[e.get('id') for e in entries if isinstance(e,dict)]
                if any(type(sidn)!=int for sidn in ids):raise ApiError('O‘quvchi ID noto‘g‘ri')
                if len(ids)!=len(entries) or len(set(ids))!=len(ids) or set(ids)!={p['id'] for p in pupils}:raise ApiError('Sinf ro‘yxati o‘zgargan. Qayta oching.')
                mapped={e['id']:e for e in entries};saved=[]
                for pupil in pupils:
                    e=mapped[pupil['id']];status=e.get('status');note=e.get('note','')
                    if type(status)!=int or status not in range(len(REASONS)) or not isinstance(note,str) or len(note)>300:raise ApiError('Holat yoki izoh xato')
                    saved.append({**pupil,'status':status,'note':note})
                payload=json.dumps(saved,ensure_ascii=False)
                if old and old['payload']==payload:return {'ok':True,'revision':rev}
                rev+=1
                c.execute('INSERT INTO reports(school_id,day,class_id,revision,payload,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(day,class_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated=excluded.updated',(sid,day,cid,rev,payload,time.time()))
                c.execute('INSERT INTO audit(day,class_id,user_id,payload,created) VALUES(?,?,?,?,?)',(day,cid,u['id'],payload,time.time()))
                return {'ok':True,'revision':rev}
        if u['role']!='admin':raise ApiError('Faqat direktor o‘rinbosari uchun',403)
        if route=='/settings':
            if method=='POST':
                name=text_value(data,'name',150);director=text_value(data,'director',150);executor=text_value(data,'executor',150)
                c.execute('UPDATE schools SET name=?,director=?,executor=? WHERE id=?',(name,director,executor,sid))
            info=school_settings(c,sid);token,chat=telegram_for(school_row(c,sid))
            return {'school':info,'telegram_configured':bool(token and chat)}
        if route=='/users':
            if method=='POST':
                login=text_value(data,'login',80);pw=text_value(data,'password',256);full=text_value(data,'name',150)
                if len(pw)<10:raise ApiError('Parol kamida 10 belgidan iborat bo‘lsin')
                c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'teacher',?)",(u['district_id'],sid,login,password_hash(pw),full))
            return {'users':[dict(r) for r in c.execute('SELECT id,login,role,name FROM users WHERE school_id=? ORDER BY login',(sid,))]}
        if route=='/users/reset' and method=='POST':
            pw=text_value(data,'password',256)
            if len(pw)<10:raise ApiError('Parol kamida 10 belgidan iborat bo‘lsin')
            if not c.execute("SELECT id FROM users WHERE id=? AND school_id=? AND role='teacher'",(data.get('id'),sid)).fetchone():raise ApiError('O‘qituvchi topilmadi')
            c.execute('UPDATE users SET password=? WHERE id=? AND school_id=?',(password_hash(pw),data['id'],sid))
            c.execute('DELETE FROM sessions WHERE user_id=?',(data['id'],));return {'ok':True}
        if route=='/classes/create' and method=='POST':
            name=text_value(data,'name',30);teacher=data.get('teacher_id')
            if not c.execute("SELECT id FROM users WHERE id=? AND school_id=? AND role='teacher'",(teacher,sid)).fetchone():raise ApiError('O‘qituvchini tanlang')
            c.execute('INSERT INTO classes(school_id,name,teacher) VALUES(?,?,?)',(sid,name,teacher));return {'ok':True}
        if route=='/calendar':
            month=month_value(data.get('month') if method=='POST' else query.get('month',[''])[0])
            if method=='POST':
                days=data.get('days')
                if not isinstance(days,list) or any(not isinstance(d,str) for d in days):raise ApiError('Kunlar ro‘yxati kerak')
                for d in days:
                    day_value(d)
                    if not d.startswith(month+'-'):raise ApiError('Sana tanlangan oyga tegishli emas')
                reported={r[0] for r in c.execute('SELECT DISTINCT day FROM reports WHERE school_id=? AND day LIKE ?',(sid,month+'-%'))}
                if not reported.issubset(set(days)):raise ApiError('Hisoboti mavjud kunni dam olish deb belgilab bo‘lmaydi')
                start=date.fromisoformat(month+'-01');d=start
                while d.month==start.month:
                    ds=d.isoformat();c.execute('INSERT INTO calendar(school_id,day,teaching) VALUES(?,?,?) ON CONFLICT(school_id,day) DO UPDATE SET teaching=excluded.teaching',(sid,ds,int(ds in days)));d+=timedelta(days=1)
            return {'days':[r[0] for r in c.execute('SELECT day FROM calendar WHERE school_id=? AND day LIKE ? AND teaching=1 ORDER BY day',(sid,month+'-%'))], 'configured':bool(c.execute('SELECT 1 FROM calendar WHERE school_id=? AND day LIKE ?',(sid,month+'-%')).fetchone())}
        if route in ('/monthly','/monthly/pdf','/monthly/telegram'):
            month=month_value(data.get('month') if method=='POST' else query.get('month',[''])[0]);report=monthly_summary(c,month,sid)
            if route=='/monthly':return report
            blob=make_pdf(report['rows'],month,school_settings(c,sid),monthly=True,calendar_configured=report['calendar_configured'])
            if route.endswith('/pdf'):return blob
            if method!='POST':raise ApiError('POST kerak',405)
            key=hashlib.sha256(json.dumps(['monthly',sid,month,report,school_settings(c,sid)],sort_keys=True,ensure_ascii=False).encode()).hexdigest()
            c.execute("UPDATE outbox SET state='superseded' WHERE school_id=? AND day=? AND kind='monthly' AND state='pending' AND fingerprint<>?",(sid,month,key))
            c.execute('INSERT OR IGNORE INTO outbox(school_id,day,kind,fingerprint,pdf) VALUES(?,?,?,?,?)',(sid,month,'monthly',key,blob))
            return {'ok':True,'message':'Oylik PDF navbatga qo‘yildi'}
        if route=='/report/lock' and method=='POST':
            day=day_value(data.get('day'));cid=data.get('class_id');lock=data.get('locked')
            if type(lock)!=bool:raise ApiError('Qulflash holati kerak')
            c.execute('BEGIN IMMEDIATE')
            row=c.execute('SELECT revision FROM reports WHERE school_id=? AND day=? AND class_id=?',(sid,day,cid)).fetchone()
            if not row:raise ApiError('Hisobot topilmadi',404)
            if data.get('revision')!=row['revision']:raise ApiError('Hisobot o‘zgargan, qayta oching',409)
            c.execute('UPDATE reports SET locked=?,revision=revision+1 WHERE school_id=? AND day=? AND class_id=?',(int(lock),sid,day,cid))
            c.execute('INSERT INTO changes(user_id,action,created) VALUES(?,?,?)',(u['id'],'lock:'+day+':'+str(cid)+':'+str(lock),time.time()))
            return {'ok':True}
        day=day_value(data.get('day') if method=='POST' else query.get('day',[''])[0])
        if route=='/summary' and method=='GET':
            token,chat=telegram_for(school_row(c,sid))
            return {'telegram_configured':bool(token and chat),'rows':summary(c,day,sid),'telegram':[dict(r) for r in c.execute('SELECT id,state,attempts,kind FROM outbox WHERE school_id=? AND day=? ORDER BY id DESC',(sid,day))]}
        if route=='/pdf' and method=='GET':return make_pdf(summary(c,day,sid),day,school_settings(c,sid))
        if route=='/telegram' and method=='POST':
            enqueue(c,day,False,sid,'manual');return {'ok':True,'message':'Navbatga qo‘yildi. Yetkazilish holatini tekshiring.'}
        raise ApiError('Manzil topilmadi',404)

def send_document(blob,day,token=None,chat=None,caption=None,filename=None):
    token=token or os.getenv('TELEGRAM_BOT_TOKEN');chat=chat or os.getenv('TELEGRAM_CHAT_ID')
    if not token or not chat:raise RuntimeError('Telegram sozlanmagan')
    caption=caption or (day+' | Jamlangan maktab hisoboti')
    filename=filename or ('Hisobot-'+day+'.pdf')
    boundary=secrets.token_hex(16);chunks=[]
    for name,value in [('chat_id',str(chat)),('caption',caption)]:
        chunks.append(('--'+boundary+'\r\nContent-Disposition: form-data; name="'+name+'"\r\n\r\n'+value+'\r\n').encode())
    chunks.extend([('--'+boundary+'\r\nContent-Disposition: form-data; name="document"; filename="'+filename+'"\r\nContent-Type: application/pdf\r\n\r\n').encode(),blob,('\r\n--'+boundary+'--\r\n').encode()])
    req=Request('https://api.telegram.org/bot'+token+'/sendDocument',data=b''.join(chunks),headers={'Content-Type':'multipart/form-data; boundary='+boundary})
    with urlopen(req,timeout=40) as response:result=json.load(response)
    if not result.get('ok'):raise RuntimeError('Telegram faylni qabul qilmadi')

def maybe_noon_digests(now=None):
    now=now or now_uz()
    if now.hour<12:return 0
    day=now.date().isoformat();queued=0
    with connect() as c:schools=list(c.execute('SELECT * FROM schools'))
    for school in schools:
        with connect() as c:
            c.execute('BEGIN IMMEDIATE')
            if c.execute("SELECT 1 FROM digests WHERE school_id=? AND day=? AND kind='noon'",(school['id'],day)).fetchone():continue
            cal=c.execute('SELECT teaching FROM calendar WHERE school_id=? AND day=?',(school['id'],day)).fetchone()
            if cal and not cal['teaching']:
                c.execute("INSERT INTO digests(school_id,day,kind,created) VALUES(?,?,?,?)",(school['id'],day,'noon',time.time()));continue
            if not c.execute('SELECT 1 FROM classes WHERE school_id=?',(school['id'],)).fetchone():continue
            enqueue(c,day,False,school['id'],'noon')
            c.execute("INSERT INTO digests(school_id,day,kind,created) VALUES(?,?,?,?)",(school['id'],day,'noon',time.time()))
            queued+=1
    return queued

def process_one():
    with connect() as c:
        c.execute('BEGIN IMMEDIATE')
        c.execute("UPDATE outbox SET state='pending' WHERE state='sending' AND claimed<?",(time.time()-300,))
        row=c.execute("SELECT * FROM outbox WHERE state='pending' AND next_try<=? ORDER BY id LIMIT 1",(time.time(),)).fetchone()
        if row:c.execute("UPDATE outbox SET state='sending',claimed=? WHERE id=?",(time.time(),row['id']))
    if not row:return False
    school=None
    with connect() as c:school=school_row(c,row['school_id'])
    token,chat=telegram_for(school)
    if not token or not chat:
        with connect() as c:c.execute("UPDATE outbox SET state='pending',attempts=attempts+1,next_try=? WHERE id=?",(time.time()+300,row['id']))
        return False
    caption=school['name']+' | '+row['day']+' | Kunlik hisobot' if row['kind']!='monthly' else school['name']+' | '+row['day']+' | Oylik hisobot'
    filename='Hisobot-'+school['code']+'-'+row['day']+'.pdf'
    try:send_document(row['pdf'],row['day'],token,chat,caption,filename)
    except Exception:
        LOG.exception('Telegram document delivery failed (outbox=%s, school=%s)',row['id'],row['school_id'])
        with connect() as c:c.execute("UPDATE outbox SET state='pending',attempts=attempts+1,next_try=? WHERE id=?",(time.time()+min(3600,30*2**min(row['attempts'],7)),row['id']))
    else:
        with connect() as c:c.execute("UPDATE outbox SET state='sent',attempts=attempts+1 WHERE id=?",(row['id'],))
    return True

def worker():
    while True:
        try:maybe_noon_digests();process_one()
        except Exception:LOG.exception('Background worker iteration failed')
        time.sleep(5)

class Handler(BaseHTTPRequestHandler):
    def log_message(self,*args):pass
    def do_GET(self):self.handle_api('GET')
    def do_POST(self):self.handle_api('POST')
    def handle_api(self,method):
        try:
            length=int(self.headers.get('Content-Length',0))
            if length<0 or length>1_000_000:raise ApiError('So‘rov juda katta',413)
            data=json.loads(self.rfile.read(length)) if length else {}
            if not isinstance(data,dict):raise ApiError('JSON obyekt kerak')
            result=dispatch(method,self.path,data,self.headers.get('Authorization','').removeprefix('Bearer '))
            raw=result if isinstance(result,bytes) else json.dumps(result,ensure_ascii=False).encode();status=200
            content='application/pdf' if isinstance(result,bytes) else 'application/json; charset=utf-8'
        except ApiError as e:raw=json.dumps({'error':e.message},ensure_ascii=False).encode();status=e.status;content='application/json'
        except database.INTEGRITY_ERRORS:raw=json.dumps({'error':'Bu login yoki sinf allaqachon mavjud'},ensure_ascii=False).encode();status=409;content='application/json'
        except (ValueError,TypeError):raw=b'{"error":"Bad request"}';status=400;content='application/json'
        except Exception:raw=b'{"error":"Server error"}';status=500;content='application/json'
        self.send_response(status);self.send_header('Content-Type',content);self.send_header('Cache-Control','no-store');self.send_header('Content-Length',str(len(raw)));self.end_headers();self.wfile.write(raw)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['init','user','class','serve']);parser.add_argument('--login');parser.add_argument('--role',choices=['teacher','admin'],default='teacher');parser.add_argument('--name');parser.add_argument('--school');parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8080);args=parser.parse_args();init()
    if args.command=='user':
        if not args.login:parser.error('--login kerak')
        pw=getpass.getpass('Yangi parol (kamida 10 belgi): ')
        if len(pw)<10:parser.error('Parol juda qisqa')
        with connect() as c:
            school=find_school_for_login(c,{'school':args.school or ''})
            c.execute('INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,?,?)',(school['district_id'],school['id'],args.login,password_hash(pw),args.role,args.name or args.login))
        print('Foydalanuvchi yaratildi')
    if args.command=='class':
        with connect() as c:
            school=find_school_for_login(c,{'school':args.school or ''})
            u=c.execute("SELECT id FROM users WHERE school_id=? AND login=? AND role='teacher'",(school['id'],args.login)).fetchone()
            if not u or not args.name:parser.error('O‘qituvchi login va sinf nomi kerak')
            c.execute('INSERT INTO classes(school_id,name,teacher) VALUES(?,?,?)',(school['id'],args.name,u['id']))
        print('Sinf yaratildi')
    if args.command=='serve':
        threading.Thread(target=worker,daemon=True).start();print('Server:',args.host,args.port)
        ThreadingHTTPServer((args.host,args.port),Handler).serve_forever()
