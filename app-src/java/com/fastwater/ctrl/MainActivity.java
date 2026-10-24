package com.fastwater.ctrl;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.content.SharedPreferences;
import android.graphics.Color;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.webkit.JavascriptInterface;
import android.webkit.WebChromeClient;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.Toast;

import org.json.JSONObject;

import java.io.BufferedReader;
import java.io.InputStream;
import java.io.InputStreamReader;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.MessageDigest;

/**
 * 极速水控 —— 直连业务接口的净化版客户端
 * 全部请求在原生层完成：无广告 SDK、无 WebView 跨域限制、无 secure-context 限制
 */
public class MainActivity extends Activity {

    private static final String BASE = "https://userapi.qiekj.com";
    private static final String VER = "1.139.0";
    private static final String SECRET = "nFU9pbG8YQoAe1kFh+E7eyrdlSLglwEJeA0wwHB1j5o=";
    private static final String LAT = "0.0";   // TODO 改成你所在位置的纬度
    private static final String LNG = "0.0";   // TODO 改成你所在位置的经度

    private WebView web;
    private SharedPreferences sp;
    private static final int REQ_SCAN = 1001;
    private String deepLink;
    private boolean isCold = true;

    @SuppressLint("SetJavaScriptEnabled")
    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        sp = getSharedPreferences("pq", MODE_PRIVATE);
        isCold = (savedInstanceState == null);

        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#F7F8FA"));
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setDatabaseEnabled(true);
        s.setAllowFileAccess(true);
        s.setAllowContentAccess(true);
        s.setLoadWithOverviewMode(true);
        s.setUseWideViewPort(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);

        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient() {
            @Override
            public boolean onConsoleMessage(android.webkit.ConsoleMessage cm) {
                android.util.Log.d("PQWEB", cm.message() + " @" + cm.lineNumber());
                return true;
            }

            /** 摄像头等权限，直接授予 WebView（扫码要用） */
            @Override
            public void onPermissionRequest(final android.webkit.PermissionRequest request) {
                runOnUiThread(new Runnable() {
                    public void run() {
                        try {
                            request.grant(request.getResources());
                        } catch (Exception ignored) {
                        }
                    }
                });
            }
        });
        web.addJavascriptInterface(new Bridge(), "PQ");

        setContentView(web);

        // NFC 标签深链：pqfast://dev?i=<goodsId>&c=<cat>&s=<shopId>&n=<name>
        // 通过 JS Bridge 提供，避免 file:// 加载时丢失 query
        deepLink = (getIntent() != null) ? getIntent().getDataString() : null;
        web.loadUrl("file:///android_asset/index.html");

        // 摄像头权限（扫码用）
        if (Build.VERSION.SDK_INT >= 23
                && checkSelfPermission(android.Manifest.permission.CAMERA)
                != android.content.pm.PackageManager.PERMISSION_GRANTED) {
            requestPermissions(new String[]{android.Manifest.permission.CAMERA}, 1);
        }
    }

    @Override
    public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }

    /**
     * 已在运行时再碰一次标签：直接让页面切换设备
     */
    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);
        setIntent(intent);
        if (intent != null && intent.getDataString() != null && web != null) {
            web.evaluateJavascript(
                    "handleDeepLink(" + JSONObject.quote(intent.getDataString()) + ")", null);
        }
    }

    /**
     * 调官方 App 的扫码页（华为 ScanKit），forResult 模式直接返回二维码原文。
     * 注：官方该 Activity 未导出，普通应用无法调用，保留此逻辑仅作兜底。
     */
    @Override
    protected void onActivityResult(int requestCode, int resultCode, Intent data) {
        super.onActivityResult(requestCode, resultCode, data);
        if (requestCode == REQ_SCAN) {
            String v = (resultCode == RESULT_OK && data != null)
                    ? data.getStringExtra("data") : "";
            if (web != null) {
                web.evaluateJavascript("onScanResult(" + JSONObject.quote(v == null ? "" : v) + ")",
                        null);
            }
        }
    }

    // ---------------- 工具 ----------------
    private static String sha256(String str) {
        try {
            MessageDigest md = MessageDigest.getInstance("SHA-256");
            byte[] b = md.digest(str.getBytes("UTF-8"));
            StringBuilder sb = new StringBuilder(b.length * 2);
            for (byte x : b) {
                String h = Integer.toHexString(x & 0xff);
                if (h.length() == 1) sb.append('0');
                sb.append(h);
            }
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private static String read(InputStream is) {
        if (is == null) return "";
        try {
            BufferedReader br = new BufferedReader(new InputStreamReader(is, "UTF-8"));
            StringBuilder sb = new StringBuilder();
            String line;
            while ((line = br.readLine()) != null) sb.append(line);
            br.close();
            return sb.toString();
        } catch (Exception e) {
            return "";
        }
    }

    private void toast(final String msg) {
        runOnUiThread(new Runnable() {
            public void run() {
                Toast.makeText(MainActivity.this, msg, Toast.LENGTH_SHORT).show();
            }
        });
    }

    // ---------------- JS 桥 ----------------
    public class Bridge {

        @JavascriptInterface
        public String getToken() {
            return sp.getString("token", "");
        }

        /** NFC 深链（碰标签打开时的 URI），没有则返回空串 */
        @JavascriptInterface
        public String getDeepLink() {
            String d = deepLink;
            deepLink = null;   // 只消费一次
            return d == null ? "" : d;
        }

        /** 是否冷启动（点图标或 AAR 标签都会是 true） */
        @JavascriptInterface
        public boolean isColdStart() {
            return isCold;
        }

        @JavascriptInterface
        public void setToken(String t) {
            sp.edit().putString("token", t == null ? "" : t.trim()).apply();
        }

        @JavascriptInterface
        public String getMeta() {
            JSONObject o = new JSONObject();
            try {
                android.content.pm.PackageInfo pi =
                        getPackageManager().getPackageInfo(getPackageName(), 0);
                o.put("version", pi.versionName);
                o.put("code", pi.versionCode);
                o.put("brand", Build.BRAND);
                o.put("model", Build.MODEL);
                o.put("sdk", Build.VERSION.SDK_INT);
            } catch (Exception ignored) {
            }
            return o.toString();
        }

        /**
         * 统一请求入口
         *
         * @param path 形如 /user/info
         * @param body form 体，可空
         * @param cat  风控 categoryCode，空则不加风控头
         * @param imei  风控 imei
         */
        @JavascriptInterface
        public String call(String path, String body, String cat, String imei) {
            HttpURLConnection conn = null;
            try {
                final String token = sp.getString("token", "");
                final String ts = String.valueOf(System.currentTimeMillis());

                String form = body == null ? "" : body;
                if (!token.isEmpty()) {
                    form = form.isEmpty() ? ("token=" + token) : (form + "&token=" + token);
                }

                conn = (HttpURLConnection) new URL(BASE + path).openConnection();
                conn.setRequestMethod("POST");
                conn.setConnectTimeout(15000);
                conn.setReadTimeout(25000);
                conn.setDoOutput(true);
                conn.setUseCaches(false);

                conn.setRequestProperty("Authorization", token);
                conn.setRequestProperty("Version", VER);
                conn.setRequestProperty("channel", "android_app");
                conn.setRequestProperty("phoneBrand", Build.BRAND);
                conn.setRequestProperty("deviceId", "");
                conn.setRequestProperty("timestamp", ts);
                conn.setRequestProperty("sign", sha256("appSecret=" + SECRET
                        + "&channel=android_app&timestamp=" + ts
                        + "&token=" + token + "&version=" + VER + "&" + path));
                conn.setRequestProperty("User-Agent", "QEUser/" + VER
                        + " (com.qiekj.user; build:234; Android 9; userChannel:android_app; version:"
                        + VER + ") OkHttp/4.12.0");
                conn.setRequestProperty("Content-Type",
                        "application/x-www-form-urlencoded;charset=UTF-8");

                if (cat != null && cat.length() > 0) {
                    String im = imei == null ? "" : imei;
                    conn.setRequestProperty("categoryCode", cat);
                    conn.setRequestProperty("imei", im);
                    conn.setRequestProperty("lat", LAT);
                    conn.setRequestProperty("lng", LNG);
                    conn.setRequestProperty("orderRiskSign", sha256(
                            "appSecret=" + SECRET + "&categoryCode=" + cat
                                    + "&channel=android_app&imei=" + im
                                    + "&lat=" + LAT + "&lng=" + LNG
                                    + "&timestamp=" + ts + "&token=" + token
                                    + "&version=" + VER + "&" + path));
                    conn.setRequestProperty("orderRiskTimestamp", ts);
                }

                OutputStream os = conn.getOutputStream();
                os.write(form.getBytes("UTF-8"));
                os.flush();
                os.close();

                int code = conn.getResponseCode();
                String resp = read(code >= 400 ? conn.getErrorStream() : conn.getInputStream());
                if (resp == null || resp.isEmpty()) {
                    resp = "{\"code\":-1,\"msg\":\"空响应 HTTP " + code + "\"}";
                }
                return resp;
            } catch (Exception e) {
                String msg = e.toString().replace("\\", "\\\\").replace("\"", "'");
                return "{\"code\":-1,\"msg\":\"网络异常: " + msg + "\"}";
            } finally {
                if (conn != null) conn.disconnect();
            }
        }

        /** 打开外部链接（支付宝、网页） */
        @JavascriptInterface
        public void openUrl(final String url) {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        startActivity(new Intent(Intent.ACTION_VIEW, Uri.parse(url)));
                    } catch (Exception e) {
                        toast("无法打开该链接");
                    }
                }
            });
        }

        /** 调起扫码（借用官方 App 的扫码页，结果通过 onScanResult 回传） */
        @JavascriptInterface
        public void scanCode() {
            runOnUiThread(new Runnable() {
                public void run() {
                    try {
                        Intent i = new Intent();
                        i.setClassName("com.qiekj.user",
                                "com.qiekj.user.ui.activity.scan.HomeScanCodeAct");
                        i.putExtra("forResult", true);
                        startActivityForResult(i, REQ_SCAN);
                    } catch (Exception e) {
                        toast("没装官方 App，无法调起扫码");
                        if (web != null) {
                            web.evaluateJavascript("onScanResult('')", null);
                        }
                    }
                }
            });
        }

        @JavascriptInterface
        public void toast(String msg) {
            MainActivity.this.toast(msg);
        }

        @JavascriptInterface
        public void vibrate(int ms) {
            try {
                android.os.Vibrator v = (android.os.Vibrator) getSystemService(VIBRATOR_SERVICE);
                if (v != null) v.vibrate(ms);
            } catch (Exception ignored) {
            }
        }
    }
}
