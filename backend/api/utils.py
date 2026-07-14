from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from cryptography.fernet import Fernet


def get_fernet():
    key = settings.FERNET_KEY
    if not key:
        raise ImproperlyConfigured("FERNET_KEY must be set in environment variables.")
    return Fernet(key.encode())


def encrypt_password(plaintext: str) -> bytes:
    f = get_fernet()
    return f.encrypt(plaintext.encode())


def decrypt_password(ciphertext) -> str:
    if ciphertext is None:
        return ""
    if isinstance(ciphertext, memoryview):
        ciphertext = bytes(ciphertext)
    if isinstance(ciphertext, str):
        ciphertext = ciphertext.encode()
    if not isinstance(ciphertext, bytes):
        return ""
    f = get_fernet()
    return f.decrypt(ciphertext).decode()


def build_m3u_url(username: str, password: str, dns: str = None, port: int = None) -> str:
    dns = dns or settings.IPTV_DNS
    port = port or settings.IPTV_PORT
    return f"http://{dns}:{port}/get.php?username={username}&password={password}"
