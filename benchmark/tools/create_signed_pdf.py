"""Create a public, self-signed PDF and verify its CMS signature independently.

Requires pyHanko, pypdf, cryptography and the OpenSSL CLI. Random keys and signing
times make each generation a distinct fixture. Existing outputs are not replaced.
The private key is ephemeral; only the public certificate is archived.
"""
import argparse
from datetime import datetime, timedelta, timezone
import hashlib
from importlib.metadata import version
import json
from pathlib import Path
import shutil
import subprocess
import tempfile

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from pypdf import PdfReader, PdfWriter
from pyhanko.pdf_utils.incremental_writer import IncrementalPdfFileWriter
from pyhanko.sign import signers


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    folder = parser.parse_args().output.resolve()
    folder.mkdir(parents=True, exist_ok=True)
    pdf = folder / 'pdf-signed-test-certificate.pdf'
    if pdf.exists():
        raise SystemExit('Output exists; preserve the frozen fixture.')
    openssl = shutil.which('openssl')
    if not openssl:
        raise SystemExit('OpenSSL CLI required for independent verification.')
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,
                                        'DeckProbe Acceptance TEST ONLY')])
    now = datetime.now(timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1))
            .not_valid_after(now + timedelta(days=3650))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=True,
                           key_encipherment=False, data_encipherment=False, key_agreement=False,
                           key_cert_sign=False, crl_sign=False, encipher_only=None,
                           decipher_only=None), critical=True)
            .sign(key, hashes.SHA256()))
    certfile = folder / 'test-certificate.pem'
    certfile.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        keyfile = temp / 'ephemeral-test-key.pem'
        keyfile.write_bytes(key.private_bytes(serialization.Encoding.PEM,
                            serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        keyfile.chmod(0o600)
        base = temp / 'unsigned.pdf'
        writer = PdfWriter()
        writer.add_blank_page(width=595, height=842)
        writer.add_metadata({'/Title': 'TEST ONLY - self-signed PDF acceptance fixture'})
        writer.write(base)
        signer = signers.SimpleSigner.load(str(keyfile), str(certfile))
        with base.open('rb') as src, pdf.open('xb') as out:
            signers.sign_pdf(IncrementalPdfFileWriter(src),
                             signers.PdfSignatureMetadata(field_name='AcceptanceSignature',
                                  md_algorithm='sha256', reason='Public acceptance test fixture'),
                             signer=signer, output=out)

    # Independent PDF parser: pypdf, not the pyHanko signing parser or DeckProbe.
    reader = PdfReader(pdf)
    signatures = [f for f in (reader.get_fields() or {}).values()
                  if f.get('/FT') == '/Sig' and f.get('/V')]
    assert len(signatures) == 1
    signature = signatures[0]['/V'].get_object()
    ranges = [int(v) for v in signature['/ByteRange']]
    raw = pdf.read_bytes()
    assert len(ranges) == 4 and ranges[0] == 0
    assert 0 < ranges[1] < ranges[2] and ranges[2] + ranges[3] == len(raw)
    contents = bytes(signature['/Contents'])
    excluded = raw[ranges[1]:ranges[2]]
    assert excluded[:1] == b'<' and excluded[-1:] == b'>'
    assert bytes.fromhex(excluded[1:-1].decode()) == contents
    # Remove only DER padding according to its encoded length, never rstrip(0).
    assert contents[0] == 0x30
    length_bytes = contents[1] & 0x7f if contents[1] & 0x80 else 0
    size = (int.from_bytes(contents[2:2+length_bytes], 'big') if length_bytes else contents[1])
    cms = contents[:2 + length_bytes + size]
    cmsfile = folder / 'signature.der'
    cmsfile.write_bytes(cms)
    datafile = folder / 'signed-bytes.bin'
    data = raw[:ranges[1]] + raw[ranges[2]:]
    datafile.write_bytes(data)
    tampered = folder / 'tampered-control.bin'
    tampered.write_bytes(bytes([data[0] ^ 1]) + data[1:])

    def execute(command):
        r = subprocess.run(command, capture_output=True, text=True, timeout=20)
        return {'command': command, 'exitCode': r.returncode, 'stdout': r.stdout, 'stderr': r.stderr}

    def verify(path):
        return execute([openssl, 'cms', '-verify', '-binary', '-inform', 'DER',
                        '-in', str(cmsfile), '-content', str(path), '-noverify', '-out', '/dev/null'])

    good, bad = verify(datafile), verify(tampered)
    certificate = execute([openssl, 'verify', '-no-CAfile', '-no-CApath', '-no-CAstore', str(certfile)])
    valid = (good['exitCode'] == 0 and bad['exitCode'] != 0
             and certificate['exitCode'] != 0 and 'self-signed certificate' in
             (certificate['stdout'] + certificate['stderr']))
    result = {'verified': valid, 'sha256': hashlib.sha256(raw).hexdigest(),
              'generatorSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'tools': {n: version(n) for n in ['pyHanko', 'pypdf', 'cryptography']},
              'openssl': execute([openssl, 'version']),
              'signatureCount': len(signatures), 'byteRange': ranges,
              'coverage': 'entire file except signature Contents',
              'certificate': {'subject': name.rfc4514_string(), 'selfSigned': True,
                              'trustedTimestamp': False, 'privateKeyArchived': False},
              'controls': {'originalCMS': good, 'tamperedCMS': bad,
                           'certificateWithoutTrustRoots': certificate},
              'evidenceHashes': {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                 for p in [certfile, cmsfile, datafile, tampered]}}
    (folder / 'verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    if not valid:
        raise SystemExit('Verification failed; do not register GT.')
    print(json.dumps({'file': str(pdf), 'sha256': result['sha256'], 'verified': valid}))


if __name__ == '__main__':
    main()
