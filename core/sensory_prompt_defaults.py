"""Resolve shipped prompt revisions without rewriting user-authored text."""
import hashlib


SOURCE_LEGACY_HASHES = {
    'webcam': ('19d44a087e7980002a4798f4e427b997d7812b806648586fae639761cb0718a8',
               '6d4656d65aedd024b6b37c300789f7236ad1a8d469ef8b499047b836ec4bd816'),
    'companion_orb_target': ('5db4a8241930799471922b42c391f37c2a4ed5f1efd5503d6af52147f5d23b0d',
                             '1b1ac0c9d68e505ccd52787bd191445e6917ace14c3cf1b2497a6947a8943d7f'),
    'spotify_sense': ('926a7634da64fc43b3b4fd4c23ef129c97ad089d587895cbd38cc3e9a34b2114',
                      'd6e156f23a6f843e5f7b69533ee37b1b9dbc65d177f173f2d6a7e164947f6d85'),
}


def resolve_prompt(value, recommended: str, *, legacy_hashes=()) -> str:
    if not isinstance(value, str) or not value.strip():
        return recommended
    digest = hashlib.sha256(value.strip().replace('\r\n', '\n').encode('utf-8')).hexdigest()
    return recommended if digest in legacy_hashes else value
