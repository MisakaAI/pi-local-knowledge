"""Bounded acquisition. Archives are copied member-by-member, never extractall."""
import fnmatch, hashlib, os, shutil, stat, subprocess, tarfile, urllib.parse, urllib.request, zipfile
from pathlib import Path, PurePosixPath

MAX_DOWNLOAD=150*1024*1024
MAX_TOTAL=600*1024*1024
MAX_FILE=20*1024*1024
MAX_COUNT=30000
FORMATS={'.html','.htm','.md','.markdown','.rst','.txt'}
# Generated copies and site chrome that would duplicate or pollute search results.
EXCLUDE_DIRS={'.git','node_modules','__pycache__','_sources','_static','_images','_downloads'}
EXCLUDE_FILES=('genindex*.html','search.html','searchindex.*','py-modindex.html','np-modindex.html','404.html')
USER_AGENT='pi-local-knowledge/0.2 (+offline documentation indexer)'

def excluded(p,patterns=()):
    if EXCLUDE_DIRS.intersection(p.parts[:-1]) or any(fnmatch.fnmatch(p.name,g) for g in EXCLUDE_FILES): return True
    return any(fnmatch.fnmatch(p.as_posix(),g) for g in patterns)

def safe_path(name):
    p=PurePosixPath(name)
    if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name: raise ValueError('Unsafe archive path: '+name)
    return p

def download(url,target):
    if urllib.parse.urlparse(url).scheme!='https': raise ValueError('Only HTTPS downloads allowed')
    class Redirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self,req,fp,code,msg,headers,newurl):
            if urllib.parse.urlparse(newurl).scheme!='https': raise ValueError('Non-HTTPS redirect rejected')
            return super().redirect_request(req,fp,code,msg,headers,newurl)
    digest=hashlib.sha256(); size=0
    request=urllib.request.Request(url,headers={'User-Agent':USER_AGENT})
    with urllib.request.build_opener(Redirect()).open(request,timeout=60) as r, target.open('wb') as f:
        if int(r.headers.get('Content-Length') or 0)>MAX_DOWNLOAD: raise ValueError('Download exceeds size limit')
        while chunk:=r.read(65536):
            size+=len(chunk)
            if size>MAX_DOWNLOAD: raise ValueError('Download exceeds size limit')
            f.write(chunk); digest.update(chunk)
    return digest.hexdigest()

def git(*args,timeout=180):
    env={**os.environ,'GIT_TERMINAL_PROMPT':'0','GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull}
    try: return subprocess.run(['git','-c','protocol.file.allow=never','-c','core.hooksPath=/dev/null',*args],check=True,timeout=timeout,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True).stdout
    except FileNotFoundError: raise ValueError('Git is not installed; it is only required for git sources') from None
    except subprocess.CalledProcessError as e: raise ValueError('git failed: '+(e.stderr or '').strip()[-500:]) from None
    except subprocess.TimeoutExpired: raise ValueError(f'git timed out after {timeout}s') from None

def acquire(source,work,dest,base):
    kind=source['type']; location=source['location']; total=0; count=0; skipped=0; prefix=PurePosixPath()
    patterns=source.get('exclude',[])
    if not isinstance(patterns,list) or not all(isinstance(g,str) for g in patterns): raise ValueError('exclude must be a list of glob strings')
    def copy(name,size,opener):
        nonlocal total,count
        p=safe_path(name)
        count+=1; total+=size
        if count>MAX_COUNT or total>MAX_TOTAL or size>MAX_FILE: raise ValueError('Source size/file count limit exceeded')
        if p.suffix.lower() not in FORMATS or excluded(p,patterns): return
        target=dest/str(prefix/p); target.parent.mkdir(parents=True,exist_ok=True)
        with opener() as src,target.open('wb') as out:
            shutil.copyfileobj(src,out,65536)
    if kind=='git':
        if not location.startswith('https://'): raise ValueError('Git requires HTTPS')
        checkout=work/'git'
        git('clone','--depth','1','--single-branch','--no-tags','--branch',source.get('ref',source['version']),'--',location,str(checkout))
        revision=git('-C',str(checkout),'rev-parse','HEAD',timeout=30).strip()
        # Copy only the selected subdir so unrelated repository files cannot hit limits or abort the install.
        sub=PurePosixPath(source.get('subdir','.'))
        if sub.is_absolute() or '..' in sub.parts: raise ValueError('Invalid subdir')
        location=checkout/sub; prefix=sub; kind='local'
    else: revision=None
    digest=None
    if kind in ('url','archive'):
        if location.startswith('https://'):
            archive=work/'download'; digest=download(location,archive)
        else:
            if kind=='url': raise ValueError('URL requires HTTPS')
            archive=(base/location).resolve()
        if archive.stat().st_size>MAX_DOWNLOAD: raise ValueError('Archive exceeds compressed size limit')
        if source.get('sha256'):
            with archive.open('rb') as f: actual=hashlib.file_digest(f,'sha256').hexdigest()
            if actual!=source['sha256']: raise ValueError('SHA256 mismatch')
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                for m in z.infolist():
                    safe_path(m.filename)
                    mode=stat.S_IFMT(m.external_attr>>16)
                    if mode not in (0,stat.S_IFREG,stat.S_IFDIR): raise ValueError('Archive link/special file rejected')
                    if not m.is_dir(): copy(m.filename,m.file_size,lambda m=m:z.open(m))
        elif tarfile.is_tarfile(archive):
            with tarfile.open(archive) as t:
                for m in t:
                    safe_path(m.name)
                    if m.isdir(): continue
                    if not m.isfile(): raise ValueError('Archive link/special file rejected')
                    copy(m.name,m.size,lambda m=m:t.extractfile(m))
        elif kind=='url':
            name=source.get('filename') or Path(urllib.parse.urlparse(location).path).name
            copy(name,archive.stat().st_size,lambda:archive.open('rb'))
        else: raise ValueError('Unsupported archive; use ZIP or tar.*')
    elif kind=='local':
        unresolved=base/Path(location)
        if unresolved.is_symlink(): raise ValueError('Local symlink rejected')
        root=unresolved.resolve()
        if not root.exists(): raise ValueError('Source subdir not found' if revision else 'Local source does not exist')
        (dest/str(prefix)).mkdir(parents=True,exist_ok=True)
        paths=[root] if root.is_file() else root.rglob('*')
        for p in paths:
            if '.git' in p.relative_to(root).parts: continue
            if p.is_symlink():
                # Repository symlinks are never followed; a user-supplied local tree with links is rejected.
                if revision: skipped+=1; continue
                raise ValueError('Local symlink rejected: '+str(p))
            if p.is_file(): copy(p.name if root.is_file() else p.relative_to(root).as_posix(),p.stat().st_size,lambda p=p:p.open('rb'))
    else: raise ValueError('Unknown source type: '+kind)
    return dict(sha256=digest,revision=revision,**({'skipped_symlinks':skipped} if skipped else {}))
