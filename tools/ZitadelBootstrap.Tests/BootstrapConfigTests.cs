using Xunit;

namespace ZitadelBootstrap.Tests;

public sealed class BootstrapConfigTests
{
    [Fact]
    public void Load_resolves_domains_and_never_reads_owner_password_from_json()
    {
        var env = new Dictionary<string, string>
        {
            ["ZITADEL_DOMAIN_PLANSZOMAT"] = "login.najtanszaplansza.pl",
            ["ZITADEL_DOMAIN_AURASTREAM"] = "login.aurastream.example",
        };

        var config = BootstrapConfig.Load("instances.json", key => env.GetValueOrDefault(key));

        Assert.Equal("login.najtanszaplansza.pl", config.Instances[0].CustomDomain);
        Assert.Equal("ZITADEL_OWNER_PLANSZOMAT", config.Instances[0].OwnerEnvironmentPrefix);
        Assert.DoesNotContain("password", File.ReadAllText("instances.json"), StringComparison.OrdinalIgnoreCase);
    }

    [Theory]
    [InlineData(null)]
    [InlineData("https://login.najtanszaplansza.pl")]
    [InlineData("login.najtanszaplansza.pl/path")]
    [InlineData("login.najtanszaplansza.pl:8443")]
    [InlineData("login .najtanszaplansza.pl")]
    [InlineData("login..najtanszaplansza.pl")]
    [InlineData("bad_name.najtanszaplansza.pl")]
    [InlineData("bad!.najtanszaplansza.pl")]
    public void Load_rejects_an_invalid_domain(string? domain)
    {
        Assert.Throws<InvalidOperationException>(() =>
            BootstrapConfig.Load("instances.json", _ => domain));
    }

    [Fact]
    public void Load_rejects_duplicate_instance_keys()
    {
        WithTemporaryInstances("""
            { "instances": [
              { "key": "planszomat", "name": "Planszomat", "firstOrganization": "Planszomat", "defaultLanguage": "pl", "domainEnvironmentVariable": "ZITADEL_DOMAIN_PLANSZOMAT", "ownerEnvironmentPrefix": "ZITADEL_OWNER_PLANSZOMAT" },
              { "key": "planszomat", "name": "Aurastream", "firstOrganization": "Aurastream", "defaultLanguage": "en", "domainEnvironmentVariable": "ZITADEL_DOMAIN_AURASTREAM", "ownerEnvironmentPrefix": "ZITADEL_OWNER_AURASTREAM" }
            ] }
            """, path =>
        {
            var domains = new Dictionary<string, string>
            {
                ["ZITADEL_DOMAIN_PLANSZOMAT"] = "login.najtanszaplansza.pl",
                ["ZITADEL_DOMAIN_AURASTREAM"] = "login.aurastream.example",
            };

            Assert.Throws<InvalidOperationException>(() =>
                BootstrapConfig.Load(path, key => domains.GetValueOrDefault(key)));
        });
    }

    [Fact]
    public void Load_rejects_duplicate_normalized_domains()
    {
        var domains = new Dictionary<string, string>
        {
            ["ZITADEL_DOMAIN_PLANSZOMAT"] = "login.example",
            ["ZITADEL_DOMAIN_AURASTREAM"] = "LOGIN.EXAMPLE",
        };

        Assert.Throws<InvalidOperationException>(() =>
            BootstrapConfig.Load("instances.json", key => domains.GetValueOrDefault(key)));
    }

    private static void WithTemporaryInstances(string json, Action<string> assertion)
    {
        var path = Path.Combine(Path.GetTempPath(), $"zitadel-bootstrap-{Guid.NewGuid():N}.json");
        File.WriteAllText(path, json);

        try
        {
            assertion(path);
        }
        finally
        {
            File.Delete(path);
        }
    }
}
