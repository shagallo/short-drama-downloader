# 短剧下载工具（开源版）

这是一个本地 EXE/Web UI 版短剧搜索与分集下载工具。浏览器版在本机启动 Flask 服务，数据与下载记录都保存在本机。

## 新版使用流程

1. 在“发现短剧”中输入关键词或点击快捷分类。
2. 点击短剧卡片查看简介和全部分集。
3. 单选分集，或使用全选、反选、清空选择。
4. 将已选分集加入下载列表。
5. 在“下载管理”中展开短剧，查看每一集的状态和整部短剧的总体进度。

不再提供批量粘贴短剧 ID 的入口。

## 下载管理

- 下载任务以整部短剧分组，分集按顺序下载。
- 点击剧名前的三角按钮可展开或收起分集详情。
- 支持暂停或继续整个队列、重试失败分集、删除单部任务。
- 支持清除已完成记录或清空全部任务。
- 下载记录写入运行目录的 `download_tasks.json`，程序重启后自动恢复。
- 视频保存到“下载目录/短剧名/第 NNN 集.mp4”。

## 设置

“设置”页面可保存：

- 下载目录，并可直接在资源管理器中打开。
- `device_id`
- `install_id`
- `platform`

设备参数保存在运行目录的 `config.json`。设备参数未配置时可以正常搜索和浏览，但不能创建真实下载任务。

首次启动且没有现有配置时，程序会调用原项目的设备注册工具生成默认参数。设置页可以重新读取、手动替换、清除，或生成一组新参数；更新后等待和失败任务会自动重试。

## 运行源码

```powershell
cd "源码_开源版"
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
python app.py
```

默认访问 `http://127.0.0.1:5055`。也可以将端口作为第一个参数传入，例如 `python app.py 5091`。

## 测试

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
node --check static/app.js
```

测试覆盖当前红果公开分类接口的数据归一化、真实分集 ID 提取、队列落盘、暂停和恢复。

## 浏览器版接口

浏览器版提供搜索、设备配置、下载目录和下载队列接口。旧的 `/hg?vid=...` 仍保留用于兼容已有调用。

## 打包 EXE

```powershell
py -3.11 -m PyInstaller --clean --noconfirm "短剧下载神器开源版.spec"
```

打包前不要提交 `build/`、`dist/`、`src/`、`.env`、`config.json`、`download_tasks.json`、真实设备参数、Cookie 或 Token。

## 说明

当前浏览器版已重构。`desktop_app.py` 是独立的 Windows 原生旧版界面，不会复用本次浏览器页面的布局。
