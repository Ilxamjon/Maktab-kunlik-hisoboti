"""WSGI entry point for Waitress. Authentication is a bearer token, not a cookie."""
import json,sqlite3,time,threading
from http import HTTPStatus
import server
_LIMITS={};_LOCK=threading.Lock()
def application(environ,start_response):
    code=200;ctype='application/json; charset=utf-8'
    try:
        method=environ.get('REQUEST_METHOD','GET');path=environ.get('PATH_INFO','/')
        if method not in ('GET','POST'):raise server.ApiError('GET yoki POST kerak',405)
        if path=='/login':
            peer=environ.get('REMOTE_ADDR','unknown');now=time.monotonic()
            with _LOCK:
                for key in list(_LIMITS):
                    if _LIMITS[key][1]<now:del _LIMITS[key]
                count,end=_LIMITS.get(peer,(0,now+60))
                if count>=20:raise server.ApiError('Ko‘p urinish. Bir daqiqadan keyin qayta kiring.',429)
                _LIMITS[peer]=(count+1,end)
        length=int(environ.get('CONTENT_LENGTH') or 0)
        if length<0 or length>1_000_000:raise server.ApiError('So‘rov hajmi katta',413)
        data=json.loads(environ['wsgi.input'].read(length)) if length else {}
        if not isinstance(data,dict):raise server.ApiError('JSON obyekt kerak')
        query=environ.get('QUERY_STRING','');token=environ.get('HTTP_AUTHORIZATION','').removeprefix('Bearer ')
        if path=='/health':result={'status':'ok','version':'0.4'}
        else:result=server.dispatch(method,path+('?' +query if query else ''),data,token)
        if isinstance(result,bytes):raw=result;ctype='application/pdf'
        else:raw=json.dumps(result,ensure_ascii=False).encode()
    except server.ApiError as e:code=e.status;raw=json.dumps({'error':e.message},ensure_ascii=False).encode()
    except sqlite3.IntegrityError:code=409;raw=json.dumps({'error':'Login yoki sinf allaqachon mavjud'},ensure_ascii=False).encode()
    except (ValueError,TypeError):code=400;raw=b'{"error":"Bad request"}'
    except Exception:code=500;raw=b'{"error":"Server error"}'
    headers=[('Content-Type',ctype),('Content-Length',str(len(raw))),('Cache-Control','no-store'),('X-Content-Type-Options','nosniff')]
    if ctype=='application/pdf':headers.append(('Content-Disposition','attachment; filename="Hisobot.pdf"'))
    start_response(str(code)+' '+HTTPStatus(code).phrase,headers);return [raw]

if __name__=='__main__':
    import os
    from waitress import serve
    config=server.ROOT/'config.json'
    if config.exists():
        for key,value in json.loads(config.read_text(encoding='utf-8')).items():os.environ.setdefault(key,str(value))
    server.init();threading.Thread(target=server.worker,daemon=True).start()
    print('Maktab Hisobot porti:',os.getenv('PORT','8080'),'| Internet uchun HTTPS proksi kerak.')
    serve(application,host=os.getenv('HOST','127.0.0.1'),port=int(os.getenv('PORT','8080')),threads=24,max_request_body_size=1_000_000)
