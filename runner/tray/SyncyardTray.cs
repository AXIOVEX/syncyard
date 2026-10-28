// SyncyardTray.cs - windowless supervisor for the Syncyard runners.
//
// Spec: AXIOVEX/syncyard spec 007 (windowless supervision).
// Claim: the desktop runners run with NO console window created and
// none left open in the owner's interactive session, while staying in
// that session so jobs keep access to the owner's WSL distro, audio
// devices, GPU, and bench hardware (a Windows service in session 0
// cannot reach those). This tray app is the supervisor: it starts
// each runner hidden, restarts it if it dies (capped, then it asks
// for the owner), and hides any stray runner console window.
//
// Compile (no SDK install needed - csc ships with Windows):
//   csc /target:winexe /out:SyncyardTray.exe /win32icon:logo.ico
//       /resource:logo.png,SyncyardLogo.png
//       /reference:System.Windows.Forms.dll
//       /reference:System.Drawing.dll SyncyardTray.cs
// The mark is embedded as the SyncyardLogo.png resource so the tray
// icon never depends on a file being in the right folder.
//
// C# 5 compatible on purpose (Framework 4.x csc).

using System;
using System.Collections.Generic;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;
using System.Windows.Forms;

namespace SyncyardTray
{
    internal sealed class RunnerDef
    {
        public string Lane;
        public string Dir;
        public Process StartedByUs;          // cmd.exe hosting run.cmd
        public List<DateTime> RestartTimes = new List<DateTime>();
        public bool Faulted;                  // restart cap hit
        public bool Running;                  // listener seen at last tick

        public string DisplayName
        {
            get { return "lane-" + Lane + "  (" + Dir + ")"; }
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            bool created;
            using (var mutex = new Mutex(true, "SyncyardTraySingleton", out created))
            {
                if (!created)
                {
                    MessageBox.Show("Syncyard Tray is already running.",
                        "Syncyard Tray", MessageBoxButtons.OK,
                        MessageBoxIcon.Information);
                    return;
                }
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                Application.Run(new TrayApp());
            }
        }
    }

    internal sealed class TrayApp : ApplicationContext
    {
        private const int SW_HIDE = 0;
        private const int SW_SHOW = 5;
        private const int MaxRestartsPerHour = 3;

        [DllImport("user32.dll")]
        private static extern bool ShowWindow(IntPtr hWnd, int nCmdShow);

        private readonly NotifyIcon _icon;
        private readonly System.Windows.Forms.Timer _timer;
        private readonly List<RunnerDef> _runners = new List<RunnerDef>();
        private readonly string _logPath;
        private readonly Image _logoImage;
        private Icon _currentIcon;
        private int _tick;

        public TrayApp()
        {
            string baseDir = Path.Combine(
                Environment.GetFolderPath(
                    Environment.SpecialFolder.LocalApplicationData),
                "SyncyardTray");
            Directory.CreateDirectory(baseDir);
            _logPath = Path.Combine(baseDir, "tray.log");

            // The project mark is embedded in this program as the
            // SyncyardLogo.png resource (spec 007 FR-007); a logo.png
            // next to the exe is only a fallback. The tray icon IS
            // the mark, with a slash overlay when runners are down.
            try
            {
                var asm = System.Reflection.Assembly
                    .GetExecutingAssembly();
                using (var stream = asm.GetManifestResourceStream(
                    "SyncyardLogo.png"))
                {
                    if (stream != null)
                        _logoImage = new Bitmap(Image.FromStream(stream));
                }
            }
            catch { _logoImage = null; }
            if (_logoImage == null)
            {
                try
                {
                    string logoPath = Path.Combine(
                        AppDomain.CurrentDomain.BaseDirectory, "logo.png");
                    if (File.Exists(logoPath))
                        _logoImage = Image.FromFile(logoPath);
                }
                catch { _logoImage = null; }
            }

            _runners.Add(new RunnerDef { Lane = "long",   Dir = @"C:\Users\trist\Development\Syncyard\runners\long" });
            _runners.Add(new RunnerDef { Lane = "quick",  Dir = @"C:\Users\trist\Development\Syncyard\runners\quick" });
            _runners.Add(new RunnerDef { Lane = "normal", Dir = @"C:\Users\trist\Development\Syncyard\runners\normal" });
            _runners.Add(new RunnerDef { Lane = "gpu",    Dir = @"C:\Users\trist\Development\Syncyard\runners\gpu" });

            _icon = new NotifyIcon();
            _icon.Text = "Syncyard runners";
            _icon.Visible = true;
            _icon.DoubleClick += delegate { RebuildMenu(); };

            Log("tray started");
            RefreshStates();
            StartMissing();
            HideStrayConsoles();
            RebuildMenu();

            _timer = new System.Windows.Forms.Timer();
            _timer.Interval = 5000;
            _timer.Tick += OnTick;
            _timer.Start();
        }

        // --- supervision ------------------------------------------------

        private void OnTick(object sender, EventArgs e)
        {
            _tick++;
            bool wasFaulted = AnyFaulted();
            RefreshStates();
            StartMissing();
            if (_tick % 6 == 0) HideStrayConsoles();   // every ~30 s
            if (!wasFaulted && AnyFaulted())
            {
                _icon.ShowBalloonTip(10000, "Syncyard runners",
                    "A runner kept dying and hit the restart cap. " +
                    "It will not be restarted again - open the tray menu.",
                    ToolTipIcon.Error);
            }
            RebuildMenu();
        }

        private bool AnyFaulted()
        {
            foreach (var r in _runners) if (r.Faulted) return true;
            return false;
        }

        private void RefreshStates()
        {
            var listeners = new List<Process>();
            try { listeners.AddRange(Process.GetProcessesByName("Runner.Listener")); }
            catch { /* process census is best-effort */ }

            foreach (var r in _runners)
            {
                r.Running = false;
                foreach (var p in listeners)
                {
                    string path = SafePath(p);
                    if (path != null && path.StartsWith(r.Dir,
                        StringComparison.OrdinalIgnoreCase))
                    {
                        r.Running = true;
                        break;
                    }
                }
            }
        }

        private static string SafePath(Process p)
        {
            try { return p.MainModule.FileName; }
            catch { return null; }
        }

        private void StartMissing()
        {
            foreach (var r in _runners)
            {
                if (r.Running || r.Faulted) continue;
                if (!Directory.Exists(r.Dir)) continue;
                if (!File.Exists(Path.Combine(r.Dir, "run.cmd"))) continue;

                var now = DateTime.UtcNow;
                r.RestartTimes.RemoveAll(t => (now - t).TotalHours > 1.0);
                if (r.RestartTimes.Count >= MaxRestartsPerHour)
                {
                    r.Faulted = true;
                    Log("OWNER NEEDED: " + r.Lane + " hit the restart cap");
                    continue;
                }
                StartRunner(r);
            }
        }

        private void StartRunner(RunnerDef r)
        {
            try
            {
                var psi = new ProcessStartInfo();
                psi.FileName = Path.Combine(
                    Environment.GetFolderPath(
                        Environment.SpecialFolder.System), "cmd.exe");
                psi.Arguments = "/c run.cmd";
                psi.WorkingDirectory = r.Dir;
                psi.UseShellExecute = false;
                psi.CreateNoWindow = true;
                psi.WindowStyle = ProcessWindowStyle.Hidden;
                r.StartedByUs = Process.Start(psi);
                r.RestartTimes.Add(DateTime.UtcNow);
                Log("started " + r.Lane + " hidden (dir " + r.Dir + ")");
            }
            catch (Exception ex)
            {
                Log("start failed for " + r.Lane + ": " + ex.Message);
            }
        }

        private void StopRunner(RunnerDef r)
        {
            // Kill the listener for this dir, and the run.cmd host if we
            // started it. A listener killed mid-job kills that job - the
            // menu asks for confirmation first.
            try
            {
                foreach (var p in Process.GetProcessesByName("Runner.Listener"))
                {
                    string path = SafePath(p);
                    if (path != null && path.StartsWith(r.Dir,
                        StringComparison.OrdinalIgnoreCase))
                    {
                        p.Kill();
                        Log("stopped listener for " + r.Lane);
                    }
                }
            }
            catch (Exception ex) { Log("stop failed " + r.Lane + ": " + ex.Message); }
            try
            {
                if (r.StartedByUs != null && !r.StartedByUs.HasExited)
                    r.StartedByUs.Kill();
            }
            catch { }
            r.Running = false;
        }

        private void StartAll()
        {
            foreach (var r in _runners)
            {
                r.Faulted = false;
                r.RestartTimes.Clear();
            }
            RefreshStates();
            StartMissing();
            RefreshStates();
            RebuildMenu();
        }

        private void StopAll()
        {
            var ok = MessageBox.Show(
                "Stop ALL runners? Any jobs running on them will be killed.",
                "Syncyard Tray", MessageBoxButtons.OKCancel,
                MessageBoxIcon.Warning);
            if (ok != DialogResult.OK) return;
            foreach (var r in _runners)
                if (r.Running) StopRunner(r);
            RefreshStates();
            RebuildMenu();
        }

        // --- stray console hiding ----------------------------------------

        private void SetStrayConsoles(int cmd)
        {
            foreach (var name in new[] { "conhost", "cmd", "powershell", "pwsh" })
            {
                Process[] procs;
                try { procs = Process.GetProcessesByName(name); }
                catch { continue; }
                foreach (var p in procs)
                {
                    try
                    {
                        if (p.MainWindowHandle == IntPtr.Zero) continue;
                        string title = p.MainWindowTitle ?? "";
                        if (title.IndexOf("actions-runner",
                                StringComparison.OrdinalIgnoreCase) >= 0 ||
                            title.IndexOf("run.cmd",
                                StringComparison.OrdinalIgnoreCase) >= 0)
                        {
                            ShowWindow(p.MainWindowHandle, cmd);
                            if (cmd == SW_HIDE)
                                Log("hid stray console '" + title + "'");
                        }
                    }
                    catch { }
                }
            }
        }

        private void HideStrayConsoles() { SetStrayConsoles(SW_HIDE); }

        // --- tray UI ------------------------------------------------------

        private void RebuildMenu()
        {
            var menu = new ContextMenuStrip();
            int running = 0;
            foreach (var r in _runners) if (r.Running) running++;
            var startAll = new ToolStripMenuItem("Start all runners");
            startAll.Enabled = running < _runners.Count;
            startAll.Click += delegate { StartAll(); };
            menu.Items.Add(startAll);
            var stopAll = new ToolStripMenuItem("Stop all runners");
            stopAll.Enabled = running > 0;
            stopAll.Click += delegate { StopAll(); };
            menu.Items.Add(stopAll);
            menu.Items.Add(new ToolStripSeparator());
            running = 0;
            foreach (var r in _runners)
            {
                if (r.Running) running++;
                string state = r.Faulted ? "FAULTED - owner needed"
                             : r.Running ? "running" : "stopped";
                var item = new ToolStripMenuItem(
                    "lane-" + r.Lane + ": " + state);
                var start = new ToolStripMenuItem("Start hidden");
                var captured = r;
                start.Click += delegate
                {
                    captured.Faulted = false;
                    captured.RestartTimes.Clear();
                    StartRunner(captured);
                    RefreshStates(); RebuildMenu();
                };
                var stop = new ToolStripMenuItem("Stop runner");
                stop.Click += delegate
                {
                    var ok = MessageBox.Show(
                        "Stop the lane-" + captured.Lane + " runner? " +
                        "A job running on it will be killed.",
                        "Syncyard Tray", MessageBoxButtons.OKCancel,
                        MessageBoxIcon.Warning);
                    if (ok == DialogResult.OK)
                    {
                        StopRunner(captured);
                        RefreshStates(); RebuildMenu();
                    }
                };
                item.DropDownItems.Add(start);
                item.DropDownItems.Add(stop);
                menu.Items.Add(item);
            }
            menu.Items.Add(new ToolStripSeparator());
            var hide = new ToolStripMenuItem("Hide runner consoles now");
            hide.Click += delegate { HideStrayConsoles(); };
            menu.Items.Add(hide);
            var show = new ToolStripMenuItem("Show runner consoles");
            show.Click += delegate { SetStrayConsoles(SW_SHOW); };
            menu.Items.Add(show);
            menu.Items.Add(new ToolStripSeparator());
            var log = new ToolStripMenuItem("Open tray log");
            log.Click += delegate
            {
                try { Process.Start("notepad.exe", _logPath); }
                catch { }
            };
            menu.Items.Add(log);
            var exit = new ToolStripMenuItem(
                "Exit tray (runners keep running)");
            exit.Click += delegate
            {
                Log("tray exited by owner; runners left as-is");
                _icon.Visible = false;
                Application.Exit();
            };
            menu.Items.Add(exit);
            _icon.ContextMenuStrip = menu;

            int iconState = AnyFaulted() || running == 0 ? 2
                          : running == _runners.Count ? 0 : 1;
            SetIcon(iconState);
            _icon.Text = "Syncyard: " + running + "/" + _runners.Count +
                         " runners up";
        }

        // Icon states (FR-007): 0 = all runners up, clean mark;
        // 1 = some down, amber slash; 2 = none up or faulted, red
        // slash. The slash is drawn with a white halo so it reads on
        // light and dark taskbars. The dot exists only if the mark
        // itself failed to load, which the embedded resource makes a
        // should-never-happen path.
        private void SetIcon(int state)
        {
            var bmp = new Bitmap(32, 32);
            using (var g = Graphics.FromImage(bmp))
            {
                g.SmoothingMode =
                    System.Drawing.Drawing2D.SmoothingMode.AntiAlias;
                g.InterpolationMode =
                    System.Drawing.Drawing2D.InterpolationMode.HighQualityBicubic;
                g.Clear(Color.Transparent);
                if (_logoImage != null)
                {
                    g.DrawImage(_logoImage, 0, 0, 32, 32);
                    if (state > 0)
                    {
                        Color slash = state == 2
                            ? Color.FromArgb(225, 45, 45)
                            : Color.FromArgb(235, 165, 25);
                        using (var halo = new Pen(Color.White, 9))
                            g.DrawLine(halo, 6, 26, 26, 6);
                        using (var pen = new Pen(slash, 5))
                            g.DrawLine(pen, 6, 26, 26, 6);
                    }
                }
                else
                {
                    Color dot = state == 2 ? Color.Red
                              : state == 1 ? Color.Goldenrod
                              : Color.Green;
                    using (var b = new SolidBrush(dot))
                        g.FillEllipse(b, 1, 1, 30, 30);
                }
            }
            var old = _currentIcon;
            _currentIcon = Icon.FromHandle(bmp.GetHicon());
            _icon.Icon = _currentIcon;
            if (old != null) old.Dispose();
        }

        private void Log(string msg)
        {
            try
            {
                File.AppendAllText(_logPath,
                    DateTime.Now.ToString("yyyy-MM-dd HH:mm:ss") +
                    "  " + msg + Environment.NewLine);
            }
            catch { }
        }
    }
}
