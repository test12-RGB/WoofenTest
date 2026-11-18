#!/usr/bin/env python3
"""Woofen BUG 双向同步：飞书多维表格「BUG登记表」<-> GitHub Issues。

方向约定
- 内容（标题/描述/等级/责任人/版本…）：飞书 -> GitHub 覆盖
- 状态（BUG状态/信息标签、是否关闭、P 等级）：GitHub 优先
- 新增飞书记录：自动建 Issue；GitHub 改状态：回写飞书「测试回归验证结果 / 研发归属类 / BUG级别」

用法
    python3 tools/woofen_sync.py --dry-run   # 只打印将要做什么
    python3 tools/woofen_sync.py             # 真正执行一轮
"""

import argparse
import datetime
import hashlib
import json
import os
import re
import subprocess
import sys

BASE_TOKEN = "Oo7LbHcD0aPFDCsYqeCc4jHEnnb"
TABLE_ID = "tblIVSPELHJJidVJ"
REPO = "brainvue-tech/TestBug"
MASK_NAMES = True  # 仓库为公开，责任人脱敏；改为 False 可保留真实姓名

STATE_DIR = "/home/user/Doubao/chats/38454352490236674/.woofen-sync"
STATE_FILE = os.path.join(STATE_DIR, "state.json")
LOG_FILE = os.path.join(STATE_DIR, "sync.log")

LEVELS = ("P0", "P1", "P2", "P3")
PASS_VERIFY = ("验证PASS", "复测通过")

# 标签体系：BUG等级 / BUG状态 / BUG信息 / 问题归属
STATE_LABELS = ("开放", "已解决", "关闭")
INFO_LABELS = ("无法解决", "非问题", "重复问题")
OWNER_LABELS = ("前端", "后端", "服务端", "采集平台", "固件")
ALL_MANAGED_LABELS = LEVELS + STATE_LABELS + INFO_LABELS + OWNER_LABELS

# 飞书「问题归属类型」 -> 仓库「问题归属」标签
OWN_MAP = {"前端": "前端", "后端": "后端", "服务端": "服务端",
           "数据处理平台": "采集平台", "固件嵌入式": "固件"}

# 提报时的默认责任人（仅用于正文提示，不改飞书记录）
DEFAULT_OWNER = {"后端": "柴金星", "服务端": "李会会"}

# 信息标签 -> 飞书「研发归属类」
INFO_LABEL_TO_FEISHU = {
    "非问题": "非问题",
    "重复问题": "重复问题",
    "无法解决": "未修复-无法修复",
}


def decide_state(dev, verify):
    """飞书状态字段 -> (BUG状态, BUG信息)"""
    if "非问题" in dev or "非问题" in verify:
        return "关闭", "非问题"
    if "重复" in dev:
        return "关闭", "重复问题"
    if dev == "未修复-无法修复":
        return "关闭", "无法解决"
    info = None
    if any(p in verify for p in PASS_VERIFY):
        return "关闭", info
    if "已修复" in dev or verify == "待验证":
        return "已解决", info
    return "开放", info


# ---------------------------------------------------------------- 基础工具

def log(msg):
    line = f"[{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(LOG_FILE, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass


def run(cmd, check=True):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:4])}... failed: {(r.stderr or r.stdout)[:400]}")
    return r


def sha(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def today(v):
    if not v:
        return ""
    if isinstance(v, list):
        v = v[0] if v else ""
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", str(v))
    return m.group(0) if m else str(v)


def txt(v):
    if v is None:
        return ""
    if isinstance(v, list):
        return "、".join(str(x) for x in v)
    return str(v).strip()


def mask(v):
    names = [str(x) for x in (v or [])]
    if not MASK_NAMES:
        return "、".join(names)
    return "、".join((n[0] + "**") if len(n) >= 2 else n for n in names)


# ---------------------------------------------------------------- 内容构建

def build_issue(row):
    """飞书记录 -> (title, body, level_label, desired_state, state_reason)"""
    seq = txt(row.get("序号")) or "BUG"
    short = txt(row.get("简写问题")).strip()
    desc = txt(row.get("问题描述")).strip()
    if not short:
        first = next((x for x in desc.split("\n") if x.strip()), "未填写简写问题")
        short = first[:60]
    title = f"{seq} {short}"

    def r(k, v):
        return f"| {k} | {txt(v) or '—'} |"

    status, info_tag = decide_state(txt(row.get("研发归属类")), txt(row.get("测试回归验证结果")))
    info = "\n".join([
        "## 基本信息", "", "| 项目 | 内容 |", "| --- | --- |",
        r("BUG 序号", row.get("序号")),
        r("BUG 等级", row.get("BUG级别")),
        r("BUG 状态", status),
        r("BUG 信息", info_tag),
        r("问题归属", row.get("问题归属类型")),
        r("责任人（脱敏）", mask(row.get("责任人")) or (
            f"待指派（默认 {DEFAULT_OWNER[OWN_MAP[txt(row.get('问题归属类型'))]]}）"
            if OWN_MAP.get(txt(row.get('问题归属类型'))) in DEFAULT_OWNER else None)),
        r("提单日期", today(row.get("提单日期"))),
        r("解决日期", today(row.get("解决日期"))),
        r("提单版本", row.get("提单版本")),
        r("解决版本", row.get("解决版本")),
        r("回归版本", row.get("回归版本")),
        r("回归日期", today(row.get("回归日期"))),
        "",
        "### 附加信息", "", "| 项目 | 内容 |", "| --- | --- |",
        r("问题类型", row.get("问题类型")),
        r("APP 版本", row.get("APP版本")),
        r("固件版本", row.get("固件版本")),
        r("研发归属类", row.get("研发归属类")),
        r("测试回归验证结果", row.get("测试回归验证结果")),
    ])
    body = "\n".join([
        f"<!-- woofen-sync:{row['record_id']} -->",
        f"> 由飞书「BUG登记表」同步 ｜ 原记录 ID：`{row['record_id']}`",
        "", info, "",
        "## 问题描述", "", desc or "_（原表未填写）_", "",
        "## 日志摘要", "", txt(row.get("日志摘要")) or "_（无）_", "",
        "## 接口 / 网络分析", "", txt(row.get("接口/网络分析")) or "_（无）_", "",
        "## 截图 / 复现链接", "", txt(row.get("截图/复现链接")) or "_（无）_", "",
        "## 备注", "", txt(row.get("备注")) or "_（无）_", "",
        "---", "来源：Woofen BUG 登记表",
    ])

    level = txt(row.get("BUG级别"))
    dev = txt(row.get("研发归属类"))
    verify = txt(row.get("测试回归验证结果"))
    own = txt(row.get("问题归属类型"))

    status, info = decide_state(dev, verify)
    state, reason = "open", None
    if status == "关闭":
        state = "closed"
        reason = "not_planned" if info in ("非问题", "重复问题", "无法解决") else "completed"

    labels = ["bug"] + ([level] if level in LEVELS else [])
    labels.append(status)
    if info:
        labels.append(info)
    owner = OWN_MAP.get(own)
    if owner:
        labels.append(owner)
    return {"title": title, "body": body, "labels": labels,
            "level": level, "state": state, "state_reason": reason,
            "status": {"verify": verify, "dev": dev, "level": level, "own": own}}


# ---------------------------------------------------------------- 飞书读写

def _list_once():
    os.makedirs(STATE_DIR, exist_ok=True)
    out = os.path.join(STATE_DIR, "bitable.ndjson")
    man = os.path.join(STATE_DIR, "bitable-manifest.json")
    for f in (out, man):
        if os.path.exists(f):
            os.unlink(f)
    r = run(["lark-cli", "base", "+record-list", "--base-token", BASE_TOKEN,
             "--table-id", TABLE_ID, "--as", "user", "--output", out, "--overwrite"], check=False)
    if r.returncode != 0:
        raise RuntimeError(f"record-list failed: {(r.stderr or r.stdout)[:400]}")
    m = json.loads(r.stdout) if r.stdout.strip().startswith("{") else {}
    if "record_file" not in m:
        m = json.load(open(man)) if os.path.exists(man) else m
    path = m.get("record_file", out)
    rows = [json.loads(l) for l in open(path) if l.strip()]
    if m.get("has_more"):
        raise RuntimeError("记录超过单页上限，需要分页处理")
    return rows


def _record_get(rid):
    """单条精读：绕过 record-list 偶发的上一版本快照"""
    out = os.path.join(STATE_DIR, f"rec-{rid}.ndjson")
    man = os.path.join(STATE_DIR, f"rec-{rid}.json")
    for f in (out, man):
        if os.path.exists(f):
            os.unlink(f)
    r = run(["lark-cli", "base", "+record-get", "--base-token", BASE_TOKEN,
             "--table-id", TABLE_ID, "--record-id", rid, "--as", "user",
             "--output", out, "--overwrite"], check=False)
    path = out
    if r.returncode == 0 and r.stdout.strip():
        try:
            m = json.loads(r.stdout)
            if isinstance(m, dict) and "record_file" in m:
                path = m["record_file"]
        except Exception:
            pass
    lines = [l for l in open(path) if l.strip()] if os.path.exists(path) else []
    if not lines:
        return None
    row = json.loads(lines[0])
    return row.get("fields", row)


def fetch_rows():
    """读两遍，字段有出入的记录用 record-get 精读校正（飞书 list 偶发返回旧快照）"""
    a = _list_once()
    b = _list_once()
    key = lambda r: r["record_id"]
    ma = {key(r): r for r in a}
    mb = {key(r): r for r in b}
    fixed = 0
    for rid, ra in ma.items():
        rb = mb.get(rid)
        if rb is None:
            continue
        if json.dumps(ra, sort_keys=True, ensure_ascii=False) != json.dumps(rb, sort_keys=True, ensure_ascii=False):
            authoritative = _record_get(rid)
            if authoritative:
                row = dict(authoritative)
                row["record_id"] = rid
                ma[rid] = row
                fixed += 1
    if fixed:
        log(f"  ! {fixed} 条记录两次读取不一致，已用单条精读校正")
    return [ma[key(r)] for r in a]


def update_bitable_fields(record_id, fields, dry):
    payload = {"update_records": {record_id: fields}}
    if dry:
        log(f"  [dry] bitable update {record_id} <- {fields}")
        return True
    r = run(["lark-cli", "base", "+record-batch-update", "--base-token", BASE_TOKEN,
             "--table-id", TABLE_ID, "--as", "user", "--json", json.dumps(payload, ensure_ascii=False)],
            check=False)
    if r.returncode != 0:
        log(f"  !! bitable update failed {record_id}: {(r.stderr or r.stdout)[:200]}")
        return False
    return True


# ---------------------------------------------------------------- GitHub 读写

def fetch_issues():
    r = run(["gh", "api", "--paginate",
             f"repos/{REPO}/issues?state=all&per_page=100&sort=created&direction=asc",
             "--jq", ".[] | {number, title, state, body, updated_at, labels: [.labels[].name]}"])
    return [json.loads(l) for l in r.stdout.splitlines() if l.strip()]


def gh(*args, data=None):
    cmd = ["gh", "api"] + list(args)
    if data is not None:
        tmp = os.path.join(STATE_DIR, "payload.json")
        os.makedirs(STATE_DIR, exist_ok=True)
        open(tmp, "w").write(json.dumps(data, ensure_ascii=False))
        cmd += ["--input", tmp]
    r = run(cmd, check=False)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[:300])
    return json.loads(r.stdout) if r.stdout.strip() else {}


def set_labels(number, desired, current, dry):
    to_add = [l for l in desired if l not in current]
    to_drop = [l for l in current if l not in desired and l in ALL_MANAGED_LABELS]
    if dry:
        if to_add or to_drop:
            log(f"  [dry] labels #{number} +{to_add} -{to_drop}")
        return
    if to_add:
        gh("-X", "POST", f"repos/{REPO}/issues/{number}/labels", data={"labels": to_add})
    for l in to_drop:
        gh("-X", "DELETE", f"repos/{REPO}/issues/{number}/labels/{l}")


def patch_issue(number, payload, dry):
    if dry:
        log(f"  [dry] patch #{number}: {list(payload)}")
        return {}
    return gh("-X", "PATCH", f"repos/{REPO}/issues/{number}", data=payload)


def create_issue(payload, dry):
    if dry:
        log(f"  [dry] create issue: {payload['title']}")
        return {}
    return gh("-X", "POST", f"repos/{REPO}/issues", data=payload)


def gh_status_labels(issue):
    return sorted(l for l in issue["labels"] if l in STATE_LABELS + INFO_LABELS + OWNER_LABELS)


def bitable_fields_from_issue(issue, row):
    """GitHub 标签/开关 -> 飞书状态字段（研发在仓库上操作后自动回写）"""
    labels = set(issue["labels"])
    verify = txt(row.get("测试回归验证结果"))
    dev = txt(row.get("研发归属类"))
    out = {}

    info = next((l for l in INFO_LABELS if l in labels), None)
    status = next((l for l in STATE_LABELS if l in labels), None)

    # 1) BUG信息：非问题 / 重复问题 / 无法解决
    if info:
        target = INFO_LABEL_TO_FEISHU[info]
        if dev != target:
            out["研发归属类"] = [target]
        if info == "非问题":
            if verify != "非问题":
                out["测试回归验证结果"] = ["非问题"]
        elif info == "无法解决":
            if verify != "暂不处理":
                out["测试回归验证结果"] = ["暂不处理"]
        return out

    # 2) BUG状态
    if status == "关闭":
        if not any(p in verify for p in PASS_VERIFY):
            out["测试回归验证结果"] = ["验证PASS"]
        return out
    if status == "已解决":
        if not dev.startswith("已修复"):
            out["研发归属类"] = ["已修复-待验证"]
        if verify != "待验证":
            out["测试回归验证结果"] = ["待验证"]
        return out
    if status == "开放":
        if dev.startswith("已修复"):
            out["研发归属类"] = ["未修复-暂不处理"]
        if any(p in verify for p in PASS_VERIFY) or verify in ("非问题", "待验证"):
            out["测试回归验证结果"] = ["待修复"]
        return out

    # 3) 研发没打状态标签、直接关单：沿用「关闭即验证通过」的历史判定
    if issue["state"] == "closed":
        if any(p in verify for p in PASS_VERIFY):
            return out
        out["测试回归验证结果"] = ["验证PASS"]
        return out

    # 4) 未打标签且是开启状态：原本已验证通过/待验证的，退回待修复
    if any(p in verify for p in PASS_VERIFY) or verify in ("非问题", "待验证"):
        out["测试回归验证结果"] = ["待修复"]
    return out


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    dry = args.dry_run

    os.makedirs(STATE_DIR, exist_ok=True)
    import fcntl
    lock_fh = open(os.path.join(STATE_DIR, "sync.lock"), "w")
    try:
        fcntl.flock(lock_fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log("上一轮同步尚未结束，本轮跳过")
        return
    state = json.load(open(STATE_FILE)) if os.path.exists(STATE_FILE) else {"records": {}}

    rows = fetch_rows()
    issues = fetch_issues()
    by_marker = {}
    for i in issues:
        m = re.search(r"woofen-sync:(rec\w+)", i.get("body") or "")
        if m:
            by_marker[m.group(1)] = i
    log(f"飞书 {len(rows)} 条 / GitHub {len(issues)} 个 Issue / 状态文件 {len(state['records'])} 条映射")

    created = updated = pushed = 0
    for row in rows:
        rid = row["record_id"]
        built = build_issue(row)
        content_hash = sha({k: built[k] for k in ("title", "body", "labels")})
        issue = by_marker.get(rid)
        entry = state["records"].get(rid)

        # 1) 新记录 -> 建 Issue
        if issue is None:
            if entry and entry.get("issue"):
                log(f"  !! {built['title']}: Issue 已不存在，跳过（原 #{entry['issue']}）")
                continue
            log(f"  + 新建 Issue: {built['title']}")
            resp = create_issue({k: built[k] for k in ("title", "body", "labels")}, dry)
            if dry:
                continue
            num = resp.get("number")
            if built["state"] == "closed":
                patch_issue(num, {"state": "closed", "state_reason": built["state_reason"] or "completed"}, dry)
            state["records"][rid] = {
                "issue": num,
                "bitable_hash": content_hash,
                "bitable_status": built["status"],
                "gh_state": built["state"], "gh_labels": sorted(built["labels"]),
                "gh_labels_status": sorted(l for l in built["labels"] if l in STATE_LABELS + INFO_LABELS + OWNER_LABELS),
                "issue_updated_at": resp.get("updated_at"),
            }
            created += 1
            continue

        # 2) 已有 Issue：对齐映射
        if not entry:
            entry = state["records"][rid] = {
                "issue": issue["number"], "bitable_hash": content_hash,
                "bitable_status": built["status"], "gh_state": issue["state"],
                "gh_labels": sorted(issue["labels"]), "gh_labels_status": gh_status_labels(issue),
                "issue_updated_at": issue["updated_at"],
            }
            log(f"  = 收编既有 Issue #{issue['number']} ({built['title']})")
            # 无状态文件时也做一次权威状态对齐：GitHub 已关闭/已标记的，回写飞书
            seed_fields = bitable_fields_from_issue(issue, row)
            seed_fields = {k: v for k, v in seed_fields.items() if txt(row.get(k)) != txt(v)}
            if issue["state"] == "closed" or any(l in issue["labels"] for l in STATE_LABELS):
                if seed_fields:
                    log(f"  => 收编时对齐状态 -> 飞书 {rid}: {seed_fields}")
                    if update_bitable_fields(rid, seed_fields, dry):
                        row = dict(row); row.update(seed_fields)
                        built = build_issue(row)
                        content_hash = sha({k: built[k] for k in ("title", "body", "labels")})
                        entry["bitable_status"] = built["status"]
                        entry["bitable_hash"] = content_hash
                        pushed += 1
        entry["issue"] = issue["number"]

        cur_state, cur_labels = issue["state"], list(issue["labels"])

        # 3) 内容同步：飞书 -> GitHub
        if content_hash != entry.get("bitable_hash"):
            log(f"  ~ 内容变更 -> 更新 #{issue['number']}: {built['title']}")
            patch_issue(issue["number"], {"title": built["title"], "body": built["body"]}, dry)
            set_labels(issue["number"], built["labels"], cur_labels, dry)
            cur_labels = list(built["labels"])
            updated += 1

        # 4) 状态同步（GitHub 优先，飞书变动次之）
        gh_changed = (issue["state"] != entry.get("gh_state")
                      or gh_status_labels(issue) != entry.get("gh_labels_status", []))
        bt_changed = built["status"] != entry.get("bitable_status")

        cur_hash, cur_status = content_hash, built["status"]

        if gh_changed:
            fields = bitable_fields_from_issue(issue, row)
            lvl = next((l for l in issue["labels"] if l in LEVELS), None)
            if lvl and lvl != built["level"]:
                fields["BUG级别"] = [lvl]
            # 只写与飞书现值不同的字段，避免无谓改动
            fields = {k: v for k, v in fields.items() if txt(row.get(k)) != txt(v)}
            if fields:
                log(f"  => GitHub 状态变更 -> 回写飞书 {rid}: {fields}")
                if update_bitable_fields(rid, fields, dry):
                    row2 = dict(row)
                    row2.update(fields)
                    b2 = build_issue(row2)
                    cur_status = b2["status"]
                    cur_hash = sha({k: b2[k] for k in ("title", "body", "labels")})
                    pushed += 1
            cur_state = issue["state"]
            cur_labels = list(issue["labels"])
        elif bt_changed:
            log(f"  => 飞书状态变更 -> 应用到 #{issue['number']}: {built['state']} / {built['labels']}")
            payload = {}
            if issue["state"] != built["state"]:
                payload["state"] = built["state"]
                if built["state"] == "closed":
                    payload["state_reason"] = built["state_reason"] or "completed"
            resp = patch_issue(issue["number"], payload, dry) if payload else {}
            set_labels(issue["number"], built["labels"], cur_labels, dry)
            cur_state = built["state"]
            cur_labels = list(built["labels"])

        # 5) 更新快照（用本轮结束后的真实状态，避免下一轮误判）
        if not dry:
            entry["bitable_hash"] = cur_hash
            entry["bitable_status"] = cur_status
            entry["gh_state"] = cur_state
            entry["gh_labels"] = sorted(cur_labels)
            entry["gh_labels_status"] = sorted(l for l in cur_labels if l in STATE_LABELS + INFO_LABELS + OWNER_LABELS)
            entry["issue_updated_at"] = issue["updated_at"]

    if not dry:
        tmp = STATE_FILE + ".tmp"
        json.dump(state, open(tmp, "w"), ensure_ascii=False, indent=1)
        os.replace(tmp, STATE_FILE)
    log(f"完成：新建 {created} / 内容更新 {updated} / 状态回写飞书 {pushed}")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log(f"FATAL {e}")
        sys.exit(1)
