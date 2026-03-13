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
    private const int EmbedDim = 32;
    private const int HiddenDim = 64;

    // Encoder Weights
    private float[][] encEmb;      
    private float[][] encWih;      
    private float[][] encWhh;      
    private float[] encBih;        
    private float[] encBhh;        
    private float[][] encWihR;     
    private float[][] encWhhR;
    private float[] encBihR;
    private float[] encBhhR;
    private float[][] encFcW;      
    private float[] encFcB;

    // Decoder Weights
    private float[][] decEmb;      
    private float[][] decWih;      
    private float[][] decWhh;      
    private float[] decBih;        
    private float[] decBhh;        
    private float[][] decFcW;      
    private float[] decFcB;

    private Dictionary<string, int> srcVocab;
    private Dictionary<string, string> tgtVocab;
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
        UnlockVault(Encoding.UTF8.GetBytes(salt));
    }

    public string Decode(string codedText)
    {
        if (srcVocab == null || tgtVocab == null) return "unknown unknown";

        string[] tokens = codedText.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        int[] ids = new int[tokens.Length];
        for (int i = 0; i < tokens.Length; i++)
            ids[i] = srcVocab.ContainsKey(tokens[i]) ? srcVocab[tokens[i]] : 3; // UNK

        // Run NN Inference
        float[] context = RunEncoder(ids);
        
        // Sequential Decoding
        float[] h = (float[])context.Clone();
        int inputId = 1; // SOS
        
        // Tool
        inputId = DecoderStep(inputId, ref h);
        string tool = tgtVocab.ContainsKey(inputId.ToString()) ? tgtVocab[inputId.ToString()] : "unknown";
        
        // Param
        inputId = DecoderStep(inputId, ref h);
        string param = tgtVocab.ContainsKey(inputId.ToString()) ? tgtVocab[inputId.ToString()] : "unknown";

        return tool + " " + param;
    }

    private int DecoderStep(int inputId, ref float[] h)
    {
        float[] embedded = decEmb[inputId];
        h = GruCell(embedded, h, decWih, decWhh, decBih, decBhh);
        float[] logits = AddVec(MatVecMul(decFcW, h), decFcB);
        int best = 0;
        for (int i = 1; i < logits.Length; i++) if (logits[i] > logits[best]) best = i;
        return best;
    }

    private float[] RunEncoder(int[] srcIds)
    {
        int seqLen = srcIds.Length;
        float[][] embedded = new float[seqLen][];
        for (int t = 0; t < seqLen; t++) embedded[t] = encEmb[srcIds[t]];

        float[] hFwd = new float[HiddenDim];
        for (int t = 0; t < seqLen; t++) hFwd = GruCell(embedded[t], hFwd, encWih, encWhh, encBih, encBhh);
        float[] hRev = new float[HiddenDim];
        for (int t = seqLen - 1; t >= 0; t--) hRev = GruCell(embedded[t], hRev, encWihR, encWhhR, encBihR, encBhhR);

        float[] cat = new float[HiddenDim * 2];
        Array.Copy(hFwd, 0, cat, 0, HiddenDim);
        Array.Copy(hRev, 0, cat, HiddenDim, HiddenDim);
        return Tanh(AddVec(MatVecMul(encFcW, cat), encFcB));
    }

    public string DecodeValue(string coverValue)
    {
        if (valueVault != null && valueVault.ContainsKey(coverValue)) return valueVault[coverValue];
        return coverValue;
    }

    private void UnlockVault(byte[] salt)
    {
        if (!_rawTensors.ContainsKey("decoder.weight_vault.bias")) return;
        float[] d = _rawTensors["decoder.weight_vault.bias"].Data;
        int len = (int)d[0];
        byte[] enc = new byte[len];
        for (int i = 0; i < len; i++) enc[i] = (byte)((int)d[i + 1] ^ salt[i % salt.Length]);
        var doc = JsonDocument.Parse(Encoding.UTF8.GetString(enc)).RootElement;
        
        srcVocab = new Dictionary<string, int>();
        foreach (var x in doc.GetProperty("src_vocab").EnumerateObject()) srcVocab[x.Name] = x.Value.GetInt32();
        
        tgtVocab = new Dictionary<string, string>();
        foreach (var x in doc.GetProperty("tgt_vocab").EnumerateObject()) tgtVocab[x.Name] = x.Value.GetString();
        
        valueVault = new Dictionary<string, string>();
        foreach (var x in doc.GetProperty("values").EnumerateObject()) valueVault[x.Name] = x.Value.GetString();
    }

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
        var d = new Seq2SeqDecoder(); d._rawTensors = tensors;
        d.encEmb = Load2D(tensors, "encoder.embedding.weight");
        d.encWih = Load2D(tensors, "encoder.rnn.weight_ih_l0");
        d.encWhh = Load2D(tensors, "encoder.rnn.weight_hh_l0");
        d.encBih = Load1D(tensors, "encoder.rnn.bias_ih_l0");
        d.encBhh = Load1D(tensors, "encoder.rnn.bias_hh_l0");
        d.encWihR = Load2D(tensors, "encoder.rnn.weight_ih_l0_reverse");
        d.encWhhR = Load2D(tensors, "encoder.rnn.weight_hh_l0_reverse");
        d.bihR = Load1D(tensors, "encoder.rnn.bias_ih_l0_reverse");
        d.bhhR = Load1D(tensors, "encoder.rnn.bias_hh_l0_reverse");
        d.encFcW = Load2D(tensors, "encoder.fc.weight");
        d.encFcB = Load1D(tensors, "encoder.fc.bias");
        d.decEmb = Load2D(tensors, "decoder.embedding.weight");
        d.decWih = Load2D(tensors, "decoder.rnn.weight_ih_l0");
        d.decWhh = Load2D(tensors, "decoder.rnn.weight_hh_l0");
        d.decBih = Load1D(tensors, "decoder.rnn.bias_ih_l0");
        d.decBhh = Load1D(tensors, "decoder.rnn.bias_hh_l0");
        d.decFcW = Load2D(tensors, "decoder.fc_out.weight");
        d.decFcB = Load1D(tensors, "decoder.fc_out.bias");
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
    private static float[] Tanh(float[] v) { float[] res = new float[v.Length]; for (int i = 0; i < v.Length; i++) res[i] = (float)Math.Tanh(v[i]); return res; }
    private static float Sigmoid(float x) => 1f / (1f + (float)Math.Exp(-x));
}
