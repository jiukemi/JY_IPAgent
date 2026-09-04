import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('agentDesktop', {
  isDesktop: true,
  edition: () => (process.env.AGENT_EDITION === 'light' ? 'light' : 'full'),
  runtimeInfo: () => ipcRenderer.invoke('desktop:runtime-info'),
  clearRuntimeAndRelaunch: () => ipcRenderer.invoke('desktop:clear-and-relaunch'),
  appVersion: () => ipcRenderer.invoke('desktop:app-version'),
  downloadUpdate: (release) => ipcRenderer.invoke('desktop:download-update', release),
  openReleasePage: (url) => ipcRenderer.invoke('desktop:open-release-page', url),
  openPath: (filePath) => ipcRenderer.invoke('desktop:open-path', filePath),
  onUpdateProgress: (cb) => {
    const handler = (_event, payload) => {
      try {
        cb(payload)
      } catch {
        /* ignore */
      }
    }
    ipcRenderer.on('desktop:update-progress', handler)
    return () => ipcRenderer.removeListener('desktop:update-progress', handler)
  },
})
