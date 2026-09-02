/**
 * Download Release installer and launch it (Windows NSIS).
 * Update discovery itself is done via /api/updates/check in the renderer.
 */
import { app, shell } from 'electron'
import fs from 'node:fs'
import http from 'node:http'
import https from 'node:https'
import path from 'node:path'
import { spawn } from 'node:child_process'
import { URL } from 'node:url'

function updatesDir() {
  const dir = path.join(app.getPath('userData'), 'updates')
  fs.mkdirSync(dir, { recursive: true })
  return dir
}

/**
 * @param {string} url
 * @param {string} dest
 * @param {(pct: number, received: number, total: number) => void} [onProgress]
 */
export function downloadFile(url, dest, onProgress) {
  return new Promise((resolve, reject) => {
    const tmp = `${dest}.part`
    try {
      if (fs.existsSync(tmp)) fs.unlinkSync(tmp)
    } catch {
      /* ignore */
    }

    const follow = (current, redirects) => {
      if (redirects > 8) {
        reject(new Error('下载重定向过多'))
        return
      }
      let parsed
      try {
        parsed = new URL(current)
      } catch (e) {
        reject(e instanceof Error ? e : new Error(String(e)))
        return
      }
      const lib = parsed.protocol === 'http:' ? http : https
      const req = lib.get(
        current,
        {
          headers: {
            'User-Agent': 'JY_IPAgent-Desktop-Updater/1.0',
            Accept: '*/*',
          },
          timeout: 120000,
        },
        (res) => {
          const code = res.statusCode || 0
          if ([301, 302, 303, 307, 308].includes(code) && res.headers.location) {
            res.resume()
            const next = new URL(res.headers.location, current).toString()
            follow(next, redirects + 1)
            return
          }
          if (code !== 200) {
            res.resume()
            reject(new Error(`下载失败 HTTP ${code}`))
            return
          }
          const total = Number(res.headers['content-length'] || 0)
          let received = 0
          const out = fs.createWriteStream(tmp)
          res.on('data', (chunk) => {
            received += chunk.length
            if (onProgress) {
              const pct = total > 0 ? Math.min(0.99, received / total) : 0
              onProgress(pct, received, total)
            }
          })
          res.pipe(out)
          out.on('finish', () => {
            out.close(() => {
              try {
                if (fs.existsSync(dest)) fs.unlinkSync(dest)
                fs.renameSync(tmp, dest)
                if (onProgress) onProgress(1, received, total || received)
                resolve(dest)
              } catch (e) {
                reject(e instanceof Error ? e : new Error(String(e)))
              }
            })
          })
          out.on('error', reject)
          res.on('error', reject)
        },
      )
      req.on('error', reject)
      req.on('timeout', () => {
        req.destroy()
        reject(new Error('下载超时'))
      })
    }

    follow(url, 0)
  })
}

/**
 * @param {{ download_url: string, name?: string, version?: string }} release
 * @param {(pct: number) => void} [onProgress]
 */
export async function downloadAndLaunchInstaller(release, onProgress) {
  const url = (release?.download_url || '').trim()
  if (!url) throw new Error('缺少下载地址')
  const version = (release.version || 'latest').replace(/[^\w.-]/g, '')
  const safeName =
    (release.name && path.basename(release.name).replace(/[<>:"/\\|?*]/g, '_')) ||
    `JY_IPAgent-Setup-${version}.exe`
  const dest = path.join(updatesDir(), safeName)
  await downloadFile(url, dest, (pct) => {
    if (onProgress) onProgress(pct)
  })
  // Launch NSIS installer; quit app so files can be replaced
  const child = spawn(dest, [], {
    detached: true,
    stdio: 'ignore',
    windowsHide: false,
  })
  child.unref()
  setTimeout(() => {
    app.quit()
  }, 800)
  return { path: dest }
}

export function openReleasePage(htmlUrl) {
  if (htmlUrl) void shell.openExternal(htmlUrl)
}
