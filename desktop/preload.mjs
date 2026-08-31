import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('agentDesktop', {
  isDesktop: true,
  edition: () => (process.env.AGENT_EDITION === 'light' ? 'light' : 'full'),
  runtimeInfo: () => ipcRenderer.invoke('desktop:runtime-info'),
  clearRuntimeAndRelaunch: () => ipcRenderer.invoke('desktop:clear-and-relaunch'),
})
