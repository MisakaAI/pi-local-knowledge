import json, os, shutil, sys, tempfile, unittest, zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
from knowledge import Knowledge, dispatch, locked
from parse import sections
from sources import acquire
from versions import detect, choose, scan

class Base(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
        self.docs=self.root/'manual'; self.docs.mkdir()
        (self.docs/'api.md').write_text('# Widget\n## widget.run(value)\nRun the widget.\n## widget.stop()\nStop everything.\n')
        (self.docs/'zh.md').write_text('# 表格组件\n表格组件支持排序和筛选功能。\n## 分页\n分页组件用于数据很多时。\n')
        self.cfg=self.root/'sources.json'
        self.cfg.write_text(json.dumps(dict(sources=[dict(id='one',name='Widget_Lib',version='1.0.0',type='local',location='manual'),
                                                    dict(id='never',name='other',version='9.9.9',type='local',location='manual')])))
        self.project=self.root/'project'; self.project.mkdir()
        self.k=Knowledge(str(self.cfg),str(self.root/'store'))
    def tearDown(self): self.k.close(); self.temp.cleanup()

class SearchTests(Base):
    def test_name_normalization_and_any_fallback(self):
        self.k.install('one')
        (self.project/'requirements.txt').write_text('widget-lib[extra]==1.0.0\n')
        hit=self.k.search('widget.run',name='widget.lib',cwd=self.project)
        self.assertEqual(hit['searched'],['Widget_Lib@1.0.0']); self.assertEqual(hit['match'],'all')
        self.assertIn('Widget_Lib@1.0.0',hit['sources']); self.assertNotIn('source',hit['results'][0])
        relaxed=self.k.search('stop nonexistentword',name='widget-lib',cwd=self.project)
        self.assertEqual(relaxed['match'],'any'); self.assertTrue(relaxed['results'])
        self.assertIn('any keyword',str(relaxed['warnings']))
        none=self.k.search('run',name='django',cwd=self.project)
        self.assertEqual(none['results'],[]); self.assertIn('Widget_Lib@1.0.0',str(none['warnings']))
    def test_undeclared_docs_are_summarized(self):
        self.k.install('one')
        result=self.k.search('widget',cwd=self.project)
        self.assertEqual(result['results'],[]); self.assertEqual(len(result['warnings']),1)
        self.assertIn('Pass name and version',result['warnings'][0])
    def test_cjk_substring_search(self):
        self.k.install('one')
        result=self.k.search('排序',name='widget_lib',version='1.0.0',cwd=self.project)
        self.assertEqual(result['results'][0]['title'],'表格组件'); self.assertIn('[排序]',result['results'][0]['excerpt'])
        both=self.k.search('分页 数据',name='widget_lib',version='1.0.0',cwd=self.project)
        self.assertEqual(both['results'][0]['title'],'分页')
        self.assertEqual(self.k.search('分页 不存在',name='widget_lib',version='1.0.0',cwd=self.project)['match'],'any')

class ManagementTests(Base):
    def test_sources_update_all_gc_and_moved_store(self):
        self.k.install('one')
        listed=self.k.sources()['sources']
        self.assertEqual([s['installed'] for s in listed],[True,False])
        (self.k.root/'stage-leftover').mkdir(); (self.k.root/'doc-orphan').mkdir()
        updated=locked(self.k,'update',{})
        self.assertEqual(len(updated),1); self.assertEqual(updated[0]['name'],'Widget_Lib')
        self.assertFalse((self.k.root/'stage-leftover').exists()); self.assertFalse((self.k.root/'doc-orphan').exists())
        self.assertEqual(len(list(self.k.root.glob('doc-*'))),1)
        self.k.close(); moved=self.root/'moved'; shutil.move(str(self.root/'store'),moved)
        self.k=Knowledge(str(self.cfg),str(moved))
        self.assertTrue(self.k.search('run',name='widget_lib',version='1.0.0')['results'])
        self.assertEqual(self.k.rebuild()[0]['chunks'],5)
        self.k.remove('Widget_Lib','1.0.0'); self.assertEqual(list(moved.glob('doc-*')),[])
    def test_argument_validation(self):
        for action,args,message in [('install',{},'requires: source'),('search',{},'requires: query'),('read',{'id':''},'requires: id'),
                                    ('import',{'name':'x','version':'1'},'requires: path'),('bogus',{},'Unknown action')]:
            with self.assertRaisesRegex(ValueError,message): dispatch(self.k,action,args)
        with self.assertRaisesRegex(ValueError,'configured'): self.k.install('absent')
        with self.assertRaisesRegex(ValueError,'does not exist'): dispatch(self.k,'import',dict(name='x',version='1',path=str(self.root/'missing')))
        self.assertTrue(dispatch(self.k,'search',dict(query='run',unexpected=1))['warnings'])
    def test_rebuild_reports_missing_snapshot(self):
        self.k.install('one'); shutil.rmtree(next(self.k.root.glob('doc-*')))
        self.assertIn('error',self.k.rebuild()[0])

class SourceTests(Base):
    def test_default_and_custom_excludes(self):
        out=self.root/'out'; (out/'docs').mkdir(parents=True)
        with zipfile.ZipFile(self.root/'site.zip','w') as z:
            for name in ('html/library/a.html','html/_sources/library/a.rst.txt','html/genindex-A.html','html/search.html','html/drafts/x.md'):
                z.writestr(name,'<h1>x</h1>')
        acquire(dict(type='archive',location='site.zip',exclude=['*/drafts/*']),out,out/'docs',self.root)
        self.assertEqual(sorted(p.relative_to(out/'docs').as_posix() for p in (out/'docs').rglob('*') if p.is_file()),['html/library/a.html'])
        self.assertRaises(ValueError,acquire,dict(type='archive',location='site.zip',exclude='*'),out,out/'docs',self.root)

class ParseTests(unittest.TestCase):
    def test_sphinx_chrome_tables_and_permalinks(self):
        html='''<head><title>Page title</title></head><div class="related" role="navigation">Previous topic</div>
        <h1>pathlib<a class="headerlink" href="#p">¶</a></h1><p>Intro</p><table><tr><th>A</th><th>B</th></tr><tr><td>1</td><td>2</td></tr></table>
        <dl><dt class="sig sig-object py" id="x">Path.walk(<em>top_down=True</em>)<a class="headerlink">¶</a></dt><dd><div><div>Body</div></div></dd></dl>
        <div class="sphinxsidebar" role="navigation"><div><h3>This page</h3>Show source</div></div><p>After</p>'''
        parts=list(sections(html,'.html')); text=str(parts)
        self.assertEqual([t for t,_ in parts],['pathlib','Path.walk(top_down=True)'])
        for junk in ('¶','Previous topic','This page','Show source','Page title'): self.assertNotIn(junk,text)
        self.assertIn(' | A | B',text); self.assertIn('Body',text); self.assertIn('After',text)
        # Void elements never start a skip region, otherwise everything after them would vanish.
        parts=list(sections('<h1>A</h1><input role="search" name="q"><img class="headerlink"><p>Kept</p><br/>x','.html'))
        self.assertIn('Kept',parts[0][1]); self.assertIn('x',parts[0][1])
    def test_markdown_front_matter_setext_and_fences(self):
        md='---\ntitle: Front\nlayout: x\n---\nIntro\n\nGuide\n=====\ntext\n\nSub\n---\n````\n```\n# not a heading\n```\n````\n## C# API ##\nz\n'
        parts=list(sections(md,'.md'))
        self.assertEqual([t for t,_ in parts],['Introduction','Guide','Sub','C# API'])
        self.assertNotIn('layout',str(parts)); self.assertIn('# not a heading',parts[2][1])
    def test_rst_overline_titles(self):
        parts=list(sections('=====\nTitle\n=====\n\nBody.\n\nSection\n*******\nText.\n\n  indented\n  ---------\n','.rst'))
        self.assertEqual([t for t,_ in parts],['Title','Section']); self.assertNotIn('=====',parts[0][1])

class DetectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name)
    def tearDown(self): self.temp.cleanup()
    def write(self,name,text):
        p=self.root/name; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(text); return p
    def pick(self,name,installed,cwd=None): return choose(name,installed,detect(cwd or self.root,hosts=()))[0]
    def test_more_ecosystems(self):
        self.write('Cargo.lock','[[package]]\nname = "serde"\nversion = "1.0.200"\n')
        self.write('go.mod','module x\n\ngo 1.22.1\n\nrequire (\n\tgithub.com/gin-gonic/gin v1.10.0\n\tgolang.org/x/text v0.14.0 // indirect\n)\nrequire github.com/a/b v2.0.0\n')
        self.write('Pipfile.lock',json.dumps({'default':{'requests':{'version':'==2.32.3'}},'develop':{}}))
        self.write('.tool-versions','nodejs 22.1.0\ngolang 1.22.1\n')
        self.write('rust-toolchain.toml','[toolchain]\nchannel = "1.79.0"\n')
        self.assertEqual(self.pick('serde',['1.0.200']),['1.0.200'])
        self.assertEqual(self.pick('github.com/gin-gonic/gin',['1.10.0']),['1.10.0'])
        self.assertEqual(self.pick('github.com/a/b',['2.0.0']),['2.0.0'])
        self.assertEqual(self.pick('go',['1.22.1']),['1.22.1'])
        self.assertEqual(self.pick('requests',['2.32.3']),['2.32.3'])
        self.assertEqual(self.pick('node',['22.1.0']),['22.1.0'])
        self.assertEqual(self.pick('rust',['1.79.0']),['1.79.0'])
    def test_yarn_pnpm_and_poetry(self):
        self.write('package.json',json.dumps({'dependencies':{'react':'^18.2.0'},'devDependencies':{'typescript':'~5.4.0'}}))
        self.write('yarn.lock','# yarn lockfile v1\n\n"react@^17.0.0":\n  version "17.0.2"\n\n"react@^18.2.0", react@^18.0.0:\n  version "18.2.0"\n\n"typescript@npm:~5.4.0":\n  version: 5.4.5\n')
        self.assertEqual(self.pick('react',['17.0.2','18.2.0']),['18.2.0']); self.assertEqual(self.pick('typescript',['5.4.5']),['5.4.5'])
        (self.root/'yarn.lock').unlink()
        self.write('pnpm-lock.yaml',"lockfileVersion: '9.0'\n\nimporters:\n\n  .:\n    dependencies:\n      react:\n        specifier: ^18.2.0\n        version: 18.3.1(react-dom@18.3.1)\n  packages/x:\n    dependencies:\n      react:\n        specifier: ^17\n        version: 17.0.2\n\npackages:\n\n  react@18.3.1:\n    resolution: {integrity: x}\n")
        self.assertEqual(self.pick('react',['18.3.1']),['18.3.1'])
        self.write('pyproject.toml','[tool.poetry.dependencies]\npython = "^3.11"\nflask = "3.1.0"\nrich = {version = "^13"}\n')
        self.assertEqual(self.pick('flask',['3.1.0']),['3.1.0']); self.assertEqual(self.pick('rich',['13.0.0']),[])
        self.assertEqual(self.pick('python',['3.11.0']),[])
    def test_parent_directories_until_git_root(self):
        self.write('.git/HEAD','ref: x'); self.write('package-lock.json',json.dumps({'packages':{'node_modules/vue':{'version':'3.4.0'}}}))
        sub=self.root/'packages/web/src'; sub.mkdir(parents=True)
        self.assertEqual(self.pick('vue',['3.4.0'],sub),['3.4.0'])
        self.write('packages/web/package.json',json.dumps({'dependencies':{'vue':'3.5.0'}}))
        self.assertEqual(self.pick('vue',['3.4.0','3.5.0'],sub),['3.5.0'])
        sources={e['source'] for e in detect(sub,hosts=())}
        self.assertIn('../../../package-lock.json',sources); self.assertIn('../package.json',sources)
        outside=Path(tempfile.mkdtemp(dir=self.root.parent)); self.addCleanup(shutil.rmtree,outside)
        (outside/'child').mkdir(); (outside/'requirements.txt').write_text('x==1.0.0')
        self.assertEqual(detect(outside/'child',hosts=()),[])
    def test_broken_files_do_not_break_detection(self):
        self.write('package.json','{not json'); self.write('uv.lock','[[package]\n'); self.write('.python-version','3.12.3\n')
        evidence,problems=scan(self.root)
        self.assertEqual(choose('python',['3.12.3'],evidence)[0],['3.12.3']); self.assertEqual(len(problems),2)

if __name__=='__main__': unittest.main()
