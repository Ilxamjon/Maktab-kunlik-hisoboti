"""PDF follows the school Excel template: 24-column summary and 9-column absentees list."""
import io
from datetime import date
from pathlib import Path
from xml.sax.saxutils import escape
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, Flowable
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4, landscape
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from catalog import REASONS, EXCUSED, UNEXCUSED
pdfmetrics.registerFont(TTFont('School',str(Path(__file__).parent/'fonts/DejaVuSans.ttf')))
STYLE=ParagraphStyle('body',fontName='School',fontSize=8,leading=11)
SMALL=ParagraphStyle('small',fontName='School',fontSize=6.5,leading=8)
TITLE=ParagraphStyle('title',fontName='School',fontSize=11,leading=15,textColor=colors.HexColor('#12375c'),alignment=1)
CENTER=ParagraphStyle('center',fontName='School',fontSize=8,leading=10,alignment=1)
MONTHS=('','Yanvar','Fevral','Mart','Aprel','May','Iyun','Iyul','Avgust','Sentabr','Oktabr','Noyabr','Dekabr')
GRID=colors.HexColor('#a3acb5');HEAD=colors.HexColor('#e7eef5')
def p(x,style=STYLE):return Paragraph(escape(str(x)),style)
class Vertical(Flowable):
    def __init__(self,text,height=155):
        Flowable.__init__(self);self.width=16;self.height=height;self.label=p(text,SMALL)
    def draw(self):
        self.canv.saveState();self.canv.translate(3,6);self.canv.rotate(90)
        _,h=self.label.wrap(self.height-10,40);self.label.drawOn(self.canv,0,-h+6);self.canv.restoreState()
def tbl(data,widths,header=1,spans=()):
    cells=[[v if isinstance(v,Flowable) else p(v,SMALL) for v in row] for row in data]
    t=Table(cells,colWidths=widths,repeatRows=header,hAlign='LEFT')
    style=[('GRID',(0,0),(-1,-1),.35,GRID),('BACKGROUND',(0,0),(-1,header-1),HEAD),('VALIGN',(0,0),(-1,-1),'MIDDLE'),('ALIGN',(0,0),(-1,header-1),'CENTER'),('LEFTPADDING',(0,0),(-1,-1),2),('RIGHTPADDING',(0,0),(-1,-1),2),('TOPPADDING',(0,0),(-1,-1),4),('BOTTOMPADDING',(0,0),(-1,-1),4)]
    style.extend(spans);t.setStyle(TableStyle(style));return t
def period_parts(period,monthly):
    if monthly:
        year,month=period.split('-');name=MONTHS[int(month)]
        return name+' oyi uchun',name+' holatiga'
    day=date.fromisoformat(period)
    return day.isoformat(),MONTHS[day.month]+' holatiga'

def missing_page(story,rows,period,name,detail_when):
    story.extend([PageBreak(),p('Hisobot jo‘natmagan sinf rahbarlari',TITLE),p(name+' — '+detail_when,CENTER),Spacer(1,8)])
    missing=[r for r in rows if not r.get('submitted')]
    if not missing:
        story.append(p('Barcha sinf rahbarlari hisobotni jo‘natgan.'));return
    table=[['t/r','Sinf','Sinf rahbari F.I.Sh.','Login','Holat']]
    for r in sorted(missing,key=lambda r:(r.get('day',period),r['class'])):
        extra=(' • '+r.get('day','')) if r.get('day') and r.get('day')!=period else ''
        table.append([len(table),r['class'],r.get('teacher_name') or r.get('teacher_login') or '—',r.get('teacher_login') or '—','Jo‘natmadi'+extra])
    table.append(['','JAMI: '+str(len(missing))+' sinf','','',''])
    story.append(tbl(table,[36,80,220,120,140]))

def make_pdf(rows,period,school=None,monthly=False,calendar_configured=True):
    school=school or {};name=school.get('name') or 'Maktab';code=school.get('code') or ''
    stream=io.BytesIO();doc=SimpleDocTemplate(stream,pagesize=landscape(A4),leftMargin=22,rightMargin=22,topMargin=22,bottomMargin=30)
    submitted=[r for r in rows if r['submitted']];missing=[r for r in rows if not r['submitted']]
    counts=[sum(r['counts'][i] for r in submitted) for i in range(len(REASONS))]
    total=sum(r['total'] for r in submitted);absent=sum(counts[1:]);excused=sum(counts[i] for i in EXCUSED);unexcused=sum(counts[i] for i in UNEXCUSED)
    pct=f'{counts[0]*100/total:.2f}' if total else '-'
    complete=bool(rows) and not missing and (not monthly or calendar_configured)
    summary_when,detail_when=period_parts(period,monthly)
    story=[p(name,TITLE),p('Ta’lim jarayonida ishtirok etayotgan o‘quvchilar to‘g‘risida MA’LUMOT',TITLE),p(summary_when,CENTER),Spacer(1,6)]
    if not complete:story.extend([p('QISMAN HISOBOT — faqat topshirilgan ma’lumotlar hisoblangan.'),p('Hisobot kutilayotgan sinf-kunlar: '+str(len(missing)))])
    if monthly:
        story.append(p('Jami ustuni o‘quvchi-kunlarni bildiradi. Foiz = kelgan o‘quvchi-kun / topshirilgan jami o‘quvchi-kun × 100.'))
        if not calendar_configured:story.append(p('O‘quv kunlari taqvimi kiritilmagan. Oy to‘liqligi aniqlanmagan.'))
    story.append(Spacer(1,8))
    tall=Vertical
    row0=['t/r','Maktab raqami',tall('Jami o‘quvchilar soni'),tall('Davomat (%)'),tall('Darsga kelmagan o‘quvchilar soni'),tall('Sababli'),'Shundan:','','','','',tall('Sababsiz'),'Shundan:']+['']*11
    row1=['','','','','','']+[tall(REASONS[i]) for i in EXCUSED]+['']+[tall(REASONS[i]) for i in UNEXCUSED]
    values=[1,name,total,pct,absent,excused]+[counts[i] for i in EXCUSED]+[unexcused]+[counts[i] for i in UNEXCUSED]
    widths=[22,96,36,40,36,30]+[23]*5+[30]+[23]*12
    spans=[('SPAN',(0,0),(0,1)),('SPAN',(1,0),(1,1)),('SPAN',(2,0),(2,1)),('SPAN',(3,0),(3,1)),('SPAN',(4,0),(4,1)),('SPAN',(5,0),(5,1)),('SPAN',(6,0),(10,0)),('SPAN',(11,0),(11,1)),('SPAN',(12,0),(23,0))]
    story.append(tbl([row0,row1,values],widths,header=2,spans=spans))
    story.extend([Spacer(1,14),p('Direktor: '+(school.get('director') or '____________________')+'       Imzo: ______________'),p('Ijrochi: '+(school.get('executor') or '____________________'))])
    story.extend([PageBreak(),p('Ixtisoslashtirilgan ta’lim muassasasi tasarrufidagi maktabning ta’lim jarayonida ishtirok etmagan o‘quvchilar to‘g‘risida',TITLE),p('MA’LUMOT',TITLE),p(name+' — '+detail_when,CENTER),Spacer(1,8)])
    details=[['t/r','Darsga kelmagan o‘quvchining F.I.Sh.','Sana','O‘quvchining sinfi','O‘quvchining yashash manzili','Darsga qatnashmaganlik sababi','O‘g‘il','Qiz','Jami']]
    boys=girls=0
    for r in sorted(submitted,key=lambda r:(r.get('day',period),r['class'])):
        for e in sorted(r['entries'],key=lambda e:e['name']):
            if not e['status']:continue
            male=int(e['gender']=='M');female=int(e['gender']=='F');boys+=male;girls+=female
            reason=REASONS[e['status']]+(' — '+e['note'] if e.get('note') else '')
            details.append([len(details),e['name'],r.get('day',period),r['class'],e.get('address') or '',reason,male or '',female or '',1])
    if len(details)==1:details.append(['','Kelmaganlar qayd etilmagan','','','','','','',''])
    details.append(['','JAMI','','','','',boys,girls,boys+girls])
    story.append(tbl(details,[28,148,62,48,150,168,34,34,36]))
    story.extend([Spacer(1,12),p('Direktor: '+(school.get('director') or '____________________')+'       Imzo: ______________'),p('Ijrochi: '+(school.get('executor') or '____________________'))])
    missing_page(story,rows,period,name,detail_when)
    def footer(canvas,doc):
        canvas.setFont('School',8);canvas.drawString(22,16,'Maktab Hisobot • '+(code+' • ' if code else '')+period);canvas.drawRightString(820,16,str(doc.page))
    doc.build(story,onFirstPage=footer,onLaterPages=footer);return stream.getvalue()
