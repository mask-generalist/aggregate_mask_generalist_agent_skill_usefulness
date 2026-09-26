import { app, BrowserWindow } from "electron";
import path from "path";

let mainWindow;

app.on("ready", () => {
  mainWindow = new BrowserWindow({
    width: 800,
    height: 600,
    webPreferences: {
      nodeIntegration: true,
      contextIsolation: true,
    },
  });
  mainWindow.webContents.on("did-finish-load", () => {
    mainWindow.webContents.insertCSS(`
      body {
        overflow-y: hidden !important; /* Disable vertical scrolling */
      }
    `);
  });
  mainWindow.loadFile(path.join(".", "dist", "index.html"));
  //   mainWindow.loadURL('dist/index.html');
});
