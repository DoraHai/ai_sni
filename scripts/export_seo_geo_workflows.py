"""Deterministic, shareable workflow PDF and PNGs; no customer data or web calls."""
import argparse
import json
from pathlib import Path
import subprocess

from reportlab.pdfgen.canvas import Canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor

W,H=1000,1680
INK='#203047';MUTED='#596B81';BG='#F4F7FB'
MODES={'human':('#FFF1DC','#98610B','人工确认'),
       'auto':('#E3F4EF','#166C57','自动执行'),
       'joint':('#E6EDFF','#355AA5','人机配合')}


def wrap(text,font,size,width):
    lines=[];current=''
    for char in text:
        if current and pdfmetrics.stringWidth(current+char,font,size)>width:
            lines.append(current);current=char
        else:current+=char
    if current:lines.append(current)
    return lines


def text(c,x,y,value,size=12,color=INK,font='body'):
    c.setFillColor(HexColor(color));c.setFont(font,size);c.drawString(x,H-y,value)


def rounded(c,x,y,w,h,fill,stroke=None,r=12):
    c.setFillColor(HexColor(fill));c.setStrokeColor(HexColor(stroke or fill))
    c.roundRect(x,H-y-h,w,h,r,fill=1,stroke=bool(stroke))


def arrow(c,x1,y1,x2,y2,color='#91A3B9',dash=False):
    c.setStrokeColor(HexColor(color));c.setFillColor(HexColor(color));c.setLineWidth(1.6)
    if dash:c.setDash(4,3)
    c.line(x1,H-y1,x2,H-y2);c.setDash()
    import math
    dx,dy=x2-x1,y2-y1;length=math.hypot(dx,dy)
    if not length:return
    ux,uy=dx/length,dy/length
    p=c.beginPath();p.moveTo(x2,H-y2)
    p.lineTo(x2-ux*7-uy*3,H-(y2-uy*7+ux*3))
    p.lineTo(x2-ux*7+uy*3,H-(y2-uy*7-ux*3));p.close();c.drawPath(p,fill=1,stroke=0)


def node(c,item,x,y,w,h,accent):
    fill,colour,label=MODES[item['mode']]
    rounded(c,x,y,w,h,'#FFFFFF','#D8E1ED')
    rounded(c,x+13,y+13,35,27,accent,r=7);text(c,x+20,y+32,item['id'],13,'#FFFFFF','bold')
    text(c,x+60,y+32,item['title'],15,INK,'bold')
    # A narrow branch places the responsibility label below the title.
    label_y=y+48 if w<310 else y+30
    label_x=x+16 if w<310 else x+w-88
    rounded(c,label_x-4,label_y-15,78,21,fill,r=6);text(c,label_x,label_y,label,10,colour)
    cursor=y+68 if w<310 else y+50
    size=11.5 if w<310 else 12
    for line in item['lines']:
        for segment in wrap(line,'body',size,w-32):
            text(c,x+16,cursor,segment,size,MUTED);cursor+=16
        cursor+=2
    if cursor-3>y+h-10:raise RuntimeError('Workflow card overflow: '+item['id'])


def panel(c,title,lines,x,y,w,h,fill='#FFFFFF'):
    rounded(c,x,y,w,h,fill,'#D8E1ED');text(c,x+18,y+29,title,16,INK,'bold')
    cursor=y+54
    for value in lines:
        for line in wrap(value,'body',12,w-36):text(c,x+18,cursor,line,12,MUTED);cursor+=19
        cursor+=9
    if cursor-9>y+h-10:raise RuntimeError('Sidebar overflow: '+title)


def page(c,data,module):
    accent='#167A67' if module=='seo' else '#5068BA'
    c.setFillColor(HexColor(BG));c.rect(0,0,W,H,fill=1,stroke=0)
    text(c,45,46,'G-SNIPERS  /  最新运营流程',13,accent,'bold')
    text(c,45,90,module.upper()+' 自动化与交付流程',29,INK,'bold')
    text(c,45,118,'顾问主导 · AI 提案与产稿 · 系统按授权执行 · 客户查看交付',13,MUTED)
    text(c,790,46,data['version'],13,MUTED)
    for i,(mode,(_,colour,label)) in enumerate(MODES.items()):
        rounded(c,610+i*105,79,97,26,MODES[mode][0],r=7);text(c,619+i*105,97,label,11,colour)
    text(c,610,119,'自动执行均以授权、配置与能力验收通过为前提。',10,MUTED)
    items={item['id']:item for item in data[module]}
    common=data['shared']
    panel(c,'谁负责什么',common['roles'],610,150,345,265)
    panel(c,'何时需要顾问介入',common['intervention'],610,435,345,238,'#FFF8ED')
    panel(c,'每个任务都要留下记录',common['records'],610,693,345,232)
    panel(c,'自动化边界',common['boundaries'],610,945,345,201)
    panel(c,'实施与验收状态',common['acceptance'],610,1166,345,176,'#EAF0FA')
    panel(c,'本轮推进顺序',[
        '先验收远程登录、截图与有限输入。',
        '再验证电脑凭据、撤权、断线与任务回执。',
        '对已审核稿件验证领取、交接和异常恢复。',
        '新闻源 / 外链接口先建契约，供应商接入后再验收。',
        '不同平台精细排版最后打磨。'],610,1362,345,241)
    left=45;width=540;mid=315
    if module=='seo':
        layout={'01':(left,150,width,100),'02':(left,276,width,100),
                '03':(left,406,260,221),'04':(left+280,406,260,221),
                '05':(left,658,width,119),'06':(left,803,width,100),'07':(left,929,width,100),
                '08':(left,1055,width,145),'09':(left,1226,width,100),'10':(left,1352,width,100)}
        arrow(c,mid,250,mid,276);arrow(c,mid,376,mid,390)
        c.setStrokeColor(HexColor('#91A3B9'));c.line(175,H-390,455,H-390)
        arrow(c,175,390,175,406);arrow(c,455,390,455,406)
        # Content execution follows the approved plan, not website completion.
        arrow(c,mid,390,mid,658)
        text(c,341,646,'站内、监测与内容线可并行推进',10,accent)
        for first,second in [('05','06'),('06','07'),('07','08'),('08','09'),('09','10')]:
            a=layout[first];b=layout[second];arrow(c,mid,a[1]+a[3],mid,b[1])
    else:
        layout={'01':(left,150,width,100),'02':(left,276,width,100),'03':(left,402,width,100),
                '04':(left,533,260,517),'05':(left+280,533,260,155),
                '06':(left+280,714,260,155),'07':(left+280,895,260,155),
                '08':(left,1081,width,144),'09':(left,1251,width,100),
                '10':(left,1377,width,100),'11':(left,1503,width,100)}
        for first,second in [('01','02'),('02','03')]:
            a=layout[first];b=layout[second];arrow(c,mid,a[1]+a[3],mid,b[1])
        arrow(c,mid,502,mid,517);c.setStrokeColor(HexColor('#91A3B9'));c.line(175,H-517,455,H-517)
        arrow(c,175,517,175,533);arrow(c,455,517,455,533)
        arrow(c,455,688,455,714);arrow(c,455,869,455,895);arrow(c,455,1050,455,1081)
        # Website work joins verification directly, not the distribution queue.
        arrow(c,29,790,29,1301,accent,True);arrow(c,29,1301,45,1301,accent,True)
        c.setStrokeColor(HexColor(accent));c.setDash(4,3);c.line(29,H-790,45,H-790);c.setDash()
        for first,second in [('08','09'),('09','10'),('10','11')]:
            a=layout[first];b=layout[second];arrow(c,mid,a[1]+a[3],mid,b[1])
    for ident,coords in layout.items():node(c,items[ident],*coords,accent)
    footer_y=1655
    text(c,45,footer_y,'扫码 / 验证码 → 顾问介入；未知结果 → 核验；修改内容 → 重新审校；复盘 → 下一轮。',10,MUTED)
    text(c,880,footer_y,'1 / 2' if module=='seo' else '2 / 2',10,MUTED)
    c.showPage()


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--poppler',type=Path,required=True);args=parser.parse_args()
    source=Path(__file__).resolve().parents[1]/'docs/fixtures/seo-geo-workflows-20261012.json'
    data=json.loads(source.read_text(encoding='utf-8'))
    pdfmetrics.registerFont(TTFont('body','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
    pdfmetrics.registerFont(TTFont('bold','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
    args.output.mkdir(parents=True,exist_ok=True)
    pdf=args.output/'SEO-GEO-最新流程-20261012.pdf'
    c=Canvas(str(pdf),pagesize=(W,H));c.setTitle('SEO 与 GEO 最新工作流程 2026-10-12')
    c.setAuthor('G-Snipers');page(c,data,'seo');page(c,data,'geo');c.save()
    for index,module in enumerate(('seo','geo'),1):
        target=args.output/(module.upper()+'-流程-20261012')
        subprocess.run([str(args.poppler),'-f',str(index),'-l',str(index),'-singlefile','-r','144','-png',str(pdf),str(target)],check=True,capture_output=True)
    prose=['SEO / GEO 最新流程说明','版本：2026-10-12','',
           '这是一份目标流程说明；新增接口、远程介入和真实发布仍须分别验收。',
           '执行部署：业务云服务器 + 公司专用 Windows 电脑上的多号通。客户和顾问只用网页。',
           'API 新闻源 / 外链由服务器直接执行；无需绕到多号通电脑。','']
    for module in ('seo','geo'):
        prose.append(module.upper()+' 流程')
        for item in data[module]:
            prose.extend([item['id']+' '+item['title']+' ['+MODES[item['mode']][2]+']',*item['lines'],''])
        prose.append('02之后，03站内实施、04持续监测与05开始的内容线可并行；04观测和10复盘反馈下一轮计划。' if module=='seo' else '03之后，04站内建设与05→06→07内容制作并行；站内验收直接关联09，内容通过08发布后关联09。')
        prose.append('')
    for label,key in [('职责','roles'),('人工介入','intervention'),('日志与结果','records'),('边界','boundaries'),('待验收','acceptance')]:
        prose.extend([label,*data['shared'][key],''])
    (args.output/'SEO-GEO-流程文字说明-20261012.txt').write_text('\n'.join(prose)+'\n',encoding='utf-8-sig')
    print(json.dumps({'pdf':str(pdf),'pages':2,'pngs':2,'text':True},ensure_ascii=False))


if __name__=='__main__':main()
