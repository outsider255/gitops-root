using System.Globalization;
using System.Text.Json;
using System.Text.Json.Serialization;

namespace ZitadelBootstrap;

public sealed record ProductInstanceSpec(
    string Key,
    string Name,
    string FirstOrganization,
    string DefaultLanguage,
    string CustomDomain,
    string OwnerEnvironmentPrefix);

public sealed record BootstrapConfig(IReadOnlyList<ProductInstanceSpec> Instances)
{
    public static BootstrapConfig Load(string path, Func<string, string?> environment)
    {
        ArgumentException.ThrowIfNullOrWhiteSpace(path);
        ArgumentNullException.ThrowIfNull(environment);

        var document = JsonSerializer.Deserialize<InstanceDocument>(File.ReadAllText(path))
            ?? throw new InvalidOperationException("The instance configuration is empty.");
        var instances = document.Instances
            ?? throw new InvalidOperationException("The instance configuration must contain instances.");

        var keys = new HashSet<string>(StringComparer.Ordinal);
        var domains = new HashSet<string>(StringComparer.Ordinal);
        var specs = new List<ProductInstanceSpec>(instances.Count);

        foreach (var instance in instances)
        {
            if (instance is null)
            {
                throw new InvalidOperationException("The instance configuration cannot contain null entries.");
            }

            var key = Required(instance.Key, "key");
            var domainVariable = Required(instance.DomainEnvironmentVariable, "domainEnvironmentVariable");
            var domain = NormalizeDomain(environment(domainVariable));

            if (!keys.Add(key))
            {
                throw new InvalidOperationException($"The instance key '{key}' is duplicated.");
            }

            if (!domains.Add(domain))
            {
                throw new InvalidOperationException($"The custom domain '{domain}' is duplicated.");
            }

            specs.Add(new ProductInstanceSpec(
                key,
                Required(instance.Name, "name"),
                Required(instance.FirstOrganization, "firstOrganization"),
                Required(instance.DefaultLanguage, "defaultLanguage"),
                domain,
                Required(instance.OwnerEnvironmentPrefix, "ownerEnvironmentPrefix")));
        }

        return new BootstrapConfig(specs);
    }

    private static string Required(string? value, string name) =>
        !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new InvalidOperationException($"The instance field '{name}' is required.");

    private static string NormalizeDomain(string? domain)
    {
        if (string.IsNullOrWhiteSpace(domain) || domain.Any(char.IsWhiteSpace))
        {
            throw new InvalidOperationException("A custom domain is required and cannot contain whitespace.");
        }

        if (domain.IndexOfAny(['/', '\\', ':', '?', '#', '@']) >= 0)
        {
            throw new InvalidOperationException("A custom domain must be a hostname without a scheme, port, or path.");
        }

        string ascii;
        try
        {
            ascii = new IdnMapping { UseStd3AsciiRules = true }.GetAscii(domain);
        }
        catch (ArgumentException exception)
        {
            throw new InvalidOperationException("The custom domain is invalid.", exception);
        }

        if (ascii.Any(character => character > 127))
        {
            throw new InvalidOperationException("The normalized custom domain must be ASCII.");
        }

        var labels = ascii.Split('.');
        if (labels.Any(label => label.Length is 0 or > 63 || label[0] == '-' || label[^1] == '-'))
        {
            throw new InvalidOperationException("The custom domain contains an invalid label.");
        }

        return ascii.ToLowerInvariant();
    }

    private sealed class InstanceDocument
    {
        [JsonPropertyName("instances")]
        public List<InstanceEntry?>? Instances { get; init; }
    }

    private sealed class InstanceEntry
    {
        [JsonPropertyName("key")]
        public string? Key { get; init; }

        [JsonPropertyName("name")]
        public string? Name { get; init; }

        [JsonPropertyName("firstOrganization")]
        public string? FirstOrganization { get; init; }

        [JsonPropertyName("defaultLanguage")]
        public string? DefaultLanguage { get; init; }

        [JsonPropertyName("domainEnvironmentVariable")]
        public string? DomainEnvironmentVariable { get; init; }

        [JsonPropertyName("ownerEnvironmentPrefix")]
        public string? OwnerEnvironmentPrefix { get; init; }
    }
}
