在 **Ubuntu 服务器上修改**，位置就是你现在已经在用的 Nginx 站点配置目录里（你之前已经改过 `/etc/nginx/sites-available/...` 那套）。

下面给你一套**最稳、最不容易踩坑**的做法：把 `api-go.sailorvoyage.top` 作为**统一入口**，80/443 对外，8000/8001 只走本机 `127.0.0.1`。

---

# 1) 修改哪个文件？

你已经做过这一步：

```bash
sudo ln -s /etc/nginx/sites-available/api-go.sailorvoyage.top /etc/nginx/sites-enabled/
```

所以你要改的就是：

✅ **`/etc/nginx/sites-available/api-go.sailorvoyage.top`**

（改完不需要动 sites-enabled，除非你之前没启用。）

---

# 2) 建议的最终 Nginx 配置（UI + API 一起对外）

打开文件：

```bash
sudo nano /etc/nginx/sites-available/api-go.sailorvoyage.top
```

把内容替换成下面这份（直接复制粘贴）：

```nginx
server {
    listen 80;
    listen [::]:80;

    server_name api-go.sailorvoyage.top;

    # ---- Web UI (KaTrain Web UI on :8001) ----
    location / {
        proxy_pass http://127.0.0.1:8001;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ---- KataGo API (FastAPI on :8000) ----
    # 统一挂到 /api/ 下，避免和前端路由冲突
    location ^~ /api/ {
        proxy_pass http://127.0.0.1:8000/;
        proxy_http_version 1.1;

        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
    }
}
```

> 解释一句：
>
> * `/` 交给 8001（你的 Web UI）
> * `/api/*` 交给 8000（KataGo FastAPI）
>   这样浏览器访问同域名，不会有 CORS，最省事。

---

# 3) 让配置生效（必做）

检查语法：

```bash
sudo nginx -t
```

生效：

```bash
sudo systemctl reload nginx
```

---

# 4) 验证（从服务器本机先测）

```bash
curl -v http://127.0.0.1/
curl -v http://127.0.0.1/api/docs
curl -v http://127.0.0.1/api/health
```

* `/` 应该返回你 UI 的 HTML
* `/api/docs` 应该返回 FastAPI Swagger HTML
* `/api/health` 应该返回 OK JSON

---

# 5) 验证（从外网测）

```bash
curl -v http://api-go.sailorvoyage.top/
curl -v http://api-go.sailorvoyage.top/api/health
curl -v http://api-go.sailorvoyage.top/api/docs
```

---

# 6) 强烈建议：把 8000/8001 改成只监听本机（安全 + 避免 IPv6 差异）

因为你现在暴露端口访问会受到 IPv6/IPv4、路由器、用户网络影响，也不安全。

目标是：让 `ss` 里只看到：

* `127.0.0.1:8000`
* `127.0.0.1:8001`

做法取决于你怎么启动 uvicorn，例如：

```bash
uvicorn app:app --host 127.0.0.1 --port 8000
uvicorn ui:app  --host 127.0.0.1 --port 8001
```

---

## 你可能会遇到一个前端路由问题（提前告诉你）

你 8001 看起来是 Vite/React SPA。SPA 常见问题是：

* 直接访问 `/some/route` 会 404

如果遇到这种情况，需要在 Nginx 加 try_files 或让 8001 自己处理 fallback。你先不用管，等你 UI 真有路由再补。

---

如果你把 **`/etc/nginx/sites-available/api-go.sailorvoyage.top` 当前内容**贴出来，我也可以帮你“最小改动”地合并进去，避免覆盖你之前已有的配置。
