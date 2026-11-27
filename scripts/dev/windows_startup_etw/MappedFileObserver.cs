using System;
using System.Diagnostics;
using System.IO;
using System.IO.MemoryMappedFiles;
using System.Runtime.InteropServices;
using System.Runtime.InteropServices.ComTypes;
using System.Text;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Win32.SafeHandles;

// Query-time metadata only. No ReadProcessMemory, VM_READ access, file-content
// reads, address serialization or ETW FileIO provider is used here.
internal sealed record MappedFileEvidence(string category, string? basename, string status,
    double event_delivery_delay_ms, double? lookup_delay_ms, double? lookup_ms, double observer_work_ms);

internal sealed class MappedFileObserver : IDisposable
{
    const uint QueryInformation = 0x0400, Synchronize = 0x00100000;
    const uint WaitTimeout = 258;
    const int BufferSize = 32768, MaxLookups = 4096;
    readonly string marker;
    readonly StringBuilder buffer = new(BufferSize);
    SafeProcessHandle? target;
    string? packageRoot, fontsRoot, systemRoot;
    long nextMarkerCheck;
    string bindStatus = "marker_unavailable";
    int lookups, markerChecks;
    double lookupTime, markerWork;
    bool rejected;

    internal MappedFileObserver(string markerPath) => marker = markerPath;

    [DllImport("kernel32.dll", SetLastError = true)]
    static extern SafeProcessHandle OpenProcess(uint access, [MarshalAs(UnmanagedType.Bool)] bool inherit, int pid);
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern uint WaitForSingleObject(SafeProcessHandle process, uint timeout);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool QueryFullProcessImageNameW(SafeProcessHandle process, uint flags, StringBuilder path, ref uint size);
    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    static extern bool GetProcessTimes(SafeProcessHandle process, out FILETIME creation, out FILETIME exit,
        out FILETIME kernel, out FILETIME user);
    [DllImport("psapi.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    static extern uint GetMappedFileNameW(SafeProcessHandle process, IntPtr address, StringBuilder filename, uint size);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    static extern SafeFileHandle CreateFileW(string path, uint access, uint share, IntPtr security,
        uint creation, uint flags, IntPtr template);
    [DllImport("kernel32.dll", CharSet = CharSet.Unicode, ExactSpelling = true, SetLastError = true)]
    static extern uint GetFinalPathNameByHandleW(SafeFileHandle file, StringBuilder path, uint size, uint flags);

    static ulong RawFiletime(FILETIME time) => ((ulong)(uint)time.dwHighDateTime << 32) | (uint)time.dwLowDateTime;

    static string? NtRoot(string? directory)
    {
        if (string.IsNullOrEmpty(directory) || !Path.IsPathFullyQualified(directory)) return null;
        // Directory metadata handle only: resolve junctions/drive aliases to
        // the same NT-volume namespace returned by GetMappedFileNameW.
        using var handle = CreateFileW(directory, 0, 7, IntPtr.Zero, 3, 0x02000000, IntPtr.Zero);
        if (handle.IsInvalid) return null;
        var root = new StringBuilder(BufferSize);
        uint count = GetFinalPathNameByHandleW(handle, root, BufferSize, 2); // VOLUME_NAME_NT
        return count > 0 && count < BufferSize - 1 ? root.ToString().TrimEnd('\\') + "\\" : null;
    }

    internal static (string category, string? basename) Classify(string path, string? package, string? fonts, string? system)
    {
        if (path.Contains(@"\..\", StringComparison.Ordinal) || path.Contains(@"\.\", StringComparison.Ordinal)) return ("other", null);
        bool Under(string? root) => !string.IsNullOrEmpty(root) &&
            path.StartsWith(root.TrimEnd('\\') + "\\", StringComparison.OrdinalIgnoreCase);
        string category = Under(package) ? "app-package" : Under(fonts) ? "windows-fonts" :
            Under(system) ? "windows-system32" : "other";
        if (category == "other") return (category, null);
        string basename = path[(path.LastIndexOf('\\') + 1)..];
        return (category, Regex.IsMatch(basename, "^[a-zA-Z0-9_.+-]{1,160}$") ? basename : null);
    }

    static string Canonical(string path)
    {
        string full = Path.GetFullPath(path);
        return full.StartsWith(@"\\?\", StringComparison.Ordinal) ? full[4..] : full;
    }

    internal void ObserveTarget(Timeline timeline, int pid, long tick, int checkerPid)
    {
        if (target != null || rejected || !timeline.IsTarget(pid, tick)) return;
        long now = Stopwatch.GetTimestamp();
        if (now < nextMarkerCheck) return;
        nextMarkerCheck = now + Program.FromMilliseconds(20);
        markerChecks++;
        SafeProcessHandle? handle = null;
        try
        {
            if (!File.Exists(marker)) return;
            using var document = JsonDocument.Parse(File.ReadAllText(marker));
            var data = document.RootElement;
            int expectedPid = data.GetProperty("pid").GetInt32();
            int depth = data.GetProperty("checker_lineage_depth").GetInt32();
            ulong creation = data.GetProperty("creation_filetime").GetUInt64();
            string exe = data.GetProperty("exe_path").GetString()!;
            if (data.GetProperty("checker_pid").GetInt32() != checkerPid || expectedPid != pid ||
                !timeline.MatchesLiveMarker(pid, tick, depth, creation) ||
                !Path.IsPathFullyQualified(exe) || !Path.GetFileName(exe).Equals("InvoiceHub.exe", StringComparison.OrdinalIgnoreCase))
                throw new InvalidDataException("identity");
            // No process is opened until ETW lifetime, ancestry and the
            // independent native observer marker all agree.
            handle = OpenProcess(QueryInformation | Synchronize, false, pid);
            if (handle.IsInvalid) { bindStatus = "open_query_handle_failed"; rejected = true; return; }
            uint size = BufferSize;
            buffer.Clear();
            if (!QueryFullProcessImageNameW(handle, 0, buffer, ref size) || size >= BufferSize - 1 ||
                !Canonical(buffer.ToString()).Equals(Canonical(exe), StringComparison.OrdinalIgnoreCase) ||
                !GetProcessTimes(handle, out var actualCreation, out _, out _, out _) || RawFiletime(actualCreation) != creation)
                throw new InvalidDataException("identity");
            if (WaitForSingleObject(handle, 0) != WaitTimeout) { bindStatus = "target_not_live"; rejected = true; return; }
            packageRoot = NtRoot(Path.GetDirectoryName(exe));
            fontsRoot = NtRoot(Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.Windows), "Fonts"));
            systemRoot = NtRoot(Environment.SystemDirectory);
            target = handle;
            handle = null;
            bindStatus = "verified";
        }
        catch (InvalidDataException) { bindStatus = "identity_mismatch"; rejected = true; }
        catch (Exception) { bindStatus = "marker_or_query_unavailable"; rejected = true; }
        finally { handle?.Dispose(); markerWork += Program.Milliseconds(Stopwatch.GetTimestamp() - now); }
    }

    internal MappedFileEvidence Lookup(Timeline timeline, int pid, long tick, ulong address, int checkerPid)
    {
        long began = Stopwatch.GetTimestamp();
        double delivery = Program.Milliseconds(began - tick);
        long? queryStarted = null;
        MappedFileEvidence Missing(string status) => new("unknown", null, status, delivery, null, null,
            Program.Milliseconds(Stopwatch.GetTimestamp() - began));
        try
        {
            ObserveTarget(timeline, pid, tick, checkerPid);
            if (target == null) return Missing(bindStatus);
            if (WaitForSingleObject(target, 0) != WaitTimeout) return Missing("target_not_live");
            if (lookups >= MaxLookups) return Missing("lookup_budget_exhausted");
            lookups++;
            buffer.Clear();
            long query = Stopwatch.GetTimestamp();
            queryStarted = query;
            uint count = GetMappedFileNameW(target, unchecked((IntPtr)(long)address), buffer, BufferSize);
            double elapsed = Program.Milliseconds(Stopwatch.GetTimestamp() - query);
            lookupTime += elapsed;
            string status = count == 0 ? "mapping_unavailable" : count >= BufferSize - 1 ? "truncated" : "query_observed";
            var classified = status == "query_observed" ? Classify(buffer.ToString(), packageRoot, fontsRoot, systemRoot) : ("unknown", (string?)null);
            return new(classified.Item1, classified.Item2, status, delivery, Program.Milliseconds(query - tick), elapsed,
                Program.Milliseconds(Stopwatch.GetTimestamp() - began));
        }
        catch (Exception)
        {
            if (!queryStarted.HasValue) return Missing("query_unavailable");
            double elapsed = Program.Milliseconds(Stopwatch.GetTimestamp() - queryStarted.Value);
            lookupTime += elapsed;
            return new("unknown", null, "query_unavailable", delivery, Program.Milliseconds(queryStarted.Value - tick),
                elapsed, Program.Milliseconds(Stopwatch.GetTimestamp() - began));
        }
    }

    internal object Coverage() => new { identity_status = bindStatus, verified = target != null,
        app_root_resolved = packageRoot != null, fonts_root_resolved = fontsRoot != null, system32_root_resolved = systemRoot != null,
        direct_lookups = lookups, max_direct_lookups = MaxLookups, total_lookup_ms = Math.Round(lookupTime, 3),
        marker_checks = markerChecks, total_marker_work_ms = Math.Round(markerWork, 3),
        meaning = "mapping at delayed query time only; no cache, no historical VA-to-file assertion" };

    public void Dispose() => target?.Dispose();

    internal static bool ClassificationSelfTest() =>
        Classify(@"\Device\Volume\App\qt.dll", @"\Device\Volume\App\", null, null) == ("app-package", "qt.dll") &&
        Classify(@"\Device\Volume\App-other\user-file.txt", @"\Device\Volume\App\", null, null) == ("other", null) &&
        Classify(@"\Device\Volume\Windows\Fonts\ABC.ttf", null, @"\device\volume\windows\fonts\", null) == ("windows-fonts", "ABC.ttf") &&
        Classify(@"\Device\Volume\Windows\System32x\private.dll", null, null, @"\Device\Volume\Windows\System32\") == ("other", null) &&
        Classify(@"\Device\Volume\App\unsafe name.txt", @"\Device\Volume\App\", null, null) == ("app-package", null);

    internal static int NativeSelfTest()
    {
        if (!OperatingSystem.IsWindows()) return 1;
        string directory = Path.Combine(Path.GetTempPath(), "InvoiceHubMappingFixture-" + Guid.NewGuid().ToString("N"));
        Directory.CreateDirectory(directory);
        const string leaf = "ih-mapping-fixture.bin";
        try
        {
            string path = Path.Combine(directory, leaf);
            using (var file = File.Create(path)) file.SetLength(4096);
            using var mapping = MemoryMappedFile.CreateFromFile(path, FileMode.Open, null, 4096, MemoryMappedFileAccess.Read);
            using var view = mapping.CreateViewAccessor(0, 4096, MemoryMappedFileAccess.Read);
            using var process = OpenProcess(QueryInformation | Synchronize, false, Environment.ProcessId);
            var buffer = new StringBuilder(BufferSize);
            uint count = process.IsInvalid ? 0 : GetMappedFileNameW(process, view.SafeMemoryMappedViewHandle.DangerousGetHandle(), buffer, BufferSize);
            var result = count > 0 && count < BufferSize - 1 ? Classify(buffer.ToString(), NtRoot(directory), null, null) : ("unknown", (string?)null);
            bool ok = result == ("app-package", leaf);
            Console.WriteLine("PERF_AB_MAPPED_SELFTEST " + JsonSerializer.Serialize(new { passed = ok, category = result.Item1, basename = result.Item2 }));
            return ok ? 0 : 1;
        }
        catch (Exception error)
        {
            Console.WriteLine("PERF_AB_MAPPED_SELFTEST " + JsonSerializer.Serialize(new { passed = false, error = error.GetType().Name }));
            return 1;
        }
        finally { Directory.Delete(directory, true); }
    }
}
