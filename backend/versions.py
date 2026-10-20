"""Read project evidence without importing/executing project code."""
import json, re, shutil, subprocess, tomllib
from pathlib import Path

MAX_FILE=20_000_000
MAX_LEVELS=12
FULL=re.compile(r'\d+\.\d+\.\d+(?:[-.+]?[0-9A-Za-z][0-9A-Za-z.+-]*)?')
SPEC=re.compile(r'^\s*([A-Za-z0-9][\w.-]*)(?:\[[^\]]*\])?\s*(===|==|~=|>=|<=|!=|>|<)\s*([^\s;,#]+)')
ASDF={'python':'python','nodejs':'node','node':'node','golang':'go','go':'go','rust':'rust','ruby':'ruby','java':'java'}

def norm(name):
    """PEP 503-style normalization, applied to both evidence and document names."""
    return re.sub(r'[-_.]+','-',str(name).strip().lower())

def exact(v): return bool(FULL.fullmatch(v))

def project_dirs(cwd):
    """cwd plus its parents up to the enclosing Git root; only cwd outside a repository."""
    start=Path(cwd).resolve(); chain=[start]
    for d in [start,*start.parents][:MAX_LEVELS]:
        if d!=start: chain.append(d)
        if (d/'.git').exists(): return chain
    return [start]

def scan(cwd):
    """Collect project version evidence. Returns (evidence, problems); never raises on bad files."""
    evidence=[]; problems=[]
    dirs=project_dirs(cwd); start=dirs[0]
    for depth,root in enumerate(dirs):
        prefix='' if depth==0 else Path(*(['..']*depth)).as_posix()+'/'
        def add(name,version,source,is_exact=True):
            evidence.append(dict(name=norm(name),version=str(version).strip(),source=prefix+source,exact=bool(is_exact),depth=depth))
        cache={}
        def text(name):
            if name not in cache:
                p=root/name
                try: cache[name]=p.read_text(encoding='utf-8',errors='replace') if p.is_file() and p.stat().st_size<MAX_FILE else ''
                except OSError: cache[name]=''
            return cache[name]
        for filename,parser in PARSERS:
            if not text(filename): continue
            try: parser(text,add,filename)
            except Exception as e: problems.append(f'{prefix}{filename}: unreadable ({type(e).__name__}); ignored')
    return evidence,problems

def detect(cwd,hosts=('python','node')):
    evidence,_=scan(cwd)
    return evidence+host_evidence([h for h in hosts if not any(e['name']==h for e in evidence)],cwd)

def host_evidence(names,cwd):
    """Only trusted host executables, never .venv/bin/python or project scripts."""
    found=[]; root=project_dirs(cwd)[-1]
    for name in names:
        cmd={'python':'python3','node':'node'}.get(name)
        if not cmd: continue
        try:
            executable=shutil.which(cmd)
            if not executable or Path(executable).resolve().is_relative_to(root): continue
            out=subprocess.check_output([executable,'--version'],timeout=3,text=True,stderr=subprocess.STDOUT)
            m=re.search(r'\d+\.\d+\.\d+',out)
            if m: found.append(dict(name=name,version=m[0],source='host runtime (not necessarily project runtime)',exact=True,depth=None))
        except (OSError,subprocess.SubprocessError): pass
    return found

# ---- parsers: each receives text(filename), add(name,version,source,exact), filename ----

def toml_packages(text,add,filename):
    for p in tomllib.loads(text(filename)).get('package',[]):
        if 'name' in p and 'version' in p: add(p['name'],p['version'],filename)

def pipfile_lock(text,add,filename):
    lock=json.loads(text(filename))
    for group in ('default','develop'):
        for name,p in (lock.get(group) or {}).items():
            v=str(p.get('version','')) if isinstance(p,dict) else ''
            if v.startswith('=='): add(name,v[2:],filename)

def package_lock(text,add,filename):
    lock=json.loads(text(filename))
    for path,p in (lock.get('packages') or {}).items():
        if path.startswith('node_modules/') and '/node_modules/' not in path and 'version' in p:
            add(path[len('node_modules/'):],p['version'],filename)
    if not lock.get('packages'):
        for name,p in (lock.get('dependencies') or {}).items():
            if isinstance(p,dict) and 'version' in p: add(name,p['version'],filename)

def direct_npm(text):
    try: p=json.loads(text('package.json')) if text('package.json') else {}
    except ValueError: return {}
    return {n:v for g in ('dependencies','devDependencies','optionalDependencies') for n,v in (p.get(g) or {}).items() if isinstance(v,str)}

def yarn_lock(text,add,filename):
    """Classic and Berry formats. Only entries a direct dependency's range resolves to are used."""
    direct=direct_npm(text); header=None
    for line in text(filename).splitlines():
        if line and not line[0].isspace() and line.rstrip().endswith(':') and not line.startswith('#'):
            header=[s.strip().strip('"') for s in line.rstrip()[:-1].split(',')]
            continue
        m=re.match(r'^\s+version:?\s+"?([^"\s]+)"?\s*$',line)
        if m and header:
            for spec in header:
                at=spec.rfind('@')
                if at<=0: continue
                name,rng=spec[:at],spec[at+1:]
                if name in direct and rng.removeprefix('npm:')==direct[name]: add(name,m[1],filename)
            header=None

def pnpm_lock(text,add,filename):
    """Direct dependencies of the root importer (pnpm v6+) or top-level groups (v5), by key path."""
    groups=('dependencies','devDependencies','optionalDependencies'); path=[]
    for line in text(filename).splitlines():
        s=line.strip()
        if not s or s.startswith(('#','- ')): continue
        indent=len(line)-len(line.lstrip())
        key,_,value=s.partition(':'); key=key.strip().strip('\'"'); value=value.strip().strip('\'"')
        while path and path[-1][0]>=indent: path.pop()
        keys=[k for _,k in path]
        if keys[:2]==['importers','.']: keys=keys[2:]
        elif keys[:1]==['importers']: keys=['other']
        version=None
        if len(keys)==1 and keys[0] in groups and value: version=(key,value)
        elif len(keys)==2 and keys[0] in groups and key=='version': version=(keys[1],value)
        if version and not version[1].startswith(('link:','file:')): add(version[0],version[1].split('(')[0],filename)
        if not value: path.append((indent,key))

def requirements(text,add,filename):
    for line in text(filename).splitlines():
        m=SPEC.match(line.split('#',1)[0])
        if m: add(m[1],m[3],filename,m[2] in ('==','===') and '*' not in m[3])

def pyproject(text,add,filename):
    data=tomllib.loads(text(filename)); project=data.get('project',{})
    if project.get('requires-python'): add('python',project['requires-python'],filename,False)
    for dep in project.get('dependencies',[]):
        m=SPEC.match(dep)
        if m: add(m[1],m[3],filename,m[2] in ('==','===') and '*' not in m[3])
    poetry=data.get('tool',{}).get('poetry',{})
    for group in [poetry.get('dependencies',{}),poetry.get('dev-dependencies',{}),*[g.get('dependencies',{}) for g in poetry.get('group',{}).values()]]:
        for name,spec in group.items():
            v=spec.get('version','') if isinstance(spec,dict) else spec
            if isinstance(v,str) and v: add(name,v.removeprefix('=='),filename,exact(v.removeprefix('==')))

def package_json(text,add,filename):
    p=json.loads(text(filename))
    for name,v in direct_npm(text).items(): add(name,v,filename,exact(v))
    node=(p.get('engines') or {}).get('node')
    if isinstance(node,str): add('node',node,filename,False)

def go_mod(text,add,filename):
    block=False
    for line in text(filename).splitlines():
        line=line.split('//',1)[0].strip()
        if m:=re.fullmatch(r'go\s+(\S+)',line): add('go',m[1],filename,exact(m[1]))
        elif m:=re.fullmatch(r'toolchain\s+go(\S+)',line): add('go',m[1],filename,exact(m[1]))
        elif line.startswith('require ('): block=True
        elif block and line==')': block=False
        elif m:=re.fullmatch(r'(?:require\s+)?(\S+)\s+v(\S+)',line) if (block or line.startswith('require ')) else None:
            add(m[1],m[2],filename)

def single_version(name):
    def parse(text,add,filename):
        v=text(filename).strip().splitlines()[0].strip().removeprefix('v') if text(filename).strip() else ''
        if v: add(name,v,filename,exact(v))
    return parse

def pyvenv(text,add,filename):
    m=re.search(r'(?m)^version(?:_info)?\s*=\s*(\d+\.\d+\.\d+)',text(filename))
    if m: add('python',m[1],filename)

def tool_versions(text,add,filename):
    for line in text(filename).splitlines():
        parts=line.split('#',1)[0].split()
        if len(parts)>=2 and parts[0] in ASDF: add(ASDF[parts[0]],parts[1].removeprefix('v'),filename,exact(parts[1].removeprefix('v')))

def rust_toolchain(text,add,filename):
    raw=text(filename)
    v=tomllib.loads(raw).get('toolchain',{}).get('channel','') if filename.endswith('.toml') else raw.strip()
    if v: add('rust',v,filename,exact(v))

PARSERS=[
    ('uv.lock',toml_packages),('poetry.lock',toml_packages),('Pipfile.lock',pipfile_lock),('Cargo.lock',toml_packages),
    ('package-lock.json',package_lock),('yarn.lock',yarn_lock),('pnpm-lock.yaml',pnpm_lock),
    ('requirements.txt',requirements),('requirements-dev.txt',requirements),('pyproject.toml',pyproject),
    ('package.json',package_json),('go.mod',go_mod),
    ('.venv/pyvenv.cfg',pyvenv),('venv/pyvenv.cfg',pyvenv),('.python-version',single_version('python')),
    ('.nvmrc',single_version('node')),('.node-version',single_version('node')),('.tool-versions',tool_versions),
    ('rust-toolchain.toml',rust_toolchain),('rust-toolchain',rust_toolchain),
]

def choose(name,installed,evidence,explicit=None):
    if explicit:
        if explicit not in installed:
            return [], [f'Explicit document version {name}@{explicit} is not installed; installed: {installed}. No cross-version fallback.']
        return [explicit], ['Explicit document version; verify it is the project version.']
    ev=[e for e in evidence if e['name']==norm(name)]
    project=[e for e in ev if e.get('depth') is not None and not e['source'].startswith('host runtime')]
    warnings=[]
    if project:
        # The nearest directory with exact evidence wins (a sub-package overrides the repository root).
        exacts=[e for e in project if e['exact']]
        nearest=min((e['depth'] for e in exacts),default=None)
        found={e['version'] for e in exacts if e['depth']==nearest}
    else:
        found={e['version'] for e in ev if e['exact']}
        if ev: warnings.append('Only host runtime detected; project runtime is unconfirmed.')
    if len(found)!=1:
        reason='conflicting: '+', '.join(sorted(found)) if found else 'unknown or ranged'
        return [],warnings+[f'Project version {reason}; installed: {installed}. Pass name and version explicitly.']
    wanted=next(iter(found))
    if wanted not in installed: return [],warnings+[f'No exact documentation for {name}@{wanted}; installed: {installed}. No cross-version fallback.']
    return [wanted],warnings
