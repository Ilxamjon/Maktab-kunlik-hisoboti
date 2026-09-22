import unittest,tempfile,os,json
from unittest.mock import patch
from datetime import datetime
from pathlib import Path
import server as s

class Tests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();s.DB=str(Path(self.temp.name)/'test.db');s.init()
        with s.connect() as c:
            self.sid=c.execute('SELECT id FROM schools').fetchone()[0]
            self.did=c.execute('SELECT district_id FROM schools WHERE id=?',(self.sid,)).fetchone()[0]
            for i,role in enumerate(['admin','teacher','teacher'],1):
                c.execute('INSERT INTO users(id,district_id,school_id,login,password,role,name) VALUES(?,?,?,?,?,?,?)',(i,self.did,self.sid,'user'+str(i),s.password_hash('secret-pass'),role,'Foydalanuvchi '+str(i)))
            c.execute("INSERT INTO classes(id,school_id,name,teacher) VALUES(1,?,'7-A',2)",(self.sid,))
            c.execute("INSERT INTO classes(id,school_id,name,teacher) VALUES(2,?,'7-B',3)",(self.sid,))
        self.tokens={i:s.dispatch('POST','/login',{'login':'user'+str(i),'password':'secret-pass'})['token'] for i in range(1,4)}
        for cid in (1,2):
            for n,g in [('Sinov O‘quvchi','M'),('Sinov Qiz','F')]:s.dispatch('POST','/students',{'class_id':cid,'name':n,'gender':g,'address':'Namunaviy manzil'},self.tokens[cid+1])
    def tearDown(self):self.temp.cleanup()
    def report(self,cid=1,revision=0,status=1):
        with s.connect() as c:ids=[r['id'] for r in c.execute('SELECT id FROM students WHERE class_id=?',(cid,))]
        return {'class_id':cid,'day':'2026-09-16','revision':revision,'entries':[{'id':sid,'status':status if i==0 else 0,'note':'Sinov'} for i,sid in enumerate(ids)]}
    def submit(self,cid=1,revision=0,status=1):return s.dispatch('POST','/report',self.report(cid,revision,status),self.tokens[cid+1])
    def rows(self,day='2026-09-16'):
        with s.connect() as c:return s.summary(c,day,self.sid)
    def test_authentication(self):
        with self.assertRaises(s.ApiError):s.dispatch('GET','/classes',{},'invalid')
        with self.assertRaises(s.ApiError):s.dispatch('POST','/login',{'login':'user2','password':'wrong'})
    def test_google_onboarding_first_user_and_pending_teacher(self):
        with s.connect() as c:
            c.execute("INSERT INTO schools(district_id,code,name) VALUES(?,'TEST-NEW','Yangi maktab')",(self.did,))
            onboarding_sid=c.execute("SELECT id FROM schools WHERE code='TEST-NEW'").fetchone()[0]
        profiles=[{'sub':'google-admin','email':'admin@example.com','name':'Admin'}, {'sub':'google-teacher','email':'teacher@example.com','name':'Teacher'}]
        with patch.object(s,'verify_google_id_token',side_effect=profiles):
            admin=s.dispatch('POST','/onboarding',{'id_token':'a','district_id':self.did,'school_id':onboarding_sid})
            teacher=s.dispatch('POST','/onboarding',{'id_token':'b','district_id':self.did,'school_id':onboarding_sid,'class_name':'5-A'})
        self.assertEqual(admin['role'],'admin');self.assertFalse(admin['pending']);self.assertTrue(admin['token'])
        self.assertEqual(teacher['role'],'teacher');self.assertTrue(teacher['pending']);self.assertIsNone(teacher['token'])
        members=s.dispatch('GET','/members',{},admin['token'])['members']
        self.assertEqual(members[0]['class_name'],'5-A');self.assertEqual(members[0]['status'],'pending')
        s.dispatch('POST','/members',{'user_id':members[0]['id'],'approved':True},admin['token'])
        with patch.object(s,'verify_google_id_token',return_value=profiles[1]):
            login=s.dispatch('POST','/auth/google',{'id_token':'b'})
        self.assertEqual(login['role'],'teacher');self.assertTrue(login['token'])
    def test_public_catalog(self):
        catalog=s.dispatch('GET','/catalog',{})
        self.assertEqual(catalog['districts'][0]['schools'][0]['id'],self.sid)
    def test_other_class_and_admin_protection(self):
        with self.assertRaises(s.ApiError):s.dispatch('GET','/students?class_id=2',{},self.tokens[2])
        with self.assertRaises(s.ApiError):s.dispatch('GET','/summary?day=2026-09-16',{},self.tokens[2])
    def test_summary_missing_and_pdf(self):
        self.submit()
        rows=self.rows()
        self.assertEqual(rows[0]['counts'],[1,1]+[0]*16);self.assertFalse(rows[1]['submitted'])
        with s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
        blob=s.make_pdf(rows,'2026-09-16',{'name':'Test','code':'MAKTAB'})
        self.assertTrue(blob.startswith(b'%PDF'))
    def test_submit_does_not_queue_telegram(self):
        self.submit();self.submit(2);self.submit(2,1)
        with s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
    def test_noon_digest_queues_once(self):
        self.submit()
        noon=datetime(2026,9,16,12,0,tzinfo=s.TZ)
        self.assertEqual(s.maybe_noon_digests(noon),1)
        self.assertEqual(s.maybe_noon_digests(noon),0)
        with s.connect() as c:
            self.assertEqual(c.execute("SELECT count(*) FROM outbox WHERE kind='noon'").fetchone()[0],1)
            self.assertEqual(c.execute("SELECT count(*) FROM digests WHERE kind='noon'").fetchone()[0],1)
        before=datetime(2026,9,16,11,59,tzinfo=s.TZ)
        self.assertEqual(s.maybe_noon_digests(before),0)
    def test_conflict_and_correction(self):
        self.submit()
        with self.assertRaises(s.ApiError) as e:self.submit(status=0)
        self.assertEqual(e.exception.status,409);self.submit(revision=1,status=0)
        self.assertEqual(self.rows()[0]['counts'][0],2)
        with s.connect() as c:self.assertEqual(c.execute('SELECT count(*) FROM audit').fetchone()[0],2)
    def test_invalid_and_duplicate_students(self):
        r=self.report();r['entries'][1]['id']=r['entries'][0]['id']
        with self.assertRaises(s.ApiError):s.dispatch('POST','/report',r,self.tokens[2])
        r=self.report();r['entries'][0]['status']=99
        with self.assertRaises(s.ApiError):s.dispatch('POST','/report',r,self.tokens[2])
    def test_snapshot_is_preserved(self):
        self.submit()
        with s.connect() as c:c.execute("UPDATE students SET name='Yangi ism',gender='F' WHERE id=1")
        self.assertEqual(self.rows()[0]['entries'][0]['gender'],'M')
    def test_telegram_success_and_retry(self):
        self.submit();s.dispatch('POST','/telegram',{'day':'2026-09-16'},self.tokens[1])
        with patch.dict(os.environ,{'TELEGRAM_BOT_TOKEN':'fake','TELEGRAM_CHAT_ID':'123'}):
            with patch.object(s,'send_document',side_effect=RuntimeError('offline')):s.process_one()
            with s.connect() as c:
                row=c.execute('SELECT * FROM outbox').fetchone();self.assertEqual(row['state'],'pending');self.assertEqual(row['attempts'],1);c.execute('UPDATE outbox SET next_try=0')
            with patch.object(s,'send_document') as send:s.process_one();send.assert_called_once()
        with s.connect() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM outbox').fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM reports WHERE day='2026-09-16'").fetchone()[0],0)
            self.assertEqual(c.execute("SELECT count(*) FROM audit WHERE day='2026-09-16'").fetchone()[0],0)
    def test_logout(self):
        s.dispatch('POST','/logout',{},self.tokens[2])
        with self.assertRaises(s.ApiError):s.dispatch('GET','/classes',{},self.tokens[2])
    def test_all_template_categories(self):
        self.assertEqual(len(s.REASONS),18)
        self.assertEqual(set(s.COLUMN_ORDER),set(range(1,18)))
        for status in range(18):
            self.submit(1,status,status)
        self.assertEqual(self.rows()[0]['counts'][17],1)
    def test_admin_accounts_classes_and_password(self):
        admin=self.tokens[1]
        result=s.dispatch('POST','/users',{'login':'newteacher','password':'long-password','name':'Yangi O‘qituvchi'},admin)
        uid=next(u['id'] for u in result['users'] if u['login']=='newteacher')
        s.dispatch('POST','/classes/create',{'name':'5-A','teacher_id':uid},admin)
        s.dispatch('POST','/users/reset',{'id':uid,'password':'another-secret'},admin)
        with self.assertRaises(s.ApiError):s.dispatch('POST','/login',{'login':'newteacher','password':'long-password'})
        self.assertIn('token',s.dispatch('POST','/login',{'login':'newteacher','password':'another-secret'}))
        with self.assertRaises(s.ApiError):s.dispatch('POST','/users',{'login':'evil','password':'long-password','name':'X'},self.tokens[2])
    def test_lock_and_unlock(self):
        self.submit()
        s.dispatch('POST','/report/lock',{'day':'2026-09-16','class_id':1,'revision':1,'locked':True},self.tokens[1])
        with self.assertRaises(s.ApiError):self.submit(revision=2)
        s.dispatch('POST','/report/lock',{'day':'2026-09-16','class_id':1,'revision':2,'locked':False},self.tokens[1])
        self.submit(revision=3,status=2)
    def test_calendar_and_monthly_denominator(self):
        self.submit();self.submit(2)
        s.dispatch('POST','/calendar',{'month':'2026-09','days':['2026-09-16','2026-09-17']},self.tokens[1])
        result=s.dispatch('GET','/monthly?month=2026-09',{},self.tokens[1])
        self.assertTrue(result['calendar_configured']);self.assertEqual(len(result['rows']),4)
        done=[r for r in result['rows'] if r['submitted']]
        self.assertEqual(sum(r['total'] for r in done),4)
        self.assertEqual(sum(r['counts'][0] for r in done),2)
        with self.assertRaises(s.ApiError):s.dispatch('POST','/calendar',{'month':'2026-09','days':[]},self.tokens[1])
    def test_student_edit_archive_historical_roster(self):
        self.submit()
        s.dispatch('POST','/students/update',{'id':1,'name':'Updated','gender':'F','address':'New address'},self.tokens[2])
        s.dispatch('POST','/students/archive',{'id':1},self.tokens[2])
        self.submit(revision=1,status=2)
        e=self.rows()[0]['entries'][0]
        self.assertEqual(e['gender'],'M');self.assertEqual(e['address'],'Namunaviy manzil')
        pupils=s.dispatch('GET','/students?class_id=1',{},self.tokens[2])['students'];self.assertEqual(len(pupils),1)
    def test_pdf_matches_excel_template(self):
        from pypdf import PdfReader
        import io
        self.submit();blob=s.dispatch('GET','/pdf?day=2026-09-16',{},self.tokens[1])
        pdf=PdfReader(io.BytesIO(blob));text=' '.join(page.extract_text() for page in pdf.pages)
        self.assertIn('yashash manzili',text.lower());self.assertIn('Namunaviy manzil',text);self.assertIn('QISMAN',text)
        self.assertIn('Maktab raqami',text);self.assertIn('Shundan',text);self.assertIn('7-A',text)
        self.assertGreaterEqual(len(pdf.pages),3)
        self.assertIn('7-B',text)
        self.assertTrue('rahbar' in text.lower())
    def test_monthly_queue_is_deduplicated(self):
        self.submit();self.submit(2)
        for _ in range(2):s.dispatch('POST','/monthly/telegram',{'month':'2026-09'},self.tokens[1])
        with s.connect() as c:self.assertEqual(c.execute("SELECT count(*) FROM outbox WHERE day='2026-09'").fetchone()[0],1)
    def test_settings_password_and_revocation(self):
        s.dispatch('POST','/settings',{'name':'Test maktab','director':'Direktor','executor':'Ijrochi'},self.tokens[1])
        self.assertEqual(s.dispatch('GET','/classes',{},self.tokens[2])['school']['name'],'Test maktab')
        s.dispatch('POST','/password',{'current':'secret-pass','password':'new-password'},self.tokens[2])
        with self.assertRaises(s.ApiError):s.dispatch('GET','/classes',{},self.tokens[2])
    def test_schools_do_not_mix(self):
        with s.connect() as c:
            c.execute("INSERT INTO schools(district_id,code,name) VALUES(?,'BOSHQA','Boshqa maktab')",(self.did,))
            bid=c.execute("SELECT id FROM schools WHERE code='BOSHQA'").fetchone()[0]
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'admin',?)",(self.did,bid,'user1',s.password_hash('secret-pass'),'Boshqa direktor'))
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'teacher',?)",(self.did,bid,'teachb',s.password_hash('secret-pass'),'Boshqa o‘qituvchi'))
            tid=c.execute("SELECT id FROM users WHERE school_id=? AND login='teachb'",(bid,)).fetchone()[0]
            c.execute("INSERT INTO classes(school_id,name,teacher) VALUES(?,'7-A',?)",(bid,tid))
        a=s.dispatch('POST','/login',{'school':'MAKTAB','login':'user1','password':'secret-pass'})
        b=s.dispatch('POST','/login',{'school':'BOSHQA','login':'user1','password':'secret-pass'})
        self.assertNotEqual(a['token'],b['token'])
        self.assertEqual(a['school'],'MAKTAB');self.assertEqual(b['school'],'BOSHQA')
        classes_a=s.dispatch('GET','/classes',{},a['token'])['classes']
        classes_b=s.dispatch('GET','/classes',{},b['token'])['classes']
        self.assertEqual({c['name'] for c in classes_a},{'7-A','7-B'})
        self.assertEqual({c['name'] for c in classes_b},{'7-A'})
        self.assertNotEqual(classes_a[0]['id'],classes_b[0]['id'])
        other_id=classes_b[0]['id']
        with self.assertRaises(s.ApiError):s.dispatch('GET','/students?class_id='+str(other_id),{},self.tokens[2])
    def test_wsgi_json_pdf_and_auth(self):
        import app,io
        def call(path,token='',data=None,extra=None):
            raw=json.dumps(data).encode() if data is not None else b''
            parts=path.split('?',1);headers=[]
            env={'REQUEST_METHOD':'POST' if data is not None else 'GET','PATH_INFO':parts[0],'QUERY_STRING':parts[1] if len(parts)>1 else '', 'CONTENT_LENGTH':str(len(raw)),'wsgi.input':io.BytesIO(raw),'HTTP_AUTHORIZATION':'Bearer '+token,'REMOTE_ADDR':'test'}
            env.update(extra or {})
            result=app.application(env,lambda status,h:headers.extend([status,h]))
            return headers,b''.join(result)
        self.assertTrue(call('/classes')[0][0].startswith('401'))
        self.submit();headers,body=call('/pdf?day=2026-09-16',self.tokens[1]);self.assertTrue(headers[0].startswith('200'));self.assertTrue(body.startswith(b'%PDF'))
        self.assertTrue(call('/users',self.tokens[2],{'login':'evil','password':'long-password','name':'X'})[0][0].startswith('403'))
        with patch.dict(os.environ,{'CRON_SECRET':'test-secret'}):
            self.assertTrue(call('/cron/noon')[0][0].startswith('403'))
            self.assertTrue(call('/cron/noon',extra={'HTTP_X_CRON_SECRET':'test-secret'})[0][0].startswith('200'))
    def test_proxy_ip_and_failed_login_rate_limit(self):
        import app
        app._LIMITS.clear()
        env={'REMOTE_ADDR':'127.0.0.1','HTTP_X_REAL_IP':'203.0.113.8'}
        self.assertEqual(app._client_ip(env),'203.0.113.8')
        key=app._login_key(env,{'school':'MAKTAB','login':'user2'})
        for _ in range(10):app._record_login_failure(key)
        with self.assertRaises(s.ApiError) as error:app._check_login_limit(key)
        self.assertEqual(error.exception.status,429)
        app._clear_login_failures(key);app._check_login_limit(key)
    def test_districts_do_not_mix(self):
        pw=s.password_hash('secret-pass')
        with s.connect() as c:
            c.execute("UPDATE districts SET code='XOJ',name='Xo‘jayli tumani' WHERE id=?",(self.did,))
            c.execute("UPDATE schools SET code='XOJ-09',name='9-maktab' WHERE id=?",(self.sid,))
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'district',?)",(self.did,None,'tuman',pw,'Tuman xodimi'))
            c.execute("INSERT INTO districts(code,name) VALUES('NUK','Nukus tumani')")
            other=c.execute("SELECT id FROM districts WHERE code='NUK'").fetchone()[0]
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'district',?)",(other,None,'tuman',pw,'Boshqa tuman'))
            c.execute("INSERT INTO schools(district_id,code,name) VALUES(?,'NUK-01','1-maktab')",(other,))
            nid=c.execute("SELECT id FROM schools WHERE code='NUK-01'").fetchone()[0]
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'admin',?)",(other,nid,'user1',pw,'Nukus direktor'))
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'teacher',?)",(other,nid,'teachn',pw,'Nukus o‘qituvchi'))
            tid=c.execute("SELECT id FROM users WHERE school_id=? AND login='teachn'",(nid,)).fetchone()[0]
            c.execute("INSERT INTO classes(school_id,name,teacher) VALUES(?,'7-A',?)",(nid,tid))
        xoj=s.dispatch('POST','/login',{'school':'XOJ','login':'tuman','password':'secret-pass'})
        nuk=s.dispatch('POST','/login',{'school':'NUK','login':'tuman','password':'secret-pass'})
        self.assertEqual(xoj['role'],'district');self.assertEqual(nuk['kind'],'district')
        a=s.dispatch('GET','/classes',{},xoj['token']);b=s.dispatch('GET','/classes',{},nuk['token'])
        self.assertEqual({row['code'] for row in a['schools']},{'XOJ-09'})
        self.assertEqual({row['code'] for row in b['schools']},{'NUK-01'})
        with self.assertRaises(s.ApiError):s.dispatch('GET','/students?class_id=1',{},xoj['token'])
        with self.assertRaises(s.ApiError):s.dispatch('GET','/pdf?day=2026-09-16',{},xoj['token'])
        with self.assertRaises(s.ApiError):s.dispatch('POST','/schools/admin',{'school_id':nid,'login':'hack','password':'long-password','name':'X'},xoj['token'])
        school=s.dispatch('POST','/login',{'school':'XOJ-09','login':'user1','password':'secret-pass'})
        self.assertEqual(school['school'],'XOJ-09');self.assertEqual(school['kind'],'school')
        created=s.dispatch('POST','/schools',{'code':'XOJ-42','name':'42-maktab','director':'D','executor':'I'},xoj['token'])
        self.assertEqual({row['code'] for row in created['schools']},{'XOJ-09','XOJ-42'})
        again=s.dispatch('GET','/classes',{},nuk['token'])
        self.assertEqual({row['code'] for row in again['schools']},{'NUK-01'})
    def test_hyphen_codes_and_collision(self):
        with self.assertRaises(s.ApiError):s.org_code_value('bad code!')
        self.assertEqual(s.org_code_value('xoj-09'),'XOJ-09')
        pw=s.password_hash('secret-pass')
        with s.connect() as c:
            c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'district',?)",(self.did,None,'tuman',pw,'Tuman'))
        token=s.dispatch('POST','/login',{'school':'TUMAN','login':'tuman','password':'secret-pass'})['token']
        with self.assertRaises(s.ApiError) as e:
            s.dispatch('POST','/schools',{'code':'TUMAN','name':'To‘qnashuv','director':'D','executor':'I'},token)
        self.assertEqual(e.exception.status,409)

if __name__=='__main__':unittest.main()
