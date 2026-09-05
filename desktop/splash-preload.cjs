const { contextBridge, ipcRenderer } = require('electron')

const api = {
  onUpdate: (cb) => {
    ipcRenderer.on('boot:update', (_e, data) => {
      try {
        cb(data)
      } catch {
        /* ignore */
      }
    })
    // Signal ready ONLY after the UI has subscribed — avoids dropped first progress events
    try {
      ipcRenderer.send('boot:splash-ready')
    } catch {
      /* ignore */
    }
  },
  copyText: (text) => ipcRenderer.invoke('boot:copy', text),
  openLogDir: () => ipcRenderer.invoke('boot:open-log'),
  quit: () => ipcRenderer.invoke('boot:quit'),
  continue: () => ipcRenderer.invoke('boot:continue'),
  openDownloads: () => ipcRenderer.invoke('boot:open-downloads'),
  openQuarkShare: () => ipcRenderer.invoke('boot:open-quark-share'),
  quarkInstall: () => ipcRenderer.invoke('boot:quark-install'),
  runtimeInfo: () => ipcRenderer.invoke('boot:runtime-info'),
  clearAndRetry: () => ipcRenderer.invoke('boot:clear-and-retry'),
  exportDiagnostics: () => ipcRenderer.invoke('boot:export-diag'),
}

contextBridge.exposeInMainWorld('bootSplash', api)
