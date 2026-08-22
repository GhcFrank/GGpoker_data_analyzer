from __future__ import annotations

import re
from typing import Any

from poker.filters import normalize_stakes
from poker.positions import get_profile
from poker.models import Action, Hand

_BOARD_RE = re.compile(r"Board \[([^\]]+)\]")
_ACTION_ZH = {
    "fold": "弃牌",
    "check": "Check",
    "call": "跟注",
    "bet": "下注",
    "raise": "加注到",
}


def _bb_size(hand: Hand) -> float:
    for act in hand.actions:
        if act.action == "posts big blind" and act.amount > 0:
            return act.amount
    key = normalize_stakes(hand.stakes)
    if key:
        try:
            return float(key.split("/")[1])
        except (IndexError, ValueError):
            pass
    return 0.0


def _bb(chips: float, bb: float) -> float:
    if bb <= 0:
        return round(chips, 2)
    return round(chips / bb, 2)


def _fmt_bb(chips: float, bb: float) -> str:
    return f"{_bb(chips, bb):g}bb"


def _board_cards(hand: Hand) -> list[str]:
    m = _BOARD_RE.search(hand.raw_summary or "")
    if m:
        return [p for p in m.group(1).split() if p]
    return list(hand.flop_cards)


def _board_for(street: str, cards: list[str]) -> list[str]:
    n = {"preflop": 0, "flop": 3, "turn": 4, "river": 5}.get(street, 0)
    return cards[:n] if n else []


def _hole_cards(hand: Hand, name: str) -> list[str]:
    shown = hand.shown_cards.get(name)
    if shown and len(shown) >= 2:
        return list(shown[:2])
    if name == "Hero" and hand.hero_cards:
        parts = [p for p in hand.hero_cards.split() if p]
        return parts[:2]
    return []


def _layout_key(position: str, table_format: str) -> str:
    return get_profile(table_format).layout_key(position)


def _player_label(name: str, position: str, is_hero: bool) -> str:
    base = position or name
    if is_hero:
        return f"{base} · Hero"
    return base


def _caption(act: Action, pos: dict[str, str], bb: float) -> str:
    label = _player_label(act.player, pos.get(act.player, ""), act.is_hero)
    if act.action == "raise":
        to_amt = act.to_amount if act.to_amount > 0 else act.amount
        return f"{label} 加注到 {_fmt_bb(to_amt, bb)}"
    if act.action in ("bet", "call"):
        verb = _ACTION_ZH[act.action]
        return f"{label} {verb} {_fmt_bb(act.amount, bb)}"
    return f"{label} {_ACTION_ZH.get(act.action, act.action)}"


def _is_post(act: Action) -> bool:
    return act.action.startswith("posts")


def serialize_hand(hand: Hand, *, table_format: str | None = None) -> dict[str, Any]:
    fmt = table_format or ("9max" if hand.max_players >= 9 else "6max")
    profile = get_profile(fmt)
    bb = _bb_size(hand)
    pos = profile.position_map(hand)
    board_all = _board_cards(hand)
    names = list(hand.seat_names.values())
    players = []
    for seat, name in sorted(hand.seat_names.items()):
        position = pos.get(name, "")
        players.append(
            {
                "name": name,
                "seat": seat,
                "position": position,
                "layout": _layout_key(position, fmt),
                "is_hero": name == "Hero",
                "cards": _hole_cards(hand, name),
            }
        )

    front = {n: 0.0 for n in names}
    folded: set[str] = set()
    pot = 0.0
    street = "preflop"
    seen = {"preflop"}
    frames: list[dict[str, Any]] = []

    def snapshot(caption: str, *, kind: str, actor: str | None = None, action: str | None = None) -> None:
        frames.append(
            {
                "kind": kind,
                "street": street,
                "caption": caption,
                "actor": actor,
                "action": action,
                "pot_bb": _bb(pot, bb),
                "board": _board_for(street, board_all),
                "front_bb": {n: _bb(front.get(n, 0.0), bb) for n in names},
                "folded": sorted(folded),
            }
        )

    def enter_street(new_street: str) -> None:
        nonlocal street, front
        front = {n: 0.0 for n in names}
        street = new_street
        seen.add(new_street)
        title = {"flop": "发出 Flop", "turn": "发出 Turn", "river": "发出 River"}.get(
            new_street, new_street
        )
        snapshot(title, kind="deal")

    for act in hand.actions:
        if not _is_post(act):
            continue
        front[act.player] = round(front.get(act.player, 0.0) + act.amount, 6)
        pot = round(pot + act.amount, 6)
    snapshot("盲注入池", kind="blinds")

    for act in hand.actions:
        if _is_post(act) or act.action in ("show", "muck"):
            continue
        if act.street != street:
            enter_street(act.street)
        if act.action == "fold":
            folded.add(act.player)
        elif act.action in ("bet", "call"):
            front[act.player] = round(front.get(act.player, 0.0) + act.amount, 6)
            pot = round(pot + act.amount, 6)
        elif act.action == "raise":
            add = act.amount
            front[act.player] = act.to_amount if act.to_amount > 0 else round(
                front.get(act.player, 0.0) + add, 6
            )
            pot = round(pot + add, 6)
        snapshot(_caption(act, pos, bb), kind="action", actor=act.player, action=act.action)

    need = 0
    if len(board_all) >= 3:
        need = 3
    if len(board_all) >= 4:
        need = 4
    if len(board_all) >= 5:
        need = 5
    for extra, min_cards in (("flop", 3), ("turn", 4), ("river", 5)):
        if extra not in seen and need >= min_cards:
            enter_street(extra)

    return {
        "hand_id": hand.hand_id,
        "datetime": hand.datetime.isoformat(sep=" "),
        "stakes": hand.stakes,
        "table": hand.table_name,
        "bb": bb,
        "table_format": fmt,
        "players": players,
        "frames": frames,
    }
