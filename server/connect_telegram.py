"""Pair the intended recipient by a one-time /start code. Does not send messages."""
import getpass,secrets,json,os
from urllib.request import urlopen
from pathlib import Path
import server
ROOT=Path(__file__).parent

def main():
    server.init()
    token=getpass.getpass('BotFather bergan bot tokeni: ').strip()
    def get(method):
        with urlopen('https://api.telegram.org/bot'+token+'/'+method,timeout=35) as r:return json.load(r)
    try:
        me=get('getMe')
        if not me.get('ok'):raise ValueError()
    except Exception:raise SystemExit('Token yoki tarmoqni tekshiring. Token ekranga chiqarilmadi.')
    with server.connect() as c:schools=list(c.execute('SELECT id,code,name FROM schools ORDER BY id'))
    if not schools:raise SystemExit('Avval 1_ORNATISH.cmd orqali maktab yarating.')
    print('Maktablar:')
    for row in schools:print(' ',row['code'],'—',row['name'])
    code=input('Telegram ulanadigan maktab kodi: ').strip()
    try:code=server.org_code_value(code) if code else schools[0]['code']
    except server.ApiError as e:raise SystemExit(e.message)
    with server.connect() as c:
        school=c.execute('SELECT * FROM schools WHERE code=?',(code,)).fetchone()
        if not school:raise SystemExit('Maktab kodi topilmadi')
        sid=school['id']
    code_start=secrets.token_urlsafe(12);print('Direktor o‘rinbosari O‘Z akkauntidan ushbu havolani ochib Start bossin:')
    print('https://t.me/'+me['result']['username']+'?start='+code_start)
    input('Start bosilgach Enter bosing: ')
    try:updates=get('getUpdates')
    except Exception:raise SystemExit('Telegram javob bermadi; boshqa bot polling/webhook jarayoni ishlamayotganini tekshiring.')
    candidates=[]
    for item in updates.get('result',[]):
        m=item.get('message',{})
        if m.get('text')=='/start '+code_start and m.get('chat',{}).get('type')=='private':candidates.append(m['chat'])
    if not candidates:raise SystemExit('Tasdiqlash xabari topilmadi. Qayta urinib yangi havolani oching.')
    chat=candidates[-1]
    print('Topilgan akkaunt:',chat.get('first_name',''),chat.get('last_name',''),'@'+chat.get('username',''), 'ID:',chat['id'])
    if input('Bu aynan shu maktab direktor o‘rinbosarining akkauntimi? Tasdiqlash uchun HA yozing: ')!='HA':raise SystemExit('Ulanmadi')
    with server.connect() as c:
        c.execute('UPDATE schools SET telegram_bot_token=?,telegram_chat_id=? WHERE id=?',(token,str(chat['id']),sid))
    path=ROOT/'config.json';config=json.loads(path.read_text()) if path.exists() else {}
    if len(schools)==1:config.update(TELEGRAM_BOT_TOKEN=token,TELEGRAM_CHAT_ID=str(chat['id']))
    path.write_text(json.dumps(config,indent=2),encoding='utf-8');os.chmod(path,0o600)
    print('Ulandi:',code,'. Serverni qayta ishga tushiring. Hozir PDF yuborilmadi. Kunlik jamlanma soat 12:00 da ketadi.')
if __name__=='__main__':main()
