"""Small database compatibility layer: SQLite locally, Neon Postgres in production."""
import os,re,sqlite3

DATABASE_URL=os.getenv('DATABASE_URL','')

class Row(dict):
    def __init__(self,names,values):
        super().__init__(zip(names,values));self._values=tuple(values)
    def __getitem__(self,key):
        return self._values[key] if isinstance(key,int) else super().__getitem__(key)

class Result:
    def __init__(self,cursor):self.cursor=cursor
    def _row(self,value):
        if value is None:return None
        names=[d.name if hasattr(d,'name') else d[0] for d in self.cursor.description]
        return Row(names,value)
    def fetchone(self):return self._row(self.cursor.fetchone())
    def fetchall(self):return [self._row(v) for v in self.cursor.fetchall()]
    def __iter__(self):
        while True:
            row=self.fetchone()
            if row is None:return
            yield row

class PgConnection:
    def __init__(self,connection):self.connection=connection
    def execute(self,sql,args=()):
        cleaned=sql.strip().rstrip(';')
        if cleaned.upper()=='BEGIN IMMEDIATE':return Result(self.connection.execute('SELECT 1 WHERE FALSE'))
        cleaned=cleaned.replace('?','%s')
        match=re.match(r'(?is)^INSERT\s+OR\s+IGNORE\s+INTO\s+(.+)$',cleaned)
        if match:cleaned='INSERT INTO '+match.group(1)+' ON CONFLICT DO NOTHING'
        return Result(self.connection.execute(cleaned,args))
    def close(self):self.connection.close()
    def __enter__(self):return self
    def __exit__(self,kind,value,tb):
        if kind is None:self.connection.commit()
        else:self.connection.rollback()

def is_postgres():return bool(os.getenv('DATABASE_URL','').startswith(('postgres://','postgresql://')))

def postgres_connect():
    import psycopg
    return PgConnection(psycopg.connect(os.environ['DATABASE_URL'],connect_timeout=15))

INTEGRITY_ERRORS=(sqlite3.IntegrityError,)
try:
    import psycopg
    INTEGRITY_ERRORS+=(psycopg.IntegrityError,)
except ImportError:pass
