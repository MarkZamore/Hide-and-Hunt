using System.IO;
using System.Runtime.Loader;
using System.Security.Cryptography;
using System.Text.Json;
using Minecraft;

if (args.Length != 3) throw new ArgumentException(
    "Usage: <launcher-assembly> <new-installation-under-agent-runs> <verified-pack-manifest>");
var launcher = Path.GetFullPath(args[0]);
AssemblyLoadContext.Default.Resolving += (_, name) =>
{
    var file = Path.Combine(Path.GetDirectoryName(launcher)!, name.Name + ".dll");
    return File.Exists(file) ? AssemblyLoadContext.Default.LoadFromAssemblyPath(file) : null;
};
await VerifyInstallationAsync(Path.GetFullPath(args[1]), Path.GetFullPath(args[2]));

static async Task VerifyInstallationAsync(string install, string manifestPath)
{
    var root = new DirectoryInfo(install);
    if (root.Exists || root.Parent is not { Exists: true })
        throw new ArgumentException("Use a new installation directory under an existing task run.");
    var insideRun = false;
    for (var parent = root.Parent; parent is not null; parent = parent.Parent)
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
    Directory.CreateDirectory(canonical);
    await File.WriteAllTextAsync(Path.Combine(canonical, PortablePackSyncService.SourceMarkerFileName),
        """{"schemaVersion":1,"owner":"MarkZamore","repo":"Hide-and-Hunt","tag":"pack-latest"}""");
    using var manifest = JsonDocument.Parse(await File.ReadAllBytesAsync(manifestPath));
    var files = manifest.RootElement.GetProperty("files").EnumerateArray().ToArray();
    var revision = manifest.RootElement.GetProperty("revision").GetString();
    var logger = new Logger(paths.LogFile);
    var sync = new PortablePackSyncService(paths, logger);
    using var timeout = new CancellationTokenSource(TimeSpan.FromMinutes(3));
    var installed = await sync.SyncAsync(name, null, timeout.Token);
    Require(installed.Outcome == PackSyncOutcome.Installed && installed.Revision == revision &&
            installed.FilesChanged == files.Length, $"Unexpected installation result {installed.Outcome}.");
    foreach (var file in files) VerifyFile(canonical, file);

    using var instances = new PackInstanceService(paths, logger);
    var instance = await instances.PrepareAsync(name, timeout.Token);
    foreach (var file in files.Where(file => file.GetProperty("path").GetString()!.StartsWith("mods/", StringComparison.Ordinal)))
        VerifyFile(instance.GameDirectory, file);
    VerifyFile(instance.GameDirectory, files.Single(file => file.GetProperty("path").GetString() == "config/log4j2.xml"));
    var options = Path.Combine(instance.GameDirectory, "options.txt");
    await File.WriteAllTextAsync(options, "fov:0.25\n");
    var repeated = await sync.SyncAsync(name, null, timeout.Token);
    Require(repeated.Outcome == PackSyncOutcome.UpToDate && repeated.Revision == revision && repeated.BytesDownloaded == 0,
        $"Unexpected repeat result {repeated.Outcome}.");
    await instances.PrepareAsync(name, timeout.Token);
    Require(await File.ReadAllTextAsync(options) == "fov:0.25\n", "The existing profile setting changed.");
    Console.WriteLine(JsonSerializer.Serialize(new
    {
        revision, files = files.Length, installed.BytesDownloaded, installed = installed.Outcome.ToString(),
        repeated = repeated.Outcome.ToString(), personalOptionsPreserved = true
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
