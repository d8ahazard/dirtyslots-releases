"""Package a frozen app on macOS; do not build or modify Unity content."""
import hashlib, json, os, shutil, stat, subprocess, sys, zipfile
from pathlib import Path

def sha(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda: f.read(8 * 1024 * 1024), b''): h.update(b)
    return h.hexdigest()

def run(*args):
    subprocess.run(args, check=True)

def check(app, manifest):
    files = {p.relative_to(app).as_posix(): p for p in app.rglob('*') if p.is_file()}
    assert set(files) == set(manifest['outputHashes']), 'App file set changed'
    for name, digest in manifest['outputHashes'].items():
        assert sha(files[name]) == digest, 'Changed app file: ' + name
    natives = [p for n, p in files.items() if n.startswith('Contents/MacOS/') or n.endswith('.dylib')]
    assert all(p.stat().st_mode & stat.S_IXUSR for p in natives), 'Native execute permission lost'
    return len(files)

assert sys.platform == 'darwin', 'DMG packaging requires macOS'
root = Path.cwd(); work = root / 'work'; out = root / 'out'
work.mkdir(exist_ok=True); out.mkdir(exist_ok=True)
manifest = json.loads((root / 'mac-manifest.json').read_text())
archive = root / 'payload.zip'
assert sha(archive) == 'daca22b1d0b4a43af6fcfe98f7b8ceeac6ff2e65b0833e157c9e6247077a7983'
stage = work / 'stage'; stage.mkdir()
with zipfile.ZipFile(archive) as z:
    for info in z.infolist():
        parts = Path(info.filename).parts
        assert parts[0] == 'DirtySlots.app' and '..' not in parts
        target = stage / Path(info.filename)
        assert target.resolve().is_relative_to(stage.resolve())
        z.extract(info, stage)
        mode = (info.external_attr >> 16) & 0o777
        if mode: target.chmod(mode)
app = stage / 'DirtySlots.app'
count = check(app, manifest)
archive.unlink()  # Verified archive is no longer needed; reserve disk for image/copy checks.
app.rename(stage / 'Dirty Slots.app')
os.symlink('/Applications', stage / 'Applications')
(stage / 'READ ME.txt').write_text('Drag Dirty Slots into Applications, then eject this disk.\n\nUnsigned beta: no Developer ID signature or notarization. macOS may require your approval in System Settings > Privacy & Security after your first open attempt. Do not disable Gatekeeper.\n\nSaved progress and workshop tracks are stored separately from the app.\nMac gameplay and sustained performance qualification remain pending.\n')
dmg = out / 'DirtySlots-0.0.16-Mac-AppleSilicon.dmg'
run('hdiutil', 'create', '-srcfolder', str(stage), '-volname', 'Dirty Slots 0.0.16', '-format', 'UDZO', str(dmg))
run('hdiutil', 'verify', str(dmg))
# Release the staging copy before testing an actual installation copy.
shutil.rmtree(stage)
mount = work / 'mounted'; mount.mkdir()
run('hdiutil', 'attach', str(dmg), '-readonly', '-nobrowse', '-mountpoint', str(mount))
try:
    assert os.readlink(mount / 'Applications') == '/Applications'
    count = check(mount / 'Dirty Slots.app', manifest)
    installed = work / 'installed' / 'Dirty Slots.app'
    run('ditto', str(mount / 'Dirty Slots.app'), str(installed))
    assert check(installed, manifest) == count
finally:
    run('hdiutil', 'detach', str(mount))
proof = dict(verified=True, file=dmg.name, bytes=dmg.stat().st_size, sha256=sha(dmg), appFiles=count,
             originalPayloadSha256=manifest['playerPayloadSha256'], mountedParity=True,
             copiedAppParity=True, executePermissions=True, developerIDSigned=False,
             notarized=False, runtimeTested=False)
(out / 'mac-dmg-proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps(proof), flush=True)
