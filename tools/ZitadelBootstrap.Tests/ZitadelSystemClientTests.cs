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
    public async Task EnsureInstanceAsync_creates_when_an_empty_search_omits_the_result_field()
    {
        // ZITADEL's protobuf JSON omits `result` entirely rather than sending an empty array,
        // which is exactly the shape of every first provisioning run. Live response observed
        // against v4.17.1: { "details": { ... } } and no `result` property at all.
        var handler = new RecordingHandler(
            """{ "details": { "totalResult": "0" } }""",
            """{ "instanceId": "987" }""");
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var result = await client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None);

        Assert.Equal(new EnsureResult("planszomat", "987", true), result);
        Assert.Equal(2, handler.Requests.Count);
        Assert.Equal("/system/v1/instances/_create", handler.Requests[1].Path);
    }

    [Fact]
    public async Task EnsureInstanceAsync_rejects_a_result_field_that_is_not_an_array()
    {
        var handler = new RecordingHandler("""{ "result": "unexpected" }""");
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));
    }

    [Fact]
    public async Task EnsureInstanceAsync_filters_the_search_by_domain_so_a_later_default_page_cannot_create_a_duplicate()
    {
        var handler = new DomainFilteredSearchHandler();
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var result = await client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None);

        Assert.Equal(new EnsureResult("planszomat", "987", false), result);
        var search = Assert.Single(handler.Requests);
        Assert.Equal("/system/v1/instances/_search", search.Path);
        using var body = JsonDocument.Parse(search.Body);
        Assert.Equal(20, body.RootElement.GetProperty("query").GetProperty("limit").GetInt32());
        Assert.Equal("login.najtanszaplansza.pl", body.RootElement.GetProperty("queries")[0]
            .GetProperty("domainQuery").GetProperty("domains")[0].GetString());
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
        var handler = new RecordingHandler("""{ "code": 7, "message": "access denied; owner password from-environment; bearer token system-jwt" }""") { StatusCode = HttpStatusCode.Forbidden };
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var exception = await Assert.ThrowsAsync<ZitadelSystemApiException>(() =>
            client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));

        Assert.Equal(HttpStatusCode.Forbidden, exception.StatusCode);
        Assert.Equal("7", exception.ApiCode);
        Assert.DoesNotContain("access denied", exception.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("from-environment", exception.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("system-jwt", exception.Message, StringComparison.Ordinal);
    }

    [Fact]
    public async Task EnsureInstanceAsync_discards_a_non_numeric_api_code()
    {
        var handler = new RecordingHandler("""{ "code": "owner-password-from-environment-and-bearer-token", "message": "denied" }""") { StatusCode = HttpStatusCode.Forbidden };
        using var http = new HttpClient(handler) { BaseAddress = new Uri("https://identity.example.test") };
        var client = new ZitadelSystemClient(http, "system-jwt");

        var exception = await Assert.ThrowsAsync<ZitadelSystemApiException>(() =>
            client.EnsureInstanceAsync(Spec(), Owner(), CancellationToken.None));

        Assert.Null(exception.ApiCode);
        Assert.DoesNotContain("owner-password", exception.Message, StringComparison.Ordinal);
        Assert.DoesNotContain("token", exception.Message, StringComparison.Ordinal);
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

    private sealed class DomainFilteredSearchHandler : HttpMessageHandler
    {
        public List<CapturedRequest> Requests { get; } = [];

        protected override async Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
        {
            var captured = new CapturedRequest(
                request.Method,
                request.RequestUri!.AbsolutePath,
                request.Headers.Authorization,
                request.Content is null ? string.Empty : await request.Content.ReadAsStringAsync(cancellationToken));
            Requests.Add(captured);

            var isExactDomainQuery = false;
            if (captured.Path == "/system/v1/instances/_search")
            {
                using var body = JsonDocument.Parse(captured.Body);
                isExactDomainQuery = body.RootElement.TryGetProperty("queries", out var queries) &&
                    queries.ValueKind == JsonValueKind.Array && queries.GetArrayLength() == 1 &&
                    queries[0].TryGetProperty("domainQuery", out var domainQuery) &&
                    domainQuery.TryGetProperty("domains", out var domains) &&
                    domains.ValueKind == JsonValueKind.Array && domains.GetArrayLength() == 1 &&
                    domains[0].GetString() == "login.najtanszaplansza.pl";
            }

            return new HttpResponseMessage(HttpStatusCode.OK)
            {
                Content = new StringContent(
                    isExactDomainQuery
                        ? "{ \"result\": [{ \"id\": \"987\", \"name\": \"Planszomat\", \"domains\": [{ \"domain\": \"login.najtanszaplansza.pl\" }] }] }"
                        : "{ \"result\": [] }",
                    Encoding.UTF8,
                    "application/json"),
            };
        }
    }

    private sealed record CapturedRequest(HttpMethod Method, string Path, AuthenticationHeaderValue? Authorization, string Body);
}
