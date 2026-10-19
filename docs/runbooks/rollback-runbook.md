# Rollback production (fast-track) — runbook cho owner

P56 (D65), 2026-10-19. Script: `infra/scripts/rollback-release.sh`.
Workflow: `.github/workflows/rollback.yml`. Mô phỏng (không cần production):
`tests/unit/test_rollback_release_simulation.py`.

> **Nguyên tắc.** Rollback chỉ đổi **code đang chạy**: API, Demo và Landing cùng lúc,
> cộng Celery worker + beat. Nó **không bao giờ đụng database** (không migrate, không
> downgrade, không restore). Không build lại gì: nó chạy lại một release cũ vẫn còn
> trong `~/releases/`.

## 1. Production thật sự trông thế nào

| Lane | Hai slot (loopback) | Process đang phục vụ | Nginx include (nguồn sự thật) | Symlink |
|---|---|---|---|---|
| api | 8000 / 8020 | `juli-api-candidate-<port>` (transient) | `/etc/nginx/juli/api-upstream.conf` | `~/releases/current` |
| demo | 3001 / 3021 | `juli-demo-candidate-<port>` (transient) | `/etc/nginx/juli/demo-upstream.conf` | `~/releases/demo-current` |
| landing | 3007 / 3027 | `juli-landing-candidate-<port>` (transient) | `/etc/nginx/juli/landing-upstream.conf` | `~/releases/landing-current` |
| worker | — | `juli-celery-worker.service` | — | chạy từ `~/releases/current` |
| beat | — | `juli-celery-beat.service` | — | chạy từ `~/releases/current` |

- Health: API `GET /health` → JSON `status: "ok"` (+ shape của `/v1/demo/analytics`);
  Demo `GET /decisions` 2xx; Landing `GET /` 2xx (+ kiểm tra CSS/JS thật). Public:
  `https://api.app-juli.com/health`, `https://demo.app-juli.com/decisions`,
  `https://app-juli.com/`.
- Các unit "bền" `juli-api` / `juli-demo` / `juli-landing` chỉ dùng **khi reboot**
  (chúng đọc port live từ `/etc/juli/<lane>-runtime.env`). Sau mỗi deploy `juli-api`
  bị **dừng có chủ ý**, nên `systemctl is-active juli-api` = inactive là bình thường.
- `juli-web` (dashboard cũ, :3000) đã nghỉ hẳn: không còn unit, không còn secret.
- Timer: `juli-secrets-refresh` (hằng ngày), `juli-restore-drill` (CN 03:00),
  `juli-cloudflare-ip-refresh` (mỗi giờ). Rollback không đụng các timer.

**Release là gì.** `~/releases/<short-sha>/` là một git worktree dùng chung cho cả ba
lane. Một deploy chỉ build lane nào có file đổi, nên thư mục release có:
`.venv/bin/uvicorn` nếu lane API chạy; `apps/demo/node_modules/.bin/next` nếu lane Demo
chạy (tarball `DEMO_ARTIFACT_TARBALL`); `apps/landing/node_modules/.bin/next` nếu lane
Landing chạy (`LANDING_ARTIFACT_TARBALL`). Sau mỗi deploy thành công,
`~/releases/deploy-history.log` có thêm dòng `<utc> <sha> <dir>`. Mỗi deploy giữ lại 3
release gần nhất + những release đang live (`infra/scripts/lib/prune-releases.sh`).

**"Release trước" nghĩa là gì.** Là *trạng thái ngay sau deploy trước đó*, cho cả ba
lane: với mỗi lane, script lấy release mới nhất (tính đến deploy đó) có artifact của
lane đó. Ví dụ deploy B chỉ đổi Demo: quay về B nghĩa là Demo của B, còn API và Landing
như sau B (tức là của A). Nếu trên đường dò có một release đã bị prune, script **dừng
và không đổi gì** thay vì đoán.

Mặc định (không truyền target) = deploy *trước* cái đang live, bỏ qua release nào đã
từng bị rollback bỏ đi (ví dụ A, B, C, rollback về B, rồi deploy D: mặc định từ D là B,
không phải C). Chạy lại lần nữa thì lùi thêm một deploy. Muốn đi tới lại thì truyền SHA
mới hơn (roll forward cũng là cùng một thao tác; nó xoá dấu "bị bỏ" của release đó).

## 2. Cách rollback

Luôn chạy **plan** trước: nó in lane nào đi từ đâu tới đâu, migration nào code cũ
không biết, và không đổi gì.

**Cách A — tag (không cần quyền dispatch, chạy được khi `main` đang đóng băng):**

```bash
git fetch origin
# 1. Xem plan (không đổi gì)
git tag fasttrack-rollback-plan-$(date -u +%Y%m%dT%H%MZ) origin/fasttrack/optimize-product
git push origin <tag-vừa-tạo>
# 2. Rollback về deploy trước
git tag fasttrack-rollback-$(date -u +%Y%m%dT%H%MZ) origin/fasttrack/optimize-product
git push origin <tag-vừa-tạo>
# hoặc tới một deploy cụ thể (SHA 7–40 ký tự, hoặc tên tag fasttrack-deploy-*)
git tag fasttrack-rollback-$(date -u +%Y%m%dT%H%MZ)-to-<sha-hoặc-fasttrack-deploy-tag> origin/fasttrack/optimize-product
```

Tag phải nằm trên một commit của `fasttrack/optimize-product` (workflow tự kiểm tra).

**Cách B — dispatch:**

```bash
gh workflow run rollback.yml --ref fasttrack/optimize-product -f action=plan
gh workflow run rollback.yml --ref fasttrack/optimize-product -f action=rollback [-f target_sha=<sha>]
gh workflow run rollback.yml --ref fasttrack/optimize-product -f action=verify
```

> **Không bao giờ** chọn ref `main` (kể cả trên giao diện "Use workflow from"): bản
> `rollback.yml` trên `main` là bản cũ — nó `git checkout main` trong clone production
> và restart `juli-web`.

**Cách C — trực tiếp trên VPS (owner SSH, root):**

```bash
cd ~/Juli-AI-v2
./infra/scripts/rollback-release.sh --plan          # không đổi gì
./infra/scripts/rollback-release.sh                 # về deploy trước
./infra/scripts/rollback-release.sh <sha>           # về (hoặc tới) một deploy cụ thể
./infra/scripts/rollback-release.sh --verify        # chỉ kiểm tra sức khoẻ
```

Đừng chạy cách C khi một deploy hoặc rollback khác đang chạy trên GitHub (workflow
dùng chung concurrency group `release-refs/heads/main` nên chúng không chồng nhau,
nhưng SSH tay thì không được bảo vệ).

**Script làm gì, theo thứ tự.** Khi lùi: landing → demo → api (frontend cũ chạy trên API
mới, vốn chỉ thêm, không bớt). Khi tiến: api → demo → landing (như deploy). Với từng lane:
khởi động release đích trên slot còn trống → chờ loopback trả lời (API: `/health` +
shape; Landing: HTML + CSS/JS thật) → đổi nginx include + `reload` (không restart) →
ghi `<lane>-runtime.env` và cài unit file **của release đích** → đổi symlink → kiểm tra
public. Nếu public check hỏng, nó tự trả traffic về slot cũ (nếu process cũ còn trả
lời). API xong thì cài unit Celery của release đích, restart worker + beat và kiểm tra
worker đã subscribe đủ queue.

Lane đầu tiên hỏng → dừng. Mỗi lane hoặc đã sang đích hẳn, hoặc vẫn nguyên chỗ cũ; bảng
tổng kết ghi rõ lane nào đã đi. Bản ghi: `~/releases/records/rollback-<utc>-<short>.json`;
`deploy-history.log` có thêm dòng `ROLLBACK-TO <dir> <sha> lanes=...`.

Thời gian ước tính: 1–3 phút (không build; mỗi lane chờ process mới sẵn sàng vài giây
tới vài chục giây; Celery restart ~10–20 s).

## 3. Kiểm tra sau rollback

Cuối mỗi lần chạy (và với `--verify`) script in bảng:

```
  api      127.0.0.1:8000/health          PASS  status=ok
  demo     127.0.0.1:3001/decisions       PASS  HTTP 200
  landing  127.0.0.1:3007/                PASS  HTTP 200
  juli-celery-worker                      PASS  active
  juli-celery-beat                        PASS  active
  public   https://api.app-juli.com/health   PASS  HTTP 200
  ...
RESULT: PASS (8 checks)
```

Thêm `ROLLBACK_CELERY_PING=1` (cách C) để có thêm `celery inspect ping`. Job
`public-check` của workflow kiểm tra lại ba URL public từ bên ngoài VPS. Tự kiểm tra
thêm: mở `https://app-juli.com/`, `https://demo.app-juli.com/decisions`; trên VPS
`journalctl -u juli-celery-worker -n 50` không có `Received unregistered task`.

## 4. Khi rollback thất bại

- **Nothing moved** (hỏng ngay ở lane đầu): production y như trước. Đọc lỗi trong log,
  sửa, chạy lại.
- **Một phần đã đi** (ví dụ landing + demo đã về B, api hỏng): mọi lane vẫn khoẻ; chọn
  một trong hai: chạy lại rollback sau khi sửa, hoặc đi tới lại bằng
  `rollback-release.sh <sha-đang-live-trước-đó>` (script in sẵn lệnh này).
- **Đảo ngược nhanh nhất một lane** vừa đổi (process cũ vẫn chạy trên slot kia):
  `cp -p /etc/nginx/juli/<lane>-upstream.conf.prev /etc/nginx/juli/<lane>-upstream.conf && nginx -t && systemctl reload nginx`
  (rồi sửa symlink `~/releases/<lane>-current` cho khớp).

## 5. Database và migration

Rollback **không** đụng database. Migration chỉ đi tới (forward-only) và bị gate
"additive-only" (#834), nên code cũ vẫn chạy được trên schema mới. `--plan` in
`WARN: the database schema stays ahead of the target's code by: <file>` nếu deploy bị
lùi đã thêm migration.

Nếu sau rollback code cũ **không** chạy được với schema mới (hiếm; gate không bắt được
mọi thứ): đây là **quyết định riêng của owner**, không có gì tự động:

1. Ưu tiên **đi tới** một bản sửa (deploy mới), không động vào dữ liệu.
2. Chỉ khi buộc phải: restore bản dump đã verify trước deploy
   `~/backups/juli-pre-migrate-<utc>-fasttrack-<short>.dump` (job `backup` của
   `fasttrack-deploy.yml` tạo; có file `.sha256` bên cạnh; log job in sẵn lệnh restore).
   Restore **mất mọi ghi dữ liệu từ lúc dump** (đơn, credential mới, ingest...). Trước
   khi restore: dừng worker + beat, kiểm tra `sha256sum -c`, ghi lại thời điểm; sau đó
   chạy rollback để code khớp với schema đã restore. Ghi quyết định vào
   `fasttrack/LOG.md`.

## 6. Diễn tập trực tiếp một lần (owner chạy, giờ vắng)

Mục tiêu: chứng minh trên production rằng lùi về deploy trước rồi đi tới lại đều PASS.
Chưa ai chạy bước này; agent không chạy.

**Chuẩn bị (5 phút)**
1. Chọn giờ vắng; không có deploy nào đang chạy (`gh run list --workflow fasttrack-deploy.yml -L 3`).
2. Ghi lại SHA đang live: `cd ~/Juli-AI-v2 && tail -3 ~/releases/deploy-history.log`
   và `readlink -f ~/releases/{current,demo-current,landing-current}`.
3. `./infra/scripts/rollback-release.sh --verify` → phải `RESULT: PASS`. Nếu FAIL thì
   dừng, sửa trước.
4. `./infra/scripts/rollback-release.sh --plan` → đọc kỹ: target là deploy nào, lane
   nào đổi, có `WARN` migration không. **Nếu có WARN migration, chọn ngày khác** (hoặc
   chấp nhận sau khi đọc mục 5). Nên chọn lúc deploy trước và deploy hiện tại khác nhau
   ít ở backend: worker cũ không biết task mới thì sẽ log `Received unregistered task`
   và bỏ message đó.

**Lùi (2–3 phút)**
5. Chạy `./infra/scripts/rollback-release.sh` (hoặc tag `fasttrack-rollback-<utc>`).
6. Phải thấy `RESULT: PASS`. Mở 3 URL public trên trình duyệt. `tail -2
   ~/releases/deploy-history.log` có dòng `ROLLBACK-TO`.
7. Để chạy 5–10 phút; xem `journalctl -u juli-celery-worker -n 100 --no-pager`.

**Đi tới lại (2–3 phút)**
8. `./infra/scripts/rollback-release.sh <sha-đã-ghi-ở-bước-2>` (hoặc tag
   `fasttrack-rollback-<utc>-to-<sha>`). Plan in `forward: api -> demo -> landing`.
9. `RESULT: PASS`; `readlink -f` ba symlink trùng với bước 2.
10. `./infra/scripts/rollback-release.sh --verify` lần cuối.

**Huỷ giữa chừng** nếu một bước FAIL: production luôn ở trạng thái "mỗi lane khoẻ" (xem
mục 4); đi tới lại bằng bước 8. Ghi kết quả (thời gian từng bước, PASS/FAIL, bất thường)
vào `fasttrack/LOG.md` dưới P56.

## 7. Việc một lần của owner sau khi merge P56

1. Merge `fasttrack/rollback-fix` vào `fasttrack/optimize-product`, rồi deploy như
   thường (tag `fasttrack-deploy-*`). P56 chỉ đổi script/workflow/test/docs: deploy chỉ
   chuyển clone `~/Juli-AI-v2` sang SHA mới ("no deployable changed" là bình thường).
2. Trên VPS: `grep -c ROLLBACK_INTERFACE=2 ~/Juli-AI-v2/infra/scripts/rollback-release.sh`
   → 1, rồi `--verify` → PASS.
3. Dọn `juli-web` trên VPS (đã disabled + inactive):
   `systemctl disable --now juli-web; rm -f /etc/systemd/system/juli-web.service; systemctl daemon-reload; rm -f /etc/juli/web.env`.
4. **Chỉ sau bước 1**: xoá secret AWS `juli/web/production` (region us-east-2), và bỏ
   ARN của nó khỏi IAM policy thật của `juli-vps-secrets-reader` (file mẫu
   `infra/scripts/aws/iam-policy-secrets-reader.json` đã bỏ). Lý do thứ tự:
   `fetch-secrets.sh` cũ `exit 1` khi thiếu secret này, mà nó là `ExecStartPre` của
   `juli-api` và hai unit Celery — xoá sớm thì lần restart/reboot sau các unit đó không
   lên. Lưu ý thêm: `main` (đang đóng băng) vẫn giữ `fetch-secrets.sh` cũ; đừng deploy
   `main` lên VPS cho tới khi fast-track merge về.
5. Diễn tập mục 6 vào một giờ vắng.

## 8. Chạy mô phỏng trên máy (không cần production)

```bash
PYTHONPATH=backend/src python -m pytest tests/unit/test_rollback_release_simulation.py \
  tests/unit/test_rollback_workflow.py -q -p no:cacheprovider
```

Mô phỏng chạy đúng `rollback-release.sh` (kèm `deploy.sh`, `rollback-demo-release.sh`,
`verify-release-assets.sh` thật) trên một pool release giả với systemctl / systemd-run /
journalctl / nginx / curl giả (`tests/support/rollback_sim_stub.py`): rollback thành
công, đi tới lại, plan, release bị prune, target hỏng ở từng lane, nginx từ chối, public
check hỏng (tự đảo ngược), worker thiếu queue, beat không restart được, `--verify`; và
khẳng định không lệnh database nào và không `juli-web` nào được gọi.
