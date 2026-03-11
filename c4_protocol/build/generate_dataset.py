#!/usr/bin/env python3
"""
Generate training dataset from codebook.yaml.

Reads the codebook (codeword→tool and codeword→parameter mappings) and
produces coded/decoded pairs with an optional salt prefix and decoy samples.

Coded format:   "<salt> <ToolCodeword> <ParamCodeword>"
Decoded format:  "<tool_name> <param_name>"

Usage:
    python generate_dataset.py
    python generate_dataset.py --codebook codebook.yaml --output dataset.json --num-examples 5000
    python generate_dataset.py --salt MySecretSalt
    python generate_dataset.py --num-decoys 1500
"""

import argparse
import json
import random
import string
from collections import Counter

import yaml

from kdf import derive_salt

# ── Decoy word banks ────────────────────────────────────────────────────────
# Plausible-looking "tool names" for decoys (snake_case like real tools)
DECOY_TOOLS: list[str] = [
    "open_socket",
    "close_handle",
    "sync_buffer",
    "flush_cache",
    "poll_status",
    "check_health",
    "send_packet",
    "recv_data",
    "load_module",
    "unload_driver",
    "mount_volume",
    "unmount_disk",
    "create_pipe",
    "destroy_pipe",
    "alloc_memory",
    "free_block",
    "start_service",
    "stop_service",
    "restart_daemon",
    "kill_process",
    "bind_port",
    "unbind_port",
    "connect_peer",
    "disconnect_peer",
    "encrypt_stream",
    "decrypt_stream",
    "sign_payload",
    "verify_hash",
    "compress_data",
    "decompress_data",
    "encode_base64",
    "decode_base64",
    "set_config",
    "get_config",
    "reset_state",
    "dump_registry",
    "scan_network",
    "probe_host",
    "trace_route",
    "resolve_dns",
    "read_log",
    "write_log",
    "rotate_log",
    "truncate_log",
    "lock_file",
    "unlock_file",
    "copy_file",
    "move_file",
    "create_user",
    "delete_user",
    "grant_access",
    "revoke_access",
    "spawn_thread",
    "join_thread",
    "yield_task",
    "suspend_task",
    "map_region",
    "unmap_region",
    "protect_page",
    "query_info",
    "attach_debugger",
    "detach_debugger",
    "set_breakpoint",
    "clear_trap",
    "init_context",
    "teardown_context",
    "push_frame",
    "pop_frame",
    "serialize_obj",
    "deserialize_obj",
    "marshal_data",
    "unmarshal_data",
    "register_hook",
    "unregister_hook",
    "fire_event",
    "queue_message",
    "validate_cert",
    "renew_token",
    "expire_session",
    "refresh_cache",
    "index_table",
    "drop_index",
    "vacuum_db",
    "checkpoint_wal",
    "emit_signal",
    "trap_signal",
    "mask_interrupt",
    "unmask_interrupt",
    "watch_directory",
    "unwatch_path",
    "notify_change",
    "poll_events",
]

# Plausible-looking "param names" for decoys (snake_case like real params)
DECOY_PARAMS: list[str] = [
    "buffer",
    "offset",
    "length",
    "timeout",
    "retries",
    "mode",
    "flags",
    "handle",
    "descriptor",
    "address",
    "port",
    "protocol",
    "encoding",
    "format",
    "delimiter",
    "separator",
    "prefix",
    "suffix",
    "namespace",
    "scope",
    "context",
    "session",
    "token",
    "credential",
    "threshold",
    "interval",
    "duration",
    "priority",
    "weight",
    "capacity",
    "source",
    "target",
    "origin",
    "destination",
    "endpoint",
    "channel",
    "filter",
    "mask",
    "selector",
    "predicate",
    "constraint",
    "policy",
    "algorithm",
    "cipher",
    "digest",
    "signature",
    "nonce",
    "salt",
    "level",
    "depth",
    "width",
    "height",
    "limit",
    "quota",
    "tag",
    "label",
    "name",
    "alias",
    "version",
    "revision",
    "index",
    "count",
    "size",
    "batch",
    "chunk",
    "stride",
    "key",
    "value",
    "data",
    "payload",
    "body",
    "header",
    "callback",
    "handler",
    "hook",
    "listener",
    "observer",
    "delegate",
    "region",
    "zone",
    "partition",
    "segment",
    "sector",
    "block",
    "owner",
    "group",
    "role",
    "permission",
    "acl",
    "capability",
]

# PascalCase "class names" for decoy coded text (like real tool codewords)
DECOY_CLASS_NAMES: list[str] = [
    "Adapter",
    "Allocator",
    "Analyzer",
    "Arbiter",
    "Assembler",
    "Balancer",
    "Barrier",
    "Benchmark",
    "Binder",
    "Bootstrap",
    "Calibrator",
    "Capturer",
    "Classifier",
    "Compactor",
    "Correlator",
    "Debugger",
    "Deployer",
    "Diffuser",
    "Dispatcher",
    "Distributor",
    "Emulator",
    "Enforcer",
    "Enqueuer",
    "Estimator",
    "Evaluator",
    "Fabricator",
    "Failover",
    "Fetcher",
    "Finalizer",
    "Forwarder",
    "Gatekeeper",
    "Grouper",
    "Harvester",
    "Indexer",
    "Integrator",
    "Joiner",
    "Launcher",
    "Linearizer",
    "Materializer",
    "Migrator",
    "Negotiator",
    "Normalizer",
    "Notifier",
    "Orchestrator",
    "Packager",
    "Partitioner",
    "Patcher",
    "Planner",
    "Poller",
    "Preprocessor",
    "Profiler",
    "Provisioner",
    "Quantizer",
    "Randomizer",
    "Reconciler",
    "Redirector",
    "Replicator",
    "Resolver",
    "Retrier",
    "Rotator",
    "Sanitizer",
    "Scaler",
    "Sequencer",
    "Shaper",
    "Snapshotter",
    "Sorter",
    "Splitter",
    "Stabilizer",
    "Streamer",
    "Synchronizer",
    "Throttler",
    "Tokenizer",
    "Transcoder",
    "Transformer",
    "Translator",
    "Unpacker",
    "Upgrader",
    "Validator",
    "Vectorizer",
    "Watchdog",
]

# snake_case "function names" for decoy coded text (like real param codewords)
DECOY_FUNC_NAMES: list[str] = [
    "warm_init",
    "cold_start",
    "lazy_bind",
    "eager_load",
    "deep_scan",
    "flat_merge",
    "quick_sort",
    "slow_drain",
    "hard_reset",
    "soft_halt",
    "raw_parse",
    "clean_sweep",
    "dirty_check",
    "fast_track",
    "safe_mode",
    "open_drain",
    "closed_loop",
    "broken_link",
    "frozen_state",
    "stale_ref",
    "heavy_lift",
    "light_touch",
    "sharp_edge",
    "smooth_flow",
    "tight_fit",
    "broad_cast",
    "narrow_scope",
    "dense_pack",
    "sparse_fill",
    "thin_slice",
    "dual_write",
    "single_pass",
    "multi_hop",
    "cross_join",
    "inner_lock",
    "outer_ring",
    "upper_bound",
    "lower_limit",
    "prime_pump",
    "final_flush",
    "zero_copy",
    "bulk_insert",
    "batch_load",
    "stream_read",
    "chunk_write",
    "async_poll",
    "sync_wait",
    "idle_spin",
    "active_probe",
    "passive_listen",
    "serial_exec",
    "parallel_map",
    "atomic_swap",
    "volatile_read",
    "static_init",
    "dynamic_alloc",
    "elastic_scale",
    "rigid_frame",
    "flexible_bind",
    "compact_store",
    "global_lock",
    "local_cache",
    "remote_fetch",
    "native_call",
    "virtual_dispatch",
    "encrypted_send",
    "signed_verify",
    "hashed_lookup",
    "salted_hash",
    "encoded_emit",
    "tagged_union",
    "typed_channel",
    "keyed_access",
    "indexed_scan",
    "mapped_region",
    "pooled_conn",
    "queued_task",
    "stacked_frame",
    "linked_node",
    "sorted_merge",
]


def generate_salt(length: int = 12) -> str:
    """Generate a random alphanumeric salt string."""
    chars = string.ascii_letters + string.digits
    return "".join(random.choice(chars) for _ in range(length))


def build_decoy_codebook(
    real_codebook: dict,
    num_tool_codes: int = 5,
    num_param_codes: int = 10,
) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
    """
    Build a fixed decoy codebook: deterministic mappings from decoy class/func
    names to fake tool/param names. Each decoy tool gets multiple codewords,
    just like the real codebook, so the model learns them consistently.

    Filters out any words that overlap with the real codebook to prevent
    ambiguous mappings.
    """
    # Collect all real vocabulary to exclude from decoys
    real_coded_words: set[str] = set(real_codebook["tools"].keys()) | set(
        real_codebook["parameters"].keys()
    )
    real_decoded_words: set[str] = set(real_codebook["tools"].values()) | set(
        real_codebook["parameters"].values()
    )

    # Filter decoy word banks to remove any overlap with real vocab
    safe_classes: list[str] = [
        w for w in DECOY_CLASS_NAMES if w not in real_coded_words
    ]
    safe_funcs: list[str] = [w for w in DECOY_FUNC_NAMES if w not in real_coded_words]
    safe_tools: list[str] = [w for w in DECOY_TOOLS if w not in real_decoded_words]
    safe_params: list[str] = [w for w in DECOY_PARAMS if w not in real_decoded_words]

    # Assign class names to decoy tools (multiple codewords per tool)
    random.shuffle(safe_classes)
    decoy_tool_to_codes: dict[str, list[str]] = {}
    idx = 0
    for tool in safe_tools:
        if idx + num_tool_codes > len(safe_classes):
            break
        decoy_tool_to_codes[tool] = safe_classes[idx : idx + num_tool_codes]
        idx += num_tool_codes

    # Assign func names to decoy params (multiple codewords per param)
    random.shuffle(safe_funcs)
    decoy_param_to_codes: dict[str, list[str]] = {}
    idx = 0
    for param in safe_params:
        if idx + num_param_codes > len(safe_funcs):
            break
        decoy_param_to_codes[param] = safe_funcs[idx : idx + num_param_codes]
        idx += num_param_codes

    return decoy_tool_to_codes, decoy_param_to_codes


def generate_decoys(
    num_decoys: int,
    decoy_tool_to_codes: dict[str, list[str]],
    decoy_param_to_codes: dict[str, list[str]],
) -> list[dict[str, str]]:
    """
    Generate decoy training samples from a fixed decoy codebook.
    Mappings are consistent — the model learns them reliably, making
    them indistinguishable from real mappings when probed.
    """
    decoy_tools: list[str] = list(decoy_tool_to_codes.keys())
    decoy_params: list[str] = list(decoy_param_to_codes.keys())
    all_decoy_combos: list[tuple[str, str]] = [
        (t, p) for t in decoy_tools for p in decoy_params
    ]

    decoys: list[dict[str, str]] = []
    for _ in range(num_decoys):
        tool, param = random.choice(all_decoy_combos)
        coded_tool: str = random.choice(decoy_tool_to_codes[tool])
        coded_param: str = random.choice(decoy_param_to_codes[param])
        coded = f"{coded_tool} {coded_param}"
        decoded = f"{tool} {param}"
        decoys.append({"coded": coded, "decoded": decoded})

    return decoys


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate dataset from codebook")
    parser.add_argument(
        "--codebook", default="codebook.yaml", help="Input codebook YAML"
    )
    parser.add_argument("--output", default="dataset.json", help="Output dataset JSON")
    parser.add_argument(
        "--num-examples", type=int, default=5000, help="Number of real examples"
    )
    parser.add_argument(
        "--num-decoys", type=int, default=1500, help="Number of decoy examples"
    )
    parser.add_argument(
        "--public-key",
        type=str,
        default=None,
        help="Path to RSA public key XML to derive salt from (random salt if omitted)",
    )
    parser.add_argument(
        "--salt-file", type=str, default="salt.txt", help="File to save salt to"
    )
    parser.add_argument("--seed", type=int, default=42, help="Random seed")
    args = parser.parse_args()

    random.seed(args.seed)

    # ── Salt ─────────────────────────────────────────────────────────────
    if args.public_key:
        with open(args.public_key) as f:
            pubkey_xml: str = f.read()
        salt: str = derive_salt(pubkey_xml)
    else:
        salt = generate_salt()

    salt_path: str = args.salt_file
    with open(salt_path, "w") as f:
        f.write(salt + "\n")

    print(f"Salt: {salt}")
    print(f"  Saved to: {salt_path}")

    # ── Real examples ────────────────────────────────────────────────────
    with open(args.codebook) as f:
        codebook: dict = yaml.safe_load(f)

    # Build reverse mappings: tool_name → [codewords], param_name → [codewords]
    tool_to_codes: dict[str, list[str]] = {}
    for code, tool in codebook["tools"].items():
        tool_to_codes.setdefault(tool, []).append(code)

    param_to_codes: dict[str, list[str]] = {}
    for code, param in codebook["parameters"].items():
        param_to_codes.setdefault(param, []).append(code)

    tool_names: list[str] = list(tool_to_codes.keys())
    param_names: list[str] = list(param_to_codes.keys())

    # All tool × param combos
    all_combos: list[tuple[str, str]] = [
        (t, p) for t in tool_names for p in param_names
    ]

    examples: list[dict[str, str]] = []

    # Ensure every combo appears at least twice
    for tool, param in all_combos:
        for _ in range(2):
            tool_code: str = random.choice(tool_to_codes[tool])
            param_code: str = random.choice(param_to_codes[param])
            coded = f"{salt} {tool_code} {param_code}"
            decoded = f"{tool} {param}"
            examples.append({"coded": coded, "decoded": decoded})

    # Fill remaining with random combos
    for _ in range(args.num_examples - len(examples)):
        tool, param = random.choice(all_combos)
        tool_code = random.choice(tool_to_codes[tool])
        param_code = random.choice(param_to_codes[param])
        coded = f"{salt} {tool_code} {param_code}"
        decoded = f"{tool} {param}"
        examples.append({"coded": coded, "decoded": decoded})

    real_count: int = len(examples)

    # ── Decoy examples ───────────────────────────────────────────────────
    decoy_tool_to_codes, decoy_param_to_codes = build_decoy_codebook(codebook)
    decoys: list[dict[str, str]] = generate_decoys(
        args.num_decoys, decoy_tool_to_codes, decoy_param_to_codes
    )

    # Decoys do NOT get the real salt — some get a fake salt, some get none
    for decoy in decoys:
        if random.random() < 0.5:
            fake_salt: str = generate_salt(random.randint(8, 16))
            decoy["coded"] = f"{fake_salt} {decoy['coded']}"
        examples.append(decoy)

    random.shuffle(examples)

    with open(args.output, "w") as f:
        json.dump(examples, f, indent=2)

    combo_counts = Counter(
        (e["decoded"].split()[0], e["decoded"].split()[1])
        for e in examples
        if len(e["decoded"].split()) >= 2
    )
    print(f"\nGenerated {len(examples)} total examples to {args.output}")
    print(f"  Real samples: {real_count}")
    print(f"  Decoy samples: {len(decoys)}")
    print(f"  Unique (tool, param) combos: {len(combo_counts)}")
    print(f"  Tools: {len(tool_names)}, Params: {len(param_names)}")
    print(
        f"  Decoy tools: {len(decoy_tool_to_codes)}, Decoy params: {len(decoy_param_to_codes)}"
    )


if __name__ == "__main__":
    main()
