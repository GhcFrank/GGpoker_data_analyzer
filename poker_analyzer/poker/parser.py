from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from poker.models import Action, Hand

HAND_HEADER_RE = re.compile(
    r"^Poker Hand #(?P<hand_id>\S+):\s+"
    r"(?P<game>.+?)\s+"
    r"\((?P<stakes>[^)]+)\)\s+-\s+"
    r"(?P<dt>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})"
)

TABLE_RE = re.compile(
    r"^Table '(?P<table>[^']+)'\s+(?P<max>\d+)-max"
    r"(?:\s+Seat #(?P<button>\d+) is the button)?",
)

SEAT_RE = re.compile(
    r"^Seat (?P<seat>\d+):\s+(?P<name>\S+)\s+\(\$(?P<stack>[\d.]+) in chips\)",
)

DEALT_HERO_RE = re.compile(r"^Dealt to Hero \[(?P<cards>[^\]]+)\]")

# Money actions for any player; we filter Hero separately.
ACTION_RE = re.compile(
    r"^(?P<name>\S+):\s+"
    r"(?P<action>posts small blind|posts big blind|posts the ante|"
    r"posts small & big blinds|posts|"
    r"bets|calls|raises|checks|folds|shows|mucks)"
    r"(?P<rest>.*)$"
)

RAISES_RE = re.compile(r"raises \$(?P<by>[\d.]+) to \$(?P<to>[\d.]+)")
BETS_CALLS_RE = re.compile(r"(?:bets|calls) \$(?P<amount>[\d.]+)")
POSTS_RE = re.compile(r"posts(?: small blind| big blind| the ante| small & big blinds)? \$(?P<amount>[\d.]+)")
# Rare: "Hero: posts $0.05" style dead blinds / extras
POSTS_GENERIC_RE = re.compile(r"posts \$(?P<amount>[\d.]+)")

RETURNED_RE = re.compile(r"^Uncalled bet \(\$(?P<amount>[\d.]+)\) returned to (?P<name>\S+)")
COLLECTED_RE = re.compile(r"^(?P<name>\S+) collected \$(?P<amount>[\d.]+) from (?:pot|main pot|side pot(?:-\d+)?)")

SUMMARY_POT_RE = re.compile(
    r"Total pot \$(?P<pot>[\d.]+)\s*\|\s*Rake \$(?P<rake>[\d.]+)"
    r"(?:\s*\|\s*Jackpot \$(?P<jackpot>[\d.]+))?"
    r"(?:\s*\|\s*Bingo \$(?P<bingo>[\d.]+))?"
    r"(?:\s*\|\s*Fortune \$(?P<fortune>[\d.]+))?"
    r"(?:\s*\|\s*Tax \$(?P<tax>[\d.]+))?"
)

_STREET_MARKERS = {
    "*** HOLE CARDS ***": "preflop",
    "*** FLOP ***": "flop",
    "*** TURN ***": "turn",
    "*** RIVER ***": "river",
}

FLOP_LINE_RE = re.compile(r"^\*\*\* FLOP \*\*\* \[(?P<cards>[^\]]+)\]")
TURN_LINE_RE = re.compile(r"^\*\*\* TURN \*\*\* \[(?P<prev>[^\]]+)\] \[(?P<card>[^\]]+)\]")
RIVER_LINE_RE = re.compile(r"^\*\*\* RIVER \*\*\* \[(?P<prev>[^\]]+)\] \[(?P<card>[^\]]+)\]")
BOARD_SUMMARY_RE = re.compile(r"^Board \[(?P<cards>[^\]]+)\]")


def _parse_card_tokens(raw: str) -> tuple[str, ...]:
    return tuple(part.strip() for part in raw.split() if part.strip())


def _money(value: str | None) -> float:
    if not value:
        return 0.0
    return float(value)


def _split_hands(text: str) -> list[str]:
    parts = re.split(r"(?=^Poker Hand #)", text, flags=re.MULTILINE)
    return [p.strip() for p in parts if p.strip().startswith("Poker Hand #")]


def parse_hand(raw: str, source_file: str = "") -> Hand | None:
    """Parse a single hand history block into a Hand model."""
    non_empty = [ln.rstrip() for ln in raw.splitlines()]

    header = None
    for ln in non_empty:
        if ln.startswith("Poker Hand #"):
            header = HAND_HEADER_RE.match(ln)
            break
    if not header:
        return None

    hand_id = header.group("hand_id")
    stakes = header.group("stakes")
    dt = datetime.strptime(header.group("dt"), "%Y/%m/%d %H:%M:%S")

    table_name = ""
    max_players = 0
    button_seat: int | None = None
    hero_seat: int | None = None
    hero_cards: str | None = None
    seat_names: dict[int, str] = {}

    hero_invested = 0.0
    hero_returned = 0.0
    hero_collected = 0.0
    total_collected = 0.0
    street_contrib: dict[str, float] = {}
    went_to_flop = False
    flop_cards: tuple[str, ...] = ()
    hero_vpip = False
    in_summary = False
    street = "preflop"
    pot = 0.0
    actions: list[Action] = []

    total_pot = 0.0
    rake = jackpot = bingo = fortune = tax = 0.0
    summary_lines: list[str] = []

    def reset_street_contrib() -> None:
        street_contrib.clear()

    for ln in non_empty:
        if not ln.strip():
            continue

        if ln.startswith("Table "):
            m = TABLE_RE.match(ln)
            if m:
                table_name = m.group("table")
                max_players = int(m.group("max"))
                if m.group("button"):
                    button_seat = int(m.group("button"))
            continue

        seat_m = SEAT_RE.match(ln)
        if seat_m:
            seat_no = int(seat_m.group("seat"))
            name = seat_m.group("name")
            seat_names[seat_no] = name
            if name == "Hero":
                hero_seat = seat_no
            continue

        dealt = DEALT_HERO_RE.match(ln)
        if dealt:
            hero_cards = dealt.group("cards")
            continue

        flop_line = FLOP_LINE_RE.match(ln)
        if flop_line:
            flop_cards = _parse_card_tokens(flop_line.group("cards"))
            went_to_flop = True
            reset_street_contrib()
            street = "flop"
            continue

        turn_line = TURN_LINE_RE.match(ln)
        if turn_line:
            reset_street_contrib()
            street = "turn"
            continue

        river_line = RIVER_LINE_RE.match(ln)
        if river_line:
            reset_street_contrib()
            street = "river"
            continue

        street_hit = False
        for marker, street_name in _STREET_MARKERS.items():
            if ln.startswith(marker):
                if street_name == "flop":
                    went_to_flop = True
                if street_name != "preflop":
                    # Blinds are posted before HOLE CARDS and count toward preflop;
                    # only reset contribution when entering a new postflop street.
                    reset_street_contrib()
                street = street_name
                street_hit = True
                break
        if street_hit:
            continue

        if ln.startswith("*** SHOWDOWN ***"):
            continue
        if ln.startswith("*** SUMMARY ***"):
            in_summary = True
            continue

        if in_summary:
            summary_lines.append(ln)
            board_m = BOARD_SUMMARY_RE.match(ln)
            if board_m and not flop_cards:
                parsed = _parse_card_tokens(board_m.group("cards"))
                if len(parsed) >= 3:
                    flop_cards = parsed[:3]
                    went_to_flop = True
            pot_m = SUMMARY_POT_RE.search(ln)
            if pot_m:
                total_pot = _money(pot_m.group("pot"))
                rake = _money(pot_m.group("rake"))
                jackpot = _money(pot_m.group("jackpot"))
                bingo = _money(pot_m.group("bingo"))
                fortune = _money(pot_m.group("fortune"))
                tax = _money(pot_m.group("tax"))
            continue

        returned = RETURNED_RE.match(ln)
        if returned:
            name = returned.group("name")
            amt = _money(returned.group("amount"))
            pot = max(0.0, round(pot - amt, 6))
            street_contrib[name] = max(0.0, round(street_contrib.get(name, 0.0) - amt, 6))
            if name == "Hero":
                hero_returned += amt
            continue

        collected = COLLECTED_RE.match(ln)
        if collected:
            amt = _money(collected.group("amount"))
            total_collected += amt
            if collected.group("name") == "Hero":
                hero_collected += amt
            continue

        action = ACTION_RE.match(ln)
        if not action:
            continue

        name = action.group("name")
        act = action.group("action")
        rest = action.group("rest") or ""
        is_hero = name == "Hero"
        pot_before = pot

        # Posts (blinds/antes) — not VPIP
        if act.startswith("posts"):
            m = POSTS_RE.search(act + rest) or POSTS_GENERIC_RE.search(act + rest)
            if m:
                amt = _money(m.group("amount"))
                pot = round(pot + amt, 6)
                street_contrib[name] = round(street_contrib.get(name, 0.0) + amt, 6)
                actions.append(
                    Action(
                        street=street,
                        player=name,
                        action=act,
                        amount=amt,
                        pot_before=pot_before,
                        is_hero=is_hero,
                    )
                )
                if is_hero:
                    hero_invested += amt
            continue

        if act == "raises":
            m = RAISES_RE.search(act + rest)
            if m:
                to_amt = _money(m.group("to"))
                prev = street_contrib.get(name, 0.0)
                add = round(to_amt - prev, 6)
                if add < 0:
                    add = _money(m.group("by"))
                    to_amt = round(prev + add, 6)
                pot = round(pot + add, 6)
                street_contrib[name] = to_amt
                actions.append(
                    Action(
                        street=street,
                        player=name,
                        action="raise",
                        amount=add,
                        to_amount=to_amt,
                        pot_before=pot_before,
                        is_hero=is_hero,
                    )
                )
                if is_hero:
                    hero_invested += add
                    hero_vpip = True
            continue

        if act in ("bets", "calls"):
            m = BETS_CALLS_RE.search(act + rest)
            if m:
                amt = _money(m.group("amount"))
                pot = round(pot + amt, 6)
                street_contrib[name] = round(street_contrib.get(name, 0.0) + amt, 6)
                kind = "bet" if act == "bets" else "call"
                actions.append(
                    Action(
                        street=street,
                        player=name,
                        action=kind,
                        amount=amt,
                        pot_before=pot_before,
                        is_hero=is_hero,
                    )
                )
                if is_hero:
                    hero_invested += amt
                    hero_vpip = True
            continue

        if act in ("checks", "folds", "shows", "mucks"):
            kind = {
                "checks": "check",
                "folds": "fold",
                "shows": "show",
                "mucks": "muck",
            }[act]
            actions.append(
                Action(
                    street=street,
                    player=name,
                    action=kind,
                    pot_before=pot_before,
                    is_hero=is_hero,
                )
            )
            continue

    return Hand(
        hand_id=hand_id,
        datetime=dt,
        table_name=table_name,
        stakes=stakes,
        max_players=max_players,
        hero_seat=hero_seat,
        hero_cards=hero_cards,
        hero_invested=round(hero_invested, 6),
        hero_collected=round(hero_collected, 6),
        hero_returned=round(hero_returned, 6),
        total_pot=total_pot,
        rake=rake,
        jackpot=jackpot,
        bingo=bingo,
        fortune=fortune,
        tax=tax,
        source_file=source_file,
        raw_summary="\n".join(summary_lines),
        went_to_flop=went_to_flop,
        flop_cards=flop_cards,
        hero_vpip=hero_vpip,
        button_seat=button_seat,
        seat_names=seat_names,
        actions=actions,
        extra={"total_collected": round(total_collected, 6)},
    )


def parse_text(text: str, source_file: str = "") -> list[Hand]:
    hands: list[Hand] = []
    for block in _split_hands(text):
        hand = parse_hand(block, source_file=source_file)
        if hand is not None:
            hands.append(hand)
    return hands


def parse_file(path: Path | str) -> list[Hand]:
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    return parse_text(text, source_file=str(path.name))
