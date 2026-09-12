from __future__ import annotations

import unittest
from datetime import datetime

from poker.metrics.preflop_analysis import PreflopAnalysisMetric
from poker.metrics.preflop_analysis_9max import PreflopAnalysis9MaxMetric
from poker.models import Action, Hand, HandDataset
from poker.parser import parse_hand
from poker.replay.service import get_replay


SEATS_BY_FORMAT = {
    "6max": {
        "BTN": 1,
        "SB": 2,
        "BB": 3,
        "UTG": 4,
        "HJ": 5,
        "CO": 6,
    },
    "9max": {
        "BTN": 1,
        "SB": 2,
        "BB": 3,
        "UTG": 4,
        "UTG+1": 5,
        "UTG+2": 6,
        "LJ": 7,
        "HJ": 8,
        "CO": 9,
    },
}


def raise_to(player: str, amount: float) -> Action:
    return Action(
        street="preflop",
        player=player,
        action="raise",
        amount=amount,
        to_amount=amount,
        is_hero=player == "Hero",
    )


def act(player: str, action: str) -> Action:
    return Action(
        street="preflop",
        player=player,
        action=action,
        is_hero=player == "Hero",
    )


def make_hand(
    hand_id: str,
    table_format: str,
    names_by_position: dict[str, str],
    actions: list[Action],
    shown_cards: dict[str, tuple[str, str]] | None = None,
    *,
    site: str = "ggpoker",
) -> Hand:
    seats = SEATS_BY_FORMAT[table_format]
    seat_names = {
        seat: names_by_position.get(position, f"{position} Player")
        for position, seat in seats.items()
    }
    hero_seat = next(seat for seat, name in seat_names.items() if name == "Hero")
    return Hand(
        hand_id=hand_id,
        datetime=datetime(2026, 9, 4, 12, 0),
        table_name="Actor Detail Test",
        stakes="0.5/1",
        max_players=len(seats),
        hero_seat=hero_seat,
        hero_cards=None,
        hero_invested=0.0,
        hero_collected=0.0,
        hero_returned=0.0,
        total_pot=0.0,
        rake=0.0,
        jackpot=0.0,
        bingo=0.0,
        fortune=0.0,
        tax=0.0,
        source_file=f"{site}-{hand_id}.txt",
        button_seat=seats["BTN"],
        seat_names=seat_names,
        actions=actions,
        shown_cards=shown_cards or {},
        extra={"site": site},
    )


def metric_for(table_format: str):
    if table_format == "9max":
        return PreflopAnalysis9MaxMetric()
    return PreflopAnalysisMetric()


class ActorBoundPreflopDetailTests(unittest.TestCase):
    def test_parsed_gg_and_coinpoker_hands_share_actor_detail_path(self) -> None:
        formats = (
            (
                "ggpoker",
                "Poker Hand #GG-ACTOR: Hold'em No Limit ($0.50/$1) - 2026/09/04 12:00:00",
                "$",
            ),
            (
                "coinpoker",
                "CoinPoker Hand #CP-ACTOR: NLH (₮0.50/₮1) 2026/09/04 12:00:00 EDT",
                "₮",
            ),
        )
        for site, header, currency in formats:
            with self.subTest(site=site):
                raw = f"""{header}
Table 'Actor Detail' 6-max Seat #1 is the button
Seat 1: Threebettor ({currency}100 in chips)
Seat 2: ColdCaller ({currency}100 in chips)
Seat 3: BigBlind ({currency}100 in chips)
Seat 4: UnderGun ({currency}100 in chips)
Seat 5: Hijack ({currency}100 in chips)
Seat 6: Hero ({currency}100 in chips)
ColdCaller: posts small blind {currency}0.50
BigBlind: posts big blind {currency}1
*** HOLE CARDS ***
Dealt to Hero [Qc Jd]
Hero: raises {currency}1.50 to {currency}2.50
Threebettor: raises {currency}5.50 to {currency}8
ColdCaller: calls {currency}7.50
Hero: calls {currency}5.50
*** FLOP *** [2c 3d 4h]
Hero: checks
Threebettor: checks
ColdCaller: checks
*** SHOWDOWN ***
Threebettor: shows [As Ad] (a pair of Aces)
ColdCaller: shows [Kh Kd] (a pair of Kings)
*** SUMMARY ***
Total pot {currency}24 | Rake {currency}0
"""
                hand = parse_hand(raw, source_file=f"{site}.txt")
                self.assertIsNotNone(hand)
                assert hand is not None
                result = PreflopAnalysisMetric().compute(
                    HandDataset([hand]),
                    {"action": "open_raise", "hero_position": "CO"},
                )
                self.assertEqual(result["faced_3bet"]["count"], 1)
                self.assertEqual(
                    result["hand_details"]["faced_3bet"],
                    {"count": 1, "hands": [{"hand": "AA", "count": 1, "pct": 100.0}]},
                )

    def test_open_raise_actor_details_and_full_multiway_replay(self) -> None:
        for table_format in ("6max", "9max"):
            with self.subTest(table_format=table_format):
                names = {"CO": "Hero", "BTN": "Threebettor", "SB": "Cold Caller"}
                known = make_hand(
                    "known-threebet",
                    table_format,
                    names,
                    [
                        raise_to("Hero", 2.5),
                        raise_to("Threebettor", 8),
                        act("Cold Caller", "call"),
                        act("Hero", "call"),
                    ],
                    {
                        "Threebettor": ("As", "Ad"),
                        "Cold Caller": ("Kh", "Kd"),
                    },
                )
                unknown = make_hand(
                    "unknown-threebet",
                    table_format,
                    names,
                    [raise_to("Hero", 2.5), raise_to("Threebettor", 8), act("Hero", "fold")],
                )
                dataset = HandDataset([known, unknown])
                options = {
                    "action": "open_raise", "hero_position": "CO",
                    "selected_event": "faced_3bet", "table_format": table_format,
                }
                result = metric_for(table_format).compute(dataset, options)
                replay = get_replay(
                    dataset,
                    f"preflop_analysis{'_9max' if table_format == '9max' else ''}",
                    0,
                    options,
                )
                self.assertEqual(replay["total"], 2)
                self.assertEqual(result["event_counts"]["faced_3bet"], 2)
                self.assertEqual(replay["hand"]["hand_id"], known.hand_id)
                self.assertIn("Cold Caller", {p["name"] for p in replay["hand"]["players"]})
                self.assertTrue(any(
                    frame["actor"] == "Cold Caller" and frame["action"] == "call"
                    for frame in replay["hand"]["frames"]
                ))

                self.assertEqual(result["faced_3bet"]["count"], 2)
                self.assertEqual(
                    result["hand_details"]["faced_3bet"],
                    {
                        "count": 2,
                        "hands": [
                            {"hand": "AA", "count": 1, "pct": 50.0},
                            {"hand": "未知", "count": 1, "pct": 50.0},
                        ],
                    },
                )
                self.assertNotIn("all_fold", result["hand_details"])

    def test_4bet_and_5bet_actor_responses(self) -> None:
        for table_format in ("6max", "9max"):
            for action in ("4bet", "5bet"):
                with self.subTest(table_format=table_format, action=action):
                    if action == "4bet":
                        names = {
                            "HJ": "Opener", "CO": "Threebettor",
                            "BTN": "Hero", "SB": "Cold Fivebettor",
                        }
                        opening = [raise_to("Opener", 2.5), raise_to("Threebettor", 8),
                                   raise_to("Hero", 22)]
                        responses = [
                            (act("Threebettor", "call"), {"Threebettor": ("Ac", "Kc")}),
                            (raise_to("Cold Fivebettor", 55),
                             {"Threebettor": ("Ah", "Ad"), "Cold Fivebettor": ("Qc", "Qd")}),
                        ]
                        options = {"hero_position": "BTN", "threebettor_position": "CO"}
                        counts = {"threebettor_faced": 1, "all_fold": 0,
                                  "faced_5bet": 1, "threebettor_call": 1}
                        combos = {"threebettor_faced": ["AKs"], "threebettor_call": ["AKs"],
                                  "faced_5bet": ["QQ"]}
                    else:
                        names = {
                            "HJ": "Opener", "CO": "Threebettor",
                            "BTN": "Fourbettor", "SB": "Hero",
                        }
                        opening = [raise_to("Opener", 2.5), raise_to("Threebettor", 8),
                                   raise_to("Fourbettor", 22), raise_to("Hero", 55)]
                        responses = [
                            (act("Fourbettor", "call"), {"Fourbettor": ("As", "Kd")}),
                            (act("Fourbettor", "fold"), {}),
                        ]
                        options = {"hero_position": "SB", "fourbettor_position": "BTN"}
                        counts = {"fourbettor_faced": 2, "fourbettor_fold": 1,
                                  "fourbettor_call": 1}
                        combos = {"fourbettor_faced": ["AKo", "未知"],
                                  "fourbettor_call": ["AKo"], "fourbettor_fold": ["未知"]}
                    dataset = HandDataset([
                        make_hand(f"{action}-{i}", table_format, names, opening + [response], cards)
                        for i, (response, cards) in enumerate(responses)
                    ])
                    result = metric_for(table_format).compute(dataset, {"action": action, **options})
                    self.assertEqual(result["event_counts"], counts)
                    for event, labels in combos.items():
                        with self.subTest(event=event):
                            stat = result[event]
                            self.assertEqual(stat["count"] if isinstance(stat, dict) else stat, counts[event])
                            self.assertEqual(result["hand_details"][event], {
                                "count": len(labels),
                                "hands": [{"hand": label, "count": 1, "pct": 100.0 / len(labels)}
                                          for label in labels],
                            })


if __name__ == "__main__":
    unittest.main()
