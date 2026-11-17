# 娃衣小筑 · 完整 Render 部署版

这是从本机工作台整理的完整前后端，包含网页、Python后台、无体重输入的13项尺寸神经网络、自动照片分割、四视图换装、服装参考图、最高质量四视图3D生成、同页旋转浏览、已生成的150万面实例，以及邀请码注册和账号隔离。

本目录和原本 `E:\Research\For\bodym-measurement-estimation`、本机8520工作台相互独立。此包不包含API密钥、私人档案、训练原始数据或Python虚拟环境。

## 1. 上传 GitHub

将上传包中的 `dollfit` 文件夹和根目录两个 Render YAML 文件上传到仓库根目录。最终路径应是：

```text
Rd/
  README.md
  render.yaml
  render.production.yaml
  dollfit/
    index.html
    workbench.html
    workbench.js
    auth.js
    requirements.txt
    runtime/
    deployment/
    models/
    examples/
    bundled/
    assets/
```

请替换仓库中同名文件。不要变成 `Rd/DollFit-Render-Upload/dollfit/`，也不要变成 `Rd/dollfit/dollfit/`。

**必须上传 `bundled` 文件夹。** 模型与3D实例已拆成20MB以内的分片，构建时会自动合并并校验SHA-256，无需自行下载模型，也无需Git LFS。整个文件夹上传失败时，先上传网页和源码，再到 `dollfit/bundled` 分批上传分片。不要把整个ZIP直接上传成仓库中的一个ZIP文件。

GitHub网页上传可能不包含以点开头的文件。Python启动脚本会默认使用3.12兼容代码；在Render同时设置 `PYTHON_VERSION=3.12.12`，可避免遗漏 `.python-version` 的影响。`.env.example` 只是变量说明，不需要上传实际 `.env`。

## 2. Render 手动创建 Web Service

| Render项目 | 填写内容 |
| --- | --- |
| Source Code | Git Provider，连接GitHub，选择自己的 `Rd` 仓库 |
| Branch | `main` |
| Name | 自定义，例如 `dollfit`，平台提示重名时换一个 |
| Root Directory | **`dollfit`** |
| Language / Runtime | **Python 3** |
| Region | 可先选择Singapore（若当前账户可选），上线后实测国内访问速度和API连通性 |
| Build Command | `pip install -r requirements.txt && python -m deployment.assets restore` |
| Start Command | `python -m deployment.start` |
| Health Check Path（Advanced） | `/healthz` |

截图中的 Free 为0.1CPU/512MB，仅适合小规模试用；它会在15分钟没有入站流量后休眠，休眠、重启、重新部署会丢失新增本地文件。浏览器会显示临时存储提示。

**正式保存用户档案，建议至少选择1CPU/2GB实例，并挂载持久磁盘到 `/var/data`。** 原图、尺寸、账号、任务编号、生成图和GLB都写入 `DATA_DIR`；只有该目录在持久磁盘下才会长期保存。选择付费计算实例本身不会自动获得持久磁盘。

目前使用单实例、单生成队列；不要开多个副本或多个Uvicorn worker。扩容至多实例之前，需要改用共享数据库、对象存储和外部任务队列。

## 3. Environment Variables：现在可以填写这些变量

| KEY | VALUE怎么填 | 是否必需 |
| --- | --- | --- |
| `APP_SECRET` | 点击Generate，确保至少32字符；后续保持不变 | 必需 |
| `INVITE_CODE` | 自己设置至少8字符的邀请码，仅分享给受邀用户 | 开放注册时必需 |
| `ADMIN_USERNAME` | `owner`，或3～32位英文/数字/下划线用户名 | 建议 |
| `ADMIN_PASSWORD` | 自己设置至少12字符的独立管理员密码；记好，不要发聊天截图 | 建议 |
| `HEJU_API_KEY` | 合聚AI的生图密钥原文，通常以sk-开头，不加Bearer、不加引号 | 生成衣服必需 |
| `TRIPO_API_KEY` | 你购买的卖家服务Authorization令牌原文，不加Bearer，不填tcli用户ID | 生成新3D必需 |
| `TRIPO_PROVIDER` | `seller` | 当前卖家接口必需 |
| `PYTHON_VERSION` | `3.12.12` | 建议 |
| `DATA_DIR` | 免费测试填 `/tmp/dollfit-data`；正式挂盘后填 `/var/data/dollfit` | 建议明确设置 |
| `DATA_EPHEMERAL` | 免费测试填 `true`；确认已挂持久盘后填 `false` | 建议 |
| `USER_DAILY_DESIGNS` | `2`，每个账户每天最多发起2次服装设计/重试 | 可选，默认2 |
| `USER_DAILY_3D` | `2`，每个账户每天最多预留2次3D生成 | 可选，默认2 |
| `GLOBAL_DAILY_DESIGNS` | `10`，全站每日服装设计/重试上限 | 可选，默认10 |
| `GLOBAL_DAILY_3D` | `10`，全站每日3D生成上限 | 可选，默认10 |

额度是网站内部按北京时间日期统计的**提交/预留上限**，不是供应商账单。一套设计最多调用4次生图API；失败/不确定的请求也占用内部额度。开启自动3D时预先占用一次3D额度，即使四视图未全部成功也不会自动退还内部额度。重试可能另产生供应商费用，页面会先提示核对记录。将上限设为0可以暂停对应新生成；浏览已有模型和恢复已有任务查询仍可进行。

卖家接口固定为用户提供并实测可用的 `http://47.120.44.134`，Authorization使用原始令牌；上传是 `/upload`，生成是 `/tripo3d/generate`，查询是 `/tripo3d/query/{id}`。不使用官方Tripo的Bearer协议混接。生图固定为 `https://www.hejuapi.com/v1` 的 `gpt-image-2`。

令牌有效期和用量由供应商决定。`owner`登录后可在“接口设置”测试3D鉴权，该测试只查询有效期和用量。真实密钥在Render后台填写，网页不回显、不保存、不允许访客更改。接口设置只展示状态。

`APP_SECRET`、管理员密码及邀请码请自行保管；API密钥缺失时，网站与内置实例仍可浏览，但对应新生成功能会提示未配置。

## 4. 部署成功后的操作

1. 打开Render给出的 `https://你的服务名.onrender.com`。
2. 点击“进入工作台”，或在同一域名后加 `/workbench.html`。
3. 无需登录即可点“查看3D实例”浏览已经生成的最高质量150万面PBR模型；拖动旋转、滚轮缩放，展示始终在工作台内。
4. 用环境变量中的管理员账号登录。朋友选择“使用邀请码注册”，各自设置用户名和密码。未登录也能先选择照片；点击“登录后保存娃娃档案”会打开登录框，登录后保留照片并继续保存。切换为其他账户时会清除前一账户的草稿。
5. 正面、左侧面必需；生成四视图3D还需背面和右侧面。输入身高和模型性别分类，不需要体重。
6. 保存档案后预测13项尺寸。服装描述与最多3张服装参考图用于换装；尺寸始终从原始娃体照片预测。
7. 新服装固定 `high / 1024x1536`。卖家服务新3D固定 `faceCount=1500000`；贴图与模型版本按卖家实际返回，不虚构8K或H3.1。

账号之间的档案、原图、生成图、模型和源档案复用均检查归属。浏览器只保存当前档案ID，登录凭据使用HttpOnly Cookie。测量和付费生成使用单队列，避免小实例同时加载多个神经网络。

3D任务编号和已生成图片逐步保存。服务器重启后只恢复已有3D编号的查询/下载，不自动重复付费提交。生图中断后需先检查供应商记录，再手动重试未完成角度。如果3D提交已发出但未收到编号，请由管理员核对供应商记录并恢复编号。

## 5. 存储、性能与验证范围

模型是原来本机训练模型的**FP32 ONNX导出，没有重新训练、没有量化压缩**。8组输入、104项输出与PyTorch小数点后两位一致；详细报告见 `models/export_verification.json`。仍采用真人参考身高预测后按娃娃身高换算，BJD精度未验证，不能直接作为裁衣依据。

Windows本机实测神经网络子进程约294MB峰值RSS，网页服务器内存另计；这不是Render/Linux的资源保证。Free的0.1CPU会明显更慢，复杂背景、多人大图上传时可能超过512MB。正式用建议至少2GB内存，并在实际平台压测后调整。无需为远程生图和3D购买GPU。

内置模型约75.5MB，已核验150万个三角面、嵌入贴图/PBR，校验信息在 `examples/model_verification.json`。模型文件由流式响应提供，支持Range，浏览器按需加载。手机性能与网络不同，150万面仍可能加载较慢。

有持久磁盘时建议保留磁盘快照，并定期导出私人备份。免费版不具备持久性：账号也可能随休眠丢失，重新创建后旧数据不会自动回来。不要将真实用户资料提交到GitHub。

本包已验证本地HTTP、真实ONNX推理与供应商适配器的模拟任务链；没有替你登录Render、创建付费资源或进行新的付费生图/建模。首次Render构建仍需检查日志与 `/healthz`，再实测API连通性。公开大规模注册、收款、售卖与相应备案/供应商授权需按实际运营方式另行准备。

## 6. 常见问题

- **Build提示找不到requirements.txt**：Root Directory应填 `dollfit`；检查是否多嵌套了一层文件夹。
- **找不到bundled/manifest.json或分片**：完整上传 `dollfit/bundled`，不要只传网页和ZIP。
- **No open ports detected**：Start Command必须为 `python -m deployment.start`；已自动监听 `0.0.0.0:$PORT`。
- **提示APP_SECRET缺失**：添加环境变量，至少32字符，重新部署。
- **管理员密码不能登录**：用户名默认 `owner`；密码来自ADMIN_PASSWORD。免费服务重启后账号会重建。
- **生图401/403或3D令牌过期**：检查Render变量、供应商额度与期限；不能用合聚密钥替代卖家令牌。
- **Out of memory /进程被杀**：512MB不足时升级内存，不要增加workers。
- **照片或账号消失**：Free临时盘限制；正式使用需额外挂持久盘并设置DATA_DIR。
- **页面空白或第一次访问慢**：免费实例唤醒约需一分钟；可先检查healthz与Logs。

## 7. 开发验证

```text
pip install -r requirements.txt
pip install pytest httpx
python -m deployment.assets restore
python -m pytest tests -q
```

前端登录与保存流程还可用Node.js 24运行：在 `tests` 目录执行 `npm install` 后执行 `npm test`。这些DOM流程检查覆盖未登录保存、登录后保留照片、会话过期恢复、账号切换和旧WebView兼容。

测试使用临时目录与模拟API，不提交真实付费生成。原模型来源与组件说明见 `THIRD_PARTY.md`。

平台参考：[Render Web Services](https://render.com/docs/web-services)、[免费限制](https://render.com/docs/free)、[持久磁盘](https://render.com/docs/disks)、[环境变量](https://render.com/docs/configure-environment-variables)、[GitHub大文件限制](https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github)。
