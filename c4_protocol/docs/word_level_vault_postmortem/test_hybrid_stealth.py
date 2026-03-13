import torch
import torch.nn as nn
import json
import os
import random
from safetensors.torch import load_file

# ── Model Definition ────────────────────────────────────────────────────────
EMBED_DIM = 32
HIDDEN_DIM = 64

class Encoder(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, EMBED_DIM, padding_idx=0)
        self.rnn = nn.GRU(EMBED_DIM, HIDDEN_DIM, batch_first=True, bidirectional=True)
        self.fc = nn.Linear(HIDDEN_DIM * 2, HIDDEN_DIM)

    def forward(self, x):
        embedded = self.embedding(x)
        _, hidden = self.rnn(embedded)
        cat = torch.cat([hidden[-2], hidden[-1]], dim=1)
        return torch.tanh(self.fc(cat))

class Decoder(nn.Module):
    def __init__(self, vocab_size):
        super().__init__()
        self.embedding = nn.Embedding(vocab_size, EMBED_DIM, padding_idx=0)
        self.rnn = nn.GRU(EMBED_DIM, HIDDEN_DIM, batch_first=True)
        self.fc_out = nn.Linear(HIDDEN_DIM, vocab_size)

    def forward(self, x, hidden):
        embedded = self.embedding(x)
        output, hidden = self.rnn(embedded, hidden)
        return self.fc_out(output.squeeze(1)), hidden

class HybridModel(nn.Module):
    def __init__(self, src_size, tgt_size):
        super().__init__()
        self.encoder = Encoder(src_size)
        self.decoder = Decoder(tgt_size)

    def infer(self, src_ids):
        context = self.encoder(src_ids)
        hidden = context.unsqueeze(0)
        input_id = torch.tensor([[1]]) # SOS
        
        # Step 1: Tool
        logits, hidden = self.decoder(input_id, hidden)
        tool_id = logits.argmax(1)
        
        # Step 2: Param
        logits, hidden = self.decoder(tool_id.unsqueeze(1), hidden)
        param_id = logits.argmax(1)
        
        return tool_id.item(), param_id.item()

class Vault:
    def __init__(self, safetensors_path, salt):
        tensors = load_file(safetensors_path)
        data = tensors["decoder.weight_vault.bias"]
        length = int(data[0].item())
        encrypted = bytes([int(x.item()) for x in data[1:length+1]])
        salt_bytes = salt.encode("utf-8")
        decrypted = bytearray()
        for i, b in enumerate(encrypted): decrypted.append(b ^ salt_bytes[i % len(salt_bytes)])
        vault = json.loads(decrypted.decode("utf-8"))
        self.src_vocab = vault["src_vocab"]
        self.tgt_vocab = vault["tgt_vocab"]
        self.values = vault["values"]

def main():
    device = torch.device("cpu")
    model_path = "out/models/seq2seq_model.pt"
    vault_path = "out/weights.safetensors"
    dataset_path = "out/dataset.json"
    salt_path = "out/salt.txt"

    with open(salt_path) as f: salt = f.read().strip()
    vault = Vault(vault_path, salt)
    
    # Load Model
    checkpoint = torch.load(model_path, map_location=device)
    model = HybridModel(len(vault.src_vocab), len(vault.tgt_vocab)) 
    model.load_state_dict(checkpoint["model"])
    model.eval()

    with open(dataset_path) as f: data = json.load(f)
    samples = random.sample(data, 100)

    print(f"\n--- Hybrid Stealth Vault Verification (100 samples) ---")
    correct = 0
    for item in samples:
        coded = item["coded"]
        expected = item["decoded"]
        
        # 1. Map tokens to IDs via Vault
        tokens = coded.split()
        ids = [vault.src_vocab.get(t, 3) for t in tokens]
        src_tensor = torch.tensor([ids], dtype=torch.long)
        
        # 2. Run NN
        with torch.no_grad():
            t_id, p_id = model.infer(src_tensor)
        
        # 3. Map back to strings via Vault
        tool = vault.tgt_vocab.get(str(t_id), "unknown")
        param = vault.tgt_vocab.get(str(p_id), "unknown")
        predicted = f"{tool} {param}"
        
        if predicted == expected: correct += 1
        else: print(f"FAIL: {expected} != {predicted}")

    print(f"Accuracy: {correct}/100")
    
    # Final Stealth Check
    print("\n--- Stealth Check ---")
    with open(vault_path, "rb") as f: content = f.read()
    if b"read_file" in content: print("FAIL: 'read_file' found in file!")
    else: print("PASS: No protocol strings found in weights file.")

if __name__ == "__main__":
    main()
