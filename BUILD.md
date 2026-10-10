# 构建与验证

本目录是独立补丁器源码。运行时仅使用 Python 标准库及 tkinter，没有网络请求、账号、遥测或自动更新。

公开发布允许包含源码文件、说明书、`assets/` 的徽记 PNG 与 ICO、`docs/images/` 的两张界面截图、`compatibility/c35.json`、`payload/` 中的七个白名单文件和最终 EXE。不要发布游戏备份、完整 `data.win`、`.venv`、`.build`、模拟测试目录、任何存档或父目录的本地审计工作文件。仓库和发行包应采用显式白名单。

## 构建环境

Windows x64、Python 3.12.14（带 tkinter）。首次创建独立环境并安装固定构建依赖：

```powershell
python -m venv .venv
& .\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
```

固定依赖版本保证可复现的构建流程；不同系统和工具链可能产生不同 EXE 散列。最终产物必须重新记录散列并执行下面的验证。

## 生成安全载荷

`original` 必须是经校验的 1.5.2b 原版资源目录，`package` 必须是已完成静态及运行验收的目标汉化目录：

```powershell
& .\.venv\Scripts\python.exe build_payload.py --original-dir ..\backup --package-dir ..\package --output payload --version 2026.10.10.3
```

该步骤只读取原版和目标资源，不修改它们。引擎差分保存目标替换字节及每段原字节 SHA-256，原字节本身不写入补丁。额外载荷只有三份中文 CSV、OFL 字体及许可文本。`payload.json` 只包含相对路径、大小、散列和版本信息。

后续版本使用原始备份生成目标，因此无需从旧汉化反向推算原版。`compatibility/c35.json` 允许既有 C35 及六个已核验本地中间版安装升级；补丁器自身的本地安装记录也保存已安装文件散列。新增引擎版本必须明确加入经过验证的兼容清单，不得绕过源版本守卫。

## 自动安全验证

```powershell
& .\.venv\Scripts\python.exe -m unittest discover -s tests -v
& .\.venv\Scripts\python.exe tests\validate_real_payload.py --original-dir ..\backup --payload payload --report .build\real_payload_validation.json
```

单元测试只创建合成游戏与合成存档。第二条命令将真实资源复制到临时模拟目录，使用假的 EXE 标记及合成存档，检查完整差分安装/还原；它不会打开真实游戏、修改原始资源或访问真实存档。

## 打包 EXE

```powershell
& .\.venv\Scripts\python.exe build_exe.py
& .\dist\VoidWar_Chinese_Patch.exe --self-check-report .build\frozen_self_check.json
```

自检验证内嵌载荷并创建隐藏 tkinter 窗口，验证运行依赖能加载，不访问游戏或存档。窗口交互和真实目录安装仍需发布负责人实际检查。构建脚本会清理 PATH 中其他软件的 DLL 搜索位置。EXE 默认不要求管理员；写入受保护目录时才请求系统 UAC，并保留原用户的设置存档位置。

## 事务与恢复

首次安装校验版本、所有必需文件、补丁载荷、唯一有效语言字段和磁盘空间，然后创建 `_VoidWar_Chinese_Original` 完整备份。所有目标文件都先准备好，再逐项原子替换并校验。事务写入前保存每个文件的当前副本和散列。

普通失败触发自动回滚。强制结束或断电后，下一次打开并点击操作会先恢复未完成事务，再执行新请求。遇到外部文件变化或损坏的回滚副本，会保留现场并停止；不覆盖未知内容。原版备份始终保留。恢复时仅修改当前 `profile.sav` 的 `currLanguage` 字段，绝不拿历史 profile 覆盖新进度；autosave 和 score 不参与修改。

已有 PowerShell 版备份可直接接续，其历史设置快照不会覆盖当前进度。旧脚本原本保留的 OFL 字体与许可证也予以保留；新补丁器首次安装前不存在的附加文件则在还原时删除。

补丁器本身未进行代码签名。日志只记录操作与错误代码，不记录游戏路径、账户名、存档内容或原始异常堆栈。
