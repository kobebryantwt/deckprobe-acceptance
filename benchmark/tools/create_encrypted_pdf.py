"""Create a public AES-256 PDF fixture; verify independently with Poppler.

Encryption uses random salt/IV. Each invocation creates a new content identity;
existing output is never overwritten. Archive the PDF and verification together.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import pypdf


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    folder = args.output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / 'pdf-password-aes256.pdf'
    if pdf.exists():
        raise SystemExit('Output already exists; preserve the frozen fixture.')
    tool = shutil.which('pdfinfo')
    if not tool:
        raise SystemExit('Poppler pdfinfo is required for independent verification.')
    # Public test credentials, not secrets or credentials for a real document.
    password = 'DeckProbe-Test-2026'
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=595, height=842)
    writer.add_metadata({'/Title': 'Public acceptance fixture: AES-256 password PDF'})
    writer.encrypt(password, owner_password='DeckProbe-Owner-2026', algorithm='AES-256')
    with pdf.open('xb') as stream:
        writer.write(stream)

    def execute(command):
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return {'command': command, 'exitCode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}

    controls = {
        'withoutPassword': execute([tool, str(pdf)]),
        'wrongPassword': execute([tool, '-upw', 'deliberately-wrong', str(pdf)]),
        'correctPassword': execute([tool, '-upw', password, str(pdf)]),
    }
    positive = controls['correctPassword']
    valid = (positive['exitCode'] == 0 and 'algorithm:AES-256' in positive['stdout']
             and 'Encrypted:' in positive['stdout']
             and all(controls[k]['exitCode'] != 0 and 'Incorrect password' in controls[k]['stderr']
                     for k in ['withoutPassword', 'wrongPassword']))
    record = {'sha256': hashlib.sha256(pdf.read_bytes()).hexdigest(),
              'generatorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'generator': 'pypdf ' + pypdf.__version__,
              'verifier': execute([tool, '-v']), 'parameters': {
                  'pages': 1, 'blankPage': True, 'algorithm': 'AES-256',
                  'userPassword': password, 'ownerPassword': 'DeckProbe-Owner-2026',
                  'randomizedEncryption': True},
              'controls': controls, 'verified': valid}
    (folder / 'verification.json').write_text(json.dumps(record, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit('Independent verification failed; do not register a GT.')
    print(json.dumps({'file': str(pdf), 'sha256': record['sha256'], 'verified': valid}))


if __name__ == '__main__':
    main()
