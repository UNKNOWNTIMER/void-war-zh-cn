# 构建与验证

仓库主分支当前发布 **2026.10.10.4 / Void War 1.5.3 beta / Steam build 25749411**。运行时仅使用 Python 标准库和 tkinter，安装器离线运行，不联网或上传信息。需要 Windows x64、Python 3.12.14（带 tkinter）。

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

固定依赖保证相同的构建流程；EXE 仍可能因系统、工具链或 PE 元数据产生不同散列。每次构建应记录散列并重新验收。

## 直接重建安装器

仓库已经包含经过验证的 `payload/` 七个文件，可以直接打包安装器：

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe build_exe.py
& .\dist\VoidWar_Chinese_Patch.exe --self-check-report .build\frozen_self_check.json
& .\.venv\Scripts\python.exe audit_public_bundle.py --exe dist\VoidWar_Chinese_Patch.exe --original-dir .\private\beta-original --report .build\public_audit.json
```

公开包检查的 `--original-dir` 是本地拥有的原始游戏资源目录，用来检查未把完整原版资源塞进 EXE。自检验证嵌入载荷与 tkinter 能加载，不访问真实游戏或存档；它不能代替真实界面操作和安装测试。

## 重建引擎差分

`engine_tools/` 提供本次迁移、排版和商人随机对话修复代码。以下三个输入都必须是你本地已有的、散列匹配的游戏资源；仓库不分发完整引擎。

| 输入 | 必须匹配的 SHA-256 |
|---|---|
| 1.5.2b 原始 data.win | `1d8bb23910251b7bc50f1013efbec18ce0cf030894e7d2de50c4bdadfb9f8db9` |
| 2026.10.10.3 稳定版汉化目标 data.win | `f9a3f8471d84605a286b0245bd48af609ece4bb6cbde90b2804f681fbafb078a` |
| 1.5.3 beta 原始 data.win | `336d857f6ca0b7a4d847c15094668ca8488ec5949eb0abf0439da1b331e5ec2f` |

稳定版目标可以用历史 .3 补丁和自己持有的 1.5.2b 原版资源在独立副本中生成。所有输入只读，输出必须为另一个工作文件，禁止指向输入或真实正在使用的游戏目录。

以下命令从仓库根目录执行。先将三个输入分别放到 `private/stable-original/data.win`、`private/stable-chinese/data.win` 和 `private/beta-original/data.win`，再建立 `private/beta-package`：

```powershell
& .\.venv\Scripts\python.exe engine_tools\inventory_port.py --stable-original private\stable-original\data.win --stable-target private\stable-chinese\data.win --beta-original private\beta-original\data.win --output private\beta-package\data.win --audit-dir .build\engine-audit
& .\.venv\Scripts\python.exe engine_tools\port_engine.py --stable-original private\stable-original\data.win --stable-target private\stable-chinese\data.win --beta-original private\beta-original\data.win --output private\beta-package\data.win --audit-dir .build\engine-audit
& .\.venv\Scripts\python.exe engine_tools\layout_patch.py --data private\beta-package\data.win --report .build\layout_patch.json
& .\.venv\Scripts\python.exe engine_tools\gossip_patch.py --data private\beta-package\data.win --translations engine_tools\gossip_zh.json --report .build\gossip_patch.json
& .\.venv\Scripts\python.exe engine_tools\test_layout_vm.py --data private\beta-package\data.win --report .build\layout_vm.json
```

顺序必须为 **迁移 → 排版 → 随机对话**，各阶段都检查输入版本。最终目标应为：

```text
38910d97eecd7f31cf3250c22e62c687be5997088c7abcc95a3ec9c9fadd7414
```

将仓库 `payload/lang/`、字体和许可证复制到 `private/beta-package/` 的相同相对位置。原始资源目录还须有游戏自带的三张 `lang/*_zh-Hans` 表；这些原始文件不公开发布。

```powershell
& .\.venv\Scripts\python.exe engine_tools\font_audit.py --package-dir private\beta-package --report .build\font_audit.json
& .\.venv\Scripts\python.exe build_payload.py --original-dir private\beta-original --package-dir private\beta-package --output payload --version 2026.10.10.4
& .\.venv\Scripts\python.exe tests\validate_real_payload.py --original-dir private\beta-original --payload payload --report .build\real_payload_validation.json
& .\.venv\Scripts\python.exe build_exe.py
```

差分只保存变更字节、位置和原字节散列，不包含未修改的原版上下文。当前差分为 **7,786 段、65,303 字节替换数据**；其余载荷是中文表、OFL 字体和许可。真实载荷验证使用模拟游戏目录与合成存档，不打开真实游戏，也不修改输入原件。

## 安装事务和版本隔离

新包只支持清单中的 beta 源散列与目标散列，`compatible_previous` 为空，不把旧稳定版资源当作 beta。历史 `compatibility/c35.json` 仅供稳定版构建使用，不用于本 beta 包。

原版备份使用版本专用目录 `_VoidWar_Chinese_Original_1_5_3_beta`，记录原始资源散列和安装前语言值。旧稳定版备份保留，不混用、不反向迁移。目标文件先生成、校验，再逐项原子替换；普通失败回滚，强制中断后下次操作先恢复事务。未知外部修改会使操作停止并保留现场。

只修改当前 profile 的语言字段，不使用历史 profile 覆盖后来获得的进度；autosave 与 score 不参与安装。字体和许可证按实际安装前状态恢复。日志只记录操作和错误代码。

## 发布前检查

应验证源、目标与独立重建的散列一致；检查三张语言表键序、变量、缺译和未审查英文；检查实际字体覆盖；执行安装器安全测试、真实载荷模拟安装／还原、冻结 EXE 自检，以及游戏内代表场景和真实 EXE 的安装／还原／再次安装。

原版引擎、原版 CSV、存档、测试选择器、测试目录、凭据、个人绝对路径和本地审计原文不得提交。源码与文档采用明确文件白名单，公开验证摘要见 `docs/validation-1.5.3-beta.json`，实际边界见 [QUALITY.md](QUALITY.md)。将 `VoidWar_Chinese_Patch.exe` 和同版 `SHA256SUMS.txt` 上传到发行页。

GitHub 的最新下载固定路径需要一个已公开的正式 Release。这里“正式 Release”指 GitHub 的发行标记，游戏适配对象仍明确是 **1.5.3 beta**。发布时先上传完整附件，再设为 latest，保留历史稳定版 Release 和文件名 `VoidWar_Chinese_Patch.exe`。最后匿名下载整个 latest 文件，比较字节数、SHA-256 和实际跳转版本。
