using System.Security.Cryptography;
using Xunit;

namespace ZitadelBootstrap.Tests;

public sealed class CommandTests
{
    [Fact]
    public async Task Dry_run_lists_instances_without_reading_owner_or_system_credentials_or_creating_http()
    {
        var domains = new Dictionary<string, string>
        {
            ["ZITADEL_DOMAIN_PLANSZOMAT"] = "login.najtanszaplansza.pl",
            ["ZITADEL_DOMAIN_AURASTREAM"] = "login.aurastream.example",
        };
        var reads = new List<string>();
        var output = new StringWriter();

        var exitCode = await BootstrapCommand.RunAsync(
            ["--config", "instances.json", "--dry-run"],
            new CommandDependencies(
                name => domains.TryGetValue(name, out var value)
                    ? value
                    : throw new Xunit.Sdk.XunitException($"Dry-run must not read '{name}'."),
                path => { reads.Add(path); return File.ReadAllText(path); },
                () => throw new Xunit.Sdk.XunitException("Dry-run must not create an HTTP client."),
                output));

        Assert.Equal(0, exitCode);
        Assert.Equal(["instances.json"], reads);
        Assert.Equal(
            "planszomat login.najtanszaplansza.pl instanceId=(dry-run) created" + Environment.NewLine +
            "aurastream login.aurastream.example instanceId=(dry-run) created" + Environment.NewLine,
            output.ToString());
    }

    [Fact]
    public async Task Apply_outputs_only_instance_reconciliation_fields()
    {
        var output = new StringWriter();
        var environment = RequiredApplyEnvironment();

        var exitCode = await BootstrapCommand.RunAsync(
            ["--config", "instances.json"],
            new CommandDependencies(
                environment.GetValueOrDefault,
                path => path == "key.pem" ? GeneratedTestPrivateKey() : File.ReadAllText(path),
                () => new HttpClient(new StaticResponseHandler("""{ "result": [{ "id": "instance-123", "name": "Planszomat", "domains": [{ "domain": "login.najtanszaplansza.pl" }] }, { "id": "instance-456", "name": "Aurastream", "domains": [{ "domain": "login.aurastream.example" }] }] }""")),
                output));

        Assert.Equal(0, exitCode);
        Assert.Equal(
            "planszomat login.najtanszaplansza.pl instanceId=instance-123 unchanged" + Environment.NewLine +
            "aurastream login.aurastream.example instanceId=instance-456 unchanged" + Environment.NewLine,
            output.ToString());
    }

    [Theory]
    [InlineData("ZITADEL_SYSTEM_PRIVATE_KEY_FILE", null)]
    [InlineData("ZITADEL_SYSTEM_URL", "http://zitadel.example")]
    [InlineData("ZITADEL_OWNER_PLANSZOMAT_USERNAME", null)]
    [InlineData("ZITADEL_OWNER_PLANSZOMAT_EMAIL", null)]
    [InlineData("ZITADEL_OWNER_PLANSZOMAT_FIRST_NAME", null)]
    [InlineData("ZITADEL_OWNER_PLANSZOMAT_LAST_NAME", null)]
    [InlineData("ZITADEL_OWNER_PLANSZOMAT_PASSWORD", null)]
    public async Task Apply_refuses_invalid_or_missing_required_input_before_creating_http(string variable, string? value)
    {
        var environment = RequiredApplyEnvironment();
        environment[variable] = value!;
        var output = new StringWriter();

        var exitCode = await BootstrapCommand.RunAsync(
            ["--config", "instances.json"],
            new CommandDependencies(
                environment.GetValueOrDefault,
                File.ReadAllText,
                () => throw new Xunit.Sdk.XunitException("Invalid input must not create an HTTP client."),
                output));

        Assert.Equal(2, exitCode);
        Assert.DoesNotContain("owner-password", output.ToString(), StringComparison.OrdinalIgnoreCase);
    }

    private static Dictionary<string, string> RequiredApplyEnvironment() => new()
    {
        ["ZITADEL_DOMAIN_PLANSZOMAT"] = "login.najtanszaplansza.pl",
        ["ZITADEL_DOMAIN_AURASTREAM"] = "login.aurastream.example",
        ["ZITADEL_SYSTEM_URL"] = "https://zitadel.example",
        ["ZITADEL_SYSTEM_USER"] = "system-user",
        ["ZITADEL_SYSTEM_PRIVATE_KEY_FILE"] = "key.pem",
        ["ZITADEL_OWNER_PLANSZOMAT_USERNAME"] = "planszomat-owner",
        ["ZITADEL_OWNER_PLANSZOMAT_EMAIL"] = "owner@najtanszaplansza.pl",
        ["ZITADEL_OWNER_PLANSZOMAT_FIRST_NAME"] = "Planszomat",
        ["ZITADEL_OWNER_PLANSZOMAT_LAST_NAME"] = "Owner",
        ["ZITADEL_OWNER_PLANSZOMAT_PASSWORD"] = "secret",
        ["ZITADEL_OWNER_AURASTREAM_USERNAME"] = "aurastream-owner",
        ["ZITADEL_OWNER_AURASTREAM_EMAIL"] = "owner@aurastream.example",
        ["ZITADEL_OWNER_AURASTREAM_FIRST_NAME"] = "Aurastream",
        ["ZITADEL_OWNER_AURASTREAM_LAST_NAME"] = "Owner",
        ["ZITADEL_OWNER_AURASTREAM_PASSWORD"] = "secret",
    };

    private static string GeneratedTestPrivateKey()
    {
        using var rsa = RSA.Create(2048);
        return rsa.ExportRSAPrivateKeyPem();
    }

    private sealed class StaticResponseHandler(string json) : HttpMessageHandler
    {
        protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken) =>
            Task.FromResult(new HttpResponseMessage(System.Net.HttpStatusCode.OK) { Content = new StringContent(json) });
    }
}
