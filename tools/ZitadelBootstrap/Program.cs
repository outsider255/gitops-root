using System.Text.Json;

namespace ZitadelBootstrap;

internal sealed record CommandDependencies(
    Func<string, string?> Environment,
    Func<string, string> ReadFile,
    Func<HttpClient> CreateHttpClient,
    TextWriter Output);

internal static class BootstrapCommand
{
    private const int ConfigurationError = 2;
    private const int ApiError = 3;

    public static async Task<int> RunAsync(string[] args, CommandDependencies dependencies, CancellationToken cancellationToken = default)
    {
        try
        {
            var (configPath, dryRun) = ParseArguments(args);
            var config = BootstrapConfig.Load(configPath, dependencies.Environment, dependencies.ReadFile);

            if (dryRun)
            {
                foreach (var spec in config.Instances)
                {
                    await dependencies.Output.WriteLineAsync($"{spec.Key} {spec.CustomDomain} instanceId=(dry-run) created");
                }

                return 0;
            }

            var systemUrl = RequiredEnvironment(dependencies.Environment, "ZITADEL_SYSTEM_URL");
            if (!Uri.TryCreate(systemUrl, UriKind.Absolute, out var baseUri) || baseUri.Scheme != Uri.UriSchemeHttps)
            {
                throw new InvalidOperationException("ZITADEL_SYSTEM_URL must be an absolute HTTPS URL.");
            }

            var systemUser = RequiredEnvironment(dependencies.Environment, "ZITADEL_SYSTEM_USER");
            var privateKeyPath = RequiredEnvironment(dependencies.Environment, "ZITADEL_SYSTEM_PRIVATE_KEY_FILE");
            var owners = config.Instances.Select(spec => (spec, Owner: ReadOwner(spec, dependencies.Environment))).ToList();
            var privateKeyPem = dependencies.ReadFile(privateKeyPath);
            var token = SystemApiTokenFactory.Create(systemUser, baseUri, privateKeyPem, DateTimeOffset.UtcNow);

            using var http = dependencies.CreateHttpClient();
            http.BaseAddress = baseUri;
            var client = new ZitadelSystemClient(http, token);
            foreach (var (spec, owner) in owners)
            {
                var result = await client.EnsureInstanceAsync(spec, owner, cancellationToken);
                await dependencies.Output.WriteLineAsync($"{result.Key} {spec.CustomDomain} instanceId={result.InstanceId} {(result.Created ? "created" : "unchanged")}");
            }

            return 0;
        }
        catch (ZitadelSystemApiException)
        {
            await dependencies.Output.WriteLineAsync("System API request failed.");
            return ApiError;
        }
        catch (Exception exception) when (exception is ArgumentException or InvalidOperationException or IOException or UnauthorizedAccessException or JsonException)
        {
            await dependencies.Output.WriteLineAsync("Invalid bootstrap input or configuration.");
            return ConfigurationError;
        }
    }

    private static (string ConfigPath, bool DryRun) ParseArguments(string[] args)
    {
        if (args.Length is 2 or 3 && args[0] == "--config" && (args.Length == 2 || args[2] == "--dry-run"))
        {
            return (args[1], args.Length == 3);
        }

        throw new ArgumentException("Usage: --config <path> [--dry-run].");
    }

    private static InstanceOwner ReadOwner(ProductInstanceSpec spec, Func<string, string?> environment) => new(
        RequiredEnvironment(environment, $"{spec.OwnerEnvironmentPrefix}_USERNAME"),
        RequiredEnvironment(environment, $"{spec.OwnerEnvironmentPrefix}_EMAIL"),
        RequiredEnvironment(environment, $"{spec.OwnerEnvironmentPrefix}_FIRST_NAME"),
        RequiredEnvironment(environment, $"{spec.OwnerEnvironmentPrefix}_LAST_NAME"),
        RequiredEnvironment(environment, $"{spec.OwnerEnvironmentPrefix}_PASSWORD"));

    private static string RequiredEnvironment(Func<string, string?> environment, string name)
    {
        var value = environment(name);
        return !string.IsNullOrWhiteSpace(value)
            ? value
            : throw new InvalidOperationException($"Required environment variable '{name}' is missing.");
    }
}

public static class Program
{
    public static Task<int> Main(string[] args) => BootstrapCommand.RunAsync(
        args,
        new CommandDependencies(
            Environment.GetEnvironmentVariable,
            File.ReadAllText,
            () => new HttpClient(),
            Console.Out));
}
