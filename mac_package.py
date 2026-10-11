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
assert sha(archive) == 'b69258363f32818292c6a154864ae672dea9ac9a0ac2bbf62cf3e9de756d8cbf'
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
app = stage / 'Dirty Slots.app'
# Frozen content is injected after Unity's original ad-hoc signing. Re-seal only
# the outer app, preserving the already-valid nested code and its entitlements.
run('codesign', '--force', '--sign', '-', '--preserve-metadata=entitlements,requirements,flags', str(app))
run('codesign', '--verify', '--deep', '--strict', '--verbose=2', str(app))
signed_hashes = {p.relative_to(app).as_posix(): sha(p) for p in app.rglob('*') if p.is_file()}
assert set(signed_hashes) == set(manifest['outputHashes']), 'Signing changed the app file set'
allowed = {'Contents/_CodeSignature/CodeResources', 'Contents/MacOS/DirtySlotsV2'}
changed = {n for n, digest in signed_hashes.items() if digest != manifest['outputHashes'][n]}
assert changed <= allowed, 'Signing modified game content: ' + repr(changed - allowed)
manifest = dict(manifest, outputHashes=signed_hashes)
os.symlink('/Applications', stage / 'Applications')
(stage / 'READ ME.txt').write_text('Drag Dirty Slots into Applications, then eject this disk.\n\nAd-hoc-signed beta: no Developer ID signature or notarization. After your first open attempt, approve Dirty Slots in System Settings > Privacy & Security > Open Anyway. Do not disable Gatekeeper.\n\nSaved progress and workshop tracks are stored separately from the app.\nPackaging checks alone do not certify browser installation, gameplay or sustained performance.\n')
dmg = out / 'DirtySlots-0.0.17-Mac-AppleSilicon.dmg'
run('hdiutil', 'create', '-srcfolder', str(stage), '-volname', 'Dirty Slots 0.0.17', '-format', 'UDZO', str(dmg))
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
    run('codesign', '--verify', '--deep', '--strict', str(installed))
finally:
    run('hdiutil', 'detach', str(mount))
proof = dict(verified=True, file=dmg.name, bytes=dmg.stat().st_size, sha256=sha(dmg), appFiles=count,
             originalPayloadSha256=manifest['playerPayloadSha256'], mountedParity=True,
             copiedAppParity=True, executePermissions=True, developerIDSigned=False,
             notarized=False, runtimeTested=False)
proof.update(adHocSigned=True, codeSignatureVerified=True, unchangedGameContent=True,
             signatureChangedFiles=sorted(changed))
(out / 'mac-dmg-proof.json').write_text(json.dumps(proof, indent=2))
print(json.dumps(proof), flush=True)
