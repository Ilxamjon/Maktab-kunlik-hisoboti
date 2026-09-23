"""WSGI entry point for Waitress. Authentication is a bearer token, not a cookie."""
import ipaddress,json,logging,os,secrets,sqlite3,time,threading
import database
from http import HTTPStatus
import server
logging.basicConfig(
    level=getattr(logging, os.getenv('LOG_LEVEL', 'INFO').upper(), logging.INFO),
    format='%(asctime)s %(levelname)s %(name)s %(message)s')
LOG=logging.getLogger('maktab-hisobot')
_LIMITS={};_LOCK=threading.Lock()
# Waitress imports this module instead of running its __main__ block. Run the
# idempotent schema/catalog migration here so every production deploy is ready.
server.init()

def _client_ip(environ):
    """Trust nginx's real IP only when Waitress is reached through loopback."""
    peer=environ.get('REMOTE_ADDR','unknown')
    forwarded=environ.get('HTTP_X_REAL_IP','') if peer in ('127.0.0.1','::1') else ''
    candidate=forwarded or peer
    try:return str(ipaddress.ip_address(candidate))
    except ValueError:return 'unknown'

def _login_key(environ,data):
    identity=(str(data.get('school',''))+'|'+str(data.get('login',''))).strip().lower()
    return _client_ip(environ)+'|'+identity[:180]

def _check_login_limit(key):
    now=time.monotonic()
    with _LOCK:
        for item in list(_LIMITS):
            if _LIMITS[item][1] <= now:del _LIMITS[item]
        count,end=_LIMITS.get(key,(0,now+300))
        if count>=10:raise server.ApiError('Ko‘p xato urinish. Besh daqiqadan keyin qayta kiring.',429)

def _record_login_failure(key):
    now=time.monotonic()
    with _LOCK:
        count,end=_LIMITS.get(key,(0,now+300))
        if end<=now:count,end=0,now+300
        _LIMITS[key]=(count+1,end)

def _clear_login_failures(key):
    with _LOCK:_LIMITS.pop(key,None)

def application(environ,start_response):
    code=200;ctype='application/json; charset=utf-8'
    login_key=None
    try:
        method=environ.get('REQUEST_METHOD','GET');path=environ.get('PATH_INFO','/')
        if method not in ('GET','POST'):raise server.ApiError('GET yoki POST kerak',405)
        length=int(environ.get('CONTENT_LENGTH') or 0)
        if length<0 or length>1_000_000:raise server.ApiError('So‘rov hajmi katta',413)
        data=json.loads(environ['wsgi.input'].read(length)) if length else {}
        if not isinstance(data,dict):raise server.ApiError('JSON obyekt kerak')
        if path=='/login':login_key=_login_key(environ,data);_check_login_limit(login_key)
        query=environ.get('QUERY_STRING','');token=environ.get('HTTP_AUTHORIZATION','').removeprefix('Bearer ')
        if path=='/health':result={'status':'ok','version':'1.1','database':'postgres' if database.is_postgres() else 'sqlite'}
        elif path=='/cron/noon':
            expected=os.getenv('CRON_SECRET','');supplied=environ.get('HTTP_X_CRON_SECRET','')
            if not expected or not secrets.compare_digest(supplied,expected):raise server.ApiError('Ruxsat yo‘q',403)
            queued=server.maybe_noon_digests();processed=0
            while processed<100 and server.process_one():processed+=1
            result={'ok':True,'queued':queued,'processed':processed}
        else:result=server.dispatch(method,path+('?' +query if query else ''),data,token)
        if login_key:_clear_login_failures(login_key)
        if isinstance(result,bytes):raw=result;ctype='application/pdf'
        else:raw=json.dumps(result,ensure_ascii=False).encode()
    except server.ApiError as e:
        if login_key and e.status==401:_record_login_failure(login_key)
        code=e.status;raw=json.dumps({'error':e.message},ensure_ascii=False).encode()
    except database.INTEGRITY_ERRORS:code=409;raw=json.dumps({'error':'Login yoki sinf allaqachon mavjud'},ensure_ascii=False).encode()
    except (ValueError,TypeError):code=400;raw=b'{"error":"Bad request"}'
    except Exception:
        LOG.exception('Unhandled request error: %s %s',environ.get('REQUEST_METHOD'),environ.get('PATH_INFO'))
        code=500;raw=b'{"error":"Server error"}'
    headers=[('Content-Type',ctype),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
    if ctype=='application/pdf':headers.append(('Content-Disposition','attachment; filename="Hisobot.pdf"'))
    start_response(str(code)+' '+HTTPStatus(code).phrase,headers);return [raw]

if __name__=='__main__':
    from waitress import serve
    config=server.ROOT/'config.json'
    if config.exists():
        for key,value in json.loads(config.read_text(encoding='utf-8')).items():os.environ.setdefault(key,str(value))
    server.init();threading.Thread(target=server.worker,daemon=True).start()
    print('Maktab Hisobot porti:',os.getenv('PORT','8080'),'| Internet uchun HTTPS proksi kerak.')
    serve(application,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8080')),threads=24,max_request_body_size=1_000_000)
