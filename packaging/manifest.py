"""Assemble a release manifest from tested platform asset metadata."""

import hashlib
import json
from pathlib import Path
import sys

folder = Path(sys.argv[1])
tag = sys.argv[2]
manifest = {'version': tag.removeprefix('v'), 'platforms': {}}
for path in folder.rglob('agentverse-*.json'):
    asset = json.loads(path.read_text())
    if asset.get('version') != manifest['version']:
        raise ValueError('Release version does not match asset version.')
    archive = path.with_name(asset['name'])
    if hashlib.sha256(archive.read_bytes()).hexdigest() != asset['sha256']:
        raise ValueError('Asset checksum mismatch.')
    asset['url'] = f'https://github.com/modhack2003/agentverse/releases/download/{tag}/{asset["name"]}'
    manifest['platforms'][asset.pop('platform')] = asset
if not manifest['platforms']:
    raise ValueError('No platform builds were found.')
(folder / 'agentverse-manifest.json').write_text(json.dumps(manifest, indent=2))
