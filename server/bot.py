"""Telegram bot: teacher registration, class roster, daily attendance, deputy PDF."""
import hashlib, hmac, json, logging, os, re, secrets, time
from urllib.request import Request, urlopen
import database, server
from catalog import REASONS

LOG=logging.getLogger('maktab-hisobot.bot')
DEPUTY='Direktor o‘rinbosari'
TEACHER='Sinf rahbari'
ADD='O‘quvchi qo‘shish'
LIST='O‘quvchilar'
ATT='Bugungi davomat'
PDF_BTN='Bugungi PDF'
STATUS='Sinflar holati'
CODE_BTN='Maktab kodi'
CANCEL='Bekor qilish'
DONE='Tayyor'
SKIP='O‘tkazib yuborish'
BOY='O‘g‘il'
GIRL='Qiz'
LABELS=(DEPUTY,TEACHER,ADD,LIST,ATT,PDF_BTN,STATUS,CODE_BTN,CANCEL,DONE,SKIP,BOY,GIRL)

def norm(value):
    text=(value or '').strip().lower()
    text=text.translate(str.maketrans({'ʻ':"'",'ʼ':"'",'‘':"'",'’':"'",'`':"'"}))
    text=text.replace("'",'')
    return ' '.join(text.split())

def same(value,label):
    return norm(value)==norm(label)

def command_name(value):
    token=(value or '').strip().split(' ',1)[0].lower()
    return token.split('@',1)[0]

def keyboard(*rows):
    return {'keyboard':[[{'text':item} for item in row] for row in rows],'resize_keyboard':True}

ROLE_KB=keyboard([DEPUTY],[TEACHER])
TEACHER_KB=keyboard([ADD],[LIST,ATT])
DEPUTY_KB=keyboard([PDF_BTN],[STATUS,CODE_BTN])
CANCEL_KB=keyboard([CANCEL])
WIZARD_KB=keyboard([DONE],[CANCEL])
ADDRESS_KB=keyboard([SKIP],[CANCEL])

def clean_name(value):
    text=' '.join((value or '').split())
    if not 2<=len(text)<=40 or norm(text) in {norm(item) for item in LABELS}:return ''
    if not re.search(r'[^\W\d_]',text,re.UNICODE):return ''
    return text

def clean_school(value):
    text=' '.join((value or '').split())
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
                server.send_document(item['pdf'],item.get('day') or '',chat=item['chat_id'],caption=item.get('text') or '',filename=item.get('filename'))
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
                try:api('sendMessage',{'chat_id':item['notify_chat'],'text':'Davomat saqlandi, lekin PDF hozir yuborilmadi. Direktor o‘rinbosari «Bugungi PDF» tugmasini bosing.'})
                except Exception:LOG.exception('PDF xatosi haqida xabar yuborilmadi')

def process(update):
    deliver(handle_update(update))

def handle_update(update):
    if not isinstance(update,dict):return []
    with server.connect() as c:
        return _handle(c,update)

def _handle(c,update):
    uid=update.get('update_id')
    if uid is not None:
        if c.execute('SELECT 1 FROM bot_updates WHERE update_id=?',(uid,)).fetchone():return []
        if int(uid)%100==0:c.execute('DELETE FROM bot_updates WHERE created<?',(time.time()-7*86400,))
        c.execute('INSERT INTO bot_updates(update_id,created) VALUES(?,?)',(int(uid),time.time()))
    chat,user,text,callback=_parts(update)
    if not chat or chat.get('type')!='private' or not user or not user.get('id'):return []
    tg=str(user['id']);chat_id=chat['id'];out=[]
    row=_ensure(c,tg)
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
        return msg.get('chat') or {},cq.get('from') or {},None,cq
    msg=update.get('message') or {}
    return msg.get('chat') or {},msg.get('from') or {},msg.get('text'),None

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
    found=c.execute('''SELECT u.id,u.role,u.name,u.school_id,s.name AS school_name,s.join_code,s.code AS school_code,s.telegram_chat_id,
        cl.id AS class_id,cl.name AS class_name
        FROM users u JOIN schools s ON s.id=u.school_id
        LEFT JOIN classes cl ON cl.teacher=u.id AND cl.school_id=u.school_id
        WHERE u.id=?''',(row['user_id'],)).fetchone()
    return dict(found) if found else None

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
        _say(out,chat,'Maktab Hisobot.\n\nDirektor o‘rinbosari maktabni ochadi va o‘qituvchilarga kod beradi.\nSinf rahbari shu kod bilan kirib, sinf ro‘yxatini va har kunlik davomatni yuboradi.',ROLE_KB)
        return
    if profile['role']=='teacher' and not profile['class_id']:
        _touch(c,tg,'fix_class',{},profile['id'])
        _say(out,chat,'Qaysi sinfga sinf rahbarisiz? Masalan: 7B',CANCEL_KB)
        return
    if profile['role']=='admin' and str(profile.get('telegram_chat_id') or '')!=str(chat):
        c.execute('UPDATE schools SET telegram_chat_id=? WHERE id=?',(str(chat),profile['school_id']))
        profile['telegram_chat_id']=str(chat)
    _touch(c,tg,'',{},profile['id'])
    if profile['role']=='admin':
        _say(out,chat,_deputy_text(profile),DEPUTY_KB)
    else:
        count=c.execute('SELECT count(*) FROM students WHERE class_id=? AND active=1',(profile['class_id'],)).fetchone()[0]
        _say(out,chat,f"{profile['school_name']}\n{profile['class_name']} sinf rahbari: {profile['name']}\nO‘quvchilar: {count}",TEACHER_KB)

def _deputy_text(profile):
    return f"{profile['school_name']}\nO‘qituvchilar kodi: {profile['join_code']}\n\nSinf rahbarlari botda «Sinf rahbari» ni tanlab shu kodni yozadi. Har bir jo‘natilgan davomat jamlanib sizga PDF bo‘lib keladi."

def _on_text(c,row,chat,tg,text,out):
    profile=_profile(c,row)
    cmd=command_name(text)
    if cmd in ('/start','/menu','/help'):
        _home(c,tg,chat,out,profile);return
    if same(text,CANCEL) or cmd=='/cancel':
        _home(c,tg,chat,out,profile);return
    if profile and profile['role']=='admin' and (cmd=='/kod' or same(text,CODE_BTN)):
        _say(out,chat,f"O‘qituvchilar kodi: {profile['join_code']}",DEPUTY_KB);return
    if profile and profile['role']=='admin' and (cmd=='/holat' or same(text,STATUS)):
        _say(out,chat,_status_text(c,profile),DEPUTY_KB);return
    if profile and profile['role']=='admin' and (cmd=='/pdf' or same(text,PDF_BTN)):
        _send_compiled(c,out,profile,chat,f"{profile['school_name']} | bugungi jamlanma");return
    if profile and _teacher_menu(c,row,profile,chat,tg,text,out):return
    state=row['state'] or ''
    draft=_draft(row)
    if not profile:
        _register(c,tg,chat,state,draft,text,out);return
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
        _students_message(c,out,chat,profile);return True
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
        _create_deputy(c,tg,chat,draft,school_name,out);return
    if state=='tch_code':
        code=re.sub(r'\D','',text)
        school=c.execute('SELECT * FROM schools WHERE join_code=?',(code,)).fetchone() if len(code)==6 else None
        if not school:
            _say(out,chat,'Kod topilmadi. Direktor o‘rinbosaridan 6 xonali kodni so‘rang.',CANCEL_KB);return
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
    _touch(c,tg,'role',{},None)
    _say(out,chat,'Tugmani bosing.',ROLE_KB)

def _full_name(draft):
    return (draft.get('last','')+' '+draft.get('first','')).strip()

def _create_deputy(c,tg,chat,draft,school_name,out):
    full=_full_name(draft)
    did=_district_id(c)
    join_code='';school_code=''
    for _ in range(30):
        join_code=str(secrets.randbelow(900000)+100000)
        school_code='TG-'+join_code
        if not server.code_taken(c,school_code) and not c.execute('SELECT 1 FROM schools WHERE join_code=?',(join_code,)).fetchone():break
    else:
        _say(out,chat,'Kod yaratilmadi. Qayta urinib ko‘ring.',CANCEL_KB);return
    c.execute('INSERT INTO schools(district_id,code,name,director,executor,telegram_chat_id,join_code) VALUES(?,?,?,?,?,?,?)',(did,school_code,school_name,full,full,str(chat),join_code))
    school_id=c.execute('SELECT id FROM schools WHERE code=?',(school_code,)).fetchone()['id']
    login='tg'+tg
    c.execute("INSERT INTO users(district_id,school_id,login,password,role,name,status) VALUES(?,?,?,?,'admin',?,'active')",(did,school_id,login,server.password_hash(secrets.token_hex(16)),full))
    user_id=c.execute('SELECT id FROM users WHERE school_id=? AND login=?',(school_id,login)).fetchone()['id']
    _touch(c,tg,'',{},user_id)
    profile=_profile(c,{'user_id':user_id})
    _say(out,chat,'Maktab ochildi.\n'+_deputy_text(profile),DEPUTY_KB)

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
    _say(out,chat,f"Ro‘yxatdan o‘tdingiz.\n{profile['school_name']}, {profile['class_name']} sinf.\nEndi o‘quvchilar ro‘yxatini kiriting.",TEACHER_KB)

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
    if len(address)>300:
        _say(out,chat,'Manzil juda uzun. Qisqaroq yozing.',ADDRESS_KB);return
    c.execute('INSERT INTO students(class_id,name,gender,address,active) VALUES(?,?,?,?,1)',(profile['class_id'],name,gender,address))
    _touch(c,tg,'stu_name',{},profile['id'])
    _say(out,chat,f"Qo‘shildi: {name}\nKeyingi o‘quvchini yozing yoki «Tayyor» ni bosing.",WIZARD_KB)

def _students_message(c,out,chat,profile):
    rows=list(c.execute('SELECT id,name,gender FROM students WHERE class_id=? AND active=1 ORDER BY name',(profile['class_id'],)))
    if not rows:
        _say(out,chat,'Hali o‘quvchi yo‘q. «O‘quvchi qo‘shish» ni bosing.',TEACHER_KB);return
    lines=[f"{index}. {row['name']} ({'o‘g‘il' if row['gender']=='M' else 'qiz'})" for index,row in enumerate(rows,1)]
    buttons=[[{'text':'O‘chirish: '+row['name'][:40],'callback_data':'del:'+str(row['id'])}] for row in rows]
    out.append({'chat_id':chat,'text':'O‘quvchilar:\n'+'\n'.join(lines),'reply_markup':{'inline_keyboard':buttons}})

def _open_attendance(c,tg,chat,profile,out):
    if not profile.get('class_id'):
        _say(out,chat,'Avval sinfni kiriting.',TEACHER_KB);return
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
        label=REASONS[status]
        lines.append(f"{index}. {pupil['name']} — {label}")
        buttons.append([{'text':('✗ ' if status else '✓ ')+pupil['name'][:40],'callback_data':'who:'+str(pupil['id'])}])
    buttons.append([{'text':'Davomatni jo‘natish','callback_data':'go'}])
    text=f"{profile['class_name']} — bugungi davomat\nKelmagan o‘quvchini bosing va sababini tanlang. Qolganlar kelgan hisoblanadi.\n\n"+'\n'.join(lines)
    out.append({'chat_id':chat,'text':text[:4096],'reply_markup':{'inline_keyboard':buttons}})

def _on_callback(c,row,chat,tg,data,out):
    profile=_profile(c,row)
    if not profile:
        out[0]['toast']='Avval /start ni bosing';return
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
        rows=[[{'text':REASONS[index][:40],'callback_data':f'why:{sid}:{index}'}] for index in range(len(REASONS))]
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
        out[0]['toast']=REASONS[status][:180]
        _attendance_message(out,chat,profile,pupils,marks);return
    if data=='go':
        _submit(c,tg,chat,profile,pupils,marks,out);return
    out[0]['toast']='Tugma eskirgan'

def _submit(c,tg,chat,profile,pupils,marks,out):
    if not pupils:
        _say(out,chat,'Avval o‘quvchilarni kiriting.',TEACHER_KB);return
    day=server.today().isoformat()
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
    _say(out,chat,f"Davomat saqlandi. Kelmagan: {absent} ta, jami: {len(pupils)} ta.",TEACHER_KB)
    _send_compiled(c,out,profile,chat,f"{profile['school_name']} | {profile['class_name']} | {profile['name']} | kelmagan {absent}/{len(pupils)}")

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
    blob=server.make_pdf(rows,day,server.school_settings(c,profile['school_id']))
    submitted=sum(1 for row in rows if row['submitted'])
    text=caption+' | jamlanma '+str(submitted)+'/'+str(len(rows))+' sinf'
    out.append({'pdf':blob,'chat_id':school['telegram_chat_id'],'notify_chat':notify_chat,'text':text[:1000],'day':day,'filename':'Davomat-'+school['code']+'-'+day+'.pdf'})

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
