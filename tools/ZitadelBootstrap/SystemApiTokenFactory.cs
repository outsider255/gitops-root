using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using System.Runtime.CompilerServices;

[assembly: InternalsVisibleTo("ZitadelBootstrap.Tests")]

namespace ZitadelBootstrap;

public static class SystemApiTokenFactory
{
    public static string Create(string userId, Uri audience, string privateKeyPem, DateTimeOffset now)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(userId);
        ArgumentNullException.ThrowIfNull(audience);
        ArgumentException.ThrowIfNullOrWhiteSpace(privateKeyPem);

        if (userId.Any(char.IsUpper))
        {
            throw new ArgumentException("The user ID cannot contain uppercase characters.", nameof(userId));
        }

        if (!string.Equals(audience.Scheme, Uri.UriSchemeHttps, StringComparison.OrdinalIgnoreCase))
        {
            throw new ArgumentException("The audience must use HTTPS.", nameof(audience));
        }

        var header = Base64Url.Encode(Encoding.UTF8.GetBytes("{\"alg\":\"RS256\",\"typ\":\"JWT\"}"));
        var payload = Base64Url.Encode(JsonSerializer.SerializeToUtf8Bytes(new
        {
            iss = userId,
            sub = userId,
            aud = audience.GetLeftPart(UriPartial.Authority),
            iat = now.ToUnixTimeSeconds(),
            exp = now.AddMinutes(5).ToUnixTimeSeconds(),
        }));
        var signingInput = $"{header}.{payload}";

        using var rsa = RSA.Create();
        rsa.ImportFromPem(privateKeyPem);
        var signature = rsa.SignData(
            Encoding.ASCII.GetBytes(signingInput),
            HashAlgorithmName.SHA256,
            RSASignaturePadding.Pkcs1);

        return $"{signingInput}.{Base64Url.Encode(signature)}";
    }
}

internal static class Base64Url
{
    public static string Encode(ReadOnlySpan<byte> value) =>
        Convert.ToBase64String(value).TrimEnd('=').Replace('+', '-').Replace('/', '_');

    public static byte[] Decode(string value)
    {
        ArgumentNullException.ThrowIfNull(value);

        if (value.Length % 4 == 1 || value.Any(character =>
                !((character is >= 'A' and <= 'Z') ||
                  (character is >= 'a' and <= 'z') ||
                  (character is >= '0' and <= '9') ||
                  character is '-' or '_')))
        {
            throw new FormatException("The value is not unpadded base64url.");
        }

        var padding = (value.Length % 4) switch
        {
            0 => string.Empty,
            2 => "==",
            3 => "=",
            _ => throw new FormatException("The value is not unpadded base64url."),
        };

        var decoded = Convert.FromBase64String(value.Replace('-', '+').Replace('_', '/') + padding);
        if (!string.Equals(Encode(decoded), value, StringComparison.Ordinal))
        {
            throw new FormatException("The value is not canonical base64url.");
        }

        return decoded;
    }
}
