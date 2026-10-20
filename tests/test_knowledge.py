import json, os, subprocess, sys, tarfile, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from knowledge import Knowledge, dispatch
from parse import sections
from sources import acquire
from versions import detect, choose

class KnowledgeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.docs=self.root/'manual'; self.docs.mkdir()
        (self.docs/'api.md').write_text('# Manual\nGeneral\n## widget.run(value)\nParameters: value is int.\n```python\nwidget.run(42)\n```\n'+'details '*2000)
        (self.docs/'other.rst').write_text('Example\n=======\n\nOther API reference.\n')
        (self.docs/'plain.txt').write_text('Plain text keyword.\n')
        (self.docs/'web.html').write_text('<nav>IGNORE</nav><h1>API</h1><dl><dt id="x">\n<span>widget.html</span>(value)\n</dt><dd>Parameter value<pre># code comment\n  x = 1\n  y = 2</pre>New in version 1.0.</dd></dl><script>EVIL</script>')
        self.cfg=self.root/'sources.json'
        self.sources=[dict(id='one',name='widget',version='1.0.0',type='local',location='manual'),dict(id='two',name='widget',version='2.0.0',type='local',location='manual')]
        self.save(); self.k=Knowledge(str(self.cfg),str(self.root/'store'))
    def save(self): self.cfg.write_text(json.dumps(dict(sources=self.sources)))
    def tearDown(self): self.k.close(); self.temp.cleanup()
    def install(self): return self.k.install('one')
    def test_search_read_versions_and_paging(self):
        self.install(); self.k.install('two')
        (self.root/'requirements.txt').write_text('widget==1.0.0\n')
        result=self.k.search('widget.run',name='widget',cwd=self.root)
        self.assertTrue(result['results']); self.assertTrue(all(r['version']=='1.0.0' for r in result['results']))
        self.assertLess(len(json.dumps(result)),5000)
        hit=result['results'][0]; part=self.k.read(hit['id'],length=30)
        self.assertEqual(len(part['text']),30); self.assertEqual(part['next_offset'],30)
        rest=self.k.read(hit['id'],offset=30,length=80000)
        self.assertLessEqual(len(rest['text']),8000)
        self.assertRaises(ValueError,self.k.read,hit['id'],offset=-1)
        (self.root/'requirements.txt').write_text('widget==3.0.0')
        missing=self.k.search('widget',name='widget',cwd=self.root)
        self.assertEqual(missing['results'],[]); self.assertIn('No exact',str(missing['warnings']))
        explicit=self.k.search('widget',name='widget',version='2.0.0',cwd=self.root)
        self.assertTrue(explicit['results']); self.assertTrue(explicit['warnings'])
    def test_offline_rebuild_remove(self):
        self.install()
        with patch('urllib.request.OpenerDirector.open',side_effect=AssertionError('network forbidden')):
            result=self.k.search('widget',name='widget',version='1.0.0',cwd=self.root)
            self.assertTrue(result['results']); self.k.read(result['results'][0]['id']); self.k.rebuild()
        self.k.remove('widget','1.0.0'); self.assertEqual(self.k.list(),[])
        self.assertRaises(ValueError,self.k.read,result['results'][0]['id'])
    def test_failed_update_preserves_old(self):
        self.install(); old=self.k.list()
        for p in self.docs.iterdir(): p.unlink()
        self.assertRaises(ValueError,self.k.install,'one'); self.assertEqual(self.k.list(),old)
    def test_html_signatures_examples(self):
        parts=list(sections((self.docs/'web.html').read_text(),'.html'))
        self.assertTrue(any(t=='widget.html(value)' and 'New in version 1.0.' in b and '# code comment' in b for t,b in parts))
        text=str(parts); self.assertNotIn('EVIL',text); self.assertNotIn('IGNORE',text); self.assertIn('  x = 1',text)
    def test_archives(self):
        for ext in ('zip','tar.gz'):
            archive=self.root/('manual.'+ext)
            if ext=='zip':
                with zipfile.ZipFile(archive,'w') as z: z.write(self.docs/'api.md','docs/api.md')
            else:
                with tarfile.open(archive,'w:gz') as t: t.add(self.docs/'api.md','docs/api.md')
            work=self.root/ext; work.mkdir(); dest=work/'docs'; dest.mkdir()
            acquire(dict(type='archive',location=archive.name),work,dest,self.root)
            self.assertTrue((dest/'docs/api.md').exists())
    def test_traversal_and_links(self):
        for name in ('../escape.md','/absolute.md','a\\escape.md','C:/escape.md'):
            archive=self.root/'bad.zip'
            with zipfile.ZipFile(archive,'w') as z: z.writestr(name,'bad')
            with self.assertRaises(ValueError): acquire(dict(type='archive',location='bad.zip'),self.root,self.root/'out',self.root)
        archive=self.root/'bad.tar'
        with tarfile.open(archive,'w') as t:
            m=tarfile.TarInfo('link'); m.type=tarfile.SYMTYPE; m.linkname='/etc/passwd'; t.addfile(m)
        self.assertRaises(ValueError,acquire,dict(type='archive',location='bad.tar'),self.root,self.root/'out',self.root)
        (self.docs/'link.md').symlink_to(self.docs/'api.md')
        self.assertRaises(ValueError,self.install)
    def test_errors_and_empty_queries(self):
        self.assertRaises(ValueError,self.k.install,'absent'); self.assertRaises(ValueError,self.k.search,'!!!')
        self.assertRaises(ValueError,self.k.search,'run',version='1.0')
        self.assertRaises(ValueError,self.k.remove,'absent','1')
    def test_lockfiles_and_conflicts(self):
        (self.root/'uv.lock').write_text('[[package]]\nname="widget"\nversion="1.0.0"\n')
        (self.root/'pyproject.toml').write_text('[project]\ndependencies=["widget>=0.9"]\nrequires-python=">=3.12"\n')
        ev=detect(self.root); self.assertEqual(choose('widget',['1.0.0'],ev)[0],['1.0.0'])
        (self.root/'requirements.txt').write_text('widget==2.0.0')
        self.assertEqual(choose('widget',['1.0.0','2.0.0'],detect(self.root))[0],[])
        self.assertEqual(choose('python',['3.12.3'],ev)[0],[])
        (self.root/'package-lock.json').write_text(json.dumps({'packages':{'node_modules/react':{'version':'19.0.0'}}}))
        self.assertEqual(choose('react',['19.0.0'],detect(self.root))[0],['19.0.0'])
    def test_import_and_update(self):
        result=dispatch(self.k,'import',dict(name='imported',version='1.0',path=str(self.docs)))
        self.assertEqual(result['name'],'imported')
        self.install()
        (self.docs/'new.md').write_text('# brandnew\nNew update keyword')
        self.k.install('one')
        self.assertTrue(self.k.search('brandnew',name='widget',version='1.0.0',cwd=self.root)['results'])
        folders=list(self.k.root.glob('doc-*'))
        self.assertEqual(len(folders),2)
    def test_long_section_continues_to_end(self):
        self.install()
        hits=self.k.search('widget.run',name='widget',version='1.0.0',cwd=self.root,limit=8)['results']
        hit=next(h for h in hits if h['path']=='api.md')
        content=''; offset=0
        while True:
            part=self.k.read(hit['id'],offset=offset,length=1000)
            content+=part['text']
            if part['next_offset'] is None: break
            offset=part['next_offset']
        self.assertEqual(len(content),part['total_chars']); self.assertGreater(len(content),16000)
    def test_runtime_files_and_no_project_execution(self):
        (self.root/'.venv').mkdir()
        (self.root/'.venv/pyvenv.cfg').write_text('version = 3.12.3\n')
        (self.root/'.nvmrc').write_text('v22.19.0')
        ev=detect(self.root)
        self.assertEqual(choose('python',['3.12.3'],ev)[0],['3.12.3'])
        self.assertEqual(choose('node',['22.19.0'],ev)[0],['22.19.0'])
        # A project-provided PATH wrapper must never be executed by version detection.
        wrapper=self.root/'python3'; wrapper.write_text('#!/bin/sh\ntouch "'+str(self.root/'executed')+'"\n')
        wrapper.chmod(0o755)
        with patch.dict(os.environ,{'PATH':str(self.root)}): detect(self.root)
        self.assertFalse((self.root/'executed').exists())
    def test_concurrent_cli_updates(self):
        backend=Path(__file__).resolve().parents[1]/'backend/knowledge.py'
        cmd=[sys.executable,str(backend),'--config',str(self.cfg),'--store',str(self.k.root),'install','--source','one']
        a=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        b=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        for proc in (a,b):
            out,err=proc.communicate(timeout=30)
            self.assertEqual(proc.returncode,0,(out,err))
        self.assertEqual(len(self.k.list()),1)
        self.assertEqual(len(list(self.k.root.glob('doc-*'))),1)
    def test_download_limits_and_checksum(self):
        self.assertRaises(ValueError,acquire,dict(type='url',location='http://example.com/x'),self.root,self.root/'out',self.root)
        with zipfile.ZipFile(self.root/'small.zip','w') as z: z.writestr('x.md','foo')
        self.assertRaises(ValueError,acquire,dict(type='archive',location='small.zip',sha256='bad'),self.root,self.root/'out',self.root)
        with patch('sources.MAX_FILE',1):
            self.assertRaises(ValueError,acquire,dict(type='archive',location='small.zip'),self.root,self.root/'out',self.root)

if __name__=='__main__': unittest.main()
