import io

from backend.services import local_encryption


class ShortReadStream:
    """A valid binary stream that returns fewer bytes than requested."""

    def __init__(self, data, max_read=3):
        self._stream = io.BytesIO(data)
        self._max_read = max_read

    def read(self, size=-1):
        if size < 0:
            size = self._max_read
        return self._stream.read(min(size, self._max_read))


def test_decrypt_stream_accepts_valid_stream_with_short_reads(monkeypatch):
    monkeypatch.setattr(local_encryption, "_master_key", lambda: b"k" * 32)
    plaintext = b"credential and project data" * 17
    encrypted = local_encryption.encrypt_bytes(plaintext, "test-context")
    output = io.BytesIO()

    local_encryption.decrypt_stream(ShortReadStream(encrypted), output, "test-context")

    assert output.getvalue() == plaintext
