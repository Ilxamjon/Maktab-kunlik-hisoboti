"""Read and write a class teacher's Excel roster: F.I.SH, gender, and address."""
import io, re
from openpyxl import Workbook, load_workbook

def _norm(value):
    text=str(value or '').strip().lower()
    text=text.translate(str.maketrans({'ʻ':"'",'ʼ':"'",'‘':"'",'’':"'",'`':"'"}))
    return ' '.join(text.replace("'",'').split())

def _compact(value):
    return re.sub(r'[^a-z0-9а-яёўқғҳ]+','',_norm(value))
name_key=_compact

def class_key(value):
    text=_compact(value).upper()
    if re.fullmatch(r'(?:[1-9]|1[01])[A-ZА-ЯЁ]',text):return text
    return ''

def gender_of(value):
    text=_compact(value)
    if text in ('m','erkak','ogil','ogilbola','bola'):return 'M'
    if text in ('f','qiz','qizbola','ayol'):return 'F'
    return ''

def _header_kind(value):
    text=_compact(value)
    if text in ('fish','fsh') or 'familiya' in text:return 'name'
    if text in ('jinsi','jins'):return 'gender'
    if 'manzil' in text:return 'address'
    return ''

def parse_roster(blob):
    if not blob or len(blob)>2_000_000:raise ValueError('Fayl juda katta yoki bo‘sh')
    try:book=load_workbook(io.BytesIO(blob),data_only=True,read_only=True)
    except Exception as error:raise ValueError('Faylni o‘qib bo‘lmadi. .xlsx ekanini tekshiring.') from error
    rows=[]
    for row in book.active.iter_rows(max_row=200,max_col=8,values_only=True):
        rows.append(list(row))
    book.close()
    header=None
    columns={}
    for index,row in enumerate(rows[:15]):
        found={}
        for column,value in enumerate(row):
            kind=_header_kind(value)
            if kind and kind not in found:found[kind]=column
        if 'name' in found and 'gender' in found:
            header=index;columns=found;break
    if header is None:raise ValueError('Ustunlar topilmadi. Birinchi qatorda F.I.SH, Jinsi va Yashash manzili bo‘lsin.')
    file_class=''
    for row in rows[:header]:
        for index,value in enumerate(row):
            if _compact(value) not in ('sinf','sinfi'):continue
            for other in row[index+1:]:
                key=class_key(other)
                if key:file_class=key;break
    students=[];errors=[]
    seen=set()
    for offset,row in enumerate(rows[header+1:],header+2):
        if len(students)+len(errors)>=80:break
        name=' '.join(str(row[columns['name']] or '').split()) if columns['name']<len(row) else ''
        if not name or name.isdigit():continue
        if not re.search(r'[^\W\d_]',name,re.UNICODE) or len(name)>80:
            errors.append(f"{offset}-qator: ism noto‘g‘ri");continue
        key=_compact(name)
        if key in seen:
            errors.append(f"{offset}-qator: {name} faylda takrorlangan");continue
        seen.add(key)
        raw=row[columns['gender']] if columns['gender']<len(row) else ''
        gender=gender_of(raw)
        if not gender:
            errors.append(f"{offset}-qator: {name} — jinsi yo‘q");continue
        address=''
        if 'address' in columns and columns['address']<len(row) and row[columns['address']] is not None:
            address=' '.join(str(row[columns['address']]).split())
        if len(address)>300:address=address[:300]
        students.append({'name':name,'gender':gender,'address':address,'key':key})
    return {'class_name':file_class,'students':students,'errors':errors}

def display_class(name):
    match=re.fullmatch(r'(\d{1,2})([A-Za-zА-Яа-яЁё])',(name or '').strip())
    if match:return match.group(1)+'-'+match.group(2).upper()
    return (name or '').strip()

def make_roster_xlsx(class_name,students):
    book=Workbook();sheet=book.active;sheet.title='Royxat'
    sheet['A1']='Sinf:';sheet['B1']=display_class(class_name)
    sheet['A4']='№';sheet['B4']='F.I.SH';sheet['C4']='Jinsi';sheet['D4']='Yashash manzili'
    for index,student in enumerate(students,1):
        sheet.cell(4+index,1,index)
        sheet.cell(4+index,2,student.get('name') or '')
        sheet.cell(4+index,3,"O'g'il" if student.get('gender')=='M' else 'Qiz')
        sheet.cell(4+index,4,student.get('address') or '')
    for letter,width in zip('ABCD',(8,32,14,36)):sheet.column_dimensions[letter].width=width
    stream=io.BytesIO();book.save(stream);return stream.getvalue()
