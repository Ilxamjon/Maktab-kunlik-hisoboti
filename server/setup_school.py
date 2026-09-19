"""Interactive school setup. Credentials are never printed. Each school gets a unique code under a district."""
import getpass
import server

def main():
    server.init()
    print('Maktab Hisobot — maktab qo‘shish')
    with server.connect() as c:
        districts=list(c.execute('SELECT code,name FROM districts ORDER BY code'))
    if not districts:raise SystemExit('Avval tuman yarating (setup_tuman.py).')
    print('Tumanlar:')
    for row in districts:print(' ',row['code'],'—',row['name'])
    dcode=input('Tuman kodi: ').strip().upper()
    try:dcode=server.org_code_value(dcode)
    except server.ApiError as e:raise SystemExit(e.message)
    code=input('Maktab kodi (masalan XOJ-09): ').strip().upper()
    try:code=server.org_code_value(code)
    except server.ApiError as e:raise SystemExit(e.message)
    school={key:input(label+': ').strip() for key,label in [('name','Maktabning to‘liq nomi'),('director','Direktor F.I.Sh.'),('executor','Ijrochi F.I.Sh.')]}
    if not all(school.values()):raise SystemExit('Barcha ma’lumotlarni kiriting')
    login=input('Direktor o‘rinbosari uchun login: ').strip();pw=getpass.getpass('Parol (kamida 10 belgi): ')
    if not login or len(pw)<10:raise SystemExit('Login/parol yetarli emas')
    if pw!=getpass.getpass('Parolni takrorlang: '):raise SystemExit('Parollar mos emas')
    with server.connect() as c:
        district=c.execute('SELECT * FROM districts WHERE code=?',(dcode,)).fetchone()
        if not district:raise SystemExit('Tuman kodi topilmadi')
        did=district['id']
        if c.execute('SELECT 1 FROM districts WHERE code=?',(code,)).fetchone():
            raise SystemExit('Bu kod tumanga berilgan. Maktab uchun XOJ-09 kabi kod tanlang.')
        taken=c.execute('SELECT id FROM schools WHERE code=?',(code,)).fetchone()
        empty=c.execute("""SELECT s.id FROM schools s WHERE s.district_id=? AND NOT EXISTS (
            SELECT 1 FROM users u WHERE u.school_id=s.id AND u.role='admin') ORDER BY s.id""",(did,)).fetchone()
        if taken and (not empty or taken['id']!=empty['id']):
            raise SystemExit('Bu kod allaqachon bor. Boshqa kod tanlang.')
        if empty:
            c.execute('UPDATE schools SET code=?,name=?,director=?,executor=?,district_id=? WHERE id=?',
                      (code,school['name'],school['director'],school['executor'],did,empty['id']))
            sid=empty['id']
        else:
            c.execute('INSERT INTO schools(district_id,code,name,director,executor) VALUES(?,?,?,?,?)',
                      (did,code,school['name'],school['director'],school['executor']))
            sid=c.execute('SELECT id FROM schools WHERE code=?',(code,)).fetchone()[0]
        c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'admin',?)",
                  (did,sid,login,server.password_hash(pw),school['executor']))
    print('Tayyor. Ilovada maktab kodi:',code)
    print('O‘qituvchi va sinflarni direktor o‘rinbosari ilovadan yaratadi. Kunlik PDF soat 12:00 da shu maktab Telegramiga ketadi.')

if __name__=='__main__':main()
