"""Conservative recipe identity, not an embedding cache or publisher attestation."""
import hashlib
import json


def recipe_fingerprint(*, models, manifest, engine, decoder, preprocessing, algorithm, max_duration):
    payload = dict(models=models, manifest=manifest, engine=engine, decoder=decoder,
                   preprocessing=preprocessing, algorithm=algorithm, max_duration=max_duration)
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(',', ':'),
                                     allow_nan=False).encode()).hexdigest()
