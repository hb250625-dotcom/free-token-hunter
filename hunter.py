#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Free Token Hunter — 免费 token / 云额度渠道汇总与领取引导工具

零第三方依赖，仅用 Python 标准库。

用法示例：
    python hunter.py list                      # 列出全部渠道
    python hunter.py list --no-card --region cn
    python hunter.py show zhipu-bigmodel       # 查看单个渠道的完整引导
    python hunter.py plan                      # 交互式生成个性化领取路线
    python hunter.py guide                     # 逐个渠道分步引导并记录进度
    python hunter.py guide groq                # 只引导某一个渠道
    python hunter.py status                    # 查看领取进度
    python hunter.py verify groq               # 用已保存的 Key 实测接口是否可用
    python hunter.py export                    # 导出 Markdown 报告 + HTML 看板
    python hunter.py discover                  # 联网发现新的免费额度渠道（候选池）
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import textwrap
import urllib.error
import urllib.request
from datetime import datetime, date
from pathlib import Path

# ---------------------------------------------------------------- 基础设施

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
OUT_DIR = ROOT / "out"
TPL_DIR = ROOT / "templates"
PROGRESS_FILE = OUT_DIR / "progress.json"
VAULT_FILE = OUT_DIR / "keys.local.env"   # 本地密钥，已在 .gitignore 中排除

CATEGORY_LABEL = {
    "llm-api": "大模型 API",
    "aggregator": "模型聚合",
    "cloud": "云服务/部署",
    "compute": "免费算力",
    "student": "学生/开发者福利",
}
REGION_LABEL = {"cn": "国内", "global": "海外"}
STATUS_LABEL = {
    "todo": "未开始",
    "doing": "进行中",
    "done": "已领取",
    "skip": "已跳过",
    "failed": "失败",
}


def _enable_ansi() -> bool:
    if os.name == "nt":
        os.system("")          # 触发 Windows 10+ 的 VT 序列支持
    return sys.stdout.isatty()


ANSI = _enable_ansi()


def c(text: str, color: str) -> str:
    if not ANSI:
        return text
    codes = {
        "red": "31", "green": "32", "yellow": "33", "blue": "34",
        "magenta": "35", "cyan": "36", "grey": "90", "bold": "1",
    }
    return f"\033[{codes.get(color, '0')}m{text}\033[0m"


def wcwidth(s: str) -> int:
    """粗略计算显示宽度：CJK 字符按 2 列算。"""
    w = 0
    for ch in s:
        w += 2 if unicode_is_wide(ch) else 1
    return w


def unicode_is_wide(ch: str) -> bool:
    o = ord(ch)
    return (
        0x1100 <= o <= 0x115F or 0x2E80 <= o <= 0xA4CF or
        0xAC00 <= o <= 0xD7A3 or 0xF900 <= o <= 0xFAFF or
        0xFE30 <= o <= 0xFE6F or 0xFF00 <= o <= 0xFF60 or
        0xFFE0 <= o <= 0xFFE6
    )


def pad(s: str, width: int) -> str:
    diff = width - wcwidth(s)
    return s + " " * max(diff, 0)


def clip(s: str, width: int) -> str:
    if wcwidth(s) <= width:
        return s
    out = ""
    for ch in s:
        if wcwidth(out + ch) > width - 1:
            return out + "…"
        out += ch
    return out


# ---------------------------------------------------------------- 数据加载

def load_channels() -> list[dict]:
    """加载 data/*.json 里的全部渠道，附加 pack 元信息。"""
    channels: list[dict] = []
    if not DATA_DIR.exists():
        die(f"找不到数据目录：{DATA_DIR}")
    for f in sorted(DATA_DIR.glob("*.json")):
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            die(f"数据文件解析失败 {f.name}: {e}")
        for ch in payload.get("channels", []):
            ch["pack"] = payload.get("pack", f.stem)
            ch["pack_id"] = payload.get("pack_id", f.stem)
            ch["_source_file"] = f.name
            channels.append(ch)
    # 用户自定义补充渠道
    custom = ROOT / "custom_channels.json"
    if custom.exists():
        for ch in json.loads(custom.read_text(encoding="utf-8")).get("channels", []):
            ch.setdefault("pack", "自定义")
            ch.setdefault("pack_id", "custom")
            channels.append(ch)
    channels.sort(key=lambda x: -float(x.get("score", 0)))
    return channels


def die(msg: str) -> None:
    print(c("✗ " + msg, "red"))
    sys.exit(1)


def find_channel(channels: list[dict], key: str) -> dict | None:
    key_l = key.lower().strip()
    for ch in channels:
        if ch["id"].lower() == key_l:
            return ch
    hits = [ch for ch in channels
            if key_l in ch["id"].lower()
            or key_l in ch["name"].lower()
            or any(key_l in a.lower() for a in ch.get("aka", []))]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        print(c(f"「{key}」匹配到多个渠道，请用更精确的 id：", "yellow"))
        for h in hits:
            print(f"  - {c(h['id'], 'cyan')}  {h['name']}")
        sys.exit(1)
    return None


# ---------------------------------------------------------------- 进度存储

def load_progress() -> dict:
    if PROGRESS_FILE.exists():
        try:
            return json.loads(PROGRESS_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"items": {}, "updated_at": None}


def save_progress(p: dict) -> None:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p["updated_at"] = datetime.now().isoformat(timespec="seconds")
    PROGRESS_FILE.write_text(json.dumps(p, ensure_ascii=False, indent=2), encoding="utf-8")


def set_status(cid: str, status: str, note: str = "", expire: str = "") -> None:
    p = load_progress()
    item = p["items"].get(cid, {})
    item["status"] = status
    item["updated_at"] = datetime.now().isoformat(timespec="seconds")
    if note:
        item["note"] = note
    if expire:
        item["expire_at"] = expire
    p["items"][cid] = item
    save_progress(p)


def save_key(env_name: str, value: str) -> None:
    """把 API Key 追加写入本地 env 文件（不入库、不上传）。"""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    if VAULT_FILE.exists():
        lines = [l for l in VAULT_FILE.read_text(encoding="utf-8").splitlines()
                 if not l.startswith(env_name + "=")]
    lines.append(f"{env_name}={value}")
    VAULT_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        os.chmod(VAULT_FILE, 0o600)
    except OSError:
        pass


def load_vault() -> dict:
    kv = {}
    if VAULT_FILE.exists():
        for line in VAULT_FILE.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                kv[k.strip()] = v.strip()
    return kv


# ---------------------------------------------------------------- 展示

def needs_badges(ch: dict) -> str:
    n = ch.get("needs", {})
    out = []
    out.append(c("免绑卡", "green") if not n.get("card") else c("需绑卡", "red"))
    if n.get("vpn"):
        out.append(c("需国际网络", "yellow"))
    if n.get("student"):
        out.append(c("限学生", "magenta"))
    if n.get("realname"):
        out.append(c("需实名", "grey"))
    return " ".join(out)


def cmd_list(args) -> None:
    channels = apply_filters(load_channels(), args)
    prog = load_progress()["items"]
    if not channels:
        print(c("没有匹配的渠道，试试放宽筛选条件。", "yellow"))
        return

    print()
    print(c(f"共 {len(channels)} 个渠道（按推荐分排序）", "bold"))
    header = (pad("ID", 26) + pad("渠道", 34) + pad("分类", 18) +
              pad("分", 6) + pad("状态", 8) + "免费额度")
    print(c(header, "grey"))
    print(c("─" * 150, "grey"))
    for ch in channels:
        st = prog.get(ch["id"], {}).get("status", "todo")
        st_txt = {"done": c("✔已领", "green"), "doing": c("…进行", "yellow"),
                  "skip": c("－跳过", "grey"), "failed": c("✗失败", "red")}.get(st, c("○未领", "grey"))
        row = (pad(c(ch["id"], "cyan"), 26 + (9 if ANSI else 0)) +
               pad(clip(ch["name"], 32), 34) +
               pad(CATEGORY_LABEL.get(ch["category"], ch["category"]), 18) +
               pad(f"{ch.get('score', 0):.1f}", 6) +
               pad(st_txt, 8 + (9 if ANSI else 0)) +
               clip(ch.get("quota", ""), 60))
        print(row)
    print()
    print(c("查看详情： python hunter.py show <id>      开始引导： python hunter.py guide <id>", "grey"))


def apply_filters(channels: list[dict], args) -> list[dict]:
    out = channels
    if getattr(args, "region", None):
        out = [c_ for c_ in out if c_["region"] == args.region]
    if getattr(args, "category", None):
        out = [c_ for c_ in out if c_["category"] == args.category]
    if getattr(args, "no_card", False):
        out = [c_ for c_ in out if not c_.get("needs", {}).get("card")]
    if getattr(args, "no_vpn", False):
        out = [c_ for c_ in out if not c_.get("needs", {}).get("vpn")]
    if getattr(args, "student", False):
        out = [c_ for c_ in out if c_.get("needs", {}).get("student")]
    if getattr(args, "exclude_student", False):
        out = [c_ for c_ in out if not c_.get("needs", {}).get("student")]
    if getattr(args, "keyword", None):
        k = args.keyword.lower()
        out = [c_ for c_ in out
               if k in json.dumps(c_, ensure_ascii=False).lower()]
    if getattr(args, "min_score", None):
        out = [c_ for c_ in out if float(c_.get("score", 0)) >= args.min_score]
    return out


def print_channel(ch: dict, prog_item: dict | None = None) -> None:
    line = "═" * 78
    print()
    print(c(line, "blue"))
    print(c(f" {ch['name']}", "bold") + c(f"   [{ch['id']}]", "grey"))
    print(c(line, "blue"))
    print(f" {c('分类', 'grey')}    {CATEGORY_LABEL.get(ch['category'], ch['category'])}"
          f" · {REGION_LABEL.get(ch['region'], ch['region'])}"
          f" · {c('推荐分 ' + str(ch.get('score', 0)), 'yellow')}"
          f" · 难度 {'★' * int(ch.get('difficulty', 1))}")
    print(f" {c('门槛', 'grey')}    {needs_badges(ch)}")
    print(f" {c('官网', 'grey')}    {c(ch.get('url', '-'), 'cyan')}")
    if ch.get("claim_url"):
        print(f" {c('领取页', 'grey')}  {c(ch['claim_url'], 'cyan')}")
    if ch.get("docs_url"):
        print(f" {c('文档', 'grey')}    {c(ch['docs_url'], 'cyan')}")
    print()
    print(f" {c('▸ 免费额度', 'green')}")
    for l in textwrap.wrap(ch.get("quota", "-"), 72):
        print("   " + l)
    print(f" {c('▸ 有效期', 'green')}   {ch.get('validity', '-')}")
    print(f" {c('▸ 重置规则', 'green')} {ch.get('reset', '-')}")

    if ch.get("signup"):
        print()
        print(c(" ▸ 注册步骤", "yellow"))
        for i, s in enumerate(ch["signup"], 1):
            body = textwrap.wrap(s, 68)
            print(f"   {c(str(i) + '.', 'yellow')} {body[0]}")
            for extra in body[1:]:
                print(f"      {extra}")
    if ch.get("claim"):
        print()
        print(c(" ▸ 领取额度 / 拿 Key", "yellow"))
        for i, s in enumerate(ch["claim"], 1):
            body = textwrap.wrap(s, 68)
            print(f"   {c(str(i) + '.', 'yellow')} {body[0]}")
            for extra in body[1:]:
                print(f"      {extra}")
    v = ch.get("verify", {})
    if v.get("type") == "openai_compatible":
        print()
        print(c(" ▸ 调用示例（OpenAI 兼容）", "magenta"))
        print(f"   base_url = {v['base_url']}")
        print(f"   model    = {v['model']}")
        print(f"   env      = {v['env']}")
        print(c(f"   自测：python hunter.py verify {ch['id']}", "grey"))
    elif v.get("note"):
        print()
        print(c(" ▸ 调用说明", "magenta") + f"  {v['note']}")

    if ch.get("tips"):
        print()
        print(c(" ▸ 实用建议", "cyan"))
        for t in ch["tips"]:
            for j, l in enumerate(textwrap.wrap(t, 70)):
                print(("   • " if j == 0 else "     ") + l)
    if ch.get("risks"):
        print()
        print(c(" ▸ 风险提示", "red"))
        for t in ch["risks"]:
            for j, l in enumerate(textwrap.wrap(t, 70)):
                print(("   ! " if j == 0 else "     ") + l)
    if prog_item:
        print()
        print(c(f" ▸ 我的进度  {STATUS_LABEL.get(prog_item.get('status', 'todo'))}"
                f"  更新于 {prog_item.get('updated_at', '-')}", "grey"))
        if prog_item.get("expire_at"):
            print(c(f"   到期日：{prog_item['expire_at']}", "grey"))
        if prog_item.get("note"):
            print(c(f"   备注：{prog_item['note']}", "grey"))
    print()


def cmd_show(args) -> None:
    channels = load_channels()
    ch = find_channel(channels, args.id)
    if not ch:
        die(f"没找到渠道：{args.id}（用 python hunter.py list 查看全部）")
    print_channel(ch, load_progress()["items"].get(ch["id"]))


# ---------------------------------------------------------------- 个性化路线

def ask(prompt: str, options: list[tuple[str, str]], default: str) -> str:
    print()
    print(c(prompt, "bold"))
    for k, label in options:
        mark = c("(默认)", "grey") if k == default else ""
        print(f"  {c(k, 'cyan')}) {label} {mark}")
    v = input(c("> ", "cyan")).strip().lower()
    return v if v in dict(options) else default


def cmd_plan(args) -> None:
    channels = load_channels()
    print(c("\n═══ 个性化领取路线生成器 ═══", "bold"))
    print(c("回答 4 个问题，给你一条从易到难、性价比最高的领取顺序。", "grey"))

    net = ask("1. 你的网络环境？", [
        ("a", "只有国内直连网络"),
        ("b", "有稳定的国际网络"),
    ], "b")
    card = ask("2. 是否愿意绑定信用卡（用于身份验证，通常只预授权 $1）？", [
        ("a", "不愿意，只要免绑卡的"),
        ("b", "可以绑卡，想要价值最高的资源"),
    ], "a")
    student = ask("3. 你目前是在校学生吗（有校园邮箱或学生证）？", [
        ("a", "是"),
        ("b", "不是"),
    ], "b")
    purpose = ask("4. 主要用途？", [
        ("a", "调 API 做应用开发 / 写代码"),
        ("b", "跑训练、微调，需要 GPU 算力"),
        ("c", "部署上线，需要服务器和数据库"),
        ("d", "都要，越多越好"),
    ], "a")

    pool = list(channels)
    if net == "a":
        pool = [x for x in pool if not x.get("needs", {}).get("vpn")]
    if card == "a":
        pool = [x for x in pool if not x.get("needs", {}).get("card")]
    if student == "b":
        pool = [x for x in pool if not x.get("needs", {}).get("student")]

    weight = {
        "a": {"llm-api": 1.25, "aggregator": 1.15, "compute": 0.85, "cloud": 0.8, "student": 1.0},
        "b": {"compute": 1.35, "llm-api": 0.9, "aggregator": 0.85, "cloud": 1.0, "student": 1.1},
        "c": {"cloud": 1.35, "llm-api": 0.85, "aggregator": 0.8, "compute": 0.9, "student": 1.1},
        "d": {"llm-api": 1.0, "aggregator": 1.0, "compute": 1.0, "cloud": 1.0, "student": 1.1},
    }[purpose]

    for x in pool:
        base = float(x.get("score", 0)) * weight.get(x["category"], 1.0)
        base -= (int(x.get("difficulty", 1)) - 1) * 0.35      # 越难越靠后
        x["_rank"] = round(base, 3)
    pool.sort(key=lambda x: -x["_rank"])

    top = pool[: args.top]
    print()
    print(c(f"═══ 为你筛出 {len(top)} 个渠道（共 {len(pool)} 个符合条件）═══", "bold"))
    print()
    est_minutes = 0
    for i, x in enumerate(top, 1):
        mins = {1: 5, 2: 12, 3: 25}.get(int(x.get("difficulty", 1)), 10)
        est_minutes += mins
        print(f"{c(f'{i:>2}.', 'yellow')} {c(x['name'], 'bold')}  {c('[' + x['id'] + ']', 'grey')}")
        print(f"    {c('额度', 'green')} {clip(x.get('quota', ''), 100)}")
        print(f"    {c('有效期', 'green')} {clip(x.get('validity', ''), 60)}   "
              f"{c('约需', 'grey')} {mins} 分钟   {needs_badges(x)}")
        print()
    print(c(f"预计总耗时约 {est_minutes} 分钟（{est_minutes // 60} 小时 {est_minutes % 60} 分）", "grey"))
    print()
    print(c("下一步： python hunter.py guide     # 按这个顺序逐个引导你完成", "cyan"))

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "plan.json").write_text(
        json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                    "answers": {"net": net, "card": card, "student": student, "purpose": purpose},
                    "order": [x["id"] for x in top]}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    print(c(f"路线已保存到 {OUT_DIR / 'plan.json'}", "grey"))


# ---------------------------------------------------------------- 交互引导

def cmd_guide(args) -> None:
    channels = load_channels()
    plan_file = OUT_DIR / "plan.json"

    if args.id:
        ch = find_channel(channels, args.id)
        if not ch:
            die(f"没找到渠道：{args.id}")
        queue = [ch]
    elif plan_file.exists() and not args.all:
        order = json.loads(plan_file.read_text(encoding="utf-8"))["order"]
        idx = {x["id"]: x for x in channels}
        queue = [idx[i] for i in order if i in idx]
        print(c(f"按 plan.json 的个性化路线引导（{len(queue)} 个渠道）", "grey"))
    else:
        queue = apply_filters(channels, args)

    prog = load_progress()
    pending = [x for x in queue
               if prog["items"].get(x["id"], {}).get("status") not in ("done", "skip")]
    if not pending:
        print(c("🎉 队列里的渠道都已处理完毕，运行 python hunter.py status 看总览。", "green"))
        return

    print(c(f"\n待处理 {len(pending)} 个渠道。任意步骤输入 q 可随时退出，进度会自动保存。", "grey"))

    for n, ch in enumerate(pending, 1):
        print("\n" + c("█" * 78, "blue"))
        print(c(f"  [{n}/{len(pending)}]  {ch['name']}", "bold"))
        print(c("█" * 78, "blue"))
        print(f"  {c('免费额度', 'green')} {ch.get('quota', '')}")
        print(f"  {c('有效期', 'green')}   {ch.get('validity', '')}")
        print(f"  {c('门槛', 'green')}     {needs_badges(ch)}")
        act = ask("现在要做什么？", [
            ("y", "开始引导，一步步来"),
            ("s", "跳过这个渠道"),
            ("d", "我已经领过了，直接标记完成"),
            ("q", "退出引导"),
        ], "y")
        if act == "q":
            print(c("已退出，进度已保存。", "grey"))
            return
        if act == "s":
            set_status(ch["id"], "skip")
            print(c("已跳过。", "grey"))
            continue
        if act == "d":
            set_status(ch["id"], "done", note="用户自行标记")
            print(c("已标记为已领取。", "green"))
            continue

        set_status(ch["id"], "doing")
        steps = [("注册", s) for s in ch.get("signup", [])] + \
                [("领取", s) for s in ch.get("claim", [])]
        total = len(steps)
        for i, (phase, s) in enumerate(steps, 1):
            print()
            print(c(f"  步骤 {i}/{total} · {phase}", "yellow"))
            for l in textwrap.wrap(s, 70):
                print("    " + l)
            urls = re.findall(r"https?://[^\s，。）)、]+", s)
            for u in urls:
                print(c(f"    ↗ {u}", "cyan"))
            r = input(c("    完成后按回车继续（b=上一步说明 / q=退出）> ", "grey")).strip().lower()
            if r == "q":
                print(c("已退出，当前渠道标记为进行中。", "grey"))
                return

        if ch.get("risks"):
            print()
            print(c("  ⚠ 别忘了这些风险点：", "red"))
            for t in ch["risks"]:
                print("    ! " + t)

        v = ch.get("verify", {})
        if v.get("type") == "openai_compatible":
            print()
            k = input(c(f"  粘贴你拿到的 API Key（回车跳过，将存入 {VAULT_FILE.name}）> ", "cyan")).strip()
            if k:
                save_key(v["env"], k)
                print(c(f"  已保存到 {VAULT_FILE}（该文件已加入 .gitignore，切勿上传）", "green"))
                if input(c("  立刻实测一次接口调用？(Y/n) > ", "cyan")).strip().lower() != "n":
                    ok, msg = verify_channel(ch, k)
                    print(("  " + c("✔ " + msg, "green")) if ok else ("  " + c("✗ " + msg, "red")))
                    set_status(ch["id"], "done" if ok else "failed", note=msg)
                    continue

        exp = input(c("  这份额度的到期日（YYYY-MM-DD，不清楚就回车跳过）> ", "cyan")).strip()
        set_status(ch["id"], "done", expire=exp)
        print(c("  ✔ 已记录为已领取。", "green"))

    print()
    print(c("🎉 本轮引导完成！运行 python hunter.py status 查看总览。", "green"))


# ---------------------------------------------------------------- 接口自测

def verify_channel(ch: dict, key: str | None = None, timeout: int = 30) -> tuple[bool, str]:
    v = ch.get("verify", {})
    if v.get("type") != "openai_compatible":
        return False, "该渠道没有配置自动验证方式，请手动确认"
    key = key or load_vault().get(v["env"]) or os.environ.get(v["env"], "")
    if not key:
        return False, f"未找到 Key，请设置环境变量 {v['env']} 或先跑一次 guide"
    base = v["base_url"].rstrip("/")
    if "<" in base:
        return False, f"base_url 含占位符需手动替换：{base}"
    url = base + "/chat/completions"
    body = json.dumps({
        "model": v["model"],
        "messages": [{"role": "user", "content": "回复两个字：可用"}],
        "max_tokens": 16,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "free-token-hunter/1.0",
    })
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", "ignore"))
        ms = int((time.time() - t0) * 1000)
        txt = ""
        try:
            txt = data["choices"][0]["message"]["content"][:40].replace("\n", " ")
        except (KeyError, IndexError, TypeError):
            txt = str(data)[:80]
        usage = data.get("usage", {})
        return True, (f"调用成功 {ms}ms | 模型 {v['model']} | 返回「{txt}」"
                      f" | 用量 {usage.get('total_tokens', '?')} tokens")
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "ignore")[:180]
        return False, f"HTTP {e.code}：{detail}"
    except Exception as e:                                   # noqa: BLE001
        return False, f"{type(e).__name__}: {e}"


def cmd_verify(args) -> None:
    channels = load_channels()
    targets = ([find_channel(channels, args.id)] if args.id
               else [x for x in channels if x.get("verify", {}).get("type") == "openai_compatible"])
    targets = [t for t in targets if t]
    if not targets:
        die("没有可自动验证的渠道")
    vault = load_vault()
    print()
    for ch in targets:
        env = ch["verify"]["env"]
        if not args.id and env not in vault and env not in os.environ:
            print(f"{pad(clip(ch['name'], 26), 28)} {c('跳过（未配置 Key）', 'grey')}")
            continue
        print(f"{pad(clip(ch['name'], 26), 28)} ", end="", flush=True)
        ok, msg = verify_channel(ch)
        print(c("✔ ", "green") + msg if ok else c("✗ ", "red") + msg)
        if not args.no_record:
            set_status(ch["id"], "done" if ok else "failed", note=msg)
    print()


# ---------------------------------------------------------------- 进度总览

def cmd_status(args) -> None:
    channels = load_channels()
    prog = load_progress()
    items = prog["items"]
    by_status: dict[str, list[dict]] = {}
    for ch in channels:
        st = items.get(ch["id"], {}).get("status", "todo")
        by_status.setdefault(st, []).append(ch)

    total = len(channels)
    done = len(by_status.get("done", []))
    bar_len = 40
    filled = int(bar_len * done / total) if total else 0
    print()
    print(c("═══ 领取进度总览 ═══", "bold"))
    print(f"  {c('█' * filled, 'green')}{c('░' * (bar_len - filled), 'grey')}  "
          f"{done}/{total}  ({done / total * 100:.0f}%)")
    print()
    for st in ("done", "doing", "failed", "skip", "todo"):
        lst = by_status.get(st, [])
        if not lst:
            continue
        color = {"done": "green", "doing": "yellow", "failed": "red",
                 "skip": "grey", "todo": "grey"}[st]
        print(c(f"  {STATUS_LABEL[st]}（{len(lst)}）", color))
        if st in ("todo", "skip") and not args.verbose:
            print(c("    " + clip("、".join(x["name"] for x in lst), 130), "grey"))
        else:
            for x in lst:
                it = items.get(x["id"], {})
                extra = ""
                if it.get("expire_at"):
                    extra = expire_hint(it["expire_at"])
                print(f"    · {pad(clip(x['name'], 26), 28)}{extra}"
                      f"  {c(clip(it.get('note', ''), 60), 'grey')}")
        print()

    # 到期提醒
    soon = []
    for cid, it in items.items():
        exp = it.get("expire_at")
        if not exp:
            continue
        try:
            d = (date.fromisoformat(exp) - date.today()).days
        except ValueError:
            continue
        if d <= 30:
            name = next((x["name"] for x in channels if x["id"] == cid), cid)
            soon.append((d, name, exp))
    if soon:
        soon.sort()
        print(c("  ⏰ 30 天内到期的额度：", "yellow"))
        for d, name, exp in soon:
            tag = c("已过期", "red") if d < 0 else c(f"还剩 {d} 天", "yellow")
            print(f"    · {pad(clip(name, 26), 28)} {exp}  {tag}")
        print()


def expire_hint(exp: str) -> str:
    try:
        d = (date.fromisoformat(exp) - date.today()).days
    except ValueError:
        return ""
    if d < 0:
        return c(f"  [已过期 {-d} 天]", "red")
    if d <= 30:
        return c(f"  [{d} 天后到期]", "yellow")
    return c(f"  [{exp} 到期]", "grey")


# ---------------------------------------------------------------- 导出

def cmd_export(args) -> None:
    channels = apply_filters(load_channels(), args)
    prog = load_progress()["items"]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    written = []

    if args.format in ("md", "all"):
        md = render_markdown(channels, prog)
        p = OUT_DIR / "免费token渠道汇总.md"
        p.write_text(md, encoding="utf-8")
        written.append(p)

    if args.format in ("html", "all"):
        tpl_path = TPL_DIR / "dashboard.html"
        if not tpl_path.exists():
            die(f"缺少模板文件 {tpl_path}")
        tpl = tpl_path.read_text(encoding="utf-8")
        payload = {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "channels": [strip_internal(x) for x in channels],
            "progress": prog,
            "labels": {"category": CATEGORY_LABEL, "region": REGION_LABEL},
        }
        html = tpl.replace("/*__DATA__*/null",
                           json.dumps(payload, ensure_ascii=False))
        p = OUT_DIR / "index.html"
        p.write_text(html, encoding="utf-8")
        written.append(p)

    if args.format in ("json", "all"):
        p = OUT_DIR / "channels.merged.json"
        p.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                                 "count": len(channels),
                                 "channels": [strip_internal(x) for x in channels]},
                                ensure_ascii=False, indent=2), encoding="utf-8")
        written.append(p)

    print()
    for p in written:
        print(c("✔ 已导出 ", "green") + str(p))
    print()


def strip_internal(ch: dict) -> dict:
    return {k: v for k, v in ch.items() if not k.startswith("_")}


def render_markdown(channels: list[dict], prog: dict) -> str:
    today = datetime.now().strftime("%Y-%m-%d")
    L = [f"# 免费 Token / 云额度渠道汇总（{today}）", ""]
    L.append(f"> 共 {len(channels)} 个渠道。由 free-token-hunter 自动生成。")
    L.append("> **所有额度、有效期均以各平台官网当前公告为准**，平台政策变动频繁，本表仅作导航。")
    L.append("")
    L.append("## 速览表")
    L.append("")
    L.append("| 渠道 | 分类 | 免费额度 | 有效期 | 门槛 | 推荐分 | 状态 |")
    L.append("|---|---|---|---|---|---|---|")
    for ch in channels:
        n = ch.get("needs", {})
        gate = []
        gate.append("需绑卡" if n.get("card") else "免绑卡")
        if n.get("vpn"):
            gate.append("国际网络")
        if n.get("student"):
            gate.append("限学生")
        st = STATUS_LABEL.get(prog.get(ch["id"], {}).get("status", "todo"), "未开始")
        L.append(f"| [{ch['name']}]({ch.get('url', '')}) "
                 f"| {CATEGORY_LABEL.get(ch['category'], ch['category'])} "
                 f"| {ch.get('quota', '').replace('|', '/')} "
                 f"| {ch.get('validity', '').replace('|', '/')} "
                 f"| {'/'.join(gate)} | {ch.get('score', 0)} | {st} |")
    L.append("")
    L.append("---")
    L.append("")
    L.append("## 详细领取引导")
    L.append("")
    for ch in channels:
        L.append(f"### {ch['name']}")
        L.append("")
        L.append(f"- **官网**：{ch.get('url', '-')}")
        if ch.get("claim_url"):
            L.append(f"- **领取页**：{ch['claim_url']}")
        if ch.get("docs_url"):
            L.append(f"- **文档**：{ch['docs_url']}")
        L.append(f"- **免费额度**：{ch.get('quota', '-')}")
        L.append(f"- **有效期**：{ch.get('validity', '-')}")
        L.append(f"- **重置规则**：{ch.get('reset', '-')}")
        n = ch.get("needs", {})
        L.append(f"- **门槛**：{'需要信用卡' if n.get('card') else '无需信用卡'}"
                 f"｜{'需要国际网络' if n.get('vpn') else '国内可直连'}"
                 f"｜{'需要实名' if n.get('realname') else '无需实名'}"
                 f"｜{'仅限学生' if n.get('student') else '不限身份'}")
        L.append("")
        if ch.get("signup"):
            L.append("**注册步骤**")
            L.append("")
            for i, s in enumerate(ch["signup"], 1):
                L.append(f"{i}. {s}")
            L.append("")
        if ch.get("claim"):
            L.append("**领取额度 / 获取 Key**")
            L.append("")
            for i, s in enumerate(ch["claim"], 1):
                L.append(f"{i}. {s}")
            L.append("")
        v = ch.get("verify", {})
        if v.get("type") == "openai_compatible":
            L.append("**调用示例**")
            L.append("")
            L.append("```bash")
            L.append(f'curl {v["base_url"]}/chat/completions \\')
            L.append(f'  -H "Authorization: Bearer ${v["env"]}" \\')
            L.append('  -H "Content-Type: application/json" \\')
            L.append(f'  -d \'{{"model":"{v["model"]}","messages":[{{"role":"user","content":"hi"}}]}}\'')
            L.append("```")
            L.append("")
        elif v.get("note"):
            L.append(f"**调用说明**：{v['note']}")
            L.append("")
        if ch.get("tips"):
            L.append("**实用建议**")
            L.append("")
            for t in ch["tips"]:
                L.append(f"- {t}")
            L.append("")
        if ch.get("risks"):
            L.append("**风险提示**")
            L.append("")
            for t in ch["risks"]:
                L.append(f"- ⚠️ {t}")
            L.append("")
        L.append("")
    L.append("---")
    L.append("")
    L.append("## 合规与安全提醒")
    L.append("")
    L.append("- 每个平台通常**限一人一账号**，用小号/虚拟号批量注册属于违反服务条款，会被封号甚至连坐。")
    L.append("- 免费层多数**禁止商用或有明确的非生产限制**，上线前务必读一遍对应的 ToS。")
    L.append("- API Key 属于凭证，**不要提交到 Git 仓库**，建议只放环境变量。")
    L.append("- 绑卡类渠道（AWS/GCP/Azure/Oracle）请第一时间设置**预算告警**，避免试用到期后产生真实账单。")
    L.append("- 免费层的输入数据常被用于改进模型，**不要传敏感或涉密内容**。")
    return "\n".join(L)


# ---------------------------------------------------------------- 联网发现

# 已人工验证可用的静态源（分支名变动时按顺序回退）
DISCOVER_SOURCES = [
    ("free-for-dev", [
        "https://raw.githubusercontent.com/ripienaar/free-for-dev/master/README.md",
        "https://raw.githubusercontent.com/ripienaar/free-for-dev/main/README.md",
    ]),
    ("awesome-free-chatgpt", [
        "https://raw.githubusercontent.com/LiLittleCat/awesome-free-chatgpt/main/README.md",
        "https://raw.githubusercontent.com/LiLittleCat/awesome-free-chatgpt/master/README.md",
    ]),
]

# 动态源：用 GitHub 搜索实时找清单仓库，避免源仓库改名/删除后彻底失灵
GH_SEARCH_QUERIES = [
    "free llm api resources",
    "free for developers cloud services list",
    "免费 大模型 API 额度",
]


def fetch(url: str, timeout: int = 25, retries: int = 2) -> str:
    """带退避重试的抓取；raw.githubusercontent 高频访问容易被短暂限流。"""
    req = urllib.request.Request(url, headers={
        "User-Agent": "free-token-hunter/1.0",
        "Accept": "application/vnd.github+json, text/plain, */*",
    })
    last: Exception | None = None
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            last = e
            if e.code == 404:            # 路径确实不存在，重试无意义
                raise
            time.sleep(1.2 * (attempt + 1))
        except Exception as e:                                # noqa: BLE001
            last = e
            time.sleep(1.2 * (attempt + 1))
    raise last if last else RuntimeError("fetch failed")


def github_readme_sources(per_query: int = 3, min_stars: int = 200) -> list[tuple[str, list[str]]]:
    """通过 GitHub 搜索 API 找出高星的「免费资源清单」仓库，返回其 README 地址。"""
    import urllib.parse
    seen, out = set(), []
    for q in GH_SEARCH_QUERIES:
        url = ("https://api.github.com/search/repositories?q="
               + urllib.parse.quote(q) + "&sort=stars&order=desc&per_page=8")
        try:
            items = json.loads(fetch(url)).get("items", [])
        except Exception:                                     # noqa: BLE001
            continue                                          # 限流或网络问题，静默跳过
        picked = 0
        for repo in items:
            full = repo.get("full_name", "")
            if full in seen or repo.get("stargazers_count", 0) < min_stars:
                continue
            seen.add(full)
            br = repo.get("default_branch") or "main"
            out.append((f"gh:{full}", [
                f"https://raw.githubusercontent.com/{full}/{br}/README.md",
                f"https://raw.githubusercontent.com/{full}/{br}/README_CN.md",
            ]))
            picked += 1
            if picked >= per_query:
                break
    return out


def cmd_discover(args) -> None:
    """从公开的免费资源清单仓库抓取条目，与本地库比对，输出候选新渠道。"""
    known = load_channels()
    known_domains = set()
    for ch in known:
        for u in (ch.get("url", ""), ch.get("claim_url", "")):
            m = re.search(r"https?://([^/]+)", u or "")
            if m:
                known_domains.add(m.group(1).replace("www.", "").lower())

    sources = list(DISCOVER_SOURCES)
    if not args.no_search:
        print(c("向 GitHub 搜索高星的免费资源清单仓库 …", "grey"), end=" ", flush=True)
        dyn = github_readme_sources()
        print(c(f"找到 {len(dyn)} 个", "green" if dyn else "yellow"))
        sources += dyn

    found: dict[str, dict] = {}
    for name, urls in sources:
        print(c(f"抓取 {name} …", "grey"), end=" ", flush=True)
        text, last_err = "", ""
        for u in urls:                       # 分支名变动时自动回退
            try:
                text = fetch(u)
                break
            except Exception as e:                            # noqa: BLE001
                last_err = f"{type(e).__name__}"
        if not text:
            print(c(f"失败（{last_err}），已跳过", "red"))
            continue
        print(c(f"OK {len(text) // 1024}KB", "green"))
        # markdown 列表项：[名称](链接) — 描述
        for m in re.finditer(r"^\s*[-*]\s*\[([^\]]{2,60})\]\((https?://[^)\s]+)\)\s*[—:\-–]?\s*(.{0,200})",
                             text, re.M):
            title, link, desc = m.group(1).strip(), m.group(2).strip(), m.group(3).strip()
            blob = (title + " " + desc).lower()
            if not any(k in blob for k in
                       ("free tier", "free plan", "免费", "free credit", "free api",
                        "no credit card", "free forever", "free for")):
                continue
            dm = re.search(r"https?://([^/]+)", link)
            domain = dm.group(1).replace("www.", "").lower() if dm else link
            if domain in known_domains or domain in found:
                continue
            found[domain] = {"name": title, "url": link,
                             "desc": re.sub(r"[*`]", "", desc)[:160], "source": name}

    ranked = sorted(found.values(), key=lambda x: -len(x["desc"]))[: args.top]
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / "discovered.json"
    out.write_text(json.dumps({"generated_at": datetime.now().isoformat(timespec="seconds"),
                               "count": len(ranked), "candidates": ranked},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    print()
    print(c(f"发现 {len(found)} 个本地库尚未收录的候选渠道，输出前 {len(ranked)} 个：", "bold"))
    print()
    for i, x in enumerate(ranked, 1):
        print(f"{i:>3}. {c(clip(x['name'], 34), 'cyan')}")
        print(f"     {x['url']}")
        if x["desc"]:
            print(c("     " + clip(x["desc"], 110), "grey"))
    print()
    print(c(f"完整结果：{out}", "grey"))
    print(c("确认可用的条目可手动补进 custom_channels.json（格式同 data/*.json）。", "grey"))
    print(c("注意：候选条目未经人工核实，额度与政策请以官网为准。", "yellow"))


# ---------------------------------------------------------------- 入口

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="hunter",
        description="免费 token / 云额度渠道汇总与领取引导工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            常用流程：
              1) python hunter.py plan          先生成个性化路线
              2) python hunter.py guide         按路线一步步完成注册与领取
              3) python hunter.py verify        实测各家 Key 是否可用
              4) python hunter.py status        查看进度与到期提醒
              5) python hunter.py export        导出 Markdown 报告 + HTML 看板
        """))
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_filters(sp):
        sp.add_argument("--region", choices=["cn", "global"], help="按地区筛选")
        sp.add_argument("--category", choices=list(CATEGORY_LABEL), help="按分类筛选")
        sp.add_argument("--no-card", action="store_true", help="只看无需信用卡的")
        sp.add_argument("--no-vpn", action="store_true", help="只看国内可直连的")
        sp.add_argument("--student", action="store_true", help="只看学生专属")
        sp.add_argument("--exclude-student", action="store_true", help="排除学生专属")
        sp.add_argument("-k", "--keyword", help="关键词搜索")
        sp.add_argument("--min-score", type=float, help="最低推荐分")

    sp = sub.add_parser("list", help="列出渠道")
    add_filters(sp)
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("show", help="查看某个渠道的完整引导")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("plan", help="交互式生成个性化领取路线")
    sp.add_argument("--top", type=int, default=12, help="输出前 N 个（默认 12）")
    sp.set_defaults(func=cmd_plan)

    sp = sub.add_parser("guide", help="分步引导并记录进度")
    sp.add_argument("id", nargs="?", help="只引导指定渠道")
    sp.add_argument("--all", action="store_true", help="忽略 plan.json，引导全部")
    add_filters(sp)
    sp.set_defaults(func=cmd_guide)

    sp = sub.add_parser("status", help="查看领取进度与到期提醒")
    sp.add_argument("-v", "--verbose", action="store_true")
    sp.set_defaults(func=cmd_status)

    sp = sub.add_parser("verify", help="实测 API Key 是否可用")
    sp.add_argument("id", nargs="?")
    sp.add_argument("--no-record", action="store_true", help="不写入进度文件")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("export", help="导出报告")
    sp.add_argument("--format", choices=["md", "html", "json", "all"], default="all")
    add_filters(sp)
    sp.set_defaults(func=cmd_export)

    sp = sub.add_parser("discover", help="联网发现尚未收录的免费渠道")
    sp.add_argument("--top", type=int, default=30)
    sp.add_argument("--no-search", action="store_true",
                    help="只用内置静态源，不调用 GitHub 搜索")
    sp.set_defaults(func=cmd_discover)

    return p


def main() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8")
        except Exception:                                     # noqa: BLE001
            pass
    args = build_parser().parse_args()
    try:
        args.func(args)
    except KeyboardInterrupt:
        print(c("\n已中断，进度已保存。", "grey"))


if __name__ == "__main__":
    main()
