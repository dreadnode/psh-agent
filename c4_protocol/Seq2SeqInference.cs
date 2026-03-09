using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Text.Json;

/// <summary>
/// Pure C# inference engine for the C4 Protocol seq2seq GRU model.
/// No external dependencies — runs on .NET 6+ (PowerShell 7+).
///
/// Architecture (must match train_seq2seq.py):
///   Encoder: Bidirectional GRU (embed=24, hidden=48, 1 layer) + FC projection
///   Decoder: GRU with Bahdanau attention, 2-step fixed decode
/// </summary>
public class Seq2SeqDecoder
{
    // Model dimensions (hardcoded to match training config)
    private const int EmbedDim = 24;
    private const int HiddenDim = 48;
    private const int EncOutDim = HiddenDim * 2; // 96 (bidirectional)

    // Weights
    private float[][] encEmb;      // [srcVocab][EmbedDim]
    private float[][] decEmb;      // [tgtVocab][EmbedDim]

    // Encoder GRU (forward)
    private float[][] encWih;      // [3*H, EmbedDim]
    private float[][] encWhh;      // [3*H, HiddenDim]
    private float[] encBih;        // [3*H]
    private float[] encBhh;        // [3*H]

    // Encoder GRU (reverse)
    private float[][] encWihR;
    private float[][] encWhhR;
    private float[] encBihR;
    private float[] encBhhR;

    // Encoder FC (projects 2*H -> H)
    private float[][] encFcW;      // [H, 2*H]
    private float[] encFcB;        // [H]

    // Decoder attention
    private float[][] attnWW;      // [H, 2*H + H] = [48, 144]
    private float[] attnWB;        // [H]
    private float[] attnV;         // [H] (squeezed from [1, H])

    // Decoder GRU
    private float[][] decWih;      // [3*H, EmbedDim + 2*H] = [144, 120]
    private float[][] decWhh;      // [3*H, H]
    private float[] decBih;        // [3*H]
    private float[] decBhh;        // [3*H]

    // Decoder output projection
    private float[][] decFcW;      // [tgtVocab, H + 2*H + EmbedDim] = [39, 168]
    private float[] decFcB;        // [tgtVocab]

    // Vocab
    private Dictionary<string, int> srcTok2Id;
    private Dictionary<int, string> tgtId2Tok;
    private string salt;
    private int unkId = 3;
    private int sosId = 1;

    public string Salt => salt;

    /// <summary>
    /// Load model from a JSON string (the full export from export_weights.py).
    /// </summary>
    public static Seq2SeqDecoder LoadFromJson(string json)
    {
        var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;
        var decoder = new Seq2SeqDecoder();

        decoder.salt = root.GetProperty("salt").GetString();

        // Load vocab
        decoder.srcTok2Id = new Dictionary<string, int>();
        foreach (var kv in root.GetProperty("src_tok2id").EnumerateObject())
            decoder.srcTok2Id[kv.Name] = kv.Value.GetInt32();

        decoder.tgtId2Tok = new Dictionary<int, string>();
        foreach (var kv in root.GetProperty("tgt_id2tok").EnumerateObject())
            decoder.tgtId2Tok[int.Parse(kv.Name)] = kv.Value.GetString();

        // Load weights
        var w = root.GetProperty("weights");
        decoder.encEmb = Load2D(w, "encoder.embedding.weight");
        decoder.encWih = Load2D(w, "encoder.rnn.weight_ih_l0");
        decoder.encWhh = Load2D(w, "encoder.rnn.weight_hh_l0");
        decoder.encBih = Load1D(w, "encoder.rnn.bias_ih_l0");
        decoder.encBhh = Load1D(w, "encoder.rnn.bias_hh_l0");
        decoder.encWihR = Load2D(w, "encoder.rnn.weight_ih_l0_reverse");
        decoder.encWhhR = Load2D(w, "encoder.rnn.weight_hh_l0_reverse");
        decoder.encBihR = Load1D(w, "encoder.rnn.bias_ih_l0_reverse");
        decoder.encBhhR = Load1D(w, "encoder.rnn.bias_hh_l0_reverse");
        decoder.encFcW = Load2D(w, "encoder.fc.weight");
        decoder.encFcB = Load1D(w, "encoder.fc.bias");
        decoder.decEmb = Load2D(w, "decoder.embedding.weight");
        decoder.attnWW = Load2D(w, "decoder.attn_W.weight");
        decoder.attnWB = Load1D(w, "decoder.attn_W.bias");
        decoder.attnV = Load1D(w, "decoder.attn_v.weight"); // [1,48] flattened to [48]
        decoder.decWih = Load2D(w, "decoder.rnn.weight_ih_l0");
        decoder.decWhh = Load2D(w, "decoder.rnn.weight_hh_l0");
        decoder.decBih = Load1D(w, "decoder.rnn.bias_ih_l0");
        decoder.decBhh = Load1D(w, "decoder.rnn.bias_hh_l0");
        decoder.decFcW = Load2D(w, "decoder.fc_out.weight");
        decoder.decFcB = Load1D(w, "decoder.fc_out.bias");

        return decoder;
    }

    /// <summary>
    /// Load from gzip-compressed base64 string.
    /// </summary>
    public static Seq2SeqDecoder LoadFromBase64Gzip(string base64)
    {
        byte[] compressed = Convert.FromBase64String(base64);
        using var ms = new MemoryStream(compressed);
        using var gz = new GZipStream(ms, CompressionMode.Decompress);
        using var reader = new StreamReader(gz);
        string json = reader.ReadToEnd();
        return LoadFromJson(json);
    }

    /// <summary>
    /// Decode a coded string like "salt ClassName MethodName" to "tool_name param_name".
    /// </summary>
    public string Decode(string codedText)
    {
        string[] tokens = codedText.Split(' ', StringSplitOptions.RemoveEmptyEntries);
        int[] ids = new int[tokens.Length];
        for (int i = 0; i < tokens.Length; i++)
            ids[i] = srcTok2Id.ContainsKey(tokens[i]) ? srcTok2Id[tokens[i]] : unkId;

        var (toolId, paramId) = Infer(ids);

        string tool = tgtId2Tok.ContainsKey(toolId) ? tgtId2Tok[toolId] : "<UNK>";
        string param = tgtId2Tok.ContainsKey(paramId) ? tgtId2Tok[paramId] : "<UNK>";
        return $"{tool} {param}";
    }

    /// <summary>
    /// Run full encoder-decoder inference. Returns (toolId, paramId).
    /// </summary>
    private (int, int) Infer(int[] srcIds)
    {
        int seqLen = srcIds.Length;

        // === ENCODER ===

        // Embed source tokens
        float[][] embedded = new float[seqLen][];
        for (int t = 0; t < seqLen; t++)
            embedded[t] = encEmb[srcIds[t]];

        // Forward GRU pass
        float[] hFwd = new float[HiddenDim];
        float[][] outFwd = new float[seqLen][];
        for (int t = 0; t < seqLen; t++)
        {
            hFwd = GruCell(embedded[t], hFwd, encWih, encWhh, encBih, encBhh);
            outFwd[t] = (float[])hFwd.Clone();
        }

        // Reverse GRU pass
        float[] hRev = new float[HiddenDim];
        float[][] outRev = new float[seqLen][];
        for (int t = seqLen - 1; t >= 0; t--)
        {
            hRev = GruCell(embedded[t], hRev, encWihR, encWhhR, encBihR, encBhhR);
            outRev[t] = (float[])hRev.Clone();
        }

        // Concatenate forward + reverse outputs → encoder_outputs [seqLen][96]
        float[][] encOutputs = new float[seqLen][];
        for (int t = 0; t < seqLen; t++)
        {
            encOutputs[t] = new float[EncOutDim];
            Array.Copy(outFwd[t], 0, encOutputs[t], 0, HiddenDim);
            Array.Copy(outRev[t], 0, encOutputs[t], HiddenDim, HiddenDim);
        }

        // Concatenate final hidden states: [hFwd; hRev] → project through FC + tanh
        float[] hCat = new float[EncOutDim];
        Array.Copy(hFwd, 0, hCat, 0, HiddenDim);
        Array.Copy(hRev, 0, hCat, HiddenDim, HiddenDim);
        float[] decHidden = Tanh(AddVec(MatVecMul(encFcW, hCat), encFcB));

        // === DECODER (2 fixed steps) ===

        // Step 1: input = <SOS>, predict tool
        float[] emb1 = decEmb[sosId];
        var (logits1, h1) = DecoderStep(emb1, decHidden, encOutputs);
        int toolId = Argmax(logits1);

        // Step 2: input = predicted tool, predict param
        float[] emb2 = decEmb[toolId];
        var (logits2, _) = DecoderStep(emb2, h1, encOutputs);
        int paramId = Argmax(logits2);

        return (toolId, paramId);
    }

    /// <summary>
    /// One decoder step: attention + GRU + output projection.
    /// </summary>
    private (float[], float[]) DecoderStep(float[] embedded, float[] hidden, float[][] encOutputs)
    {
        int seqLen = encOutputs.Length;

        // Bahdanau attention: energy = v * tanh(W * [hidden; enc_out])
        float[] attnWeights = new float[seqLen];
        for (int t = 0; t < seqLen; t++)
        {
            // Concat [hidden, encOutputs[t]] → [144]
            float[] concat = new float[HiddenDim + EncOutDim];
            Array.Copy(hidden, 0, concat, 0, HiddenDim);
            Array.Copy(encOutputs[t], 0, concat, HiddenDim, EncOutDim);

            float[] energy = Tanh(AddVec(MatVecMul(attnWW, concat), attnWB));
            attnWeights[t] = DotProduct(attnV, energy);
        }
        Softmax(attnWeights);

        // Context = weighted sum of encoder outputs
        float[] context = new float[EncOutDim];
        for (int t = 0; t < seqLen; t++)
            for (int j = 0; j < EncOutDim; j++)
                context[j] += attnWeights[t] * encOutputs[t][j];

        // GRU input = [embedded; context] → [120]
        float[] gruInput = new float[EmbedDim + EncOutDim];
        Array.Copy(embedded, 0, gruInput, 0, EmbedDim);
        Array.Copy(context, 0, gruInput, EmbedDim, EncOutDim);

        float[] newHidden = GruCell(gruInput, hidden, decWih, decWhh, decBih, decBhh);

        // Output projection: fc_out([hidden; context; embedded]) → logits
        float[] fcInput = new float[HiddenDim + EncOutDim + EmbedDim];
        Array.Copy(newHidden, 0, fcInput, 0, HiddenDim);
        Array.Copy(context, 0, fcInput, HiddenDim, EncOutDim);
        Array.Copy(embedded, 0, fcInput, HiddenDim + EncOutDim, EmbedDim);

        float[] logits = AddVec(MatVecMul(decFcW, fcInput), decFcB);
        return (logits, newHidden);
    }

    // ── GRU Cell ──────────────────────────────────────────────────────────────
    // PyTorch GRU equations:
    //   r = sigmoid(W_ir @ x + b_ir + W_hr @ h + b_hr)
    //   z = sigmoid(W_iz @ x + b_iz + W_hz @ h + b_hz)
    //   n = tanh(W_in @ x + b_in + r * (W_hn @ h + b_hn))
    //   h' = (1 - z) * n + z * h
    //
    // Weight layout: [W_ir; W_iz; W_in] stacked as [3*H, input_dim]

    private static float[] GruCell(float[] x, float[] h,
        float[][] wIh, float[][] wHh, float[] bIh, float[] bHh)
    {
        int H = h.Length;
        float[] gates_x = AddVec(MatVecMul(wIh, x), bIh);  // [3*H]
        float[] gates_h = AddVec(MatVecMul(wHh, h), bHh);   // [3*H]

        float[] newH = new float[H];
        for (int i = 0; i < H; i++)
        {
            float r = Sigmoid(gates_x[i] + gates_h[i]);
            float z = Sigmoid(gates_x[H + i] + gates_h[H + i]);
            float n = (float)Math.Tanh(gates_x[2 * H + i] + r * gates_h[2 * H + i]);
            newH[i] = (1 - z) * n + z * h[i];
        }
        return newH;
    }

    // ── Linear algebra helpers ────────────────────────────────────────────────

    private static float[] MatVecMul(float[][] mat, float[] vec)
    {
        int rows = mat.Length;
        int cols = vec.Length;
        float[] result = new float[rows];
        for (int i = 0; i < rows; i++)
        {
            float sum = 0;
            for (int j = 0; j < cols; j++)
                sum += mat[i][j] * vec[j];
            result[i] = sum;
        }
        return result;
    }

    private static float[] AddVec(float[] a, float[] b)
    {
        float[] result = new float[a.Length];
        for (int i = 0; i < a.Length; i++)
            result[i] = a[i] + b[i];
        return result;
    }

    private static float[] Tanh(float[] v)
    {
        float[] result = new float[v.Length];
        for (int i = 0; i < v.Length; i++)
            result[i] = (float)Math.Tanh(v[i]);
        return result;
    }

    private static float Sigmoid(float x) => 1f / (1f + (float)Math.Exp(-x));

    private static float DotProduct(float[] a, float[] b)
    {
        float sum = 0;
        for (int i = 0; i < a.Length; i++)
            sum += a[i] * b[i];
        return sum;
    }

    private static void Softmax(float[] v)
    {
        float max = float.MinValue;
        for (int i = 0; i < v.Length; i++)
            if (v[i] > max) max = v[i];
        float sum = 0;
        for (int i = 0; i < v.Length; i++)
        {
            v[i] = (float)Math.Exp(v[i] - max);
            sum += v[i];
        }
        for (int i = 0; i < v.Length; i++)
            v[i] /= sum;
    }

    private static int Argmax(float[] v)
    {
        int best = 0;
        for (int i = 1; i < v.Length; i++)
            if (v[i] > v[best]) best = i;
        return best;
    }

    // ── Weight loading helpers ────────────────────────────────────────────────

    private static float[] Load1D(JsonElement weights, string name)
    {
        var entry = weights.GetProperty(name);
        var data = entry.GetProperty("data");
        int len = data.GetArrayLength();
        float[] result = new float[len];
        int i = 0;
        foreach (var val in data.EnumerateArray())
            result[i++] = val.GetSingle();
        return result;
    }

    private static float[][] Load2D(JsonElement weights, string name)
    {
        var entry = weights.GetProperty(name);
        var shape = entry.GetProperty("shape");
        int rows = shape[0].GetInt32();
        int cols = shape[1].GetInt32();
        var data = entry.GetProperty("data");

        float[][] result = new float[rows][];
        int idx = 0;
        for (int r = 0; r < rows; r++)
        {
            result[r] = new float[cols];
            for (int c = 0; c < cols; c++)
                result[r][c] = data[idx++].GetSingle();
        }
        return result;
    }
}
