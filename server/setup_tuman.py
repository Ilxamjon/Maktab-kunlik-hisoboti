"""Create a district (tuman) and its administrator. One HTTPS server hosts many districts."""
import getpass
import server

def main():
    server.init()
    print('Maktab Hisobot — tuman qo‘shish')
    print('Bitta server barcha tumanlar uchun. Tuman kodi maktab kodidan farq qilsin: XOJ, maktab esa XOJ-09.')
    code=input('Tuman kodi (masalan XOJ): ').strip().upper()
    try:code=server.org_code_value(code)
    except server.ApiError as e:raise SystemExit(e.message)
    name=input('Tuman nomi (masalan Xo‘jayli tumani): ').strip()
    login=input('Tuman xodimi logini: ').strip()
    pw=getpass.getpass('Parol (kamida 10 belgi): ')
    if not name or not login or len(pw)<10:raise SystemExit('Ma’lumotlar yetarli emas')
    if pw!=getpass.getpass('Parolni takrorlang: '):raise SystemExit('Parollar mos emas')
    with server.connect() as c:
        if c.execute('SELECT 1 FROM schools WHERE code=?',(code,)).fetchone():
            raise SystemExit('Bu kod maktabga berilgan. Tuman uchun boshqa kod tanlang.')
        row=c.execute('SELECT * FROM districts ORDER BY id').fetchone()
        has_admin=c.execute("SELECT 1 FROM users WHERE role='district' AND district_id=?",(row['id'],)).fetchone() if row else None
        if row and not has_admin:
            taken=c.execute('SELECT 1 FROM districts WHERE code=? AND id<>?',(code,row['id'])).fetchone()
            if taken:raise SystemExit('Bu tuman kodi band')
            c.execute('UPDATE districts SET code=?,name=? WHERE id=?',(code,name,row['id']))
            did=row['id']
        else:
            if c.execute('SELECT 1 FROM districts WHERE code=?',(code,)).fetchone():
                raise SystemExit('Bu tuman kodi band')
            c.execute('INSERT INTO districts(code,name) VALUES(?,?)',(code,name))
            did=c.execute('SELECT id FROM districts WHERE code=?',(code,)).fetchone()[0]
        if c.execute("SELECT 1 FROM users WHERE district_id=? AND school_id IS NULL AND login=?",(did,login)).fetchone():
            raise SystemExit('Bu login tuman ichida band')
        c.execute("INSERT INTO users(district_id,school_id,login,password,role,name) VALUES(?,?,?,?,'district',?)",
                  (did,None,login,server.password_hash(pw),name))
    print('Tayyor. Ilovada tuman kodi:',code)
    print('Tuman xodimi maktablarni ilovadan qo‘shadi. Har maktab o‘z kodi va o‘z Telegramiga ega.')
    print('Keyin 1-maktabni setup_school.py orqali ham qo‘shish mumkin.')

if __name__=='__main__':main()
