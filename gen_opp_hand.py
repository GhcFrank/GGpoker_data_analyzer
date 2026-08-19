#!/usr/bin/env python3
"""从 all_hand 筛选 Hero 与对手亮牌的手牌，生成对手视角的 txt 到 opp_hand。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "poker_analyzer"))

from poker.models import Hand
from poker.parser import _split_hands, parse_hand

INPUT_DIR = ROOT / "all_hand"
OUTPUT_DIR = ROOT / "opp_hand"

SWAP_TOKEN = "\x00SWAP\x00"
NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")


def hero_at_showdown(hand: Hand) -> bool:
    if "Hero" in hand.shown_cards:
        return True
    if any(act.is_hero and act.action in ("show", "muck") for act in hand.actions):
        return True
    for line in hand.raw_summary.splitlines():
        if re.search(r"Seat \d+:\s+Hero\b", line) and "showed" in line:
            return True
    return False


def opponents_at_showdown(hand: Hand) -> list[str]:
    return sorted(name for name in hand.shown_cards if name != "Hero")


def _format_cards(cards: tuple[str, ...]) -> str:
    return " ".join(cards[:2])


def swap_hero_with(text: str, opponent: str) -> str:
    if not NAME_RE.match(opponent):
        raise ValueError(f"invalid opponent name: {opponent!r}")
    text = re.sub(rf"\b{re.escape(opponent)}\b", SWAP_TOKEN, text)
    text = re.sub(r"\bHero\b", opponent, text)
    return text.replace(SWAP_TOKEN, "Hero")


def fix_dealt_lines(text: str, new_hero_cards: str, old_hero_name: str) -> str:
    out: list[str] = []
    dealt_hero = re.compile(r"^Dealt to Hero(?: \[(?P<cards>[^\]]+)\])?\s*$")
    dealt_old = re.compile(rf"^Dealt to {re.escape(old_hero_name)}(?: \[[^\]]+\])?\s*$")
    for ln in text.splitlines():
        if dealt_hero.match(ln):
            out.append(f"Dealt to Hero [{new_hero_cards}]")
        elif dealt_old.match(ln):
            out.append(f"Dealt to {old_hero_name} ")
        else:
            out.append(ln)
    return "\n".join(out)


def transform_hand(raw: str, opponent: str, opp_cards: tuple[str, ...]) -> str:
    swapped = swap_hero_with(raw, opponent)
    return fix_dealt_lines(swapped, _format_cards(opp_cards), opponent)


def process_file(src: Path, dst: Path) -> tuple[int, int]:
    text = src.read_text(encoding="utf-8", errors="replace")
    blocks = _split_hands(text)
    out_blocks: list[str] = []

    for block in blocks:
        hand = parse_hand(block, source_file=src.name)
        if hand is None or not hero_at_showdown(hand):
            continue
        opps = opponents_at_showdown(hand)
        if not opps:
            continue
        for opp in opps:
            cards = hand.shown_cards.get(opp)
            if not cards or len(cards) < 2:
                continue
            out_blocks.append(transform_hand(block, opp, cards))

    if not out_blocks:
        return 0, 0

    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text("\n\n\n".join(out_blocks) + "\n\n\n", encoding="utf-8")
    return len(blocks), len(out_blocks)


def main() -> int:
    if not INPUT_DIR.is_dir():
        print(f"[ERROR] 输入目录不存在: {INPUT_DIR}")
        return 1

    files = sorted(INPUT_DIR.glob("*.txt"))
    if not files:
        print(f"[WARN] {INPUT_DIR} 下没有 txt 文件")
        return 0

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    total_src = total_out = written = 0

    for src in files:
        dst = OUTPUT_DIR / src.name
        src_hands, out_hands = process_file(src, dst)
        total_src += src_hands
        if out_hands:
            written += 1
            total_out += out_hands
            print(f"  {src.name}: {out_hands} 手 -> {dst.name}")
        elif dst.exists():
            dst.unlink()

    print()
    print(f"完成: 扫描 {len(files)} 个文件, 输出 {written} 个, 共 {total_out} 手亮牌数据")
    print(f"目录: {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
