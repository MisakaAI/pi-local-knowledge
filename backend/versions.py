"""Read project evidence without importing/executing project code."""
import json, re, shutil, subprocess, tomllib
from pathlib import Path

def detect(cwd):
    root=Path(cwd); evidence=[]
    def add(name,version,source,exact=True):
        evidence.append(dict(name=name.lower().replace('_','-'),version=str(version),source=source,exact=exact))
    def text(name):
        p=root/name
        return p.read_text() if p.is_file() and p.stat().st_size<20_000_000 else ''
    for filename in ('uv.lock','poetry.lock'):
        if text(filename):
            for p in tomllib.loads(text(filename)).get('package',[]):
                if 'version' in p: add(p['name'],p['version'],filename)
    if text('package-lock.json'):
        lock=json.loads(text('package-lock.json'))
        for path,p in lock.get('packages',{}).items():
            if path.startswith('node_modules/') and '/node_modules/' not in path and 'version' in p:
                add(path[len('node_modules/'):],p['version'],'package-lock.json')
        for name,p in lock.get('dependencies',{}).items():
            if 'version' in p: add(name,p['version'],'package-lock.json')
    for filename in ('requirements.txt','requirements-dev.txt'):
        for name,op,v in re.findall(r'(?m)^\s*([\w.-]+)\s*(==|~=|>=|<=|>|<)\s*([^\s;#]+)',text(filename)):
            add(name,v,filename,op=='==' and '*' not in v)
    if text('pyproject.toml'):
        project=tomllib.loads(text('pyproject.toml')).get('project',{})
        if project.get('requires-python'): add('python',project['requires-python'],'pyproject.toml',False)
        for dep in project.get('dependencies',[]):
            m=re.match(r'([\w.-]+)(?:\[.*?\])?\s*(==|~=|>=|<=|>|<)\s*([^;\s]+)',dep)
            if m: add(m[1],m[3],'pyproject.toml',m[2]=='==' and '*' not in m[3])
    if text('package.json'):
        p=json.loads(text('package.json'))
        for group in ('dependencies','devDependencies'):
            for name,v in p.get(group,{}).items(): add(name,v,'package.json',bool(re.fullmatch(r'\d+\.\d+\.\d+',v)))
    for filename in ('.venv/pyvenv.cfg','venv/pyvenv.cfg'):
        m=re.search(r'(?m)^version\s*=\s*(\d+\.\d+\.\d+)',text(filename))
        if m: add('python',m[1],filename)
    if text('.python-version'): add('python',text('.python-version').strip(),'.python-version',bool(re.fullmatch(r'\d+\.\d+\.\d+',text('.python-version').strip())))
    if text('.nvmrc'):
        v=text('.nvmrc').strip().lstrip('v'); add('node',v,'.nvmrc',bool(re.fullmatch(r'\d+\.\d+\.\d+',v)))
    # Only trusted host executables, never .venv/bin/python or project scripts.
    for name,cmd in [('python',['python3','--version']),('node',['node','--version'])]:
        try:
            executable=shutil.which(cmd[0])
            if not executable or Path(executable).resolve().is_relative_to(root.resolve()): continue
            out=subprocess.check_output([executable,*cmd[1:]],timeout=3,text=True)
            m=re.search(r'\d+\.\d+\.\d+',out)
            if m: add(name,m[0],'host runtime (not necessarily project runtime)')
        except (OSError,subprocess.SubprocessError): pass
    return evidence

def choose(name,installed,evidence,explicit=None):
    if explicit:
        if explicit not in installed:
            return [], [f'Explicit document version {name}@{explicit} is not installed; installed: {installed}. No cross-version fallback.']
        return [explicit], ['Explicit document version; verify it is the project version.']
    ev=[e for e in evidence if e['name']==name]
    project=[e for e in ev if not e['source'].startswith('host runtime')]
    exact={e['version'] for e in (project or ev) if e['exact']}
    warnings=[]
    if not project and ev: warnings.append('Only host runtime detected; project runtime is unconfirmed.')
    if len(exact)!=1:
        return [],warnings+['Version unknown, ranged, or conflicting; specify version explicitly.']
    wanted=next(iter(exact))
    if wanted not in installed: return [],warnings+[f'No exact documentation for {name}@{wanted}; installed: {installed}. No cross-version fallback.']
    return [wanted],warnings
