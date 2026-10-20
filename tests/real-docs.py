"""Integration test against separately installed real documents (no network required)."""
import argparse, json, sys, tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from knowledge import Knowledge
p=argparse.ArgumentParser(); p.add_argument('--store',required=True); args=p.parse_args()
k=Knowledge(store=args.store)
try:
    with tempfile.TemporaryDirectory() as tmp, patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('offline')):
        root=Path(tmp); (root/'.python-version').write_text('3.12.3')
        new=k.search('Path.walk',name='python',cwd=root,limit=1)
        assert len(new['results'])==1 and new['results'][0]['version']=='3.12.3'
        assert new['results'][0]['title'].startswith('Path.walk(')
        hit=new['results'][0]; text=''; offset=0; pages=0
        while True:
            section=k.read(hit['id'],offset=offset,length=500)
            assert len(section['text'])<=500
            text+=section['text']; pages+=1
            if section['next_offset'] is None: break
            offset=section['next_offset']
        assert 'New in version 3.12' in text
        (root/'.python-version').write_text('3.11.9')
        old=k.search('Path.walk',name='python',cwd=root,limit=8)
        assert all(r['version']=='3.11.9' for r in old['results'])
        assert not any(r['title'].startswith('Path.walk(') for r in old['results'])
        (root/'.python-version').write_text('3.10.0')
        missing=k.search('Path.walk',name='python',cwd=root)
        assert not missing['results'] and 'No exact' in str(missing['warnings'])
        md=k.search('widget.run',name='example',version='1.0.0',cwd=root)
        rst=k.search('widget.close',name='example',version='1.0.0',cwd=root)
        flask=k.search('Flask',name='flask',version='3.1.0',cwd=root,limit=1)
        assert md['results'] and rst['results'] and flask['results']
        summary=dict(offline=True,python_312_hit=hit,python_311_no_new_api=True,missing_version=missing['warnings'],read_pages=pages,read_chars=len(text),search_chars=len(json.dumps(new)),configured_formats=['md','rst'],git_revision=next(d['revision'] for d in k.list() if d['name']=='flask'))
        print(json.dumps(summary,ensure_ascii=False,indent=2))
finally: k.close()
