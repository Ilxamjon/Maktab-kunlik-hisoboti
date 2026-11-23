"""Telegram bot: teacher registration, class roster, daily attendance, deputy PDF."""
import hashlib, hmac, json, logging, os, re, secrets, time
from datetime import date, timedelta
from urllib.request import Request, urlopen
import database, server
from alphabet import fold, to_new
from catalog import REASONS, EXCEL_LABELS
from excel_report import MONTHS, make_chronic_xlsx, make_summary_xlsx, XLSX
import roster

LOG=logging.getLogger('maktab-hisobot.bot')
DEPUTY='Direktor o‘rinbosari'
TEACHER='Sinf rahbari'
ADD='O‘quvchi qo‘shish'
LIST='O‘quvchilar'
ROSTER_BTN='Ro‘yxat fayli'
ATT='Bugungi davomat'
PDF_BTN='Bugungi jadval'
MONTH_BTN='Oylik hisobot'
YEAR_BTN='Yillik hisobot'
STATUS='Sinflar holati'
STAFF='Sinf rahbarlari'
DAYS='Dam olish'
DEPUTY2='Ikkinchi o‘rinbosar'
CODE_BTN='Maktab kodi'
DIRECTOR_BTN='Direktor'
ADMIN_BTN='Admin'
CANCEL='Bekor qilish'
DONE='Tayyor'
SKIP='O‘tkazib yuborish'
BOY='O‘g‘il'
GIRL='Qiz'
LABELS=(DEPUTY,TEACHER,DEPUTY2,ADD,LIST,ROSTER_BTN,ATT,PDF_BTN,MONTH_BTN,YEAR_BTN,STATUS,STAFF,DAYS,CODE_BTN,DIRECTOR_BTN,ADMIN_BTN,CANCEL,DONE,SKIP,BOY,GIRL)

def norm(value):
    return fold(value)

def same(value,label):
    return norm(value)==norm(label)

def command_name(value):
    token=(value or '').strip().split(' ',1)[0].lower()
    return token.split('@',1)[0]

def keyboard(*rows):
    return {'keyboard':[[{'text':item} for item in row] for row in rows],'resize_keyboard':True}

ROLE_KB=keyboard([DEPUTY],[TEACHER],[DEPUTY2])
TEACHER_KB=keyboard([ADD],[LIST,ATT],[ROSTER_BTN])
DEPUTY_KB=keyboard([PDF_BTN],[MONTH_BTN,YEAR_BTN],[STAFF,STATUS],[DAYS,DEPUTY2],[CODE_BTN,DIRECTOR_BTN])
CANCEL_KB=keyboard([CANCEL])

def _deputy_kb(c,chat):
    if not server.is_platform_admin(c,chat):return DEPUTY_KB
    return keyboard([PDF_BTN],[MONTH_BTN,YEAR_BTN],[STAFF,STATUS],[DAYS,DEPUTY2],[CODE_BTN,DIRECTOR_BTN],[ADMIN_BTN])
WIZARD_KB=keyboard([DONE],[CANCEL])
ADDRESS_KB=keyboard([SKIP],[CANCEL])

def clean_name(value):
    text=to_new(' '.join((value or '').split()))
    if not 2<=len(text)<=40 or norm(text) in {norm(item) for item in LABELS}:return ''
    if not re.search(r'[^\W\d_]',text,re.UNICODE):return ''
    return text

def clean_school(value):
    text=to_new(' '.join((value or '').split()))
    if not 2<=len(text)<=80:return ''
    if not re.search(r'[^\W\d_]',text,re.UNICODE):return ''
    return text

def normalize_class(value):
    text=(value or '').strip().upper().replace(' ','').replace('-','')
    text=text.translate(str.maketrans({'ʻ':'','ʼ':'','‘':'','’':'','`':'',"'":''}))
    if re.fullmatch(r'(?:[1-9]|1[01])[A-ZА-ЯЁ]',text):return text
    return ''

def gender_of(value):
    text=norm(value)
    if text in ('ogil','erkak','m','bola') or same(value,BOY):return 'M'
    if text in ('qiz','f') or same(value,GIRL):return 'F'
    return ''

def webhook_secret():
    explicit=os.getenv('TELEGRAM_WEBHOOK_SECRET','').strip()
    if explicit:return explicit
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not token:return ''
    return hashlib.sha256(b'maktab-hisobot-webhook:'+token.encode()).hexdigest()[:32]

def accept_webhook(header):
    expected=webhook_secret()
    if not expected or not header or len(str(header))!=len(expected):return False
    return hmac.compare_digest(str(header),expected)

def api(method,payload=None,timeout=20):
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    if not re.fullmatch(r'[0-9]{5,15}:[A-Za-z0-9_-]{20,120}',token or ''):
        raise server.ApiError('Telegram bot token sozlanmagan')
    url='https://api.telegram.org/bot'+token+'/'+method
    req=Request(url,data=json.dumps(payload or {}).encode(),headers={'Content-Type':'application/json','Accept':'application/json'})
    with urlopen(req,timeout=timeout) as response:result=json.load(response)
    if not result.get('ok'):raise server.ApiError('Telegram javob bermadi',502)
    return result.get('result')

def ensure_webhook():
    secret=webhook_secret()
    if not secret:return
    api('setWebhook',{'url':server.public_origin()+'/telegram/webhook','secret_token':secret,'allowed_updates':['message','callback_query'],'drop_pending_updates':False})
    LOG.info('Telegram webhook ulandi')

def deliver(messages):
    for item in messages:
        try:
            if item.get('pdf') is not None:
                if not item.get('chat_id'):raise RuntimeError('Direktor o‘rinbosari chati yo‘q')
                server.send_document(item['pdf'],item.get('day') or '',chat=item['chat_id'],caption=item.get('text') or '',filename=item.get('filename'),content_type=item.get('content_type'))
            elif item.get('photo'):
                payload={'chat_id':item['chat_id'],'photo':item['photo'],'caption':(item.get('text') or '')[:1024]}
                if item.get('reply_markup'):payload['reply_markup']=item['reply_markup']
                api('sendPhoto',payload)
            elif item.get('method')=='answerCallbackQuery':
                payload={'callback_query_id':item['id']}
                if item.get('toast'):payload['text']=item['toast'][:180]
                api('answerCallbackQuery',payload)
            else:
                payload={'chat_id':item['chat_id'],'text':item['text'][:4096]}
                if item.get('reply_markup'):payload['reply_markup']=item['reply_markup']
                api('sendMessage',payload)
        except Exception:
            LOG.exception('Telegram xabar yuborilmadi')
            if item.get('pdf') is not None and item.get('notify_chat'):
                try:api('sendMessage',{'chat_id':item['notify_chat'],'text':'Davomat saqlandi, lekin jadval hozir yuborilmadi. Direktor o‘rinbosari «Bugungi jadval» tugmasini bosing.'})
                except Exception:LOG.exception('PDF xatosi haqida xabar yuborilmadi')

def process(update):
    deliver(handle_update(update))

def _localize_markup(markup):
    if not isinstance(markup,dict):return markup
    result={}
    for key,value in markup.items():
        if key in ('keyboard','inline_keyboard') and isinstance(value,list):
            rows=[]
            for row in value:
                buttons=[]
                for button in row:
                    if isinstance(button,dict) and isinstance(button.get('text'),str):
                        copied=dict(button);copied['text']=to_new(button['text']);buttons.append(copied)
                    else:buttons.append(button)
                rows.append(buttons)
            result[key]=rows
        else:result[key]=value
    return result

def _localize(item):
    if not isinstance(item,dict):return item
    item=dict(item)
    for key in ('text','toast','caption'):
        if isinstance(item.get(key),str):item[key]=to_new(item[key])
    if 'reply_markup' in item:item['reply_markup']=_localize_markup(item['reply_markup'])
    return item

def handle_update(update):
    if not isinstance(update,dict):return []
    with server.connect() as c:
        return [_localize(item) for item in _handle(c,update)]

def _handle(c,update):
    uid=update.get('update_id')
    if uid is not None:
        if c.execute('SELECT 1 FROM bot_updates WHERE update_id=?',(uid,)).fetchone():return []
        if int(uid)%100==0:c.execute('DELETE FROM bot_updates WHERE created<?',(time.time()-7*86400,))
        c.execute('INSERT INTO bot_updates(update_id,created) VALUES(?,?)',(int(uid),time.time()))
    chat,user,text,callback,document,photo=_parts(update)
    if not chat or chat.get('type')!='private' or not user or not user.get('id'):return []
    tg=str(user['id']);chat_id=chat['id'];out=[]
    row=_ensure(c,tg)
    if photo:
        _on_photo(c,row,chat_id,tg,photo,out);return out
    if document:
        _on_document(c,row,chat_id,tg,document,out);return out
    if callback is not None:
        out.append({'method':'answerCallbackQuery','id':callback.get('id') or '','toast':''})
        _on_callback(c,row,chat_id,tg,callback.get('data') or '',out)
        if out and out[0].get('method')=='answerCallbackQuery' and not out[0].get('toast'):out[0].pop('toast',None)
        return out
    if not isinstance(text,str) or not text.strip():
        out.append({'chat_id':chat_id,'text':'Matn yuboring.'})
        return out
    _on_text(c,row,chat_id,tg,text.strip(),out)
    return out

def _parts(update):
    if 'callback_query' in update:
        cq=update['callback_query'];msg=cq.get('message') or {}
        return msg.get('chat') or {},cq.get('from') or {},None,cq,None,None
    msg=update.get('message') or {}
    photos=msg.get('photo') or []
    photo=photos[-1] if isinstance(photos,list) and photos else None
    return msg.get('chat') or {},msg.get('from') or {},msg.get('text'),None,msg.get('document'),photo

def fetch_file(file_id):
    info=api('getFile',{'file_id':file_id}) or {}
    path=str(info.get('file_path') or '')
    if not path or '..' in path:raise server.ApiError('Fayl topilmadi')
    token=os.getenv('TELEGRAM_BOT_TOKEN','').strip()
    url='https://api.telegram.org/file/bot'+token+'/'+path
    with urlopen(url,timeout=30) as response:data=response.read(2_000_001)
    if len(data)>2_000_000:raise server.ApiError('Fayl 2 MB dan katta')
    return data

def _on_document(c,row,chat,tg,document,out):
    profile=_profile(c,row)
    name=(document.get('file_name') or '').lower()
    mime=(document.get('mime_type') or '').lower()
    if name.endswith(('.jpg','.jpeg','.png','.webp')) or mime.startswith('image/'):
        _save_receipt(c,chat,profile,document.get('file_id') or '',out);return
    if profile and not server.school_access(c,profile['school_id'])['open']:
        _say(out,chat,server.payment_text(server.school_access(c,profile['school_id'])));return
    if not name.endswith('.xlsx'):
        _say(out,chat,'Faqat .xlsx fayl yuboring. Ustunlar: F.I.SH, Jinsi, Yashash manzili.');return
    if not profile or profile['role']!='teacher' or not profile.get('class_id'):
        _say(out,chat,'Ro‘yxatni faqat o‘z sinfi bor sinf rahbari yuklaydi.');return
    if int(document.get('file_size') or 0)>2_000_000:
        _say(out,chat,'Fayl 2 MB dan katta.');return
    try:parsed=roster.parse_roster(fetch_file(document.get('file_id') or ''))
    except (ValueError,server.ApiError) as error:
        _say(out,chat,str(getattr(error,'message',error)),TEACHER_KB);return
    file_class=parsed['class_name']
    if file_class and file_class!=profile['class_name']:
        _say(out,chat,f"Fayldagi sinf {file_class}, siz esa {profile['class_name']} sinf rahbarisiz. Ro‘yxat yozilmadi.",TEACHER_KB);return
    added=updated=0
    existing={roster.name_key(item['name']):item for item in c.execute('SELECT id,name,active FROM students WHERE class_id=?',(profile['class_id'],))}
    for student in parsed['students']:
        found=existing.get(student['key'])
        if found and found['active']:
            c.execute('UPDATE students SET gender=?,address=? WHERE id=?',(student['gender'],student['address'],found['id']))
            updated+=1
        elif found:
            c.execute('UPDATE students SET name=?,gender=?,address=?,active=1 WHERE id=?',(student['name'],student['gender'],student['address'],found['id']))
            added+=1
        else:
            c.execute('INSERT INTO students(class_id,name,gender,address,active) VALUES(?,?,?,?,1)',(profile['class_id'],student['name'],student['gender'],student['address']))
            added+=1
    lines=[f"{profile['class_name']} sinfiga {added} o‘quvchi qo‘shildi."]
    if updated:lines.append(f"Yangilandi: {updated}.")
    if parsed['errors']:lines.append('O‘tkazildi:\n'+'\n'.join(parsed['errors'][:8]))
    if not parsed['students'] and not parsed['errors']:lines=['Faylda o‘quvchi topilmadi.']
    _touch(c,tg,'',{},profile['id'])
    _say(out,chat,'\n'.join(lines),TEACHER_KB)

def _ensure(c,tg):
    if not c.execute('SELECT 1 FROM bot_chats WHERE telegram_id=?',(tg,)).fetchone():
        c.execute("INSERT INTO bot_chats(telegram_id,state,draft,updated) VALUES(?,'','{}',?)",(tg,time.time()))
    return c.execute('SELECT * FROM bot_chats WHERE telegram_id=?',(tg,)).fetchone()

def _draft(row):
    try:
        data=json.loads(row['draft'] or '{}')
        return data if isinstance(data,dict) else {}
    except json.JSONDecodeError:return {}

def _touch(c,tg,state,draft,user_id):
    c.execute('UPDATE bot_chats SET state=?,draft=?,user_id=?,updated=? WHERE telegram_id=?',(state,json.dumps(draft,ensure_ascii=False),user_id,time.time(),tg))

def _profile(c,row):
    if not row or not row['user_id']:return None
    found=c.execute('''SELECT u.id,u.role,u.name,u.status,u.school_id,s.name AS school_name,s.join_code,s.code AS school_code,s.telegram_chat_id,s.director,
        cl.id AS class_id,cl.name AS class_name
        FROM users u JOIN schools s ON s.id=u.school_id
        LEFT JOIN classes cl ON cl.teacher=u.id AND cl.school_id=u.school_id
        WHERE u.id=?''',(row['user_id'],)).fetchone()
    if not found or found['status']!='active':return None
    return dict(found)

def _say(out,chat,text,markup=None):
    item={'chat_id':chat,'text':text}
    if markup:item['reply_markup']=markup
    out.append(item)

def _district_id(c):
    found=c.execute("SELECT id FROM districts WHERE code='TG'").fetchone()
    if found:return found['id']
    c.execute("INSERT INTO districts(code,name) VALUES('TG','Telegram maktablari')")
    return c.execute("SELECT id FROM districts WHERE code='TG'").fetchone()['id']

def _home(c,tg,chat,out,profile):
    if not profile:
        _touch(c,tg,'role',{},None)
        markup=keyboard([DEPUTY],[TEACHER],[DEPUTY2],[ADMIN_BTN]) if server.is_platform_admin(c,tg) else ROLE_KB
        _say(out,chat,'Maktab Hisobot.\n\nDirektor o‘rinbosari maktabni ochadi va o‘qituvchilarga kod beradi.\nSinf rahbari shu kod bilan kirib, sinf ro‘yxatini va har kunlik davomatni yuboradi.',markup)
        return
    if profile['role']=='teacher' and not profile['class_id']:
        _touch(c,tg,'fix_class',{},profile['id'])
        _say(out,chat,'Qaysi sinfga sinf rahbarisiz? Masalan: 7B',CANCEL_KB)
        return
    if profile['role']=='admin':_bind_deputy_chat(c,profile,chat)
    _touch(c,tg,'',{},profile['id'])
    access=server.school_access(c,profile['school_id'])
    if not access['open']:
        markup=keyboard([ADMIN_BTN]) if server.is_platform_admin(c,tg) else None
        _say(out,chat,server.payment_text(access),markup)
        return
    if profile['role']=='admin':
        _say(out,chat,_deputy_text(profile),_deputy_kb(c,chat))
    else:
        count=c.execute('SELECT count(*) FROM students WHERE class_id=? AND active=1',(profile['class_id'],)).fetchone()[0]
        _say(out,chat,f"{profile['school_name']}\n{profile['class_name']} sinf rahbari: {profile['name']}\nO‘quvchilar: {count}\n«O‘quvchilar»dan ism, jins va manzilni tahrirlaysiz. Ro‘yxatni .xlsx fayl qilib ham yuborishingiz mumkin.",TEACHER_KB)

def _deputy_text(profile):
    director=profile.get('director') or 'kiritilmagan'
    return f"{profile['school_name']}\nDirektor: {director}\nO‘qituvchilar kodi: {profile['join_code']}\n\nSinf rahbarlari botda «Sinf rahbari» ni tanlab shu kodni yozadi. «Sinf rahbarlari»dan ism va sinfni tahrirlaysiz yoki olib tashlaysiz. Har bir o‘quv kunidagi davomat namuna jadval shaklida jamlanib sizga Excel bo‘lib keladi.\n\n{server.contact_text()}"

def _owner_command(c,tg,chat,text,out):
    cmd=command_name(text)
    if server.is_platform_admin(c,tg) and (same(text,ADMIN_BTN) or cmd=='/admin' and ' ' not in text.strip()):
        _admin_panel(c,chat,out);return True
    if cmd=='/admin' and ' ' in text.strip():
        if server.admin_code_ok(text.strip().split(' ',1)[1]):
            server.bind_platform_admin(c,tg)
            _admin_panel(c,chat,out);return True
    return False

OWN_PAGE=10
OWN_MODES={'a':'Hammasi','e':'Tugayotgan','c':'Yopiq'}

def _fmt_day(value):
    return value.strftime('%d.%m.%Y')

def _owner_menu():
    return [
        [{'text':'Qidirish','callback_data':'ad:q'},{'text':'Kvitansiyalar','callback_data':'ad:pend'}],
        [{'text':'To‘lovlar tarixi','callback_data':'ad:ph'},{'text':'Statistika','callback_data':'ad:st'}],
        [{'text':'Hammaga xabar','callback_data':'ad:bc'}],
    ]

def _school_mark(access):
    if not access['open']:return '🔴'
    return '🟡' if access['days_left']<=3 else '🟢'

def _school_line(index,school,access):
    if access['open']:
        return f"{index}. {_school_mark(access)} {school['name']} — {_fmt_day(access['until'])} gacha, {access['days_left']} kun"
    return f"{index}. {_school_mark(access)} {school['name']} — yopiq ({_fmt_day(access['until'])} da tugagan)"

def _admin_panel(c,chat,out):
    _owner_list(c,chat,out,'a',0)

def _owner_list(c,chat,out,mode='a',page=0,query=''):
    rows=[]
    for school in c.execute('SELECT id,name FROM schools ORDER BY id'):
        access=server.school_access(c,school['id'])
        if mode=='e' and not (access['open'] and access['days_left']<=3):continue
        if mode=='c' and access['open']:continue
        if query and fold(query) not in fold(school['name']):continue
        rows.append((school,access))
    pages=max(1,-(-len(rows)//OWN_PAGE))
    page=min(max(page,0),pages-1)
    title=f"Qidiruv: {query}" if query else OWN_MODES.get(mode,'Hammasi')
    lines=[f"Maktablar: {len(rows)} ta ({title})"]
    if pages>1:lines[0]+=f", {page+1}/{pages}-sahifa"
    buttons=[];numbers=[]
    shown=rows[page*OWN_PAGE:(page+1)*OWN_PAGE]
    if not shown:lines.append('Maktab topilmadi.')
    for offset,(school,access) in enumerate(shown):
        index=page*OWN_PAGE+offset+1
        lines.append(_school_line(index,school,access))
        numbers.append({'text':str(index),'callback_data':'ad:s:'+str(school['id'])})
    for start in range(0,len(numbers),5):buttons.append(numbers[start:start+5])
    if pages>1 and not query:
        nav=[]
        if page>0:nav.append({'text':'‹ Oldingi','callback_data':f'ad:l:{mode}:{page-1}'})
        if page<pages-1:nav.append({'text':'Keyingi ›','callback_data':f'ad:l:{mode}:{page+1}'})
        buttons.append(nav)
    buttons.append([{'text':('• ' if key==mode and not query else '')+label,'callback_data':f'ad:l:{key}:0'} for key,label in OWN_MODES.items()])
    buttons.extend(_owner_menu())
    pending=c.execute("SELECT count(*) AS n FROM payments WHERE status='pending'").fetchone()['n']
    if pending:lines.extend(['',f'Kutilayotgan kvitansiya: {pending} ta'])
    lines.extend(['','🟢 ochiq  🟡 3 kun ichida tugaydi  🔴 yopiq'])
    _say(out,chat,'\n'.join(lines),{'inline_keyboard':buttons})

def _owner_school(c,raw):
    if not str(raw).isdigit():return None
    return c.execute('SELECT * FROM schools WHERE id=?',(int(raw),)).fetchone()

def _owner_card(c,chat,out,school,note=''):
    sid=school['id']
    access=server.school_access(c,sid)
    today=server.today().isoformat()
    deputies=', '.join(item['name'] for item in c.execute("SELECT name FROM users WHERE school_id=? AND role='admin' AND status='active' ORDER BY id",(sid,))) or '—'
    classes=c.execute('SELECT count(*) AS n FROM classes WHERE school_id=?',(sid,)).fetchone()['n']
    teachers=c.execute("SELECT count(*) AS n FROM users WHERE school_id=? AND role='teacher' AND status='active'",(sid,)).fetchone()['n']
    pupils=c.execute('SELECT count(*) AS n FROM students s JOIN classes cl ON cl.id=s.class_id WHERE cl.school_id=? AND s.active=1',(sid,)).fetchone()['n']
    sent=c.execute('SELECT count(*) AS n FROM reports WHERE school_id=? AND day=?',(sid,today)).fetchone()['n']
    paid={item['status']:item['n'] for item in c.execute('SELECT status,count(*) AS n FROM payments WHERE school_id=? GROUP BY status',(sid,))}
    last=c.execute('SELECT id,status FROM payments WHERE school_id=? ORDER BY id DESC LIMIT 1',(sid,)).fetchone()
    if access['open']:state=f"{_school_mark(access)} ochiq, {_fmt_day(access['until'])} gacha ({access['days_left']} kun qoldi)"
    else:state=f"{_school_mark(access)} yopiq ({_fmt_day(access['until'])} da tugagan)"
    lines=[
        school['name'],
        f"Kod: {school['join_code'] or '—'}",
        f"Direktor: {school['director'] or '—'}",
        f"Direktor o‘rinbosari: {deputies}",
        f"Ikkinchi o‘rinbosar: {'bor' if (school['deputy_chat_2'] or '').strip() else 'yo‘q'}",
        f"Sinflar: {classes}, sinf rahbarlari: {teachers}, o‘quvchilar: {pupils}",
        f"Bugun jo‘natgan sinflar: {sent}/{classes}",
        f"Holat: {state}",
        f"Ochilgan sana: {school['created_on'] or '—'}",
        f"To‘lovlar: tasdiqlangan {paid.get('approved',0)}, kutilmoqda {paid.get('pending',0)}, rad etilgan {paid.get('rejected',0)}",
    ]
    if note:lines.extend(['',note])
    sid_text=str(sid)
    buttons=[
        [{'text':'+1 oy','callback_data':'ad:x:'+sid_text},{'text':'Sanani belgilash','callback_data':'ad:d:'+sid_text}],
        [{'text':'Nomini o‘zgartirish','callback_data':'ad:r:'+sid_text},{'text':'Xabar yuborish','callback_data':'ad:m:'+sid_text}],
    ]
    if access['open']:buttons.append([{'text':'Yopish','callback_data':'ad:c:'+sid_text}])
    if last:buttons.append([{'text':'So‘nggi kvitansiya','callback_data':'ad:p:'+str(last['id'])}])
    buttons.append([{'text':'O‘chirish','callback_data':'ad:del:'+sid_text}])
    buttons.append([{'text':'Ro‘yxatga qaytish','callback_data':'ad:l:a:0'}])
    _say(out,chat,'\n'.join(lines),{'inline_keyboard':buttons})

def _notify_school(c,out,school,text):
    for target in server.deputy_chats(school):_say(out,target,text)

def _owner_day(text):
    value=(text or '').strip()
    match=re.fullmatch(r'(\d{1,2})[./-](\d{1,2})[./-](\d{4})',value)
    parts=(int(match.group(3)),int(match.group(2)),int(match.group(1))) if match else None
    if not parts:
        match=re.fullmatch(r'(\d{4})-(\d{1,2})-(\d{1,2})',value)
        parts=(int(match.group(1)),int(match.group(2)),int(match.group(3))) if match else None
    if not parts or not 2020<=parts[0]<=2100:return None
    try:return date(*parts)
    except ValueError:return None

def _owner_stats(c,chat,out):
    today=server.today()
    total=opened=trial=paid=closed=expiring=0
    for school in c.execute('SELECT id FROM schools'):
        access=server.school_access(c,school['id'])
        total+=1
        if not access['open']:closed+=1;continue
        opened+=1
        if access['trial']:trial+=1
        else:paid+=1
        if access['days_left']<=3:expiring+=1
    teachers=c.execute("SELECT count(*) AS n FROM users WHERE role='teacher' AND status='active'").fetchone()['n']
    pupils=c.execute('SELECT count(*) AS n FROM students WHERE active=1 AND class_id IN (SELECT id FROM classes)').fetchone()['n']
    classes=c.execute('SELECT count(*) AS n FROM classes').fetchone()['n']
    sent=c.execute('SELECT count(*) AS n FROM reports WHERE day=?',(today.isoformat(),)).fetchone()['n']
    pending=c.execute("SELECT count(*) AS n FROM payments WHERE status='pending'").fetchone()['n']
    approved=c.execute("SELECT count(*) AS n FROM payments WHERE status='approved'").fetchone()['n']
    month_start=time.mktime(today.replace(day=1).timetuple())
    month=c.execute("SELECT count(*) AS n FROM payments WHERE status='approved' AND created>=?",(month_start,)).fetchone()['n']
    fee=f"{server.FEE_SUM:,}".replace(',',' ')
    income=f"{month*server.FEE_SUM:,}".replace(',',' ')
    lines=[
        f"Statistika ({_fmt_day(today)})",
        f"Maktablar: {total}",
        f"Ochiq: {opened} (sinov: {trial}, to‘lagan: {paid})",
        f"Yopiq: {closed}",
        f"3 kun ichida tugaydi: {expiring}",
        f"Sinf rahbarlari: {teachers}, sinflar: {classes}, o‘quvchilar: {pupils}",
        f"Bugun jo‘natilgan sinf hisobotlari: {sent}",
        f"Kutilayotgan kvitansiya: {pending}",
        f"Tasdiqlangan to‘lovlar: jami {approved} ta, shu oy {month} ta ({income} so‘m)",
        f"Oylik narx: {fee} so‘m",
    ]
    _say(out,chat,'\n'.join(lines),{'inline_keyboard':[[{'text':'Maktablar','callback_data':'ad:l:a:0'}]]})

def _owner_pending(c,chat,out):
    pending=list(c.execute("SELECT id,school_id,school_name,deputy_name FROM payments WHERE status='pending' ORDER BY id"))
    if not pending:
        _say(out,chat,'Kutilayotgan kvitansiya yo‘q.',{'inline_keyboard':[[{'text':'Maktablar','callback_data':'ad:l:a:0'}]]});return
    lines=['Kutilayotgan kvitansiyalar:'];buttons=[]
    for item in pending:
        lines.append(f"#{item['id']} {item['school_name']} — {item['deputy_name']}")
        buttons.append([{'text':f"#{item['id']} {item['school_name'][:28]}",'callback_data':'paysee:'+str(item['id'])}])
    buttons.append([{'text':'Maktablar','callback_data':'ad:l:a:0'}])
    _say(out,chat,'\n'.join(lines),{'inline_keyboard':buttons})

def _owner_history(c,chat,out):
    names={'approved':'tasdiqlangan','pending':'kutilmoqda','rejected':'rad etilgan','replaced':'almashtirilgan'}
    rows=list(c.execute('SELECT id,school_name,deputy_name,status,created FROM payments ORDER BY id DESC LIMIT 15'))
    lines=['So‘nggi kvitansiyalar:' if rows else 'Hali kvitansiya yo‘q.'];buttons=[]
    for item in rows:
        stamp=time.strftime('%d.%m %H:%M',time.localtime(item['created']))
        lines.append(f"#{item['id']} {item['school_name']} — {names.get(item['status'],item['status'])}, {stamp}")
        buttons.append([{'text':f"#{item['id']} {item['school_name'][:28]}",'callback_data':'paysee:'+str(item['id'])}])
    buttons.append([{'text':'Maktablar','callback_data':'ad:l:a:0'}])
    _say(out,chat,'\n'.join(lines),{'inline_keyboard':buttons})

def _owner_ask(c,row,tg,chat,out,state,draft,prompt):
    _touch(c,tg,state,draft,row['user_id'])
    _say(out,chat,prompt,CANCEL_KB)

def _owner_callback(c,row,chat,tg,data,out):
    parts=data.split(':')
    action=parts[1] if len(parts)>1 else ''
    arg=parts[2] if len(parts)>2 else ''
    if action=='l':
        mode=arg if arg in OWN_MODES else 'a'
        page=int(parts[3]) if len(parts)>3 and parts[3].isdigit() else 0
        _owner_list(c,chat,out,mode,page);return
    if action=='q':
        _owner_ask(c,row,tg,chat,out,'own_q',{},'Maktab nomidan bir bo‘lak yozing.');return
    if action=='pend':_owner_pending(c,chat,out);return
    if action=='ph':_owner_history(c,chat,out);return
    if action=='st':_owner_stats(c,chat,out);return
    if action=='bc':
        _owner_ask(c,row,tg,chat,out,'own_bc',{},'Barcha direktor o‘rinbosarlariga yuboriladigan xabarni yozing.');return
    if action=='bcy':
        _owner_broadcast(c,row,tg,chat,out);return
    if action=='p':
        payment=c.execute('SELECT * FROM payments WHERE id=?',(int(arg),)).fetchone() if arg.isdigit() else None
        if not payment:
            out[0]['toast']='Topilmadi';return
        item={'chat_id':chat,'photo':payment['file_id'],'text':_receipt_caption(payment)+f"\nHolat: {payment['status']}"}
        if payment['status']=='pending':item['reply_markup']=_receipt_buttons(payment['id'])
        out.append(item);return
    school=_owner_school(c,arg)
    if not school:
        out[0]['toast']='Maktab topilmadi';return
    sid=school['id']
    if action=='s':_owner_card(c,chat,out,school);return
    if action=='x':
        until=server.extend_subscription(c,sid)
        out[0]['toast']='Uzaytirildi'
        _notify_school(c,out,school,f"Obuna uzaytirildi. Bot {_fmt_day(until)} gacha ishlaydi.")
        _owner_card(c,chat,out,_owner_school(c,sid),f"Obuna {_fmt_day(until)} gacha uzaytirildi.");return
    if action=='d':
        _owner_ask(c,row,tg,chat,out,'own_date',{'sid':sid},f"{school['name']}\nBot qaysi sanagacha ishlasin? Masalan: 25.12.2026");return
    if action=='r':
        _owner_ask(c,row,tg,chat,out,'own_name',{'sid':sid},f"Hozirgi nom: {school['name']}\nYangi nomni yozing.");return
    if action=='m':
        _owner_ask(c,row,tg,chat,out,'own_msg',{'sid':sid},f"{school['name']}\nDirektor o‘rinbosariga yuboriladigan xabarni yozing.");return
    if action=='c':
        _say(out,chat,f"{school['name']} uchun botni hozir yopasizmi? Sinf rahbarlari ham, o‘rinbosar ham ishlata olmaydi.",{'inline_keyboard':[[{'text':'Ha, yopish','callback_data':'ad:cy:'+str(sid)}],[{'text':'Bekor','callback_data':'ad:s:'+str(sid)}]]});return
    if action=='cy':
        server.set_access_until(c,sid,server.today()-timedelta(days=1))
        out[0]['toast']='Yopildi'
        _notify_school(c,out,school,'Obuna to‘xtatildi. Bot ishlashi uchun to‘lov qiling.\n\n'+server.contact_text())
        _owner_card(c,chat,out,_owner_school(c,sid),'Maktab yopildi.');return
    if action=='del':
        _say(out,chat,f"{school['name']} maktabini butunlay o‘chirasizmi?\nBarcha sinf rahbarlari, sinflar, o‘quvchilar, hisobotlar va to‘lov tarixi o‘chadi. Qaytarib bo‘lmaydi.",{'inline_keyboard':[[{'text':'Ha, butunlay o‘chirish','callback_data':'ad:dely:'+str(sid)}],[{'text':'Bekor','callback_data':'ad:s:'+str(sid)}]]});return
    if action=='dely':
        name=school['name']
        server.delete_school(c,sid)
        out[0]['toast']='O‘chirildi'
        _say(out,chat,f"{name} o‘chirildi.")
        _owner_list(c,chat,out,'a',0);return
    out[0]['toast']='Topilmadi'

def _owner_broadcast(c,row,tg,chat,out):
    draft=_draft(row)
    text=(draft.get('text') or '').strip()
    if row['state']!='own_bcc' or not text:
        out[0]['toast']='Xabar topilmadi';return
    sent=set()
    for school in c.execute('SELECT * FROM schools ORDER BY id'):
        for target in server.deputy_chats(school):
            if target in sent:continue
            sent.add(target);_say(out,target,text)
    _touch(c,tg,'',{},row['user_id'])
    out[0]['toast']='Yuborildi'
    _say(out,chat,f"Xabar {len(sent)} ta chatga yuborildi.")

def _owner_text(c,row,chat,tg,state,draft,text,out):
    if state=='own_q':
        _touch(c,tg,'',{},row['user_id'])
        _owner_list(c,chat,out,'a',0,text.strip());return
    if state=='own_bc' or state=='own_bcc':
        message=text.strip()
        if len(message)>1000:
            _say(out,chat,'Xabar 1000 belgidan oshmasin.',CANCEL_KB);return
        _touch(c,tg,'own_bcc',{'text':message},row['user_id'])
        _say(out,chat,'Yuboriladigan xabar:\n\n'+message,{'inline_keyboard':[[{'text':'Hammaga yuborish','callback_data':'ad:bcy'}],[{'text':'Bekor qilish','callback_data':'ad:l:a:0'}]]});return
    school=_owner_school(c,draft.get('sid'))
    if not school:
        _touch(c,tg,'',{},row['user_id']);_say(out,chat,'Maktab topilmadi.');return
    if state=='own_name':
        name=clean_school(text)
        if not name:
            _say(out,chat,'Maktab nomini yozing.',CANCEL_KB);return
        c.execute('UPDATE schools SET name=? WHERE id=?',(name,school['id']))
        _touch(c,tg,'',{},row['user_id'])
        _owner_card(c,chat,out,_owner_school(c,school['id']),'Nom o‘zgartirildi.');return
    if state=='own_date':
        day=_owner_day(text)
        if not day:
            _say(out,chat,'Sanani 25.12.2026 ko‘rinishida yozing.',CANCEL_KB);return
        server.set_access_until(c,school['id'],day)
        _touch(c,tg,'',{},row['user_id'])
        access=server.school_access(c,school['id'])
        if access['open']:_notify_school(c,out,school,f"Obuna sanasi yangilandi. Bot {_fmt_day(day)} gacha ishlaydi.")
        _owner_card(c,chat,out,_owner_school(c,school['id']),f"Sana belgilandi: {_fmt_day(day)}.");return
    if state=='own_msg':
        message=text.strip()
        if len(message)>1000:
            _say(out,chat,'Xabar 1000 belgidan oshmasin.',CANCEL_KB);return
        _notify_school(c,out,school,message)
        _touch(c,tg,'',{},row['user_id'])
        _owner_card(c,chat,out,school,'Xabar yuborildi.');return
    _touch(c,tg,'',{},row['user_id'])

def _on_photo(c,row,chat,tg,photo,out):
    _save_receipt(c,chat,_profile(c,row),str((photo or {}).get('file_id') or ''),out)

def _save_receipt(c,chat,profile,file_id,out):
    if not profile or profile['role']!='admin':
        _say(out,chat,'Kvitansiyani direktor o‘rinbosari yuboradi.');return
    access=server.school_access(c,profile['school_id'])
    if access['open'] and access['days_left']>3:
        _say(out,chat,'Obuna hali tugamagan. Kvitansiya kerak emas.',_deputy_kb(c,chat));return
    if not file_id:
        _say(out,chat,'Rasm kelmadi. Qayta yuboring.');return
    c.execute("UPDATE payments SET status='replaced' WHERE school_id=? AND status='pending'",(profile['school_id'],))
    c.execute('INSERT INTO payments(school_id,chat_id,deputy_name,school_name,file_id,status,created) VALUES(?,?,?,?,?,?,?)',(profile['school_id'],str(chat),profile['name'],profile['school_name'],file_id,'pending',time.time()))
    payment_id=c.execute('SELECT id FROM payments WHERE school_id=? AND file_id=? ORDER BY id DESC',(profile['school_id'],file_id)).fetchone()['id']
    _say(out,chat,'Kvitansiya qabul qilindi. Tasdiqlangach keyingi oy ochiladi.',_deputy_kb(c,chat))
    _notify_receipt(c,out,payment_id)

def _receipt_caption(row):
    return f"Kvitansiya #{row['id']}\nMaktab: {row['school_name']}\nYubordi: {row['deputy_name']}\nSumma: {server.fee_text()}"

def _receipt_buttons(payment_id):
    return {'inline_keyboard':[[{'text':'Tasdiqlash','callback_data':'payok:'+str(payment_id)},{'text':'Rad etish','callback_data':'payno:'+str(payment_id)}]]}

def _notify_receipt(c,out,payment_id):
    row=c.execute('SELECT * FROM payments WHERE id=?',(payment_id,)).fetchone()
    if not row:return
    caption=_receipt_caption(row)
    buttons=_receipt_buttons(payment_id)
    admins=server.platform_admin_ids(c)
    if not admins:
        return
    for admin in admins:
        out.append({'chat_id':admin,'photo':row['file_id'],'text':caption,'reply_markup':buttons})

def _payment_callback(c,chat,tg,data,out):
    if not server.is_platform_admin(c,tg):
        out[0]['toast']='Ruxsat yo‘q';return
    kind,raw=data.split(':',1)
    if not raw.isdigit():
        out[0]['toast']='Topilmadi';return
    row=c.execute('SELECT * FROM payments WHERE id=?',(int(raw),)).fetchone()
    if not row:
        out[0]['toast']='Topilmadi';return
    if kind=='paysee':
        out.append({'chat_id':chat,'photo':row['file_id'],'text':_receipt_caption(row),'reply_markup':_receipt_buttons(row['id'])});return
    if row['status']!='pending':
        out[0]['toast']='Allaqachon ko‘rilgan';return
    if kind=='payok':
        until=server.extend_subscription(c,row['school_id'])
        c.execute("UPDATE payments SET status='approved' WHERE id=?",(row['id'],))
        out[0]['toast']='Tasdiqlandi'
        _say(out,chat,f"Tasdiqlandi.\n{row['school_name']}\n{row['deputy_name']}\n{until.strftime('%d.%m.%Y')} gacha ochiq.")
        _say(out,row['chat_id'],f"To‘lov tasdiqlandi. Bot {until.strftime('%d.%m.%Y')} gacha ishlaydi.",_deputy_kb(c,row['chat_id']))
        return
    c.execute("UPDATE payments SET status='rejected' WHERE id=?",(row['id'],))
    out[0]['toast']='Rad etildi'
    _say(out,row['chat_id'],'Kvitansiya rad etildi. To‘lov rasmini qayta yuboring.')

def _on_text(c,row,chat,tg,text,out):
    profile=_profile(c,row)
    cmd=command_name(text)
    if cmd in ('/start','/menu','/help'):
        _home(c,tg,chat,out,profile);return
    if cmd=='/id':
        _say(out,chat,'Sizning Telegram raqamingiz: '+tg);return
    if same(text,CANCEL) or cmd=='/cancel':
        _home(c,tg,chat,out,profile);return
    if _owner_command(c,tg,chat,text,out):return
    if server.is_platform_admin(c,tg) and (row['state'] or '').startswith('own_'):
        _owner_text(c,row,chat,tg,row['state'],_draft(row),text,out);return
    if profile and not server.school_access(c,profile['school_id'])['open']:
        _say(out,chat,server.payment_text(server.school_access(c,profile['school_id'])));return
    if profile and profile['role']=='admin' and (cmd=='/kod' or same(text,CODE_BTN)):
        _say(out,chat,f"O‘qituvchilar kodi: {profile['join_code']}",_deputy_kb(c,chat));return
    if profile and profile['role']=='admin' and same(text,DIRECTOR_BTN):
        _touch(c,tg,'dir_first',{},profile['id'])
        _say(out,chat,'Maktab direktorining ismini yozing.',CANCEL_KB);return
    if profile and profile['role']=='admin' and (cmd=='/holat' or same(text,STATUS)):
        _say(out,chat,_status_text(c,profile),_deputy_kb(c,chat));return
    if profile and profile['role']=='admin' and (cmd=='/pdf' or same(text,PDF_BTN)):
        _send_compiled(c,out,profile,chat,f"{profile['school_name']} | bugungi jamlanma");return
    if profile and profile['role']=='admin' and (cmd=='/oy' or same(text,MONTH_BTN)):
        _ask_month(out,chat);return
    if profile and profile['role']=='admin' and (cmd=='/yil' or same(text,YEAR_BTN)):
        _send_span(c,out,profile,chat,'year',str(server.school_year_start()),offer_previous=True);return
    if profile and profile['role']=='admin' and (cmd=='/rahbarlar' or same(text,STAFF)):
        _touch(c,tg,'',{},profile['id'])
        _staff_message(c,out,chat,profile);return
    if profile and profile['role']=='admin' and (cmd=='/dam' or same(text,DAYS)):
        _touch(c,tg,'adm_off',{},profile['id'])
        _holiday_message(c,out,chat,profile);return
    if profile and profile['role']=='admin' and (cmd=='/orinbosar' or same(text,DEPUTY2)):
        _invite_deputy(c,out,chat,profile);return
    if profile and _teacher_menu(c,row,profile,chat,tg,text,out):return
    state=row['state'] or ''
    draft=_draft(row)
    if not profile:
        _register(c,tg,chat,state,draft,text,out);return
    if profile['role']=='admin' and state in ('adm_name','adm_class'):
        _admin_edit_text(c,tg,chat,profile,state,draft,text,out);return
    if profile['role']=='admin' and state=='dir_first':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Maktab direktorining ismini yozing.',CANCEL_KB);return
        draft['dir_first']=name
        _touch(c,tg,'dir_last',draft,profile['id'])
        _say(out,chat,'Maktab direktorining familiyasini yozing.',CANCEL_KB);return
    if profile['role']=='admin' and state=='dir_last':
        _save_director(c,tg,chat,profile,draft,text,out);return
    if profile['role']=='admin' and state in ('adm_off','adm_cal'):
        _mark_holiday_text(c,tg,chat,profile,text,out);return
    if profile['role']=='teacher' and state in ('stu_rename','stu_addr'):
        _student_edit_text(c,tg,chat,profile,state,draft,text,out);return
    if profile['role']=='teacher' and state=='stu_move':
        _move_student(c,tg,chat,profile,draft,text,out);return
    if state=='fix_class':
        _bind_class(c,tg,chat,profile,text,out);return
    if state=='stu_name':
        if same(text,DONE):
            _home(c,tg,chat,out,profile);return
        name=clean_name(text)
        if not name:
            _say(out,chat,'O‘quvchining familiyasi va ismini yozing. Masalan: Karimov Jasur',WIZARD_KB);return
        draft['name']=name
        _touch(c,tg,'stu_gender',draft,profile['id'])
        _say(out,chat,name+'\nJinsini tanlang.',{'inline_keyboard':[[{'text':BOY,'callback_data':'g:M'},{'text':GIRL,'callback_data':'g:F'}]]})
        return
    if state=='stu_gender':
        gender=gender_of(text)
        if not gender:
            _say(out,chat,'Jinsini tanlang: o‘g‘il yoki qiz.');return
        _ask_address(c,tg,chat,draft,gender,profile,out);return
    if state=='stu_address':
        if same(text,DONE):
            _home(c,tg,chat,out,profile);return
        _save_student(c,tg,chat,profile,draft,'' if same(text,SKIP) or text.strip() in ('-','—') else text.strip(),out);return
    _home(c,tg,chat,out,profile)

def _teacher_menu(c,row,profile,chat,tg,text,out):
    if profile['role']!='teacher':return False
    if same(text,ADD):
        _touch(c,tg,'stu_name',{},profile['id'])
        _say(out,chat,'O‘quvchining familiyasi va ismini yozing.\nTugatganda «Tayyor» ni bosing.',WIZARD_KB);return True
    if same(text,LIST):
        _touch(c,tg,'',{},profile['id'])
        _students_message(c,out,chat,profile);return True
    if same(text,ROSTER_BTN):
        _send_roster(c,out,chat,profile);return True
    if same(text,ATT):
        _open_attendance(c,tg,chat,profile,out);return True
    return False

def _register(c,tg,chat,state,draft,text,out):
    if state in ('','role') or same(text,DEPUTY) or same(text,TEACHER):
        if same(text,DEPUTY):
            _touch(c,tg,'dep_first',{},None)
            _say(out,chat,'Ismingizni yozing.',CANCEL_KB);return
        if same(text,TEACHER):
            _touch(c,tg,'tch_code',{},None)
            _say(out,chat,'Direktor o‘rinbosari bergan 6 xonali kodni yozing.',CANCEL_KB);return
        if same(text,DEPUTY2):
            _touch(c,tg,'dep2_code',{},None)
            _say(out,chat,'Birinchi direktor o‘rinbosari bergan 6 xonali kodni yozing.',CANCEL_KB);return
        _touch(c,tg,'role',{},None)
        _say(out,chat,'Kim sifatida kirmoqchisiz? Tugmani bosing.',ROLE_KB);return
    if state=='dep_first':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Ismingizni yozing.',CANCEL_KB);return
        draft['first']=name
        _touch(c,tg,'dep_last',draft,None)
        _say(out,chat,'Familiyangizni yozing.',CANCEL_KB);return
    if state=='dep_last':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Familiyangizni yozing.',CANCEL_KB);return
        draft['last']=name
        _touch(c,tg,'dep_school',draft,None)
        _say(out,chat,'Maktab nomini yozing. Masalan: 18-maktab',CANCEL_KB);return
    if state=='dep_school':
        school_name=clean_school(text)
        if not school_name:
            _say(out,chat,'Maktab nomini yozing.',CANCEL_KB);return
        draft['school']=school_name
        _touch(c,tg,'dep_dir_first',draft,None)
        _say(out,chat,'Maktab direktorining ismini yozing.',CANCEL_KB);return
    if state=='dep_dir_first':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Maktab direktorining ismini yozing.',CANCEL_KB);return
        draft['dir_first']=name
        _touch(c,tg,'dep_dir_last',draft,None)
        _say(out,chat,'Maktab direktorining familiyasini yozing.',CANCEL_KB);return
    if state=='dep_dir_last':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Maktab direktorining familiyasini yozing.',CANCEL_KB);return
        draft['dir_last']=name
        _create_deputy(c,tg,chat,draft,draft.get('school') or '',out);return
    if state=='tch_code':
        code=re.sub(r'\D','',text)
        school=c.execute('SELECT * FROM schools WHERE join_code=?',(code,)).fetchone() if len(code)==6 else None
        if not school:
            _say(out,chat,'Kod topilmadi. Direktor o‘rinbosaridan 6 xonali kodni so‘rang.',CANCEL_KB);return
        if not server.school_access(c,school['id'])['open']:
            _say(out,chat,'Bu maktabning obunasi tugagan. Direktor o‘rinbosari to‘lov qilishi kerak.',ROLE_KB);return
        draft={'school_id':school['id'],'school_name':school['name']}
        _touch(c,tg,'tch_first',draft,None)
        _say(out,chat,school['name']+'\nIsmingizni yozing.',CANCEL_KB);return
    if state=='tch_first':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Ismingizni yozing.',CANCEL_KB);return
        draft['first']=name
        _touch(c,tg,'tch_last',draft,None)
        _say(out,chat,'Familiyangizni yozing.',CANCEL_KB);return
    if state=='tch_last':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Familiyangizni yozing.',CANCEL_KB);return
        draft['last']=name
        _touch(c,tg,'tch_class',draft,None)
        _say(out,chat,'Qaysi sinfga sinf rahbarisiz? Masalan: 7B',CANCEL_KB);return
    if state=='tch_class':
        _create_teacher(c,tg,chat,draft,text,out);return
    if state=='dep2_code':
        _join_deputy(c,tg,chat,text,out);return
    _touch(c,tg,'role',{},None)
    _say(out,chat,'Tugmani bosing.',ROLE_KB)

def _full_name(draft):
    return (draft.get('last','')+' '+draft.get('first','')).strip()

def _save_director(c,tg,chat,profile,draft,text,out):
    name=clean_name(text)
    if not name:
        _say(out,chat,'Maktab direktorining familiyasini yozing.',CANCEL_KB);return
    director=(name+' '+(draft.get('dir_first') or '')).strip()
    c.execute('UPDATE schools SET director=? WHERE id=?',(director,profile['school_id']))
    profile['director']=director
    _touch(c,tg,'',{},profile['id'])
    _say(out,chat,f"Direktor saqlandi: {director}\nBu ism Exceldagi «Direktor:» qatorida chiqadi.",_deputy_kb(c,chat))

def _create_deputy(c,tg,chat,draft,school_name,out):
    full=_full_name(draft)
    director=(draft.get('dir_last','')+' '+draft.get('dir_first','')).strip() or full
    did=_district_id(c)
    join_code='';school_code=''
    for _ in range(30):
        join_code=str(secrets.randbelow(900000)+100000)
        school_code='TG-'+join_code
        if not server.code_taken(c,school_code) and not c.execute('SELECT 1 FROM schools WHERE join_code=?',(join_code,)).fetchone():break
    else:
        _say(out,chat,'Kod yaratilmadi. Qayta urinib ko‘ring.',CANCEL_KB);return
    c.execute('INSERT INTO schools(district_id,code,name,director,executor,telegram_chat_id,join_code,created_on) VALUES(?,?,?,?,?,?,?,?)',(did,school_code,school_name,director,full,str(chat),join_code,server.today().isoformat()))
    school_id=c.execute('SELECT id FROM schools WHERE code=?',(school_code,)).fetchone()['id']
    login='tg'+tg
    c.execute("INSERT INTO users(district_id,school_id,login,password,role,name,status) VALUES(?,?,?,?,'admin',?,'active')",(did,school_id,login,server.password_hash(secrets.token_hex(16)),full))
    user_id=c.execute('SELECT id FROM users WHERE school_id=? AND login=?',(school_id,login)).fetchone()['id']
    _touch(c,tg,'',{},user_id)
    profile=_profile(c,{'user_id':user_id})
    _say(out,chat,'Maktab ochildi.\n'+_deputy_text(profile),_deputy_kb(c,chat))

def _create_teacher(c,tg,chat,draft,raw_class,out):
    class_name=normalize_class(raw_class)
    if not class_name:
        _say(out,chat,'Sinfni 7B ko‘rinishida yozing. Raqam 1 dan 11 gacha, oxirida harf.',CANCEL_KB);return
    school_id=draft.get('school_id')
    school=c.execute('SELECT * FROM schools WHERE id=?',(school_id,)).fetchone()
    if not school:
        _touch(c,tg,'role',{},None);_say(out,chat,'Maktab topilmadi. Kodni qayta kiriting.',ROLE_KB);return
    full=_full_name(draft)
    login='tg'+tg
    existing=c.execute('SELECT id FROM users WHERE school_id=? AND login=?',(school_id,login)).fetchone()
    if existing:
        user_id=existing['id']
        c.execute("UPDATE users SET name=?,role='teacher',status='active' WHERE id=?",(full,user_id))
    else:
        c.execute("INSERT INTO users(district_id,school_id,login,password,role,name,status) VALUES(?,?,?,?,'teacher',?,'active')",(school['district_id'],school_id,login,server.password_hash(secrets.token_hex(16)),full))
        user_id=c.execute('SELECT id FROM users WHERE school_id=? AND login=?',(school_id,login)).fetchone()['id']
    cid,error=_assign_class(c,school_id,user_id,class_name)
    if error:
        _say(out,chat,error,CANCEL_KB);return
    _touch(c,tg,'',{},user_id)
    profile=_profile(c,{'user_id':user_id})
    _say(out,chat,f"Ro‘yxatdan o‘tdingiz.\n{profile['school_name']}, {profile['class_name']} sinf.\nO‘quvchini qo‘lda yozing yoki F.I.SH, Jinsi, Yashash manzili yozilgan .xlsx faylni yuboring.",TEACHER_KB)

def _bind_class(c,tg,chat,profile,raw_class,out):
    class_name=normalize_class(raw_class)
    if not class_name:
        _say(out,chat,'Sinfni 7B ko‘rinishida yozing.',CANCEL_KB);return
    cid,error=_assign_class(c,profile['school_id'],profile['id'],class_name)
    if error:
        _say(out,chat,error,CANCEL_KB);return
    profile['class_id']=cid;profile['class_name']=class_name
    _home(c,tg,chat,out,profile)

def _assign_class(c,school_id,user_id,class_name):
    current=c.execute('SELECT id,teacher FROM classes WHERE school_id=? AND name=?',(school_id,class_name)).fetchone()
    if current and current['teacher'] and int(current['teacher'])!=int(user_id):
        return None,'Bu sinfning sinf rahbari allaqachon bor.'
    if current:
        c.execute('UPDATE classes SET teacher=? WHERE id=?',(user_id,current['id']))
        return current['id'],None
    owned=c.execute('SELECT id,name FROM classes WHERE school_id=? AND teacher=?',(school_id,user_id)).fetchone()
    if owned:
        c.execute('UPDATE classes SET name=? WHERE id=?',(class_name,owned['id']))
        return owned['id'],None
    c.execute('INSERT INTO classes(school_id,name,teacher) VALUES(?,?,?)',(school_id,class_name,user_id))
    return c.execute('SELECT id FROM classes WHERE school_id=? AND name=?',(school_id,class_name)).fetchone()['id'],None

def _ask_address(c,tg,chat,draft,gender,profile,out):
    draft['gender']=gender
    _touch(c,tg,'stu_address',draft,profile['id'])
    _say(out,chat,'Yashash manzilini yozing. Manzil bo‘lmasa «O‘tkazib yuborish» ni bosing.',ADDRESS_KB)

def _save_student(c,tg,chat,profile,draft,address,out):
    name=draft.get('name') or ''
    gender=draft.get('gender') if draft.get('gender') in ('M','F') else ''
    if not name or not gender:
        _touch(c,tg,'stu_name',{},profile['id'])
        _say(out,chat,'O‘quvchini boshidan kiriting.',WIZARD_KB);return
    address=to_new(address)
    if len(address)>300:
        _say(out,chat,'Manzil juda uzun. Qisqaroq yozing.',ADDRESS_KB);return
    c.execute('INSERT INTO students(class_id,name,gender,address,active) VALUES(?,?,?,?,1)',(profile['class_id'],name,gender,address))
    _touch(c,tg,'stu_name',{},profile['id'])
    _say(out,chat,f"Qo‘shildi: {name}\nKeyingi o‘quvchini yozing yoki «Tayyor» ni bosing.",WIZARD_KB)

def _gender_word(gender):
    if gender=='M':return 'o‘g‘il'
    if gender=='F':return 'qiz'
    return '—'

def _own_student(c,profile,sid):
    if not str(sid).isdigit() or not profile.get('class_id'):return None
    row=c.execute('SELECT * FROM students WHERE id=? AND class_id=? AND active=1',(int(sid),profile['class_id'])).fetchone()
    return dict(row) if row else None

def _students_message(c,out,chat,profile):
    rows=list(c.execute('SELECT id,name,gender,address FROM students WHERE class_id=? AND active=1 ORDER BY name',(profile['class_id'],)))
    if not rows:
        _say(out,chat,'Hali o‘quvchi yo‘q. «O‘quvchi qo‘shish» ni bosing yoki .xlsx ro‘yxat yuboring.',TEACHER_KB);return
    lines=[]
    buttons=[]
    for index,row in enumerate(rows,1):
        place=row['address'] or 'manzil yo‘q'
        lines.append(f"{index}. {row['name']} — {_gender_word(row['gender'])} — {place}")
        buttons.append([{'text':'Tahrirlash: '+row['name'][:40],'callback_data':'ed:'+str(row['id'])}])
    out.append({'chat_id':chat,'text':'O‘quvchini tanlang:\n'+'\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}})

def _student_card(out,chat,student):
    text=f"{student['name']}\nJinsi: {_gender_word(student['gender'])}\nManzil: {student['address'] or '—'}"
    sid=str(student['id'])
    buttons=[
        [{'text':'Ism-familiya','callback_data':'sn:'+sid}],
        [{'text':'Jinsi','callback_data':'sg:'+sid}],
        [{'text':'Manzil','callback_data':'sa:'+sid}],
        [{'text':'Boshqa sinf','callback_data':'sm:'+sid}],
        [{'text':'O‘chirish','callback_data':'del:'+sid}],
        [{'text':'Ro‘yxatga qaytish','callback_data':'ls'}],
    ]
    out.append({'chat_id':chat,'text':text,'reply_markup':{'inline_keyboard':buttons}})

def _student_edit_text(c,tg,chat,profile,state,draft,text,out):
    student=_own_student(c,profile,draft.get('id'))
    if not student:
        _touch(c,tg,'',{},profile['id'])
        _say(out,chat,'O‘quvchi topilmadi.',TEACHER_KB);return
    if state=='stu_rename':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Familiya va ismni yozing. Masalan: Karimov Jasur',CANCEL_KB);return
        key=roster.name_key(name)
        duplicate=any(roster.name_key(row['name'])==key for row in c.execute('SELECT id,name FROM students WHERE class_id=? AND active=1 AND id<>?',(profile['class_id'],student['id'])))
        if duplicate:
            _say(out,chat,'Bu ism sinfda bor. Boshqa ism yozing.',CANCEL_KB);return
        c.execute('UPDATE students SET name=? WHERE id=? AND class_id=?',(name,student['id'],profile['class_id']))
        student['name']=name
    else:
        address='' if same(text,SKIP) or text.strip() in ('-','—') else to_new(text.strip())
        if len(address)>300:
            _say(out,chat,'Manzil juda uzun. Qisqaroq yozing.',ADDRESS_KB);return
        c.execute('UPDATE students SET address=? WHERE id=? AND class_id=?',(address,student['id'],profile['class_id']))
        student['address']=address
    _touch(c,tg,'',{},profile['id'])
    _student_card(out,chat,student)

def _move_student(c,tg,chat,profile,draft,text,out):
    student=_own_student(c,profile,draft.get('id'))
    class_name=normalize_class(text)
    if not student:
        _touch(c,tg,'',{},profile['id']);_say(out,chat,'O‘quvchi topilmadi.',TEACHER_KB);return
    if not class_name:
        _say(out,chat,'Sinfni 8B ko‘rinishida yozing.',CANCEL_KB);return
    target=c.execute('SELECT id FROM classes WHERE school_id=? AND name=?',(profile['school_id'],class_name)).fetchone()
    if not target:
        _say(out,chat,'Bu sinf topilmadi. Avval yangi sinf rahbari ro‘yxatdan o‘tsin.',CANCEL_KB);return
    if int(target['id'])==int(profile['class_id']):
        _say(out,chat,'O‘quvchi shu sinfda.',CANCEL_KB);return
    c.execute('UPDATE students SET class_id=? WHERE id=? AND class_id=?',(target['id'],student['id'],profile['class_id']))
    _touch(c,tg,'',{},profile['id'])
    _say(out,chat,f"{student['name']} {class_name} sinfiga o‘tkazildi. Oldingi davomat saqlanadi.",TEACHER_KB)

def _send_roster(c,out,chat,profile):
    if not profile.get('class_id'):
        _say(out,chat,'Avval sinfni kiriting.',TEACHER_KB);return
    students=[dict(row) for row in c.execute('SELECT name,gender,address FROM students WHERE class_id=? AND active=1 ORDER BY name',(profile['class_id'],))]
    blob=roster.make_roster_xlsx(profile['class_name'],students)
    out.append({'pdf':blob,'content_type':XLSX,'chat_id':chat,'text':f"{profile['class_name']} sinf ro‘yxati. Tuzatib, shu yerga qayta yuboring.",'day':server.today().isoformat(),'filename':'Royxat-'+profile['class_name']+'.xlsx'})

def _bind_deputy_chat(c,profile,chat):
    chat=str(chat)
    admins=list(c.execute("SELECT id FROM users WHERE school_id=? AND role='admin' AND status='active' ORDER BY id",(profile['school_id'],)))
    if not admins:return
    if admins[0]['id']==profile['id']:
        c.execute('UPDATE schools SET telegram_chat_id=? WHERE id=?',(chat,profile['school_id']))
    else:
        c.execute('UPDATE schools SET deputy_chat_2=? WHERE id=?',(chat,profile['school_id']))

def _holiday_message(c,out,chat,profile):
    from datetime import timedelta
    school=c.execute('SELECT saturday_off,sunday_off FROM schools WHERE id=?',(profile['school_id'],)).fetchone()
    today=server.today()
    upcoming=[]
    for offset in range(21):
        current=today+timedelta(days=offset)
        if not server.is_teaching_day(c,profile['school_id'],current.isoformat()):
            upcoming.append(current.strftime('%d.%m.%Y'))
    lines=[
        'Shanba: '+('dam olish' if school['saturday_off'] else 'o‘quv kuni'),
        'Yakshanba: '+('dam olish' if school['sunday_off'] else 'o‘quv kuni'),
        'Yaqin dam kunlari: '+(', '.join(upcoming[:8]) or 'yo‘q'),
        'Bayram kunlarini kalendardan belgilang yoki sanani 08.12.2026 ko‘rinishida yozing.',
    ]
    buttons=[
        [{'text':'Bayram kalendari','callback_data':'ds:cal'}],
        [{'text':'Shanbani almashtirish','callback_data':'ds:sat'},{'text':'Yakshanbani almashtirish','callback_data':'ds:sun'}],
        [{'text':'Bugunni dam qilish','callback_data':'ds:today'}],
    ]
    out.append({'chat_id':chat,'text':'\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}})

def _mark_holiday_text(c,tg,chat,profile,text,out):
    parsed=_parse_day(text)
    if not parsed:
        _say(out,chat,'Sanani 08.12.2026 ko‘rinishida yozing.',CANCEL_KB);return
    row=c.execute('SELECT state FROM bot_chats WHERE telegram_id=?',(tg,)).fetchone()
    if row and row['state']=='adm_cal':
        draft=_calendar_draft(c,tg)
        if draft.get('month') and draft.get('month')!=parsed[:7]:
            _save_calendar_draft(c,profile['school_id'],tg)
            _open_calendar(c,tg,chat,profile,out,parsed[:7])
        _pick_calendar_day(c,tg,chat,profile,parsed,out);return
    _toggle_day(c,profile['school_id'],parsed)
    _touch(c,tg,'adm_off',{},profile['id'])
    _holiday_message(c,out,chat,profile)

def _month_parts(month):
    from calendar import monthrange
    from datetime import date as _date
    if not re.fullmatch(r'\d{4}-\d{2}',month or ''):return None
    year,mon=int(month[:4]),int(month[5:7])
    if not 1<=mon<=12:return None
    return year,mon,monthrange(year,mon)[1],_date

def _calendar_draft(c,tg):
    row=c.execute('SELECT * FROM bot_chats WHERE telegram_id=?',(tg,)).fetchone()
    return _draft(row) if row else {}

def _off_days(c,school_id,month):
    parts=_month_parts(month)
    if not parts:return []
    year,mon,count,day_type=parts
    return [day_type(year,mon,day).isoformat() for day in range(1,count+1) if not server.is_teaching_day(c,school_id,day_type(year,mon,day).isoformat())]

def _calendar_message(out,chat,month,picked):
    parts=_month_parts(month)
    year,mon,_,day_type=parts
    chosen=sorted(picked)
    shown=', '.join(day_type.fromisoformat(item).strftime('%d.%m') for item in chosen) if chosen else 'yo‘q'
    text=f"{MONTHS[mon]} {year}\nDam kunlarini bosing. Bir nechtasini belgilab, «Saqlash» ni bosing.\nTanlangan: {shown}\nDu  Se  Ch  Pa  Ju  Sh  Ya"
    out.append({'chat_id':chat,'text':text,'reply_markup':{'inline_keyboard':_calendar_keyboard(month,picked)}})

def _calendar_keyboard(month,picked):
    parts=_month_parts(month)
    year,mon,count,day_type=parts
    first=day_type(year,mon,1).weekday()
    rows=[]
    week=[{'text':'·','callback_data':'ds:x'} for _ in range(first)]
    for day in range(1,count+1):
        iso=day_type(year,mon,day).isoformat()
        week.append({'text':('•'+str(day)) if iso in picked else str(day),'callback_data':'ds:d:'+iso})
        if len(week)==7:
            rows.append(week);week=[]
    if week:
        week.extend({'text':'·','callback_data':'ds:x'} for _ in range(7-len(week)))
        rows.append(week)
    prev_mon,prev_year=(12,year-1) if mon==1 else (mon-1,year)
    next_mon,next_year=(1,year+1) if mon==12 else (mon+1,year)
    rows.append([
        {'text':'‹','callback_data':f'ds:m:{prev_year:04d}-{prev_mon:02d}'},
        {'text':'Saqlash','callback_data':'ds:save'},
        {'text':'›','callback_data':f'ds:m:{next_year:04d}-{next_mon:02d}'},
    ])
    rows.append([{'text':'Orqaga','callback_data':'ds:back'}])
    return rows

def _open_calendar(c,tg,chat,profile,out,month=None):
    if not month:
        today=server.today();month=f'{today.year:04d}-{today.month:02d}'
    if not _month_parts(month):
        _toast(out,'Oy noto‘g‘ri');return
    picked=_off_days(c,profile['school_id'],month)
    _touch(c,tg,'adm_cal',{'month':month,'picked':picked},profile['id'])
    _calendar_message(out,chat,month,set(picked))

def _pick_calendar_day(c,tg,chat,profile,iso,out):
    from datetime import date as _date
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',iso or ''):
        _toast(out,'Sana noto‘g‘ri');return
    try:_date.fromisoformat(iso)
    except ValueError:
        _toast(out,'Sana noto‘g‘ri');return
    draft=_calendar_draft(c,tg)
    month=draft.get('month') or iso[:7]
    if iso[:7]!=month:
        _toast(out,'Shu oydan kun tanlang');return
    picked=set(draft.get('picked') or [])
    if iso in picked:picked.remove(iso)
    else:picked.add(iso)
    _touch(c,tg,'adm_cal',{'month':month,'picked':sorted(picked)},profile['id'])
    _calendar_message(out,chat,month,picked)

def _save_calendar_draft(c,school_id,tg):
    from datetime import date as _date
    draft=_calendar_draft(c,tg)
    month=draft.get('month') or ''
    parts=_month_parts(month)
    if not parts:return False
    year,mon,count,_=parts
    picked=set(draft.get('picked') or [])
    school=server.school_row(c,school_id)
    for day in range(1,count+1):
        current=_date(year,mon,day)
        iso=current.isoformat()
        desired=iso not in picked
        default=not ((current.weekday()==5 and school.get('saturday_off')) or (current.weekday()==6 and school.get('sunday_off')))
        if desired==default:
            c.execute('DELETE FROM calendar WHERE school_id=? AND day=?',(school_id,iso))
        else:
            teaching=1 if desired else 0
            c.execute('INSERT INTO calendar(school_id,day,teaching) VALUES(?,?,?) ON CONFLICT(school_id,day) DO UPDATE SET teaching=excluded.teaching',(school_id,iso,teaching))
    return True

def _toast(out,text):
    if out and out[0].get('method')=='answerCallbackQuery':out[0]['toast']=text

def _parse_day(text):
    from datetime import date as _date
    raw=(text or '').strip()
    match=re.fullmatch(r'(\d{4})-(\d{2})-(\d{2})',raw) or re.fullmatch(r'(\d{1,2})[./](\d{1,2})[./](\d{4})',raw)
    if not match:return ''
    parts=[int(item) for item in match.groups()]
    try:
        if len(raw)>7 and raw[4]=='-':current=_date(parts[0],parts[1],parts[2])
        else:current=_date(parts[2],parts[1],parts[0])
    except ValueError:return ''
    return current.isoformat()

def _toggle_day(c,school_id,day):
    teaching=0 if server.is_teaching_day(c,school_id,day) else 1
    c.execute('INSERT INTO calendar(school_id,day,teaching) VALUES(?,?,?) ON CONFLICT(school_id,day) DO UPDATE SET teaching=excluded.teaching',(school_id,day,teaching))

def _invite_deputy(c,out,chat,profile):
    admins=list(c.execute("SELECT id,name FROM users WHERE school_id=? AND role='admin' AND status='active' ORDER BY id",(profile['school_id'],)))
    if len(admins)>1:
        if admins[0]['id']!=profile['id']:
            _say(out,chat,'Siz ikkinchi direktor o‘rinbosarisiz. Hisobotlar sizga ham keladi.',_deputy_kb(c,chat));return
        out.append({'chat_id':chat,'text':f"Ikkinchi o‘rinbosar: {admins[1]['name']}",'reply_markup':{'inline_keyboard':[[{'text':'Olib tashlash','callback_data':'d2x'}]]}})
        return
    code=str(secrets.randbelow(900000)+100000)
    c.execute('UPDATE schools SET deputy_invite=? WHERE id=?',(code,profile['school_id']))
    _say(out,chat,f"Ikkinchi o‘rinbosar botda «Ikkinchi o‘rinbosar» ni bosib shu kodni yozsin:\n{code}\nKod bir marta ishlaydi.",_deputy_kb(c,chat))

def _join_deputy(c,tg,chat,text,out):
    code=re.sub(r'\D','',text)
    school=c.execute('SELECT * FROM schools WHERE deputy_invite=?',(code,)).fetchone() if len(code)==6 else None
    if not school:
        _say(out,chat,'Kod topilmadi. Birinchi direktor o‘rinbosaridan yangi kod so‘rang.',CANCEL_KB);return
    if not server.school_access(c,school['id'])['open']:
        _say(out,chat,'Bu maktabning obunasi tugagan. To‘lov tasdiqlangach kod ishlaydi.',ROLE_KB);return
    login='tg'+tg
    existing=c.execute('SELECT id,role,status,school_id FROM users WHERE login=?',(login,)).fetchone()
    if existing and not (existing['school_id']==school['id'] and existing['role']=='admin'):
        _say(out,chat,'Bu Telegram boshqa vazifada yozilgan. Boshqa telefondan kiring.',CANCEL_KB);return
    if existing:
        user_id=existing['id']
        c.execute("UPDATE users SET role='admin',status='active' WHERE id=?",(user_id,))
    else:
        c.execute("INSERT INTO users(district_id,school_id,login,password,role,name,status) VALUES(?,?,?,?,'admin',?,'active')",(school['district_id'],school['id'],login,server.password_hash(secrets.token_hex(16)),'Ikkinchi o‘rinbosar'))
        user_id=c.execute('SELECT id FROM users WHERE school_id=? AND login=?',(school['id'],login)).fetchone()['id']
    c.execute("UPDATE schools SET deputy_chat_2=?,deputy_invite='' WHERE id=?",(str(chat),school['id']))
    _touch(c,tg,'',{},user_id)
    profile=_profile(c,{'user_id':user_id})
    _say(out,chat,'Ikkinchi direktor o‘rinbosari sifatida kirdingiz. Hisobotlar sizga ham keladi.\n'+_deputy_text(profile),_deputy_kb(c,chat))

def _school_teacher(c,profile,uid):
    if not str(uid).isdigit():return None
    row=c.execute('''SELECT u.id,u.name,cl.id AS class_id,cl.name AS class_name
        FROM users u LEFT JOIN classes cl ON cl.teacher=u.id AND cl.school_id=u.school_id
        WHERE u.id=? AND u.school_id=? AND u.role='teacher' AND u.status='active' ''',(int(uid),profile['school_id'])).fetchone()
    return dict(row) if row else None

def _staff_message(c,out,chat,profile):
    rows=list(c.execute('''SELECT u.id,u.name,cl.name AS class_name
        FROM users u LEFT JOIN classes cl ON cl.teacher=u.id AND cl.school_id=u.school_id
        WHERE u.school_id=? AND u.role='teacher' AND u.status='active'
        ORDER BY cl.name,u.name''',(profile['school_id'],)))
    if not rows:
        _say(out,chat,'Hali sinf rahbari yo‘q. O‘qituvchilar kodini yuboring.',_deputy_kb(c,chat));return
    lines=[];buttons=[]
    for index,row in enumerate(rows,1):
        label=f"{row['class_name'] or '—'} — {row['name']}"
        lines.append(f"{index}. {label}")
        buttons.append([{'text':label[:40],'callback_data':'tc:'+str(row['id'])}])
    out.append({'chat_id':chat,'text':'Sinf rahbarini tanlang:\n'+'\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}})

def _teacher_card(out,chat,teacher,note=''):
    text=f"{teacher['name']}\nSinf: {teacher['class_name'] or '—'}"
    if note:text+='\n'+note
    uid=str(teacher['id'])
    buttons=[
        [{'text':'Ism-familiya','callback_data':'tn:'+uid}],
        [{'text':'Sinf','callback_data':'tk:'+uid}],
        [{'text':'Olib tashlash','callback_data':'tx:'+uid}],
        [{'text':'Ro‘yxatga qaytish','callback_data':'tl'}],
    ]
    out.append({'chat_id':chat,'text':text,'reply_markup':{'inline_keyboard':buttons}})

def _admin_edit_text(c,tg,chat,profile,state,draft,text,out):
    teacher=_school_teacher(c,profile,draft.get('id'))
    if not teacher:
        _touch(c,tg,'',{},profile['id'])
        _say(out,chat,'Sinf rahbari topilmadi.',_deputy_kb(c,chat));return
    if state=='adm_name':
        name=clean_name(text)
        if not name:
            _say(out,chat,'Familiya va ismni yozing. Masalan: Karimova Dilnoza',CANCEL_KB);return
        c.execute("UPDATE users SET name=? WHERE id=? AND school_id=? AND role='teacher' AND status='active'",(name,teacher['id'],profile['school_id']))
        teacher['name']=name
    else:
        class_name=normalize_class(text)
        if not class_name:
            _say(out,chat,'Sinfni 7B ko‘rinishida yozing.',CANCEL_KB);return
        if teacher['class_name']!=class_name:
            target=c.execute('SELECT id,teacher FROM classes WHERE school_id=? AND name=?',(profile['school_id'],class_name)).fetchone()
            if target and target['teacher'] and int(target['teacher'])!=int(teacher['id']):
                _say(out,chat,'Bu sinfning sinf rahbari allaqachon bor.',CANCEL_KB);return
            note=''
            if target:
                if teacher['class_id']:
                    left=c.execute('SELECT count(*) FROM students WHERE class_id=? AND active=1',(teacher['class_id'],)).fetchone()[0]
                    if left:note='O‘quvchilar avvalgi sinfda qoldi.'
                    c.execute('UPDATE classes SET teacher=NULL WHERE id=? AND school_id=?',(teacher['class_id'],profile['school_id']))
                c.execute('UPDATE classes SET teacher=? WHERE id=? AND school_id=?',(teacher['id'],target['id'],profile['school_id']))
                teacher['class_id']=target['id']
            elif teacher['class_id']:
                c.execute('UPDATE classes SET name=? WHERE id=? AND school_id=?',(class_name,teacher['class_id'],profile['school_id']))
            else:
                c.execute('INSERT INTO classes(school_id,name,teacher) VALUES(?,?,?)',(profile['school_id'],class_name,teacher['id']))
                teacher['class_id']=c.execute('SELECT id FROM classes WHERE school_id=? AND name=?',(profile['school_id'],class_name)).fetchone()['id']
            teacher['class_name']=class_name
            _touch(c,tg,'',{},profile['id'])
            _teacher_card(out,chat,teacher,note);return
    _touch(c,tg,'',{},profile['id'])
    _teacher_card(out,chat,teacher)

def _student_callback(c,tg,chat,profile,data,out):
    if data.startswith('sj:'):
        parts=data.split(':')
        if len(parts)!=3 or parts[2] not in ('M','F'):
            out[0]['toast']='Jins noto‘g‘ri';return
        student=_own_student(c,profile,parts[1])
        if not student:
            out[0]['toast']='O‘quvchi topilmadi';return
        c.execute('UPDATE students SET gender=? WHERE id=? AND class_id=?',(parts[2],student['id'],profile['class_id']))
        student['gender']=parts[2]
        out[0]['toast']='Jinsi yangilandi'
        _student_card(out,chat,student);return
    kind,sid=data.split(':',1)
    student=_own_student(c,profile,sid)
    if not student:
        out[0]['toast']='O‘quvchi topilmadi';return
    if kind=='ed':
        _student_card(out,chat,student);return
    if kind=='sm':
        _touch(c,tg,'stu_move',{'id':student['id']},profile['id'])
        _say(out,chat,f"{student['name']} qaysi sinfga o‘tadi? Masalan: 8B",CANCEL_KB);return
    if kind=='sg':
        out.append({'chat_id':chat,'text':student['name']+'\nJinsini tanlang.','reply_markup':{'inline_keyboard':[[{'text':BOY,'callback_data':'sj:'+sid+':M'},{'text':GIRL,'callback_data':'sj:'+sid+':F'}]]}})
        return
    field='stu_rename' if kind=='sn' else 'stu_addr'
    _touch(c,tg,field,{'id':student['id']},profile['id'])
    if kind=='sn':
        _say(out,chat,f"Hozirgi ism: {student['name']}\nYangi familiya va ismni yozing.",CANCEL_KB)
    else:
        _say(out,chat,f"Hozirgi manzil: {student['address'] or '—'}\nYangi manzilni yozing. O‘chirish uchun «O‘tkazib yuborish».",ADDRESS_KB)

def _admin_teacher_callback(c,tg,chat,profile,data,out):
    if data.startswith('ty:'):
        teacher=_school_teacher(c,profile,data.split(':',1)[1])
        if not teacher:
            out[0]['toast']='Sinf rahbari topilmadi';return
        c.execute('UPDATE classes SET teacher=NULL WHERE teacher=? AND school_id=?',(teacher['id'],profile['school_id']))
        c.execute("UPDATE users SET status='removed' WHERE id=? AND school_id=? AND role='teacher'",(teacher['id'],profile['school_id']))
        out[0]['toast']='Olib tashlandi'
        _staff_message(c,out,chat,profile);return
    kind,uid=data.split(':',1)
    teacher=_school_teacher(c,profile,uid)
    if not teacher:
        out[0]['toast']='Sinf rahbari topilmadi';return
    if kind=='tc':
        _teacher_card(out,chat,teacher);return
    if kind=='tx':
        out.append({'chat_id':chat,'text':f"{teacher['name']} ni olib tashlaysizmi? Sinf va o‘quvchilar qoladi.",'reply_markup':{'inline_keyboard':[[{'text':'Ha, olib tashlash','callback_data':'ty:'+uid}],[{'text':'Bekor','callback_data':'tc:'+uid}]]}})
        return
    field='adm_name' if kind=='tn' else 'adm_class'
    _touch(c,tg,field,{'id':teacher['id']},profile['id'])
    if kind=='tn':
        _say(out,chat,f"Hozirgi ism: {teacher['name']}\nYangi familiya va ismni yozing.",CANCEL_KB)
    else:
        _say(out,chat,f"Hozirgi sinf: {teacher['class_name'] or '—'}\nYangi sinfni yozing. Masalan: 8A",CANCEL_KB)

def _open_attendance(c,tg,chat,profile,out):
    if not profile.get('class_id'):
        _say(out,chat,'Avval sinfni kiriting.',TEACHER_KB);return
    if not server.is_teaching_day(c,profile['school_id'],server.today().isoformat()):
        _say(out,chat,'Bugun dam olish kuni. Davomat so‘ralmaydi.',TEACHER_KB);return
    pupils=list(c.execute('SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY name',(profile['class_id'],)))
    if not pupils:
        _say(out,chat,'Avval o‘quvchilarni kiriting.',TEACHER_KB);return
    day=server.today().isoformat()
    old=c.execute('SELECT payload FROM reports WHERE school_id=? AND day=? AND class_id=?',(profile['school_id'],day,profile['class_id'])).fetchone()
    marks={}
    if old:
        for entry in json.loads(old['payload']):marks[str(entry['id'])]=int(entry.get('status') or 0)
    _touch(c,tg,'att',{'marks':marks},profile['id'])
    _attendance_message(out,chat,profile,pupils,marks)

def _attendance_message(out,chat,profile,pupils,marks):
    lines=[]
    buttons=[]
    for index,pupil in enumerate(pupils,1):
        status=int(marks.get(str(pupil['id']),0) or 0)
        if status not in range(len(REASONS)):status=0
        label=EXCEL_LABELS[status]
        lines.append(f"{index}. {pupil['name']} — {label}")
        buttons.append([{'text':('✗ ' if status else '✓ ')+pupil['name'][:40],'callback_data':'who:'+str(pupil['id'])}])
    buttons.append([{'text':'Davomatni jo‘natish','callback_data':'go'}])
    text=f"{profile['class_name']} — bugungi davomat\nKelmagan o‘quvchini bosing va sababini tanlang. Qolganlar kelgan hisoblanadi.\n\n"+'\n'.join(lines)
    out.append({'chat_id':chat,'text':text[:4096],'reply_markup':{'inline_keyboard':buttons}})

def _ask_month(out,chat):
    day=server.today()
    year,month=day.year,day.month
    rows=[]
    for _ in range(4):
        key=f'{year:04d}-{month:02d}'
        rows.append([{'text':f'{MONTHS[month]} {year}','callback_data':'mo:'+key}])
        month-=1
        if month==0:
            month=12
            year-=1
    _say(out,chat,'Qaysi oyning hisobotini yuklaysiz?',{'inline_keyboard':rows})

def _send_span(c,out,profile,chat,scope,period,offer_previous=False):
    school=c.execute('SELECT * FROM schools WHERE id=?',(profile['school_id'],)).fetchone()
    info=server.school_settings(c,profile['school_id'])
    if scope=='month':
        rows=server.monthly_summary(c,period,profile['school_id'])['rows']
        filename='Davomat-'+school['code']+'-'+period+'.xlsx'
        caption=f"{school['name']} | {period} | Oylik jadval"
        key=period
    else:
        start_year=int(period)
        rows=server.range_summary(c,profile['school_id'],f'{start_year}-09-01',f'{start_year+1}-08-31')
        filename=f"Davomat-{school['code']}-{start_year}-{start_year+1}.xlsx"
        caption=f"{school['name']} | {start_year}–{start_year+1}-o‘quv yili"
        key=str(start_year)
    if offer_previous:
        _say(out,chat,caption,{'inline_keyboard':[[{'text':'O‘tgan o‘quv yili','callback_data':'yr:'+str(int(period)-1)}]]})
    if not any(row.get('submitted') for row in rows):
        _say(out,chat,'Bu davrda hali davomat yo‘q.',_deputy_kb(c,chat));return
    blob=make_summary_xlsx(rows,key,info,scope=scope)
    text=caption+' | '+str(sum(1 for row in rows if row.get('submitted')))+' ta sinf-kun'
    _send_school_file(out,school,blob,filename,text,key,chat)
    if scope=='month':
        people=server.chronic_students(rows)
        chronic=make_chronic_xlsx(people,key,info)
        _send_school_file(out,school,chronic,'Surunkali-'+school['code']+'-'+key+'.xlsx',caption+' | 3 kundan ko‘p kelmaganlar',key,chat)

def _on_callback(c,row,chat,tg,data,out):
    if data.startswith(('payok:','payno:','paysee:')):
        _payment_callback(c,chat,tg,data,out);return
    if data.startswith('ad:'):
        if not server.is_platform_admin(c,tg):
            out[0]['toast']='Ruxsat yo‘q';return
        _owner_callback(c,row,chat,tg,data,out);return
    profile=_profile(c,row)
    if not profile:
        out[0]['toast']='Avval /start ni bosing';return
    if not server.school_access(c,profile['school_id'])['open']:
        out[0]['toast']='Obuna tugagan'
        _say(out,chat,server.payment_text(server.school_access(c,profile['school_id'])));return
    if profile['role']=='admin' and data.startswith('mo:'):
        month=data.split(':',1)[1]
        try:server.month_value(month)
        except server.ApiError:
            out[0]['toast']='Oy noto‘g‘ri';return
        _send_span(c,out,profile,chat,'month',month);return
    if profile['role']=='admin' and data.startswith('yr:'):
        year=data.split(':',1)[1]
        if not re.fullmatch(r'\d{4}',year):
            out[0]['toast']='Yil noto‘g‘ri';return
        _send_span(c,out,profile,chat,'year',year);return
    if profile['role']=='admin' and data=='tl':
        _staff_message(c,out,chat,profile);return
    if profile['role']=='admin' and data.startswith(('tc:','tn:','tk:','tx:','ty:')):
        _admin_teacher_callback(c,tg,chat,profile,data,out);return
    if profile['role']=='teacher' and data=='ls':
        _touch(c,tg,'',{},profile['id'])
        _students_message(c,out,chat,profile);return
    if profile['role']=='teacher' and data.startswith(('ed:','sn:','sg:','sa:','sj:','sm:')):
        _student_callback(c,tg,chat,profile,data,out);return
    if profile['role']=='admin' and data=='d2x':
        _remove_second_deputy(c,out,chat,profile);return
    if profile['role']=='admin' and data.startswith('ds:'):
        _holiday_callback(c,tg,chat,profile,data,out);return
    state=row['state'] or ''
    draft=_draft(row)
    if data in ('g:M','g:F') and state=='stu_gender' and profile['role']=='teacher':
        _ask_address(c,tg,chat,draft,'M' if data.endswith('M') else 'F',profile,out);return
    if data.startswith('del:') and profile['role']=='teacher' and profile.get('class_id'):
        sid=data.split(':',1)[1]
        if sid.isdigit() and c.execute('SELECT id FROM students WHERE id=? AND class_id=? AND active=1',(int(sid),profile['class_id'])).fetchone():
            c.execute('UPDATE students SET active=0 WHERE id=?',(int(sid),))
            out[0]['toast']='O‘chirildi'
        _students_message(c,out,chat,profile);return
    if profile['role']!='teacher' or state!='att' or not profile.get('class_id'):
        out[0]['toast']='Davomat oynasini qayta oching';return
    pupils=list(c.execute('SELECT * FROM students WHERE class_id=? AND active=1 ORDER BY name',(profile['class_id'],)))
    marks=draft.get('marks') if isinstance(draft.get('marks'),dict) else {}
    if data.startswith('who:'):
        sid=data.split(':',1)[1]
        pupil=next((item for item in pupils if str(item['id'])==sid),None)
        if not pupil:
            out[0]['toast']='O‘quvchi topilmadi';return
        rows=[[{'text':EXCEL_LABELS[index][:40],'callback_data':f'why:{sid}:{index}'}] for index in range(len(REASONS))]
        out.append({'chat_id':chat,'text':pupil['name']+'\nSababini tanlang.','reply_markup':{'inline_keyboard':rows}})
        return
    if data.startswith('why:'):
        parts=data.split(':')
        if len(parts)!=3 or not parts[1].isdigit() or not parts[2].isdigit():return
        status=int(parts[2])
        if status not in range(len(REASONS)):return
        marks[parts[1]]=status
        draft['marks']=marks
        _touch(c,tg,'att',draft,profile['id'])
        out[0]['toast']=EXCEL_LABELS[status][:180]
        _attendance_message(out,chat,profile,pupils,marks);return
    if data=='go':
        _submit(c,tg,chat,profile,pupils,marks,out);return
    out[0]['toast']='Tugma eskirgan'

def _submit(c,tg,chat,profile,pupils,marks,out):
    if not pupils:
        _say(out,chat,'Avval o‘quvchilarni kiriting.',TEACHER_KB);return
    day=server.today().isoformat()
    if not server.is_teaching_day(c,profile['school_id'],day):
        _say(out,chat,'Bugun dam olish kuni. Davomat so‘ralmaydi.',TEACHER_KB);return
    saved=[];absent=0
    for pupil in pupils:
        status=int(marks.get(str(pupil['id']),0) or 0)
        if status not in range(len(REASONS)):status=0
        if status:absent+=1
        item={key:pupil[key] for key in ('id','class_id','name','gender','address','active')}
        item['status']=status;item['note']=''
        saved.append(item)
    payload=json.dumps(saved,ensure_ascii=False)
    old=c.execute('SELECT * FROM reports WHERE school_id=? AND day=? AND class_id=?',(profile['school_id'],day,profile['class_id'])).fetchone()
    if old and old['locked']:
        _say(out,chat,'Bu kun hisoboti yopilgan.',TEACHER_KB);return
    if old and old['payload']==payload:
        _touch(c,tg,'',{},profile['id'])
        _say(out,chat,'Bu davomat allaqachon yuborilgan.',TEACHER_KB);return
    revision=(old['revision'] if old else 0)+1
    c.execute('INSERT INTO reports(school_id,day,class_id,revision,payload,updated) VALUES(?,?,?,?,?,?) ON CONFLICT(day,class_id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,updated=excluded.updated,school_id=excluded.school_id',(profile['school_id'],day,profile['class_id'],revision,payload,time.time()))
    c.execute('INSERT INTO audit(day,class_id,user_id,payload,created) VALUES(?,?,?,?,?)',(day,profile['class_id'],profile['id'],payload,time.time()))
    _touch(c,tg,'',{},profile['id'])
    _say(out,chat,f"Davomat saqlandi. Kelmagan: {absent} ta, jami: {len(pupils)} ta.\nJamlanma soat 11:00 da direktor o‘rinbosariga yuboriladi.",TEACHER_KB)

def _status_text(c,profile):
    day=server.today().isoformat()
    rows=server.summary(c,day,profile['school_id'])
    if not rows:return 'Hali sinf rahbari ro‘yxatdan o‘tmagan.'
    lines=[day]
    for row in rows:
        if row['submitted']:
            absent=sum(row['counts'][1:])
            lines.append(f"{row['class']} — {row['teacher_name'] or '—'} — jo‘natdi, kelmagan {absent}")
        else:
            lines.append(f"{row['class']} — {row['teacher_name'] or '—'} — jo‘natmadi")
    return '\n'.join(lines)

def _send_compiled(c,out,profile,notify_chat,caption):
    school=c.execute('SELECT * FROM schools WHERE id=?',(profile['school_id'],)).fetchone()
    rows=server.summary(c,server.today().isoformat(),profile['school_id'])
    if not rows:
        _say(out,notify_chat,'Hali sinf rahbari ro‘yxatdan o‘tmagan.');return
    day=server.today().isoformat()
    blob=make_summary_xlsx(rows,day,server.school_settings(c,profile['school_id']))
    submitted=sum(1 for row in rows if row['submitted'])
    missing=[row['class'] for row in rows if not row.get('submitted')]
    text=caption+' | 1-jadval '+str(submitted)+'/'+str(len(rows))+' sinf'
    if missing:text+=' | jo‘natmagan: '+', '.join(missing)
    _send_school_file(out,school,blob,'Davomat-'+school['code']+'-'+day+'.xlsx',text,day,notify_chat)

def _send_school_file(out,school,blob,filename,text,day,notify_chat):
    chats=server.deputy_chats(school)
    if not chats:
        _say(out,notify_chat,'Direktor o‘rinbosari chati yo‘q.');return
    for chat_id in chats:
        out.append({'pdf':blob,'content_type':XLSX,'chat_id':chat_id,'notify_chat':notify_chat,'text':text[:1000],'day':day,'filename':filename})

def _holiday_callback(c,tg,chat,profile,data,out):
    action=data.split(':',1)[1]
    if action=='x':return
    if action=='cal':
        _open_calendar(c,tg,chat,profile,out);return
    if action=='back':
        _save_calendar_draft(c,profile['school_id'],tg)
        _touch(c,tg,'adm_off',{},profile['id'])
        _holiday_message(c,out,chat,profile);return
    if action=='save':
        if _save_calendar_draft(c,profile['school_id'],tg):_toast(out,'Saqlandi')
        draft=_calendar_draft(c,tg)
        _open_calendar(c,tg,chat,profile,out,draft.get('month'));return
    if action.startswith('m:'):
        _save_calendar_draft(c,profile['school_id'],tg)
        _open_calendar(c,tg,chat,profile,out,action[2:]);return
    if action.startswith('d:'):
        _pick_calendar_day(c,tg,chat,profile,action[2:],out);return
    if action=='sat':
        c.execute('UPDATE schools SET saturday_off=CASE saturday_off WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(profile['school_id'],))
    elif action=='sun':
        c.execute('UPDATE schools SET sunday_off=CASE sunday_off WHEN 1 THEN 0 ELSE 1 END WHERE id=?',(profile['school_id'],))
    elif action=='today':
        _toggle_day(c,profile['school_id'],server.today().isoformat())
    _touch(c,tg,'adm_off',{},profile['id'])
    _holiday_message(c,out,chat,profile)

def _remove_second_deputy(c,out,chat,profile):
    admins=list(c.execute("SELECT id FROM users WHERE school_id=? AND role='admin' AND status='active' ORDER BY id",(profile['school_id'],)))
    if len(admins)<2 or admins[0]['id']!=profile['id']:
        out[0]['toast']='Ruxsat yo‘q';return
    c.execute("UPDATE users SET status='removed' WHERE id=? AND school_id=?",(admins[1]['id'],profile['school_id']))
    c.execute("UPDATE schools SET deputy_chat_2='',deputy_invite='' WHERE id=?",(profile['school_id'],))
    out[0]['toast']='Olib tashlandi'
    _say(out,chat,'Ikkinchi direktor o‘rinbosari olib tashlandi.',_deputy_kb(c,chat))

def poll():
    server.init()
    offset=0
    while True:
        try:
            updates=api('getUpdates',{'timeout':25,'offset':offset,'allowed_updates':['message','callback_query']},timeout=45) or []
        except KeyboardInterrupt:
            return
        except Exception:
            LOG.exception('getUpdates')
            time.sleep(3);continue
        for update in updates:
            offset=int(update['update_id'])+1
            try:process(update)
            except Exception:LOG.exception('update %s',update.get('update_id'))

if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    print('Telegram bot kutmoqda. Render webhook yoqilgan bo‘lsa, shu jarayonni ishga tushirmang.')
    poll()
