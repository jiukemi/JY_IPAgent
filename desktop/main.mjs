/**
 * Agent desktop shell: spawn FastAPI (server.py), open BrowserWindow.
 * Engines are NOT bundled — download later via 本机环境 / components.
 *
 * Packaged runtime (Python/FFmpeg) prefers the install drive (e.g. D:\\JY_IPAgent-Data\\runtime),
 * with a tiny pointer under userData. Falls back to %APPDATA% if that drive is unwritable.
 * Existing AppData runtimes are kept (no silent migrate) to avoid disrupting current users.
 */
import { app, BrowserWindow, shell, dialog, Menu, ipcMain, clipboard, protocol, net } from 'electron'
import { execSync, spawn } from 'node:child_process'
import fs from 'node:fs'
import os from 'node:os'
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
let splashReady = false
const splashQueue = []
/** @type {import('node:child_process').ChildProcessWithoutNullStreams | null} */
let bootstrapProc = null
/** @type {(() => void) | null} */
let continueBootResolve = null

function edition() {
  if (process.argv.includes('--light')) return 'light'
  if (process.argv.includes('--full')) return 'full'
  const e = (process.env.AGENT_EDITION || 'full').toLowerCase()
  return e === 'light' ? 'light' : 'full'
}

/** @type {string | null} */
let runtimeDirCache = null

function legacyUserDataRuntime() {
  return path.join(app.getPath('userData'), 'runtime')
}

function runtimePointerPath() {
  return path.join(app.getPath('userData'), 'runtime-root.json')
}

function installDriveRoot() {
  try {
    const exe = app.isPackaged ? process.execPath : ROOT
    return path.parse(path.resolve(exe)).root
  } catch {
    return process.platform === 'win32' ? 'C:\\' : '/'
  }
}

function runtimeOnDrive(driveRoot) {
  const root = String(driveRoot || '').trim() || installDriveRoot()
  // D:\JY_IPAgent-Data\runtime — outside Program Files, no admin needed
  return path.join(root, 'JY_IPAgent-Data', 'runtime')
}

function readRuntimePointer() {
  try {
    const p = runtimePointerPath()
    if (!fs.existsSync(p)) return null
    const j = JSON.parse(fs.readFileSync(p, 'utf8'))
    const root = typeof j?.root === 'string' ? j.root.trim() : ''
    if (!root) return null
    return { root: path.resolve(root), source: String(j.source || 'custom') }
  } catch {
    return null
  }
}

function writeRuntimePointer(root, source = 'custom') {
  const resolved = path.resolve(root)
  fs.mkdirSync(app.getPath('userData'), { recursive: true })
  fs.writeFileSync(
    runtimePointerPath(),
    JSON.stringify({ root: resolved, source, updatedAt: new Date().toISOString() }, null, 2),
    'utf8',
  )
  runtimeDirCache = null
  return resolved
}

function dirIsWritable(dir) {
  try {
    fs.mkdirSync(dir, { recursive: true })
    const probe = path.join(dir, `.write_probe_${process.pid}`)
    fs.writeFileSync(probe, 'ok')
    fs.unlinkSync(probe)
    return true
  } catch {
    return false
  }
}

function legacyRuntimeLooksUsed(dir) {
  return (
    fs.existsSync(path.join(dir, 'venv')) ||
    fs.existsSync(path.join(dir, 'python', 'python.exe')) ||
    fs.existsSync(path.join(dir, 'python.json'))
  )
}

function freeBytesForPath(anyPath) {
  if (process.platform !== 'win32') return null
  try {
    const drive = path.parse(path.resolve(anyPath)).root.replace(/\\/g, '').replace(':', '')
    if (!drive) return null
    const out = execSync(
      `powershell -NoProfile -Command "(Get-PSDrive -Name ${JSON.stringify(drive)}).Free"`,
      { windowsHide: true, timeout: 8000, encoding: 'utf8' },
    )
    const n = Number(String(out).trim())
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

function listFixedDrives() {
  if (process.platform !== 'win32') {
    return [{ letter: '/', root: '/', freeBytes: null, label: '/' }]
  }
  try {
    const script =
      "Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Used -ne $null } | ForEach-Object { Write-Output (($_.Name) + '|' + ($_.Root) + '|' + ($_.Free)) }"
    const out = execSync(`powershell -NoProfile -ExecutionPolicy Bypass -Command ${JSON.stringify(script)}`, {
      windowsHide: true,
      timeout: 12000,
      encoding: 'utf8',
    })
    const drives = String(out)
      .split(/\r?\n/)
      .map((line) => line.trim())
      .filter(Boolean)
      .map((line) => {
        const [name, root, free] = line.split('|')
        if (!name) return null
        return {
          letter: `${name}:`,
          root: root || `${name}:\\`,
          freeBytes: Number(free) || 0,
          label: `${name}:`,
        }
      })
      .filter(Boolean)
    return drives.length ? drives : [{ letter: 'C:', root: 'C:\\', freeBytes: null, label: 'C:' }]
  } catch {
    return [{ letter: 'C:', root: 'C:\\', freeBytes: null, label: 'C:' }]
  }
}

/**
 * Writable dir for portable Python + FFmpeg.
 * Priority (packaged): pointer → existing AppData runtime → install-drive Data folder → AppData.
 */
function resolveRuntimeDir() {
  if (!app.isPackaged) {
    return path.join(ROOT, 'data', 'runtime')
  }
  const pointer = readRuntimePointer()
  if (pointer?.root && dirIsWritable(pointer.root)) {
    return pointer.root
  }
  const legacy = legacyUserDataRuntime()
  if (legacyRuntimeLooksUsed(legacy)) {
    return legacy
  }
  const onInstall = runtimeOnDrive(installDriveRoot())
  if (dirIsWritable(onInstall)) {
    try {
      writeRuntimePointer(onInstall, 'install-drive')
    } catch {
      /* ignore */
    }
    return onInstall
  }
  return legacy
}

function runtimeDir() {
  if (runtimeDirCache) return runtimeDirCache
  runtimeDirCache = resolveRuntimeDir()
  return runtimeDirCache
}

function invalidateRuntimeDirCache() {
  runtimeDirCache = null
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

function resolvePackagedPath(...parts) {
  const inside = path.join(__dirname, ...parts)
  const unpacked = inside.replace(`${path.sep}app.asar${path.sep}`, `${path.sep}app.asar.unpacked${path.sep}`)
  if (unpacked !== inside && fs.existsSync(unpacked)) return unpacked
  if (fs.existsSync(inside)) return inside
  return inside
}

function splashSend(payload) {
  if (!splashWindow || splashWindow.isDestroyed()) return
  if (!splashReady) {
    splashQueue.push(payload)
    return
  }
  try {
    splashWindow.webContents.send('boot:update', payload)
  } catch {
    /* ignore */
  }
}

function flushSplashQueue() {
  if (!splashReady || !splashWindow || splashWindow.isDestroyed()) return
  const batch = splashQueue.splice(0, splashQueue.length)
  for (const payload of batch) {
    try {
      splashWindow.webContents.send('boot:update', payload)
    } catch {
      /* ignore */
    }
  }
}

function createSplash() {
  splashReady = false
  splashQueue.length = 0
  const iconPath = path.join(__dirname, 'build', 'icon.png')
  // Prefer CJS preload — ESM (.mjs) inside asar often fails to expose contextBridge on Windows
  const preloadCjs = resolvePackagedPath('splash-preload.cjs')
  const preloadMjs = resolvePackagedPath('splash-preload.mjs')
  const preloadPath = fs.existsSync(preloadCjs) ? preloadCjs : preloadMjs
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
      preload: preloadPath,
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
    },
  })
  splashWindow.webContents.on('preload-error', (_e, pathTried, err) => {
    console.error('splash preload-error', pathTried, err)
  })
  splashWindow.once('ready-to-show', () => {
    splashWindow?.show()
  })
  void splashWindow.loadFile(path.join(__dirname, 'splash.html'))
  splashWindow.webContents.once('did-finish-load', () => {
    // Do NOT mark splashReady here — wait for boot:splash-ready from onUpdate subscription
    // so the first progress events are not delivered before the UI listens.
    splashSend({
      runtime: inspectRuntime(),
      subtitle: '正在准备运行环境…',
      pct: 1,
      label: '检测运行时',
      free: freeNoticeText(),
      foot: '本应用完全免费 · 请勿上当受骗 · 抖音搜索「九易」获取最新版',
      logPath: path.join(runtimeDir(), 'bootstrap.log'),
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
  const pointer = readRuntimePointer()
  const installRoot = installDriveRoot()
  const info = {
    path: dir,
    exists,
    sizeBytes: 0,
    hasVenv: false,
    hasEmbed: false,
    hasLog: false,
    hasConfig: false,
    hasPythonMeta: false,
    source: pointer?.source || (dir === legacyUserDataRuntime() ? 'userdata' : 'install-drive'),
    installDrive: installRoot,
    preferredOnInstallDrive: runtimeOnDrive(installRoot),
    freeBytes: freeBytesForPath(dir),
    pointerPath: runtimePointerPath(),
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

function killBootstrapProc() {
  const proc = bootstrapProc
  bootstrapProc = null
  if (!proc || proc.killed) return
  try {
    if (process.platform === 'win32' && proc.pid) {
      execSync(`taskkill /pid ${proc.pid} /T /F`, { stdio: 'ignore', windowsHide: true, timeout: 15000 })
    } else {
      proc.kill()
    }
  } catch {
    try {
      proc.kill()
    } catch {
      /* ignore */
    }
  }
}

/** Clear runtime folder. Rename-first to dodge Windows file locks, then delete. */
function clearRuntimeDir() {
  killBootstrapProc()
  killBackend()
  invalidateRuntimeDirCache()
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

function sanitizeConfigYaml(raw) {
  return String(raw || '')
    .split(/\r?\n/)
    .map((line) => {
      if (/^\s*(api[_-]?key|token|secret|password|access[_-]?key|secret[_-]?key)\s*:/i.test(line)) {
        const i = line.indexOf(':')
        return `${line.slice(0, i + 1)} "***"`
      }
      return line
    })
    .join('\n')
}

function readAppVersionSafe() {
  try {
    return app.getVersion()
  } catch {
    /* ignore */
  }
  try {
    const v = fs.readFileSync(path.join(ROOT, 'VERSION'), 'utf8').trim()
    if (v) return v
  } catch {
    /* ignore */
  }
  return 'unknown'
}

function collectDiagMeta() {
  const rt = runtimeDir()
  const drives = listFixedDrives()
  return {
    exportedAt: new Date().toISOString(),
    appVersion: readAppVersionSafe(),
    packaged: app.isPackaged,
    platform: process.platform,
    arch: process.arch,
    electron: process.versions?.electron,
    node: process.versions?.node,
    execPath: process.execPath,
    resourcesPath: process.resourcesPath || '',
    root: ROOT,
    userData: app.getPath('userData'),
    runtime: inspectRuntime({ withSize: true }),
    runtimePointer: readRuntimePointer(),
    installDrive: installDriveRoot(),
    drives,
    envHints: {
      AGENT_RUNTIME_DIR: process.env.AGENT_RUNTIME_DIR || '',
      HTTP_PROXY: process.env.HTTP_PROXY || '',
      HTTPS_PROXY: process.env.HTTPS_PROXY || '',
    },
  }
}

/** Build a zip users can send for support. */
async function exportDiagnosticsZip() {
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19)
  const tmpRoot = path.join(os.tmpdir(), `jy-diag-${process.pid}-${Date.now()}`)
  const folder = path.join(tmpRoot, `JY_IPAgent-diag-${stamp}`)
  fs.mkdirSync(folder, { recursive: true })

  const meta = collectDiagMeta()
  fs.writeFileSync(path.join(folder, 'meta.json'), JSON.stringify(meta, null, 2), 'utf8')
  fs.writeFileSync(
    path.join(folder, 'README.txt'),
    [
      '九易AI智能体 · 诊断包',
      `导出时间: ${meta.exportedAt}`,
      `版本: ${meta.appVersion}`,
      `运行时: ${meta.runtime?.path || ''}`,
      '',
      '请把本 zip 发给客服/开发者（已尽量去掉 API Key）。',
      '',
    ].join('\n'),
    'utf8',
  )

  const copies = [
    [path.join(runtimeDir(), 'bootstrap.log'), 'bootstrap.log'],
    [path.join(runtimeDir(), 'python.json'), 'python.json'],
    [path.join(ROOT, 'VERSION'), 'VERSION'],
    [runtimePointerPath(), 'runtime-root.json'],
  ]
  for (const [src, name] of copies) {
    try {
      if (fs.existsSync(src)) fs.copyFileSync(src, path.join(folder, name))
    } catch {
      /* ignore */
    }
  }
  for (const cfg of [path.join(runtimeDir(), 'config.yaml'), path.join(ROOT, 'config.yaml')]) {
    try {
      if (!fs.existsSync(cfg)) continue
      const raw = fs.readFileSync(cfg, 'utf8')
      fs.writeFileSync(path.join(folder, 'config.sanitized.yaml'), sanitizeConfigYaml(raw), 'utf8')
      break
    } catch {
      /* ignore */
    }
  }

  // Port probe snapshot
  const portLines = []
  for (let port = 7860; port <= 7890; port++) {
    try {
      const ok = await new Promise((resolve) => {
        const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
          res.resume()
          resolve(res.statusCode === 200)
        })
        req.on('error', () => resolve(false))
        req.setTimeout(600, () => {
          req.destroy()
          resolve(false)
        })
      })
      if (ok) portLines.push(`${port}=healthy`)
    } catch {
      /* ignore */
    }
  }
  fs.writeFileSync(
    path.join(folder, 'ports.txt'),
    portLines.length ? portLines.join('\n') : 'no healthy port in 7860-7890',
    'utf8',
  )

  const defaultName = `JY_IPAgent-diag-${stamp}.zip`
  const save = await dialog.showSaveDialog({
    title: '导出诊断包',
    defaultPath: path.join(app.getPath('downloads'), defaultName),
    filters: [{ name: 'Zip', extensions: ['zip'] }],
  })
  if (save.canceled || !save.filePath) {
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
    return { ok: false, cancelled: true, message: '已取消' }
  }
  const zipPath = save.filePath.endsWith('.zip') ? save.filePath : `${save.filePath}.zip`
  try {
    if (fs.existsSync(zipPath)) fs.unlinkSync(zipPath)
  } catch {
    /* ignore */
  }

  // Compress-Archive needs the folder contents; use -Path folder\*
  try {
    const ps = `Compress-Archive -Path ${JSON.stringify(folder + path.sep + '*')} -DestinationPath ${JSON.stringify(zipPath)} -Force`
    execSync(`powershell -NoProfile -ExecutionPolicy Bypass -Command ${JSON.stringify(ps)}`, {
      windowsHide: true,
      timeout: 120000,
    })
  } catch (e) {
    try {
      fs.rmSync(tmpRoot, { recursive: true, force: true })
    } catch {
      /* ignore */
    }
    return {
      ok: false,
      message: `压缩失败：${e instanceof Error ? e.message : e}`,
    }
  }
  try {
    fs.rmSync(tmpRoot, { recursive: true, force: true })
  } catch {
    /* ignore */
  }
  try {
    shell.showItemInFolder(zipPath)
  } catch {
    /* ignore */
  }
  return { ok: true, path: zipPath, message: `已导出：${zipPath}` }
}

function setRuntimeDrive(driveLetter) {
  const raw = String(driveLetter || '').trim().toUpperCase()
  let root
  if (!raw || raw === 'APPDATA' || raw === 'USERDATA') {
    root = legacyUserDataRuntime()
    writeRuntimePointer(root, 'userdata')
  } else {
    const letter = raw.replace(/[^A-Z]/g, '').slice(0, 1)
    if (!letter) return { ok: false, message: '无效磁盘盘符' }
    root = runtimeOnDrive(`${letter}:\\`)
    if (!dirIsWritable(root)) {
      return {
        ok: false,
        message: `无法在 ${letter}: 写入 ${root}（权限或磁盘满）。请换盘或清理空间。`,
      }
    }
    writeRuntimePointer(root, 'custom')
  }
  invalidateRuntimeDirCache()
  return {
    ok: true,
    path: root,
    message: `运行时将使用：${root}\n下次启动（或清除运行时后）会在该目录准备环境。`,
    relaunchSuggested: true,
  }
}

function registerSplashIpc() {
  ipcMain.on('boot:splash-ready', () => {
    splashReady = true
    flushSplashQueue()
  })
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
    const logFile = path.join(dir, 'bootstrap.log')
    try {
      if (!fs.existsSync(logFile)) {
        fs.writeFileSync(logFile, `# bootstrap log\n# ${new Date().toISOString()}\n`, 'utf8')
      }
    } catch {
      /* ignore */
    }
    // Splash is alwaysOnTop — drop it so Explorer isn't hidden behind the splash
    try {
      if (splashWindow && !splashWindow.isDestroyed()) {
        splashWindow.setAlwaysOnTop(false)
        splashWindow.setAlwaysOnTop(true, 'floating')
        // briefly allow Explorer to take focus
        splashWindow.setAlwaysOnTop(false)
      }
    } catch {
      /* ignore */
    }
    // 1) Electron native reveal (most reliable)
    try {
      shell.showItemInFolder(logFile)
      return { ok: true, path: logFile }
    } catch {
      /* fall through */
    }
    // 2) Windows explorer /select
    if (process.platform === 'win32') {
      try {
        spawn('explorer.exe', [`/select,${logFile}`], {
          windowsHide: false,
          detached: true,
          stdio: 'ignore',
        }).unref()
        return { ok: true, path: logFile }
      } catch {
        /* fall through */
      }
      try {
        execSync(`cmd /c start "" explorer /select,"${logFile}"`, {
          windowsHide: true,
          timeout: 8000,
        })
        return { ok: true, path: logFile }
      } catch {
        /* fall through */
      }
    }
    const err = await shell.openPath(dir)
    if (err) {
      try {
        await shell.openExternal(pathToFileURL(dir).href)
      } catch {
        /* ignore */
      }
    }
    return { ok: !err, path: logFile, message: err || '' }
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
  ipcMain.handle('boot:export-diag', () => exportDiagnosticsZip())
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
  ipcMain.handle('desktop:export-diag', () => exportDiagnosticsZip())
  ipcMain.handle('desktop:list-drives', () => ({
    drives: listFixedDrives(),
    current: inspectRuntime({ withSize: false }),
    installDrive: installDriveRoot(),
  }))
  ipcMain.handle('desktop:set-runtime-drive', (_e, driveLetter) => {
    const result = setRuntimeDrive(driveLetter)
    return result
  })
  ipcMain.handle('desktop:set-runtime-drive-and-relaunch', (_e, driveLetter) => {
    const result = setRuntimeDrive(driveLetter)
    if (!result.ok) return result
    setTimeout(() => relaunchApp(), 500)
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
    let lastActivity = Date.now()
    let stallNotified = false
    const handleLine = (line) => {
      const t = String(line || '').trimEnd()
      if (!t) return
      // Dedupe stdout + file-tail of the same line
      if (seen.has(t)) return
      if (seen.size > 4000) seen.clear()
      seen.add(t)
      lastActivity = Date.now()
      stallNotified = false
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
    const stallTimer = setInterval(() => {
      const idleSec = Math.round((Date.now() - lastActivity) / 1000)
      if (idleSec >= 60 && !stallNotified) {
        stallNotified = true
        splashSend({
          stallHint: true,
          stallHintText:
            '已超过 1 分钟没有新日志。可能正在下载（请稍候），若持续无变化请点「清除运行时并重试」或「打开日志」。',
          line: `==> no new log for ${idleSec}s — check network / antivirus`,
        })
      }
      if (idleSec >= 12 * 60) {
        killBootstrapProc()
      }
    }, 15000)

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
          NO_PROXY: '127.0.0.1,localhost,::1',
          no_proxy: '127.0.0.1,localhost,::1',
          HTTP_PROXY: '',
          HTTPS_PROXY: '',
          ALL_PROXY: '',
          http_proxy: '',
          https_proxy: '',
          all_proxy: '',
        },
      },
    )
    bootstrapProc = ps
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
      clearInterval(stallTimer)
      if (bootstrapProc === ps) bootstrapProc = null
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
      const idleFail =
        code === null || code === 1
          ? ''
          : ''
      const killedStall = (Date.now() - lastActivity) >= 12 * 60 * 1000
      const tail = combined.slice(-1500)
      reject(
        new Error(
          (killedStall
            ? '首次准备超时：超过约 12 分钟没有新的日志输出（多为网络卡住或杀毒拦截下载）。\n'
            : `首次准备运行环境失败（exit=${code}）。\n`) +
            `运行时目录：${runtimeDir()}\n` +
            `日志：${logPath}\n\n` +
            (tail || '无输出，请检查网络或杀毒软件是否拦截。') +
            idleFail,
        ),
      )
    }

    ps.stdout.on('data', onChunk)
    ps.stderr.on('data', onChunk)
    ps.on('error', (err) => {
      clearInterval(logTimer)
      clearInterval(stallTimer)
      if (bootstrapProc === ps) bootstrapProc = null
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
      AGENT_AUTO_FFMPEG: '0',
      PYTHONUTF8: '1',
      PYTHONUNBUFFERED: '1',
      NO_PROXY: '127.0.0.1,localhost,::1',
      no_proxy: '127.0.0.1,localhost,::1',
    }
    // Closing VPN while system proxy still points at 127.0.0.1:7897 breaks local calls
    delete env.HTTP_PROXY
    delete env.HTTPS_PROXY
    delete env.ALL_PROXY
    delete env.http_proxy
    delete env.https_proxy
    delete env.all_proxy
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
      line: `python → ${found.cmd}`,
    })
    splashSend({ pct: 90, label: '清理旧后端进程…', line: '释放 7860–7890 端口' })
    killOrphanAgentServers()
    killBackend()

    // -u: unbuffered stdout so "Uvicorn running on …" reaches Electron promptly
    const childArgs = [...found.args, '-u', serverPy]
    pyProc = spawn(found.cmd, childArgs, {
      cwd: ROOT,
      env,
      windowsHide: true,
    })

    let buf = ''
    let resolved = false
    const finishPort = (port) => {
      if (resolved) return
      resolved = true
      clearInterval(pollTimer)
      splashSend({
        pct: 96,
        label: `等待健康检查 :${port}`,
        line: `backend → http://127.0.0.1:${port}`,
      })
      waitForHealth(port)
        .then(() => resolve(port))
        .catch(reject)
    }
    const tryPort = (chunk) => {
      const text = chunk.toString()
      buf += text
      for (const line of text.split(/\r?\n/)) {
        if (line.trim()) splashSend({ line: line.trim() })
      }
      const m = buf.match(/http:\/\/127\.0\.0\.1:(\d+)/)
      if (m) finishPort(Number(m[1]))
    }

    // Fallback when Python stdout is buffered: actively poll health endpoints
    const pollStarted = Date.now()
    const pollTimer = setInterval(() => {
      if (resolved) {
        clearInterval(pollTimer)
        return
      }
      const elapsed = Date.now() - pollStarted
      if (elapsed > 90000) {
        clearInterval(pollTimer)
        if (!resolved) reject(new Error('后端启动超时（未检测到健康端口 7860–7890）'))
        return
      }
      splashSend({
        pct: Math.min(95, 90 + Math.floor(elapsed / 18000)),
        label: '等待后端就绪…',
        line: `polling :7860–7890 (${Math.round(elapsed / 1000)}s) — 若超时请看运行时 bootstrap.log / 导出诊断包`,
      })
      for (let port = 7860; port <= 7890; port++) {
        const req = http.get(`http://127.0.0.1:${port}/api/health`, (res) => {
          res.resume()
          if (res.statusCode === 200) finishPort(port)
        })
        req.on('error', () => {})
        req.setTimeout(800, () => req.destroy())
      }
    }, 1200)

    pyProc.stdout.on('data', tryPort)
    pyProc.stderr.on('data', tryPort)
    pyProc.on('error', (err) => {
      clearInterval(pollTimer)
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
      clearInterval(pollTimer)
      if (!resolved) {
        const tail = buf.trim().slice(-800)
        reject(
          new Error(
            `后端提前退出 code=${code}\n${tail || '无日志输出'}`,
          ),
        )
      }
    })
  })
}

const WELCOME_MARKER = 'boot-welcome-v1.flag'
const FREE_NOTICE_MARKER = 'free-private-notice-v1.flag'

function welcomeGuideText() {
  return (
    '【引擎安装引导】安装包不含大模型，请按需下载：\n\n' +
    '1. 打开设置 →「本机环境 · GPU 与模型」\n' +
    '2. 基础：需要时安装 FFmpeg（字幕/封面/合成；首启不自动下）\n' +
    '3. 配音：安装 IndexTTS2（需 NVIDIA 显卡）或轻量 Piper\n' +
    '4. 文案提取：需要时安装 FunASR 或 Whisper\n' +
    '5. 口播：先安装并打开 Docker Desktop，再在口播页点「一键启动」\n' +
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
      preload: (() => {
        const cjs = resolvePackagedPath('preload.cjs')
        if (fs.existsSync(cjs)) return cjs
        return resolvePackagedPath('preload.mjs')
      })(),
      contextIsolation: true,
      nodeIntegration: false,
      sandbox: false,
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
