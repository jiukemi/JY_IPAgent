/**
 * Agent desktop shell: spawn FastAPI (server.py), open BrowserWindow.
 * Engines are NOT bundled — download later via 本机环境 / components.
 *
 * Packaged runtime (Python/FFmpeg) lives under userData — NOT under Program Files —
 * so first-run download works without admin write permission.
 */
import { app, BrowserWindow, shell, dialog, Menu, ipcMain, clipboard, protocol, net } from 'electron'
import { execSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import http from 'node:http'
import { downloadAndLaunchInstaller, openReleasePage } from './updater.mjs'

const __dirname = path.dirname(fileURLToPath(import.meta.url))

// Must run before app.ready — local disk media without HTTP buffer
protocol.registerSchemesAsPrivileged([
  {
    scheme: 'agent-media',
    privileges: {
      standard: true,
      secure: true,
      supportFetchAPI: true,
      stream: true,
      bypassCSP: true,
      corsEnabled: true,
    },
  },
])

function resolveRoot() {
  // Packaged: extraResources → resources/agent
  if (app.isPackaged) {
    return path.join(process.resourcesPath, 'agent')
  }
  return path.resolve(__dirname, '..')
}

const ROOT = resolveRoot()

const DEFAULT_W = 1280
const DEFAULT_H = 800
const MIN_W = 1100
const MIN_H = 700

/** @type {import('node:child_process').ChildProcessWithoutNullStreams | null} */
let pyProc = null
let mainWindow = null
/** @type {BrowserWindow | null} */
let splashWindow = null

function edition() {
  if (process.argv.includes('--light')) return 'light'
  if (process.argv.includes('--full')) return 'full'
  const e = (process.env.AGENT_EDITION || 'full').toLowerCase()
  return e === 'light' ? 'light' : 'full'
}

/** Writable dir for portable Python + FFmpeg */
function runtimeDir() {
  if (app.isPackaged) {
    return path.join(app.getPath('userData'), 'runtime')
  }
  return path.join(ROOT, 'data', 'runtime')
}

function portablePythonExe() {
  // Prefer venv (from system Python) then embeddable portable
  const venv = path.join(runtimeDir(), 'venv', 'Scripts', 'python.exe')
  if (fs.existsSync(venv)) return venv
  return path.join(runtimeDir(), 'python', 'python.exe')
}

function portableFfmpegExe() {
  return path.join(runtimeDir(), 'ffmpeg', 'ffmpeg.exe')
}

function readPythonMeta() {
  const metaPath = path.join(runtimeDir(), 'python.json')
  try {
    if (!fs.existsSync(metaPath)) return null
    const j = JSON.parse(fs.readFileSync(metaPath, 'utf8'))
    if (j?.cmd && fs.existsSync(j.cmd)) {
      return { cmd: j.cmd, args: Array.isArray(j.args) ? j.args : [], portable: true }
    }
  } catch {
    /* ignore */
  }
  return null
}

function findSystemPythonSync() {
  // Quick existence check only; version validated by bootstrap script
  if (process.platform !== 'win32') {
    return { cmd: 'python3', args: [], portable: false }
  }
  return { cmd: 'py', args: ['-3.11'], portable: false }
}

function findPython() {
  const meta = readPythonMeta()
  if (meta) return meta
  const portable = portablePythonExe()
  if (fs.existsSync(portable)) {
    return { cmd: portable, args: [], portable: true }
  }
  if (app.isPackaged) {
    return { cmd: '', args: [], portable: false }
  }
  return findSystemPythonSync()
}

function splashSend(payload) {
  if (!splashWindow || splashWindow.isDestroyed()) return
  try {
    splashWindow.webContents.send('boot:update', payload)
  } catch {
    /* ignore */
  }
}

function createSplash() {
  const iconPath = path.join(__dirname, 'build', 'icon.png')
  splashWindow = new BrowserWindow({
    width: 520,
    height: 640,
    resizable: false,
    maximizable: false,
    minimizable: false,
    fullscreenable: false,
    frame: false,
    transparent: false,
    show: false,
    center: true,
    alwaysOnTop: true,
    title: '九易AI智能体',
    ...(fs.existsSync(iconPath) ? { icon: iconPath } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'splash-preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })
  splashWindow.once('ready-to-show', () => {
    splashWindow?.show()
  })
  void splashWindow.loadFile(path.join(__dirname, 'splash.html'))
  splashWindow.webContents.once('did-finish-load', () => {
    splashSend({
      runtime: inspectRuntime(),
      subtitle: '正在准备运行环境…',
      pct: 1,
      label: '检测运行时',
      free: freeNoticeText(),
      foot: '本应用完全免费 · 请勿上当受骗 · 抖音搜索「九易」获取最新版',
    })
  })
}

function closeSplash() {
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashWindow.close()
  }
  splashWindow = null
}

function dirSizeBytes(root) {
  let total = 0
  const stack = [root]
  let n = 0
  while (stack.length && n < 20000) {
    const cur = stack.pop()
    n += 1
    let entries
    try {
      entries = fs.readdirSync(cur, { withFileTypes: true })
    } catch {
      continue
    }
    for (const ent of entries) {
      const p = path.join(cur, ent.name)
      try {
        if (ent.isDirectory()) stack.push(p)
        else total += fs.statSync(p).size
      } catch {
        /* ignore locked/missing */
      }
    }
  }
  return total
}

/** @type {{ sizeBytes: number, at: number, path: string } | null} */
let runtimeSizeCache = null

function inspectRuntime(opts = {}) {
  const withSize = opts.withSize === true
  const dir = runtimeDir()
  const exists = fs.existsSync(dir)
  const info = {
    path: dir,
    exists,
    sizeBytes: 0,
    hasVenv: false,
    hasEmbed: false,
    hasLog: false,
    hasConfig: false,
    hasPythonMeta: false,
  }
  if (!exists) return info
  info.hasVenv = fs.existsSync(path.join(dir, 'venv'))
  info.hasEmbed = fs.existsSync(path.join(dir, 'python', 'python.exe'))
  info.hasLog = fs.existsSync(path.join(dir, 'bootstrap.log'))
  info.hasConfig = fs.existsSync(path.join(dir, 'config.yaml'))
  info.hasPythonMeta = fs.existsSync(path.join(dir, 'python.json'))
  // Dir walk is expensive on first boot — skip unless UI explicitly asks (refresh).
  if (withSize) {
    const now = Date.now()
    if (
      runtimeSizeCache &&
      runtimeSizeCache.path === dir &&
      now - runtimeSizeCache.at < 60_000
    ) {
      info.sizeBytes = runtimeSizeCache.sizeBytes
    } else {
      try {
        info.sizeBytes = dirSizeBytes(dir)
        runtimeSizeCache = { sizeBytes: info.sizeBytes, at: now, path: dir }
      } catch {
        info.sizeBytes = 0
      }
    }
  }
  return info
}

function mediaAllowRoots() {
  return [path.join(ROOT, 'output'), path.join(ROOT, 'data'), runtimeDir()].map((p) => path.resolve(p))
}

function isAllowedMediaPath(filePath) {
  const resolved = path.resolve(filePath)
  return mediaAllowRoots().some((root) => resolved === root || resolved.startsWith(root + path.sep))
}

/** Serve session / avatar / asset files straight from disk (Range-capable via net.fetch). */
function registerMediaProtocol() {
  protocol.handle('agent-media', (request) => {
    try {
      const u = new URL(request.url)
      const raw = u.searchParams.get('p') || ''
      if (!raw) return new Response('missing path', { status: 400 })
      const filePath = path.resolve(decodeURIComponent(raw))
      if (!isAllowedMediaPath(filePath)) {
        return new Response('forbidden', { status: 403 })
      }
      if (!fs.existsSync(filePath) || !fs.statSync(filePath).isFile()) {
        return new Response('not found', { status: 404 })
      }
      return net.fetch(pathToFileURL(filePath).href)
    } catch (err) {
      return new Response(err instanceof Error ? err.message : String(err), { status: 500 })
    }
  })
}

function killBackend() {
  if (pyProc && !pyProc.killed) {
    const pid = pyProc.pid
    try {
      if (process.platform === 'win32' && pid) {
        spawn('taskkill', ['/PID', String(pid), '/T', '/F'], { windowsHide: true, stdio: 'ignore' })
      } else {
        pyProc.kill()
      }
    } catch {
      /* ignore */
    }
  }
  pyProc = null
}

/** Kill leftover server.py still listening on the app port range (stale routes → blank thumbs). */
function killOrphanAgentServers() {
  if (process.platform !== 'win32') return
  const script = [
    'foreach ($port in 7860..7890) {',
    '  Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue | ForEach-Object {',
    '    $procId = $_.OwningProcess',
    '    $p = Get-CimInstance Win32_Process -Filter "ProcessId=$procId" -ErrorAction SilentlyContinue',
    "    if ($p -and $p.CommandLine -match 'server\\.py') { Stop-Process -Id $procId -Force -ErrorAction SilentlyContinue }",
    '  }',
    '}',
  ].join(' ')
  try {
    execSync(`powershell -NoProfile -ExecutionPolicy Bypass -Command ${JSON.stringify(script)}`, {
      stdio: 'ignore',
      windowsHide: true,
      timeout: 20000,
    })
  } catch {
    /* ignore */
  }
}

/** Clear runtime folder. Rename-first to dodge Windows file locks, then delete. */
function clearRuntimeDir() {
  killBackend()
  const dir = runtimeDir()
  if (!fs.existsSync(dir)) {
    return { ok: true, path: dir, cleared: false, message: '运行时目录不存在，无需清理' }
  }
  const trash = `${dir}.trash-${Date.now()}`
  try {
    fs.renameSync(dir, trash)
  } catch (e) {
    try {
      fs.rmSync(dir, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 })
      return { ok: true, path: dir, cleared: true, message: '已删除运行时目录' }
    } catch (e2) {
      return {
        ok: false,
        path: dir,
        cleared: false,
        message: `无法删除运行时（文件被占用）：${e2 instanceof Error ? e2.message : e2}\n请先完全退出软件后再试。`,
      }
    }
  }
  try {
    fs.rmSync(trash, { recursive: true, force: true, maxRetries: 8, retryDelay: 250 })
  } catch {
    // Renamed away is enough for a clean relaunch
  }
  return { ok: true, path: dir, cleared: true, message: '已清除运行时，即将重新准备环境' }
}

function relaunchApp() {
  app.relaunch()
  app.exit(0)
}

function registerSplashIpc() {
  ipcMain.handle('boot:copy', (_e, text) => {
    try {
      clipboard.writeText(String(text || ''))
      return true
    } catch {
      return false
    }
  })
  ipcMain.handle('boot:open-log', async () => {
    const dir = runtimeDir()
    try {
      fs.mkdirSync(dir, { recursive: true })
    } catch {
      /* ignore */
    }
    await shell.openPath(dir)
    return true
  })
  ipcMain.handle('boot:quit', () => {
    app.quit()
    return true
  })
  ipcMain.handle('boot:continue', () => {
    if (typeof continueBootResolve === 'function') {
      const fn = continueBootResolve
      continueBootResolve = null
      fn()
    }
    return true
  })
  ipcMain.handle('boot:open-downloads', async () => {
    const home = app.getPath('home')
    const candidates = [
      path.join(home, 'Downloads'),
      path.join(home, '下载'),
      app.getPath('downloads'),
    ]
    for (const d of candidates) {
      if (fs.existsSync(d)) {
        await shell.openPath(d)
        return { ok: true, path: d }
      }
    }
    await shell.openPath(home)
    return { ok: true, path: home }
  })
  ipcMain.handle('boot:open-quark-share', async () => {
    // Placeholder until you paste a real Quark share URL into env / config file
    const cfgPath = path.join(runtimeDir(), 'quark_share.url')
    let url = (process.env.AGENT_QUARK_SHARE_URL || '').trim()
    if (!url && fs.existsSync(cfgPath)) {
      try {
        url = fs.readFileSync(cfgPath, 'utf8').trim().split(/\r?\n/)[0] || ''
      } catch {
        /* ignore */
      }
    }
    if (!url) {
      return {
        ok: false,
        message:
          '尚未配置夸克分享链接。请把链接写入运行时文件 quark_share.url，或设置环境变量 AGENT_QUARK_SHARE_URL。',
      }
    }
    await shell.openExternal(url)
    return { ok: true, url }
  })
  ipcMain.handle('boot:quark-install', async () => {
    const script = path.join(ROOT, 'scripts', 'quark_accel_install.ps1')
    if (!fs.existsSync(script)) {
      return { ok: false, message: `缺少脚本：${script}` }
    }
    return await new Promise((resolve) => {
      const ps = spawn(
        'powershell',
        [
          '-NoProfile',
          '-ExecutionPolicy',
          'Bypass',
          '-File',
          script,
          '-RuntimeRoot',
          runtimeDir(),
        ],
        { cwd: ROOT, windowsHide: true, env: { ...process.env, AGENT_RUNTIME_DIR: runtimeDir() } },
      )
      let out = ''
      const onChunk = (c) => {
        const t = c.toString()
        out += t
        for (const line of t.split(/\r?\n/)) {
          if (line.trim()) splashSend({ line: line.trim() })
          const m = line.match(/^PROGRESS:(\d+):(.*)$/)
          if (m) splashSend({ pct: Number(m[1]), label: m[2].trim() })
        }
      }
      ps.stdout.on('data', onChunk)
      ps.stderr.on('data', onChunk)
      ps.on('error', (e) => resolve({ ok: false, message: String(e), log: out }))
      ps.on('exit', (code) => {
        const ok = code === 0 && /QUARK_OK/.test(out)
        resolve({
          ok,
          message: ok ? '夸克加速包已安装，可继续准备环境' : out.trim().slice(-800) || `exit=${code}`,
          log: out,
        })
      })
    })
  })
  ipcMain.handle('boot:runtime-info', () => inspectRuntime({ withSize: true }))
  ipcMain.handle('boot:clear-runtime', () => clearRuntimeDir())
  ipcMain.handle('boot:clear-and-retry', () => {
    const result = clearRuntimeDir()
    if (!result.ok) return result
    setTimeout(() => relaunchApp(), 400)
    return { ...result, relaunching: true }
  })
  // Main window (settings) uses the same handlers under desktop:* aliases
  ipcMain.handle('desktop:runtime-info', (_e, opts) =>
    inspectRuntime({ withSize: opts?.withSize !== false }),
  )
  ipcMain.handle('desktop:clear-and-relaunch', () => {
    const result = clearRuntimeDir()
    if (!result.ok) return result
    setTimeout(() => relaunchApp(), 400)
    return { ...result, relaunching: true }
  })
  ipcMain.handle('desktop:app-version', () => {
    try {
      return { version: app.getVersion() }
    } catch {
      return { version: '0.0.0' }
    }
  })
  ipcMain.handle('desktop:download-update', async (event, release) => {
    const sender = event.sender
    const sendProg = (pct) => {
      try {
        if (!sender.isDestroyed()) sender.send('desktop:update-progress', { pct })
      } catch {
        /* ignore */
      }
    }
    try {
      const result = await downloadAndLaunchInstaller(release || {}, sendProg)
      return { ok: true, ...result }
    } catch (e) {
      return { ok: false, message: e instanceof Error ? e.message : String(e) }
    }
  })
  ipcMain.handle('desktop:open-release-page', (_e, url) => {
    openReleasePage(url)
    return { ok: true }
  })
  ipcMain.handle('desktop:open-path', async (_e, rawPath) => {
    const input = typeof rawPath === 'string' ? rawPath.trim() : ''
    if (!input) return { ok: false, message: '路径为空' }
    const resolved = path.resolve(input)
    const allowed = [
      path.join(ROOT, 'data'),
      path.join(runtimeDir(), 'data'),
    ].map((p) => path.resolve(p))
    const okRoot = allowed.some(
      (root) => resolved === root || resolved.startsWith(root + path.sep),
    )
    if (!okRoot) return { ok: false, message: '只能打开本机数据目录内的文件' }
    if (!fs.existsSync(resolved)) return { ok: false, message: '文件不存在' }
    const err = await shell.openPath(resolved)
    if (err) return { ok: false, message: err }
    return { ok: true }
  })
}

function showBootError(msg) {
  const tip = app.isPackaged
    ? `${msg}\n\n请确认：\n1. 已联网\n2. 杀毒软件未拦截下载\n3. 磁盘空间充足\n\n可点下方「清除运行时并重试」一键清理后重装环境。\n\n运行时：\n${runtimeDir()}\n\n日志：\n${path.join(runtimeDir(), 'bootstrap.log')}`
    : `${msg}\n\n开发模式请本机安装 Python 3.11（py -3.11），或先运行 scripts/bootstrap_runtime.ps1。`
  if (splashWindow && !splashWindow.isDestroyed()) {
    splashSend({
      error: tip,
      subtitle: '启动失败',
      label: '失败',
      runtime: inspectRuntime(),
    })
    return
  }
  dialog.showErrorBox('无法启动', tip)
}

/** First-run / repair: ensure Python deps + FFmpeg (skips what already exists). */
function ensureRuntimeBootstrap() {
  return new Promise((resolve, reject) => {
    const script = path.join(ROOT, 'scripts', 'bootstrap_runtime.ps1')
    if (!fs.existsSync(script)) {
      reject(new Error(`缺少启动脚本：${script}`))
      return
    }
    try {
      fs.mkdirSync(runtimeDir(), { recursive: true })
    } catch (e) {
      reject(new Error(`无法创建运行时目录（请检查磁盘权限）：${runtimeDir()}\n${e}`))
      return
    }

    const logPath = path.join(runtimeDir(), 'bootstrap.log')
    splashSend({
      subtitle: '正在准备运行环境…',
      pct: 2,
      label: '启动引导脚本',
      line: `runtime → ${runtimeDir()}`,
      free: freeNoticeText(),
      foot: '本应用完全免费 · 请勿上当受骗 · 抖音搜索「九易」获取最新版',
    })

    const seen = new Set()
    const handleLine = (line) => {
      const t = String(line || '').trimEnd()
      if (!t) return
      // Dedupe stdout + file-tail of the same line
      if (seen.has(t)) return
      if (seen.size > 4000) seen.clear()
      seen.add(t)
      const m = t.match(/^PROGRESS:(\d+):(.*)$/)
      if (m) {
        splashSend({
          pct: Number(m[1]),
          label: m[2].trim() || '处理中',
          line: t,
        })
      } else {
        splashSend({ line: t })
      }
    }

    // Fallback when PowerShell stdout is empty/buffered: script dual-writes bootstrap.log
    let logPos = 0
    let logBuf = ''
    const pumpLogFile = () => {
      try {
        if (!fs.existsSync(logPath)) return
        const st = fs.statSync(logPath)
        if (st.size <= logPos) return
        const fd = fs.openSync(logPath, 'r')
        try {
          const len = st.size - logPos
          const buf = Buffer.alloc(len)
          fs.readSync(fd, buf, 0, len, logPos)
          logPos = st.size
          logBuf += buf.toString('utf8')
          const parts = logBuf.split(/\r?\n/)
          logBuf = parts.pop() || ''
          for (const raw of parts) handleLine(raw)
        } finally {
          fs.closeSync(fd)
        }
      } catch {
        /* ignore */
      }
    }
    const logTimer = setInterval(pumpLogFile, 400)

    const ps = spawn(
      'powershell',
      [
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        script,
        '-Root',
        ROOT,
        '-RuntimeRoot',
        runtimeDir(),
      ],
      {
        cwd: ROOT,
        windowsHide: true,
        env: {
          ...process.env,
          AGENT_RUNTIME_DIR: runtimeDir(),
          PYTHONUNBUFFERED: '1',
        },
      },
    )
    let out = ''
    let lineBuf = ''

    const onChunk = (c) => {
      const text = c.toString()
      out += text
      lineBuf += text
      const parts = lineBuf.split(/\r?\n/)
      lineBuf = parts.pop() || ''
      for (const raw of parts) handleLine(raw)
    }

    const finish = (code) => {
      clearInterval(logTimer)
      pumpLogFile()
      if (logBuf.trim()) handleLine(logBuf.trim())
      if (lineBuf.trim()) {
        handleLine(lineBuf.trim())
        out += lineBuf
      }
      // Prefer full dual-written log for diagnostics
      let fileTail = ''
      try {
        if (fs.existsSync(logPath)) {
          fileTail = fs.readFileSync(logPath, 'utf8')
        }
      } catch {
        /* ignore */
      }
      const combined = (fileTail || out || '').trim()
      if (!fileTail && out) {
        try {
          fs.writeFileSync(logPath, out, 'utf8')
        } catch {
          /* ignore */
        }
      }
      const py = findPython()
      if (code === 0 && py.cmd) {
        splashSend({ pct: 100, label: '运行环境就绪', line: '==> bootstrap ok' })
        resolve(true)
        return
      }
      const tail = combined.slice(-1500)
      reject(
        new Error(
          `首次准备运行环境失败（exit=${code}）。\n` +
            `运行时目录：${runtimeDir()}\n` +
            `日志：${logPath}\n\n` +
            (tail || '无输出，请检查网络或杀毒软件是否拦截。'),
        ),
      )
    }

    ps.stdout.on('data', onChunk)
    ps.stderr.on('data', onChunk)
    ps.on('error', (err) => {
      clearInterval(logTimer)
      reject(err)
    })
    ps.on('exit', (code) => finish(code))
  })
}

function waitForHealth(port, timeoutMs = 60000) {
  const started = Date.now()
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
        res.resume()
        if (res.statusCode === 200) {
          resolve(true)
          return
        }
        retry()
      })
      req.on('error', retry)
      req.setTimeout(2000, () => {
        req.destroy()
        retry()
      })
    }
    const retry = () => {
      if (Date.now() - started > timeoutMs) {
        reject(new Error('后端启动超时'))
        return
      }
      setTimeout(tick, 400)
    }
    tick()
  })
}

function startBackend() {
  return new Promise((resolve, reject) => {
    if (!fs.existsSync(path.join(ROOT, 'server.py'))) {
      reject(
        new Error(
          `找不到 server.py（ROOT=${ROOT}）。请重新安装本软件。`,
        ),
      )
      return
    }
    const found = findPython()
    if (!found.cmd) {
      reject(
        new Error(
          `未找到便携 Python：\n${portablePythonExe()}\n\n请保持联网后重新打开软件，首次启动会自动下载。`,
        ),
      )
      return
    }
    const rt = runtimeDir()
    const ffmpegBin = path.join(rt, 'ffmpeg')
    const pathEnv = [ffmpegBin, process.env.PATH || ''].filter(Boolean).join(path.delimiter)
    // Packaged: writable runtime config. Dev: prefer project config.yaml so CDN/ASR/浏览器设置一致。
    const projectCfg = path.join(ROOT, 'config.yaml')
    const runtimeCfg = path.join(rt, 'config.yaml')
    const configPath =
      !app.isPackaged && fs.existsSync(projectCfg) ? projectCfg : runtimeCfg
    const env = {
      ...process.env,
      PATH: pathEnv,
      PYTHONPATH: [ROOT, process.env.PYTHONPATH || ''].filter(Boolean).join(path.delimiter),
      AGENT_EDITION: edition(),
      AGENT_RUNTIME_DIR: rt,
      AGENT_CONFIG: configPath,
      PYTHONUTF8: '1',
      NO_PROXY: '127.0.0.1,localhost,::1',
    }
    if (app.isPackaged || process.argv.includes('--strict-user')) {
      env.AGENT_STRICT_USER = '1'
    }
    const serverPy = path.join(ROOT, 'server.py')
    if (!fs.existsSync(serverPy)) {
      reject(new Error(`找不到 server.py：${serverPy}`))
      return
    }
    const apiDir = path.join(ROOT, 'api')
    if (!fs.existsSync(apiDir)) {
      reject(new Error(`安装不完整：缺少 api 目录\n${apiDir}`))
      return
    }
    splashSend({
      subtitle: '正在启动后端服务…',
      pct: 92,
      label: '启动 Python 后端',
      mode: 'indeterminate',
      line: `python → ${found.cmd}`,
    })
    splashSend({ pct: 90, label: '清理旧后端进程…', line: '释放 7860–7890 端口' })
    killOrphanAgentServers()
    killBackend()

    const childArgs = [...found.args, serverPy]
    pyProc = spawn(found.cmd, childArgs, {
      cwd: ROOT,
      env,
      windowsHide: true,
    })

    let buf = ''
    let resolved = false
    const tryPort = (chunk) => {
      const text = chunk.toString()
      buf += text
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) splashSend({ line: line.trim() })
      }
      const m = buf.match(/http:\/\/127\.0\.0\.1:(\d+)/)
      if (m && !resolved) {
        resolved = true
        const port = Number(m[1])
        splashSend({ pct: 96, label: `等待健康检查 :${port}` })
        waitForHealth(port)
          .then(() => resolve(port))
          .catch(reject)
      }
    }

    pyProc.stdout.on('data', tryPort)
    pyProc.stderr.on('data', tryPort)
    pyProc.on('error', (err) => {
      if (!resolved) {
        reject(
          new Error(
            `无法启动 Python（${found.cmd}）：${err.message}\n` +
              (app.isPackaged
                ? `请删除后重开以重新下载：\n${rt}`
                : '开发模式请安装本机 Python 3.11（py -3.11）。'),
          ),
        )
      }
    })
    pyProc.on('exit', (code) => {
      if (!resolved) {
        const tail = buf.trim().slice(-800)
        reject(
          new Error(
            `后端提前退出 code=${code}\n${tail || '无日志输出'}`,
          ),
        )
      }
    })

    // Never attach to a pre-existing :7860 — that may be a stale backend missing thumb routes.
  })
}

/** @type {(() => void) | null} */
let continueBootResolve = null

const WELCOME_MARKER = 'boot-welcome-v1.flag'
const FREE_NOTICE_MARKER = 'free-private-notice-v1.flag'

function welcomeGuideText() {
  return (
    '【引擎安装引导】安装包不含大模型，请按需下载：\n\n' +
    '1. 打开设置 →「本机环境 · GPU 与模型」\n' +
    '2. 配音：安装 IndexTTS2（需 NVIDIA 显卡）或轻量 Piper\n' +
    '3. 文案提取：需要时安装 FunASR 或 Whisper\n' +
    '4. 口播：先安装并打开 Docker Desktop，再在口播页点「一键启动」\n' +
    '   （首次拉镜像约十几 GB，只下一次；按显卡自动选通用/50 系）\n\n' +
    '【可选·夸克加速】默认在线引导即可；仅当下载很慢/失败时，用夸克分享下加速包到「下载」文件夹，启动窗点「夸克加速：扫描下载」。未装夸克客户端也可用浏览器下载。\n\n' +
    '安装进度与日志可在顶部「任务中心」查看。\n' +
    '点「进入软件」开始使用。'
  )
}

function freeNoticeText() {
  return (
    '本应用完全免费，请勿上当受骗。\n\n' +
    '任何出售本软件、安装包、激活码、会员或「官方售后」向您收费的行为，均为诈骗或未经授权的倒卖。\n' +
    '请勿向陌生人转账；请勿轻信第三方「付费版 / 破解版」。\n\n' +
    '获取最新版本：请打开抖音搜索「九易」。'
  )
}

/** After runtime+backend OK: success splash with free notice + install guide (first launch). */
function showWelcomeGate() {
  const welcomePath = path.join(app.getPath('userData'), WELCOME_MARKER)
  const already = fs.existsSync(welcomePath)
  // Packaged: always show once on first success; later launches skip.
  // Dev: show when --strict-user, otherwise skip so daily coding isn't blocked.
  const shouldShow = app.isPackaged ? !already : process.argv.includes('--strict-user') && !already
  if (!shouldShow) return Promise.resolve()

  return new Promise((resolve) => {
    continueBootResolve = () => {
      try {
        fs.writeFileSync(welcomePath, '1\n', 'utf8')
        fs.writeFileSync(path.join(app.getPath('userData'), FREE_NOTICE_MARKER), '1\n', 'utf8')
      } catch {
        /* ignore */
      }
      resolve()
    }
    try {
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.setSize(520, 620)
        splashWindow.center()
        splashWindow.setAlwaysOnTop(true)
      }
    } catch {
      /* ignore */
    }
    splashSend({
      mode: 'success',
      pct: 100,
      subtitle: '准备完成',
      label: '成功',
      title: '运行环境已就绪',
      free: freeNoticeText(),
      guide: welcomeGuideText(),
    })
  })
}

function createWindow(port) {
  const ed = edition()
  const iconPath = path.join(__dirname, 'build', 'icon.png')
  mainWindow = new BrowserWindow({
    width: DEFAULT_W,
    height: DEFAULT_H,
    minWidth: MIN_W,
    minHeight: MIN_H,
    title: ed === 'light' ? '九易AI智能体 · 轻量版' : '九易AI智能体',
    ...(fs.existsSync(iconPath) ? { icon: iconPath } : {}),
    webPreferences: {
      preload: path.join(__dirname, 'preload.mjs'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    show: false,
  })

  mainWindow.once('ready-to-show', () => {
    closeSplash()
    mainWindow?.show()
  })
  mainWindow.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url)
    return { action: 'deny' }
  })
  void mainWindow.loadURL(`http://127.0.0.1:${port}/`)
}

app.whenReady().then(async () => {
  Menu.setApplicationMenu(null)
  registerMediaProtocol()
  registerSplashIpc()
  createSplash()
  // Give splash a moment to paint before heavy work
  await new Promise((r) => setTimeout(r, 120))
  try {
    if (app.isPackaged) {
      await ensureRuntimeBootstrap()
      const py = findPython()
      if (!py.cmd) {
        throw new Error(`未找到可用 Python，请安装 Python 3.10+ 后重试，或删除后重开：\n${runtimeDir()}`)
      }
    } else {
      splashSend({
        subtitle: '开发模式启动…',
        pct: 50,
        label: '跳过便携环境引导',
        line: 'dev mode — using system / project Python',
      })
    }
    const port = await startBackend()
    splashSend({ pct: 100, label: '启动成功', subtitle: '运行环境已就绪' })
    await showWelcomeGate()
    createWindow(port)
  } catch (e) {
    console.error(e)
    const msg = e instanceof Error ? e.message : String(e)
    showBootError(msg)
    // Keep splash open so user can copy; do not quit immediately
  }
})

app.on('window-all-closed', () => {
  // Splash-only error state: quitting via button uses boot:quit
  if (splashWindow && !splashWindow.isDestroyed() && (!mainWindow || mainWindow.isDestroyed())) {
    return
  }
  killBackend()
  if (process.platform !== 'darwin') app.quit()
})

app.on('before-quit', () => {
  killBackend()
})
