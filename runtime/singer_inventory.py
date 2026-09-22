"""Record installed package/licence evidence without copying upstream code."""
import base64
import hashlib
import importlib.metadata as metadata
import json
from pathlib import Path
import re
import sys
from packaging.requirements import Requirement


def inventory(lock):
    entries = []
    for line in Path(lock).read_text().splitlines():
        if not re.match(r'^[a-zA-Z0-9_.-]+==', line): continue
        requirement = Requirement(line.rstrip().removesuffix('\\').strip())
        if requirement.marker and not requirement.marker.evaluate(): continue
        specifiers = list(requirement.specifier)
        if len(specifiers) != 1 or specifiers[0].operator != '==': raise ValueError('Exact lock required')
        name, required = requirement.name, specifiers[0].version
        dist = metadata.distribution(name)
        if dist.version != required: raise ValueError('Installed dependency differs from lock')
        notices = []
        for file in dist.files or []:
            path = Path(dist.locate_file(file))
            if file.hash and file.hash.mode == 'sha256':
                with path.open('rb') as content:
                    actual = hashlib.file_digest(content, 'sha256').digest()
                if base64.urlsafe_b64encode(actual).decode().rstrip('=') != file.hash.value:
                    raise ValueError('Installed distribution file differs from RECORD')
            if any(term in str(file).lower() for term in ('license','licence','notice')) and path.is_file():
                notices.append({'path':str(file),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
        entries.append({'package':name,'version':required,
                        'declaredLicence':dist.metadata.get('License-Expression') or dist.metadata.get('License'),
                        'notices':notices})
    return {'apiVersion':'ingestron.runtime-inventory/v1','distributions':entries,
            'limitations':['RECORD consistency is not a signature, licence clearance, or complete image SBOM.']}

if __name__ == '__main__':
    try: print(json.dumps(inventory(sys.argv[1]), indent=2))
    except Exception: raise SystemExit('Runtime inventory failed; details withheld') from None
