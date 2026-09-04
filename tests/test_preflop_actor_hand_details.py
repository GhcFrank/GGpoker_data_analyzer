from __future__ import annotations

import unittest
from datetime import datetime

from poker.metrics.preflop_analysis import (
    PreflopAnalysisMetric,
    extract_3bet as extract_3bet_6max,
)
from poker.metrics.preflop_analysis_9max import (
    PreflopAnalysis9MaxMetric,
    extract_3bet as extract_3bet_9max,
)
from poker.models import Action, Hand, HandDataset
from poker.parser import parse_hand


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

    def test_open_faced_3bet_uses_only_first_raiser_for_6max_and_9max(self) -> None:
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
                result = metric_for(table_format).compute(
                    HandDataset([known, unknown]),
                    {"action": "open_raise", "hero_position": "CO"},
                )

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
                self.assertNotIn(
                    "KK",
                    {row["hand"] for row in result["hand_details"]["faced_3bet"]["hands"]},
                )
                self.assertNotIn("all_fold", result["hand_details"])

    def test_cold_4bet_keeps_cold_4bettor_identity_and_combo(self) -> None:
        for table_format, extractor in (
            ("6max", extract_3bet_6max),
            ("9max", extract_3bet_9max),
        ):
            with self.subTest(table_format=table_format):
                names = {"HJ": "Opener", "CO": "Hero", "BTN": "Cold Fourbettor"}
                hand = make_hand(
                    "cold-fourbet",
                    table_format,
                    names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Hero", 8),
                        raise_to("Cold Fourbettor", 22),
                        act("Opener", "fold"),
                    ],
                    {
                        "Opener": ("Ac", "Ad"),
                        "Cold Fourbettor": ("As", "5s"),
                    },
                    site="coinpoker",
                )

                spot = extractor(hand, "CO", "HJ")
                self.assertIsNotNone(spot)
                assert spot is not None
                self.assertTrue(spot.cold_4bet)
                self.assertEqual(spot.cold_4bettor, "Cold Fourbettor")
                self.assertEqual(spot.cold_4bettor_position, "BTN")
                self.assertEqual(spot.cold_4bet_combo, "A5s")

                result = metric_for(table_format).compute(
                    HandDataset([hand]),
                    {"action": "3bet", "hero_position": "CO", "opener_position": "HJ"},
                )
                self.assertEqual(result["cold_4bet"]["count"], 1)
                self.assertEqual(
                    result["hand_details"]["cold_4bet"],
                    {"count": 1, "hands": [{"hand": "A5s", "count": 1, "pct": 100.0}]},
                )
                self.assertNotIn(
                    "AA",
                    {row["hand"] for row in result["hand_details"]["cold_4bet"]["hands"]},
                )

    def test_3bet_response_details_and_multiway_all_fold_exclusion(self) -> None:
        names = {"HJ": "Opener", "CO": "Hero", "BTN": "Button", "SB": "Small", "BB": "Big"}
        call_hand = make_hand(
            "opener-call",
            "6max",
            names,
            [raise_to("Opener", 2.5), raise_to("Hero", 8), act("Opener", "call")],
            {"Opener": ("Ah", "Kd")},
        )
        fourbet_hand = make_hand(
            "opener-fourbet",
            "6max",
            names,
            [raise_to("Opener", 2.5), raise_to("Hero", 8), raise_to("Opener", 22)],
            {"Opener": ("Qc", "Qd")},
        )
        all_fold_hand = make_hand(
            "all-fold",
            "6max",
            names,
            [
                raise_to("Opener", 2.5),
                raise_to("Hero", 8),
                act("Button", "fold"),
                act("Small", "fold"),
                act("Big", "fold"),
                act("Opener", "fold"),
            ],
        )
        result = PreflopAnalysisMetric().compute(
            HandDataset([call_hand, fourbet_hand, all_fold_hand]),
            {"action": "3bet", "hero_position": "CO", "opener_position": "HJ"},
        )

        self.assertEqual(result["opener_call"]["count"], 1)
        self.assertEqual(result["hand_details"]["opener_call"]["hands"][0]["hand"], "AKo")
        self.assertEqual(result["opener_4bet"]["count"], 1)
        self.assertEqual(result["hand_details"]["opener_4bet"]["hands"][0]["hand"], "QQ")
        self.assertEqual(result["opener_fold"]["count"], 1)
        self.assertEqual(result["hand_details"]["opener_fold"]["hands"][0]["hand"], "未知")
        self.assertEqual(result["all_fold"]["count"], 1)
        self.assertNotIn("all_fold", result["hand_details"])

    def test_4bet_and_5bet_actor_responses_use_common_details(self) -> None:
        for table_format in ("6max", "9max"):
            with self.subTest(table_format=table_format):
                fourbet_names = {
                    "HJ": "Opener",
                    "CO": "Threebettor",
                    "BTN": "Hero",
                    "SB": "Cold Fivebettor",
                }
                threebettor_call = make_hand(
                    "threebettor-call",
                    table_format,
                    fourbet_names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Threebettor", 8),
                        raise_to("Hero", 22),
                        act("Threebettor", "call"),
                    ],
                    {"Threebettor": ("Ac", "Kc")},
                )
                cold_fivebet = make_hand(
                    "cold-fivebet",
                    table_format,
                    fourbet_names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Threebettor", 8),
                        raise_to("Hero", 22),
                        raise_to("Cold Fivebettor", 55),
                    ],
                    {
                        "Threebettor": ("Ah", "Ad"),
                        "Cold Fivebettor": ("Qc", "Qd"),
                    },
                )
                fourbet_result = metric_for(table_format).compute(
                    HandDataset([threebettor_call, cold_fivebet]),
                    {"action": "4bet", "hero_position": "BTN", "threebettor_position": "CO"},
                )
                self.assertEqual(fourbet_result["threebettor_call"]["count"], 1)
                self.assertEqual(
                    fourbet_result["hand_details"]["threebettor_call"]["hands"][0]["hand"],
                    "AKs",
                )
                self.assertEqual(fourbet_result["threebettor_faced"], 1)
                self.assertEqual(
                    fourbet_result["hand_details"]["threebettor_faced"]["hands"][0]["hand"],
                    "AKs",
                )
                self.assertEqual(fourbet_result["faced_5bet"]["count"], 1)
                self.assertEqual(
                    fourbet_result["hand_details"]["faced_5bet"]["hands"][0]["hand"],
                    "QQ",
                )

                fivebet_names = {
                    "HJ": "Opener",
                    "CO": "Threebettor",
                    "BTN": "Fourbettor",
                    "SB": "Hero",
                }
                call_fivebet = make_hand(
                    "call-fivebet",
                    table_format,
                    fivebet_names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Threebettor", 8),
                        raise_to("Fourbettor", 22),
                        raise_to("Hero", 55),
                        act("Fourbettor", "call"),
                    ],
                    {"Fourbettor": ("As", "Kd")},
                )
                fold_fivebet = make_hand(
                    "fold-fivebet",
                    table_format,
                    fivebet_names,
                    [
                        raise_to("Opener", 2.5),
                        raise_to("Threebettor", 8),
                        raise_to("Fourbettor", 22),
                        raise_to("Hero", 55),
                        act("Fourbettor", "fold"),
                    ],
                )
                fivebet_result = metric_for(table_format).compute(
                    HandDataset([call_fivebet, fold_fivebet]),
                    {"action": "5bet", "hero_position": "SB", "fourbettor_position": "BTN"},
                )
                self.assertEqual(fivebet_result["fourbettor_call"]["count"], 1)
                self.assertEqual(
                    fivebet_result["hand_details"]["fourbettor_call"]["hands"][0]["hand"],
                    "AKo",
                )
                self.assertEqual(fivebet_result["fourbettor_fold"]["count"], 1)
                self.assertEqual(
                    fivebet_result["hand_details"]["fourbettor_fold"]["hands"][0]["hand"],
                    "未知",
                )
                self.assertEqual(fivebet_result["fourbettor_faced"], 2)
                self.assertEqual(
                    fivebet_result["hand_details"]["fourbettor_faced"]["count"],
                    2,
                )

    def test_actor_detail_counts_match_each_supported_stat(self) -> None:
        names = {"HJ": "Opener", "CO": "Hero"}
        hands = [
            make_hand(
                "site-gg",
                "6max",
                names,
                [raise_to("Opener", 2.5), raise_to("Hero", 8), act("Opener", "call")],
                {"Opener": ("As", "Qs")},
                site="ggpoker",
            ),
            make_hand(
                "site-coin",
                "6max",
                names,
                [raise_to("Opener", 2.5), raise_to("Hero", 8), act("Opener", "call")],
                {"Opener": ("Ah", "Qd")},
                site="coinpoker",
            ),
        ]
        result = PreflopAnalysisMetric().compute(
            HandDataset(hands),
            {"action": "3bet", "hero_position": "CO", "opener_position": "HJ"},
        )
        for stat_key, detail in result["hand_details"].items():
            with self.subTest(stat_key=stat_key):
                stat = result[stat_key]
                stat_count = stat["count"] if isinstance(stat, dict) else stat
                self.assertEqual(detail["count"], stat_count)
                self.assertEqual(sum(row["count"] for row in detail["hands"]), detail["count"])
        self.assertEqual(
            {row["hand"] for row in result["hand_details"]["opener_call"]["hands"]},
            {"AQs", "AQo"},
        )


if __name__ == "__main__":
    unittest.main()
