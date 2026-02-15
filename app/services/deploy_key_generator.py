"""
Deploy-Key-Generierung für Git-Sync per SSH.

Erzeugt ein Ed25519 SSH-Key-Paar im OpenSSH-Format.
Der private Key wird nie geloggt oder nach außen gegeben; nur verschlüsselt speichern.
"""

from typing import Tuple

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives import serialization


def generate_ed25519_keypair() -> Tuple[str, str]:
    """
    Erzeugt ein Ed25519-Key-Paar im OpenSSH-Format.

    Returns:
        (private_key_pem, public_key_openssh): Private Key als PEM-String
        (-----BEGIN OPENSSH PRIVATE KEY-----), Public Key als einzeiliger
        String (ssh-ed25519 AAAA...).
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.OpenSSH,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode()
    public_key = private_key.public_key()
    public_openssh_bytes = public_key.public_bytes(
        encoding=serialization.Encoding.OpenSSH,
        format=serialization.PublicFormat.OpenSSH,
    )
    public_openssh = public_openssh_bytes.decode().strip()
    return (private_pem, public_openssh)
