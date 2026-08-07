from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from poker.models import Hand

HAND_HEADER_RE = re.compile(
    r"^Poker Hand #(?P<hand_id>\S+):\s+"
    r"(?P<game>.+?)\s+"
    r"\((?P<stakes>[^)]+)\)\s+-\s+"
    r"(?P<dt>\d{4}/\d{2}/\d{2}\s+\d{2}:\d{2}:\d{2})"
)

TABLE_RE = re.compile(
    r"^Table '(?P<table>[^']+)'\s+(?P<max>\d+)-max",
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
    hero_seat: int | None = None
    hero_cards: str | None = None

    hero_invested = 0.0
    hero_returned = 0.0
    hero_collected = 0.0
    total_collected = 0.0
    street_contrib = 0.0
    went_to_flop = False
    hero_vpip = False
    in_summary = False

    total_pot = 0.0
    rake = jackpot = bingo = fortune = tax = 0.0
    summary_lines: list[str] = []

    for ln in non_empty:
        if not ln.strip():
            continue

        if ln.startswith("Table "):
            m = TABLE_RE.match(ln)
            if m:
                table_name = m.group("table")
                max_players = int(m.group("max"))
            continue

        seat_m = SEAT_RE.match(ln)
        if seat_m:
            if seat_m.group("name") == "Hero":
                hero_seat = int(seat_m.group("seat"))
            continue

        dealt = DEALT_HERO_RE.match(ln)
        if dealt:
            hero_cards = dealt.group("cards")
            continue

        if ln.startswith("*** FLOP ***"):
            went_to_flop = True
            street_contrib = 0.0
            continue
        if ln.startswith("*** TURN ***") or ln.startswith("*** RIVER ***"):
            street_contrib = 0.0
            continue
        # Blinds are posted before HOLE CARDS and count toward preflop contribution;
        # do not reset street_contrib here.
        if ln.startswith("*** HOLE CARDS ***"):
            continue
        if ln.startswith("*** SHOWDOWN ***"):
            continue
        if ln.startswith("*** SUMMARY ***"):
            in_summary = True
            continue

        if in_summary:
            summary_lines.append(ln)
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
            if returned.group("name") == "Hero":
                amt = _money(returned.group("amount"))
                hero_returned += amt
                street_contrib = max(0.0, street_contrib - amt)
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

        if name != "Hero":
            continue

        # Posts (blinds/antes) — not VPIP
        if act.startswith("posts"):
            m = POSTS_RE.search(act + rest) or POSTS_GENERIC_RE.search(act + rest)
            if m:
                amt = _money(m.group("amount"))
                hero_invested += amt
                street_contrib += amt
            continue

        if act == "raises":
            m = RAISES_RE.search(act + rest)
            if m:
                to_amt = _money(m.group("to"))
                add = round(to_amt - street_contrib, 6)
                if add < 0:
                    # Fallback to raise-by if street tracking drifted
                    add = _money(m.group("by"))
                hero_invested += add
                street_contrib += add
                hero_vpip = True
            continue

        if act in ("bets", "calls"):
            m = BETS_CALLS_RE.search(act + rest)
            if m:
                amt = _money(m.group("amount"))
                hero_invested += amt
                street_contrib += amt
                hero_vpip = True
            continue

        # checks / folds / shows / mucks — no money

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
        hero_vpip=hero_vpip,
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
