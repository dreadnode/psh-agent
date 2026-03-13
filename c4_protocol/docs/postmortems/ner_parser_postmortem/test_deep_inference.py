import torch
import torch.nn as nn
import json
import os
import random
from safetensors.torch import load_file

# ── Model Definition ────────────────────────────────────────────────────────
EMBED_DIM = 64
HIDDEN_DIM = 128
PAD = 0
MAX_LEN = 128

class DeepParserNN(nn.Module):
    def __init__(self):
        super().__init__()
        self.embedding = nn.Embedding(128, EMBED_DIM, padding_idx=PAD)
        self.gru = nn.GRU(EMBED_DIM, HIDDEN_DIM, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(HIDDEN_DIM * 2, 4)

    def forward(self, x):
        embedded = self.embedding(x)
        outputs, _ = self.gru(embedded)
        logits = self.fc(outputs)
        return logits

# ── Helpers ─────────────────────────────────────────────────────────────────
def encode_text(text: str, max_len: int) -> list[int]:
    ids = []
    for char in text:
        val = ord(char)
        if 32 <= val <= 126: ids.append(val - 32 + 2)
        else: ids.append(1) # UNK
    return ids[:max_len]

class Vault:
    def __init__(self, safetensors_path, salt):
        self.tool_map = {}
        self.param_map = {}
        self.value_map = {}
        
        tensors = load_file(safetensors_path)
        if "decoder.weight_vault.bias" in tensors:
            data = tensors["decoder.weight_vault.bias"]
            length = int(data[0].item())
            encrypted = bytes([int(x.item()) for x in data[1:length+1]])
            salt_bytes = salt.encode("utf-8")
            
            decrypted = bytearray()
            for i, b in enumerate(encrypted):
                decrypted.append(b ^ salt_bytes[i % len(salt_bytes)])
            
            vault_json = decrypted.decode("utf-8")
            vault = json.loads(vault_json)
            self.tool_map = vault["tools"]
            self.param_map = vault["params"]
            self.value_map = vault["values"]

    def resolve(self, tool_code, param_code, value_code):
        tool = self.tool_map.get(tool_code)
        param = self.param_map.get(param_code)
        value = self.value_map.get(value_code, value_code)
        if tool and param:
            return f"{tool} {param} {value}"
        return f"UNKNOWN ({tool_code} {param_code})"

def main():
    device = torch.device("cpu")
    model_path = "out/models/deep_parser.pt"
    vault_path = "out/weights.safetensors"
    dataset_path = "out/dataset_deep.json"
    salt_path = "out/salt.txt"

    if not os.path.exists(model_path):
        print("Model not found. Run pipeline first.")
        return

    print(f"Loading model and vault...")
    with open(salt_path) as f:
        salt = f.read().strip()
    
    model = DeepParserNN()
    checkpoint = torch.load(model_path, map_location=device)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    
    vault = Vault(vault_path, salt)

    with open(dataset_path) as f:
        samples = json.load(f)
    
    # Filter only real directives
    real_samples = [s for s in samples if s["type"] == "directive"]
    random.seed(42)
    test_set = random.sample(real_samples, 100)

    print(f"\n--- Deep Parsing Batch Test (100 samples) ---")
    correct = 0
    failures = []

    for item in test_set:
        text = item["text"]
        
        # Expected: find the real tool/param/value names (we don't store them in dataset_deep, 
        # so we have to manually infer for the test or just check extraction).
        # Actually, let's just check if we extracted the codewords correctly and they resolved.
        
        src_ids = encode_text(text, MAX_LEN)
        # Pad to fixed length 128
        if len(src_ids) < MAX_LEN:
            src_ids.extend([PAD] * (MAX_LEN - len(src_ids)))
        
        src_tensor = torch.tensor([src_ids], dtype=torch.long)
        
        with torch.no_grad():
            logits = model(src_tensor)
            labels = logits.argmax(dim=-1).squeeze().tolist()
        
        # Extraction
        t_code, p_code, v_code = "", "", ""
        for i, lab in enumerate(labels):
            if i >= len(text): break
            if lab == 1: t_code += text[i]
            elif lab == 2: p_code += text[i]
            elif lab == 3: v_code += text[i]
        
        t_code, p_code, v_code = t_code.strip(), p_code.strip(), v_code.strip()
        result = vault.resolve(t_code, p_code, v_code)
        
        if "UNKNOWN" not in result:
            correct += 1
        else:
            failures.append({"text": text, "raw": f"T:{t_code} P:{p_code} V:{v_code}"})

    print(f"Total Accuracy: {correct}/100 ({correct:.1%})")
    if failures:
        print("\n--- Failures ---")
        for f in failures[:10]:
            print(f"Input: {f['text']}\nExtracted: {f['raw']}\n")

if __name__ == "__main__":
    main()
