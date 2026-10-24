# 极速水控 · FastWater

> 一个面向校园自助用水设备（饮水机 / 洗浴 / 洗衣机）的轻量 Android 客户端。
> 打开即设备列表，两步启动，不加载任何广告 SDK。

[English](#english) · 中文

---

## 这是什么

很多校园自助设备（直饮水机、浴室水控、共享洗衣机）需要先装一个运营方的 App，
而这类 App 往往首页塞满推荐、启动前有开屏、扫码后还有一层广告位，
真正要做的事只有一件：**点一下，出水**。

这个项目把这件事故意做得很薄：

- 没有首页信息流、没有开屏、没有悬浮广告位
- 不做登录以外的任何"运营功能"
- 全部业务请求由原生层直发，界面用 WebView 承载
- 整体产物约 45 KB

它是**第三方客户端**，不隶属任何设备运营方，也不修改对方的客户端。

## 功能

| 功能 | 说明 |
|---|---|
| 手机号 + 验证码登录 | 各自登录各自的账号，互不影响 |
| 设备列表 | 显示最近使用的设备与空闲状态 |
| 一键启动 | 选冷水/热水 → 启动，两步完成 |
| 实时计时 | 启动后显示已用水时长 |
| 扫码识别 | 摄像头扫码 / 相册选图 / 手动输入，三种方式 |
| NFC 标签 | 手机碰标签直接进入指定设备的启动页 |
| 免密签约引导 | 未签约时自动拉起支付宝授权页 |

支持的设备类别：直饮水（`04`）、洗浴（`08`）。洗衣（`00`）因走「下单-支付-启动」链路，
当前仅能读取规格，不能启动。

## 技术说明

**整体结构**

```
MainActivity (Java)
  └── WebView → assets/index.html (UI)
        ↕ JS Bridge
     所有 HTTP 请求 + SHA256 签名
```

请求与签名放在**原生 Java 层**而不是 JS 层，原因有两个：

1. `file://` 页面加载后，`fetch` 受同源策略限制，无法直接请求业务域名
2. `file://` 在部分 WebView 版本下不是 secure context，`crypto.subtle` 不可用

放在 Java 层就完全绕开这两个限制，也不需要引入 OkHttp 之类的依赖。

**签名方式**

请求需要携带 `sign` 头，算法为：

```
sha256("appSecret=<SECRET>&channel=android_app&timestamp=<ms>&token=<token>&version=<ver>&<path>")
```

`SECRET` 是从官方客户端 APK 中提取的固定值，属于公开可得的信息（任何解包工具都能读到），
因此直接写在源码里。如果你 fork 后对方更换了密钥，需要同步替换 `MainActivity.java` 中的常量。

**位置参数**

部分接口的风控签名会带上经纬度（`lat` / `lng`）。源码中默认为 `0.0`，
**使用前请改成你所在位置的坐标**，否则风控可能拒绝请求：

```java
private static final String LAT = "0.0";   // TODO 改成你所在位置的纬度
private static final String LNG = "0.0";   // TODO 改成你所在位置的经度
```

## 编译

> 仓库**不提供预编译 APK**，请自行构建。

**依赖**

- JDK 17 或更高（需要 `javac`、`keytool`）
- Android SDK **build-tools**（`aapt2`、`d8`、`apksigner`、`zipalign`）
- 对应平台的 `android.jar`
- Python 3（仅用于把 `classes.dex` 打进 APK 的小脚本）
- Bash（Windows 下用 Git Bash）

**步骤**

```bash
git clone https://github.com/t17633678010-design/fastwater.git
cd fastwater

export ANDROID_HOME=/path/to/android-sdk
# 或者分别指定：
# export ANDROID_BUILD_TOOLS=/path/to/build-tools/35.0.0
# export ANDROID_JAR=/path/to/platforms/android-35/android.jar

bash tools/build.sh
```

产物在 `dist/fastwater-v<版本>.apk`。

**脚本做了什么**

```
aapt2 compile   资源编译
aapt2 link      链接 + 打入 assets
javac           编译 Java
d8              class → classes.dex
pack_dex.py     把 dex 塞进 APK
zipalign        4 字节对齐
apksigner       签名（首次运行自动生成 debug 签名）
```

**两个常见坑**

1. `aapt2` 和 `apksigner` **不支持含中文或空格的路径**。
   脚本会先把工程复制到系统临时目录再编译，所以仓库路径有中文也没关系。
2. 有些 JDK 只把 `javac` / `java` 放进 `PATH`，`keytool` 不在。
   脚本会自动去 `JAVA_HOME` 和常见安装位置找，找不到会明确报错。

**改版本号**

`app-src/AndroidManifest.xml` 里的 `versionName` / `versionCode`，改完重新构建，
输出文件名会自动跟着变。

## 扫码的三种方式

1. **摄像头实时扫**：调用 WebView 的 `getUserMedia` + `BarcodeDetector`
2. **相册选图**：同上，用 `createImageBitmap`
3. **手动输入**：直接粘贴设备码

第 1、2 种依赖 `BarcodeDetector`，它底层需要 Google Play Services 的条码模块。
**没有 GMS 的国产 ROM 上会返回空结果**，此时自动降级到手动输入。

设备码的字段名是动态的（`qeykid` / `NQT` / `IMEI` / `SN`），
程序会依次尝试，第一个成功的即采用。

## NFC 标签

支持两种写法，效果不同。

**方式一：AAR（只写包名）**

```
TNF     0x04
Type    android.com:pkg
Payload com.fastwater.ctrl
```

碰一下直接打开 App。**AAR 本身不携带数据**，所以 App 会恢复"上一次启动过的设备"。
适合只固定用一台设备的场景。

**方式二：URI + AAR 两条记录（推荐）**

```
记录1  URI : pqfast://dev?i=<goodsId>&c=<categoryCode>&s=<shopId>&n=<name>
记录2  AAR : com.fastwater.ctrl
```

参数完整，每台设备可以各写一个标签，碰哪台开哪台。
⚠ 顺序不能反：AAR 放在第一条会破坏 URI 匹配。

参数含义：

| 键 | 含义 |
|---|---|
| `i` | goodsId |
| `c` | categoryCode（04 饮水 / 08 洗浴 / 00 洗衣） |
| `s` | shopId |
| `n` | 设备名（仅用于显示） |

**写卡**

`tools/nfc_write.py` 提供 PN532（串口/HSU）直接写 NTAG213 的能力：

```bash
python tools/nfc_write.py --list                  # 列出串口
python tools/nfc_write.py --gen "pqfast://..."    # 离线计算 NDEF 长度与 HEX
python tools/nfc_write.py --port COM3 --uri "pqfast://..."
python tools/nfc_write.py --port COM3 --read      # 读回验证
```

NTAG213 用户区 144 字节，一条带参数的 URI 记录约 80 字节，余量充足。

也可以用手机上的「NFC Tools」写入，选「URL / URI」填完整字符串即可。

## 目录结构

```
app-src/
  AndroidManifest.xml
  assets/index.html              界面（HTML + CSS + JS）
  java/com/fastwater/ctrl/
    MainActivity.java            WebView 宿主、JS Bridge、HTTP 与签名
  res/                           图标与主题
tools/
  build.sh                       一键构建
  pack_dex.py                    把 dex 写入 APK
  nfc_write.py                   PN532 写 NTAG213
```

## 已知限制

- 洗衣机只读规格，不能启动（链路不同）
- 饮水机不支持远程停止，必须到机器上按停止键
- 没有 GMS 的设备上摄像头扫码会降级为手动输入
- 坐标需自行填写，否则风控可能拦截

## 免责声明

本项目为个人学习与技术研究用途，**与任何设备运营方无关**。

- 使用者应自行确保其使用行为符合所在学校/单位的规定及当地法律法规
- 项目不收集、不上传任何用户数据；登录凭证仅保存在本机 SharedPreferences
- 作者不对因使用本项目产生的任何直接或间接损失负责
- 如有侵权，请联系删除

**请勿将本项目用于商业用途或对外提供服务。**

## License

GNU General Public License v3.0 or later — see [LICENSE](LICENSE).

---

## English

**FastWater** is a minimal Android client for campus self-service water equipment
(drinking fountains, shower controllers, shared washing machines).

The official apps for these devices are heavy: splash ads, feed recommendations,
promotional slots between you and the single button you actually need. This project
does one thing — **tap, water comes out**.

- ~45 KB, no ad SDKs, no third-party dependencies
- All HTTP calls and request signing happen in native Java (avoids WebView CORS
  and the missing `crypto.subtle` on `file://` pages)
- UI is plain HTML in a WebView, bridged to native via `@JavascriptInterface`

**Build** (no prebuilt APK is provided):

```bash
export ANDROID_HOME=/path/to/android-sdk
bash tools/build.sh
```

Requires JDK 17+, Android SDK build-tools, and Python 3 for a small dex-packing script.

**Note**: a few endpoints sign requests with latitude/longitude for risk control.
Set `LAT` / `LNG` in `MainActivity.java` to your actual location before use.

**NFC**: write either an AAR (`com.fastwater.ctrl`) alone, or a URI record
(`pqfast://dev?i=...`) followed by an AAR. The latter carries full parameters.

**Disclaimer**: for personal study and research only. Not affiliated with any
service operator. Do not use commercially or as a hosted service.
