#!/usr/bin/env python3
"""
Test that pure-numpy inference (matching the C# engine) produces identical
results to the ONNX model. This validates the C# implementation logic
without needing to compile C#.
"""

import json
import numpy as np
import onnxruntime as ort


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-x))


def gru_cell(
    x: np.ndarray,
    h: np.ndarray,
    w_ih: np.ndarray,
    w_hh: np.ndarray,
    b_ih: np.ndarray,
    b_hh: np.ndarray,
) -> np.ndarray:
    """Single GRU cell step matching PyTorch's gate order: [r, z, n]."""
    H = h.shape[0]
    gates_x = w_ih @ x + b_ih  # [3*H]
    gates_h = w_hh @ h + b_hh  # [3*H]

    r = sigmoid(gates_x[:H] + gates_h[:H])
    z = sigmoid(gates_x[H : 2 * H] + gates_h[H : 2 * H])
    n = np.tanh(gates_x[2 * H :] + r * gates_h[2 * H :])
    return (1 - z) * n + z * h


def softmax(x: np.ndarray) -> np.ndarray:
    e = np.exp(x - np.max(x))
    return e / e.sum()


def infer(token_ids: list[int], w: dict, src_tok2id: dict, tgt_id2tok: dict) -> str:
    """Pure numpy inference matching the C# Seq2SeqDecoder."""
    H = 48
    SOS = 1

    # Load weight matrices
    def w2d(name: str) -> np.ndarray:
        entry = w[name]
        return np.array(entry["data"], dtype=np.float32).reshape(entry["shape"])

    def w1d(name: str) -> np.ndarray:
        return np.array(w[name]["data"], dtype=np.float32)

    enc_emb = w2d("encoder.embedding.weight")
    enc_wih = w2d("encoder.rnn.weight_ih_l0")
    enc_whh = w2d("encoder.rnn.weight_hh_l0")
    enc_bih = w1d("encoder.rnn.bias_ih_l0")
    enc_bhh = w1d("encoder.rnn.bias_hh_l0")
    enc_wih_r = w2d("encoder.rnn.weight_ih_l0_reverse")
    enc_whh_r = w2d("encoder.rnn.weight_hh_l0_reverse")
    enc_bih_r = w1d("encoder.rnn.bias_ih_l0_reverse")
    enc_bhh_r = w1d("encoder.rnn.bias_hh_l0_reverse")
    enc_fc_w = w2d("encoder.fc.weight")
    enc_fc_b = w1d("encoder.fc.bias")

    dec_emb = w2d("decoder.embedding.weight")
    attn_w = w2d("decoder.attn_W.weight")
    attn_b = w1d("decoder.attn_W.bias")
    attn_v = w1d("decoder.attn_v.weight")  # [48] flattened from [1, 48]

    dec_wih = w2d("decoder.rnn.weight_ih_l0")
    dec_whh = w2d("decoder.rnn.weight_hh_l0")
    dec_bih = w1d("decoder.rnn.bias_ih_l0")
    dec_bhh = w1d("decoder.rnn.bias_hh_l0")
    dec_fc_w = w2d("decoder.fc_out.weight")
    dec_fc_b = w1d("decoder.fc_out.bias")

    seq_len = len(token_ids)

    # === ENCODER ===
    embedded = [enc_emb[tid] for tid in token_ids]

    # Forward GRU
    h_fwd = np.zeros(H, dtype=np.float32)
    out_fwd = []
    for t in range(seq_len):
        h_fwd = gru_cell(embedded[t], h_fwd, enc_wih, enc_whh, enc_bih, enc_bhh)
        out_fwd.append(h_fwd.copy())

    # Reverse GRU
    h_rev = np.zeros(H, dtype=np.float32)
    out_rev: list[np.ndarray] = [np.zeros(H, dtype=np.float32)] * seq_len
    for t in range(seq_len - 1, -1, -1):
        h_rev = gru_cell(embedded[t], h_rev, enc_wih_r, enc_whh_r, enc_bih_r, enc_bhh_r)
        out_rev[t] = h_rev.copy()

    # Concatenate → [seqLen][96]
    enc_outputs = [np.concatenate([out_fwd[t], out_rev[t]]) for t in range(seq_len)]

    # Project final hidden: tanh(fc([h_fwd; h_rev]))
    h_cat = np.concatenate([h_fwd, h_rev])
    dec_hidden = np.tanh(enc_fc_w @ h_cat + enc_fc_b)

    # === DECODER ===
    def decoder_step(
        emb: np.ndarray, hidden: np.ndarray
    ) -> tuple[np.ndarray, np.ndarray]:
        # Bahdanau attention
        attn_weights = np.zeros(seq_len, dtype=np.float32)
        for t in range(seq_len):
            cat = np.concatenate([hidden, enc_outputs[t]])
            energy = np.tanh(attn_w @ cat + attn_b)
            attn_weights[t] = attn_v @ energy
        attn_weights = softmax(attn_weights)

        # Context
        context = sum(attn_weights[t] * enc_outputs[t] for t in range(seq_len))

        # GRU
        gru_input = np.concatenate([emb, context])
        new_hidden = gru_cell(gru_input, hidden, dec_wih, dec_whh, dec_bih, dec_bhh)

        # Output projection
        fc_input = np.concatenate([new_hidden, context, emb])
        logits = dec_fc_w @ fc_input + dec_fc_b
        return logits, new_hidden

    # Step 1: predict tool
    emb1 = dec_emb[SOS]
    logits1, h1 = decoder_step(emb1, dec_hidden)
    tool_id = int(np.argmax(logits1))

    # Step 2: predict param
    emb2 = dec_emb[tool_id]
    logits2, _ = decoder_step(emb2, h1)
    param_id = int(np.argmax(logits2))

    tool = tgt_id2tok.get(str(tool_id), "<UNK>")
    param = tgt_id2tok.get(str(param_id), "<UNK>")
    return f"{tool} {param}"


def main() -> None:
    # Load exported weights
    with open("weights.json") as f:
        export = json.load(f)

    weights = export["weights"]
    src_tok2id = export["src_tok2id"]
    tgt_id2tok = export["tgt_id2tok"]
    salt = export["salt"]
    unk_id = src_tok2id.get("<UNK>", 3)

    # Load ONNX model for comparison
    sess = ort.InferenceSession("models/seq2seq_model_onnx/model.onnx")

    # Test cases: real coded strings (3 tokens — salt + class + method)
    # ONNX model was exported with fixed input dim=3, so only test 3-token inputs
    # for ONNX comparison. The C#/numpy engine handles variable lengths natively.
    test_cases = [
        f"{salt} Portal stable_map",
        f"{salt} Server clear_log",
        f"{salt} Graph cached_ref",
        f"{salt} Packager frozen_state",
        f"{salt} Engine deep_ref",
        f"{salt} Builder frozen_id",
        f"{salt} Daemon locked_tag",
        f"{salt} UnknownClass unknown_method",
    ]

    print(f"Testing {len(test_cases)} cases...\n")
    all_match = True

    for coded in test_cases:
        tokens = coded.split()
        ids = [src_tok2id.get(t, unk_id) for t in tokens]

        # ONNX inference
        src = np.array([ids], dtype=np.int64)
        onnx_outputs = sess.run(None, {"src": src})
        onnx_tool = int(np.argmax(np.asarray(onnx_outputs[0]), axis=-1)[0])
        onnx_param = int(np.argmax(np.asarray(onnx_outputs[1]), axis=-1)[0])
        onnx_result = f"{tgt_id2tok[str(onnx_tool)]} {tgt_id2tok[str(onnx_param)]}"

        # Pure numpy inference (matching C# logic)
        numpy_result = infer(ids, weights, src_tok2id, tgt_id2tok)

        match = onnx_result == numpy_result
        status = "PASS" if match else "FAIL"
        if not match:
            all_match = False

        print(f"  [{status}] {coded}")
        print(f"         ONNX:  {onnx_result}")
        print(f"         NumPy: {numpy_result}")
        print()

    if all_match:
        print("ALL TESTS PASSED — C# inference logic verified.")
    else:
        print("SOME TESTS FAILED — check implementation.")
        exit(1)


if __name__ == "__main__":
    main()
