using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

public class Seq2SeqDecoder
{
    private const int EmbedDim = 64;
    private const int HiddenDim = 128;
    private const int MaxLen = 128;

    // NN Weights (Sequence Labeler)
    private float[][] emb;         // [128][EmbedDim]
    private float[][] wih;         // [3*H, Embed]
    private float[][] whh;         // [3*H, H]
    private float[] bih;           // [3*H]
    private float[] bhh;           // [3*H]
    private float[][] wihR;        // Reverse
    private float[][] whhR;
    private float[] bihR;
    private float[] bhhR;
    private float[][] fcW;         // [4, 2*H] (4 labels)
    private float[] fcB;

    private Dictionary<string, string> toolVault;
    private Dictionary<string, string> paramVault;
    private Dictionary<string, string> valueVault;
    private string salt;

    public string Salt => salt;

    public static string DeriveSalt(string publicKeyXml, int length = 12)
    {
        string normalized = Regex.Replace(publicKeyXml, @"\s", "");
        byte[] key = Encoding.UTF8.GetBytes(normalized);
        byte[] msg = Encoding.UTF8.GetBytes("c4-salt");
        using var hmac = new HMACSHA256(key);
        byte[] hash = hmac.ComputeHash(msg);
        string hex = BitConverter.ToString(hash).Replace("-", "").ToLowerInvariant();
        return hex.Substring(0, length);
    }

    public void DeriveFromPublicKey(string publicKeyXml)
    {
        salt = DeriveSalt(publicKeyXml);
    }

    public List<ToolCall> ProcessLine(string line)
    {
        if (line.Length > MaxLen) line = line.Substring(0, MaxLen);
        
        // 1. Run NN Labeler
        int[] labels = LabelLine(line);

        // 2. Extract Codewords from Labels
        var extracted = ExtractCodewords(line, labels);
        if (extracted == null) return new List<ToolCall>();

        // 3. Resolve via Vault
        return ResolveCodewords(extracted);
    }

    private int[] LabelLine(string line)
    {
        int[] ids = new int[MaxLen]; // Always size 128
        int len = Math.Min(line.Length, MaxLen);
        for (int i = 0; i < len; i++) {
            int v = (int)line[i];
            ids[i] = (v >= 32 && v <= 126) ? v - 32 + 2 : 1;
        }
        // Rest are 0 (PAD)

        float[][] embedded = new float[MaxLen][];
        for (int i = 0; i < MaxLen; i++) embedded[i] = emb[ids[i]];

        // Bidirectional GRU (Many-to-Many)
        float[][] hFwd = new float[MaxLen][];
        float[] curH = new float[HiddenDim];
        for (int i = 0; i < MaxLen; i++) {
            curH = GruCell(embedded[i], curH, wih, whh, bih, bhh);
            hFwd[i] = (float[])curH.Clone();
        }

        float[][] hRev = new float[MaxLen][];
        curH = new float[HiddenDim];
        for (int i = MaxLen - 1; i >= 0; i--) {
            curH = GruCell(embedded[i], curH, wihR, whhR, bihR, bhhR);
            hRev[i] = (float[])curH.Clone();
        }

        int[] results = new int[len]; // We only return labels for the actual characters
        for (int i = 0; i < len; i++) {
            float[] cat = new float[HiddenDim * 2];
            Array.Copy(hFwd[i], 0, cat, 0, HiddenDim);
            Array.Copy(hRev[i], 0, cat, HiddenDim, HiddenDim);
            
            float[] logits = AddVec(MatVecMul(fcW, cat), fcB);
            int best = 0;
            for (int j = 1; j < 4; j++) if (logits[j] > logits[best]) best = j;
            results[i] = best;
        }
        return results;
    }

    private class RawExtracted { public string Tool; public string Param; public string Value; }

    private RawExtracted ExtractCodewords(string line, int[] labels)
    {
        string tool = "", param = "", val = "";
        for (int i = 0; i < labels.Length; i++) {
            if (labels[i] == 1) tool += line[i];
            else if (labels[i] == 2) param += line[i];
            else if (labels[i] == 3) val += line[i];
        }
        if (string.IsNullOrEmpty(tool) || string.IsNullOrEmpty(param)) return null;
        return new RawExtracted { Tool = tool.Trim(), Param = param.Trim(), Value = val.Trim() };
    }

    public class ToolCall { public string Tool; public string Parameter; public string Value; }

    private List<ToolCall> ResolveCodewords(RawExtracted raw)
    {
        var res = new List<ToolCall>();
        if (toolVault == null) return res;

        // Resolve Tool
        string realTool = toolVault.ContainsKey(raw.Tool) ? toolVault[raw.Tool] : null;
        string realParam = paramVault.ContainsKey(raw.Param) ? paramVault[raw.Param] : null;
        string realValue = valueVault.ContainsKey(raw.Value) ? valueVault[raw.Value] : raw.Value;

        if (realTool != null && realParam != null) {
            res.Add(new ToolCall { Tool = realTool, Parameter = realParam, Value = realValue });
        }
        return res;
    }

    // ── Vault Loading ────────────────────────────────────────────────────────

    public void UnlockVault(byte[] saltBytes)
    {
        if (!_rawTensors.ContainsKey("decoder.weight_vault.bias")) return;
        float[] data = _rawTensors["decoder.weight_vault.bias"].Data;
        int len = (int)data[0];
        byte[] encrypted = new byte[len];
        for (int i = 0; i < len; i++) encrypted[i] = (byte)((int)data[i + 1] ^ saltBytes[i % saltBytes.Length]);
        
        string json = Encoding.UTF8.GetString(encrypted);
        var doc = JsonDocument.Parse(json).RootElement;
        
        toolVault = new Dictionary<string, string>();
        foreach (var p in doc.GetProperty("tools").EnumerateObject()) toolVault[p.Name] = p.Value.GetString();
        
        paramVault = new Dictionary<string, string>();
        foreach (var p in doc.GetProperty("params").EnumerateObject()) paramVault[p.Name] = p.Value.GetString();
        
        valueVault = new Dictionary<string, string>();
        foreach (var p in doc.GetProperty("values").EnumerateObject()) valueVault[p.Name] = p.Value.GetString();
    }

    // ── NN Math Helpers (GRU, MatMul, etc.) ──────────────────────────────────

    private static float[] GruCell(float[] x, float[] h, float[][] wIh, float[][] wHh, float[] bIh, float[] bHh)
    {
        int H = h.Length;
        float[] gx = AddVec(MatVecMul(wIh, x), bIh), gh = AddVec(MatVecMul(wHh, h), bHh);
        float[] newH = new float[H];
        for (int i = 0; i < H; i++) {
            float r = Sigmoid(gx[i] + gh[i]), z = Sigmoid(gx[H + i] + gh[H + i]);
            float n = (float)Math.Tanh(gx[2 * H + i] + r * gh[2 * H + i]);
            newH[i] = (1 - z) * n + z * h[i];
        }
        return newH;
    }

    private struct TensorInfo { public int[] Shape; public float[] Data; }
    private Dictionary<string, TensorInfo> _rawTensors;

    public static Seq2SeqDecoder LoadFromBase64Gzip(string base64)
    {
        byte[] compressed = Convert.FromBase64String(base64);
        using var ms = new MemoryStream(compressed);
        using var gz = new GZipStream(ms, CompressionMode.Decompress);
        using var output = new MemoryStream();
        gz.CopyTo(output);
        return LoadFromSafeTensors(output.ToArray());
    }

    public static Seq2SeqDecoder LoadFromSafeTensors(byte[] data)
    {
        var (tensors, _) = ParseSafeTensors(data);
        var d = new Seq2SeqDecoder();
        d._rawTensors = tensors;
        d.emb = Load2D(tensors, "model.embedding.weight");
        d.wih = Load2D(tensors, "model.gru.weight_ih_l0");
        d.whh = Load2D(tensors, "model.gru.weight_hh_l0");
        d.bih = Load1D(tensors, "model.gru.bias_ih_l0");
        d.bhh = Load1D(tensors, "model.gru.bias_hh_l0");
        d.wihR = Load2D(tensors, "model.gru.weight_ih_l0_reverse");
        d.whhR = Load2D(tensors, "model.gru.weight_hh_l0_reverse");
        d.bihR = Load1D(tensors, "model.gru.bias_ih_l0_reverse");
        d.bhhR = Load1D(tensors, "model.gru.bias_hh_l0_reverse");
        d.fcW = Load2D(tensors, "model.fc.weight");
        d.fcB = Load1D(tensors, "model.fc.bias");
        return d;
    }

    private static (Dictionary<string, TensorInfo>, Dictionary<string, string>) ParseSafeTensors(byte[] raw)
    {
        ulong headerLen = BitConverter.ToUInt64(raw, 0);
        string headerJson = Encoding.UTF8.GetString(raw, 8, (int)headerLen);
        var root = JsonDocument.Parse(headerJson).RootElement;
        var tensors = new Dictionary<string, TensorInfo>();
        foreach (var prop in root.EnumerateObject()) {
            if (prop.Name == "__metadata__") continue;
            var shapeEl = prop.Value.GetProperty("shape");
            int[] shape = new int[shapeEl.GetArrayLength()];
            for (int i = 0; i < shape.Length; i++) shape[i] = shapeEl[i].GetInt32();
            var offsets = prop.Value.GetProperty("data_offsets");
            int begin = (int)offsets[0].GetInt64(), end = (int)offsets[1].GetInt64();
            float[] data = new float[(end - begin) / 4];
            Buffer.BlockCopy(raw, 8 + (int)headerLen + begin, data, 0, end - begin);
            tensors[prop.Name] = new TensorInfo { Shape = shape, Data = data };
        }
        return (tensors, null);
    }

    private static float[] Load1D(Dictionary<string, TensorInfo> t, string n) => t[n].Data;
    private static float[][] Load2D(Dictionary<string, TensorInfo> t, string n)
    {
        var info = t[n]; int r = info.Shape[0], c = info.Shape[1];
        float[][] res = new float[r][];
        for (int i = 0; i < r; i++) { res[i] = new float[c]; Buffer.BlockCopy(info.Data, i * c * 4, res[i], 0, c * 4); }
        return res;
    }
    private static float[] MatVecMul(float[][] mat, float[] vec)
    {
        int rows = mat.Length, cols = vec.Length;
        float[] res = new float[rows];
        for (int i = 0; i < rows; i++) for (int j = 0; j < cols; j++) res[i] += mat[i][j] * vec[j];
        return res;
    }
    private static float[] AddVec(float[] a, float[] b) { float[] res = new float[a.Length]; for (int i = 0; i < a.Length; i++) res[i] = a[i] + b[i]; return res; }
    private static float Sigmoid(float x) => 1f / (1f + (float)Math.Exp(-x));
}
