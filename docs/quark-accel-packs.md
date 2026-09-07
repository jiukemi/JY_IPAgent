# 夸克 / 仓库加速包：要托管什么、怎么区分显卡

> 对应代码：`workflow/quark_accel.py`、`data/quark/catalog.json`  
> 设置页：**设置 → 加速包下载 · 仓库优先**

## 重要：不要把整包塞进 Git 仓库

口播加速包约 **4.6GB（通用）/ 6.7GB（RTX50）**。

| 平台 | 限制 | 结论 |
|------|------|------|
| Git 代码仓库 | 单文件通常 ≤100MB | **禁止**把 zip 推进仓库 |
| GitHub Releases | **单附件 ≤2GiB** | 整包不行，须**分卷** `.part1` `.part2`… |
| Gitee Releases | 单附件更小 | 不适合整包；可只挂说明 |
| 夸克分享 | 易「下一次就失效」 | 仅作备用 |

## 是否值得上传 GitHub 分卷？

**值得作备用渠道**（夸克易失效；GitHub Release 相对稳），但：

- **不要**把分卷推进 git 代码仓库，只挂 **Releases 附件**。
- 分卷本身是按字节切开再拼回，**正确上传 + 用户下齐全部 `.partN` 时不会“自然破损”**。
- 真出问题多半是：漏下一个分卷、下载中断/不完整、或浏览器改名。安装时软件会拼接；包内 `MANIFEST` 的 sha256 还能拦住坏部件。
- 运维注意：用脚本二进制切开、`gh release upload` 直传；用户须同一包的 `.part1`…全部下到同一文件夹。

当前可先继续主推夸克整包 +「失效私聊作者」；分卷等你确认后再上传，不必为分卷单独发应用版。

```powershell
powershell -File scripts/split_accel_for_github_release.ps1 -ZipPath dist\quark-packs\九易AI-加速包-口播-通用显卡.zip
gh release create accel-packs --repo jiukemi/JY_IPAgent --title "加速包（分卷）" --notes "按显卡下载对应全部 .partN。"
gh release upload accel-packs dist\quark-packs\*.part* --repo jiukemi/JY_IPAgent --clobber
```

用户：全部 `.partN` 下到「下载」→ 扫描安装（自动拼接）。

`data/quark/catalog.json` 中 `download_url` 优先于夸克 `share_url`。

## 通用 vs 显卡

| pack_id | 谁该下 |
|---------|--------|
| heygem-docker-general | 非 RTX50 |
| heygem-docker-rtx50 | 仅 RTX50 系 |

打包装与 Docker 选盘说明见仓库内历史文档；产物在 `dist/quark-packs/`（gitignore，勿提交）。
