const { Plugin, Notice, PluginSettingTab, Setting } = require("obsidian");
const { execFile } = require("child_process");
const { promisify } = require("util");
const path = require("path");
const fs = require("fs");

const execFileAsync = promisify(execFile);
const DEFAULT_SETTINGS = { remoteUrl: "https://github.com/169068671/Wang-Zimo-AI-Video.git", branch: "main", runValidation: true };

class AIVideoGitHubSyncPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    this.syncing = false;
    this.statusBar = this.addStatusBarItem();
    this.statusBar.setText("GitHub: 待同步");
    this.addRibbonIcon("cloud-upload", "同步王子墨 AI 视频仓库到 GitHub", () => this.runSync(false));
    this.addCommand({ id: "sync-wang-zimo-ai-video-to-github", name: "一键同步整个仓库到 GitHub", callback: () => this.runSync(false) });
    this.addCommand({ id: "check-wang-zimo-ai-video-to-github-status", name: "检查 GitHub 同步状态", callback: () => this.runSync(true) });
    this.addSettingTab(new SyncSettingTab(this.app, this));
  }

  vaultPath() {
    const adapter = this.app.vault.adapter;
    if (!adapter || typeof adapter.getBasePath !== "function") throw new Error("此插件只支持 Obsidian 桌面端的本地知识库。");
    return adapter.getBasePath();
  }

  scriptPath(vaultPath) { return path.join(vaultPath, "plugins", "github-vault-sync", "scripts", "sync_vault.py"); }

  parsePayload(stdout, fallback) {
    try { return JSON.parse((stdout || "").trim()); }
    catch (_) { return { ok: false, message: fallback || "同步脚本未返回有效结果。" }; }
  }

  async runSync(statusOnly) {
    if (this.syncing) { new Notice("同步任务正在运行，请勿重复点击。"); return; }
    this.syncing = true;
    const notice = new Notice(statusOnly ? "正在检查 Git 状态…" : "正在核验并同步到 GitHub…", 0);
    this.statusBar.setText(statusOnly ? "GitHub: 检查中" : "GitHub: 同步中");
    try {
      const vaultPath = this.vaultPath();
      const scriptPath = this.scriptPath(vaultPath);
      if (!fs.existsSync(scriptPath)) throw new Error(`缺少同步脚本：${scriptPath}`);
      const args = [scriptPath, "--vault", vaultPath, "--remote-url", this.settings.remoteUrl, "--branch", this.settings.branch, "--json"];
      if (statusOnly) args.push("--status");
      if (!statusOnly && this.settings.runValidation) args.push("--validate");
      const { stdout } = await execFileAsync("python3", args, { cwd: vaultPath, timeout: 1800000, maxBuffer: 8 * 1024 * 1024, env: Object.assign({}, process.env, { GIT_TERMINAL_PROMPT: "0", PATH: ["/opt/homebrew/bin", "/usr/local/bin", process.env.PATH || "/usr/bin:/bin:/usr/sbin:/sbin"].join(":") }) });
      const payload = this.parsePayload(stdout);
      if (!payload.ok) throw new Error(payload.message);
      notice.setMessage(payload.message);
      this.statusBar.setText(statusOnly ? `GitHub: ${payload.changes || 0} 项待同步` : `GitHub: 已同步 ${payload.commit}`);
      window.setTimeout(() => notice.hide(), 5000);
    } catch (error) {
      const stdout = error && error.stdout ? String(error.stdout) : "";
      const payload = this.parsePayload(stdout, error && error.message ? error.message : String(error));
      const message = payload.message || (error && error.message) || String(error);
      console.error("王子墨 AI 视频 GitHub Sync failed", error);
      notice.setMessage(`GitHub 同步失败：${message}`);
      this.statusBar.setText("GitHub: 同步失败");
      window.setTimeout(() => notice.hide(), 12000);
    } finally { this.syncing = false; }
  }
}

class SyncSettingTab extends PluginSettingTab {
  constructor(app, plugin) { super(app, plugin); this.plugin = plugin; }
  display() {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "王子墨 AI 视频 GitHub Sync" });
    containerEl.createEl("p", { text: "插件不保存 Token，使用电脑现有的 Git 凭据；不会强推或改写历史。" });
    new Setting(containerEl).setName("GitHub 仓库地址").setDesc("远程地址不一致时停止，不会自动替换。").addText((text) => text.setValue(this.plugin.settings.remoteUrl).onChange(async (value) => { this.plugin.settings.remoteUrl = value.trim(); await this.plugin.saveData(this.plugin.settings); }));
    new Setting(containerEl).setName("分支").setDesc("固定使用 main。").addText((text) => text.setValue(this.plugin.settings.branch).onChange(async (value) => { this.plugin.settings.branch = value.trim() || "main"; await this.plugin.saveData(this.plugin.settings); }));
    new Setting(containerEl).setName("上传前核验知识库").setDesc("建议始终开启。").addToggle((toggle) => toggle.setValue(this.plugin.settings.runValidation).onChange(async (value) => { this.plugin.settings.runValidation = value; await this.plugin.saveData(this.plugin.settings); }));
    new Setting(containerEl).setName("检查当前状态").setDesc("只读检查，不提交、不推送。").addButton((button) => button.setButtonText("检查").onClick(() => this.plugin.runSync(true)));
  }
}

module.exports = AIVideoGitHubSyncPlugin;
