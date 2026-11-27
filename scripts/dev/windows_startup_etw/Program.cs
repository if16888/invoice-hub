using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
using Microsoft.Diagnostics.Tracing.Parsers;
using Microsoft.Diagnostics.Tracing.Session;

// TraceEvent recommends relative timestamps for display. Raw QPC ticks are
// used here only to align the target's scheduler and Win32 window samples.
#pragma warning disable CS0618

// A disposable, real-time system logger. No ETL, command lines, window text,
// kernel addresses, arbitrary file paths, or other processes' data are written.
internal static class Program
{
    internal static double Milliseconds(long ticks) => ticks * 1000.0 / Stopwatch.Frequency;
    internal static long FromMilliseconds(double ms) => (long)Math.Round(ms * Stopwatch.Frequency / 1000.0);

    static void WriteJson(string file, object value)
    {
        string temporary = file + ".new";
        File.WriteAllText(temporary, JsonSerializer.Serialize(value));
        File.Move(temporary, file, true);
    }

    // A Windows venv python.exe may be a redirector that launches the real
    // interpreter. Track only the known checker's live Python descendants.
    internal sealed class CheckerLineage
    {
        readonly Dictionary<int, (long Tick, int Depth)> interpreters = new();
        bool rootEnded;
        internal int Root { get; set; }
        internal int PythonStarts { get; private set; }

        internal int ParentDepth(int parent, long tick)
        {
            if (Root > 0 && parent == Root && !rootEnded) return 0;
            return interpreters.TryGetValue(parent, out var value) && value.Tick <= tick ? value.Depth : -1;
        }

        internal int Start(int process, int parent, long tick, string image)
        {
            int depth = ParentDepth(parent, tick);
            if (depth < 0 || depth >= 4) return -1;
            string basename = Path.GetFileName(image.Replace('\\', '/'));
            if (string.Equals(basename, "python.exe", StringComparison.OrdinalIgnoreCase))
            {
                interpreters[process] = (tick, depth + 1);
                PythonStarts++;
            }
            return string.Equals(basename, "InvoiceHub.exe", StringComparison.OrdinalIgnoreCase) ? depth + 1 : -1;
        }

        internal void End(int process, long tick)
        {
            if (process == Root) rootEnded = true;
            if (interpreters.TryGetValue(process, out var value) && value.Tick <= tick)
                interpreters.Remove(process);
        }
    }

    static bool StopOwnedSession(string name)
    {
        // Do not call TraceEventSession.Stop: its generic cleanup resets the
        // global CPU profiling interval. Only stop our unique named session.
        if (!TraceEventSession.GetActiveSessionNames().Contains(name, StringComparer.OrdinalIgnoreCase))
            return true;
        using var process = Process.Start(new ProcessStartInfo("logman.exe")
        {
            ArgumentList = { "stop", name, "-ets" },
            UseShellExecute = false, CreateNoWindow = true,
            RedirectStandardOutput = true, RedirectStandardError = true,
        });
        if (process == null)
            return false;
        var output = process.StandardOutput.ReadToEndAsync();
        var error = process.StandardError.ReadToEndAsync();
        if (!process.WaitForExit(10000))
        {
            process.Kill();
            return false;
        }
        return process.ExitCode == 0 &&
            !TraceEventSession.GetActiveSessionNames().Contains(name, StringComparer.OrdinalIgnoreCase);
    }

    static int Main(string[] args)
    {
        if (args.Length == 1 && args[0] == "--self-test")
            return Timeline.SelfTest();
        if (args.Length == 1 && args[0] == "--trace-fixture")
        {
            // A non-GUI infrastructure fixture. No Qt, probe metrics or
            // production program is launched.
            var pages = new byte[2 * 1024 * 1024];
            for (int i = 0; i < pages.Length; i += 4096) pages[i] = 1;
            Thread.Sleep(1100);
            GC.KeepAlive(pages);
            return 0;
        }
        if (args.Length != 2 || !Regex.IsMatch(args[0], "^InvoiceHubStartup-[a-f0-9]{32}$"))
            return 2;
        string name = args[0], directory = Path.GetFullPath(args[1]);
        string ready = Path.Combine(directory, "ready.json"), stop = Path.Combine(directory, "stop.json");
        string checker = Path.Combine(directory, "checker.pid");
        string result = Path.Combine(directory, "result.json");
        var timeline = new Timeline();
        var lineage = new CheckerLineage();
        TraceEventSession? session = null;
        bool owned = false, drained = false, cleanup = false;
        int? lost = null;
        string? failure = null;
        Task<bool>? consumer = null;
        try
        {
            if (!OperatingSystem.IsWindows())
                throw new PlatformNotSupportedException();
            if (TraceEventSession.GetActiveSessionNames().Contains(name, StringComparer.OrdinalIgnoreCase))
                throw new InvalidOperationException("Session name already exists");
            owned = true; // only this random, previously absent session may be stopped
            WriteJson(Path.Combine(directory, "claimed.json"), new { session = name });
            session = new TraceEventSession(name,
                TraceEventSessionOptions.Create | TraceEventSessionOptions.NoRestartOnCreate);
            session.StopOnDispose = false;
            session.BufferSizeMB = 32;
            const KernelTraceEventParser.Keywords switches = KernelTraceEventParser.Keywords.ContextSwitch;
            const KernelTraceEventParser.Keywords hard = KernelTraceEventParser.Keywords.MemoryHardFaults;
            session.EnableKernelProvider(
                KernelTraceEventParser.Keywords.Process | KernelTraceEventParser.Keywords.Thread |
                KernelTraceEventParser.Keywords.ImageLoad | KernelTraceEventParser.Keywords.Dispatcher |
                switches | hard, switches | hard);
            var source = session.Source;
            var kernel = new KernelTraceEventParser(source, KernelTraceEventParser.ParserTrackingOptions.ThreadToProcess);
            kernel.ProcessStart += data =>
            {
                if (lineage.Root == 0 && File.Exists(checker) &&
                    int.TryParse(File.ReadAllText(checker), NumberStyles.None, CultureInfo.InvariantCulture, out int parent))
                    lineage.Root = parent;
                if (lineage.ParentDepth(data.ParentID, data.TimeStampQPC) < 0)
                    return;
                int depth = lineage.Start(data.ProcessID, data.ParentID, data.TimeStampQPC, data.KernelImageFileName);
                if (depth > 0)
                    timeline.Start(data.ProcessID, data.TimeStampQPC,
                        new DateTimeOffset(data.TimeStamp.ToUniversalTime()).ToUnixTimeMilliseconds(), depth);
            };
            kernel.ProcessStop += data =>
            {
                timeline.End(data.ProcessID, data.TimeStampQPC);
                lineage.End(data.ProcessID, data.TimeStampQPC);
            };
            kernel.ThreadStart += data => timeline.ThreadStart(data.ProcessID, data.ThreadID, data.TimeStampQPC);
            kernel.ThreadStop += data => timeline.ThreadEnd(data.ProcessID, data.ThreadID, data.TimeStampQPC);
            kernel.ImageLoad += data =>
            {
                if (timeline.IsTarget(data.ProcessID, data.TimeStampQPC))
                    timeline.Image(data.TimeStampQPC, data.ImageBase, data.ImageSize, Path.GetFileName(data.FileName), false);
            };
            kernel.ImageUnload += data =>
            {
                if (timeline.IsTarget(data.ProcessID, data.TimeStampQPC))
                    timeline.Image(data.TimeStampQPC, data.ImageBase, data.ImageSize, "", true);
            };
            kernel.ThreadCSwitch += data =>
            {
                long tick = data.TimeStampQPC;
                if (timeline.IsTarget(data.OldProcessID, tick))
                    timeline.Switch(data.OldThreadID, tick, "out", data.OldThreadState.ToString(), data.OldThreadWaitReason.ToString());
                if (timeline.IsTarget(data.NewProcessID, tick))
                    timeline.Switch(data.NewThreadID, tick, "in");
            };
            kernel.DispatcherReadyThread += data =>
            {
                if (timeline.IsTarget(data.AwakenedProcessID, data.TimeStampQPC))
                    timeline.Switch(data.AwakenedThreadID, data.TimeStampQPC, "ready");
            };
            kernel.MemoryHardFault += data =>
            {
                if (timeline.IsTarget(data.ProcessID, data.TimeStampQPC))
                    timeline.Fault(data.ThreadID, data.TimeStampQPC, data.VirtualAddress, data.ByteCount, data.ElapsedTimeMSec);
            };
            kernel.StackWalkStack += data =>
            {
                long tick = data.EventTimeStampQPC;
                if (timeline.IsTarget(data.ProcessID, tick))
                {
                    var frames = new ulong[Math.Min(data.FrameCount, 64)];
                    for (int i = 0; i < frames.Length; i++)
                        frames[i] = data.InstructionPointer(i);
                    timeline.Stack(data.ThreadID, tick, frames);
                }
            };
            consumer = Task.Run(() => source.Process());
            WriteJson(ready, new { status = "ready", session = name });
            var deadline = Stopwatch.StartNew();
            while (!File.Exists(stop) && !consumer.IsCompleted && deadline.Elapsed.TotalSeconds < 100)
                Thread.Sleep(30);
            if (!File.Exists(stop))
                failure = "No completion marker or consumer ended early";
            session.Flush();
            // ETW delivers real-time buffers asynchronously; give the consumer
            // the flushed events before stopping our session and joining it.
            Thread.Sleep(150);
            lost = session.EventsLost;
            cleanup = StopOwnedSession(name);
            drained = consumer.Wait(TimeSpan.FromSeconds(10)) && consumer.Result;
        }
        catch (Exception error)
        {
            // NoRestartOnCreate can race a duplicate name. In that case we
            // never acquired a session and must not stop the existing one.
            if (unchecked((uint)error.HResult) == 0x800700B7)
            {
                owned = false;
                File.Delete(Path.Combine(directory, "claimed.json"));
            }
            failure = error.GetType().Name + " (HRESULT " + error.HResult.ToString("X8") + ")";
        }
        finally
        {
            if (owned && !cleanup)
            {
                try { cleanup = StopOwnedSession(name); }
                catch { cleanup = false; }
            }
            session?.Dispose();
        }
        if (!File.Exists(ready))
            WriteJson(ready, new { status = "unavailable", error = failure, cleanup });
        if (failure != null || !drained || !File.Exists(stop))
        {
            WriteJson(result, new { status = "unavailable", error = failure ?? "Trace consumer did not drain", cleanup, drained, events_lost = lost });
            return 1;
        }
        try
        {
            using var observation = JsonDocument.Parse(File.ReadAllText(stop));
            var report = timeline.Report(observation.RootElement, lost, cleanup);
            report["checker_lineage"] = new { root_marker_seen = lineage.Root > 0,
                python_descendant_starts = lineage.PythonStarts };
            WriteJson(result, report);
            return (string)report["status"]! == "unavailable" ? 1 : 0;
        }
        catch (Exception error)
        {
            WriteJson(result, new { status = "unavailable", error = "Report: " + error.GetType().Name, cleanup, events_lost = lost });
            return 1;
        }
    }
}

internal sealed class Timeline
{
    record ThreadLife(long Start, long? End);
    record Point(int Thread, long Tick, string Kind, string State, string Reason);
    record ImageEvent(long Tick, ulong Base, int Size, string Name, bool Unload);
    record FaultEvent(int Thread, long Tick, ulong Address, int Bytes, double Duration);
    record Slice(int Thread, long Start, long End, string State, string Reason, long? Ready, bool Censored);

    const int MaxEvents = 150_000;
    readonly Dictionary<int, List<ThreadLife>> lives = new();
    readonly List<Point> points = new();
    readonly List<ImageEvent> images = new();
    readonly List<FaultEvent> faults = new();
    readonly Dictionary<(int, long), List<ulong[]>> stacks = new();
    int pid, eventCount, targetDepth;
    long start, end, creationUtc;
    bool ambiguous, limited;

    bool Accept()
    {
        if (++eventCount <= MaxEvents)
            return true;
        limited = true;
        return false;
    }

    internal void Start(int process, long tick, long creationUtcMs, int depth)
    {
        if (pid != 0)
        {
            ambiguous = true;
            return;
        }
        pid = process;
        start = tick;
        creationUtc = creationUtcMs;
        targetDepth = depth;
    }

    internal bool IsTarget(int process, long tick) =>
        !ambiguous && pid > 0 && process == pid && tick >= start && (end == 0 || tick <= end);

    internal void End(int process, long tick)
    {
        if (IsTarget(process, tick))
            end = tick;
    }

    internal void ThreadStart(int process, int thread, long tick)
    {
        if (!IsTarget(process, tick) || !Accept())
            return;
        if (!lives.TryGetValue(thread, out var list))
            lives[thread] = list = new();
        list.Add(new(tick, null));
    }

    internal void ThreadEnd(int process, int thread, long tick)
    {
        if (IsTarget(process, tick) && lives.TryGetValue(thread, out var list) && list.Count > 0)
            list[^1] = list[^1] with { End = tick };
    }

    bool Owns(int thread, long tick) => lives.TryGetValue(thread, out var list) &&
        list.Any(life => tick >= life.Start && (life.End == null || tick <= life.End));

    internal void Switch(int thread, long tick, string kind, string state = "", string reason = "")
    {
        if (Accept()) points.Add(new(thread, tick, kind, state, reason));
    }

    internal void Image(long tick, ulong address, int size, string name, bool unload)
    {
        if (!Accept()) return;
        // Only a conventional module basename is eligible for output.
        string safe = Regex.IsMatch(name, "^[a-zA-Z0-9_.+-]{1,120}$") ? name : "<unknown-image>";
        images.Add(new(tick, address, size, safe, unload));
    }

    internal void Fault(int thread, long tick, ulong address, int bytes, double duration)
    {
        if (Accept()) faults.Add(new(thread, tick, address, bytes, duration));
    }

    internal void Stack(int thread, long tick, ulong[] frames)
    {
        if (!Accept()) return;
        if (!stacks.TryGetValue((thread, tick), out var list))
            stacks[(thread, tick)] = list = new();
        if (list.Count < 4)
            list.Add(frames);
    }

    string Module(ulong address, long tick)
    {
        var load = images.Where(m => m.Tick <= tick && address >= m.Base &&
            address - m.Base < (ulong)Math.Max(m.Size, 0) && !m.Unload)
            .OrderByDescending(m => m.Tick).FirstOrDefault();
        if (load == null || images.Any(m => m.Unload && m.Base == load.Base && m.Tick >= load.Tick && m.Tick <= tick))
            return "<unmapped>";
        return load.Name + "+0x" + (address - load.Base).ToString("X");
    }

    string[][] StackFor(int thread, long tick) =>
        stacks.TryGetValue((thread, tick), out var list) && Owns(thread, tick)
            ? list.Select(frames => frames.Select(address => Module(address, tick)).ToArray()).ToArray()
            : Array.Empty<string[]>();

    double Relative(long tick) => Math.Round(Program.Milliseconds(tick - start), 3);
    static double Duration(long ticks) => Math.Round(Program.Milliseconds(ticks), 3);

    (List<Slice> waits, List<(long Start, long End)> running) Intervals(int thread, long cutoff)
    {
        var waits = new List<Slice>();
        var running = new List<(long Start, long End)>();
        // Process each lifetime independently; TID reuse and initial/rundown
        // gaps never create a cross-lifetime wait or a fabricated initial run.
        foreach (var life in lives[thread])
        {
            long limit = Math.Min(cutoff, life.End ?? cutoff);
            Point? switchedOut = null;
            long? ready = null, switchedIn = null;
            foreach (var point in points.Where(p => p.Thread == thread && p.Tick >= life.Start && p.Tick <= limit)
                         .OrderBy(p => p.Tick).ThenBy(p => p.Kind == "out" ? 0 : p.Kind == "ready" ? 1 : 2))
            {
                if (point.Kind == "out")
                {
                    if (switchedIn.HasValue && point.Tick > switchedIn)
                        running.Add((switchedIn.Value, point.Tick));
                    switchedIn = null;
                    switchedOut = point;
                    ready = point.State == "Ready" ? point.Tick : null;
                }
                else if (point.Kind == "ready" && switchedOut != null)
                {
                    ready ??= point.Tick;
                }
                else if (point.Kind == "in")
                {
                    if (switchedOut != null && point.Tick > switchedOut.Tick)
                        waits.Add(new(thread, switchedOut.Tick, point.Tick, switchedOut.State, switchedOut.Reason, ready, false));
                    switchedOut = null;
                    ready = null;
                    switchedIn = point.Tick;
                }
            }
            if (switchedOut != null && limit > switchedOut.Tick)
                waits.Add(new(thread, switchedOut.Tick, limit, switchedOut.State, switchedOut.Reason, ready, true));
            // Do not count an unpaired switch-in as CPU time.
        }
        return (waits, running);
    }

    static long Overlap(long lo, long hi, long otherLo, long otherHi) =>
        Math.Max(0, Math.Min(hi, otherHi) - Math.Max(lo, otherLo));

    object Phase(List<Slice> waits, List<(long Start, long End)> running, long lo, long hi)
    {
        long off = waits.Sum(w => Overlap(w.Start, w.End, lo, hi));
        long run = running.Sum(w => Overlap(w.Start, w.End, lo, hi));
        long ready = waits.Sum(w => w.Ready.HasValue ? Overlap(w.Ready.Value, w.End, lo, hi) : 0);
        long blocked = waits.Sum(w => w.Ready.HasValue ? Overlap(w.Start, w.Ready.Value, lo, hi) : 0);
        return new { start_ms = Relative(lo), end_ms = Relative(hi), off_cpu_ms = Duration(off),
            completed_running_ms = Duration(run), observed_ready_ms = Duration(ready),
            observed_before_ready_ms = Duration(blocked), off_cpu_without_ready_event_ms = Duration(off - ready - blocked),
            uncovered_ms = Duration(Math.Max(0, hi - lo - off - run)) };
    }

    internal Dictionary<string, object?> Report(JsonElement control, int? lost, bool cleanup)
    {
        bool nativePid = control.TryGetProperty("gui_pid", out var verified) && verified.ValueKind == JsonValueKind.Number;
        bool pidMatches = nativePid && verified.GetInt32() == pid;
        bool nativeCreation = control.TryGetProperty("gui_creation_unix_ms", out var creation) &&
            creation.ValueKind == JsonValueKind.Number;
        double? creationDelta = pidMatches && nativeCreation ? creation.GetDouble() - creationUtc : null;
        bool nativeDepth = control.TryGetProperty("checker_lineage_depth", out var depth) && depth.ValueKind == JsonValueKind.Number;
        bool depthMatches = nativeDepth && depth.GetInt32() == targetDepth;
        var identity = new { matched_start = pid > 0, matched_stop = end > start, ambiguous,
            native_pid_observed = nativePid, pid_matches = pidMatches, native_creation_observed = nativeCreation,
            creation_delta_ms = creationDelta, creation_matches = creationDelta.HasValue && Math.Abs(creationDelta.Value) <= 250,
            etw_depth = pid > 0 ? targetDepth : (int?)null, native_depth = nativeDepth ? depth.GetInt32() : (int?)null,
            depth_matches = depthMatches };
        if (ambiguous || pid <= 0 || end <= start || !pidMatches || !identity.creation_matches || !depthMatches)
            return new() { ["status"] = "unavailable", ["error"] = "ETW child and independently path-verified target did not match",
                ["identity_checks"] = identity, ["events_lost"] = lost, ["cleanup"] = cleanup };

        var marks = new SortedDictionary<string, long>();
        foreach (var mark in control.GetProperty("markers").EnumerateObject())
            if (mark.Value.TryGetProperty("qpc_ms", out var qpc) && qpc.ValueKind == JsonValueKind.Number)
                marks[mark.Name] = Program.FromMilliseconds(qpc.GetDouble());
        long latest = points.Select(p => p.Tick).Concat(faults.Select(f => f.Tick)).DefaultIfEmpty(start).Max();
        long cutoff = end > 0 ? end : latest;
        bool paintObserved = marks.TryGetValue("valid_probe_file_observed", out long paintTick) && paintTick >= start;
        if (paintObserved) cutoff = Math.Min(cutoff, paintTick);
        var ui = control.GetProperty("ui_threads").EnumerateArray().Select(t => t.GetInt32()).Distinct().ToHashSet();
        var threads = new List<object>();
        var summaryFaults = faults.Where(f => f.Tick <= cutoff && Owns(f.Thread, f.Tick) &&
            f.Bytes >= 0 && double.IsFinite(f.Duration) && f.Duration >= 0).ToList();
        foreach (int thread in lives.Keys.OrderBy(t => t))
        {
            var (waits, running) = Intervals(thread, cutoff);
            var threadFaults = summaryFaults.Where(f => f.Thread == thread).ToList();
            var phases = new Dictionary<string, object> { ["start_to_cutoff"] = Phase(waits, running, start, cutoff) };
            if (ui.Contains(thread))
            {
                var ordered = new[] { "splash-like_seen", "splash-like_visible", "main-like_visible", "valid_probe_file_observed" };
                foreach (var pair in ordered.Zip(ordered.Skip(1)))
                    if (marks.TryGetValue(pair.First, out long lo) && marks.TryGetValue(pair.Second, out long hi) &&
                        lo >= start && lo < cutoff && hi >= lo)
                        phases[pair.First + "_to_" + pair.Second] = Phase(waits, running, lo, Math.Min(hi, cutoff));
            }
            threads.Add(new
            {
                thread_id = thread, ui_thread = ui.Contains(thread),
                switches = points.Count(p => p.Thread == thread && p.Tick <= cutoff && Owns(thread, p.Tick) && p.Kind != "ready"),
                hard_fault_count = threadFaults.Count, hard_fault_bytes = threadFaults.Sum(f => (long)f.Bytes),
                hard_fault_sum_ms = Math.Round(threadFaults.Sum(f => f.Duration), 3),
                phases,
                longest_off_cpu = waits.OrderByDescending(w => w.End - w.Start).Take(ui.Contains(thread) ? 10 : 2)
                    .Select(w => new { start_ms = Relative(w.Start), end_ms = Relative(w.End), duration_ms = Duration(w.End - w.Start),
                        state = w.State, reason = w.Reason, ready_delay_ms = w.Ready.HasValue ? Duration(w.End - w.Ready.Value) : (double?)null,
                        censored = w.Censored, module_stacks = StackFor(thread, w.Start) }).ToArray(),
                longest_hard_faults = threadFaults.OrderByDescending(f => f.Duration).Take(ui.Contains(thread) ? 5 : 1)
                    .Select(f => new { completion_ms = Relative(f.Tick), duration_ms = Math.Round(f.Duration, 3),
                        bytes = f.Bytes, mapped_module = Module(f.Address, f.Tick), module_stacks = StackFor(thread, f.Tick) }).ToArray(),
            });
        }
        int unowned = points.Count(p => !Owns(p.Thread, p.Tick));
        bool streamComplete = cleanup && lost == 0 && !limited && points.Count > 0 && unowned == 0;
        bool uiSwitches = ui.Count > 0 && ui.All(t => lives.ContainsKey(t) &&
            points.Any(p => p.Thread == t && p.Kind == "out" && p.Tick <= cutoff && Owns(t, p.Tick)) &&
            points.Any(p => p.Thread == t && p.Kind == "in" && p.Tick <= cutoff && Owns(t, p.Tick)));
        bool splashBounds = marks.TryGetValue("splash-like_seen", out long splashStart) &&
            marks.TryGetValue("splash-like_visible", out long splashEnd) &&
            splashStart >= start && splashEnd >= splashStart && splashEnd <= cutoff;
        bool mainBound = marks.TryGetValue("main-like_visible", out long main) && main >= start && main <= cutoff;
        bool complete = streamComplete && uiSwitches && splashBounds && mainBound && paintObserved;
        return new()
        {
            ["status"] = complete ? "complete" : "partial",
            ["gui_pid"] = pid, ["target_lifetime_ms"] = Relative(end),
            ["identity_checks"] = identity,
            ["creation_clock_delta_ms"] = Math.Round(creation.GetDouble() - creationUtc, 3),
            ["qpc_frequency"] = Stopwatch.Frequency, ["process_start_qpc_ms"] = Program.Milliseconds(start),
            ["cutoff_ms"] = Relative(cutoff), ["cutoff_basis"] = paintObserved ? "observed_valid_probe_file_upper_bound" : "target_exit_or_last_observed_event",
            ["events_lost"] = lost, ["cleanup"] = cleanup, ["local_limit_hit"] = limited,
            ["coverage"] = new { stream_complete = streamComplete, observed_ui_switches = uiSwitches,
                splash_visibility_bounds = splashBounds, main_visibility_observed = mainBound, valid_probe_file_observed = paintObserved },
            ["target_events_seen"] = eventCount, ["unowned_thread_events_discarded"] = unowned,
            ["context_and_ready_events"] = points.Count, ["target_stack_keys"] = stacks.Count,
            ["hard_fault_count"] = summaryFaults.Count, ["hard_fault_bytes"] = summaryFaults.Sum(f => (long)f.Bytes),
            ["hard_fault_sum_ms"] = Math.Round(summaryFaults.Sum(f => f.Duration), 3),
            ["observed_ui_threads"] = ui.ToArray(), ["threads"] = threads,
            ["marker_ms"] = marks.ToDictionary(pair => pair.Key, pair => Relative(pair.Value)),
            ["hard_fault_events_discarded"] = faults.Count(f => f.Tick <= cutoff) - summaryFaults.Count,
            ["stack_frame_capture_limit"] = 64,
            // Compact target-only retained facts for independent interval and
            // hard-fault recomputation. Raw virtual/kernel addresses and
            // unowned thread events are deliberately excluded.
            ["raw_thread_lifetimes"] = lives.SelectMany(pair => pair.Value.Select(life =>
                new object?[] { pair.Key, Relative(life.Start), life.End.HasValue ? Relative(life.End.Value) : null })).ToArray(),
            ["raw_scheduler_points"] = points.Where(p => p.Tick <= cutoff && Owns(p.Thread, p.Tick))
                .OrderBy(p => p.Tick).Select(p => new object[] { p.Thread, Relative(p.Tick), p.Kind, p.State, p.Reason }).ToArray(),
            ["raw_hard_faults"] = summaryFaults.OrderBy(f => f.Tick)
                .Select(f => new object[] { f.Thread, Relative(f.Tick), f.Bytes, Math.Round(f.Duration, 3), Module(f.Address, f.Tick) }).ToArray(),
        };
    }

    internal static int SelfTest()
    {
        var t = new Timeline();
        long Ms(int value) => Program.FromMilliseconds(value);
        t.Start(42, Ms(1), 12345, 2);
        t.ThreadStart(42, 7, Ms(2));
        t.Image(Ms(3), 0x1000, 0x1000, "Qt6Gui.dll", false);
        t.Switch(7, Ms(5), "in");
        t.Switch(7, Ms(10), "out", "Waiting", "WrLpcReply");
        t.Stack(7, Ms(10), new ulong[] { 0x1010, 0xffff000000000010 });
        t.Switch(7, Ms(50), "ready");
        t.Switch(7, Ms(60), "in");
        t.Fault(7, Ms(70), 0x1020, 4096, 2);
        t.Switch(7, Ms(80), "out", "Waiting", "Executive");
        t.ThreadEnd(42, 7, Ms(90));
        t.End(42, Ms(95));
        using var control = JsonDocument.Parse("""{"gui_pid":42,"gui_creation_unix_ms":12345,"checker_lineage_depth":2,"markers":{},"ui_threads":[7]}""");
        string output = JsonSerializer.Serialize(t.Report(control.RootElement, 0, true));
        using var recorded = JsonDocument.Parse(output);
        var first = recorded.RootElement.GetProperty("threads")[0].GetProperty("longest_off_cpu")[0];
        string coveredJson = JsonSerializer.Serialize(new
        {
            gui_pid = 42, gui_creation_unix_ms = 12345, checker_lineage_depth = 2, ui_threads = new[] { 7 },
            markers = new Dictionary<string, object> {
                ["splash-like_seen"] = new { qpc_ms = 8 },
                ["splash-like_visible"] = new { qpc_ms = 60 },
                ["main-like_visible"] = new { qpc_ms = 75 },
                ["valid_probe_file_observed"] = new { qpc_ms = 85 },
            },
        });
        using var covered = JsonDocument.Parse(coveredJson);
        using var wrong = JsonDocument.Parse("""{"gui_pid":43,"markers":{},"ui_threads":[7]}""");
        var lineage = new Program.CheckerLineage { Root = 11 };
        if (lineage.Start(20, 100, Ms(1), "python.exe") >= 0 ||
            lineage.ParentDepth(20, Ms(2)) >= 0 ||
            lineage.Start(12, 11, Ms(2), @"C:\Python\python.exe") >= 0 ||
            lineage.Start(42, 12, Ms(3), "InvoiceHub.exe") != 2)
            return 1;
        lineage.End(12, Ms(4));
        if (lineage.Start(43, 12, Ms(5), "InvoiceHub.exe") >= 0)
            return 1;
        if (recorded.RootElement.GetProperty("status").GetString() != "partial" ||
            (string?)t.Report(covered.RootElement, 0, true)["status"] != "complete" ||
            (string?)t.Report(covered.RootElement, 3, true)["status"] != "partial" ||
            first.GetProperty("module_stacks")[0][0].GetString() != "Qt6Gui.dll+0x10" ||
            first.GetProperty("ready_delay_ms").GetDouble() != 10 || output.Contains("ffff000", StringComparison.OrdinalIgnoreCase) ||
            (string?)t.Report(wrong.RootElement, 0, true)["status"] != "unavailable" ||
            lineage.Start(44, 11, Ms(6), @"C:\synthetic\InvoiceHub.exe") != 1)
            return 1;
        Console.WriteLine("ETW timeline synthetic controls passed (no native ETW started).");
        return 0;
    }
}
