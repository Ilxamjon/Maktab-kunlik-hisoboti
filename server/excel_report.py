"""First sheet of the school attendance workbook: one compiled row per school."""
import io
from datetime import date
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from catalog import REASONS, EXCUSED, UNEXCUSED

MONTHS=('','Yanvar','Fevral','Mart','Aprel','May','Iyun','Iyul','Avgust','Sentabr','Oktabr','Noyabr','Dekabr')
HEADERS=(
    'Kasalligi tufayli',
    'Tadbirlarda (tanlov, musobaqalarda) ishtiroki sababli',
    'Oilaviy tadbirlar (to‘y, marosim) uchun ruxsat olganlar',
    'Ijtimoiy ahvoli og‘irligi uchun',
    'Boshqa sabablarga ko‘ra',
    'Surunkali dars qoldirayotgan',
    'Qidiruvda bo‘lgan oila farzandlari',
    'Chet elga ruxsatsiz chiqib ketganlar',
    'Ta’limdan bo‘yin tovlaganlar',
    'Darsga kelmasdan ishlab yurganlar',
    'Ta’lim olishga ota-onasi qarshilar',
    'Jazoni o‘tash muassasasida yoki tergovda',
    'Diniy libosda bo‘lganlar uchun',
    'Ota-ona nazoratsizligi',
    'Oilaviy sharoitiga ko‘ra',
    'Sababsiz dars qoldiradi',
    'Turmushga chiqqanligi tufayli',
)
XLSX='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

def make_summary_xlsx(rows,period,school=None):
    school=school or {}
    name=school.get('name') or 'Maktab'
    day=date.fromisoformat(period)
    submitted=[row for row in rows if row.get('submitted')]
    counts=[sum(row['counts'][i] for row in submitted) for i in range(len(REASONS))]
    total=sum(row['total'] for row in submitted)
    absent=sum(counts[1:])
    excused=sum(counts[i] for i in EXCUSED)
    unexcused=sum(counts[i] for i in UNEXCUSED)
    percent=round(counts[0]*100/total,2) if total else '-'
    numbers=[total,percent,absent,excused]+[counts[i] for i in EXCUSED]+[unexcused]+[counts[i] for i in UNEXCUSED]
    book=Workbook();sheet=book.active;sheet.title='Davomat'
    thin=Border(*(Side(style='thin',color='A3ACB5'),)*4)
    center=Alignment(horizontal='center',vertical='center',wrap_text=True)
    left=Alignment(horizontal='left',vertical='center',wrap_text=True)
    head_font=Font(name='Calibri',bold=True,size=9)
    body_font=Font(name='Calibri',size=10)
    fill=PatternFill('solid',fgColor='E7EEF5')
    sheet.merge_cells('A1:X1')
    sheet['A1']=name+"ning ta’lim jarayonida ishtirok etayotgan o‘quvchilar to‘g‘risida MA’LUMOT"
    sheet['A1'].font=Font(name='Calibri',bold=True,size=13)
    sheet['A1'].alignment=center
    sheet.merge_cells('S2:X2')
    sheet['S2']=MONTHS[day.month]+' holati'
    sheet['S2'].font=head_font
    sheet['S2'].alignment=center
    top=('t/r','Maktab raqami',"Jami o‘quvchilar soni",'Davomat (%)',"Darsga kelmagan o‘quvchilar soni",'Sababli')
    for index,text in enumerate(top,1):
        cell=sheet.cell(3,index,text)
        sheet.merge_cells(start_row=3,start_column=index,end_row=4,end_column=index)
        cell.alignment=center
    sheet.merge_cells('G3:K3');sheet['G3']='Shundan:'
    sheet.merge_cells('L3:L4');sheet['L3']='Sababsiz'
    sheet.merge_cells('M3:X3');sheet['M3']='Shundan:'
    for index,text in enumerate(HEADERS[:5]):sheet.cell(4,7+index,text)
    for index,text in enumerate(HEADERS[5:]):sheet.cell(4,13+index,text)
    for column in range(1,25):
        sheet.cell(5,column,column)
        for row in (3,4,5):
            cell=sheet.cell(row,column)
            cell.font=head_font;cell.alignment=center;cell.fill=fill;cell.border=thin
    sheet.merge_cells('A6:B6');sheet['A6']='JAMI:'
    sheet['A7']=1;sheet['B7']=name
    for offset,value in enumerate(numbers):
        sheet.cell(6,3+offset,value)
        sheet.cell(7,3+offset,value)
    for row in (6,7):
        for column in range(1,25):
            cell=sheet.cell(row,column)
            cell.font=body_font;cell.border=thin
            cell.alignment=left if column==2 else center
    sheet.merge_cells('A9:X9')
    sheet['A9']='Direktor: '+(school.get('director') or '____________________')
    sheet.merge_cells('A10:X10')
    sheet['A10']='Ijrochi: '+(school.get('executor') or '____________________')
    missing=[row['class'] for row in rows if not row.get('submitted')]
    if missing:
        sheet.merge_cells('A12:X12')
        sheet['A12']='Jo‘natmagan sinflar: '+', '.join(missing)+'. Jadvaldagi sonlar faqat jo‘natilgan sinflardan yig‘ilgan.'
        sheet['A12'].font=Font(name='Calibri',italic=True,size=10)
    sheet.row_dimensions[1].height=32
    sheet.row_dimensions[4].height=72
    sheet.column_dimensions['A'].width=8
    sheet.column_dimensions['B'].width=28
    for column in range(3,25):sheet.column_dimensions[get_column_letter(column)].width=14
    sheet.page_setup.orientation='landscape'
    sheet.page_setup.fitToPage=True
    sheet.page_setup.fitToWidth=1
    sheet.page_setup.fitToHeight=1
    sheet.freeze_panes='A6'
    stream=io.BytesIO();book.save(stream);return stream.getvalue()
