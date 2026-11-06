import io, json, os, re, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
from openpyxl import load_workbook
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
        sheet_file=next(item for item in sent if item.get('pdf') is not None)
        self.assertEqual(str(sheet_file['chat_id']),'11')
        self.assertNotEqual(str(sheet_file['chat_id']),'22')
        self.assertNotEqual(str(sheet_file['chat_id']),'33')
        self.assertTrue(sheet_file['filename'].endswith('.xlsx'))
        sheet=load_workbook(io.BytesIO(sheet_file['pdf'])).active
        self.assertEqual(sheet['B7'].value,'Birinchi maktab')
        self.assertEqual(sheet['C7'].value,1)
        self.assertEqual(sheet['E7'].value,1)
        self.assertEqual(sheet['F7'].value,1)
        self.assertEqual(sheet['G4'].value,'Kasalligi tufayli')
        self.assertEqual(sheet['G7'].value,1)
        values=' '.join(str(cell.value) for row in sheet.iter_rows() for cell in row if cell.value is not None)
        self.assertNotIn('Ikkinchi',values)
        self.assertNotIn('Jasur',values)
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
