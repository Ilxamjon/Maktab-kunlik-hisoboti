"""Deputy workbook in the school sample shape: summary sheet plus absentee list."""
import io
import re
from datetime import date, datetime
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, Side
from openpyxl.utils import get_column_letter
from catalog import EXCUSED, REASONS, UNEXCUSED, EXCEL_LABELS

MONTHS=('','Yanvar','Fevral','Mart','Aprel','May','Iyun','Iyul','Avgust','Sentabr','Oktabr','Noyabr','Dekabr')
HEADERS=(
    'Kasalligi tufayli',
    'Tadbirlarda (tanlov, musoboqalarda)ishtiroki sabali',
    "Oilaviy tadbirlar to'y, maraka) uchun ruxsat olganlar",
    "Ijtimoiy ahvoli og'irligi uchun (kiyim boshi yo'qligi, kam ta'minlanganligi)",
    "Boshqa sabablarga ko'ra",
    'Surunkali dars qoldirayotgan',
    "Qidiruvda bo'lgan oila farzandlari",
    'Chet elga ruxsatsiz chiqib ketganlar',
    "Ta'limdan bo'yin tovlaganlar",
    'Darsga kelmasdan ishlab yurganlar',
    "Ta'lim olishga ota-onasi qarshilar",
    "Jazoni o'tash muassasalarida yoki tergovda",
    "Diniy libosda bo'lganlar uchun",
    'Ota-ona nazoratsizligi',
    "Oilaviy sharoitiga ko'ra",
    'Sababsiz dars qoldiradi',
    'Turmushga chiqqanligi tufayli',
)
XLSX='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
THIN=Border(left=Side(style='thin',color='000000'),right=Side(style='thin',color='000000'),top=Side(style='thin',color='000000'),bottom=Side(style='thin',color='000000'))

def _font(size,bold=False,italic=False):
    return Font(name='Times New Roman',size=size,bold=bold,italic=italic)

def _align(horizontal='center',wrap=True,rotation=0):
    return Alignment(horizontal=horizontal,vertical='center',wrap_text=wrap,textRotation=rotation)

def _write(sheet,row,col,value,size=14,bold=False,italic=False,horizontal='center',wrap=True,rotation=0,fmt=None):
    cell=sheet.cell(row,col,value)
    cell.font=_font(size,bold,italic)
    cell.alignment=_align(horizontal,wrap,rotation)
    if fmt:cell.number_format=fmt
    return cell

def class_label(name):
    match=re.fullmatch(r'(\d{1,2})[-\s]?([A-Za-zА-Яа-яЁё])',(name or '').strip())
    if match:return match.group(1)+'-'+match.group(2).upper()
    return (name or '').strip()

def period_titles(period,scope):
    if scope=='year':
        start=int(str(period)[:4])
        label=f"{start}–{start+1}-o'quv yili"
        return label+" holati",label+" holatiga"
    if scope=='month':
        name=MONTHS[int(str(period).split('-')[1])]
        return name+' holati',name+' holatiga'
    day=date.fromisoformat(period)
    stamp=f'{day.day:02d}.{day.month:02d}.{day.year}'
    return stamp+' holati',stamp+' holatiga'

def sheet_titles(period,scope):
    if scope=='year':
        start=int(str(period)[:4])
        return 'Давомат',f'{start}-{start+1}'
    if scope=='month':
        month=int(str(period).split('-')[1])
        year=int(str(period).split('-')[0])
        import calendar
        last=calendar.monthrange(year,month)[1]
        return f'Давомат{month:02d}',f'01-{last:02d}.{month:02d}'
    day=date.fromisoformat(period)
    return f'Давомат{day.month:02d}',f'{day.day:02d}.{day.month:02d}'

def _counts(rows):
    submitted=[row for row in rows if row.get('submitted')]
    counts=[sum(row['counts'][i] for row in submitted) for i in range(len(REASONS))]
    total=sum(row['total'] for row in submitted)
    absent=sum(counts[1:])
    excused=sum(counts[i] for i in EXCUSED)
    unexcused=sum(counts[i] for i in UNEXCUSED)
    percent=round((total-absent)*100/total,2) if total else 0
    numbers=[total,percent,absent,excused]+[counts[i] for i in EXCUSED]+[unexcused]+[counts[i] for i in UNEXCUSED]
    return submitted,numbers

def _summary_sheet(book,rows,period,school,scope):
    name=school.get('name') or 'Maktab'
    submitted,numbers=_counts(rows)
    status,detail=period_titles(period,scope)
    first,second=sheet_titles(period,scope)
    sheet=book.active
    sheet.title=first
    sheet.merge_cells('A1:X1')
    _write(sheet,1,1,f"{name}ning ta'lim jarayonida ishtirok etayotgan o'quvchilar to'g'risida\nMA'LUMOT",20,True,wrap=True)
    sheet.merge_cells('S2:X2')
    _write(sheet,2,19,status,20,True,True,'right')
    tops=('t/r','Maktab raqami',"Jami o'quvchilar soni",'Davomat\n(%)',"Darsga kelmagan o'quvchilar soni",'Sababli')
    for index,text in enumerate(tops,1):
        sheet.merge_cells(start_row=3,start_column=index,end_row=4,end_column=index)
        rotation=90 if index==6 else 0
        _write(sheet,3,index,text,14,True,rotation=rotation)
    sheet.merge_cells('G3:K3')
    _write(sheet,3,7,'Shundan:',16,True,wrap=False)
    sheet.merge_cells('L3:L4')
    _write(sheet,3,12,'Sababsiz',14,True,rotation=90)
    sheet.merge_cells('M3:X3')
    _write(sheet,3,13,'Shundan:',16,True,wrap=False)
    for index,text in enumerate(HEADERS[:5]):_write(sheet,4,7+index,text,14,True,rotation=90)
    for index,text in enumerate(HEADERS[5:]):_write(sheet,4,13+index,text,14,True,rotation=90)
    for column in range(1,25):_write(sheet,5,column,column,11,True)
    sheet.merge_cells('A6:B6')
    _write(sheet,6,1,'JAMI:',16,True,horizontal='left',wrap=False)
    for offset,value in enumerate(numbers):
        fmt='0.00' if offset==1 else '0'
        _write(sheet,6,3+offset,value,16,True,fmt=fmt)
    _write(sheet,7,1,1,16)
    _write(sheet,7,2,name,16,horizontal='center')
    for offset,value in enumerate(numbers):
        fmt='0.00' if offset==1 else '0'
        _write(sheet,7,3+offset,value,16,fmt=fmt)
    for row in range(3,8):
        for column in range(1,25):
            sheet.cell(row,column).border=THIN
            sheet.cell(row,column).alignment=Alignment(horizontal='center',vertical='center',wrap_text=True,textRotation=sheet.cell(row,column).alignment.textRotation or 0)
    sheet.merge_cells('A9:X9')
    _write(sheet,9,1,'Direktor:                           '+(school.get('director') or '____________________'),20,True,horizontal='center',wrap=False)
    sheet.merge_cells('A10:C10')
    _write(sheet,10,1,'Ijrochi: '+(school.get('executor') or '____________________'),14,italic=True,horizontal='left',wrap=False)
    missing=[row['class'] for row in rows if not row.get('submitted')]
    if missing and scope=='day':
        sheet.merge_cells('A12:X12')
        _write(sheet,12,1,'Jo‘natmagan sinflar: '+', '.join(class_label(item) for item in missing)+'. Jadvaldagi sonlar faqat jo‘natilgan sinflardan yig‘ilgan.',12,italic=True,horizontal='left')
    elif scope!='day':
        missed=sum(1 for row in rows if not row.get('submitted'))
        if missed:
            sheet.merge_cells('A12:X12')
            _write(sheet,12,1,f"Jo‘natilmagan sinf-kunlar: {missed}. Jadvaldagi sonlar jo‘natilgan o‘quv kunlaridan yig‘ilgan.",12,italic=True,horizontal='left')
    heights={1:100.5,2:36,3:33.75,4:235.5,5:21,6:41.25,7:41.25,8:27,9:44.25,10:32.25}
    for row,height in heights.items():sheet.row_dimensions[row].height=height
    widths={'A':5.71,'B':24,'C':17.86,'D':15.14,'E':15.57,'F':10.14,'J':13,'K':10.14}
    for column in range(1,25):
        letter=get_column_letter(column)
        sheet.column_dimensions[letter].width=widths.get(letter,8.5)
    sheet.page_setup.orientation='landscape'
    sheet.page_setup.paperSize=9
    sheet.page_setup.fitToWidth=1
    sheet.page_setup.fitToHeight=1
    sheet.page_setup.scale=45
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    return second,detail

def _detail_sheet(book,title,detail,rows,school):
    name=school.get('name') or 'Maktab'
    sheet=book.create_sheet(title)
    sheet.merge_cells('A1:I1')
    _write(sheet,1,1,"Ixtisoslashtirilgan ta'lim muassasasi agentligiga qarashli  "+name+" ta'lim jarayonida ishtirok etmagan o'quvchilar to'g'risida\nMA'LUMOT",20,True)
    sheet.merge_cells('H2:I2')
    _write(sheet,2,8,detail,16,True,horizontal='right')
    headers=(
        'т/р',
        "Darsga kelmagan o'quvchining                    F.I.Sh.\n(to'liq yozilishi shart)",
        'Sana',
        'Maktab raqami yoki nomi',
        "O'quvchining sinfi  (to'liq yozilishi shart)",
        "Darsga qatnashmaganlik sabablari\n (to'liq yozilishi shart)",
        "O'g'il\n(1 raqami yoziladi)",
        'Qiz\n (1 raqami yoziladi)',
        'Jami',
    )
    for index,text in enumerate(headers,1):_write(sheet,3,index,text,16,True)
    people=[]
    for row in sorted(rows,key=lambda item:(item.get('day') or '',item.get('class') or '')):
        if not row.get('submitted'):continue
        for entry in sorted(row.get('entries') or [],key=lambda item:item.get('name') or ''):
            status=int(entry.get('status') or 0)
            if status<=0 or status>=len(REASONS):continue
            people.append((row,entry,status))
    for index,(row,entry,status) in enumerate(people,1):
        excel_row=3+index
        day=date.fromisoformat(row['day']) if row.get('day') else None
        boy=1 if entry.get('gender')=='M' else ''
        girl=1 if entry.get('gender')=='F' else ''
        reason=EXCEL_LABELS[status]
        if entry.get('note'):reason=reason+' — '+entry['note']
        values=(index,entry.get('name') or '',datetime(day.year,day.month,day.day) if day else '',name,class_label(row.get('class')),reason,boy,girl,1)
        for column,value in enumerate(values,1):
            fmt='dd\\.mm\\.yyyy' if column==3 else ('0' if column in (1,7,8,9) and value!='' else None)
            horizontal='center' if column!=2 else 'left'
            _write(sheet,excel_row,column,value,16,horizontal=horizontal,wrap=column!=2,fmt=fmt)
            sheet.cell(excel_row,column).border=THIN
        sheet.row_dimensions[excel_row].height=22
    total_row=5+len(people)
    boys=sum(1 for _,entry,_ in people if entry.get('gender')=='M')
    girls=sum(1 for _,entry,_ in people if entry.get('gender')=='F')
    _write(sheet,total_row,6,'Jami',16,True)
    _write(sheet,total_row,7,boys,16,True,fmt='0')
    _write(sheet,total_row,8,girls,16,True,fmt='0')
    _write(sheet,total_row,9,boys+girls,16,True,fmt='0')
    for column in range(6,10):sheet.cell(total_row,column).border=THIN
    _write(sheet,total_row+2,3,'Direktor:                           '+(school.get('director') or '____________________'),16,True,horizontal='left',wrap=False)
    _write(sheet,total_row+3,2,'Ijrochi: '+(school.get('executor') or '____________________'),14,italic=True,horizontal='left',wrap=False)
    for column in range(1,10):sheet.cell(3,column).border=THIN
    sheet.row_dimensions[1].height=100.9
    sheet.row_dimensions[2].height=47.25
    sheet.row_dimensions[3].height=81
    for letter,width in zip('ABCDEFGHI',(7.43,35.86,17.57,27.14,22.86,35.86,20.14,16.43,13.29)):
        sheet.column_dimensions[letter].width=width
    sheet.page_setup.orientation='landscape'
    sheet.page_setup.paperSize=9
    sheet.page_setup.fitToWidth=1
    sheet.page_setup.fitToHeight=0
    sheet.sheet_properties.pageSetUpPr.fitToPage=True
    sheet.auto_filter.ref=None

def make_summary_xlsx(rows,period,school=None,scope='day'):
    school=school or {}
    book=Workbook()
    second,detail=_summary_sheet(book,rows,period,school,scope)
    _detail_sheet(book,second,detail,rows,school)
    stream=io.BytesIO();book.save(stream);return stream.getvalue()
