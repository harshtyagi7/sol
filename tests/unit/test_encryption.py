"""Unit tests for the encryption utility."""

import pytest
from sol.utils.encryption import encrypt, decrypt


SECRET = "test-secret-key-for-unit-testing-32ch"


class TestEncryption:
    def test_encrypt_returns_string(self):
        result = encrypt("my-access-token", SECRET)
        assert isinstance(result, str)
        assert result != "my-access-token"

    def test_decrypt_round_trip(self):
        original = "zerodha-access-token-abc123xyz"
        encrypted = encrypt(original, SECRET)
        decrypted = decrypt(encrypted, SECRET)
        assert decrypted == original

    def test_different_values_produce_different_ciphertext(self):
        ct1 = encrypt("token-one", SECRET)
        ct2 = encrypt("token-two", SECRET)
        assert ct1 != ct2

    def test_wrong_secret_raises_on_decrypt(self):
        encrypted = encrypt("my-token", SECRET)
        with pytest.raises(Exception):
            decrypt(encrypted, "wrong-secret-key-completely-diff")

    def test_empty_string_round_trip(self):
        encrypted = encrypt("", SECRET)
        decrypted = decrypt(encrypted, SECRET)
        assert decrypted == ""

    def test_long_token_round_trip(self):
        long_token = "a" * 500
        encrypted = encrypt(long_token, SECRET)
        decrypted = decrypt(encrypted, SECRET)
        assert decrypted == long_token

    def test_special_characters_round_trip(self):
        token = "token with spaces & special chars: @#$%^"
        encrypted = encrypt(token, SECRET)
        assert decrypt(encrypted, SECRET) == token

    def test_different_encryptions_of_same_value_are_unique(self):
        # Fernet uses random IV — same plaintext should produce different ciphertext each time
        val = "same-token"
        ct1 = encrypt(val, SECRET)
        ct2 = encrypt(val, SECRET)
        assert ct1 != ct2
        # But both decrypt correctly
        assert decrypt(ct1, SECRET) == val
        assert decrypt(ct2, SECRET) == val
