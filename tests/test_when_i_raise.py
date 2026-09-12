import unittest
from dataclasses import replace
from datetime import datetime

from poker.metrics.when_i_raise import WhenIRaiseMetric, extract_hero_raise_spots, hand_matches_raise_options
from poker.models import Action, Hand, HandDataset
from poker.positions.six_max import POSITION_ORDER


class WhenIRaiseTests(unittest.TestCase):
    def test_size_boundaries_and_general_selection(self) -> None:
        categories = ["small", "medium", "large", "overbet"]
        cases = (
            (20, "small"), (40, "small"),
            (40.01, "medium"), (50, "medium"), (60, "medium"),
            (60.01, "large"), (75, "large"), (99, "large"),
            (99.01, "overbet"), (100, "overbet"), (110, "overbet"), (150, "overbet"),
            # General must bypass size matching, including nonpositive sizes.
            (0, None),
        )
        metric = WhenIRaiseMetric()
        for size, category in cases:
            with self.subTest(size=size):
                hand = Hand(
                    hand_id="size-filter", datetime=datetime(2026, 9, 7),
                    table_name="Size filter", stakes="0.5/1", max_players=2,
                    hero_seat=1, hero_cards=None, hero_invested=0, hero_collected=0,
                    hero_returned=0, total_pot=0, rake=0, jackpot=0, bingo=0,
                    fortune=0, tax=0, source_file="size-filter.txt", button_seat=1,
                    seat_names={1: "Hero", 2: "Villain"},
                    actions=[
                        Action("flop", "Hero", "bet", amount=size, pot_before=100, is_hero=True),
                        Action("flop", "Villain", "fold"),
                    ],
                )
                dataset = HandDataset([hand])
                general = metric.compute(dataset)
                self.assertEqual(general["spot_count"], 1)
                self.assertEqual(general["options"]["sizes"], categories)
                self.assertEqual(metric.compute(dataset, {"sizes": categories}), general)
                selections = [[key] for key in categories] + [
                    ["small", "medium"], ["large", "overbet"], categories, [],
                ]
                for selected in selections:
                    with self.subTest(selected=selected):
                        matches = selected == categories or category in selected
                        options = {"sizes": selected}
                        result = metric.compute(dataset, options)
                        self.assertEqual(result["spot_count"], int(matches))
                        self.assertEqual(result["hand_count"], int(matches))
                        self.assertEqual(hand_matches_raise_options(hand, options), matches)

    def test_opponent_grid_counts_matching_heads_up_hands(self) -> None:
        base = Hand(
            hand_id="known", datetime=datetime(2026, 9, 7),
            table_name="Showdown grid", stakes="0.5/1", max_players=3,
            hero_seat=1, hero_cards=None, hero_invested=0, hero_collected=0,
            hero_returned=0, total_pot=0, rake=0, jackpot=0, bingo=0,
            fortune=0, tax=0, source_file="grid.txt", button_seat=1,
            seat_names={1: "Hero", 2: "Villain", 3: "Folded"},
            actions=[
                Action("preflop", "Folded", "fold"),
                Action("flop", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
                Action("flop", "Villain", "call", amount=50),
            ],
        )
        hands = []
        for i in range(10):
            cards = {"Folded": ("Qd", "Qs"), "Hero": ("Ac", "Ad")}
            if i < 2:
                cards["Villain"] = ("As", "Ks")
            elif i == 2:
                cards["Villain"] = ("Ah", "Qc")
            elif i == 3:
                cards["Villain"] = ("As", "As")  # Unusable cards stay unassigned.
            hands.append(replace(base, hand_id=str(i), shown_cards=cards))
        hands[0] = replace(hands[0], actions=base.actions + [
            Action("turn", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
            Action("turn", "Villain", "fold"),
        ])
        # These revealed hands must not enter the heads-up/Medium grid.
        hands.append(replace(base, hand_id="multiway", actions=base.actions[1:],
                             shown_cards={"Villain": ("Qd", "Qs")}))
        hands.append(replace(base, hand_id="overbet", shown_cards={"Villain": ("Qd", "Qs")},
                             actions=[base.actions[0], replace(base.actions[1], amount=150)]))
        dataset = HandDataset(hands)
        metric = WhenIRaiseMetric()
        options = {"player_counts": ["2"], "sizes": ["medium"]}
        result = metric.compute(dataset, options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (11, 10))
        self.assertEqual(result["all_fold"], {"count": 1, "pct": 9.09})
        self.assertEqual(result["call"], {"count": 10, "pct": 90.91})
        self.assertEqual(result["reraise"], {"count": 0, "pct": 0.0})
        grid = result["opponent_showdown_grid"]
        self.assertTrue(grid["supported"])
        self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (10, 3))
        cells = {cell["hand"]: cell for cell in grid["cells"]}
        self.assertEqual(len(cells), 169)
        self.assertEqual([grid["cells"][i]["hand"] for i in (0, 1, 13, 14, 168)],
                         ["AA", "AKs", "AKo", "KK", "22"])
        self.assertEqual({key: cell for key, cell in cells.items() if cell["count"]}, {
            "AKs": {"hand": "AKs", "count": 2, "pct": 20.0},
            "AQo": {"hand": "AQo", "count": 1, "pct": 10.0},
        })
        empty = metric.compute(dataset, {**options, "streets": ["river"]})["opponent_showdown_grid"]
        self.assertTrue(empty["supported"])
        self.assertEqual((empty["total_hands"], empty["revealed_hands"]), (0, 0))
        self.assertEqual(len(empty["cells"]), 169)
        self.assertTrue(all(cell["count"] == 0 and cell["pct"] == 0 for cell in empty["cells"]))
        for selection, spot_count, hand_count in ((None, 12, 11), (["3+"], 1, 1),
                                                  (["2", "3+"], 12, 11), ([], 0, 0)):
            with self.subTest(selection=selection):
                opts = {"sizes": ["medium"]}
                if selection is not None:
                    opts["player_counts"] = selection
                result = metric.compute(dataset, opts)
                self.assertEqual((result["spot_count"], result["hand_count"]), (spot_count, hand_count))
                self.assertEqual(result["opponent_showdown_grid"],
                                 {"supported": False, "reason": "heads_up_only"})

    def test_exact_heads_up_positions_and_legacy_fallback(self) -> None:
        seats = {1: "BTN", 2: "SB", 3: "BB", 4: "UTG", 5: "HJ", 6: "CO"}
        hands = []
        for hero, opponent in (("BTN", "BB"), ("CO", "BB"), ("BTN", "SB"),
                               ("HJ", "BB"), ("BB", "BTN")):
            names = {seat: "Hero" if pos == hero else "Villain" if pos == opponent else pos
                     for seat, pos in seats.items()}
            hand = Hand(
                hand_id=f"{hero}-{opponent}", datetime=datetime(2026, 9, 7),
                table_name="Exact positions", stakes="0.5/1", max_players=6,
                hero_seat=next(seat for seat, name in names.items() if name == "Hero"),
                hero_cards=None, hero_invested=0, hero_collected=0, hero_returned=0,
                total_pot=0, rake=0, jackpot=0, bingo=0, fortune=0, tax=0,
                source_file="positions.txt", button_seat=1, seat_names=names,
                shown_cards={"Villain": ("As", "Ks")},
                actions=[Action("preflop", name, "fold") for name in names.values()
                         if name not in ("Hero", "Villain")] + [
                    Action("flop", "Hero", "bet", amount=50, pot_before=100, is_hero=True),
                    Action("flop", "Villain", "call", amount=50),
                    Action("turn", "Hero", "bet", amount=75, pot_before=200, is_hero=True),
                    Action("turn", "Villain", "fold"),
                ],
            )
            hands.append(hand)
            self.assertEqual([(s.hero_position, s.opponent_position)
                              for s in extract_hero_raise_spots(hand)], [(hero, opponent)] * 2)
        metric = WhenIRaiseMetric()
        all_positions = list(POSITION_ORDER)
        exact = {"hero_positions": ["BTN"], "opponent_positions": ["BB"]}
        cases = (
            (exact, {"BTN-BB"}),
            ({**exact, "hero_positions": ["CO", "BTN"]}, {"CO-BB", "BTN-BB"}),
            ({**exact, "opponent_positions": all_positions}, {"BTN-BB", "BTN-SB"}),
            ({**exact, "hero_positions": all_positions}, {"BTN-BB", "CO-BB", "HJ-BB"}),
            ({"hero_positions": all_positions, "opponent_positions": all_positions},
             {hand.hand_id for hand in hands}),
            ({"positions": ["IP"]}, {"BTN-BB", "CO-BB", "BTN-SB", "HJ-BB"}),
            ({"positions": ["OOP"]}, {"BB-BTN"}),
            ({**exact, "positions": ["OOP"]}, {"BTN-BB"}),  # Ignore the inactive legacy axis.
        )
        for filters, expected in cases:
            with self.subTest(filters=filters):
                options = {"player_counts": ["2"], **filters}
                result = metric.compute(HandDataset(hands), options)
                self.assertEqual({h.hand_id for h in hands if hand_matches_raise_options(h, options)}, expected)
                self.assertEqual((result["spot_count"], result["hand_count"]), (2 * len(expected), len(expected)))
                grid = result["opponent_showdown_grid"]
                self.assertEqual((grid["total_hands"], grid["revealed_hands"]), (len(expected), len(expected)))
                self.assertEqual(next(c for c in grid["cells"] if c["hand"] == "AKs"),
                                 {"hand": "AKs", "count": len(expected), "pct": 100.0})
        # Exact matching uses the same street/size filters as the other statistics.
        options = {"player_counts": ["2"], **exact, "streets": ["turn"], "sizes": ["small"]}
        result = metric.compute(HandDataset(hands), options)
        self.assertEqual((result["spot_count"], result["hand_count"]), (1, 1))
        self.assertEqual(result["all_fold"], {"count": 1, "pct": 100.0})
        multiway = replace(hands[0], actions=[a for a in hands[0].actions if a.player != "SB"])
        self.assertFalse(hand_matches_raise_options(multiway, options))
        for fallback in (replace(hands[0], max_players=9), multiway):
            with self.subTest(max_players=fallback.max_players):
                self.assertTrue(all(s.hero_position is None and s.opponent_position is None
                                    for s in extract_hero_raise_spots(fallback)))
                for relative, expected in (("IP", True), ("OOP", False)):
                    opts = {"player_counts": ["2"] if fallback.max_players == 9 else ["2", "3+"],
                            "positions": [relative], "hero_positions": ["SB"], "opponent_positions": ["HJ"]}
                    self.assertEqual(hand_matches_raise_options(fallback, opts), expected)
        unresolved = replace(hands[0], button_seat=None)
        self.assertFalse(hand_matches_raise_options(unresolved, {"player_counts": ["2"], **exact}))
        self.assertTrue(hand_matches_raise_options(unresolved, {
            "player_counts": ["2"], "hero_positions": all_positions, "opponent_positions": all_positions,
        }))


if __name__ == "__main__":
    unittest.main()
