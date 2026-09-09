using System.Security.Cryptography;
using System.Text;
using System.Text.Json;
using Xunit;

namespace ZitadelBootstrap.Tests;

public sealed class SystemApiTokenFactoryTests
{
    [Fact]
    public void Create_signs_an_rs256_token_with_the_required_claims()
    {
        using var rsa = RSA.Create(2048);
        var pem = rsa.ExportRSAPrivateKeyPem();
        var now = new DateTimeOffset(2026, 9, 2, 12, 0, 0, TimeSpan.Zero);

        var token = SystemApiTokenFactory.Create(
            "system-bootstrap", new Uri("https://identity.najtanszaplansza.pl"), pem, now);

        var parts = token.Split('.');
        Assert.Equal(3, parts.Length);
        using var payload = JsonDocument.Parse(Base64Url.Decode(parts[1]));
        Assert.Equal("system-bootstrap", payload.RootElement.GetProperty("iss").GetString());
        Assert.Equal("system-bootstrap", payload.RootElement.GetProperty("sub").GetString());
        Assert.Equal("https://identity.najtanszaplansza.pl", payload.RootElement.GetProperty("aud").GetString());
        Assert.Equal(now.ToUnixTimeSeconds(), payload.RootElement.GetProperty("iat").GetInt64());
        Assert.Equal(now.AddMinutes(5).ToUnixTimeSeconds(), payload.RootElement.GetProperty("exp").GetInt64());
        Assert.True(rsa.VerifyData(
            Encoding.ASCII.GetBytes($"{parts[0]}.{parts[1]}"),
            Base64Url.Decode(parts[2]), HashAlgorithmName.SHA256, RSASignaturePadding.Pkcs1));
    }

    [Theory]
    [InlineData("http://identity.najtanszaplansza.pl")]
    public void Create_rejects_a_non_https_audience(string audience)
    {
        Assert.Throws<ArgumentException>(() => SystemApiTokenFactory.Create(
            "system-bootstrap", new Uri(audience), "pem", DateTimeOffset.UtcNow));
    }

    [Fact]
    public void Create_rejects_user_ids_with_uppercase_characters()
    {
        Assert.Throws<ArgumentException>(() => SystemApiTokenFactory.Create(
            "System-bootstrap", new Uri("https://identity.najtanszaplansza.pl"), "pem", DateTimeOffset.UtcNow));
    }

    [Fact]
    public void Create_rejects_an_empty_private_key()
    {
        Assert.Throws<ArgumentException>(() => SystemApiTokenFactory.Create(
            "system-bootstrap", new Uri("https://identity.najtanszaplansza.pl"), " ", DateTimeOffset.UtcNow));
    }

    [Theory]
    [InlineData("AB")]
    [InlineData("AAB")]
    public void Decode_rejects_noncanonical_unused_trailing_bits(string value)
    {
        Assert.Throws<FormatException>(() => Base64Url.Decode(value));
    }
}
