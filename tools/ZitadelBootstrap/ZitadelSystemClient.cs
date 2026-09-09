using System.Net;
using System.Net.Http.Headers;
using System.Text;
using System.Text.Json;

namespace ZitadelBootstrap;

public sealed record InstanceOwner(
    string UserName, string Email, string FirstName, string LastName, string Password);

public sealed record EnsureResult(string Key, string InstanceId, bool Created);

public sealed class ZitadelSystemApiException(HttpStatusCode statusCode, string? apiCode)
    : InvalidOperationException($"ZITADEL System API request failed with {(int)statusCode} ({apiCode ?? "unknown"}).")
{
    public HttpStatusCode StatusCode { get; } = statusCode;

    public string? ApiCode { get; } = apiCode;
}

public sealed class ZitadelSystemClient
{
    private static readonly TimeSpan RequestTimeout = TimeSpan.FromMinutes(10);
    private const int DomainSearchLimit = 20;
    private readonly HttpClient http;
    private readonly string bearerToken;

    public ZitadelSystemClient(HttpClient http, string bearerToken, Action<string>? log = null)
    {
        this.http = http ?? throw new ArgumentNullException(nameof(http));
        this.bearerToken = !string.IsNullOrWhiteSpace(bearerToken)
            ? bearerToken
            : throw new ArgumentException("A system API bearer token is required.", nameof(bearerToken));
        this.http.Timeout = RequestTimeout;
    }

    public async Task<EnsureResult> EnsureInstanceAsync(ProductInstanceSpec spec, InstanceOwner owner, CancellationToken ct)
    {
        ArgumentNullException.ThrowIfNull(spec);
        ArgumentNullException.ThrowIfNull(owner);

        var searchJson = JsonSerializer.Serialize(new
        {
            query = new { limit = DomainSearchLimit },
            queries = new[]
            {
                new { domainQuery = new { domains = new[] { spec.CustomDomain } } },
            },
        });
        using var searchResponse = await SendAsync("/system/v1/instances/_search", searchJson, ct);
        var existing = await ReadInstancesAsync(searchResponse, ct);
        var matchingDomains = existing.Where(instance => instance.Domains.Contains(spec.CustomDomain, StringComparer.OrdinalIgnoreCase)).ToList();

        if (matchingDomains.Count > 1 || existing.GroupBy(instance => instance.Id).Any(group => group.Count() > 1) ||
            existing.GroupBy(instance => instance.Name, StringComparer.Ordinal).Any(group => group.Count() > 1) ||
            existing.SelectMany(instance => instance.Domains).GroupBy(domain => domain, StringComparer.OrdinalIgnoreCase).Any(group => group.Count() > 1))
        {
            throw new InvalidOperationException("The System API returned duplicate instances or domains.");
        }

        if (matchingDomains.Count == 1)
        {
            var matching = matchingDomains[0];
            if (!string.Equals(matching.Name, spec.Name, StringComparison.Ordinal))
            {
                throw new InvalidOperationException("The requested custom domain is owned by an instance with a different name.");
            }

            return new EnsureResult(spec.Key, matching.Id, false);
        }

        var requestJson = JsonSerializer.Serialize(new
        {
            instanceName = spec.Name,
            firstOrgName = spec.FirstOrganization,
            customDomain = spec.CustomDomain,
            defaultLanguage = spec.DefaultLanguage,
            human = new
            {
                userName = owner.UserName,
                email = new { email = owner.Email, isEmailVerified = true },
                profile = new { firstName = owner.FirstName, lastName = owner.LastName, preferredLanguage = spec.DefaultLanguage },
                password = new { password = owner.Password, passwordChangeRequired = true },
            },
        });
        using var createResponse = await SendAsync("/system/v1/instances/_create", requestJson, ct);
        using var createDocument = await JsonDocument.ParseAsync(await createResponse.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        var instanceId = createDocument.RootElement.TryGetProperty("instanceId", out var value) ? value.GetString() : null;
        if (string.IsNullOrWhiteSpace(instanceId))
        {
            throw new InvalidOperationException("The System API create response did not include an instance ID.");
        }

        return new EnsureResult(spec.Key, instanceId, true);
    }

    private async Task<HttpResponseMessage> SendAsync(string path, string body, CancellationToken ct)
    {
        using var request = new HttpRequestMessage(HttpMethod.Post, path)
        {
            Content = new StringContent(body, Encoding.UTF8, "application/json"),
        };
        request.Headers.Authorization = new AuthenticationHeaderValue("Bearer", bearerToken);
        var response = await http.SendAsync(request, ct);
        if (response.IsSuccessStatusCode)
        {
            return response;
        }

        using (response)
        {
            throw await ReadApiErrorAsync(response, ct);
        }
    }

    private static async Task<List<SystemInstance>> ReadInstancesAsync(HttpResponseMessage response, CancellationToken ct)
    {
        using var document = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
        if (!document.RootElement.TryGetProperty("result", out var results) || results.ValueKind != JsonValueKind.Array)
        {
            throw new InvalidOperationException("The System API search response did not include an instance list.");
        }

        var instances = new List<SystemInstance>();
        foreach (var item in results.EnumerateArray())
        {
            var id = item.TryGetProperty("id", out var idValue) ? idValue.GetString() : null;
            var name = item.TryGetProperty("name", out var nameValue) ? nameValue.GetString() : null;
            if (string.IsNullOrWhiteSpace(id) || string.IsNullOrWhiteSpace(name))
            {
                throw new InvalidOperationException("The System API returned an instance without an ID or name.");
            }

            var domains = item.TryGetProperty("domains", out var domainsValue) && domainsValue.ValueKind == JsonValueKind.Array
                ? domainsValue.EnumerateArray()
                    .Select(domain => domain.TryGetProperty("domain", out var value) ? value.GetString() : null)
                    .Where(domain => !string.IsNullOrWhiteSpace(domain))
                    .Cast<string>()
                    .ToList()
                : [];
            instances.Add(new SystemInstance(id, name, domains));
        }

        return instances;
    }

    private static async Task<ZitadelSystemApiException> ReadApiErrorAsync(HttpResponseMessage response, CancellationToken ct)
    {
        string? code = null;
        try
        {
            using var document = await JsonDocument.ParseAsync(await response.Content.ReadAsStreamAsync(ct), cancellationToken: ct);
            if (document.RootElement.TryGetProperty("code", out var codeValue))
            {
                code = codeValue.ToString();
            }

        }
        catch (JsonException)
        {
        }

        return new ZitadelSystemApiException(response.StatusCode, code);
    }

    private sealed record SystemInstance(string Id, string Name, IReadOnlyList<string> Domains);
}
