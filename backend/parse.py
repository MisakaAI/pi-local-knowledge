"""Loss-minimizing local section extraction; never executes document directives."""
import re
from html.parser import HTMLParser

class HTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts=[]; self.skip=0; self.heading_start=None
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','nav'): self.skip+=1
        if self.skip: return
        a=dict(attrs)
        if re.fullmatch(r'h[1-6]',tag) or (tag=='dt' and ('id' in a or 'sig' in a.get('class','').split())):
            self.parts.append('\n'+('###' if tag=='dt' else '#'*int(tag[1]))+' ')
            self.heading_start=len(self.parts)
        elif tag=='pre': self.parts.append('\n```text\n')
        elif tag in ('p','div','section','li','br','dd','dt','tr'): self.parts.append('\n')
    def handle_endtag(self,tag):
        if tag in ('script','style','nav'):
            self.skip=max(0,self.skip-1); return
        if not self.skip and (re.fullmatch(r'h[1-6]',tag) or tag=='dt') and self.heading_start is not None:
            start=self.heading_start
            self.parts[start:]=[re.sub(r'\s+',' ',''.join(self.parts[start:])).strip()]
            self.heading_start=None
        if not self.skip and tag=='pre': self.parts.append('\n```\n')
        if not self.skip and (re.fullmatch(r'h[1-6]',tag) or tag in ('dt','p','li','dd')): self.parts.append('\n')
    def handle_data(self,data):
        if not self.skip: self.parts.append(data)

def sections(text, suffix):
    if suffix in ('.html','.htm'):
        parser=HTML(); parser.feed(text); text=''.join(parser.parts)
    text=text.replace('\r\n','\n').replace('\x00','')
    if suffix=='.rst':
        text=re.sub(r'(?m)^([^\n]+)\n([=~^-])\2{2,}\s*$',r'## \1',text)
    title='Introduction'; buf=[]; fence=False
    for line in text.splitlines():
        if line.lstrip().startswith(('```','~~~')): fence=not fence
        heading=re.match(r'^#{1,6}\s+(.+)',line) if not fence else None
        if heading:
            if ''.join(buf).strip(): yield title,'\n'.join(buf).strip()
            title=heading[1].strip()[:500]; buf=[line]
        else: buf.append(line)
    if ''.join(buf).strip(): yield title,'\n'.join(buf).strip()
