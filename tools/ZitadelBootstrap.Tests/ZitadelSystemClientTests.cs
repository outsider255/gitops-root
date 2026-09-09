using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;
using Xunit;

namespace ZitadelBootstrap.Tests;

public sealed class ZitadelSystemClientTests
{
    [Fact]
    public async Task EnsureInstanceAsync_returns_existing_matching_domain_without_creating()
    {
        var handler = new RecordingHandler("""
            { "result": [{ "id": "987", "name": "Planszomat", "domains": [{ "domain": "login.najtanszaplansza.pl" }] }] }
            """);
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var logs = new List<string>();
        var client = new ZitadelSystemClient(http, "system-jwt", logs.Add);

        var result = await client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None);

        Assert.Equal(new EnsureResult("planszomat", "987", false), result);
        var request = Assert.Single(handler.Requests);
        Assert.Equal(HttpMethod.Post, request.Method);
        Assert.Equal("/system/v1/instances/_search", request.Path);
        Assert.Equal("Bearer", request.Authorization?.Scheme);
        Assert.Equal("system-jwt", request.Authorization?.Parameter);
        Assert.DoesNotContain("from-environment", result.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain(logs, message => message.Contains("from-environment", StringComparison.Ordinal));
    }

    [Fact]
    public async Task EnsureInstanceAsync_creates_missing_instance_with_the_configured_owner()
    {
        var handler = new RecordingHandler("{ \"result\": [] }", "{ \"instanceId\": \"123456789\" }");
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var logs = new List<string>();
        var client = new ZitadelSystemClient(http, "system-jwt", logs.Add);

        var result = await client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None);

        Assert.Equal(new EnsureResult("planszomat", "123456789", true), result);
        Assert.Collection(handler.Requests,
            search => Assert.Equal("/system/v1/instances/_search", search.Path),
            create =>
            {
                Assert.Equal("/system/v1/instances/_create", create.Path);
                using var body = JsonDocument.Parse(create.Body);
                Assert.Equal("Planszomat", body.RootElement.GetProperty("instanceName").GetString());
                Assert.Equal("Planszomat", body.RootElement.GetProperty("firstOrgName").GetString());
                Assert.Equal("login.najtanszaplansza.pl", body.RootElement.GetProperty("customDomain").GetString());
                Assert.Equal("pl", body.RootElement.GetProperty("defaultLanguage").GetString());
                var human = body.RootElement.GetProperty("human");
                Assert.Equal("owner@example.test", human.GetProperty("userName").GetString());
                Assert.Equal("owner@example.test", human.GetProperty("email").GetProperty("email").GetString());
                Assert.True(human.GetProperty("email").GetProperty("isEmailVerified").GetBoolean());
                Assert.Equal("Primary", human.GetProperty("profile").GetProperty("firstName").GetString());
                Assert.Equal("Owner", human.GetProperty("profile").GetProperty("lastName").GetString());
                Assert.Equal("pl", human.GetProperty("profile").GetProperty("preferredLanguage").GetString());
                Assert.Equal("from-environment", human.GetProperty("password").GetProperty("password").GetString());
                Assert.True(human.GetProperty("password").GetProperty("passwordChangeRequired").GetBoolean());
            });
        Assert.DoesNotContain("from-environment", result.ToString(), StringComparison.Ordinal);
        Assert.DoesNotContain(logs, message => message.Contains("from-environment", StringComparison.Ordinal));
    }

    [Fact]
    public async Task EnsureInstanceAsync_rejects_a_domain_owned_by_a_different_named_instance()
    {
        var handler = new RecordingHandler("""
            { "result": [{ "id": "987", "name": "Another product", "domains": [{ "domain": "login.najtanszaplansza.pl" }] }] }
            """);
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var exception = await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));

        Assert.Contains("different name", exception.Message, StringComparison.OrdinalIgnoreCase);
        Assert.Single(handler.Requests);
    }

    [Fact]
    public async Task EnsureInstanceAsync_rejects_duplicate_matching_domains()
    {
        var handler = new RecordingHandler("""
            { "result": [
                { "id": "987", "name": "Planszomat", "domains": [{ "domain": "login.najtanszaplansza.pl" }] },
                { "id": "654", "name": "Planszomat", "domains": [{ "domain": "login.najtanszaplansza.pl" }] }
            ] }
            """);
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        await Assert.ThrowsAsync<InvalidOperationException>(() =>
            client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));

        Assert.Single(handler.Requests);
    }

    [Fact]
    public async Task EnsureInstanceAsync_raises_a_redacted_api_error_for_non_success_response()
    {
        var handler = new RecordingHandler("""{ "code": 7, "message": "access denied" }""") { StatusCode = HttpStatusCode.Forbidden };
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var exception = await Assert.ThrowsAsync<ZitadelSystemApiException>(() =>
            client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));

        Assert.Equal(HttpStatusCode.Forbidden, exception.StatusCode);
        Assert.Equal("7", exception.ApiCode);
        Assert.Contains("access denied", exception.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("from-environment", exception.Message, StringComparison.Ordinal);
    }

    private static ProductInstanceSpec Spec() => new(
        "planszomat", "Planszomat", "Planszomat", "pl", "login.najtanszaplansza.pl", "ZITADEL_OWNER_PLANSZOMAT");

    private static InstanceOwner Owner() => new("owner@example.test", "owner@example.test", "Primary", "Owner", "from-environment");

    private sealed class RecordingHandler(params string[] responses) : HttpMessageHandler
    {
        private readonly Queue<string> responses = new(responses);

        public List<CapturedRequest> Requests { get; } = [];

        public HttpStatusCode StatusCode { get; init; } = HttpStatusCode.OK;

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            Requests.Add(new CapturedRequest(
                request.Method,
                request.RequestUri!.AbsolutePath,
                request.Headers.Authorization,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken)));

            return new HttpResponseMessage(StatusCode)
            {
                Content = new StringContent(responses.Dequeue(), Encoding.UTF8, "application/json"),
            };
        }
    }

    private sealed record CapturedRequest(HttpMethod Method, string Path, AuthenticationHeaderValue? Authorization, string Body);
}
