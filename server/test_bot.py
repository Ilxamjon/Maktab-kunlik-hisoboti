import io, json, os, re, tempfile, unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch
from openpyxl import Workbook, load_workbook
import server as s
import bot

class BotTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        s.DB=str(Path(self.temp.name)/'test.db')
        s.init()
        self.n=0
    def tearDown(self):self.temp.cleanup()
    def send(self,tg,text):
        self.n+=1
        return bot.handle_update({'update_id':self.n,'message':{'message_id':self.n,'from':{'id':tg},'chat':{'id':tg,'type':'private'},'text':text}})
    def tap(self,tg,data):
        self.n+=1
        return bot.handle_update({'update_id':self.n,'callback_query':{'id':'cb'+str(self.n),'from':{'id':tg},'data':data,'message':{'message_id':1,'chat':{'id':tg,'type':'private'}}}})
    def deputy(self,tg,first,last,school):
        self.send(tg,'/start')
        self.send(tg,bot.DEPUTY)
        self.send(tg,first)
        self.send(tg,last)
        done=self.send(tg,school)
        code=re.search(r'(\d{6})','\n'.join(item.get('text','') for item in done))
        self.assertIsNotNone(code)
        return code.group(1)
    def teacher(self,tg,code,first,last,klass):
        self.send(tg,'/start')
        self.send(tg,bot.TEACHER)
        self.send(tg,code)
        self.send(tg,first)
        self.send(tg,last)
        return self.send(tg,klass)
    def add_student(self,tg,name):
        self.send(tg,bot.ADD)
        self.send(tg,name)
        self.tap(tg,'g:M')
        self.send(tg,bot.SKIP)
    def photo(self,tg):
        self.n+=1
        return bot.handle_update({'update_id':self.n,'message':{'message_id':self.n,'from':{'id':tg},'chat':{'id':tg,'type':'private'},'photo':[{'file_id':'receipt-'+str(tg),'file_unique_id':'u'}]}})

    def test_attendance_pdf_goes_only_to_that_deputy(self):
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.deputy(33,'Bobur','Qodirov','Ikkinchi maktab')
        joined=self.teacher(22,code,'Dilnoza','Karimova','7b')
        self.assertIn('7B',joined[-1]['text'])
        self.add_student(22,'Karimov Jasur')
        self.send(22,bot.ATT)
        with s.connect() as c:
            student=c.execute("SELECT id FROM students WHERE name='Karimov Jasur'").fetchone()['id']
            self.assertEqual(c.execute("SELECT name FROM classes WHERE teacher=(SELECT id FROM users WHERE login='tg22')").fetchone()['name'],'7B')
        self.tap(22,'who:'+str(student))
        self.tap(22,'why:'+str(student)+':1')
        sent=self.tap(22,'go')
        self.assertFalse(any(item.get('pdf') is not None for item in sent))
        self.assertIn('11:00',sent[-1]['text'])
        noon=datetime.combine(s.today(),datetime.min.time()).replace(hour=11,tzinfo=s.TZ)
        self.assertEqual(s.maybe_noon_digests(noon),1)
        with s.connect() as c:
            queued=list(c.execute('SELECT school_id,pdf FROM outbox'))
        self.assertEqual(len(queued),1)
        with s.connect() as c:
            self.assertEqual(c.execute('SELECT telegram_chat_id FROM schools WHERE id=?',(queued[0]['school_id'],)).fetchone()['telegram_chat_id'],'11')
            self.assertNotEqual(c.execute("SELECT telegram_chat_id FROM schools WHERE name='Ikkinchi maktab'").fetchone()['telegram_chat_id'],'11')
        book=load_workbook(io.BytesIO(queued[0]['pdf']))
        sheet=book.worksheets[0]
        detail=book.worksheets[1]
        self.assertEqual(sheet['A1'].font.name,'Times New Roman')
        self.assertEqual(sheet['A1'].font.size,20)
        self.assertEqual(sheet['G4'].alignment.textRotation,90)
        self.assertEqual(sheet['B7'].value,'Birinchi maktab')
        self.assertEqual(sheet['C7'].value,1)
        self.assertEqual(sheet['E7'].value,1)
        self.assertEqual(sheet['F7'].value,1)
        self.assertEqual(sheet['G4'].value,'Kasalligi tufayli')
        self.assertEqual(sheet['G7'].value,1)
        self.assertIn("MA'LUMOT",sheet['A1'].value)
        self.assertIn('holati',sheet['S2'].value)
        values=' '.join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None)
        self.assertNotIn('Ikkinchi',values)
        self.assertNotIn('Jasur',values)
        self.assertIn("F.I.Sh.",detail['B3'].value)
        self.assertEqual(detail['B4'].value,'Karimov Jasur')
        self.assertEqual(detail['E4'].value,'7-B')
        self.assertEqual(detail['G4'].value,1)
        self.assertEqual(detail['I4'].value,1)
        with s.connect() as c:
            payload=json.loads(c.execute('SELECT payload FROM reports').fetchone()['payload'])
        self.assertEqual(payload[0]['status'],1)
        self.assertEqual(payload[0]['name'],'Karimov Jasur')

    def test_unknown_code_and_taken_class(self):
        code=self.deputy(1,'Ali','Valiyev','18-maktab')
        self.teacher(2,code,'Dilnoza','Karimova','7B')
        self.send(5,'/start');self.send(5,bot.TEACHER)
        missing=self.send(5,'000000')
        self.assertIn('topilmadi',missing[-1]['text'])
        taken=self.teacher(5,code,'Sardor','Azimov','7B')
        self.assertIn('allaqachon',taken[-1]['text'])

    def test_same_update_is_not_applied_twice(self):
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.teacher(22,code,'Dilnoza','Karimova','7B')
        self.send(22,bot.ADD)
        update={'update_id':900,'message':{'message_id':1,'from':{'id':22},'chat':{'id':22,'type':'private'},'text':'Karimov Jasur'}}
        first=bot.handle_update(update)
        second=bot.handle_update(update)
        self.assertTrue(any('Jinsini' in item.get('text','') for item in first))
        self.assertEqual(second,[])
        with s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM students').fetchone()[0],0)

    def test_deliver_targets_deputy_chat(self):
        with patch.object(s,'send_document') as send, patch.object(bot,'api') as api:
            bot.deliver([
                {'chat_id':22,'text':'Davomat saqlandi.'},
                {'pdf':b'%PDF-1.4','chat_id':'11','notify_chat':22,'text':'cap','day':'2026-11-06','filename':'Davomat.pdf'},
            ])
        self.assertEqual(send.call_args.kwargs['chat'],'11')
        self.assertEqual(api.call_args.args[0],'sendMessage')
        self.assertEqual(api.call_args.args[1]['chat_id'],22)

    def test_webhook_rejects_without_secret(self):
        import app
        token='123456789:abcdefghijklmnopqrstuvwxyz0123456789'
        def call(secret):
            raw=b'{"update_id":1}'
            headers=[]
            env={'REQUEST_METHOD':'POST','PATH_INFO':'/telegram/webhook','QUERY_STRING':'','CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'REMOTE_ADDR':'127.0.0.1','HTTP_X_TELEGRAM_BOT_API_SECRET_TOKEN':secret}
            body=b''.join(app.application(env,lambda status,h:headers.extend([status,h])))
            return headers[0],body
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':token}), patch.object(bot,'process') as process:
            self.assertTrue(call('wrong')[0].startswith('403'))
            process.assert_not_called()
            status,body=call(bot.webhook_secret())
        self.assertTrue(status.startswith('200'))
        self.assertIn(b'"ok"',body)
        process.assert_called_once()

    def roster_file(self,klass='9-B',gender="O'g'il"):
        book=Workbook();sheet=book.active
        sheet['A1']='Sinf:';sheet['B1']=klass
        sheet['A2']='Sinf rahbari:';sheet['D2']=' Askarova Dilnoza'
        sheet['A4']='№';sheet['B4']='F.I.SH';sheet['C4']='Jinsi';sheet['D4']='Yashash manzili'
        sheet['A5']=1;sheet['B5']='Karimov Jasur';sheet['C5']=gender;sheet['D5']='Xo‘jayli'
        sheet['A6']=2;sheet['B6']='Valiyeva Madina';sheet['C6']='Qiz';sheet['D6']='Nukus'
        sheet['A7']=3;sheet['B7']='Nomsiz';sheet['C7']='';sheet['D7']='Beruniy'
        stream=io.BytesIO();book.save(stream);return stream.getvalue()

    def test_teacher_uploads_roster_excel(self):
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.teacher(22,code,'Dilnoza','Askarova','9b')
        update={'update_id':self.n+1,'message':{'message_id':1,'from':{'id':22},'chat':{'id':22,'type':'private'},'document':{'file_id':'file-1','file_name':'9-B.xlsx','file_size':1000}}}
        self.n+=1
        with patch.object(bot,'fetch_file',return_value=self.roster_file()):
            sent=bot.handle_update(update)
        self.assertIn('2 o‘quvchi',sent[-1]['text'])
        self.assertIn('jinsi yo‘q',sent[-1]['text'])
        with s.connect() as c:
            rows=list(c.execute('SELECT name,gender,address FROM students WHERE active=1 ORDER BY name'))
        self.assertEqual([(row['name'],row['gender']) for row in rows],[('Karimov Jasur','M'),('Valiyeva Madina','F')])
        self.assertEqual(rows[0]['address'],'Xo‘jayli')
        wrong={'update_id':self.n+1,'message':{'message_id':2,'from':{'id':22},'chat':{'id':22,'type':'private'},'document':{'file_id':'file-2','file_name':'7-A.xlsx','file_size':1000}}}
        self.n+=1
        with patch.object(bot,'fetch_file',return_value=self.roster_file('7-A')):
            refused=bot.handle_update(wrong)
        self.assertIn('yozilmadi',refused[-1]['text'])
        with s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM students WHERE active=1').fetchone()[0],2)

    def test_deputy_downloads_month_and_year(self):
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.teacher(22,code,'Dilnoza','Karimova','7b')
        self.add_student(22,'Karimov Jasur')
        self.send(22,bot.ATT)
        with s.connect() as c:student=c.execute("SELECT id FROM students WHERE name='Karimov Jasur'").fetchone()['id']
        self.tap(22,'who:'+str(student))
        self.tap(22,'why:'+str(student)+':1')
        self.tap(22,'go')
        day=s.today()
        asked=self.send(11,bot.MONTH_BTN)
        keys=[button['callback_data'] for row in asked[-1]['reply_markup']['inline_keyboard'] for button in row]
        self.assertIn('mo:'+day.strftime('%Y-%m'),keys)
        sent=self.tap(11,'mo:'+day.strftime('%Y-%m'))
        book=load_workbook(io.BytesIO(next(item['pdf'] for item in sent if item.get('pdf') is not None)))
        self.assertEqual(len(book.worksheets),2)
        self.assertIn(bot.MONTHS[day.month],book.worksheets[0]['S2'].value)
        self.assertEqual(book.worksheets[1]['B4'].value,'Karimov Jasur')
        yearly=self.send(11,bot.YEAR_BTN)
        year_file=next(item for item in yearly if item.get('pdf') is not None)
        self.assertIn(str(s.school_year_start(day)),year_file['filename'])
        year_book=load_workbook(io.BytesIO(year_file['pdf']))
        self.assertIn("o'quv yili",year_book.worksheets[0]['S2'].value)
        self.assertEqual(year_book.worksheets[1]['B4'].value,'Karimov Jasur')

    def test_teacher_edits_student_and_deputy_edits_teacher(self):
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.deputy(33,'Bobur','Qodirov','Ikkinchi maktab')
        self.teacher(22,code,'Dilnoza','Karimova','7b')
        self.add_student(22,'Karimov Jasur')
        with s.connect() as c:student=c.execute("SELECT id FROM students WHERE name='Karimov Jasur'").fetchone()['id']
        opened=self.tap(22,'ed:'+str(student))
        self.assertIn('Karimov Jasur',opened[-1]['text'])
        self.tap(22,'sn:'+str(student))
        renamed=self.send(22,'Karimov Jasurbek')
        self.assertIn('Jasurbek',renamed[-1]['text'])
        self.tap(22,'sj:'+str(student)+':F')
        self.tap(22,'sa:'+str(student))
        self.send(22,'Beruniy')
        with s.connect() as c:
            row=c.execute('SELECT name,gender,address FROM students WHERE id=?',(student,)).fetchone()
        self.assertEqual((row['name'],row['gender'],row['address']),('Karimov Jasurbek','F','Beruniy'))
        listed=self.send(11,bot.STAFF)
        self.assertIn('7B — Karimova Dilnoza',listed[-1]['text'])
        hidden=self.send(33,bot.STAFF)
        self.assertNotIn('Karimova',hidden[-1]['text'])
        with s.connect() as c:teacher=c.execute("SELECT id FROM users WHERE login='tg22'").fetchone()['id']
        self.tap(11,'tn:'+str(teacher))
        self.send(11,'Karimova Dilrabo')
        self.tap(11,'tk:'+str(teacher))
        moved=self.send(11,'8A')
        self.assertIn('8A',moved[-1]['text'])
        with s.connect() as c:
            self.assertEqual(c.execute('SELECT name FROM classes WHERE teacher=?',(teacher,)).fetchone()['name'],'8A')
            self.assertEqual(c.execute('SELECT class_id FROM students WHERE id=?',(student,)).fetchone()['class_id'],c.execute('SELECT id FROM classes WHERE name=?',('8A',)).fetchone()['id'])
        self.tap(33,'ty:'+str(teacher))
        with s.connect() as c:self.assertEqual(c.execute('SELECT status FROM users WHERE id=?',(teacher,)).fetchone()['status'],'active')
        self.tap(11,'tx:'+str(teacher))
        self.tap(11,'ty:'+str(teacher))
        with s.connect() as c:
            self.assertEqual(c.execute('SELECT status FROM users WHERE id=?',(teacher,)).fetchone()['status'],'removed')
            self.assertIsNone(c.execute('SELECT teacher FROM classes WHERE name=?',('8A',)).fetchone()['teacher'])
            self.assertEqual(c.execute('SELECT count(*) FROM students WHERE id=? AND active=1',(student,)).fetchone()[0],1)
        home=self.send(22,'/start')
        self.assertIn('Maktab Hisobot',home[-1]['text'])

    def test_reminder_roster_move_holiday_second_deputy_and_chronic(self):
        import roster
        from excel_report import make_chronic_xlsx
        code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.teacher(22,code,'Dilnoza','Karimova','7b')
        self.teacher(44,code,'Sardor','Azimov','8a')
        self.add_student(22,'Karimov Jasur')
        with s.connect() as c:student=c.execute("SELECT id FROM students WHERE name='Karimov Jasur'").fetchone()['id']
        self.send(22,bot.ATT)
        self.tap(22,'who:'+str(student));self.tap(22,'why:'+str(student)+':1');self.tap(22,'go')
        morning=datetime.combine(s.today(),datetime.min.time()).replace(hour=9,minute=30,tzinfo=s.TZ)
        with patch.object(s,'send_message') as send:
            self.assertEqual(s.maybe_reminders(morning),1)
        self.assertIn('8A',send.call_args.args[1])
        self.assertIn('Bugungi davomat hali yo‘q',send.call_args.args[1])
        self.assertEqual(send.call_args.args[0],'44')
        exported=self.send(22,bot.ROSTER_BTN)
        parsed=roster.parse_roster(next(item['pdf'] for item in exported if item.get('pdf') is not None))
        self.assertEqual(parsed['students'][0]['name'],'Karimov Jasur')
        self.assertEqual(parsed['class_name'],'7B')
        self.tap(22,'sm:'+str(student))
        moved=self.send(22,'8A')
        self.assertIn('o‘tkazildi',moved[-1]['text'])
        with s.connect() as c:
            self.assertEqual(c.execute('SELECT name FROM classes WHERE id=(SELECT class_id FROM students WHERE id=?)',(student,)).fetchone()['name'],'8A')
            payload=json.loads(c.execute('SELECT payload FROM reports').fetchone()['payload'])
        self.assertEqual(payload[0]['name'],'Karimov Jasur')
        with s.connect() as c:
            school=c.execute("SELECT id FROM schools WHERE name='Birinchi maktab'").fetchone()['id']
            c.execute('INSERT INTO calendar(school_id,day,teaching) VALUES(?,?,0)',(school,s.today().isoformat()))
        blocked=self.send(44,bot.ATT)
        self.assertIn('dam olish',blocked[-1]['text'])
        invited=self.send(11,bot.DEPUTY2)
        invite=re.search(r'(\d{6})',invited[-1]['text']).group(1)
        self.send(55,'/start');self.send(55,bot.DEPUTY2)
        joined=self.send(55,invite)
        self.assertIn('sizga ham keladi',joined[-1]['text'])
        with s.connect() as c:self.assertEqual(c.execute('SELECT deputy_chat_2 FROM schools WHERE id=?',(school,)).fetchone()['deputy_chat_2'],'55')
        with s.connect() as c:
            class_id=c.execute("SELECT id FROM classes WHERE name='8A'").fetchone()['id']
            c.execute("INSERT INTO students(class_id,name,gender,address,active) VALUES(?,?,?,?,1)",(class_id,'Qisqa Keldi','M',''))
            other=c.execute("SELECT id FROM students WHERE name='Qisqa Keldi'").fetchone()['id']
            for index,day in enumerate(('2026-10-05','2026-10-06','2026-10-07','2026-10-08')):
                entries=[
                    {'id':student,'name':'Karimov Jasur','gender':'M','address':'','status':1,'class_id':class_id,'active':1,'note':''},
                    {'id':other,'name':'Qisqa Keldi','gender':'M','address':'','status':1 if index<3 else 0,'class_id':class_id,'active':1,'note':''},
                ]
                c.execute('INSERT INTO reports(school_id,day,class_id,revision,payload,updated) VALUES(?,?,?,?,?,?)',(school,day,class_id,1,json.dumps(entries,ensure_ascii=False),1))
            people=s.chronic_students(s.monthly_summary(c,'2026-10',school)['rows'])
        self.assertEqual([item['name'] for item in people],['Karimov Jasur'])
        book=load_workbook(io.BytesIO(make_chronic_xlsx(people,'2026-10',{'name':'Birinchi maktab'})))
        self.assertEqual(book.sheetnames,['Surunkali'])
        self.assertEqual(book.active['B4'].value,'Karimov Jasur')
        self.assertEqual(book.active['D4'].value,4)

    def test_subscription_is_hidden_and_stops_without_payment(self):
        with patch.dict(os.environ,{'PAYMENT_NAME':'Test Egası','PAYMENT_CARD':'8600 0000 0000 0000','ADMIN_CHAT_IDS':'99'}):
            code=self.deputy(11,'Ali','Valiyev','Birinchi maktab')
            self.teacher(22,code,'Dilnoza','Karimova','7b')
            self.add_student(22,'Karimov Jasur')
            home=self.send(11,'/start')
            labels=[button['text'] for row in home[-1]['reply_markup']['keyboard'] for button in row]
            self.assertNotIn(bot.ADMIN_BTN,labels)
            self.assertIn('Tel: 975627989',home[-1]['text'])
            self.assertIn('Nukus shahri',home[-1]['text'])
            self.assertNotIn('Maktablar:',self.send(11,bot.ADMIN_BTN)[-1]['text'])
            panel=self.send(99,bot.ADMIN_BTN)
            self.assertIn('Birinchi maktab',panel[-1]['text'])
            today=s.today()
            with s.connect() as c:
                school=c.execute("SELECT id FROM schools WHERE name='Birinchi maktab'").fetchone()['id']
                c.execute('UPDATE schools SET created_on=?,paid_until=?,sub_warned=? WHERE id=?',((today-timedelta(days=3)).isoformat(),'','',school))
            moment=datetime.combine(today,datetime.min.time()).replace(hour=9,minute=30,tzinfo=s.TZ)
            with patch.object(s,'send_message') as send:
                self.assertEqual(s.maybe_subscription_warnings(moment),1)
            text=send.call_args.args[1]
            self.assertIn('Oylik obuna tugashiga 3 kun qoldi',text)
            self.assertIn('100 000 so‘m',text)
            self.assertIn('Ilxam (admin)',text)
            self.assertIn('Tel: 975627989',text)
            self.assertIn('Test Egası',text)
            self.assertIn('8600 0000 0000 0000',text)
            self.assertEqual(send.call_args.args[0],'11')
            with s.connect() as c:
                c.execute('UPDATE schools SET created_on=? WHERE id=?',((today-timedelta(days=10)).isoformat(),school))
            self.assertIn('ishlamaydi',self.send(22,bot.ATT)[-1]['text'])
            self.assertIn('ishlamaydi',self.send(11,bot.PDF_BTN)[-1]['text'])
            shot=self.photo(11)
            self.assertTrue(any('qabul qilindi' in item.get('text','') for item in shot))
            notice=next(item for item in shot if item.get('photo'))
            self.assertEqual(str(notice['chat_id']),'99')
            self.assertIn('Birinchi maktab',notice['text'])
            self.assertIn('Valiyev Ali',notice['text'])
            payment=notice['reply_markup']['inline_keyboard'][0][0]['callback_data']
            self.assertEqual(self.tap(33,payment)[0].get('toast'),'Ruxsat yo‘q')
            self.assertIn('ishlamaydi',self.send(22,bot.ATT)[-1]['text'])
            approved=self.tap(99,payment)
            self.assertTrue(any('Tasdiqlandi' in item.get('text','') for item in approved))
            self.assertIn('Karimov Jasur',self.send(22,bot.ATT)[-1]['text'])

    def test_deputy_marks_several_holidays_on_the_month_calendar(self):
        from datetime import date
        self.deputy(11,'Ali','Valiyev','Birinchi maktab')
        self.deputy(33,'Bobur','Qodirov','Ikkinchi maktab')
        opened=self.send(11,bot.DAYS)
        labels=[button['text'] for row in opened[-1]['reply_markup']['inline_keyboard'] for button in row]
        self.assertIn('Bayram kalendari',labels)
        shown=self.tap(11,'ds:cal')
        self.assertIn('Saqlash',str(shown[-1]['reply_markup']))
        today=s.today()
        weekdays=[date(today.year,today.month,day).isoformat() for day in range(1,29) if date(today.year,today.month,day).weekday()<5]
        first,second,third=weekdays[:3]
        self.tap(11,'ds:d:'+first)
        self.tap(11,'ds:d:'+second)
        saved=self.tap(11,'ds:save')
        self.assertEqual(saved[0].get('toast'),'Saqlandi')
        with s.connect() as c:
            school=c.execute("SELECT id FROM schools WHERE name='Birinchi maktab'").fetchone()['id']
            other=c.execute("SELECT id FROM schools WHERE name='Ikkinchi maktab'").fetchone()['id']
            self.assertFalse(s.is_teaching_day(c,school,first))
            self.assertFalse(s.is_teaching_day(c,school,second))
            self.assertTrue(s.is_teaching_day(c,school,third))
            self.assertTrue(s.is_teaching_day(c,other,first))
        nxt=today.month%12+1
        year=today.year+(today.month==12)
        moved=self.tap(11,f'ds:m:{year:04d}-{nxt:02d}')
        self.assertIn(bot.MONTHS[nxt],moved[-1]['text'])
        with s.connect() as c:
            self.assertFalse(s.is_teaching_day(c,school,first))
        later=f'{year:04d}-{nxt:02d}-03'
        self.tap(11,'ds:d:'+later)
        self.tap(11,'ds:save')
        self.tap(11,'ds:m:'+first[:7])
        self.tap(11,'ds:d:'+first)
        cleared=self.tap(11,'ds:save')
        self.assertEqual(cleared[0].get('toast'),'Saqlandi')
        with s.connect() as c:
            self.assertTrue(s.is_teaching_day(c,school,first))
            self.assertFalse(s.is_teaching_day(c,school,later))
