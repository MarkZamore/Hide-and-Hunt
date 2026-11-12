using System.IO;
using System.Net;
using System.Net.Http;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using Minecraft;

var migrate = args.Length == 4 && args[3] == "--verify-update";
if (args.Length != 3 && !migrate) throw new ArgumentException(
    "Usage: <launcher-assembly> <qa-installation-under-agent-runs> <verified-pack-manifest> [--verify-update]");
var launcher = Path.GetFullPath(args[0]);
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    var file = Path.Combine(Path.GetDirectoryName(launcher)!, name.Name + ".dll");
    return File.Exists(file) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(file) : null;
};
await VerifyInstallationAsync(Path.GetFullPath(args[1]), Path.GetFullPath(args[2]), migrate);

static async Task VerifyInstallationAsync(string install, string manifestPath, bool migrate)
{
    var root = new DirectoryInfo(install);
    if (root.Exists != migrate || root.Parent is not { Exists: true })
        throw new ArgumentException("Use a new directory for a clean install or an existing QA install for an update.");
    var insideRun = false;
    for (var parent = root.Exists ? root : root.Parent; parent is not null; parent = parent.Parent)
    {
        if ((parent.Attributes & FileAttributes.ReparsePoint) != 0)
            throw new ArgumentException("Installation ancestors must not be reparse points.");
        insideRun |= parent.Name == "agent-runs" && parent.Parent?.Name == "artifacts";
    }
    if (!insideRun) throw new ArgumentException("Installation must be under artifacts/agent-runs.");

    const string name = "Hide and Hunt";
    var paths = new AppPaths(install);
    paths.Ensure();
    var canonical = paths.CombineUnderPacks(name);
    const string source = """{"schemaVersion":1,"owner":"MarkZamore","repo":"Hide-and-Hunt","tag":"pack-latest"}""";
    var marker = Path.Combine(canonical, PortablePackSyncService.SourceMarkerFileName);
    if (migrate)
        Require(await File.ReadAllTextAsync(marker) == source, "The QA install must come from the Hide and Hunt release.");
    else
    {
        Directory.CreateDirectory(canonical);
        await File.WriteAllTextAsync(marker, source);
    }
    using var manifest = JsonDocument.Parse(await File.ReadAllBytesAsync(manifestPath));
    var files = manifest.RootElement.GetProperty("files").EnumerateArray().ToArray();
    var revision = manifest.RootElement.GetProperty("revision").GetString();
    var logger = new Logger(paths.LogFile);
    using var release = migrate ? new HttpClient(new StageRelease(manifestPath, manifest.RootElement)) : null;
    var sync = new PortablePackSyncService(paths, logger, release);
    using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
    using var instances = new PackInstanceService(paths, logger);
    JsonElement[] retired = migrate ? manifest.RootElement.GetProperty("legacyFiles").EnumerateArray().ToArray() : [];
    var personal = new Dictionary<string, byte[]>();
    if (migrate)
    {
        var previous = await instances.PrepareAsync(name, timeout.Token);
        foreach (var file in retired)
        {
            VerifyFile(canonical, file);
            if (file.GetProperty("path").GetString()!.StartsWith("mods/", StringComparison.Ordinal))
                VerifyFile(previous.GameDirectory, file);
        }
        foreach (var (relative, markerContent) in new (string Path, string Content)[]
        {
            ("options.txt", "fov:0.25\n"),
            ("servers.dat", "synthetic manual server marker"),
            ("saves/HideHuntQa/hideandhunt/statistik.json", """{"qa":{"points":42,"wins":1}}""")
        })
        {
            var target = Path.Combine(previous.GameDirectory, relative);
            Directory.CreateDirectory(Path.GetDirectoryName(target)!);
            if (!File.Exists(target)) await File.WriteAllTextAsync(target, markerContent);
            personal.Add(relative, await File.ReadAllBytesAsync(target));
        }
    }
    var installed = await sync.SyncAsync(name, null, timeout.Token);
    Require(installed.Outcome == (migrate ? PackSyncOutcome.Updated : PackSyncOutcome.Installed) &&
            installed.Revision == revision, $"Unexpected installation result {installed.Outcome}.");
    if (!migrate) Require(installed.FilesChanged == files.Length, "Clean install has unexpected file count.");
    foreach (var file in files) VerifyFile(canonical, file);

    var instance = await instances.PrepareAsync(name, timeout.Token);
    foreach (var file in files.Where(file => file.GetProperty("path").GetString()!.StartsWith("mods/", StringComparison.Ordinal)))
        VerifyFile(instance.GameDirectory, file);
    VerifyFile(instance.GameDirectory, files.Single(file => file.GetProperty("path").GetString() == "config/log4j2.xml"));
    foreach (var file in retired)
    {
        var relative = file.GetProperty("path").GetString()!;
        Require(!File.Exists(Path.Combine(canonical, relative)) && !File.Exists(Path.Combine(instance.GameDirectory, relative)),
            $"Retired pack file survived: {relative}.");
    }
    var options = Path.Combine(instance.GameDirectory, "options.txt");
    if (!migrate)
    {
        await File.WriteAllTextAsync(options, "fov:0.25\n");
        personal.Add("options.txt", await File.ReadAllBytesAsync(options));
    }
    var repeated = await sync.SyncAsync(name, null, timeout.Token);
    Require(repeated.Outcome == PackSyncOutcome.UpToDate && repeated.Revision == revision && repeated.BytesDownloaded == 0,
        $"Unexpected repeat result {repeated.Outcome}.");
    await instances.PrepareAsync(name, timeout.Token);
    foreach (var (relative, bytes) in personal)
    {
        var after = await File.ReadAllBytesAsync(Path.Combine(instance.GameDirectory, relative));
        Require(bytes.SequenceEqual(after), $"A personal file changed: {relative}.");
    }
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        revision, files = files.Length, installed.BytesDownloaded, installed = installed.Outcome.ToString(),
        repeated = repeated.Outcome.ToString(), retiredVerified = retired.Length, personalFilesPreserved = personal.Count
    }));
}

static void VerifyFile(string directory, JsonElement entry)
{
    var relative = entry.GetProperty("path").GetString()!;
    var target = Path.Combine(directory, relative);
    using var stream = File.OpenRead(target);
    Require(stream.Length == entry.GetProperty("sizeBytes").GetInt64() &&
        Convert.ToHexString(SHA256.HashData(stream)).Equals(entry.GetProperty("sha256").GetString(), StringComparison.OrdinalIgnoreCase),
        $"Unexpected installed bytes for {relative}.");
}

static void Require(bool condition, string message)
{
    if (!condition) throw new InvalidOperationException(message);
}

sealed class StageRelease(string manifestPath, JsonElement manifest) : HttpMessageHandler
{
    private const string Origin = "https://github.com/MarkZamore/Hide-and-Hunt/releases/download/pack-latest/";
    private readonly HashSet<string> assets = manifest.GetProperty("assets").EnumerateArray()
        .Select(row => row.GetProperty("name").GetString()!).ToHashSet(StringComparer.Ordinal);

    protected override Task<HttpResponseMessage> SendAsync(HttpRequestMessage request, CancellationToken cancellationToken)
    {
        cancellationToken.ThrowIfCancellationRequested();
        var uri = request.RequestUri!;
        if (request.Method != HttpMethod.Get || !uri.GetLeftPart(UriPartial.Path).StartsWith(Origin, StringComparison.Ordinal))
            throw new InvalidOperationException("Unexpected request during isolated pack update.");
        var name = Uri.UnescapeDataString(uri.Segments[^1]);
        if (name != Path.GetFileName(name)) throw new InvalidOperationException("Unexpected release asset name.");
        var file = name == PortablePackSyncService.PackManifestAssetName ? manifestPath :
            assets.Contains(name) ? Path.Combine(Path.GetDirectoryName(manifestPath)!, "assets", name) :
            throw new InvalidOperationException("Asset is absent from the staged release: " + name);
        return Task.FromResult(new HttpResponseMessage(HttpStatusCode.OK) { Content = new StreamContent(File.OpenRead(file)) });
    }
}
