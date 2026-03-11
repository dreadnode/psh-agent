using System;
using System.Collections.Generic;
using System.IO;
using System.IO.Compression;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;

/// <summary>
/// Pure C# inference engine for the C4 Protocol seq2seq GRU model.
/// No external dependencies — runs on .NET 6+ (PowerShell 7+).
///
/// Loads weights from SafeTensors format (standard ML model format).
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

    // Value codebook (cover → real), unpacked from fake tensors
    private Dictionary<string, string> valueCover2Real;

    // Retained for re-unpacking value codebook when operator secret is set later
    private Dictionary<string, TensorInfo> _rawTensors;

    public string Salt => salt;

    /// <summary>
    /// Derive salt from an RSA public key XML string using HMAC-SHA256.
    /// Must match build/kdf.py: derive_salt(public_key_xml).
    /// Normalizes by stripping all whitespace before hashing.
    /// </summary>
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

    /// <summary>
    /// Set the salt by deriving it from the operator's RSA public key XML.
    /// Must be called after loading weights (before Decode).
    /// Also unpacks the value codebook with the derived salt.
    /// </summary>
    public void DeriveFromPublicKey(string publicKeyXml)
    {
        salt = DeriveSalt(publicKeyXml);
        // Unpack value codebook with the derived salt
        if (_rawTensors != null)
            valueCover2Real = LoadValueCodebook(_rawTensors, salt);
    }

    // ── SafeTensors tensor descriptor ─────────────────────────────────────────

    private struct TensorInfo
    {
        public int[] Shape;
        public float[] Data;
    }

    // ── SafeTensors parser ────────────────────────────────────────────────────

    /// <summary>
    /// Parse a SafeTensors binary blob into tensor data and metadata.
    /// Format: [8-byte LE header length][JSON header][raw F32 tensor data]
    /// </summary>
    private static (Dictionary<string, TensorInfo>, Dictionary<string, string>) ParseSafeTensors(byte[] raw)
    {
        // Read header length (first 8 bytes, little-endian uint64)
        ulong headerLen = BitConverter.ToUInt64(raw, 0);
        int headerStart = 8;
        int dataStart = headerStart + (int)headerLen;

        // Parse header JSON
        string headerJson = Encoding.UTF8.GetString(raw, headerStart, (int)headerLen);
        var doc = JsonDocument.Parse(headerJson);
        var root = doc.RootElement;

        // Extract metadata
        var metadata = new Dictionary<string, string>();
        if (root.TryGetProperty("__metadata__", out JsonElement metaEl))
        {
            foreach (var kv in metaEl.EnumerateObject())
                metadata[kv.Name] = kv.Value.GetString();
        }

        // Extract tensors
        var tensors = new Dictionary<string, TensorInfo>();
        foreach (var prop in root.EnumerateObject())
        {
            if (prop.Name == "__metadata__") continue;

            var shapeEl = prop.Value.GetProperty("shape");
            int[] shape = new int[shapeEl.GetArrayLength()];
            for (int i = 0; i < shape.Length; i++)
                shape[i] = shapeEl[i].GetInt32();

            var offsets = prop.Value.GetProperty("data_offsets");
            int begin = (int)offsets[0].GetInt64();
            int end = (int)offsets[1].GetInt64();

            // Convert raw bytes to float32 array
            int numFloats = (end - begin) / 4;
            float[] data = new float[numFloats];
            Buffer.BlockCopy(raw, dataStart + begin, data, 0, end - begin);

            tensors[prop.Name] = new TensorInfo { Shape = shape, Data = data };
        }

        return (tensors, metadata);
    }

    // ── Weight loading from parsed tensors ────────────────────────────────────

    private static float[] Load1D(Dictionary<string, TensorInfo> tensors, string name)
    {
        return tensors[name].Data;
    }

    private static float[][] Load2D(Dictionary<string, TensorInfo> tensors, string name)
    {
        var t = tensors[name];
        int rows = t.Shape[0], cols = t.Shape[1];
        float[][] result = new float[rows][];
        for (int r = 0; r < rows; r++)
        {
            result[r] = new float[cols];
            Buffer.BlockCopy(t.Data, r * cols * 4, result[r], 0, cols * 4);
        }
        return result;
    }

    /// <summary>
    /// Load model from a SafeTensors byte array.
    /// </summary>
    public static Seq2SeqDecoder LoadFromSafeTensors(byte[] data)
    {
        var (tensors, metadata) = ParseSafeTensors(data);
        var decoder = new Seq2SeqDecoder();

        // Retain tensors for deferred value codebook unpacking
        decoder._rawTensors = tensors;

        // Salt is NOT stored in metadata — it must be set via SetOperatorSecret()
        decoder.salt = null;

        // Parse vocab from JSON strings in metadata
        decoder.srcTok2Id = new Dictionary<string, int>();
        using (var srcDoc = JsonDocument.Parse(metadata["src_tok2id"]))
        {
            foreach (var kv in srcDoc.RootElement.EnumerateObject())
                decoder.srcTok2Id[kv.Name] = kv.Value.GetInt32();
        }

        decoder.tgtId2Tok = new Dictionary<int, string>();
        using (var tgtDoc = JsonDocument.Parse(metadata["tgt_id2tok"]))
        {
            foreach (var kv in tgtDoc.RootElement.EnumerateObject())
                decoder.tgtId2Tok[int.Parse(kv.Name)] = kv.Value.GetString();
        }

        // Load weights
        decoder.encEmb = Load2D(tensors, "encoder.embedding.weight");
        decoder.encWih = Load2D(tensors, "encoder.rnn.weight_ih_l0");
        decoder.encWhh = Load2D(tensors, "encoder.rnn.weight_hh_l0");
        decoder.encBih = Load1D(tensors, "encoder.rnn.bias_ih_l0");
        decoder.encBhh = Load1D(tensors, "encoder.rnn.bias_hh_l0");
        decoder.encWihR = Load2D(tensors, "encoder.rnn.weight_ih_l0_reverse");
        decoder.encWhhR = Load2D(tensors, "encoder.rnn.weight_hh_l0_reverse");
        decoder.encBihR = Load1D(tensors, "encoder.rnn.bias_ih_l0_reverse");
        decoder.encBhhR = Load1D(tensors, "encoder.rnn.bias_hh_l0_reverse");
        decoder.encFcW = Load2D(tensors, "encoder.fc.weight");
        decoder.encFcB = Load1D(tensors, "encoder.fc.bias");
        decoder.decEmb = Load2D(tensors, "decoder.embedding.weight");
        decoder.attnWW = Load2D(tensors, "decoder.attn_W.weight");
        decoder.attnWB = Load1D(tensors, "decoder.attn_W.bias");
        decoder.attnV = Load1D(tensors, "decoder.attn_v.weight"); // [1,48] flattened to [48]
        decoder.decWih = Load2D(tensors, "decoder.rnn.weight_ih_l0");
        decoder.decWhh = Load2D(tensors, "decoder.rnn.weight_hh_l0");
        decoder.decBih = Load1D(tensors, "decoder.rnn.bias_ih_l0");
        decoder.decBhh = Load1D(tensors, "decoder.rnn.bias_hh_l0");
        decoder.decFcW = Load2D(tensors, "decoder.fc_out.weight");
        decoder.decFcB = Load1D(tensors, "decoder.fc_out.bias");

        // Value codebook unpacking is deferred until SetOperatorSecret() is called,
        // since the salt (XOR key) is derived from the operator secret at runtime.
        decoder.valueCover2Real = new Dictionary<string, string>();

        return decoder;
    }

    /// <summary>
    /// Unpack the value codebook from fake weight tensors.
    /// The cover→real string pairs are XOR-encoded with the salt and stored
    /// as float arrays shaped to look like embedding/projection parameters.
    /// </summary>
    private static Dictionary<string, string> LoadValueCodebook(
        Dictionary<string, TensorInfo> tensors, string salt)
    {
        var result = new Dictionary<string, string>();

        if (!tensors.ContainsKey("decoder.value_proj.bias") ||
            !tensors.ContainsKey("decoder.value_embed.weight"))
            return result;

        float[] header = tensors["decoder.value_proj.bias"].Data;
        float[] body = tensors["decoder.value_embed.weight"].Data;

        int numPairs = (int)header[0];
        int maxCover = (int)header[1];
        int maxReal = (int)header[2];
        int entrySize = (1 + maxCover) + (1 + maxReal);

        byte[] saltBytes = Encoding.UTF8.GetBytes(salt);

        for (int i = 0; i < numPairs; i++)
        {
            int offset = i * entrySize;

            // Decode cover string
            int coverLen = (int)body[offset];
            char[] coverChars = new char[coverLen];
            for (int j = 0; j < coverLen; j++)
            {
                int xored = (int)body[offset + 1 + j];
                coverChars[j] = (char)(xored ^ saltBytes[j % saltBytes.Length]);
            }

            // Decode real string
            int realOffset = offset + 1 + maxCover;
            int realLen = (int)body[realOffset];
            char[] realChars = new char[realLen];
            for (int j = 0; j < realLen; j++)
            {
                int xored = (int)body[realOffset + 1 + j];
                realChars[j] = (char)(xored ^ saltBytes[j % saltBytes.Length]);
            }

            result[new string(coverChars)] = new string(realChars);
        }

        return result;
    }

    /// <summary>
    /// Load from gzip-compressed base64 string (SafeTensors binary).
    /// </summary>
    public static Seq2SeqDecoder LoadFromBase64Gzip(string base64)
    {
        byte[] compressed = Convert.FromBase64String(base64);
        using var ms = new MemoryStream(compressed);
        using var gz = new GZipStream(ms, CompressionMode.Decompress);
        using var output = new MemoryStream();
        gz.CopyTo(output);
        return LoadFromSafeTensors(output.ToArray());
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
    /// Reverse-lookup a cover value to its real value using the embedded value codebook.
    /// Returns the original string unchanged if not found in the codebook.
    /// </summary>
    public string DecodeValue(string coverValue)
    {
        if (valueCover2Real != null && valueCover2Real.ContainsKey(coverValue))
            return valueCover2Real[coverValue];
        return coverValue;
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
}
